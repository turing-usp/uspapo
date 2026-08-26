"""Ônibus que atendem a USP usando dados oficiais e gratuitos da SPTrans.

A API Olho Vivo fornece posições e, quando disponíveis, previsões em tempo
real. Como o endpoint de paradas cobre apenas corredores e às vezes devolve
zero previsões dentro da USP, o módulo usa o GTFS oficial como fallback para
paradas e horários programados, deixando explícito quando o resultado não é
uma estimativa ao vivo.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
import math
import os
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from uspapo import gtfs_sptrans, olhovivo
from uspapo.ferramentas import RespostaFerramenta, Registro, cache, casa, normalizar
from uspapo.locais_usp import (
    CATALOGO_LOCAIS,
    coordenada_local,
    dados_local,
    resolver_local,
)
from uspapo.intencao_transporte import (
    RestricaoTemporal,
    analisar_intencao_transporte,
)
from uspapo.consulta_transporte import (
    TransitQuery,
    interpretar_consulta_transporte,
    resultado_consulta_transporte,
)
from uspapo.operacao_sptrans import (
    aviso_programacao_incompleta,
    fontes_operacionais,
    horario_gtfs_confiavel,
    parada_atendida_na_data,
)
from uspapo.transporte_resposta import (
    AlternativaPublica,
    EstimativaEspera,
    FaixaPassagemProgramada,
    LocalPublico,
    PassagensPorSentido,
    PrevisaoChegada,
    ResultadoChegada,
    ResultadoTrajeto,
    facetas_da_pergunta,
    renderizar_chegada,
    renderizar_trajeto,
)
from uspapo.transporte.geometria import (
    distancia_local_coordenadas_m as _distancia_local_coordenadas_m,
    paradas_projetadas_na_viagem as _paradas_projetadas_na_viagem,
    projetar_ponto_no_shape as _projetar_ponto_no_shape,
)
from uspapo.transporte import planoper as _planoper

BASE_URL = "https://api.olhovivo.sptrans.com.br/v2.1"
FONTE_API = "https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/"
FONTE_GTFS = "https://www.sptrans.com.br/desenvolvedores/"
FONTE_PLANOPER = (
    "https://www.sptrans.com.br/itinerarios/"
)
ARQUIVO_GTFS = Path(__file__).resolve().parents[1] / "dados_sptrans.json"
TIMEOUT = 10

try:
    FUSO_SP = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # pragma: no cover - imagens Windows sem tzdata
    FUSO_SP = timezone(timedelta(hours=-3))

# TTLs do cache:
# Posições de GPS e previsões mudam rápido: 20 segundos.
# Mapeamento de códigos de linha na SPTrans: 24 horas.
TTL_AO_VIVO = 20
TTL_LINHAS = 86400

# Uma correspondência por coordenada só é válida quando há de fato uma parada
# caminhável perto do local pedido. Antes, o ponto globalmente mais próximo era
# aceito sem teto: uma linha que não atende o Metrô Butantã podia ser anunciada
# usando uma parada a mais de meio quilômetro dali.
RAIO_ACESSO_M = 450
# As caminhadas abaixo são estimadas a partir da distância ao ponto, e não de
# uma malha de calçadas. Diferenças menores que dois minutos não justificam
# anunciar uma plataforma como objetivamente melhor por essa aproximação.
MARGEM_INCERTEZA_CAMINHADA_S = 2 * 60
# O pipeline atualiza o recorte diariamente. Depois de uma semana sem uma
# geração bem-sucedida, a resposta continua útil, mas passa a avisar claramente
# que o dado está vencido em vez de aparentar atualidade.
MAX_IDADE_GTFS_DIAS = 7

# Limites iniciais deliberadamente conservadores para a idade de ``ta`` em
# relação a ``hr``. Eles são parâmetros de produto, não uma estimativa de
# probabilidade: até 90 s normalmente representa uma posição recém-publicada;
# até 5 min ainda é aproveitável; entre 5 e 15 min só merece baixa confiança;
# acima disso não anunciamos ETA ao vivo. Dados históricos poderão calibrá-los.
IDADE_TA_ALTA_S = 90
IDADE_TA_MEDIA_S = 5 * 60
IDADE_TA_MAXIMA_S = 15 * 60
ADIANTAMENTO_TA_MAXIMO_S = 60

# Salvaguardas do ETA derivado de GPS. O GPS precisa estar realmente próximo
# do itinerário e as paradas precisam encaixar de forma coerente no shape.
MAX_DISTANCIA_GPS_SHAPE_M = 100
MAX_ERRO_PARADA_SHAPE_M = 60
TOLERANCIA_ORDEM_SHAPE_M = 20

# ``cp`` e ``stop_id`` pertencem a bases diferentes. A igualdade literal pode
# ser usada como identidade comprovável, mas qualquer exceção precisa entrar
# aqui após validação dos dois cadastros; proximidade e nome nunca a substituem.
CPS_OLHO_VIVO_POR_STOP_GTFS: dict[str, frozenset[str]] = {}

CABECALHOS = {"User-Agent": "USPapo/1.0 (chatbot de alunos da USP)"}


def _mesmo_nome(pedido: str, alvo: str) -> bool:
    """Equivalência lexical explicável, sem o falso positivo por prefixo.

    ``casa`` é intencionalmente permissiva e serve bem para busca. Para
    identidade de parada, porém, ela fazia "Poli" casar com "Academia de
    Polícia", "FAU" com "Faustolo" e "IP" com "Ipiranga". Exigir o casamento
    nos dois sentidos conserva variações de caixa/acentos/conectivos, mas não
    aceita que sobrem palavras semanticamente importantes em apenas um lado.
    """
    return casa(pedido, alvo) and casa(alvo, pedido)


def _normalizar_sentido_operacional(valor: object) -> str:
    """Normaliza apenas variações seguras de grafia entre os dois feeds."""
    palavras = [
        {"cid": "cidade", "univ": "universitaria"}.get(palavra, palavra)
        for palavra in normalizar(valor).replace(".", " ").split()
    ]
    return " ".join(palavras)


def _sentido_explicito_da_pergunta(
    numero: str,
    pergunta: str | None,
) -> str | None:
    """Resolve um headsign GTFS somente quando o usuário o informou.

    O trecho após ``sentido`` não vira um fato por si só: ele precisa casar de
    maneira inequívoca com um destino já existente para a linha no GTFS.
    """
    achado = re.search(r"\bsentido\s+(.+?)(?:[?!.,;]|$)", normalizar(pergunta or ""))
    if not achado:
        return None
    pedido = _normalizar_sentido_operacional(achado.group(1))
    if not pedido:
        return None
    rotas = _catalogo_gtfs().get("linhas", {}).get(normalizar(numero).upper(), [])
    destinos = sorted({
        str(viagem.get("destino") or "").strip()
        for rota in rotas
        for viagem in rota.get("viagens", [])
        if str(viagem.get("destino") or "").strip()
    }, key=normalizar)
    compativeis = [
        destino for destino in destinos
        if (
            _normalizar_sentido_operacional(destino) == pedido
            or _normalizar_sentido_operacional(destino) in pedido
            or pedido in _normalizar_sentido_operacional(destino)
        )
    ]
    return compativeis[0] if len(compativeis) == 1 else pedido


def _linha_corresponde_ao_sentido_gtfs(
    linha: dict[str, Any], destino_gtfs: object,
) -> bool:
    """Não usa o casamento permissivo de busca para decidir o sentido."""
    destino = _normalizar_sentido_operacional(_destino_linha_sptrans(linha))
    esperado = _normalizar_sentido_operacional(destino_gtfs)
    return bool(destino and esperado and destino == esperado)


def _cps_olho_vivo_do_stop_gtfs(stop_id: object) -> frozenset[str]:
    stop = str(stop_id or "").strip()
    if not stop:
        return frozenset()
    return frozenset({stop, *CPS_OLHO_VIVO_POR_STOP_GTFS.get(stop, ())})


def _paradas_olho_vivo_do_stop_gtfs(
    paradas: list[dict[str, Any]], stop_id: object,
) -> list[dict[str, Any]]:
    """Retorna somente ``cp`` cuja equivalência ao stop GTFS é conhecida."""
    cps_permitidos = _cps_olho_vivo_do_stop_gtfs(stop_id)
    return [
        parada for parada in paradas
        if str(parada.get("cp", "")).strip() in cps_permitidos
    ]

def _autenticar_sptrans(session: requests.Session, token: str) -> bool:
    """Autentica a sessão do requests com o token da SPTrans."""
    try:
        res = session.post(
            f"{BASE_URL}/Login/Autenticar?token={token}",
            headers=CABECALHOS,
            timeout=TIMEOUT,
        )
        return res.status_code == 200 and res.json() is True
    except Exception as err:
        # Exceções de requests podem incluir a URL completa, e o token da
        # Olho Vivo é enviado na query string. Nunca grave essa URL nos logs.
        print(
            "[circulares] Falha na autenticacao SPTrans: "
            f"{type(err).__name__}"
        )
        return False


def _get_json(
    session: requests.Session, caminho: str, **parametros: Any
) -> Any:
    resposta = session.get(
        f"{BASE_URL}/{caminho}",
        params=parametros,
        headers=CABECALHOS,
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def _linhas_sptrans(session: requests.Session, numero: str) -> list[dict[str, Any]]:
    """Resolve os códigos por sentido; eles podem mudar e não devem ser fixos."""
    dados = _get_json(session, "Linha/Buscar", termosBusca=numero)
    if not isinstance(dados, list):
        return []
    alvo = normalizar(numero).split("-")[0]
    return [
        item for item in dados
        if isinstance(item, dict) and normalizar(item.get("lt", "")) == alvo
    ]


def _coordenada_ponto(ponto: str) -> tuple[float, float] | None:
    coordenada = coordenada_local(ponto)
    if coordenada:
        return coordenada
    # Nomes de parada que não estão no catálogo manual continuam roteáveis. A
    # média entre plataformas/lados da via representa o local, não o embarque;
    # o planejador escolhe depois o lado e o sentido corretos.
    paradas: dict[str, dict[str, Any]] = {}
    for rotas in _catalogo_gtfs().get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    if _mesmo_nome(ponto, parada.get("nome", "")):
                        paradas[str(parada.get("id"))] = parada
    if paradas:
        return (
            sum(float(p["latitude"]) for p in paradas.values()) / len(paradas),
            sum(float(p["longitude"]) for p in paradas.values()) / len(paradas),
        )
    return None


def _distancia_aproximada(parada: dict[str, Any], coordenada: tuple[float, float]) -> float:
    """Distância local aproximada em metros, suficiente para ordenar paradas."""
    lat, lon = coordenada
    py, px = float(parada.get("py", 0)), float(parada.get("px", 0))
    dy = (py - lat) * 111_320
    dx = (px - lon) * 111_320 * math.cos(math.radians(lat))
    return math.hypot(dx, dy)


def _ordenar_paradas(
    paradas: list[dict[str, Any]],
    ponto: str,
    parada_id_esperada: str | None = None,
) -> list[dict[str, Any]]:
    if parada_id_esperada:
        # Para tempo real, stop GTFS conhecido elimina qualquer fallback por
        # texto ou coordenada: estes métodos não distinguem plataformas.
        return _paradas_olho_vivo_do_stop_gtfs(paradas, parada_id_esperada)

    textuais = [
        parada for parada in paradas
        if (
            _mesmo_nome(ponto, str(parada.get("np", "")))
            or _mesmo_nome(ponto, str(parada.get("ed", "")))
        )
    ]
    if textuais:
        return textuais

    coordenada = _coordenada_ponto(ponto)
    if coordenada:
        return [
            parada
            for parada in sorted(
                paradas,
                key=lambda item: _distancia_aproximada(item, coordenada),
            )
            if _distancia_aproximada(parada, coordenada) <= RAIO_ACESSO_M
        ]
    return []


@lru_cache(maxsize=1)
def _catalogo_gtfs() -> dict[str, Any]:
    """Carrega o pequeno recorte oficial gerado por atualizar_gtfs_sptrans.py."""
    try:
        with ARQUIVO_GTFS.open(encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        return dados if isinstance(dados, dict) else {}
    except (OSError, json.JSONDecodeError) as err:
        print(f"[circulares] Nao foi possivel ler o recorte GTFS: {err}")
        return {}


def _nota_atualizacao_gtfs(agora: datetime | None = None) -> str:
    """Expõe a idade do snapshot; dado estático nunca deve parecer "ao vivo"."""
    texto_gerado = str(_catalogo_gtfs().get("gerado_em") or "").strip()
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
    if idade_dias > MAX_IDADE_GTFS_DIAS:
        nota += (
            f" **Atenção:** ele está há {idade_dias} dias sem atualização; "
            "confirme o itinerário na SPTrans."
        )
    return nota


def _aviso_gtfs_se_necessario(agora: datetime | None = None) -> str:
    """Só leva a idade do feed à UX quando ela realmente exige atenção."""
    nota = _nota_atualizacao_gtfs(agora)
    problemas = (
        "**Atenção:**",
        "não está disponível",
        "é inválida",
    )
    return nota if any(problema in nota for problema in problemas) else ""


def _servico_ativo(catalogo: dict[str, Any], servico: str, dia: date) -> bool:
    data_gtfs = dia.strftime("%Y%m%d")
    excecao = (
        catalogo.get("excecoes_calendario", {})
        .get(servico, {})
        .get(data_gtfs)
    )
    if excecao is not None:
        # GTFS: 1 adiciona o serviço naquela data; 2 o remove.
        return int(excecao) == 1

    calendario = catalogo.get("calendarios", {}).get(servico)
    if not isinstance(calendario, dict):
        return False
    dias = calendario.get("dias", [])
    return (
        calendario.get("inicio", "99999999") <= data_gtfs
        <= calendario.get("fim", "00000000")
        and len(dias) == 7
        and bool(dias[dia.weekday()])
    )


def _distancia_parada_gtfs(
    parada: dict[str, Any], coordenada: tuple[float, float]
) -> float:
    lat, lon = coordenada
    py = float(parada.get("latitude", 0))
    px = float(parada.get("longitude", 0))
    dy = (py - lat) * 111_320
    dx = (px - lon) * 111_320 * math.cos(math.radians(lat))
    return math.hypot(dx, dy)


def _slots_estimados_frequencia(
    inicio: datetime,
    fim: datetime,
    intervalo_s: int,
    depois_de: datetime,
    *,
    limite: int = 3,
) -> list[datetime]:
    """Próximos slots estimados de uma faixa GTFS ``exact_times=0``.

    A âncora é o início publicado da faixa; os slots são aproximações
    reproduzíveis, não partidas confirmadas. ``datetime`` preserva naturalmente
    serviços 24:xx, que já carregam o dia de serviço correto.
    """
    if intervalo_s <= 0 or fim <= inicio or limite <= 0 or depois_de >= fim:
        return []
    if depois_de < inicio:
        proximo = inicio
    else:
        decorrido_s = (depois_de - inicio).total_seconds()
        passos = math.floor(decorrido_s / intervalo_s) + 1
        proximo = inicio + timedelta(seconds=passos * intervalo_s)
    slots: list[datetime] = []
    while proximo < fim and len(slots) < limite:
        slots.append(proximo)
        proximo += timedelta(seconds=intervalo_s)
    return slots


def _tipo_dia_planoper(dia: date) -> int:
    """PlanOper: 1=dia útil, 0=sábado, 2=domingo."""
    return _planoper.tipo_dia(dia)


def _sentido_planoper_da_viagem(
    rota: dict[str, Any],
    viagem: dict[str, Any],
    tipo_dia: int,
) -> str | None:
    """Associa uma viagem GTFS à ida/volta PlanOper sem heurística permissiva."""
    return _planoper.sentido_da_viagem(
        rota, viagem, tipo_dia, _normalizar_sentido_operacional,
    )


def _partidas_planoper_da_viagem(
    rota: dict[str, Any],
    viagem: dict[str, Any],
    dia_servico: date,
) -> list[tuple[int, bool | None]]:
    """Partidas PlanOper em segundos desde o início do dia de serviço.

    Horários após a meia-noite continuam pertencendo ao mesmo dia de serviço:
    23:55, 00:11 vira 23:55, 24:11.
    """
    return _planoper.partidas_da_viagem(
        rota, viagem, dia_servico, _normalizar_sentido_operacional,
    )


def _programacao_gtfs(
    numero: str,
    ponto: str,
    agora: datetime | None = None,
    sentido_esperado: str | None = None,
    datas_permitidas: tuple[date, ...] = (),
    restricao_temporal: RestricaoTemporal | None = None,
) -> dict[str, Any]:
    """Calcula as proximas passagens programadas no GTFS, sem chama de LLM."""
    catalogo = _catalogo_gtfs()
    rotas = catalogo.get("linhas", {}).get(normalizar(numero).upper(), [])
    if not rotas:
        return {"erro": f"O GTFS atual da SPTrans nao contem a linha {numero}."}

    candidatos: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    todas: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                item = (rota, viagem, parada)
                todas.append(item)
                if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                    candidatos.append(item)

    if sentido_esperado:
        def atende_sentido(
            item: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
        ) -> bool:
            destino_viagem = str(item[1].get("destino", ""))
            return (
                _normalizar_sentido_operacional(destino_viagem)
                == _normalizar_sentido_operacional(sentido_esperado)
            )

        todas_no_sentido = [item for item in todas if atende_sentido(item)]
        havia_candidato_na_parada = bool(candidatos)
        candidatos_no_sentido = [
            item for item in candidatos if atende_sentido(item)
        ]
        # Depois de reconhecer um sentido explícito, nunca voltamos ao conjunto
        # completo por proximidade. Isso impediria uma resposta no sentido
        # oposto quando a parada não pertence ao headsign solicitado.
        if not todas_no_sentido or (
            havia_candidato_na_parada and not candidatos_no_sentido
        ):
            return {
                "tipo": "sentido_incompativel",
                "linha": str(rotas[0].get("linha") or numero),
                "parada": ponto,
                "sentido_solicitado": sentido_esperado,
                "sentidos_disponiveis": sorted({
                    str(item[1].get("destino") or "")
                    for item in candidatos
                    if str(item[1].get("destino") or "")
                }, key=normalizar),
            }
        todas = todas_no_sentido
        candidatos = candidatos_no_sentido

    coordenada = _coordenada_ponto(ponto)
    if not candidatos:
        if coordenada and todas:
            # Inclui a mesma parada em diferentes viagens/sentidos, mas nao uma
            # parada distante apenas porque é a mais próxima que a linha tem.
            # O teto é o que impede, por exemplo, anunciar a 7725 no Metrô
            # Butantã usando uma parada da Av. Afrânio Peixoto.
            menor = min(
                _distancia_parada_gtfs(item[2], coordenada) for item in todas
            )
            if menor <= RAIO_ACESSO_M:
                candidatos = sorted(
                    (
                        item for item in todas
                        if _distancia_parada_gtfs(item[2], coordenada)
                        <= min(menor + 40, RAIO_ACESSO_M)
                    ),
                    key=lambda item: _distancia_parada_gtfs(item[2], coordenada),
                )
    elif coordenada:
        candidatos.sort(
            key=lambda item: _distancia_parada_gtfs(item[2], coordenada)
        )
    if not candidatos:
        return {
            "erro": (
                f"Nao localizei no GTFS uma parada da linha {numero} "
                f"correspondente a '{ponto}'."
            )
        }

    # A busca geográfica pode encontrar vários pontos próximos. Misturar as
    # faixas de todos eles e rotular o resultado com apenas o primeiro nome
    # produzia uma tabela impossível de auditar. A programação abaixo pertence
    # sempre a um único stop_id (a plataforma mais próxima); repetições desse
    # mesmo ID em viagens/serviços continuam sendo combinadas.
    if coordenada:
        candidatos.sort(
            key=lambda item: (
                _distancia_parada_gtfs(item[2], coordenada),
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
    parada_escolhida_id = str(candidatos[0][2].get("id", ""))
    candidatos = [
        item
        for item in candidatos
        if str(item[2].get("id", "")) == parada_escolhida_id
    ]

    # Um mesmo stop_id pode aparecer nos dois sentidos da linha (especialmente
    # em terminais). Somar as faixas e imprimir apenas o headsign do primeiro
    # candidato atribui horários do sentido oposto ao rótulo errado. Sem um
    # sentido pedido, devolvemos blocos independentes e auditáveis.
    destinos = sorted({
        str(item[1].get("destino", "")).strip()
        for item in candidatos
        if str(item[1].get("destino", "")).strip()
    }, key=normalizar)
    if not sentido_esperado and len(destinos) > 1:
        programacoes: list[dict[str, Any]] = []
        for destino in destinos:
            programacao = _programacao_gtfs(
                numero,
                ponto,
                agora,
                sentido_esperado=destino,
                datas_permitidas=datas_permitidas,
                restricao_temporal=restricao_temporal,
            )
            if not programacao.get("erro"):
                programacoes.append(programacao)
        if programacoes:
            tipos = {str(item.get("tipo")) for item in programacoes}
            if "programacao" in tipos:
                tipo_agregado = "programacao"
            elif "sem_passagem" in tipos:
                tipo_agregado = "sem_passagem"
            else:
                tipo_agregado = "sem_servico"
            avisos = list(dict.fromkeys(
                str(item.get("aviso") or "")
                for item in programacoes
                if item.get("aviso")
            ))
            return {
                "tipo": tipo_agregado,
                "linha": programacoes[0].get("linha", numero),
                "parada": programacoes[0].get("parada", ponto),
                "horarios": [],
                "instantes": [],
                "sentidos": programacoes,
                "programacao_incompleta": any(
                    bool(item.get("programacao_incompleta"))
                    for item in programacoes
                ),
                "servico_cadastrado": any(
                    bool(item.get("servico_cadastrado"))
                    for item in programacoes
                ),
                "aviso": " ".join(avisos),
            }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    datas_ordenadas = tuple(sorted(set(datas_permitidas)))
    limite_inicio = (
        datetime.combine(datas_ordenadas[0], time.min, tzinfo=FUSO_SP)
        if datas_ordenadas
        else None
    )
    limite_fim = (
        datetime.combine(
            datas_ordenadas[-1] + timedelta(days=1), time.min, tzinfo=FUSO_SP
        )
        if datas_ordenadas
        else None
    )
    if restricao_temporal is not None:
        # A consulta e calculada a partir do limite pedido, mesmo quando a
        # janela esta no passado/futuro em relacao ao relogio da requisicao.
        # ``datas_permitidas`` continua definindo os dias de servico a testar.
        instante = restricao_temporal.inicio
        limite_inicio = restricao_temporal.inicio
        limite_fim = restricao_temporal.fim
    dias_servico = (
        sorted({
            *(dia - timedelta(days=1) for dia in datas_ordenadas),
            *datas_ordenadas,
        })
        if datas_ordenadas
        else [instante.date() + timedelta(days=dias) for dias in range(-1, 8)]
    )
    chegadas: set[datetime] = set()
    estimativas_frequencia: set[tuple[datetime, int]] = set()
    faixas_frequencia: set[tuple[datetime, datetime, int]] = set()
    estimativas_planoper: dict[
        datetime,
        bool | None,
    ] = {}

    programacao_incompleta = False
    houve_servico_no_ponto = False
    dias_gtfs_incompletos: set[date] = set()
    dias_cobertos_planoper: set[date] = set()
    for rota, viagem, parada in candidatos:
        deslocamento = int(parada.get("deslocamento", 0))
        # Horários GTFS podem ultrapassar 24:00 e pertencem ao dia de serviço
        # anterior. À 00:30, por exemplo, uma viagem 24:45 de sexta ainda é uma
        # chegada futura válida no sábado civil.
        for dia_servico in dias_servico:
            if not _servico_ativo(catalogo, str(viagem.get("servico", "")), dia_servico):
                continue
            if not parada_atendida_na_data(
                str(rota.get("linha", numero)), parada, dia_servico
            ):
                continue
            dia_civil_pedido = (
                not datas_ordenadas or dia_servico in datas_ordenadas
            )
            if dia_civil_pedido:
                houve_servico_no_ponto = True
            linha_atual = str(
                rota.get("linha", numero)
            )

            gtfs_confiavel = horario_gtfs_confiavel(
                linha_atual,
                dia_servico,
            )

            if not gtfs_confiavel:
                if dia_civil_pedido:
                    dias_gtfs_incompletos.add(
                        dia_servico
                    )

            meia_noite = datetime.combine(
                dia_servico,
                time.min,
                tzinfo=FUSO_SP,
            )

            # Quando a grade GTFS não é confiável, usamos as partidas oficiais
            # da PlanOper como âncora e o deslocamento relativo GTFS para
            # estimar a passagem nesta parada.
            partidas_planoper: list[
                tuple[int, bool | None]
            ] = []

            if not gtfs_confiavel:
                partidas_planoper = (
                    _partidas_planoper_da_viagem(
                        rota,
                        viagem,
                        dia_servico,
                    )
                )

                if (
                    partidas_planoper
                    and dia_civil_pedido
                ):
                    dias_cobertos_planoper.add(
                        dia_servico
                    )

                for (
                    partida_planoper_s,
                    acessivel,
                ) in partidas_planoper:
                    chegada_planoper = (
                        meia_noite
                        + timedelta(
                            seconds=(
                                partida_planoper_s
                                + deslocamento
                            )
                        )
                    )

                    if (
                        chegada_planoper
                        >= instante - timedelta(seconds=30)
                        and (
                            limite_inicio is None
                            or chegada_planoper >= limite_inicio
                        )
                        and (
                            limite_fim is None
                            or chegada_planoper < limite_fim
                        )
                    ):
                        estimativas_planoper.setdefault(
                            chegada_planoper,
                            acessivel,
                        )

                # A PlanOper preencheu a grade que o GTFS marcou como
                # não confiável. Não misture as duas programações.
                if partidas_planoper:
                    continue

            frequencias = viagem.get("frequencias", [])
            if frequencias:
                for frequencia in frequencias:
                    inicio = int(frequencia["inicio"])
                    fim = int(frequencia["fim"])
                    intervalo = int(frequencia["intervalo"])
                    if int(frequencia.get("exact_times", 0)) == 1:
                        for partida in range(inicio, fim, intervalo):
                            chegada = meia_noite + timedelta(
                                seconds=partida + deslocamento
                            )
                            if (
                                chegada >= instante - timedelta(seconds=30)
                                and (limite_inicio is None or chegada >= limite_inicio)
                                and (limite_fim is None or chegada < limite_fim)
                            ):
                                chegadas.add(chegada)
                    else:
                        inicio_ponto = meia_noite + timedelta(
                            seconds=inicio + deslocamento
                        )
                        fim_ponto = meia_noite + timedelta(
                            seconds=fim + deslocamento
                        )
                        inicio_util = max(
                            inicio_ponto,
                            instante,
                            limite_inicio or inicio_ponto,
                        )
                        fim_util = min(fim_ponto, limite_fim or fim_ponto)
                        if fim_util > inicio_util:
                            faixas_frequencia.add(
                                (inicio_util, fim_util, intervalo)
                            )
                            for slot in _slots_estimados_frequencia(
                                inicio_ponto,
                                fim_ponto,
                                intervalo,
                                inicio_util,
                            ):
                                if limite_fim is None or slot < limite_fim:
                                    estimativas_frequencia.add((slot, intervalo))
            else:
                chegada = meia_noite + timedelta(seconds=int(parada["horario"]))
                if (
                    chegada >= instante - timedelta(seconds=30)
                    and (limite_inicio is None or chegada >= limite_inicio)
                    and (limite_fim is None or chegada < limite_fim)
                ):
                    chegadas.add(chegada)

    programacao_incompleta = bool(
        dias_gtfs_incompletos
        - dias_cobertos_planoper
    )

    proximas = sorted(chegadas)[:3]
    faixas = sorted(faixas_frequencia)[:3]
    estimativas = sorted(estimativas_frequencia)[:3]

    estimativas_planoper_ordenadas = sorted(
        estimativas_planoper.items(),
        key=lambda item: item[0],
    )[:3]

    rota, viagem_escolhida, parada = candidatos[0]
    if not proximas and not faixas and not estimativas and not estimativas_planoper_ordenadas and datas_ordenadas:
        aviso = ""
        if programacao_incompleta:
            aviso = aviso_programacao_incompleta(
                str(rota.get("linha", numero)), datas_ordenadas[0]
            )
        return {
            "tipo": (
                "programacao"
                if programacao_incompleta
                else "sem_passagem"
                if houve_servico_no_ponto
                else "sem_servico"
            ),
            "linha": rota.get("linha", numero),
            "parada": parada.get("nome", ponto),
            "parada_id": parada_escolhida_id,
            "destino": viagem_escolhida.get("destino", ""),
            "sentido_gtfs": viagem_escolhida.get("sentido"),
            "horarios": [],
            "instantes": [],
            "faixas": [],
            "programacao_incompleta": programacao_incompleta,
            "servico_cadastrado": houve_servico_no_ponto,
            "aviso": aviso,
        }
    if not proximas and not faixas and not estimativas and not estimativas_planoper_ordenadas:
        return {"erro": "Nao ha horario programado no periodo coberto pelo GTFS."}

    horarios = [
        chegada.strftime("%H:%M")
        if chegada.date() == instante.date()
        else chegada.strftime("%d/%m as %H:%M")
        for chegada in proximas
    ]

    estimativas_formatadas = [
        {
            "horario": (
                chegada.strftime("%H:%M")
                if chegada.date() == instante.date()
                else chegada.strftime("%d/%m as %H:%M")
            ),
            "instante": chegada.isoformat(),
            "intervalo_min": round(intervalo / 60),
            "source": "scheduled_estimate",
            "confidence": (
                "scheduled_uncertain"
                if programacao_incompleta
                else "scheduled"
            ),
            "origem_programacao": "gtfs_frequencia",
        }
        for chegada, intervalo in estimativas
    ]

    estimativas_formatadas.extend(
        {
            "horario": (
                chegada.strftime("%H:%M")
                if chegada.date() == instante.date()
                else chegada.strftime("%d/%m as %H:%M")
            ),
            "instante": chegada.isoformat(),
            "source": "scheduled_estimate",
            "confidence": "scheduled",
            "origem_programacao": "planoper",
            "acessivel": acessivel,
        }
        for chegada, acessivel
        in estimativas_planoper_ordenadas
    )

    # Ordem cronológica e deduplicação.
    estimativas_por_instante: dict[
        str,
        dict[str, Any],
    ] = {}

    for item in estimativas_formatadas:
        chave = str(item["instante"])

        # Em colisão, PlanOper é preferido à extrapolação de frequência GTFS.
        if (
            chave not in estimativas_por_instante
            or item.get("origem_programacao") == "planoper"
        ):
            estimativas_por_instante[chave] = item

    estimativas_formatadas = sorted(
        estimativas_por_instante.values(),
        key=lambda item: str(item["instante"]),
    )[:3]

    resultado = {
        "tipo": "programacao",
        "linha": rota.get("linha", numero),
        "parada": parada.get("nome", ponto),
        "parada_id": parada_escolhida_id,
        "destino": viagem_escolhida.get("destino", ""),
        "sentido_gtfs": viagem_escolhida.get("sentido"),
        "horarios": horarios,
        "instantes": [chegada.isoformat() for chegada in proximas],
        "estimativas": estimativas_formatadas,
        "programacao_incompleta": programacao_incompleta,
        "servico_cadastrado": houve_servico_no_ponto,
        "programacao_planoper": bool(
            estimativas_planoper_ordenadas
        ),
    }
    if faixas:
        faixas_formatadas = []
        for inicio, fim, intervalo in faixas:
            # exact_times=0 não autoriza cravar os múltiplos do headway como
            # partidas. Ainda assim, o headway permite responder de maneira
            # útil: se a faixa está ativa, a próxima passagem é esperada em
            # até um intervalo; se ela ainda vai começar, a janela parte do
            # início publicado. A referência central é uma estimativa, nunca
            # um horário garantido.
            janela_inicio = max(instante, inicio)
            janela_fim = min(
                janela_inicio + timedelta(seconds=intervalo),
                fim,
            )
            referencia = janela_inicio + (janela_fim - janela_inicio) / 2

            def texto_horario(valor: datetime) -> str:
                if valor.date() == instante.date():
                    return valor.strftime("%H:%M")
                return valor.strftime("%d/%m às %H:%M")

            faixas_formatadas.append({
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
                "inicio_texto": texto_horario(inicio),
                "fim_texto": texto_horario(fim),
                "intervalo_min": round(intervalo / 60),
                "ativa_agora": inicio <= instante < fim,
                "proxima_janela_inicio": janela_inicio.isoformat(),
                "proxima_janela_fim": janela_fim.isoformat(),
                "proxima_janela_inicio_texto": texto_horario(janela_inicio),
                "proxima_janela_fim_texto": texto_horario(janela_fim),
                "proxima_referencia": referencia.isoformat(),
                "proxima_referencia_texto": texto_horario(referencia),
                # Metade do headway é a espera típica dentro de uma faixa. O
                # tempo desde agora até a referência é outro fato, sobretudo
                # quando a próxima faixa ainda não começou.
                "espera_tipica_min": max(1, round(intervalo / 120)),
                "espera_ate_referencia_min": max(
                    0,
                    round((referencia - instante).total_seconds() / 60),
                ),
                "espera_maxima_min": max(
                    0,
                    math.ceil((janela_fim - instante).total_seconds() / 60),
                ),
            })
        resultado["faixas"] = faixas_formatadas
    return resultado


def _resumo_gtfs(numero: str) -> list[dict[str, Any]]:
    catalogo = _catalogo_gtfs()
    rotas = catalogo.get("linhas", {}).get(normalizar(numero).upper(), [])
    resumos = []
    for rota in rotas:
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


def _pergunta_pede_atendimento_de_linha(pergunta: str | None) -> bool:
    """Distingue "passa nessa parada" de pedir a lista do itinerário."""
    texto = normalizar(pergunta or "")
    return bool(re.search(r"\b(?:passa|atende)\b", texto)) or bool(
        re.search(r"\btem\s+(?:a\s+)?(?:linha\s+)?[\d]", texto)
    )


def _atendimento_linha_na_parada_gtfs(
    numero: str,
    ponto: str,
    datas: tuple[date, ...],
) -> dict[str, Any]:
    """Verifica atendimento por stop+viagem na data, sem inferir por resumo.

    A presença da parada em uma viagem prova apenas itinerário. A resposta
    positiva exige também serviço ativo (calendário/calendar_dates) e a
    regra operacional da parada para a data consultada.
    """
    catalogo = _catalogo_gtfs()
    rotas = catalogo.get("linhas", {}).get(normalizar(numero).upper(), [])
    if not rotas:
        return {"estado": "dados_insuficientes", "linhas": []}

    ocorrencias: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                    ocorrencias.append((rota, viagem, parada))
    if not ocorrencias:
        return {"estado": "nao_atende", "linhas": []}
    if not datas:
        return {
            "estado": "dados_insuficientes",
            "linhas": sorted({str(rota.get("linha", numero)) for rota, _, _ in ocorrencias}),
            "paradas": sorted({str(parada.get("nome", ponto)) for _, _, parada in ocorrencias}),
        }

    ativos: list[dict[str, Any]] = []
    for rota, viagem, parada in ocorrencias:
        linha = str(rota.get("linha", numero))
        dias = [
            dia for dia in datas
            if (
                _servico_ativo(catalogo, str(viagem.get("servico", "")), dia)
                and parada_atendida_na_data(linha, parada, dia)
            )
        ]
        if dias:
            ativos.append({
                "linha": linha,
                "parada": str(parada.get("nome", ponto)),
                "stop_id": str(parada.get("id", "")),
                "sentido": str(viagem.get("destino", "")),
                "viagem_id": str(viagem.get("id", "")),
                "datas": [dia.isoformat() for dia in dias],
            })
    paradas = sorted({str(parada.get("nome", ponto)) for _, _, parada in ocorrencias})
    linhas = sorted({str(rota.get("linha", numero)) for rota, _, _ in ocorrencias})
    return {
        "estado": "atende" if ativos else "sem_servico",
        "linhas": linhas,
        "paradas": paradas,
        "ocorrencias_ativas": ativos,
    }


def _linhas_por_ponto_gtfs(
    ponto: str,
    datas: tuple[date, ...] = (),
) -> dict[str, Any]:
    """Inverte o GTFS e, quando pedido, filtra serviço e itinerário por data."""
    catalogo = _catalogo_gtfs()
    ocorrencias: list[
        tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ] = []
    textuais: list[
        tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ] = []
    for rotas in catalogo.get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    item = (rota, viagem, parada)
                    ocorrencias.append(item)
                    if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                        textuais.append(item)

    candidatas = textuais
    coordenada = _coordenada_ponto(ponto)
    if not candidatas:
        if coordenada and ocorrencias:
            menor = min(
                _distancia_parada_gtfs(parada, coordenada)
                for _rota, _viagem, parada in ocorrencias
            )
            if menor <= RAIO_ACESSO_M:
                candidatas = sorted(
                    (
                        item for item in ocorrencias
                        if _distancia_parada_gtfs(item[2], coordenada)
                        <= min(menor + 40, RAIO_ACESSO_M)
                    ),
                    key=lambda item: _distancia_parada_gtfs(item[2], coordenada),
                )
    elif coordenada:
        candidatas.sort(
            key=lambda item: _distancia_parada_gtfs(item[2], coordenada)
        )
    if not candidatas:
        return {"erro": f"Não localizei a parada '{ponto}' no GTFS da SPTrans."}

    linhas_candidatas = [str(rota.get("linha", "")) for rota, _, _ in candidatas]
    linhas: dict[str, dict[str, Any]] = {}
    paradas: dict[str, str] = {}
    for rota, viagem, parada in candidatas:
        dias_ativos = [
            dia
            for dia in datas
            if (
                _servico_ativo(catalogo, str(viagem.get("servico", "")), dia)
                and parada_atendida_na_data(str(rota.get("linha", "")), parada, dia)
            )
        ]
        if datas and not dias_ativos:
            continue
        id_rota = str(rota.get("id") or rota.get("linha"))
        item_linha = linhas.setdefault(id_rota, {
            "linha": str(rota.get("linha", "")),
            "nome": str(rota.get("nome", "")),
            "datas": [],
        })
        item_linha["datas"] = sorted({
            *item_linha.get("datas", []),
            *(dia.isoformat() for dia in dias_ativos),
        })
        paradas[str(parada.get("id"))] = str(parada.get("nome", ponto))

    # Mesmo quando nenhuma linha opera no período, a parada foi localizada e a
    # resposta deve dizer "nenhuma", não fingir que ela inexiste no catálogo.
    if not paradas:
        for _rota, _viagem, parada in candidatas:
            paradas[str(parada.get("id"))] = str(parada.get("nome", ponto))
    return {
        "parada": sorted(paradas.values(), key=normalizar)[0],
        "linhas": sorted(linhas.values(), key=lambda item: normalizar(item["linha"])),
        "fontes_operacionais": fontes_operacionais(linhas_candidatas, datas),
    }


def _chave_local(ponto: str) -> str | None:
    return ponto if ponto in CATALOGO_LOCAIS else resolver_local(ponto)


def _proxima_passagem_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    depois_de: datetime,
    ate: datetime | None = None,
) -> datetime | None:
    deslocamento = int(parada.get("deslocamento", 0))
    melhor: datetime | None = None
    for dias_a_frente in range(-1, 8):
        dia_servico = depois_de.date() + timedelta(days=dias_a_frente)
        if not _servico_ativo(catalogo, str(viagem.get("servico", "")), dia_servico):
            continue
        meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
        frequencias = viagem.get("frequencias", [])
        if frequencias:
            for frequencia in frequencias:
                inicio = int(frequencia["inicio"])
                fim = int(frequencia["fim"])
                if int(frequencia.get("exact_times", 0)) == 1:
                    partidas = range(
                        inicio,
                        fim,
                        int(frequencia["intervalo"]),
                    )
                    for partida in partidas:
                        passagem = meia_noite + timedelta(
                            seconds=partida + deslocamento
                        )
                        if passagem >= depois_de and (
                            (ate is None or passagem < ate)
                            and (melhor is None or passagem < melhor)
                        ):
                            melhor = passagem
                else:
                    # exact_times=0 não confirma partidas, mas a ancoragem da
                    # faixa permite calcular slots programados estimados.
                    inicio_ponto = meia_noite + timedelta(
                        seconds=inicio + deslocamento
                    )
                    fim_ponto = meia_noite + timedelta(
                        seconds=fim + deslocamento
                    )
                    for passagem in _slots_estimados_frequencia(
                        inicio_ponto,
                        fim_ponto,
                        int(frequencia["intervalo"]),
                        depois_de,
                        limite=1,
                    ):
                        if (ate is None or passagem < ate) and (
                            melhor is None or passagem < melhor
                        ):
                            melhor = passagem
        else:
            passagem = meia_noite + timedelta(seconds=int(parada["horario"]))
            if (
                passagem >= depois_de
                and (ate is None or passagem < ate)
                and (melhor is None or passagem < melhor)
            ):
                melhor = passagem
    return melhor


def _espera_media_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    pronto_para_embarcar: datetime,
    ate: datetime | None = None,
) -> tuple[float, float | None]:
    """Espera GTFS; frequências produzem slots explicitamente estimados."""
    servico = str(viagem.get("servico", ""))
    deslocamento = int(parada.get("deslocamento", 0))
    estimativas: list[tuple[datetime, int]] = []
    for dias_a_frente in range(-1, 8):
        dia_servico = pronto_para_embarcar.date() + timedelta(days=dias_a_frente)
        if not _servico_ativo(catalogo, servico, dia_servico):
            continue
        meia_noite_servico = datetime.combine(
            dia_servico, time.min, tzinfo=FUSO_SP
        )
        for frequencia in viagem.get("frequencias", []):
            if int(frequencia.get("exact_times", 0)) == 1:
                continue
            inicio_no_ponto = meia_noite_servico + timedelta(
                seconds=int(frequencia["inicio"]) + deslocamento
            )
            fim_no_ponto = meia_noite_servico + timedelta(
                seconds=int(frequencia["fim"]) + deslocamento
            )
            for slot in _slots_estimados_frequencia(
                inicio_no_ponto,
                fim_no_ponto,
                int(frequencia["intervalo"]),
                pronto_para_embarcar,
                limite=1,
            ):
                if ate is None or slot < ate:
                    estimativas.append((slot, int(frequencia["intervalo"])))
    if estimativas:
        proxima, intervalo_s = min(estimativas, key=lambda item: item[0])
        return (
            max(0, (proxima - pronto_para_embarcar).total_seconds() / 60),
            intervalo_s / 60,
        )

    proxima = _proxima_passagem_gtfs(
        catalogo, viagem, parada, pronto_para_embarcar, ate=ate
    )
    if proxima is None:
        return float("inf"), None
    return (
        (proxima - pronto_para_embarcar).total_seconds() / 60,
        None,
    )


def _chave_ranking_rota(candidato: dict[str, Any]) -> tuple[Any, ...]:
    """Desempate estável para planos diretos já estruturalmente válidos.

    O tempo total continua sendo o critério primário. A caminhada vem em
    seguida porque é a parte menos precisa do modelo; em empate prático ela
    evita escolher uma plataforma mais distante por ordem do arquivo GTFS.
    """
    caminhada = float(candidato["caminhada_origem_m"]) + float(
        candidato["caminhada_destino_m"]
    )
    # Uma partida explicitamente tabelada é um pouco mais informativa que a
    # metade de uma faixa de frequência, mas só é usada depois do total e da
    # caminhada, nunca para inverter uma opção materialmente mais rápida.
    qualidade_programacao = 1 if candidato.get("intervalo_programado_s") is None else 0
    return (
        float(candidato.get("total_estimado_s") or candidato.get("ranking_s") or math.inf),
        caminhada,
        -qualidade_programacao,
        normalizar(candidato.get("linha", "")),
        normalizar(candidato.get("sentido", "")),
        str(candidato.get("embarque_id", "")),
        str(candidato.get("desembarque_id", "")),
    )


def _planejar_trajeto_gtfs(
    origem: str,
    destino: str,
    agora: datetime | None = None,
    modo_solicitado: str | None = None,
    restricao_temporal: RestricaoTemporal | None = None,
) -> dict[str, Any]:
    """Ranqueia viagens diretas por caminhada, espera programada e tempo a bordo."""
    coordenada_origem = _coordenada_ponto(origem)
    coordenada_destino = _coordenada_ponto(destino)
    if not coordenada_origem or not coordenada_destino:
        return {
            "erro": (
                "Não reconheci a origem ou o destino com precisão suficiente para "
                "comparar os ônibus."
            )
        }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    catalogo = _catalogo_gtfs()
    candidatos: list[dict[str, Any]] = []
    candidatos_sem_horario: list[dict[str, Any]] = []
    limite_caminhada = RAIO_ACESSO_M
    velocidade_caminhada_m_min = 80
    chave_origem = _chave_local(origem)
    chave_destino = _chave_local(destino)
    ambos_dentro_campus = bool(
        chave_origem
        and chave_destino
        and chave_origem != "metro_butanta"
        and chave_destino != "metro_butanta"
    )
    # A janela de planejamento cobre a proximidade da meia-noite (inclusive
    # viagens 24:xx do dia de serviço anterior), mas não transforma a primeira
    # faixa do dia seguinte em espera útil para uma pergunta feita à tarde.
    fim_horizonte = instante + timedelta(hours=4)
    if restricao_temporal is not None and restricao_temporal.fim is not None:
        fim_horizonte = min(fim_horizonte, restricao_temporal.fim)

    for rotas in catalogo.get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                embarques = [
                    parada for parada in viagem.get("paradas", [])
                    if _distancia_parada_gtfs(parada, coordenada_origem)
                    <= limite_caminhada
                ]
                desembarques = [
                    parada for parada in viagem.get("paradas", [])
                    if _distancia_parada_gtfs(parada, coordenada_destino)
                    <= limite_caminhada
                ]
                for embarque in embarques:
                    for desembarque in desembarques:
                        if int(desembarque["sequencia"]) <= int(embarque["sequencia"]):
                            continue
                        linha = str(rota.get("linha", ""))
                        # Depois da meia-noite, 00:15 pode pertencer à grade do
                        # serviço de ontem (por exemplo, 24:15 no GTFS). Nunca
                        # assumimos que a data civil atual é a data de serviço.
                        datas_servico = (instante.date(),)
                        if instante.hour < 6:
                            # A tolerância é deliberadamente limitada à
                            # madrugada: fora dela, aceitar a grade de ontem
                            # faria uma operação de fim de semana parecer ativa.
                            datas_servico = (
                                instante.date() - timedelta(days=1),
                                instante.date(),
                            )
                        datas_compativeis = [
                            dia for dia in datas_servico
                            if (
                                parada_atendida_na_data(linha, embarque, dia)
                                and parada_atendida_na_data(linha, desembarque, dia)
                                and _servico_ativo(
                                    catalogo, str(viagem.get("servico", "")), dia
                                )
                            )
                        ]
                        if not datas_compativeis:
                            continue
                        caminhada_origem = _distancia_parada_gtfs(
                            embarque, coordenada_origem
                        )
                        caminhada_destino = _distancia_parada_gtfs(
                            desembarque, coordenada_destino
                        )
                        minutos_ate_ponto = caminhada_origem / velocidade_caminhada_m_min
                        pronto_para_embarcar = instante + timedelta(
                            minutes=minutos_ate_ponto
                        )
                        viagem_s = (
                            int(desembarque["deslocamento"])
                            - int(embarque["deslocamento"])
                        )
                        viagem_min = viagem_s / 60
                        trecho = [
                            parada
                            for parada in viagem.get("paradas", [])
                            if int(embarque["sequencia"])
                            <= int(parada["sequencia"])
                            <= int(desembarque["sequencia"])
                        ]
                        passa_metro = any(
                            "metro butanta" in normalizar(parada.get("nome", ""))
                            for parada in trecho
                        )
                        # Uma viagem entre dois destinos internos nunca deve
                        # sair do campus até o terminal para depois voltar. É
                        # exatamente a regressão Central/Reitoria -> Biênio.
                        if ambos_dentro_campus and passa_metro:
                            continue
                        caminhada_origem_s = minutos_ate_ponto * 60
                        caminhada_destino_s = (
                            caminhada_destino / velocidade_caminhada_m_min * 60
                        )
                        candidato_base = {
                            "linha": linha,
                            "nome": rota.get("nome", ""),
                            "viagem_id": str(viagem.get("id", "")),
                            "sentido": viagem.get("destino", ""),
                            "embarque": embarque.get("nome", ""),
                            "embarque_id": str(embarque.get("id", "")),
                            "embarque_sequencia": int(embarque["sequencia"]),
                            "desembarque": desembarque.get("nome", ""),
                            "desembarque_id": str(desembarque.get("id", "")),
                            "desembarque_sequencia": int(desembarque["sequencia"]),
                            "caminhada_origem_m": round(caminhada_origem),
                            "caminhada_destino_m": round(caminhada_destino),
                            "caminhada_origem_s": caminhada_origem_s,
                            "caminhada_destino_s": caminhada_destino_s,
                            "viagem_s": viagem_s,
                            "viagem_min": round(viagem_min),
                            "passa_metro_butanta": passa_metro,
                        }
                        espera, intervalo = _espera_media_gtfs(
                            catalogo,
                            viagem,
                            embarque,
                            pronto_para_embarcar,
                            ate=fim_horizonte,
                        )
                        if not math.isfinite(espera):
                            candidatos_sem_horario.append({
                                **candidato_base,
                                "modo": "onibus_sem_horario",
                                "espera_programada_s": None,
                                "intervalo_programado_s": None,
                                "total_estimado_s": None,
                                "espera_programada_min": None,
                                "intervalo_programado_min": None,
                                "total_estimado_min": None,
                                "ranking_s": (
                                    caminhada_origem_s
                                    + viagem_s
                                    + caminhada_destino_s
                                ),
                            })
                            continue
                        espera_s = espera * 60
                        total_s = (
                            caminhada_origem_s + espera_s + viagem_s
                            + caminhada_destino_s
                        )
                        candidatos.append({
                            **candidato_base,
                            "modo": "onibus",
                            "espera_programada_s": espera_s,
                            "intervalo_programado_s": (
                                intervalo * 60 if intervalo is not None else None
                            ),
                            "total_estimado_s": total_s,
                            "espera_programada_min": round(espera),
                            "intervalo_programado_min": (
                                round(intervalo) if intervalo is not None else None
                            ),
                            "total_estimado_min": round(total_s / 60),
                            # A confiabilidade operacional deixa de ser um
                            # interruptor: se a grade é interpretável, ela
                            # ainda participa do plano, com rótulo de cautela.
                            "espera_source": (
                                "scheduled_estimate"
                                if intervalo is not None else "scheduled"
                            ),
                            "espera_confidence": (
                                "scheduled"
                                if any(
                                    horario_gtfs_confiavel(linha, dia)
                                    for dia in datas_compativeis
                                )
                                else "scheduled_uncertain"
                            ),
                        })

    # Não colapsar uma linha inteira em uma só opção: plataformas/sentidos
    # distintos podem ser candidatos válidos. Cada candidato abaixo vem de
    # uma mesma viagem GTFS e portanto já satisfaz sequência desembarque >
    # embarque, sem jamais cruzar o outro sentido.
    melhores_por_itinerario: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for candidato in candidatos:
        chave_itinerario = (
            str(candidato["linha"]), str(candidato["sentido"]),
            str(candidato["embarque_id"]), str(candidato["desembarque_id"]),
        )
        guardado = melhores_por_itinerario.get(chave_itinerario)
        if guardado is None or _chave_ranking_rota(candidato) < _chave_ranking_rota(guardado):
            melhores_por_itinerario[chave_itinerario] = candidato
    opcoes = sorted(
        melhores_por_itinerario.values(), key=_chave_ranking_rota,
    )
    melhores_sem_horario: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for candidato in candidatos_sem_horario:
        chave_itinerario = (
            str(candidato["linha"]), str(candidato["sentido"]),
            str(candidato["embarque_id"]), str(candidato["desembarque_id"]),
        )
        guardado = melhores_sem_horario.get(chave_itinerario)
        if guardado is None or _chave_ranking_rota(candidato) < _chave_ranking_rota(guardado):
            melhores_sem_horario[chave_itinerario] = candidato
    opcoes_sem_horario = sorted(
        melhores_sem_horario.values(), key=_chave_ranking_rota,
    )
    distancia_reta = _distancia_parada_gtfs(
        {
            "latitude": coordenada_destino[0],
            "longitude": coordenada_destino[1],
        },
        coordenada_origem,
    )
    # Ruas e calçadas raramente seguem a linha reta; 15% é uma aproximação
    # conservadora para decidir apenas se vale avisar que caminhar pode vencer.
    caminhada_direta_m = round(distancia_reta * 1.15)
    caminhada_direta_min = max(
        1, round(caminhada_direta_m / velocidade_caminhada_m_min)
    )
    plano_base = {
        "origem": chave_origem or origem,
        "destino": chave_destino or destino,
        "horario_referencia": instante.strftime("%H:%M"),
        "caminhada_direta_m": caminhada_direta_m,
        "caminhada_direta_min": caminhada_direta_min,
        "comparacao_caminhada_aproximada": bool(
            len(opcoes) > 1
            and abs(
                float(opcoes[0]["total_estimado_s"])
                - float(opcoes[1]["total_estimado_s"])
            ) <= MARGEM_INCERTEZA_CAMINHADA_S
        ),
    }

    caminhada = {
        "modo": "a_pe",
        "distancia_aproximada_m": caminhada_direta_m,
        "total_estimado_min": caminhada_direta_min,
    }
    if modo_solicitado == "onibus":
        if opcoes:
            return {
                **plano_base,
                "melhor": opcoes[0],
                "alternativas": opcoes[1:3],
                "alternativas_sem_horario": opcoes_sem_horario[:3],
            }
        if opcoes_sem_horario:
            return {
                **plano_base,
                "melhor": opcoes_sem_horario[0],
                "alternativas": opcoes_sem_horario[1:3],
                "ranking_temporal": (
                    "indeterminado" if len(opcoes_sem_horario) > 1 else "indisponivel"
                ),
                "aviso": aviso_programacao_incompleta(
                    str(opcoes_sem_horario[0]["linha"]), instante.date()
                ),
            }
        return {
            **plano_base,
            "melhor": caminhada,
            "alternativas": [],
            "aviso": (
                "Não encontrei uma linha direta em operação nesse período; "
                "a caminhada aparece somente como alternativa."
            ),
            "modo_solicitado": "onibus",
        }
    if not opcoes:
        # A falta de uma grade temporal confiável não transforma uma viagem
        # direta e operacional em inexistente. Mantém-na como melhor opção
        # factual para que o chamador possa tentar ETA ao vivo; sem ETA, não
        # há base para declarar a caminhada mais rápida.
        if opcoes_sem_horario:
            return {
                **plano_base,
                "melhor": opcoes_sem_horario[0],
                "alternativas": opcoes_sem_horario[1:3],
                "ranking_temporal": (
                    "indeterminado" if len(opcoes_sem_horario) > 1 else "indisponivel"
                ),
                "caminhada_alternativa": caminhada,
                "aviso": (
                    "Há linha direta em operação, mas faltam horários GTFS "
                    "confiáveis para comparar o tempo total com a caminhada."
                ),
            }
        return {
            **plano_base,
            "melhor": caminhada,
            "aviso": (
                "Não encontrei uma linha direta; a opção coberta é caminhar."
            ),
            "alternativas": [],
        }
    if caminhada_direta_min + 2 < opcoes[0]["total_estimado_min"]:
        return {
            **plano_base,
            "melhor": caminhada,
            "alternativas": opcoes[:3],
        }
    return {
        **plano_base,
        "melhor": opcoes[0],
        "alternativas": opcoes[1:3],
    }


def _local_publico(chave: str, dados: dict[str, Any] | None) -> LocalPublico:
    if not dados:
        nome = str(chave).replace("_", " ").strip().title()
        return LocalPublico(
            chave=chave,
            nome=nome,
            nome_curto=nome,
            localizacao="na região da Cidade Universitária",
        )
    return LocalPublico(
        chave=chave,
        nome=str(dados.get("nome") or chave),
        nome_curto=str(dados.get("nome_curto") or dados.get("nome") or chave),
        localizacao=str(dados.get("localizacao") or "na Cidade Universitária"),
    )


def _instante_referencia_sptrans(horario: str | None) -> datetime:
    agora = datetime.now(FUSO_SP)
    try:
        hora, minuto = (int(parte) for parte in str(horario).split(":")[:2])
        referencia = datetime.combine(
            agora.date(), time(hora, minuto), tzinfo=FUSO_SP
        )
        if referencia - agora > timedelta(hours=12):
            referencia -= timedelta(days=1)
        elif agora - referencia > timedelta(hours=12):
            referencia += timedelta(days=1)
        return referencia
    except (TypeError, ValueError):
        return agora


def _melhor_eta_ao_vivo(
    previsao: dict[str, Any], caminhada_origem_s: float,
) -> tuple[EstimativaEspera, str] | None:
    """Retorna o primeiro ETA válido alcançável, com sua confiança pronta."""
    if previsao.get("tipo") != "previsao":
        return None
    referencia = _instante_referencia_sptrans(previsao.get("hr"))
    candidatas: list[tuple[float, str, str]] = []
    for veiculo in previsao.get("veiculos", []):
        if not isinstance(veiculo, dict):
            continue
        horario = str(veiculo.get("t") or "").strip()
        ate_chegada_s = _segundos_ate_eta_sptrans(horario, referencia)
        if ate_chegada_s is None:
            continue
        # Um ônibus que passa antes de o aluno alcançar o ponto não pode ser
        # usado para recalcular o tempo total.
        if ate_chegada_s + 30 >= caminhada_origem_s:
            classificacao = _classificar_confianca_chegada(
                veiculo, previsao.get("hr"), referencia=referencia,
            )
            if classificacao["valid"]:
                candidatas.append((
                    max(0, ate_chegada_s), horario,
                    str(veiculo.get("confidence") or classificacao["level"]),
                ))
    if not candidatas:
        return None
    ate_chegada_s, horario, confianca = min(candidatas)
    espera_depois_da_caminhada_s = max(0, ate_chegada_s - caminhada_origem_s)
    return (
        EstimativaEspera(
            base="eta_ao_vivo",
            esperada_s=espera_depois_da_caminhada_s,
            minima_s=espera_depois_da_caminhada_s,
            maxima_s=espera_depois_da_caminhada_s,
            eta=horario,
            observado_em=str(previsao.get("hr") or "") or None,
        ),
        confianca,
    )


def _espera_ao_vivo(
    previsao: dict[str, Any], caminhada_origem_s: float,
) -> EstimativaEspera | None:
    """Compatibilidade para consumidores que só precisam da estimativa."""
    melhor = _melhor_eta_ao_vivo(previsao, caminhada_origem_s)
    return melhor[0] if melhor else None


def _segundos_ate_eta_sptrans(
    horario: str,
    referencia: datetime,
) -> float | None:
    """Valida um relógio Olho Vivo sem transformar dado stale em amanhã."""
    try:
        hora, minuto = (int(parte) for parte in horario.split(":")[:2])
        chegada = datetime.combine(
            referencia.date(), time(hora, minuto), tzinfo=FUSO_SP
        )
    except (TypeError, ValueError):
        return None
    if chegada < referencia - timedelta(seconds=30):
        if referencia.hour >= 20 and hora <= 4:
            chegada += timedelta(days=1)
        else:
            return None
    segundos = (chegada - referencia).total_seconds()
    if segundos < -30 or segundos > timedelta(hours=3).total_seconds():
        return None
    return max(0, segundos)


def _instante_atualizacao_sptrans(
    valor: object,
    referencia: datetime,
) -> datetime | None:
    """Interpreta ``ta`` sem transformar uma hora de ontem em dado novo."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    try:
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=FUSO_SP)
        return instante.astimezone(FUSO_SP)
    except ValueError:
        pass
    try:
        partes = texto.split(":")
        hora, minuto = int(partes[0]), int(partes[1])
        segundo = int(partes[2]) if len(partes) > 2 else 0
        instante = datetime.combine(
            referencia.date(), time(hora, minuto, segundo), tzinfo=FUSO_SP,
        )
    except (TypeError, ValueError):
        return None
    if instante - referencia > timedelta(hours=12):
        instante -= timedelta(days=1)
    elif referencia - instante > timedelta(hours=12):
        instante += timedelta(days=1)
    return instante


def _gps_valido(veiculo: dict[str, Any]) -> bool:
    try:
        latitude, longitude = float(veiculo["py"]), float(veiculo["px"])
    except (KeyError, TypeError, ValueError):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180 and bool(
        latitude or longitude
    )


def _classificar_confianca_chegada(
    veiculo: dict[str, Any],
    horario_referencia: str | None,
    *,
    referencia: datetime | None = None,
    source: str = "live",
) -> dict[str, Any]:
    """Classifica deterministamente uma chegada, sem interferência da LLM."""
    if source == "scheduled":
        return {"level": "scheduled", "reasons": ["gtfs_sem_eta_ao_vivo"], "valid": True}

    relogio = referencia or _instante_referencia_sptrans(horario_referencia)
    eta = _segundos_ate_eta_sptrans(str(veiculo.get("t") or ""), relogio)
    if eta is None:
        return {"level": "low", "reasons": ["eta_invalido"], "valid": False}

    reasons: list[str] = ["eta_valido"]
    gps_presente = _gps_valido(veiculo)
    if gps_presente:
        reasons.append("gps_presente")
    else:
        reasons.append("gps_ausente")
    identificador = str(veiculo.get("p") or "").strip()
    if identificador:
        reasons.append("veiculo_identificado")
    else:
        reasons.append("veiculo_nao_identificado")

    atualizado_em = _instante_atualizacao_sptrans(veiculo.get("ta"), relogio)
    if atualizado_em is None:
        reasons.append("ta_ausente_ou_invalido")

        if source == "live_gps_estimate":
            return {
                "level": "low",
                "reasons": reasons,
                "valid": False,
            }

        return {"level": "low", "reasons": reasons, "valid": True}
    idade_s = (relogio - atualizado_em).total_seconds()
    if idade_s < -ADIANTAMENTO_TA_MAXIMO_S:
        return {
            "level": "low",
            "reasons": [*reasons, "ta_posterior_ao_hr"],
            "valid": False,
        }
    idade_s = max(0, idade_s)
    if idade_s > IDADE_TA_MAXIMA_S:
        return {
            "level": "low",
            "reasons": [*reasons, "ta_antigo_demais"],
            "valid": False,
        }
    if source == "live_gps_estimate":
        if not gps_presente:
            return {
                "level": "low",
                "reasons": [
                    *reasons,
                    "gps_necessario_para_eta_derivado",
                ],
                "valid": False,
            }

        if idade_s <= IDADE_TA_MEDIA_S:
            return {
                "level": "medium",
                "reasons": [
                    *reasons,
                    "eta_derivado_da_posicao_gps",
                    "gps_recente",
                ],
                "valid": True,
            }

        return {
            "level": "low",
            "reasons": [
                *reasons,
                "eta_derivado_da_posicao_gps",
                "gps_pouco_recente",
            ],
            "valid": True,
        }
    if idade_s <= IDADE_TA_ALTA_S and gps_presente and identificador:
        level = "high"
        reasons.append("ta_muito_recente")
    elif idade_s <= IDADE_TA_MEDIA_S and gps_presente:
        level = "medium"
        reasons.append("ta_recente")
    elif idade_s <= IDADE_TA_MEDIA_S:
        level = "low"
        reasons.append("dados_operacionais_incompletos")
    else:
        level = "low"
        reasons.append("ta_antigo")
    return {"level": level, "reasons": reasons, "valid": True}


def _resultado_trajeto_publico(
    plano: dict[str, Any],
    previsao: dict[str, Any] | None = None,
) -> ResultadoTrajeto:
    melhor = plano["melhor"]
    api_consultada = bool(
        previsao
        and (
            previsao.get("api_consultada")
            or previsao.get("tipo") == "previsao"
            or "veiculos" in previsao
        )
    )
    intervalo_s = melhor.get("intervalo_programado_s")
    espera_programada_s = float(melhor["espera_programada_s"])
    if intervalo_s is not None:
        espera = EstimativaEspera(
            base="frequencia_media",
            esperada_s=espera_programada_s,
            minima_s=0,
            # Antes do início de uma faixa, a espera inclui o tempo até a
            # janela mais a incerteza de um headway. Dentro dela, o limite
            # continua sendo o próprio intervalo.
            maxima_s=max(float(intervalo_s), espera_programada_s),
            intervalo_s=float(intervalo_s),
        )
    else:
        espera = EstimativaEspera(
            base="programacao_exata",
            esperada_s=espera_programada_s,
            minima_s=espera_programada_s,
            maxima_s=espera_programada_s,
        )
    espera_source = str(
        melhor.get("espera_source")
        or ("scheduled_estimate" if intervalo_s is not None else "scheduled")
    )
    confianca_espera = str(melhor.get("espera_confidence") or "scheduled")
    ao_vivo = _melhor_eta_ao_vivo(
        previsao or {}, float(melhor["caminhada_origem_s"])
    )
    if ao_vivo:
        espera, confianca_espera = ao_vivo
        espera_source = "live"

    chave_origem = str(plano.get("origem") or "")
    chave_destino = str(plano.get("destino") or "")
    return ResultadoTrajeto(
        origem=_local_publico(chave_origem, dados_local(chave_origem)),
        destino=_local_publico(chave_destino, dados_local(chave_destino)),
        linha=str(melhor["linha"]),
        sentido=str(melhor["sentido"]),
        embarque=str(melhor["embarque"]),
        desembarque=str(melhor["desembarque"]),
        caminhada_origem_m=float(melhor["caminhada_origem_m"]),
        caminhada_destino_m=float(melhor["caminhada_destino_m"]),
        caminhada_origem_s=float(melhor["caminhada_origem_s"]),
        caminhada_destino_s=float(melhor["caminhada_destino_s"]),
        viagem_s=float(melhor["viagem_s"]),
        espera=espera,
        previsao_consultada=api_consultada,
        veiculos_ativos=(
            int(previsao["veiculos_ativos"])
            if (
                api_consultada
                and previsao
                and previsao.get("veiculos_ativos") is not None
            )
            else None
        ),
        alternativas=tuple(
            AlternativaPublica(
                linha=str(item["linha"]),
                sentido=str(item["sentido"]),
                total_s=float(item["total_estimado_s"]),
            )
            for item in plano.get("alternativas", [])
            if item.get("modo") == "onibus"
        ),
        aviso=" ".join(filter(None, (
            _aviso_gtfs_se_necessario(),
            (
                "As opções diretas estão muito próximas; a diferença de "
                "caminhada é apenas aproximada, não uma rota de pedestres."
                if plano.get("comparacao_caminhada_aproximada") else ""
            ),
        ))),
        embarque_id=str(melhor.get("embarque_id") or "") or None,
        desembarque_id=str(melhor.get("desembarque_id") or "") or None,
        espera_source=espera_source,
        espera_confidence=confianca_espera,
        tempo_bordo_source="gtfs_scheduled",
    )


def _resultado_chegada_publico(
    previsao: dict[str, Any],
    *,
    api_consultada: bool,
    ponto_pedido: str,
) -> ResultadoChegada:
    """Traduz respostas SPTrans/GTFS para um contrato estável de apresentação."""
    if previsao.get("tipo") in {"programacao", "sem_servico", "sem_passagem"}:
        dados_sentidos = previsao.get("sentidos") or [previsao]
        sentidos: list[PassagensPorSentido] = []
        for programacao in dados_sentidos:
            faixas = tuple(
                FaixaPassagemProgramada(
                    referencia=str(faixa.get("proxima_referencia_texto", "")),
                    referencia_instante=str(
                        faixa.get("proxima_referencia")
                        or faixa.get("proxima_janela_inicio", "")
                    ),
                    inicio=str(faixa.get("proxima_janela_inicio", "")),
                    fim=str(faixa.get("proxima_janela_fim", "")),
                    inicio_texto=str(
                        faixa.get("proxima_janela_inicio_texto", "")
                    ),
                    fim_texto=str(faixa.get("proxima_janela_fim_texto", "")),
                    intervalo_min=max(1, int(faixa.get("intervalo_min", 1))),
                    espera_tipica_min=max(
                        0, int(faixa.get("espera_tipica_min", 0))
                    ),
                    espera_maxima_min=max(
                        0, int(faixa.get("espera_maxima_min", 0))
                    ),
                    ativa_agora=bool(faixa.get("ativa_agora")),
                )
                for faixa in programacao.get("faixas", [])
            )
            sentidos.append(PassagensPorSentido(
                linha=str(programacao.get("linha") or previsao.get("linha") or ""),
                parada=str(programacao.get("parada") or ponto_pedido),
                sentido=str(programacao.get("destino") or ""),
                horarios_programados=tuple(
                    str(item) for item in programacao.get("horarios", [])
                ),
                instantes_programados=tuple(
                    str(item) for item in programacao.get("instantes", [])
                ),
                estimativas_programadas = tuple(
                    PrevisaoChegada(
                        horario=str(item["horario"]),
                        acessivel=(
                            bool(item["acessivel"])
                            if item.get("acessivel") is not None
                            else None
                        ),
                        source=str(
                            item.get("source")
                            or "scheduled_estimate"
                        ),
                        confidence=str(
                            item.get("confidence")
                            or "scheduled"
                        ),
                        intervalo_programado_min=(
                            int(item["intervalo_min"])
                            if item.get("intervalo_min") is not None
                            else None
                        ),
                    )
                    for item in programacao.get("estimativas", [])
                    if isinstance(item, dict)
                    and item.get("horario")
                ),
                faixas_programadas=faixas,
                programacao_confidence=(
                    "scheduled_uncertain"
                    if programacao.get("programacao_incompleta")
                    else "scheduled"
                ),
            ))
        tem_programacao_util = any(
            item.horarios_programados
            or item.estimativas_programadas
            or item.faixas_programadas
            for item in sentidos
        )
        return ResultadoChegada(
            linha=str(previsao.get("linha") or sentidos[0].linha),
            parada=str(previsao.get("parada") or sentidos[0].parada),
            sentidos=tuple(sentidos),
            api_consultada=api_consultada,
            observado_em=str(previsao.get("hr") or "") or None,
            veiculos_ativos=(
                int(previsao["veiculos_ativos"])
                if previsao.get("veiculos_ativos") is not None
                else None
            ),
            aviso_api=str(previsao.get("aviso_api") or ""),
            aviso=str(previsao.get("aviso") or _aviso_gtfs_se_necessario()),
            sem_servico=previsao.get("tipo") == "sem_servico",
            sem_passagem=previsao.get("tipo") == "sem_passagem",
            horario_indisponivel=(
                bool(previsao.get("programacao_incompleta"))
                and not tem_programacao_util
            ),
            periodo=str(previsao.get("periodo") or ""),
        )

    blocos_ao_vivo = previsao.get("previsoes_por_sentido") or [previsao]
    sentidos_ao_vivo: list[PassagensPorSentido] = []
    for bloco in blocos_ao_vivo:
        if not isinstance(bloco, dict):
            continue
        referencia_api = _instante_referencia_sptrans(bloco.get("hr"))
        veiculos = tuple(
            PrevisaoChegada(
                horario=str(item["t"]),
                acessivel=(
                    bool(item["a"]) if item.get("a") is not None else None
                ),
                source=str(item.get("source") or "live"),
                confidence=str(item.get("confidence") or "low"),
                minutos_ate_chegada=math.ceil(
                    _segundos_ate_eta_sptrans(str(item["t"]), referencia_api)
                    / 60
                ),
            )
            for item in _veiculos_ao_vivo_ordenados(
                list(bloco.get("veiculos", [])), bloco.get("hr"),
            )
        )
        if not veiculos:
            continue
        estimativas_programadas = tuple(
            PrevisaoChegada(
                horario=str(item["horario"]),
                acessivel=(
                    bool(item["acessivel"])
                    if item.get("acessivel") is not None
                    else None
                ),
                source=str(
                    item.get("source")
                    or "scheduled_estimate"
                ),
                confidence=str(
                    item.get("confidence")
                    or "scheduled"
                ),
                intervalo_programado_min=(
                    int(item["intervalo_min"])
                    if item.get("intervalo_min") is not None
                    else None
                ),
            )
            for item in bloco.get(
                "estimativas_programadas",
                [],
            )
            if isinstance(item, dict)
            and item.get("horario")
        )
        sentidos_ao_vivo.append(PassagensPorSentido(
            linha=str(bloco.get("linha") or previsao.get("linha") or ""),
            parada=str(bloco.get("parada") or ponto_pedido),
            sentido=str(bloco.get("destino") or ""),
            previsoes_ao_vivo=veiculos,
            horarios_programados=tuple(
                str(item) for item in bloco.get("horarios_programados", [])
            ),
            instantes_programados=tuple(
                str(item) for item in bloco.get("instantes_programados", [])
            ),
            estimativas_programadas=estimativas_programadas,
            programacao_confidence=(
                "scheduled_uncertain"
                if bloco.get("programacao_incompleta")
                else "scheduled"
            ),
            dados_operacionais=(
                dict(bloco["operacional"])
                if isinstance(bloco.get("operacional"), dict)
                else {}
            ,),
        ))
    if not sentidos_ao_vivo:
        # Não deveria ocorrer para uma resposta produzida acima, mas nunca
        # transforma uma previsão inválida recebida de outro chamador em ETA.
        fallback = {
            "tipo": "programacao",
            "linha": previsao.get("linha", ""),
            "parada": previsao.get("parada", ponto_pedido),
            "horarios": [],
            "aviso_api": "A previsão ao vivo não tinha ETA válido.",
        }
        return _resultado_chegada_publico(
            fallback, api_consultada=api_consultada, ponto_pedido=ponto_pedido,
        )
    linha = str(previsao.get("linha") or sentidos_ao_vivo[0].linha)
    parada = str(previsao.get("parada") or sentidos_ao_vivo[0].parada)
    return ResultadoChegada(
        linha=linha,
        parada=parada,
        sentidos=tuple(sentidos_ao_vivo),
        api_consultada=api_consultada,
        observado_em=str(
            previsao.get("hr")
            or blocos_ao_vivo[0].get("hr", "")
        ) or None,
        aviso_api=str(previsao.get("aviso_api") or ""),
    )


def _previsoes_linha(
    session: requests.Session, codigo_linha: int
) -> dict[str, Any]:
    """Previsões e paradas da linha, inclusive fora dos corredores.

    O catálogo `/Parada/*` da SPTrans documenta cobertura apenas dos corredores
    e pode devolver lista vazia dentro da USP. `/Previsao/Linha` é a fonte
    apropriada: traz todas as paradas monitoradas da linha e seus horários.
    """
    dados = _get_json(session, "Previsao/Linha", codigoLinha=codigo_linha)
    return dados if isinstance(dados, dict) else {}


def _posicoes_linha(session: requests.Session, codigo_linha: int) -> dict[str, Any]:
    dados = _get_json(session, "Posicao/Linha", codigoLinha=codigo_linha)
    return dados if isinstance(dados, dict) else {}


def _destino_linha_sptrans(linha: dict[str, Any]) -> str:
    """Destino operacional conforme o sentido documentado pela SPTrans."""
    # ``sl=1`` segue em direção a ``ts``; no sentido oposto, a referência é
    # ``tp``. Inverter esses campos faz o filtro abaixo associar um veículo ao
    # headsign GTFS oposto e elimina previsões válidas antes do contrato.
    destino = linha.get("ts") if linha.get("sl") == 1 else linha.get("tp")
    return str(destino or "")

def _shape_da_viagem(
    viagem: dict[str, Any],
) -> list[dict[str, Any]]:
    """Obtém do recorte GTFS o shape associado à viagem."""
    shape_id = str(
        viagem.get("shape_id") or ""
    ).strip()

    if not shape_id:
        return []

    shapes = _catalogo_gtfs().get("shapes", {})

    if not isinstance(shapes, dict):
        return []

    pontos = shapes.get(shape_id, [])

    if not isinstance(pontos, list):
        return []

    validos = [
        ponto
        for ponto in pontos
        if isinstance(ponto, dict)
    ]

    try:
        return sorted(
            validos,
            key=lambda ponto: int(
                ponto.get("sequencia", 0)
            ),
        )
    except (TypeError, ValueError):
        return []


def _eta_derivado_de_gps(
    viagem: dict[str, Any],
    stop_id_alvo: str,
    veiculo: dict[str, Any],
    horario_referencia: str | None,
) -> dict[str, Any] | None:
    """Estima chegada usando GPS ao vivo + geometria/tempos relativos do GTFS.

    Não inventa uma grade horária. O GPS informa onde o veículo está agora;
    o GTFS fornece o shape da viagem e o tempo relativo entre suas paradas.

    Retorna None sempre que a associação não for suficientemente segura.
    """
    if not isinstance(viagem, dict) or not isinstance(veiculo, dict):
        return None

    stop_id_alvo = str(stop_id_alvo or "").strip()
    if not stop_id_alvo:
        return None

    # Um ETA derivado só existe se houver uma posição GPS válida.
    if not _gps_valido(veiculo):
        return None

    referencia = _instante_referencia_sptrans(
        horario_referencia
    )

    # O instante da posição GPS é a base temporal da estimativa.
    # Sem ta não sabemos quando o ônibus estava naquela coordenada.
    atualizado_em = _instante_atualizacao_sptrans(
        veiculo.get("ta"),
        referencia,
    )

    if atualizado_em is None:
        return None

    shape = _shape_da_viagem(viagem)

    if len(shape) < 2:
        return None

    paradas = _paradas_projetadas_na_viagem(
        viagem,
        shape,
    )

    if len(paradas) < 2:
        return None

    # Se alguma parada da viagem estiver muito distante do shape,
    # a geometria dessa trip não é confiável o bastante para ETA.
    if any(
        float(parada["erro_shape_m"])
        > MAX_ERRO_PARADA_SHAPE_M
        for parada in paradas
    ):
        return None

    # A sequência das paradas deve avançar ao longo do shape.
    # Isso também protege contra projeções erradas em rotas que se cruzam.
    if any(
        float(atual["shape_m"])
        + TOLERANCIA_ORDEM_SHAPE_M
        < float(anterior["shape_m"])
        for anterior, atual in zip(
            paradas,
            paradas[1:],
        )
    ):
        return None

    alvo = next(
        (
            parada
            for parada in paradas
            if parada["id"] == stop_id_alvo
        ),
        None,
    )

    if alvo is None:
        return None

    try:
        latitude = float(veiculo["py"])
        longitude = float(veiculo["px"])
    except (KeyError, TypeError, ValueError):
        return None

    projecao_veiculo = _projetar_ponto_no_shape(
        latitude,
        longitude,
        shape,
    )

    if projecao_veiculo is None:
        return None

    distancia_shape_m = float(
        projecao_veiculo["distancia_m"]
    )

    if distancia_shape_m > MAX_DISTANCIA_GPS_SHAPE_M:
        return None

    posicao_veiculo_m = float(
        projecao_veiculo["shape_m"]
    )

    posicao_alvo_m = float(
        alvo["shape_m"]
    )

    # O veículo já chegou ou já passou pela parada pedida.
    # Não o anunciamos como "próximo".
    if posicao_veiculo_m >= posicao_alvo_m:
        return None

    # Descobre entre quais duas paradas GTFS o ônibus está.
    anterior: dict[str, Any] | None = None
    posterior: dict[str, Any] | None = None

    for parada_a, parada_b in zip(
        paradas,
        paradas[1:],
    ):
        posicao_a = float(
            parada_a["shape_m"]
        )
        posicao_b = float(
            parada_b["shape_m"]
        )

        if (
            posicao_a
            <= posicao_veiculo_m
            <= posicao_b
        ):
            anterior = parada_a
            posterior = parada_b
            break

    if anterior is None or posterior is None:
        return None

    inicio_m = float(
        anterior["shape_m"]
    )
    fim_m = float(
        posterior["shape_m"]
    )

    comprimento_trecho_m = (
        fim_m - inicio_m
    )

    # Duas paradas projetadas praticamente no mesmo ponto não permitem
    # uma interpolação espacial estável.
    if comprimento_trecho_m <= 1:
        return None

    tempo_anterior_s = float(
        anterior["deslocamento_s"]
    )
    tempo_posterior_s = float(
        posterior["deslocamento_s"]
    )

    if tempo_posterior_s < tempo_anterior_s:
        return None

    fracao = (
        posicao_veiculo_m - inicio_m
    ) / comprimento_trecho_m

    fracao = max(
        0.0,
        min(1.0, fracao),
    )

    tempo_atual_s = (
        tempo_anterior_s
        + fracao
        * (
            tempo_posterior_s
            - tempo_anterior_s
        )
    )

    tempo_alvo_s = float(
        alvo["deslocamento_s"]
    )

    restante_s = (
        tempo_alvo_s
        - tempo_atual_s
    )

    if restante_s <= 0:
        return None

    # A posição GPS foi observada em `ta`, portanto o ETA começa naquele
    # instante — e não no momento em que terminamos a requisição HTTP.
    chegada = (
        atualizado_em
        + timedelta(seconds=restante_s)
    )

    # A interface da Olho Vivo trabalha com HH:MM. Arredondamos para cima
    # para não publicar uma chegada anterior ao instante realmente calculado.
    chegada_relogio = chegada.replace(
        second=0,
        microsecond=0,
    )

    if chegada > chegada_relogio:
        chegada_relogio += timedelta(
            minutes=1
        )

    resultado: dict[str, Any] = {
        "p": veiculo.get("p"),
        "t": chegada_relogio.strftime("%H:%M"),
        "ta": veiculo.get("ta"),
        "py": veiculo.get("py"),
        "px": veiculo.get("px"),
        "source": "live_gps_estimate",

        # Evidência interna útil para diagnóstico. O normalizador atual
        # descarta estes campos antes de chegar ao renderer.
        "gps_eta_restante_s": restante_s,
        "gps_distancia_shape_m": distancia_shape_m,
        "gps_shape_m": posicao_veiculo_m,
        "gps_alvo_shape_m": posicao_alvo_m,
        "gps_tempo_relativo_s": tempo_atual_s,
        "gps_alvo_tempo_relativo_s": tempo_alvo_s,
        "gps_trecho_de": anterior["nome"],
        "gps_trecho_para": posterior["nome"],
    }

    if veiculo.get("a") is not None:
        resultado["a"] = veiculo.get("a")

    return resultado

def _contextos_ao_vivo_do_gtfs(
    programacao: dict[str, Any],
    parada_id_esperada: str | None,
) -> list[dict[str, str]]:
    """Extrai os pares stop/headsign que o GTFS já validou para a consulta."""
    blocos = programacao.get("sentidos") or [programacao]
    contextos: list[dict[str, str]] = []
    vistos: set[tuple[str, str]] = set()
    for bloco in blocos:
        stop_id = str(bloco.get("parada_id") or "").strip()
        destino = str(bloco.get("destino") or "").strip()
        if parada_id_esperada and stop_id != str(parada_id_esperada):
            continue
        chave = (stop_id, destino)
        if not stop_id or not destino or chave in vistos:
            continue
        vistos.add(chave)
        contextos.append({
            "stop_id": stop_id,
            "parada": str(bloco.get("parada") or ""),
            "destino": destino,
            "sentido_gtfs": str(bloco.get("sentido_gtfs") or ""),
        })
    return contextos

def _viagens_gtfs_do_contexto(
    numero: str,
    contexto: dict[str, str],
) -> list[dict[str, Any]]:
    """Templates GTFS compatíveis com parada + destino já validados."""

    stop_id = str(
        contexto.get("stop_id") or ""
    ).strip()

    destino_esperado = (
        _normalizar_sentido_operacional(
            contexto.get("destino")
        )
    )

    if not stop_id or not destino_esperado:
        return []

    rotas = (
        _catalogo_gtfs()
        .get("linhas", {})
        .get(
            normalizar(numero).upper(),
            [],
        )
    )

    # Trips de serviços diferentes podem representar exatamente o mesmo
    # itinerário/perfil temporal. Não queremos tratá-las como ambíguas.
    unicas: dict[
        tuple[
            str,
            tuple[tuple[str, int], ...],
        ],
        dict[str, Any],
    ] = {}

    for rota in rotas:
        if not isinstance(rota, dict):
            continue

        for viagem in rota.get("viagens", []):
            if not isinstance(viagem, dict):
                continue

            destino = (
                _normalizar_sentido_operacional(
                    viagem.get("destino")
                )
            )

            if destino != destino_esperado:
                continue

            paradas = [
                parada
                for parada in viagem.get(
                    "paradas", []
                )
                if isinstance(parada, dict)
            ]

            if not any(
                str(parada.get("id") or "")
                == stop_id
                for parada in paradas
            ):
                continue

            try:
                perfil = tuple(
                    (
                        str(
                            parada.get("id")
                            or ""
                        ),
                        int(
                            parada.get(
                                "deslocamento",
                                0,
                            )
                        ),
                    )
                    for parada in sorted(
                        paradas,
                        key=lambda item: int(
                            item.get(
                                "sequencia",
                                0,
                            )
                        ),
                    )
                )
            except (TypeError, ValueError):
                continue

            assinatura = (
                str(
                    viagem.get("shape_id")
                    or ""
                ),
                perfil,
            )

            unicas.setdefault(
                assinatura,
                viagem,
            )

    return list(unicas.values())

def _plataformas_gtfs_ambíguas(
    numero: str,
    ponto: str,
    *,
    sentido_esperado: str | None,
    parada_id_esperada: str | None,
) -> bool:
    """Evita inferir lado da via a partir de um nome/local genérico.

    A programação continua podendo escolher uma parada próxima para ser útil,
    mas o relógio ao vivo exige uma plataforma inequívoca. Um embarque já
    escolhido pelo planejador ou um sentido explicitamente escolhido resolvem
    essa ambiguidade operacional.
    """
    if parada_id_esperada or sentido_esperado:
        return False
    rotas = _catalogo_gtfs().get("linhas", {}).get(normalizar(numero).upper(), [])
    coordenada = _coordenada_ponto(ponto)
    candidatas: list[tuple[dict[str, Any], str]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            destino = str(viagem.get("destino") or "").strip()
            for parada in viagem.get("paradas", []):
                if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                    candidatas.append((parada, destino))
    if not candidatas and coordenada:
        todas = [
            (parada, str(viagem.get("destino") or "").strip())
            for rota in rotas
            for viagem in rota.get("viagens", [])
            for parada in viagem.get("paradas", [])
        ]
        if todas:
            menor = min(_distancia_parada_gtfs(parada, coordenada) for parada, _ in todas)
            if menor <= RAIO_ACESSO_M:
                candidatas = [
                    (parada, destino) for parada, destino in todas
                    if _distancia_parada_gtfs(parada, coordenada)
                    <= min(menor + 40, RAIO_ACESSO_M)
                ]
    plataformas: dict[str, set[str]] = {}
    for parada, destino in candidatas:
        stop_id = str(parada.get("id") or "").strip()
        if stop_id:
            plataformas.setdefault(stop_id, set()).add(destino)
    destinos = {
        destino for destinos_plataforma in plataformas.values()
        for destino in destinos_plataforma if destino
    }
    return len(plataformas) > 1 and len(destinos) > 1


def _veiculos_ao_vivo_ordenados(
    veiculos: list[dict[str, Any]], horario_referencia: str | None,
    restricao_temporal: RestricaoTemporal | None = None,
) -> list[dict[str, Any]]:
    """Valida, ordena e deduplica ETAs antes de limitar os próximos três."""
    referencia = _instante_referencia_sptrans(horario_referencia)
    ordenados: list[tuple[float, tuple[str, ...], dict[str, Any]]] = []
    vistos: set[tuple[str, ...]] = set()
    for veiculo in veiculos:
        if not isinstance(veiculo, dict):
            continue
        horario = str(veiculo.get("t") or "").strip()
        segundos = _segundos_ate_eta_sptrans(horario, referencia)
        if segundos is None:
            continue
        if (
            restricao_temporal is not None
            and not restricao_temporal.contem(
                referencia + timedelta(seconds=segundos)
            )
        ):
            continue

        identificador = str(veiculo.get("p") or "").strip()
        chave = (
            ("veiculo", identificador)
            if identificador
            else (
                "eta", horario, str(veiculo.get("ta") or ""),
                str(veiculo.get("py") or ""), str(veiculo.get("px") or ""),
            )
        )
        if chave in vistos:
            continue
        vistos.add(chave)
        # Mantém a evidência operacional disponível no resultado interno sem
        # despejar campos técnicos no renderer/naturalizador.
        preservado = {
            campo: veiculo.get(campo)
            for campo in ("p", "t", "ta", "py", "px", "a")
            if veiculo.get(campo) is not None
        }

        source = str(veiculo.get("source") or "live")

        confianca = _classificar_confianca_chegada(
            veiculo,
            horario_referencia,
            referencia=referencia,
            source=source,
        )

        if not confianca["valid"]:
            continue

        preservado.update({
            "source": source,
            "confidence": confianca["level"],
            "confidence_reasons": list(confianca["reasons"]),
        })
        ordenados.append((segundos, chave, preservado))
    ordenados.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ordenados[:3]]


def _obter_previsao_sptrans(
    numero: str,
    ponto: str,
    token: str,
    sentido_esperado: str | None = None,
    parada_id_esperada: str | None = None,
    datas_permitidas: tuple[date, ...] = (),
    restricao_temporal: RestricaoTemporal | None = None,
) -> dict[str, Any]:
    """Busca a previsão linha+ponto usando uma única sessão autenticada."""
    # O GTFS escolhe primeiro a plataforma e os sentidos válidos. O Olho Vivo
    # só pode complementar esse fato, nunca substituí-lo por nome/proximidade.
    programacao = _programacao_gtfs(
        numero,
        ponto,
        sentido_esperado=sentido_esperado,
        datas_permitidas=datas_permitidas,
        restricao_temporal=restricao_temporal,
    )
    if programacao.get("erro"):
        return programacao
    contextos_gtfs = _contextos_ao_vivo_do_gtfs(
        programacao, parada_id_esperada,
    )
    blocos_programados = programacao.get("sentidos") or [programacao]

    def programacao_do_contexto(contexto: dict[str, str]) -> dict[str, Any]:
        for bloco in blocos_programados:
            if not isinstance(bloco, dict):
                continue
            if (
                str(bloco.get("parada_id") or "") == contexto["stop_id"]
                and _normalizar_sentido_operacional(bloco.get("destino"))
                == _normalizar_sentido_operacional(contexto["destino"])
            ):
                return bloco
        return programacao if isinstance(programacao, dict) else {}
    if sentido_esperado and not any(
        _normalizar_sentido_operacional(contexto["destino"])
        == _normalizar_sentido_operacional(sentido_esperado)
        for contexto in contextos_gtfs
    ):
        programacao.update({
            "api_consultada": False,
            "aviso_api": (
                "O GTFS não identificou o sentido escolhido; nenhum ETA do "
                "sentido oposto foi usado."
            ),
        })
        return programacao
    if _plataformas_gtfs_ambíguas(
        numero,
        ponto,
        sentido_esperado=sentido_esperado,
        parada_id_esperada=parada_id_esperada,
    ):
        aviso_ambiguidade = (
            "Há mais de uma plataforma para sentidos diferentes nesse local; "
            "informe o sentido ou destino do ônibus para eu identificar o "
            "ponto de embarque correto."
        )
        programacao.update({
            "api_consultada": False,
            "aviso_api": aviso_ambiguidade,
            "aviso": aviso_ambiguidade,
        })
        return programacao
    if not contextos_gtfs:
        programacao.update({
            "api_consultada": False,
            "aviso_api": (
                "Não há uma associação GTFS inequívoca de parada e sentido; "
                "o horário exibido é apenas o programado."
            ),
        })
        return programacao

    session = requests.Session()
    if not _autenticar_sptrans(session, token):
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A autenticação da API Olho Vivo falhou."
            programacao["api_consultada"] = False
        return programacao

    try:
        linhas = cache(
            ("circulares", "linhas", normalizar(numero)),
            TTL_LINHAS,
            lambda: _linhas_sptrans(session, numero),
        )
        if not linhas:
            programacao["api_consultada"] = True
            return programacao

        tentativas: list[tuple[dict[str, Any], dict[str, str], dict[str, Any], str]] = []
        ha_linha_no_sentido = False
        for linha_api in linhas:
            codigo_linha = int(linha_api["cl"])
            previsoes = cache(
                ("circulares", "previsoes-linha", codigo_linha),
                TTL_AO_VIVO,
                lambda codigo=codigo_linha: _previsoes_linha(session, codigo),
            )
            paradas = previsoes.get("ps", []) if isinstance(previsoes, dict) else []
            for contexto in contextos_gtfs:
                if not _linha_corresponde_ao_sentido_gtfs(
                    linha_api, contexto["destino"],
                ):
                    continue
                ha_linha_no_sentido = True
                for parada in _paradas_olho_vivo_do_stop_gtfs(
                    paradas, contexto["stop_id"],
                ):
                    tentativas.append((
                        linha_api, contexto, parada, str(previsoes.get("hr") or ""),
                    ))

        previsoes_por_sentido: list[dict[str, Any]] = []
        for linha_api, contexto, parada, horario_referencia in tentativas:
            veiculos = _veiculos_ao_vivo_ordenados(
                list(parada.get("vs", [])), horario_referencia,
                restricao_temporal,
            )
            if not veiculos:
                continue
            fallback_programado = programacao_do_contexto(contexto)
            previsoes_por_sentido.append({
                "hr": horario_referencia,
                "linha": f"{linha_api.get('lt', numero)}-{linha_api.get('tl', 10)}",
                "sentido": linha_api.get("sl"),
                "destino": contexto["destino"],
                "parada": contexto["parada"] or parada.get("np") or ponto,
                "endereco": parada.get("ed", ""),
                "veiculos": veiculos,
                "horarios_programados": list(fallback_programado.get("horarios", [])),
                "instantes_programados": list(fallback_programado.get("instantes", [])),
                "estimativas_programadas": list(fallback_programado.get("estimativas", [])),
                "programacao_incompleta": bool(
                    fallback_programado.get("programacao_incompleta")
                ),
                "operacional": {
                    "origem": "live",
                    "hr": horario_referencia,
                    "linha_sptrans": linha_api.get("cl"),
                    "sentido_sptrans": linha_api.get("sl"),
                    "headsign_gtfs": contexto["destino"],
                    "sentido_gtfs": contexto["sentido_gtfs"],
                    "parada_gtfs": {
                        "stop_id": contexto["stop_id"],
                        "nome": contexto["parada"],
                    },
                    "parada_olho_vivo": {
                        campo: parada.get(campo)
                        for campo in ("cp", "np", "ed", "py", "px")
                        if parada.get(campo) is not None
                    },
                    "veiculos": veiculos,
                },
            })
        if previsoes_por_sentido:
            resultado: dict[str, Any] = {
                "tipo": "previsao",
                "previsoes_por_sentido": previsoes_por_sentido,
                "api_consultada": True,
            }
            # Compatibilidade com o uso de ETA ao vivo no planejador de rota,
            # que sempre pede um único sentido já validado pelo GTFS.
            if len(previsoes_por_sentido) == 1:
                resultado.update(previsoes_por_sentido[0])
            return resultado

        if not ha_linha_no_sentido:
            programacao.update({
                "api_consultada": True,
                "aviso_api": (
                    "A API Olho Vivo não identificou o sentido escolhido; "
                    "nenhum ETA do sentido oposto foi usado."
                ),
            })
            return programacao

        previsoes_gps_por_sentido: list[
            dict[str, Any]
        ] = []

        veiculos_ativos: dict[
            str,
            dict[str, Any],
        ] = {}

        horarios_referencia: list[str] = []


        for contexto in contextos_gtfs:
            viagens_contexto = (
                _viagens_gtfs_do_contexto(
                    numero,
                    contexto,
                )
            )


            candidatos_gps: list[
                dict[str, Any]
            ] = []

            horarios_contexto: list[str] = []

            linha_contexto: (
                dict[str, Any] | None
            ) = None

            for linha_api in linhas:
                # Nunca misturar GPS do sentido oposto.
                if not _linha_corresponde_ao_sentido_gtfs(
                    linha_api,
                    contexto["destino"],
                ):
                    continue

                if linha_contexto is None:
                    linha_contexto = linha_api

                codigo_linha = int(
                    linha_api["cl"]
                )

                posicoes = cache(
                    (
                        "circulares",
                        "posicoes-linha",
                        codigo_linha,
                    ),
                    TTL_AO_VIVO,
                    lambda codigo=codigo_linha: (
                        _posicoes_linha(
                            session,
                            codigo,
                        )
                    ),
                )

                horario_referencia = str(
                    posicoes.get("hr") or ""
                )

                if horario_referencia:
                    horarios_contexto.append(
                        horario_referencia
                    )
                    horarios_referencia.append(
                        horario_referencia
                    )

                for veiculo in posicoes.get(
                    "vs",
                    [],
                ):
                    if not isinstance(
                        veiculo,
                        dict,
                    ):
                        continue

                    identificador = str(
                        veiculo.get("p")
                        or id(veiculo)
                    )

                    veiculos_ativos[
                        identificador
                    ] = veiculo

                    # A contagem operacional independe de haver geometria
                    # GTFS suficiente para derivar ETA. Sem essa separação,
                    # um fallback de programação reportava zero veículos mesmo
                    # quando a própria API acabara de listá-los.
                    if not viagens_contexto:
                        continue

                    # Um mesmo contexto pode ter mais de um template
                    # GTFS possível. Tentamos todos, mas só usamos o
                    # veículo quando exatamente um produz ETA válido.
                    estimativas_validas: list[
                        dict[str, Any]
                    ] = []

                    for viagem in viagens_contexto:
                        estimativa = (
                            _eta_derivado_de_gps(
                                viagem,
                                contexto["stop_id"],
                                veiculo,
                                horario_referencia,
                            )
                        )

                        if estimativa is not None:
                            estimativas_validas.append(
                                estimativa
                            )

                    if len(estimativas_validas) == 1:
                        candidatos_gps.append(
                            estimativas_validas[0]
                        )

                    # len == 0:
                    #   veículo fora do shape, já passou,
                    #   GPS inválido etc.
                    #
                    # len > 1:
                    #   mais de um template continua plausível;
                    #   preferimos não inventar qual é o correto.


            if (
                not candidatos_gps
                or linha_contexto is None
            ):
                continue

            horario_contexto = (
                horarios_contexto[-1]
                if horarios_contexto
                else ""
            )

            veiculos_estimados = (
                _veiculos_ao_vivo_ordenados(
                    candidatos_gps,
                    horario_contexto,
                    restricao_temporal,
                )
            )

            if not veiculos_estimados:
                continue

            fallback_programado = (
                programacao_do_contexto(
                    contexto
                )
            )

            previsoes_gps_por_sentido.append({
                "hr": horario_contexto,
                "linha": (
                    f"{linha_contexto.get('lt', numero)}"
                    f"-{linha_contexto.get('tl', 10)}"
                ),
                "sentido": linha_contexto.get(
                    "sl"
                ),
                "destino": contexto["destino"],
                "parada": (
                    contexto["parada"]
                    or ponto
                ),
                "endereco": "",
                "veiculos": veiculos_estimados,

                "horarios_programados": list(
                    fallback_programado.get(
                        "horarios",
                        [],
                    )
                ),
                "instantes_programados": list(
                    fallback_programado.get(
                        "instantes",
                        [],
                    )
                ),
                "estimativas_programadas": list(
                    fallback_programado.get(
                        "estimativas",
                        [],
                    )
                ),

                "programacao_incompleta": bool(
                    fallback_programado.get(
                        "programacao_incompleta"
                    )
                ),

                "operacional": {
                    "origem": (
                        "live_gps_estimate"
                    ),
                    "hr": horario_contexto,
                    "linha_sptrans": (
                        linha_contexto.get("cl")
                    ),
                    "sentido_sptrans": (
                        linha_contexto.get("sl")
                    ),
                    "headsign_gtfs": (
                        contexto["destino"]
                    ),
                    "sentido_gtfs": (
                        contexto["sentido_gtfs"]
                    ),
                    "parada_gtfs": {
                        "stop_id": (
                            contexto["stop_id"]
                        ),
                        "nome": (
                            contexto["parada"]
                        ),
                    },
                    "veiculos": (
                        veiculos_estimados
                    ),
                },
            })


        if previsoes_gps_por_sentido:
            resultado_gps: dict[
                str,
                Any,
            ] = {
                "tipo": "previsao",
                "previsoes_por_sentido": (
                    previsoes_gps_por_sentido
                ),
                "api_consultada": True,
            }

            if (
                len(
                    previsoes_gps_por_sentido
                )
                == 1
            ):
                resultado_gps.update(
                    previsoes_gps_por_sentido[
                        0
                    ]
                )

            return resultado_gps


        # A API tinha veículos, mas nenhum deles pôde
        # produzir um ETA derivado seguro.
        programacao.update({
            "hr": (
                horarios_referencia[-1]
                if horarios_referencia
                else ""
            ),
            "veiculos_ativos": len(
                veiculos_ativos
            ),
            "api_consultada": True,
            "aviso_api": (
                "A API Olho Vivo não publicou uma parada com associação "
                "GTFS inequívoca para esse ponto e sentido; nenhum ETA foi usado."
                if not tentativas else
                "A API Olho Vivo não publicou um ETA e nenhuma posição GPS "
                "disponível permitiu calcular uma chegada com segurança para "
                "essa parada e esse sentido."
            ),
        })

        return programacao
    except (requests.RequestException, ValueError, TypeError, KeyError) as err:
        print(f"[circulares] Erro ao consultar previsão: {type(err).__name__}: {err}")
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A API Olho Vivo não respondeu agora."
            programacao["api_consultada"] = True
        return programacao


# A modularização que já existia na main continua sendo a autoridade para as
# responsabilidades compartilhadas e estáveis: leitura do recorte, calendário,
# geometria básica e acesso bruto ao Olho Vivo. As regras mais conservadoras de
# identidade GTFS↔Olho Vivo, sentido, confiança, ETA por GPS e ranking ficam
# neste motor, pois são justamente as garantias acrescentadas depois.
_catalogo_gtfs = gtfs_sptrans.catalogo
_mesmo_nome = gtfs_sptrans.mesmo_nome
_servico_ativo = gtfs_sptrans.servico_ativo
_distancia_parada_gtfs = gtfs_sptrans.distancia_m

_autenticar_sptrans = olhovivo._autenticar
_get_json = olhovivo._get_json
_linhas_sptrans = olhovivo._linhas
_previsoes_linha = olhovivo._previsoes_linha
_posicoes_linha = olhovivo._posicoes_linha
_destino_linha_sptrans = olhovivo.destino_da_linha


def _consultar_circulares_calcular(
    linha: str | None = None,
    destino_ou_ponto: str | None = None,
    origem: str | None = None,
    detalhes: bool = False,
    _pergunta: str | None = None,
    _historico: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Consulta itinerários ou previsão de chegada em uma parada."""
    fontes: list[str] = []
    token = os.getenv("SPTRANS_TOKEN", "").strip()
    agora = datetime.now(FUSO_SP)
    intencao = analisar_intencao_transporte(_pergunta, agora)

    termo_linha = normalizar(linha or "")
    termo_destino = normalizar(destino_ou_ponto or "")
    termo_origem = normalizar(origem or "")
    atendimento_pedido = (
        _pergunta_pede_atendimento_de_linha(_pergunta)
        and not intencao.pede_chegada
    )
    if (
        termo_linha
        and not termo_destino
        and _historico
        and (intencao.pede_chegada or atendimento_pedido)
    ):
        # Tool calls do modelo também podem chegar aqui sem a parada. Reuse a
        # mesma regra conservadora da pré-consulta, sem extrair locais das
        # respostas do bot.
        from uspapo.roteamento import _ponto_recente_associado

        ponto_contextual = _ponto_recente_associado(termo_linha, _historico)
        if ponto_contextual:
            destino_ou_ponto = ponto_contextual
            termo_destino = normalizar(ponto_contextual)

    if termo_origem and termo_destino:
        referencia_planejamento = intencao.instante_para_planejamento(agora)
        if _pergunta is None and intencao.modo_solicitado is None:
            # Mantém a interface histórica para chamadas Python diretas. No
            # fluxo do chatbot, `_pergunta` sempre existe e fornece a referência
            # temporal estável ou explicitamente pedida.
            plano = _planejar_trajeto_gtfs(
                origem or "", destino_ou_ponto or ""
            )
        else:
            plano = _planejar_trajeto_gtfs(
                origem or "",
                destino_ou_ponto or "",
                referencia_planejamento,
                intencao.modo_solicitado,
                intencao.restricao_temporal,
            )
        if plano.get("erro"):
            return str(plano["erro"]), [FONTE_GTFS]
        melhor = plano["melhor"]
        info_origem = dados_local(str(plano.get("origem", "")))
        if info_origem:
            fontes.append(str(info_origem["fonte"]))
        info_destino = dados_local(str(plano.get("destino", "")))
        if info_destino:
            fontes.append(str(info_destino["fonte"]))
        nome_origem = (
            str(info_origem["nome"]) if info_origem else str(plano["origem"])
        )
        nome_destino = (
            str(info_destino["nome"]) if info_destino else str(plano["destino"])
        )
        facetas = facetas_da_pergunta(_pergunta)
        if detalhes:
            facetas = replace(facetas, explicacao=True)

        if melhor.get("modo") == "a_pe":
            partes = []
            if facetas.localizacao and info_destino:
                partes.append(
                    f"A **{info_destino.get('nome_curto') or nome_destino}** fica "
                    f"{info_destino.get('localizacao') or 'na Cidade Universitária'}."
                )
            if plano.get("modo_solicitado") == "onibus":
                partes.append(
                    f"Não encontrei uma linha direta em operação entre "
                    f"**{nome_origem}** e **{nome_destino}** no período pedido."
                )
                partes.append(
                    "Como alternativa apenas aproximada, a distância em linha "
                    f"reta ajustada para caminhada equivale a cerca de "
                    f"**{melhor['total_estimado_min']} minutos** "
                    f"({melhor['distancia_aproximada_m']} m); isso não é uma "
                    "rota de pedestres calculada por ruas e calçadas."
                )
            else:
                partes.append(
                    f"De **{nome_origem}** até **{nome_destino}**, a opção "
                    f"estimada mais rápida é ir a pé: cerca de "
                    f"**{melhor['total_estimado_min']} minutos** "
                    f"({melhor['distancia_aproximada_m']} m em uma aproximação, "
                    "não em uma rota de pedestres)."
                )
            if plano.get("aviso"):
                partes.append(str(plano["aviso"]))
            if intencao.periodo == "tipico":
                partes.append(
                    "A comparação considera um **dia útil típico**. Para uma "
                    "resposta operacional, informe “hoje” ou “agora”."
                )
            if facetas.alternativas:
                alternativas = [
                    item
                    for item in plano.get("alternativas", [])
                    if item.get("modo") == "onibus"
                ]
                if alternativas:
                    partes.append(
                        "Se preferir ônibus, as opções diretas são: "
                        + "; ".join(
                            f"**{item['linha']}** (cerca de "
                            f"{item['total_estimado_min']} min)"
                            for item in alternativas
                        )
                        + "."
                    )
            aviso_gtfs = _aviso_gtfs_se_necessario()
            if aviso_gtfs:
                partes.append(aviso_gtfs)
            fontes.insert(0, FONTE_GTFS)
            fontes = list(dict.fromkeys(fontes))
            dados_publicos: dict[str, object] = {
                "tipo": "trajeto_a_pe",
                "facetas": {
                    "localizacao": facetas.localizacao,
                    "duracao": facetas.duracao,
                    "tempo_real": facetas.tempo_real,
                    "alternativas": facetas.alternativas,
                    "explicacao": facetas.explicacao,
                },
                "origem": nome_origem,
                "destino": nome_destino,
                "melhor_opcao": {
                    "modo": "a_pe",
                    "distancia_m": int(melhor["distancia_aproximada_m"]),
                    "tempo_total_min": int(melhor["total_estimado_min"]),
                },
            }
            if facetas.alternativas:
                dados_publicos["alternativas"] = [
                    {
                        "modo": "onibus",
                        "linha": str(item["linha"]),
                        "sentido": str(item["sentido"]),
                        "tempo_total_min": int(item["total_estimado_min"]),
                    }
                    for item in plano.get("alternativas", [])
                    if item.get("modo") == "onibus"
                ]
            if plano.get("aviso") or aviso_gtfs:
                dados_publicos["aviso"] = str(plano.get("aviso") or aviso_gtfs)
            return RespostaFerramenta(
                "\n\n".join(partes),
                fontes,
                dados_publicos,
            )

        if melhor.get("modo") == "onibus_sem_horario":
            api_sem_eta = False
            if token and facetas.tempo_real:
                opcoes_ao_vivo: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
                linhas_testadas: set[str] = set()
                for opcao in [melhor, *plano.get("alternativas", [])][:3]:
                    linha_opcao = str(opcao.get("linha", ""))
                    if not linha_opcao or linha_opcao in linhas_testadas:
                        continue
                    linhas_testadas.add(linha_opcao)
                    numero_opcao = linha_opcao.split("-", 1)[0]
                    previsao_opcao = cache(
                        (
                            "circulares", "previsao-rota", numero_opcao,
                            normalizar(opcao.get("embarque", "")),
                            normalizar(opcao.get("sentido", "")),
                            str(opcao.get("embarque_id", "")),
                            tuple(dia.isoformat() for dia in intencao.datas),
                            (
                                intencao.restricao_temporal.chave_cache()
                                if intencao.restricao_temporal else ()
                            ),
                        ),
                        TTL_AO_VIVO,
                        lambda numero=numero_opcao, item=opcao: (
                            _obter_previsao_sptrans(
                                numero,
                                str(item.get("embarque", "")),
                                token,
                                str(item.get("sentido", "")),
                                str(item.get("embarque_id", "")),
                                intencao.datas,
                                intencao.restricao_temporal,
                            )
                        ),
                    )
                    api_opcao = bool(
                        previsao_opcao.get("api_consultada")
                        or previsao_opcao.get("tipo") == "previsao"
                    )
                    api_sem_eta = api_sem_eta or api_opcao
                    espera_viva = _espera_ao_vivo(
                        previsao_opcao,
                        float(opcao["caminhada_origem_s"]),
                    )
                    if espera_viva:
                        total_vivo = (
                            float(opcao["caminhada_origem_s"])
                            + espera_viva.esperada_s
                            + float(opcao["viagem_s"])
                            + float(opcao["caminhada_destino_s"])
                        )
                        opcoes_ao_vivo.append(
                            (total_vivo, opcao, previsao_opcao)
                        )

                if opcoes_ao_vivo:
                    total_vivo, opcao, previsao_viva = min(
                        opcoes_ao_vivo, key=lambda item: item[0]
                    )
                    caminhada_s = float(plano.get("caminhada_direta_min", 0)) * 60
                    if caminhada_s and caminhada_s < total_vivo:
                        # Agora há duas estimativas temporais comparáveis: a
                        # caminhada aproximada e a rota com ETA validado. Não
                        # use a ausência da grade GTFS como se fosse esse fato.
                        fontes.insert(0, FONTE_GTFS)
                        fontes.append(FONTE_API)
                        fontes.extend(fontes_operacionais(
                            [str(opcao["linha"])], intencao.datas
                        ))
                        return RespostaFerramenta(
                            (
                                f"Com o ETA ao vivo da linha **{opcao['linha']}**, "
                                f"o trajeto de ônibus leva cerca de "
                                f"**{round(total_vivo / 60)} minutos**. A caminhada "
                                f"aproximada leva cerca de "
                                f"**{plano['caminhada_direta_min']} minutos**, então "
                                "ela é a menor estimativa entre as opções com tempo "
                                "calculável agora."
                            ),
                            list(dict.fromkeys(fontes)),
                            {
                                "tipo": "comparacao_trajeto_com_eta",
                                "melhor_opcao": {"modo": "a_pe"},
                                "onibus": {
                                    "linha": str(opcao["linha"]),
                                    "sentido": str(opcao["sentido"]),
                                    "tempo_total_min": round(total_vivo / 60),
                                    "source": "live",
                                },
                                "caminhada_aproximada_min": plano["caminhada_direta_min"],
                            },
                        )
                    melhor_vivo = {
                        **opcao,
                        "modo": "onibus",
                        "espera_programada_s": 0,
                        "intervalo_programado_s": None,
                        "espera_programada_min": 0,
                        "intervalo_programado_min": None,
                        "total_estimado_s": total_vivo,
                        "total_estimado_min": round(total_vivo / 60),
                    }
                    plano_vivo = {
                        **plano,
                        "melhor": melhor_vivo,
                        "alternativas": [],
                    }
                    resultado_vivo = _resultado_trajeto_publico(
                        plano_vivo, previsao_viva
                    )
                    dados_vivos = resultado_vivo.public_view(facetas)
                    dados_vivos["periodo"] = intencao.rotulo_periodo or "agora"
                    fontes.insert(0, FONTE_GTFS)
                    fontes.append(FONTE_API)
                    fontes.extend(fontes_operacionais(
                        [str(melhor_vivo["linha"])], intencao.datas
                    ))
                    return RespostaFerramenta(
                        renderizar_trajeto(resultado_vivo, facetas),
                        list(dict.fromkeys(fontes)),
                        dados_vivos,
                    )

            if plano.get("ranking_temporal") == "indeterminado":
                # A ordem estrutural serve apenas para apresentar candidatas;
                # sem espera programada ou ETA, ela não é um ranking de tempo.
                opcoes_estruturais: list[dict[str, Any]] = []
                vistas: set[tuple[str, str]] = set()
                for opcao in [melhor, *plano.get("alternativas", [])]:
                    chave = (str(opcao["linha"]), str(opcao["sentido"]))
                    if chave not in vistas:
                        vistas.add(chave)
                        opcoes_estruturais.append(opcao)
                partes = [
                    (
                        f"Há {len(opcoes_estruturais)} opções diretas de ônibus "
                        f"entre **{nome_origem}** e **{nome_destino}**, mas não há "
                        "horário GTFS confiável nem ETA ao vivo para determinar qual "
                        "é mais rápida agora."
                    ),
                    *[
                        f"- **{opcao['linha']}**, sentido **{opcao['sentido']}**: "
                        f"embarque em **{opcao['embarque']}** e desça em "
                        f"**{opcao['desembarque']}** "
                        f"({round(float(opcao['caminhada_destino_m']))} m após o desembarque)."
                        for opcao in opcoes_estruturais
                    ],
                    (
                        "As linhas estão em operação, mas a espera desconhecida "
                        "pode inverter a ordem entre elas."
                    ),
                ]
                if api_sem_eta:
                    partes.append(
                        "A API Olho Vivo foi consultada, mas não publicou ETA "
                        "para esses pontos de embarque agora."
                    )
                fontes.insert(0, FONTE_GTFS)
                fontes.extend(fontes_operacionais(
                    [str(opcao["linha"]) for opcao in opcoes_estruturais],
                    intencao.datas or (referencia_planejamento.date(),),
                ))
                dados_publicos = {
                    "tipo": "trajeto_onibus_sem_horario",
                    "origem": nome_origem,
                    "destino": nome_destino,
                    "periodo": intencao.rotulo_periodo or "dia útil típico",
                    "ranking_temporal": "indeterminado",
                    "melhor_opcao": None,
                    "opcoes_diretas": [
                        {
                            "linha": str(opcao["linha"]),
                            "sentido": str(opcao["sentido"]),
                            "embarque": str(opcao["embarque"]),
                            "desembarque": str(opcao["desembarque"]),
                            "caminhada_apos_desembarque_m": int(opcao["caminhada_destino_m"]),
                        }
                        for opcao in opcoes_estruturais
                    ],
                    "status_programacao": "horario_indisponivel",
                    "status_api": "consultada_sem_eta" if api_sem_eta else "nao_consultada",
                    "fatos_obrigatorios": [
                        valor
                        for opcao in opcoes_estruturais
                        for valor in (
                            str(opcao["linha"]), str(opcao["embarque"]), str(opcao["desembarque"]),
                        )
                    ],
                }
                return RespostaFerramenta(
                    "\n\n".join(partes), list(dict.fromkeys(fontes)), dados_publicos,
                )

            linha_melhor = str(melhor["linha"])
            aviso = str(plano.get("aviso") or aviso_programacao_incompleta(
                linha_melhor, referencia_planejamento.date()
            ))
            partes = [
                f"Para ir de **{nome_origem}** até **{nome_destino}** de ônibus, "
                f"use a linha **{linha_melhor}**, sentido "
                f"**{melhor['sentido']}**.",
                f"Embarque em **{melhor['embarque']}** e desça em "
                f"**{melhor['desembarque']}**.",
                (
                    "A operação da linha nesse período é confirmada pela "
                    "SPTrans, mas a grade GTFS disponível está incompleta; "
                    "por isso não é seguro informar a espera nem o tempo total."
                ),
            ]
            if aviso:
                partes.append(aviso)
            if api_sem_eta:
                partes.append(
                    "A API Olho Vivo também foi consultada, mas não publicou "
                    "um ETA para os pontos de embarque agora."
                )
            if plano.get("caminhada_direta_min"):
                partes.append(
                    "A caminhada aparece apenas como alternativa aproximada de "
                    f"cerca de **{plano['caminhada_direta_min']} minutos**; sem "
                    "horário ou ETA válido, não é seguro dizer qual opção é mais rápida."
                )
            datas_operacionais = intencao.datas or (
                referencia_planejamento.date(),
            )
            fontes.insert(0, FONTE_GTFS)
            fontes.extend(fontes_operacionais(
                [linha_melhor], datas_operacionais
            ))
            fontes = list(dict.fromkeys(fontes))
            dados_publicos = {
                "tipo": "trajeto_onibus_sem_horario",
                "origem": nome_origem,
                "destino": nome_destino,
                "periodo": intencao.rotulo_periodo or "dia útil típico",
                "melhor_opcao": {
                    "modo": "onibus",
                    "linha": linha_melhor,
                    "sentido": str(melhor["sentido"]),
                    "embarque": str(melhor["embarque"]),
                    "desembarque": str(melhor["desembarque"]),
                    "caminhada_ate_embarque_m": int(
                        melhor["caminhada_origem_m"]
                    ),
                    "caminhada_apos_desembarque_m": int(
                        melhor["caminhada_destino_m"]
                    ),
                    "espera_min": None,
                    "tempo_total_min": None,
                },
                "status_programacao": "horario_indisponivel",
                "frases_obrigatorias": [
                    "não é seguro informar a espera nem o tempo total"
                ],
                "status_api": (
                    "consultada_sem_eta" if api_sem_eta else "nao_consultada"
                ),
                "fatos_obrigatorios": [
                    linha_melhor,
                    str(melhor["embarque"]),
                    str(melhor["desembarque"]),
                ],
                "aviso": aviso,
            }
            return RespostaFerramenta(
                "\n\n".join(dict.fromkeys(partes)),
                fontes,
                dados_publicos,
            )

        # Só vale pagar a consulta ao vivo quando a pergunta pede o estado de
        # agora. Se houver ETA, ele substitui a espera programada no contrato e
        # o total é recalculado; nunca anexamos dois relógios incompatíveis.
        previsao = None
        plano_para_resultado = plano
        if token and facetas.tempo_real:
            # O ETA substitui somente a espera da mesma plataforma e do mesmo
            # headsign que o GTFS escolheu. Reavalia as alternativas diretas
            # antes de eleger a melhor, em vez de consultar somente a primeira
            # opção programada.
            opcoes_com_eta: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
            for opcao in [melhor, *plano.get("alternativas", [])]:
                numero_opcao = str(opcao["linha"]).split("-", 1)[0]
                previsao_opcao = cache(
                    (
                        "circulares", "previsao-rota", numero_opcao,
                        normalizar(opcao["embarque"]),
                        normalizar(opcao["sentido"]),
                        str(opcao["embarque_id"]),
                        tuple(dia.isoformat() for dia in intencao.datas),
                        (
                            intencao.restricao_temporal.chave_cache()
                            if intencao.restricao_temporal else ()
                        ),
                    ),
                    TTL_AO_VIVO,
                    lambda numero=numero_opcao, item=opcao: _obter_previsao_sptrans(
                        numero, str(item["embarque"]), token,
                        str(item["sentido"]), str(item["embarque_id"]),
                        intencao.datas,
                        intencao.restricao_temporal,
                    ),
                )
                espera_viva = _melhor_eta_ao_vivo(
                    previsao_opcao, float(opcao["caminhada_origem_s"]),
                )
                recalculada = dict(opcao)
                confianca = "scheduled"
                if espera_viva:
                    espera, confianca = espera_viva
                    recalculada["total_estimado_s"] = (
                        float(opcao["caminhada_origem_s"])
                        + espera.esperada_s
                        + float(opcao["viagem_s"])
                        + float(opcao["caminhada_destino_s"])
                    )
                    recalculada["total_estimado_min"] = round(
                        float(recalculada["total_estimado_s"]) / 60
                    )
                    recalculada["espera_source"] = "live"
                    recalculada["espera_confidence"] = confianca
                qualidade_eta = {"high": 3, "medium": 2, "low": 1, "scheduled": 0}.get(
                    confianca, 0
                )
                chave = (
                    *_chave_ranking_rota(recalculada)[:2],
                    -qualidade_eta,
                    *_chave_ranking_rota(recalculada)[2:],
                )
                opcoes_com_eta.append((chave, recalculada, previsao_opcao))

            opcoes_com_eta.sort(key=lambda item: item[0])
            if opcoes_com_eta:
                _, melhor_recalculada, previsao = opcoes_com_eta[0]
                plano_para_resultado = {
                    **plano,
                    "melhor": melhor_recalculada,
                    "alternativas": [item[1] for item in opcoes_com_eta[1:3]],
                }
            if any(
                item[2].get("api_consultada") or item[2].get("tipo") == "previsao"
                for item in opcoes_com_eta
            ):
                fontes.append(FONTE_API)

        resultado = _resultado_trajeto_publico(plano_para_resultado, previsao)
        texto = renderizar_trajeto(resultado, facetas)
        dados_trajeto = resultado.public_view(facetas)
        if intencao.periodo == "tipico":
            texto += (
                "\n\nEsta orientação considera um **dia útil típico**. "
                "Se você pretende ir hoje, pergunte novamente com “hoje” ou “agora”."
            )
            dados_trajeto["periodo"] = "dia útil típico"
            fatos = list(dados_trajeto.get("fatos_obrigatorios", []))
            fatos.append("dia útil típico")
            dados_trajeto["fatos_obrigatorios"] = fatos
        fontes.insert(0, FONTE_GTFS)
        fontes.extend(fontes_operacionais(
            [str(plano_para_resultado["melhor"]["linha"])],
            intencao.datas or (referencia_planejamento.date(),),
        ))
        fontes = list(dict.fromkeys(fontes))
        return RespostaFerramenta(
            texto,
            fontes,
            dados_trajeto,
        )

    # Perguntas como "quais linhas passam no Biênio?" são uma consulta reversa
    # de parada. Não escolha candidatas pelo catálogo manual: o GTFS é a fonte
    # oficial e deve devolver todas as linhas associadas ao stop_id.
    if not termo_linha and termo_destino:
        atendimento = _linhas_por_ponto_gtfs(
            destino_ou_ponto or "", intencao.datas
        )
        if not atendimento.get("erro"):
            linhas_ponto = atendimento.get("linhas", [])
            if intencao.periodo_explicito:
                partes = [
                    f"{intencao.rotulo_periodo.capitalize()}, a parada "
                    f"**{atendimento['parada']}** tem serviço programado de "
                    f"**{len(linhas_ponto)} linha(s)**:"
                ]
            else:
                partes = [
                    f"No catálogo GTFS oficial da SPTrans, a parada "
                    f"**{atendimento['parada']}** aparece cadastrada como "
                    f"atendida por {len(linhas_ponto)} linhas. Isso indica cadastro "
                    "de itinerário, não circulação em tempo real:"
                ]
            for item in linhas_ponto:
                datas_item = [
                    datetime.fromisoformat(str(valor)).strftime("%d/%m")
                    for valor in item.get("datas", [])
                ]
                sufixo_datas = (
                    " (" + " e ".join(datas_item) + ")"
                    if len(intencao.datas) > 1 and datas_item
                    else ""
                )
                partes.append(
                    f"- **{item['linha']}** — {item['nome']}{sufixo_datas}"
                )
            partes.append(
                f"Total no período consultado: **{len(linhas_ponto)} linha(s)**."
                if intencao.periodo_explicito
                else f"Total oficial cadastrado: **{len(linhas_ponto)} linha(s)**."
            )
            partes.append(_nota_atualizacao_gtfs())
            fontes_atendimento = [FONTE_GTFS]
            fontes_atendimento.extend(
                str(item)
                for item in atendimento.get("fontes_operacionais", [])
            )
            linhas_texto = [str(item["linha"]) for item in linhas_ponto]
            dados_publicos = {
                "tipo": "linhas_por_parada",
                "parada": str(atendimento["parada"]),
                "periodo": intencao.rotulo_periodo or None,
                "natureza": (
                    "servico_programado"
                    if intencao.periodo_explicito
                    else "cadastro_de_itinerario"
                ),
                "linhas": [
                    {
                        "linha": str(item["linha"]),
                        "nome": str(item["nome"]),
                        "datas": list(item.get("datas", [])),
                    }
                    for item in linhas_ponto
                ],
                "total": len(linhas_ponto),
                "numeros_obrigatorios": [len(linhas_ponto)],
                "fatos_obrigatorios": [
                    str(atendimento["parada"]),
                    *linhas_texto,
                ],
            }
            return RespostaFerramenta(
                "\n".join(partes),
                list(dict.fromkeys(fontes_atendimento)),
                dados_publicos,
            )
        return str(atendimento["erro"]), [FONTE_GTFS]

    partes = []
    numero = termo_linha.split("-", 1)[0].upper() if termo_linha else ""
    resumos = _resumo_gtfs(numero) if numero else []
    if numero and not resumos:
        return (
            f"A linha {linha} não aparece no GTFS atual da SPTrans. "
            "Ela pode ter sido desativada, renumerada ou não atender a área da USP.",
            [FONTE_GTFS],
        )

    if numero and atendimento_pedido:
        if not termo_destino:
            return RespostaFerramenta(
                f"Em qual parada você quer verificar se a linha **{linha or numero}** passa?",
                [],
                {
                    "tipo": "esclarecimento_transporte",
                    "linha": str(linha or numero),
                    "campo_necessario": "parada",
                    "fatos_obrigatorios": [str(linha or numero)],
                },
            )
        atendimento = _atendimento_linha_na_parada_gtfs(
            numero, destino_ou_ponto or "", intencao.datas,
        )
        estado = str(atendimento["estado"])
        rotulo_periodo = intencao.rotulo_periodo or "na data informada"
        linha_publica = str((atendimento.get("linhas") or [linha or numero])[0])
        parada_publica = str((atendimento.get("paradas") or [destino_ou_ponto or ""])[0])
        if estado == "atende":
            texto = (
                f"Sim, a linha **{linha_publica}** atende a parada "
                f"**{parada_publica}** {rotulo_periodo}."
            )
        elif estado == "sem_servico":
            texto = (
                f"A linha **{linha_publica}** inclui a parada **{parada_publica}** "
                f"no itinerário, mas não tem serviço programado nessa parada "
                f"{rotulo_periodo}."
            )
        elif estado == "nao_atende":
            texto = (
                f"Não, a linha **{linha or numero}** não atende a parada "
                f"**{destino_ou_ponto}** no GTFS atual."
            )
        else:
            texto = (
                f"Não há dados suficientes para confirmar se a linha "
                f"**{linha or numero}** atende **{destino_ou_ponto}** "
                f"{rotulo_periodo}."
            )
        dados_atendimento = {
            "tipo": "atendimento_linha_parada",
            "estado": estado,
            "linha": linha_publica,
            "parada": parada_publica,
            "periodo": intencao.rotulo_periodo or None,
            "fatos_obrigatorios": [linha_publica, parada_publica],
        }
        return RespostaFerramenta(
            texto,
            [FONTE_GTFS, *fontes_operacionais(
                list(atendimento.get("linhas") or [linha_publica]), intencao.datas,
            )],
            dados_atendimento,
        )

    if numero and not termo_destino and intencao.pede_chegada:
        return RespostaFerramenta(
            f"Em qual parada você quer saber a chegada da linha **{linha or numero}**?",
            [],
            {
                "tipo": "esclarecimento_transporte",
                "linha": str(linha or numero),
                "campo_necessario": "parada",
                "fatos_obrigatorios": [str(linha or numero)],
            },
        )

    # Previsão é o caso prioritário: uma única execução da ferramenta resolve
    # linha, parada e horários, sem exigir outra rodada do modelo/Groq.
    if numero and termo_destino:
        sentido_esperado = _sentido_explicito_da_pergunta(numero, _pergunta)
        if token and intencao.tempo_real:
            def produzir_previsao() -> dict[str, Any]:
                argumentos: dict[str, Any] = {
                    "datas_permitidas": intencao.datas,
                }
                if intencao.restricao_temporal is not None:
                    argumentos["restricao_temporal"] = (
                        intencao.restricao_temporal
                    )
                if sentido_esperado:
                    argumentos["sentido_esperado"] = sentido_esperado
                return _obter_previsao_sptrans(
                    numero,
                    destino_ou_ponto or "",
                    token,
                    **argumentos,
                )

            previsao = cache(
                (
                    "circulares",
                    "previsao",
                    numero,
                    termo_destino,
                    normalizar(sentido_esperado or ""),
                    tuple(dia.isoformat() for dia in intencao.datas),
                    (
                        intencao.restricao_temporal.chave_cache()
                        if intencao.restricao_temporal else ()
                    ),
                ),
                TTL_AO_VIVO,
                produzir_previsao,
            )
        else:
            previsao = _programacao_gtfs(
                numero,
                destino_ou_ponto or "",
                agora,
                sentido_esperado=sentido_esperado,
                datas_permitidas=intencao.datas,
                restricao_temporal=intencao.restricao_temporal,
            )
        if previsao.get("tipo") == "sentido_incompativel":
            sentido = str(previsao.get("sentido_solicitado") or "")
            dados_incompativeis = {
                "tipo": "sentido_incompativel",
                "linha": str(previsao.get("linha") or linha or numero),
                "parada": str(previsao.get("parada") or destino_ou_ponto or ""),
                "sentido_solicitado": sentido,
                "fatos_obrigatorios": [
                    str(previsao.get("linha") or linha or numero),
                    str(previsao.get("parada") or destino_ou_ponto or ""),
                    sentido,
                ],
            }
            return RespostaFerramenta(
                f"A parada **{dados_incompativeis['parada']}** não é compatível "
                f"com o sentido **{sentido}** dessa linha; não usei o sentido oposto.",
                [FONTE_GTFS],
                dados_incompativeis,
            )
        if previsao.get("erro"):
            return str(previsao["erro"]), [FONTE_GTFS]

        if intencao.rotulo_periodo:
            previsao.setdefault("periodo", intencao.rotulo_periodo)

        api_consultada = bool(
            previsao.get("api_consultada")
            or previsao.get("tipo") == "previsao"
            or "veiculos" in previsao
        )
        resultado_chegada = _resultado_chegada_publico(
            previsao,
            api_consultada=api_consultada,
            ponto_pedido=destino_ou_ponto or "",
        )
        facetas_chegada = facetas_da_pergunta(_pergunta)
        texto = renderizar_chegada(
            resultado_chegada,
            detalhes=detalhes or facetas_chegada.explicacao,
        )
        dados_publicos = resultado_chegada.public_view(
            _pergunta,
            detalhes=detalhes or facetas_chegada.explicacao,
        )
        fontes_operacao = fontes_operacionais(
            [str(previsao.get("linha") or linha or numero)],
            intencao.datas,
        )
        if previsao.get("tipo") in {
            "programacao", "sem_servico", "sem_passagem"
        }:
            fontes_programacao = [FONTE_GTFS]

            if api_consultada:
                fontes_programacao.insert(0, FONTE_API)

            usa_planoper = bool(
                previsao.get("programacao_planoper")
            ) or any(
                isinstance(bloco, dict)
                and bloco.get("programacao_planoper")
                for bloco in previsao.get("sentidos", [])
            )

            if usa_planoper:
                fontes_programacao.append(
                    FONTE_PLANOPER
                )

            fontes_programacao.extend(
                fontes_operacao
            )

            return RespostaFerramenta(
                texto,
                list(dict.fromkeys(fontes_programacao)),
                dados_publicos,
            )
        fontes_chegada = [FONTE_API] if api_consultada else []
        fontes_chegada.extend(fontes_operacao)
        return RespostaFerramenta(
            texto, list(dict.fromkeys(fontes_chegada)), dados_publicos
        )

    if numero:
        for resumo in resumos[:2]:
            partes.append(f"### Linha {resumo['linha']} — {resumo['nome']}")
            if resumo["paradas"]:
                partes.append(
                    "**Paradas oficiais do itinerário:** "
                    + ", ".join(resumo["paradas"])
                    + "."
                )
        partes.append(_nota_atualizacao_gtfs())
        return "\n\n".join(partes), [FONTE_GTFS]

    # Sem argumentos, não inventa uma lista de "principais" linhas. Mostra o
    # conjunto efetivamente presente no recorte oficial atual.
    rotas_atuais = sorted(
        (
            (str(rota.get("linha", "")), str(rota.get("nome", "")))
            for rotas in _catalogo_gtfs().get("linhas", {}).values()
            for rota in rotas
        ),
        key=lambda item: normalizar(item[0]),
    )
    partes.append(
        f"O recorte GTFS atual contém {len(rotas_atuais)} variantes de linhas "
        "que possuem ao menos uma parada na área geográfica da USP:"
    )
    partes.extend(f"- {numero_linha} — {nome}" for numero_linha, nome in rotas_atuais)
    partes.append(_nota_atualizacao_gtfs())
    return "\n".join(partes), [FONTE_GTFS]


def _resposta_com_consulta_transporte(
    resposta: tuple[str, list[str]] | RespostaFerramenta,
    consulta: TransitQuery,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Anexa o contrato comum sem alterar a apresentação factual existente."""
    if not isinstance(resposta, RespostaFerramenta):
        return resposta
    dados = dict(resposta.dados_publicos or {})
    dados["consulta_transporte"] = consulta.como_publico()
    kind = str(dados.get("tipo") or "transporte")
    envelope = resultado_consulta_transporte(consulta, kind, dados)
    return RespostaFerramenta(
        resposta.texto,
        resposta.fontes,
        dados,
        resultado_transporte=envelope,
    )


def consultar_circulares(
    linha: str | None = None,
    destino_ou_ponto: str | None = None,
    origem: str | None = None,
    detalhes: bool = False,
    _pergunta: str | None = None,
    _historico: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Interpreta uma consulta flexível antes de delegar aos motores atuais."""
    # A LLM pode fornecer entidades explícitas pela tool call; a pergunta fica
    # disponível para facetas e período, mas nunca para recalcular fatos.
    consulta = interpretar_consulta_transporte(
        _pergunta,
        origin=origem,
        destination=destino_ou_ponto if origem else None,
        line=linha,
        stop=destino_ou_ponto if not origem else None,
        now=datetime.now(FUSO_SP),
        interpretation="tool_arguments" if any((linha, destino_ou_ponto, origem)) else "deterministic",
    )
    # Deíticos de parada ("lá", "ali", "nesse ponto") podem aproveitar
    # somente o destino inequívoco de uma pergunta anterior do usuário. Isso
    # também deixa a TransitQuery final refletir a parada realmente consultada.
    linha_contextual = linha or consulta.entities.line
    if (
        linha_contextual
        and not origem
        and not destino_ou_ponto
        and _pergunta_pede_atendimento_de_linha(_pergunta)
        and _historico
    ):
        from uspapo.roteamento import _ponto_recente_associado

        ponto_contextual = _ponto_recente_associado(
            str(linha_contextual), _historico,
        )
        if ponto_contextual:
            linha = str(linha_contextual)
            destino_ou_ponto = ponto_contextual
            consulta = interpretar_consulta_transporte(
                _pergunta,
                line=linha,
                stop=destino_ou_ponto,
                now=datetime.now(FUSO_SP),
                interpretation="contextual_user_message",
            )
    if (
        _pergunta_pede_atendimento_de_linha(_pergunta)
        and not (linha or consulta.entities.line)
        and re.search(r"\b(?:la|ali|nesse\s+ponto|neste\s+ponto)\b", normalizar(_pergunta or ""))
    ):
        texto = "Qual linha e qual parada você quer verificar?"
        return _resposta_com_consulta_transporte(
            RespostaFerramenta(
                texto,
                [],
                {
                    "tipo": "esclarecimento_transporte",
                    "campos_necessarios": ["linha", "parada"],
                    "fatos_obrigatorios": [],
                },
            ),
            consulta,
        )
    if consulta.task == "service_info" and (
        consulta.facets.service_window
        or not (consulta.entities.line and consulta.entities.stop)
    ):
        # Não há ainda um motor de primeiro/último horário. Recusar a resposta
        # parcial é mais seguro do que reutilizar o motor de próxima chegada.
        texto = (
            "Entendi que você quer a operação da linha, mas ainda não calculo "
            "com segurança o primeiro ou último horário. Posso informar as "
            "próximas chegadas, um trajeto direto ou as linhas de uma parada."
        )
        dados = {
            "tipo": "consulta_transporte_geral",
            "status": "nao_suportada_ainda",
            "fatos_obrigatorios": [],
        }
        return _resposta_com_consulta_transporte(
            RespostaFerramenta(texto, [], dados), consulta,
        )
    resposta = _consultar_circulares_calcular(
        linha=linha,
        destino_ou_ponto=destino_ou_ponto,
        origem=origem,
        detalhes=detalhes,
        _pergunta=_pergunta,
        _historico=_historico,
    )
    return _resposta_com_consulta_transporte(resposta, consulta)


def registrar(registro: Registro) -> None:
    """Registra a ferramenta consultar_circulares no registro do backend."""
    registro.ferramenta(
        nome="consultar_circulares",
        descricao=(
            "Consulta o catálogo GTFS atual e a API Olho Vivo da SPTrans para "
            "itinerários, paradas, sentidos e previsões dos ônibus que atendem "
            "a USP (Cidade Universitária / Butantã). Os nomes das linhas e das "
            "paradas vêm dos dados oficiais atuais; não use uma lista manual nem "
            "deduza o embarque pelo nome da linha. "
            "Use esta ferramenta sempre que a pergunta mencionar ônibus, circular, "
            "linha, ponto, parada, chegada ou horário de ônibus. Quando o aluno "
            "perguntar quando uma linha chega a um local, envie tanto `linha` "
            "quanto `destino_ou_ponto`; a ferramenta devolve os horários em uma "
            "única chamada. Quando perguntar qual é o melhor ônibus ou como ir de "
            "um local a outro, envie `origem` e `destino_ou_ponto`; a ferramenta "
            "compara caminhada, sentido, percurso e frequência programada."
        ),
        parametros={
            "type": "object",
            "properties": {
                "linha": {
                    "type": "string",
                    "description": (
                        "Número oficial da linha de ônibus (ex: '8012', '8082', "
                        "'8084-10', '8022'). Omita se o aluno perguntar de forma "
                        "genérica."
                    ),
                },
                "destino_ou_ponto": {
                    "type": "string",
                    "description": (
                        "Destino ou instituto desejado (ex: 'Poli', 'FFLCH', "
                        "'Metrô Butantã', 'FEA', 'CRUSP', 'Biênio'). Para previsão "
                        "de chegada, este campo é obrigatório."
                    ),
                },
                "origem": {
                    "type": "string",
                    "description": (
                        "Local de partida quando o aluno pedir o melhor ônibus ou "
                        "um trajeto (ex: 'P1', 'Central', 'Reitoria', 'Biênio', "
                        "'Metrô Butantã'). Central significa o Restaurante "
                        "Universitário Central; Administração Central e Reitoria "
                        "são locais distintos."
                    ),
                },
                "detalhes": {
                    "type": "boolean",
                    "description": (
                        "Use true somente quando o aluno pedir para explicar o "
                        "cálculo, a origem dos dados ou a confiabilidade."
                    ),
                },
            },
        },
    )(consultar_circulares)
