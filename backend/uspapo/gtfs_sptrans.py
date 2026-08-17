"""Motor de horários sobre o recorte GTFS oficial da SPTrans.

Este módulo é a camada de dados da ferramenta de transporte, como o
``ferramentas/jupiter.py`` é a dos dois consumidores do JupiterWeb: ele não se
registra como ferramenta, não fala com a API Olho Vivo e não escreve prosa para
o aluno. Ele responde três perguntas sobre o arquivo ``dados_sptrans.json``:
quando uma linha passa numa parada, quais linhas atendem uma parada e qual é o
melhor ônibus direto entre dois pontos.

O recorte é gerado diariamente por ``scripts/atualizar_gtfs_sptrans.py`` e vive
versionado no repositório: o servidor nunca baixa os 14 MB do feed no cold
start. A seleção é geográfica, por uma caixa em volta da Cidade Universitária,
que o próprio arquivo publica em ``criterio`` — é dela que sai a regra de
"trajeto interno" mais abaixo, sem repetir a caixa aqui.

Duas semânticas do GTFS são fáceis de errar e custam caro ao aluno:

* ``frequencies.txt`` com ``exact_times=0`` descreve uma JANELA com intervalo
  esperado, não uma grade de partidas. Nenhum múltiplo de ``headway_secs`` pode
  virar horário cravado, e a espera esperada dentro de uma janela é meio
  intervalo — nunca zero. A SPTrans publica essas janelas como
  ``[inicio, inicio+3540]``, deixando 60 segundos de lacuna entre uma e a
  seguinte; tratar essa lacuna como "sem faixa" fazia o instante que caísse nela
  valer uma espera de segundos, e era isso que embaralhava o ranking de rotas.
* horários acima de 24:00 pertencem ao dia de serviço anterior. À 00:30, uma
  viagem 24:45 de sexta ainda é uma passagem futura no sábado civil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from uspapo.ferramentas import casa, normalizar
from uspapo.locais_usp import CATALOGO_LOCAIS, coordenada_local, resolver_local

FONTE = "https://www.sptrans.com.br/desenvolvedores/"
ARQUIVO = Path(__file__).resolve().parent / "dados_sptrans.json"

try:
    FUSO_SP = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # pragma: no cover - imagens Windows sem tzdata
    FUSO_SP = timezone(timedelta(hours=-3))

# Uma correspondência por coordenada só é válida quando há de fato uma parada
# caminhável perto do local pedido. Antes, o ponto globalmente mais próximo era
# aceito sem teto: uma linha que não atende o Metrô Butantã podia ser anunciada
# usando uma parada a mais de meio quilômetro dali.
RAIO_ACESSO_M = 450
# O pipeline atualiza o recorte diariamente. Depois de uma semana sem uma
# geração bem-sucedida, a resposta continua útil, mas passa a avisar claramente
# que o dado está vencido em vez de aparentar atualidade.
MAX_IDADE_DIAS = 7
# Ninguém planeja o dia com um ônibus que só passa daqui a mais de hora e meia.
# Sem este teto, um domingo devolvia a 8084 "em cerca de 618 minutos" como
# alternativa, porque a próxima partida programada era na segunda de manhã.
MAX_ESPERA_MIN = 90
VELOCIDADE_CAMINHADA_M_MIN = 80
# Ruas e calçadas raramente seguem a linha reta; 15% é uma aproximação
# conservadora para decidir apenas se vale caminhar em vez de esperar.
FATOR_PERCURSO_A_PE = 1.15


# ─────────────────────────────────────────────
# Catálogo
# ─────────────────────────────────────────────
@lru_cache(maxsize=1)
def catalogo() -> dict[str, Any]:
    """Carrega o pequeno recorte oficial gerado por atualizar_gtfs_sptrans.py."""
    try:
        with ARQUIVO.open(encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        return dados if isinstance(dados, dict) else {}
    except (OSError, json.JSONDecodeError) as erro:
        print(f"[gtfs] não foi possível ler o recorte: {type(erro).__name__}: {erro}")
        return {}


def limpar_caches() -> None:
    """Descarta a memoização do módulo; usado por testes que trocam o recorte."""
    catalogo.cache_clear()
    _coordenada_por_nome.cache_clear()
    _caixa_campus.cache_clear()


def nota_atualizacao(agora: datetime | None = None) -> str:
    """Expõe a idade do snapshot; dado estático nunca deve parecer "ao vivo"."""
    texto_gerado = str(catalogo().get("gerado_em") or "").strip()
    if not texto_gerado:
        return "A data de atualização do recorte GTFS não está disponível."
    try:
        gerado = datetime.fromisoformat(texto_gerado.replace("Z", "+00:00"))
        if gerado.tzinfo is None:
            gerado = gerado.replace(tzinfo=timezone.utc)
        referencia = agora or datetime.now(timezone.utc)
        if referencia.tzinfo is None:
            referencia = referencia.replace(tzinfo=timezone.utc)
        idade_dias = max(0, (referencia - gerado).days)
        local = gerado.astimezone(FUSO_SP)
    except (TypeError, ValueError, OverflowError):
        return "A data de atualização do recorte GTFS é inválida."

    nota = (
        "Recorte GTFS oficial gerado em "
        f"{local.strftime('%d/%m/%Y às %H:%M')} (horário de São Paulo)."
    )
    if idade_dias > MAX_IDADE_DIAS:
        nota += (
            f" **Atenção:** ele está há {idade_dias} dias sem atualização; "
            "confirme o itinerário na SPTrans."
        )
    return nota


def aviso_se_necessario(agora: datetime | None = None) -> str:
    """Só leva a idade do feed à UX quando ela realmente exige atenção."""
    nota = nota_atualizacao(agora)
    problemas = ("**Atenção:**", "não está disponível", "é inválida")
    return nota if any(problema in nota for problema in problemas) else ""


def rotas_do_recorte() -> list[tuple[str, str]]:
    """Todas as variantes de linha presentes no recorte, em ordem de número."""
    return sorted(
        (
            (str(rota.get("linha", "")), str(rota.get("nome", "")))
            for rotas in catalogo().get("linhas", {}).values()
            for rota in rotas
        ),
        key=lambda item: normalizar(item[0]),
    )


def _rotas_da_linha(numero: str) -> list[dict[str, Any]]:
    return catalogo().get("linhas", {}).get(normalizar(numero).upper(), [])


# ─────────────────────────────────────────────
# Calendário de serviço
# ─────────────────────────────────────────────
def servico_ativo(dados: dict[str, Any], servico: str, dia: date) -> bool:
    """Se um ``service_id`` opera numa data, com calendar_dates tendo prioridade."""
    data_gtfs = dia.strftime("%Y%m%d")
    excecao = (
        dados.get("excecoes_calendario", {}).get(servico, {}).get(data_gtfs)
    )
    if excecao is not None:
        # GTFS: 1 adiciona o serviço naquela data; 2 o remove.
        return int(excecao) == 1

    calendario = dados.get("calendarios", {}).get(servico)
    if not isinstance(calendario, dict):
        return False
    dias = calendario.get("dias", [])
    return (
        calendario.get("inicio", "99999999") <= data_gtfs
        <= calendario.get("fim", "00000000")
        and len(dias) == 7
        and bool(dias[dia.weekday()])
    )


# ─────────────────────────────────────────────
# Geografia e casamento de paradas
# ─────────────────────────────────────────────
def mesmo_nome(pedido: str, alvo: str) -> bool:
    """Equivalência lexical explicável, sem o falso positivo por prefixo.

    ``casa`` é intencionalmente permissiva e serve bem para busca. Para
    identidade de parada, porém, ela fazia "Poli" casar com "Academia de
    Polícia", "FAU" com "Faustolo" e "IP" com "Ipiranga". Exigir o casamento
    nos dois sentidos conserva variações de caixa/acentos/conectivos, mas não
    aceita que sobrem palavras semanticamente importantes em apenas um lado.
    """
    return casa(pedido, alvo) and casa(alvo, pedido)


def distancia_m(parada: dict[str, Any], coordenada: tuple[float, float]) -> float:
    """Distância local aproximada em metros, suficiente para ordenar paradas."""
    lat, lon = coordenada
    dy = (float(parada.get("latitude", 0)) - lat) * 111_320
    dx = (float(parada.get("longitude", 0)) - lon) * 111_320 * math.cos(
        math.radians(lat)
    )
    return math.hypot(dx, dy)


@lru_cache(maxsize=1)
def _caixa_campus() -> dict[str, float] | None:
    """A caixa de seleção que o próprio recorte declara ter usado."""
    criterio = catalogo().get("criterio")
    if not isinstance(criterio, dict):
        return None
    limites = criterio.get("linhas_com_parada_na_area_do_campus")
    if not isinstance(limites, dict):
        return None
    try:
        return {chave: float(limites[chave]) for chave in (
            "latitude_min", "latitude_max", "longitude_min", "longitude_max",
        )}
    except (KeyError, TypeError, ValueError):
        return None


def dentro_do_campus(coordenada: tuple[float, float] | None) -> bool:
    """Se um ponto cai na área de seleção do recorte.

    A regra é geográfica de propósito. Ela já foi um teste de pertencimento ao
    catálogo manual de locais, e por isso desligava sozinha assim que uma das
    pontas era um nome de rua em texto livre — justamente quando a regressão do
    desvio até o terminal voltava a aparecer.
    """
    limites = _caixa_campus()
    if not limites or not coordenada:
        return False
    latitude, longitude = coordenada
    return (
        limites["latitude_min"] <= latitude <= limites["latitude_max"]
        and limites["longitude_min"] <= longitude <= limites["longitude_max"]
    )


def _centro_campus() -> tuple[float, float] | None:
    limites = _caixa_campus()
    if not limites:
        return None
    return (
        (limites["latitude_min"] + limites["latitude_max"]) / 2,
        (limites["longitude_min"] + limites["longitude_max"]) / 2,
    )


@lru_cache(maxsize=256)
def _coordenada_por_nome(ponto: str) -> tuple[float, float] | None:
    """Coordenada de um nome de parada que não está no catálogo manual.

    A média entre plataformas/lados da via representa o local, não o embarque;
    o planejador escolhe depois o lado e o sentido corretos. O nome, porém, pode
    se repetir em bairros distantes ("Terminal", "Igreja"), e a média de dois
    grupos afastados cai no meio do nada, longe dos dois. Por isso ancoramos no
    grupo mais próximo do campus — que é o que o aluno da USP está perguntando —
    e ignoramos as homônimas fora dele.
    """
    paradas: dict[str, dict[str, Any]] = {}
    for rotas in catalogo().get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    if mesmo_nome(ponto, parada.get("nome", "")):
                        paradas[str(parada.get("id"))] = parada
    if not paradas:
        return None

    centro = _centro_campus()
    candidatas = list(paradas.values())
    if centro:
        ancora = min(candidatas, key=lambda item: distancia_m(item, centro))
        alvo = (float(ancora["latitude"]), float(ancora["longitude"]))
        candidatas = [
            parada for parada in candidatas
            if distancia_m(parada, alvo) <= RAIO_ACESSO_M * 2
        ]
    return (
        sum(float(p["latitude"]) for p in candidatas) / len(candidatas),
        sum(float(p["longitude"]) for p in candidatas) / len(candidatas),
    )


def coordenada_do_ponto(ponto: str) -> tuple[float, float] | None:
    """Coordenada de um local do catálogo ou de um nome de parada do GTFS."""
    return coordenada_local(ponto) or _coordenada_por_nome(str(ponto))


def chave_local(ponto: str) -> str | None:
    return ponto if ponto in CATALOGO_LOCAIS else resolver_local(ponto)


# ─────────────────────────────────────────────
# Espera programada
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class EsperaProgramada:
    """Quanto se espera no ponto, com os limites que a fonte realmente sustenta.

    ``intervalo_s`` é ``None`` quando a espera veio de uma grade de partidas
    exatas: aí mínimo, esperado e máximo coincidem, porque o horário é um só.
    """

    esperada_s: float
    minima_s: float
    maxima_s: float
    intervalo_s: float | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.minima_s <= self.esperada_s <= self.maxima_s:
            raise ValueError("espera programada fora de seus limites")


def _faixa_vigente(
    viagem: dict[str, Any], parada: dict[str, Any], segundos_servico: float
) -> tuple[int, int, int] | None:
    """A primeira janela de headway que ainda não terminou nesta parada.

    Janelas com ``exact_times=1`` ficam de fora: elas são grade de partidas e
    têm tratamento próprio em ``proxima_partida_exata``.
    """
    deslocamento = int(parada.get("deslocamento", 0))
    melhor: tuple[int, int, int] | None = None
    for frequencia in viagem.get("frequencias", []):
        if int(frequencia.get("exact_times", 0)) == 1:
            continue
        inicio = int(frequencia["inicio"]) + deslocamento
        fim = int(frequencia["fim"]) + deslocamento
        if fim <= segundos_servico:
            continue
        if melhor is None or inicio < melhor[0]:
            melhor = (inicio, fim, int(frequencia["intervalo"]))
    return melhor


def espera_por_frequencia(
    dados: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    pronto: datetime,
) -> EsperaProgramada | None:
    """Espera esperada numa janela de headway, contínua nas bordas das janelas.

    Dentro da janela, a espera esperada de quem chega em um instante qualquer é
    meio intervalo. Se a janela ainda vai abrir, soma-se o tempo até a abertura:
    é o que evita que os 60 segundos de lacuna entre duas janelas do feed virem
    "o próximo ônibus passa em 40 segundos" — um artefato de formatação do
    arquivo que vencia o ranking do planejador e trocava a linha recomendada a
    cada minuto.
    """
    servico = str(viagem.get("servico", ""))
    # Duas voltas: a viagem que serve este instante pode ter começado no dia de
    # serviço anterior e atravessado a meia-noite.
    for recuo in (1, 0):
        dia_servico = pronto.date() - timedelta(days=recuo)
        if not servico_ativo(dados, servico, dia_servico):
            continue
        meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
        segundos_servico = (pronto - meia_noite).total_seconds()
        faixa = _faixa_vigente(viagem, parada, segundos_servico)
        if faixa is None:
            continue
        inicio, fim, intervalo = faixa
        ate_abrir = max(0.0, inicio - segundos_servico)
        return EsperaProgramada(
            esperada_s=ate_abrir + intervalo / 2,
            minima_s=ate_abrir,
            maxima_s=ate_abrir + intervalo,
            intervalo_s=float(intervalo),
        )
    return None


def proxima_partida_exata(
    dados: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    depois_de: datetime,
) -> datetime | None:
    """Próxima partida de uma grade exata: ``exact_times=1`` ou stop_times.

    Nunca é usada para ``exact_times=0``. Uma janela de headway não tem partida
    cravada, e tratar o início dela como "o ônibus passa agora" era o mesmo bug
    de espera zero visto pelo outro lado.
    """
    deslocamento = int(parada.get("deslocamento", 0))
    melhor: datetime | None = None
    for dias_a_frente in range(-1, 8):
        dia_servico = depois_de.date() + timedelta(days=dias_a_frente)
        if not servico_ativo(dados, str(viagem.get("servico", "")), dia_servico):
            continue
        meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
        exatas = [
            frequencia for frequencia in viagem.get("frequencias", [])
            if int(frequencia.get("exact_times", 0)) == 1
        ]
        if exatas:
            for frequencia in exatas:
                for partida in range(
                    int(frequencia["inicio"]),
                    int(frequencia["fim"]),
                    int(frequencia["intervalo"]),
                ):
                    passagem = meia_noite + timedelta(
                        seconds=partida + deslocamento
                    )
                    if passagem >= depois_de and (
                        melhor is None or passagem < melhor
                    ):
                        melhor = passagem
        elif not viagem.get("frequencias"):
            passagem = meia_noite + timedelta(seconds=int(parada["horario"]))
            if passagem >= depois_de and (melhor is None or passagem < melhor):
                melhor = passagem
    return melhor


def espera_no_ponto(
    dados: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    pronto: datetime,
) -> EsperaProgramada | None:
    """A espera desta viagem nesta parada, pela semântica correta da fonte."""
    por_frequencia = espera_por_frequencia(dados, viagem, parada, pronto)
    if por_frequencia is not None:
        return por_frequencia
    proxima = proxima_partida_exata(dados, viagem, parada, pronto)
    if proxima is None:
        return None
    segundos = (proxima - pronto).total_seconds()
    return EsperaProgramada(
        esperada_s=segundos, minima_s=segundos, maxima_s=segundos
    )


# ─────────────────────────────────────────────
# Programação de passagens numa parada
# ─────────────────────────────────────────────
def _candidatos_na_parada(
    numero: str, ponto: str, sentido_esperado: str | None
) -> dict[str, Any]:
    """Escolhe UM stop_id e devolve todas as viagens que o atendem."""
    rotas = _rotas_da_linha(numero)
    if not rotas:
        return {
            "erro": (
                f"A linha {numero} não aparece no recorte oficial atual da "
                "SPTrans. Ela pode ter sido desativada, renumerada ou não "
                "atender a área da USP. NÃO conclua que a linha não existe: "
                "avise o aluno e sugira conferir o número."
            )
        }

    todas: list[tuple[dict, dict, dict]] = []
    candidatos: list[tuple[dict, dict, dict]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                item = (rota, viagem, parada)
                todas.append(item)
                if mesmo_nome(ponto, str(parada.get("nome", ""))):
                    candidatos.append(item)

    if sentido_esperado:
        def atende_sentido(item: tuple[dict, dict, dict]) -> bool:
            return normalizar(item[1].get("destino", "")) == normalizar(
                sentido_esperado
            )

        todas = [item for item in todas if atende_sentido(item)]
        candidatos = [item for item in candidatos if atende_sentido(item)]
        if not todas:
            # Silenciar o filtro devolvia a programação do sentido OPOSTO com o
            # rótulo do sentido pedido. Melhor não responder do que responder o
            # ônibus que vai para o outro lado.
            return {
                "erro": (
                    f"A linha {numero} não tem, no recorte oficial, nenhuma "
                    f"viagem no sentido '{sentido_esperado}'. NÃO responda com "
                    "o outro sentido: confirme com o aluno para onde ele quer ir."
                )
            }

    coordenada = coordenada_do_ponto(ponto)
    if not candidatos and coordenada and todas:
        # Inclui a mesma parada em diferentes viagens/sentidos, mas não uma
        # parada distante apenas porque é a mais próxima que a linha tem. O teto
        # é o que impede, por exemplo, anunciar a 7725 no Metrô Butantã usando
        # uma parada da Av. Afrânio Peixoto.
        menor = min(distancia_m(item[2], coordenada) for item in todas)
        if menor <= RAIO_ACESSO_M:
            candidatos = [
                item for item in todas
                if distancia_m(item[2], coordenada)
                <= min(menor + 40, RAIO_ACESSO_M)
            ]
    if not candidatos:
        return {
            "erro": (
                f"Não localizei no recorte oficial uma parada da linha {numero} "
                f"que corresponda a '{ponto}'. NÃO conclua que a linha não passa "
                "por lá: peça ao aluno o nome da parada como aparece na placa, "
                "ou o instituto mais próximo."
            )
        }

    # A busca geográfica pode encontrar vários pontos próximos. Misturar as
    # faixas de todos eles e rotular o resultado com apenas o primeiro nome
    # produzia uma tabela impossível de auditar. A programação pertence sempre a
    # um único stop_id (a plataforma mais próxima); repetições desse mesmo ID em
    # viagens/serviços continuam sendo combinadas.
    if coordenada:
        candidatos.sort(
            key=lambda item: (
                distancia_m(item[2], coordenada),
                str(item[2].get("id", "")),
            )
        )
    else:
        candidatos.sort(
            key=lambda item: (
                normalizar(str(item[2].get("nome", ""))),
                str(item[2].get("id", "")),
            )
        )
    escolhido = str(candidatos[0][2].get("id", ""))
    return {
        "parada_id": escolhido,
        "candidatos": [
            item for item in candidatos
            if str(item[2].get("id", "")) == escolhido
        ],
    }


def _texto_horario(valor: datetime, referencia: datetime) -> str:
    if valor.date() == referencia.date():
        return valor.strftime("%H:%M")
    return valor.strftime("%d/%m às %H:%M")


def programacao(
    numero: str,
    ponto: str,
    agora: datetime | None = None,
    sentido_esperado: str | None = None,
) -> dict[str, Any]:
    """Próximas passagens programadas de uma linha numa parada."""
    dados = catalogo()
    selecao = _candidatos_na_parada(numero, ponto, sentido_esperado)
    if selecao.get("erro"):
        return selecao
    parada_escolhida_id = str(selecao["parada_id"])
    candidatos = selecao["candidatos"]

    # Um mesmo stop_id pode aparecer nos dois sentidos da linha (especialmente
    # em terminais). Somar as faixas e imprimir apenas o headsign do primeiro
    # candidato atribui horários do sentido oposto ao rótulo errado. Sem um
    # sentido pedido, devolvemos blocos independentes e auditáveis.
    destinos = sorted(
        {
            str(item[1].get("destino", "")).strip()
            for item in candidatos
            if str(item[1].get("destino", "")).strip()
        },
        key=normalizar,
    )
    if not sentido_esperado and len(destinos) > 1:
        programacoes = [
            resultado for resultado in (
                programacao(numero, ponto, agora, sentido_esperado=destino)
                for destino in destinos
            )
            if not resultado.get("erro")
        ]
        if programacoes:
            return {
                "tipo": "programacao",
                "linha": programacoes[0].get("linha", numero),
                # O nome canônico da parada vem do GTFS. Repetir aqui o texto
                # que o aluno digitou fazia a resposta dizer "a parada metro
                # butanta" no cabeçalho e "Terminal Metrô Butantã" nos itens.
                "parada": programacoes[0].get("parada", ponto),
                "parada_id": parada_escolhida_id,
                "horarios": [],
                "instantes": [],
                "sentidos": programacoes,
            }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    chegadas: set[datetime] = set()
    faixas_frequencia: set[tuple[datetime, datetime, int]] = set()
    for _rota, viagem, parada in candidatos:
        deslocamento = int(parada.get("deslocamento", 0))
        for dias_a_frente in range(-1, 8):
            dia_servico = instante.date() + timedelta(days=dias_a_frente)
            if not servico_ativo(dados, str(viagem.get("servico", "")), dia_servico):
                continue
            meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
            frequencias = viagem.get("frequencias", [])
            if not frequencias:
                chegada = meia_noite + timedelta(seconds=int(parada["horario"]))
                if chegada >= instante - timedelta(seconds=30):
                    chegadas.add(chegada)
                continue
            for frequencia in frequencias:
                inicio = int(frequencia["inicio"])
                fim = int(frequencia["fim"])
                intervalo = int(frequencia["intervalo"])
                if int(frequencia.get("exact_times", 0)) == 1:
                    for partida in range(inicio, fim, intervalo):
                        chegada = meia_noite + timedelta(
                            seconds=partida + deslocamento
                        )
                        if chegada >= instante - timedelta(seconds=30):
                            chegadas.add(chegada)
                    continue
                inicio_ponto = meia_noite + timedelta(
                    seconds=inicio + deslocamento
                )
                fim_ponto = meia_noite + timedelta(seconds=fim + deslocamento)
                if fim_ponto > instante:
                    faixas_frequencia.add((inicio_ponto, fim_ponto, intervalo))

    proximas = sorted(chegadas)[:3]
    faixas = sorted(faixas_frequencia)[:3]
    if not proximas and not faixas:
        return {
            "erro": (
                f"A linha {numero} não tem passagem programada em '{ponto}' no "
                "período coberto pelo recorte oficial. Avise o aluno e sugira "
                "conferir o horário na SPTrans."
            )
        }

    rota, viagem_escolhida, parada = candidatos[0]
    resultado: dict[str, Any] = {
        "tipo": "programacao",
        "linha": rota.get("linha", numero),
        "parada": parada.get("nome", ponto),
        "parada_id": parada_escolhida_id,
        "destino": viagem_escolhida.get("destino", ""),
        "horarios": [
            _texto_horario(chegada, instante) for chegada in proximas
        ],
        "instantes": [chegada.isoformat() for chegada in proximas],
    }
    if faixas:
        resultado["faixas"] = [
            _faixa_publica(inicio, fim, intervalo, instante)
            for inicio, fim, intervalo in faixas
        ]
    return resultado


def _faixa_publica(
    inicio: datetime, fim: datetime, intervalo: int, instante: datetime
) -> dict[str, Any]:
    """Descreve uma janela de headway sem transformá-la em partida cravada.

    ``exact_times=0`` não autoriza cravar os múltiplos do headway como partidas.
    Ainda assim, o headway permite responder de maneira útil: se a janela está
    aberta, a próxima passagem é esperada em até um intervalo; se ela ainda vai
    abrir, a janela parte do início publicado. A referência central é uma
    estimativa, nunca um horário garantido.
    """
    janela_inicio = max(instante, inicio)
    janela_fim = min(janela_inicio + timedelta(seconds=intervalo), fim)
    referencia = janela_inicio + (janela_fim - janela_inicio) / 2
    return {
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "inicio_texto": _texto_horario(inicio, instante),
        "fim_texto": _texto_horario(fim, instante),
        "intervalo_min": round(intervalo / 60),
        "ativa_agora": inicio <= instante < fim,
        "proxima_janela_inicio": janela_inicio.isoformat(),
        "proxima_janela_fim": janela_fim.isoformat(),
        "proxima_janela_inicio_texto": _texto_horario(janela_inicio, instante),
        "proxima_janela_fim_texto": _texto_horario(janela_fim, instante),
        "proxima_referencia": referencia.isoformat(),
        "proxima_referencia_texto": _texto_horario(referencia, instante),
        # Metade do headway é a espera típica dentro de uma faixa. O tempo desde
        # agora até a referência é outro fato, sobretudo quando a próxima faixa
        # ainda não começou.
        "espera_tipica_min": max(1, round(intervalo / 120)),
        "espera_ate_referencia_min": max(
            0, round((referencia - instante).total_seconds() / 60)
        ),
        "espera_maxima_min": max(
            0, math.ceil((janela_fim - instante).total_seconds() / 60)
        ),
    }


# ─────────────────────────────────────────────
# Consultas por parada e por linha
# ─────────────────────────────────────────────
def resumo_da_linha(numero: str) -> list[dict[str, Any]]:
    """Itinerário de cada variante da linha, sem repetir nomes de parada."""
    resumos = []
    for rota in _rotas_da_linha(numero):
        nomes_paradas: list[str] = []
        vistas: set[str] = set()
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                nome = str(parada.get("nome", "")).strip()
                chave = normalizar(nome)
                if nome and chave not in vistas:
                    vistas.add(chave)
                    nomes_paradas.append(nome)
        resumos.append({
            "linha": rota.get("linha", numero),
            "nome": rota.get("nome", ""),
            "paradas": nomes_paradas,
        })
    return resumos


def linhas_por_ponto(ponto: str) -> dict[str, Any]:
    """Inverte o GTFS: dada uma parada, devolve todas as linhas que a servem."""
    ocorrencias: list[tuple[dict[str, Any], dict[str, Any]]] = []
    textuais: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for rotas in catalogo().get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    item = (rota, parada)
                    ocorrencias.append(item)
                    if mesmo_nome(ponto, str(parada.get("nome", ""))):
                        textuais.append(item)

    candidatas = textuais
    coordenada = coordenada_do_ponto(ponto)
    if not candidatas and coordenada and ocorrencias:
        menor = min(
            distancia_m(parada, coordenada) for _rota, parada in ocorrencias
        )
        if menor <= RAIO_ACESSO_M:
            candidatas = [
                item for item in ocorrencias
                if distancia_m(item[1], coordenada)
                <= min(menor + 40, RAIO_ACESSO_M)
            ]
    if not candidatas:
        return {
            "erro": (
                f"Não localizei a parada '{ponto}' no recorte oficial da "
                "SPTrans. NÃO conclua que nenhuma linha passa por lá: peça ao "
                "aluno o nome como aparece na placa ou o instituto mais próximo."
            )
        }

    linhas: dict[str, dict[str, str]] = {}
    paradas: dict[str, str] = {}
    for rota, parada in candidatas:
        id_rota = str(rota.get("id") or rota.get("linha"))
        linhas[id_rota] = {
            "linha": str(rota.get("linha", "")),
            "nome": str(rota.get("nome", "")),
        }
        paradas[str(parada.get("id"))] = str(parada.get("nome", ponto))
    return {
        "parada": sorted(paradas.values(), key=normalizar)[0],
        "linhas": sorted(
            linhas.values(), key=lambda item: normalizar(item["linha"])
        ),
    }


# ─────────────────────────────────────────────
# Planejamento de trajeto
# ─────────────────────────────────────────────
def _passa_pelo_metro(
    paradas: list[dict[str, Any]],
    embarque: dict[str, Any],
    desembarque: dict[str, Any],
) -> bool:
    inicio = int(embarque["sequencia"])
    fim = int(desembarque["sequencia"])
    return any(
        "metro butanta" in normalizar(parada.get("nome", ""))
        for parada in paradas
        if inicio <= int(parada["sequencia"]) <= fim
    )


def _candidato(
    rota: dict[str, Any],
    viagem: dict[str, Any],
    embarque: dict[str, Any],
    desembarque: dict[str, Any],
    espera: EsperaProgramada,
    caminhada_origem_m: float,
    caminhada_destino_m: float,
    passa_metro: bool,
) -> dict[str, Any]:
    caminhada_origem_s = caminhada_origem_m / VELOCIDADE_CAMINHADA_M_MIN * 60
    caminhada_destino_s = caminhada_destino_m / VELOCIDADE_CAMINHADA_M_MIN * 60
    viagem_s = int(desembarque["deslocamento"]) - int(embarque["deslocamento"])
    fixo_s = caminhada_origem_s + viagem_s + caminhada_destino_s
    return {
        "modo": "onibus",
        "linha": rota.get("linha", ""),
        "nome": rota.get("nome", ""),
        "sentido": viagem.get("destino", ""),
        "embarque": embarque.get("nome", ""),
        "embarque_id": str(embarque.get("id", "")),
        "embarque_sequencia": int(embarque["sequencia"]),
        "desembarque": desembarque.get("nome", ""),
        "desembarque_id": str(desembarque.get("id", "")),
        "desembarque_sequencia": int(desembarque["sequencia"]),
        "caminhada_origem_m": round(caminhada_origem_m),
        "caminhada_destino_m": round(caminhada_destino_m),
        "caminhada_origem_s": caminhada_origem_s,
        "caminhada_destino_s": caminhada_destino_s,
        "espera_programada_s": espera.esperada_s,
        "espera_minima_s": espera.minima_s,
        "espera_maxima_s": espera.maxima_s,
        "intervalo_programado_s": espera.intervalo_s,
        "viagem_s": viagem_s,
        "total_estimado_s": fixo_s + espera.esperada_s,
        "total_minimo_s": fixo_s + espera.minima_s,
        "total_maximo_s": fixo_s + espera.maxima_s,
        "espera_programada_min": round(espera.esperada_s / 60),
        "intervalo_programado_min": (
            round(espera.intervalo_s / 60)
            if espera.intervalo_s is not None
            else None
        ),
        "viagem_min": round(viagem_s / 60),
        "total_estimado_min": round((fixo_s + espera.esperada_s) / 60),
        "passa_metro_butanta": passa_metro,
    }


def planejar_trajeto(
    origem: str, destino: str, agora: datetime | None = None
) -> dict[str, Any]:
    """Ranqueia viagens diretas por caminhada, espera programada e tempo a bordo."""
    coordenada_origem = coordenada_do_ponto(origem)
    coordenada_destino = coordenada_do_ponto(destino)
    if not coordenada_origem or not coordenada_destino:
        return {
            "erro": (
                "Não reconheci a origem ou o destino com precisão suficiente "
                "para comparar os ônibus. Peça ao aluno o instituto, a portaria "
                "ou o nome da parada."
            )
        }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    dados = catalogo()
    candidatos: list[dict[str, Any]] = []
    # Uma linha pode ligar os dois pontos e mesmo assim não servir agora — é o
    # domingo, quando os circulares do campus não operam. Dizer "não encontrei
    # linha direta" nesse caso seria falso; o aluno precisa saber que a linha
    # existe e que hoje ela não passa.
    liga_os_dois_pontos = False
    # Uma viagem entre dois pontos internos nunca deve sair do campus até o
    # terminal para depois voltar. É exatamente a regressão Central/Reitoria ->
    # Biênio, e a condição é geográfica: vale também para nomes de rua.
    trajeto_interno = dentro_do_campus(coordenada_origem) and dentro_do_campus(
        coordenada_destino
    )

    for rotas in dados.get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                paradas = viagem.get("paradas", [])
                embarques = [
                    parada for parada in paradas
                    if distancia_m(parada, coordenada_origem) <= RAIO_ACESSO_M
                ]
                if not embarques:
                    continue
                desembarques = [
                    parada for parada in paradas
                    if distancia_m(parada, coordenada_destino) <= RAIO_ACESSO_M
                ]
                if not desembarques:
                    continue
                for embarque in embarques:
                    uteis = [
                        desembarque for desembarque in desembarques
                        if int(desembarque["sequencia"])
                        > int(embarque["sequencia"])
                    ]
                    if not uteis:
                        continue
                    liga_os_dois_pontos = True
                    caminhada_origem_m = distancia_m(embarque, coordenada_origem)
                    pronto = instante + timedelta(
                        seconds=caminhada_origem_m
                        / VELOCIDADE_CAMINHADA_M_MIN
                        * 60
                    )
                    espera = espera_no_ponto(dados, viagem, embarque, pronto)
                    if espera is None or espera.esperada_s > MAX_ESPERA_MIN * 60:
                        continue
                    for desembarque in uteis:
                        passa_metro = _passa_pelo_metro(
                            paradas, embarque, desembarque
                        )
                        if trajeto_interno and passa_metro:
                            continue
                        candidatos.append(_candidato(
                            rota,
                            viagem,
                            embarque,
                            desembarque,
                            espera,
                            caminhada_origem_m,
                            distancia_m(desembarque, coordenada_destino),
                            passa_metro,
                        ))

    melhores_por_linha: dict[str, dict[str, Any]] = {}
    for candidato in candidatos:
        linha = str(candidato["linha"])
        guardado = melhores_por_linha.get(linha)
        if not guardado or candidato["total_estimado_s"] < guardado["total_estimado_s"]:
            melhores_por_linha[linha] = candidato
    opcoes = sorted(
        melhores_por_linha.values(),
        key=lambda item: (
            item["total_estimado_s"],
            item["caminhada_origem_m"] + item["caminhada_destino_m"],
            normalizar(item["linha"]),
        ),
    )

    distancia_reta = distancia_m(
        {"latitude": coordenada_destino[0], "longitude": coordenada_destino[1]},
        coordenada_origem,
    )
    caminhada_direta_m = round(distancia_reta * FATOR_PERCURSO_A_PE)
    caminhada_direta_s = caminhada_direta_m / VELOCIDADE_CAMINHADA_M_MIN * 60
    caminhada = {
        "modo": "a_pe",
        "distancia_aproximada_m": caminhada_direta_m,
        "total_estimado_s": caminhada_direta_s,
        "total_estimado_min": max(1, round(caminhada_direta_s / 60)),
    }
    plano = {
        "origem": chave_local(origem) or origem,
        "destino": chave_local(destino) or destino,
        "horario_referencia": instante.strftime("%H:%M"),
        "caminhada_direta_m": caminhada_direta_m,
        "caminhada_direta_min": caminhada["total_estimado_min"],
    }

    if not opcoes:
        plano["melhor"] = caminhada
        plano["alternativas"] = []
        plano["aviso"] = (
            "As linhas que fazem esse trajeto não têm passagem programada para "
            "as próximas horas; a opção coberta é caminhar."
            if liga_os_dois_pontos
            else "Não encontrei uma linha direta; a opção coberta é caminhar."
        )
        return plano

    # A caminhada ganha o empate. O fator conservador sobre a distância em linha
    # reta já é a margem de erro; recomendar um ônibus que chega depois de quem
    # foi a pé não tem como estar certo.
    if caminhada_direta_s <= opcoes[0]["total_estimado_s"]:
        plano["melhor"] = caminhada
        plano["alternativas"] = opcoes[:3]
        return plano
    plano["melhor"] = opcoes[0]
    plano["alternativas"] = opcoes[1:3]
    return plano


__all__ = [
    "ARQUIVO",
    "EsperaProgramada",
    "FATOR_PERCURSO_A_PE",
    "FONTE",
    "FUSO_SP",
    "MAX_ESPERA_MIN",
    "MAX_IDADE_DIAS",
    "RAIO_ACESSO_M",
    "VELOCIDADE_CAMINHADA_M_MIN",
    "aviso_se_necessario",
    "catalogo",
    "chave_local",
    "coordenada_do_ponto",
    "dentro_do_campus",
    "distancia_m",
    "espera_no_ponto",
    "espera_por_frequencia",
    "limpar_caches",
    "linhas_por_ponto",
    "mesmo_nome",
    "nota_atualizacao",
    "planejar_trajeto",
    "programacao",
    "proxima_partida_exata",
    "resumo_da_linha",
    "rotas_do_recorte",
    "servico_ativo",
]
