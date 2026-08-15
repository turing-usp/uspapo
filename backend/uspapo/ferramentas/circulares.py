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
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from uspapo.ferramentas import RespostaFerramenta, Registro, cache, casa, normalizar
from uspapo.locais_usp import (
    CATALOGO_LOCAIS,
    coordenada_local,
    dados_local,
    resolver_local,
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

BASE_URL = "https://api.olhovivo.sptrans.com.br/v2.1"
FONTE_API = "https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/"
FONTE_GTFS = "https://www.sptrans.com.br/desenvolvedores/"
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
# O pipeline atualiza o recorte diariamente. Depois de uma semana sem uma
# geração bem-sucedida, a resposta continua útil, mas passa a avisar claramente
# que o dado está vencido em vez de aparentar atualidade.
MAX_IDADE_GTFS_DIAS = 7

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
        print(f"[circulares] Falha na autenticacao SPTrans: {err}")
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
        por_id = [
            parada
            for parada in paradas
            if str(parada.get("cp", "")) == str(parada_id_esperada)
        ]
        if por_id:
            return por_id

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


def _programacao_gtfs(
    numero: str,
    ponto: str,
    agora: datetime | None = None,
    sentido_esperado: str | None = None,
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
            return normalizar(destino_viagem) == normalizar(sentido_esperado)

        todas_no_sentido = [item for item in todas if atende_sentido(item)]
        if todas_no_sentido:
            todas = todas_no_sentido
            candidatos = [
                item for item in candidatos if atende_sentido(item)
            ]

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
        programacoes = []
        for destino in destinos:
            programacao = _programacao_gtfs(
                numero,
                ponto,
                agora,
                sentido_esperado=destino,
            )
            if not programacao.get("erro"):
                programacoes.append(programacao)
        if programacoes:
            return {
                "tipo": "programacao",
                "linha": programacoes[0].get("linha", numero),
                "parada": ponto,
                "horarios": [],
                "instantes": [],
                "sentidos": programacoes,
            }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    chegadas: set[datetime] = set()
    faixas_frequencia: set[tuple[datetime, datetime, int]] = set()
    for rota, viagem, parada in candidatos:
        deslocamento = int(parada.get("deslocamento", 0))
        # Horários GTFS podem ultrapassar 24:00 e pertencem ao dia de serviço
        # anterior. À 00:30, por exemplo, uma viagem 24:45 de sexta ainda é uma
        # chegada futura válida no sábado civil.
        for dias_a_frente in range(-1, 8):
            dia_servico = instante.date() + timedelta(days=dias_a_frente)
            if not _servico_ativo(catalogo, str(viagem.get("servico", "")), dia_servico):
                continue
            meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
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
                            if chegada >= instante - timedelta(seconds=30):
                                chegadas.add(chegada)
                    else:
                        inicio_ponto = meia_noite + timedelta(
                            seconds=inicio + deslocamento
                        )
                        fim_ponto = meia_noite + timedelta(
                            seconds=fim + deslocamento
                        )
                        if fim_ponto > instante:
                            faixas_frequencia.add(
                                (inicio_ponto, fim_ponto, intervalo)
                            )
            else:
                chegada = meia_noite + timedelta(seconds=int(parada["horario"]))
                if chegada >= instante - timedelta(seconds=30):
                    chegadas.add(chegada)

    proximas = sorted(chegadas)[:3]
    faixas = sorted(faixas_frequencia)[:3]
    if not proximas and not faixas:
        return {"erro": "Nao ha horario programado no periodo coberto pelo GTFS."}

    rota, viagem_escolhida, parada = candidatos[0]
    horarios = [
        chegada.strftime("%H:%M")
        if chegada.date() == instante.date()
        else chegada.strftime("%d/%m as %H:%M")
        for chegada in proximas
    ]
    resultado = {
        "tipo": "programacao",
        "linha": rota.get("linha", numero),
        "parada": parada.get("nome", ponto),
        "parada_id": parada_escolhida_id,
        "destino": viagem_escolhida.get("destino", ""),
        "horarios": horarios,
        "instantes": [chegada.isoformat() for chegada in proximas],
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


def _linhas_por_ponto_gtfs(ponto: str) -> dict[str, Any]:
    """Inverte o GTFS: dada uma parada, devolve todas as linhas que a servem."""
    catalogo = _catalogo_gtfs()
    ocorrencias: list[tuple[dict[str, Any], dict[str, Any]]] = []
    textuais: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for rotas in catalogo.get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    item = (rota, parada)
                    ocorrencias.append(item)
                    if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                        textuais.append(item)

    candidatas = textuais
    coordenada = _coordenada_ponto(ponto)
    if not candidatas:
        if coordenada and ocorrencias:
            menor = min(
                _distancia_parada_gtfs(parada, coordenada)
                for _rota, parada in ocorrencias
            )
            if menor <= RAIO_ACESSO_M:
                candidatas = sorted(
                    (
                        item for item in ocorrencias
                        if _distancia_parada_gtfs(item[1], coordenada)
                        <= min(menor + 40, RAIO_ACESSO_M)
                    ),
                    key=lambda item: _distancia_parada_gtfs(item[1], coordenada),
                )
    elif coordenada:
        candidatas.sort(
            key=lambda item: _distancia_parada_gtfs(item[1], coordenada)
        )
    if not candidatas:
        return {"erro": f"Não localizei a parada '{ponto}' no GTFS da SPTrans."}

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
        "linhas": sorted(linhas.values(), key=lambda item: normalizar(item["linha"])),
    }


def _chave_local(ponto: str) -> str | None:
    return ponto if ponto in CATALOGO_LOCAIS else resolver_local(ponto)


def _proxima_passagem_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    depois_de: datetime,
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
                            melhor is None or passagem < melhor
                        ):
                            melhor = passagem
                else:
                    # exact_times=0 descreve uma janela com headway, não uma
                    # tabela de partidas. Fora da janela, só podemos dizer
                    # quando a próxima faixa começa.
                    inicio_ponto = meia_noite + timedelta(
                        seconds=inicio + deslocamento
                    )
                    fim_ponto = meia_noite + timedelta(
                        seconds=fim + deslocamento
                    )
                    if fim_ponto > depois_de:
                        passagem = max(inicio_ponto, depois_de)
                        if melhor is None or passagem < melhor:
                            melhor = passagem
        else:
            passagem = meia_noite + timedelta(seconds=int(parada["horario"]))
            if passagem >= depois_de and (melhor is None or passagem < melhor):
                melhor = passagem
    return melhor


def _espera_media_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    pronto_para_embarcar: datetime,
) -> tuple[float, float | None]:
    """Espera esperada; frequências não são tratadas como partidas exatas."""
    servico = str(viagem.get("servico", ""))
    deslocamento = int(parada.get("deslocamento", 0))
    for recuo in (1, 0):
        dia_servico = pronto_para_embarcar.date() - timedelta(days=recuo)
        if not _servico_ativo(catalogo, servico, dia_servico):
            continue
        meia_noite_servico = datetime.combine(
            dia_servico, time.min, tzinfo=FUSO_SP
        )
        segundos_servico = int(
            (pronto_para_embarcar - meia_noite_servico).total_seconds()
        )
        for frequencia in viagem.get("frequencias", []):
            inicio_no_ponto = int(frequencia["inicio"]) + deslocamento
            fim_no_ponto = int(frequencia["fim"]) + deslocamento
            if inicio_no_ponto <= segundos_servico < fim_no_ponto:
                # exact_times=1 é uma grade de partidas; nesse caso a espera
                # correta é até o próximo múltiplo, calculado logo abaixo.
                if int(frequencia.get("exact_times", 0)) == 1:
                    continue
                intervalo_min = int(frequencia["intervalo"]) / 60
                return intervalo_min / 2, intervalo_min

    proxima = _proxima_passagem_gtfs(
        catalogo, viagem, parada, pronto_para_embarcar
    )
    if proxima is None:
        return float("inf"), None
    return (
        (proxima - pronto_para_embarcar).total_seconds() / 60,
        None,
    )


def _planejar_trajeto_gtfs(
    origem: str, destino: str, agora: datetime | None = None
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
                        espera, intervalo = _espera_media_gtfs(
                            catalogo, viagem, embarque, pronto_para_embarcar
                        )
                        if not math.isfinite(espera):
                            continue
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
                        espera_s = espera * 60
                        total_s = (
                            caminhada_origem_s + espera_s + viagem_s
                            + caminhada_destino_s
                        )
                        candidatos.append({
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
                            "caminhada_origem_m": round(caminhada_origem),
                            "caminhada_destino_m": round(caminhada_destino),
                            "caminhada_origem_s": caminhada_origem_s,
                            "caminhada_destino_s": caminhada_destino_s,
                            "espera_programada_s": espera_s,
                            "intervalo_programado_s": (
                                intervalo * 60 if intervalo is not None else None
                            ),
                            "viagem_s": viagem_s,
                            "total_estimado_s": total_s,
                            "espera_programada_min": round(espera),
                            "intervalo_programado_min": (
                                round(intervalo) if intervalo is not None else None
                            ),
                            "viagem_min": round(viagem_min),
                            "total_estimado_min": round(total_s / 60),
                            "passa_metro_butanta": passa_metro,
                        })

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
    }

    caminhada = {
        "modo": "a_pe",
        "distancia_aproximada_m": caminhada_direta_m,
        "total_estimado_min": caminhada_direta_min,
    }
    if not opcoes:
        return {
            **plano_base,
            "melhor": caminhada,
            "alternativas": [],
            "aviso": "Não encontrei uma linha direta; a opção coberta é caminhar.",
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


def _espera_ao_vivo(
    previsao: dict[str, Any], caminhada_origem_s: float
) -> EstimativaEspera | None:
    """Converte ETAs da parada em espera após a caminhada até o embarque."""
    if previsao.get("tipo") != "previsao":
        return None
    referencia = _instante_referencia_sptrans(previsao.get("hr"))
    candidatas: list[tuple[float, str]] = []
    for veiculo in previsao.get("veiculos", []):
        horario = str(veiculo.get("t") or "").strip()
        try:
            hora, minuto = (int(parte) for parte in horario.split(":")[:2])
            chegada = datetime.combine(
                referencia.date(), time(hora, minuto), tzinfo=FUSO_SP
            )
            if chegada < referencia - timedelta(seconds=30):
                chegada += timedelta(days=1)
            ate_chegada_s = (chegada - referencia).total_seconds()
        except (TypeError, ValueError):
            continue
        # Um ônibus que passa antes de o aluno alcançar o ponto não pode ser
        # usado para recalcular o tempo total.
        if ate_chegada_s + 30 >= caminhada_origem_s:
            candidatas.append((max(0, ate_chegada_s), horario))
    if not candidatas:
        return None
    ate_chegada_s, horario = min(candidatas)
    espera_depois_da_caminhada_s = max(0, ate_chegada_s - caminhada_origem_s)
    return EstimativaEspera(
        base="eta_ao_vivo",
        esperada_s=espera_depois_da_caminhada_s,
        minima_s=espera_depois_da_caminhada_s,
        maxima_s=espera_depois_da_caminhada_s,
        eta=horario,
        observado_em=str(previsao.get("hr") or "") or None,
    )


def _resultado_trajeto_publico(
    plano: dict[str, Any],
    previsao: dict[str, Any] | None = None,
) -> ResultadoTrajeto:
    melhor = plano["melhor"]
    intervalo_s = melhor.get("intervalo_programado_s")
    espera_programada_s = float(melhor["espera_programada_s"])
    if intervalo_s is not None:
        espera = EstimativaEspera(
            base="frequencia_media",
            esperada_s=espera_programada_s,
            minima_s=0,
            maxima_s=float(intervalo_s),
            intervalo_s=float(intervalo_s),
        )
    else:
        espera = EstimativaEspera(
            base="programacao_exata",
            esperada_s=espera_programada_s,
            minima_s=espera_programada_s,
            maxima_s=espera_programada_s,
        )
    ao_vivo = _espera_ao_vivo(
        previsao or {}, float(melhor["caminhada_origem_s"])
    )
    if ao_vivo:
        espera = ao_vivo

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
        previsao_consultada=previsao is not None,
        veiculos_ativos=(
            int(previsao["veiculos_ativos"])
            if previsao and previsao.get("veiculos_ativos") is not None
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
        aviso=_aviso_gtfs_se_necessario(),
    )


def _resultado_chegada_publico(
    previsao: dict[str, Any],
    *,
    api_consultada: bool,
    ponto_pedido: str,
) -> ResultadoChegada:
    """Traduz respostas SPTrans/GTFS para um contrato estável de apresentação."""
    if previsao.get("tipo") == "programacao":
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
                faixas_programadas=faixas,
            ))
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
            aviso=_aviso_gtfs_se_necessario(),
        )

    veiculos = tuple(
        PrevisaoChegada(
            horario=str(item["t"]),
            acessivel=(
                bool(item["a"]) if item.get("a") is not None else None
            ),
        )
        for item in previsao.get("veiculos", [])[:3]
        if isinstance(item, dict) and item.get("t")
    )
    linha = str(previsao.get("linha") or "")
    parada = str(previsao.get("parada") or ponto_pedido)
    return ResultadoChegada(
        linha=linha,
        parada=parada,
        sentidos=(PassagensPorSentido(
            linha=linha,
            parada=parada,
            sentido=str(previsao.get("destino") or ""),
            previsoes_ao_vivo=veiculos,
        ),),
        api_consultada=api_consultada,
        observado_em=str(previsao.get("hr") or "") or None,
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
    destino = linha.get("ts") if linha.get("sl") == 1 else linha.get("tp")
    return str(destino or "")


def _obter_previsao_sptrans(
    numero: str,
    ponto: str,
    token: str,
    sentido_esperado: str | None = None,
    parada_id_esperada: str | None = None,
) -> dict[str, Any]:
    """Busca a previsão linha+ponto usando uma única sessão autenticada."""
    session = requests.Session()
    if not _autenticar_sptrans(session, token):
        programacao = _programacao_gtfs(
            numero, ponto, sentido_esperado=sentido_esperado
        )
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A autenticação da API Olho Vivo falhou."
        return programacao

    try:
        linhas = cache(
            ("circulares", "linhas", normalizar(numero)),
            TTL_LINHAS,
            lambda: _linhas_sptrans(session, numero),
        )
        if not linhas:
            return _programacao_gtfs(
                numero, ponto, sentido_esperado=sentido_esperado
            )
        if sentido_esperado:
            linhas_no_sentido = [
                item
                for item in linhas
                if (
                    casa(sentido_esperado, _destino_linha_sptrans(item))
                    or casa(_destino_linha_sptrans(item), sentido_esperado)
                )
            ]
            if not linhas_no_sentido:
                programacao = _programacao_gtfs(
                    numero, ponto, sentido_esperado=sentido_esperado
                )
                if not programacao.get("erro"):
                    programacao["aviso_api"] = (
                        "A API Olho Vivo não identificou o sentido escolhido; "
                        "nenhum ETA do sentido oposto foi usado."
                    )
                return programacao
            linhas = linhas_no_sentido

        tentativas: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for linha_api in linhas:
            codigo_linha = int(linha_api["cl"])
            previsoes = cache(
                ("circulares", "previsoes-linha", codigo_linha),
                TTL_AO_VIVO,
                lambda codigo=codigo_linha: _previsoes_linha(session, codigo),
            )
            paradas = previsoes.get("ps", []) if isinstance(previsoes, dict) else []
            for parada in _ordenar_paradas(
                paradas, ponto, parada_id_esperada
            )[:2]:
                tentativas.append((linha_api, parada, previsoes.get("hr", "")))

        if not tentativas:
            programacao = _programacao_gtfs(
                numero, ponto, sentido_esperado=sentido_esperado
            )
            if programacao.get("erro"):
                return programacao

            veiculos: dict[str, dict[str, Any]] = {}
            horarios_referencia: list[str] = []
            for linha_api in linhas:
                codigo_linha = int(linha_api["cl"])
                posicoes = cache(
                    ("circulares", "posicoes-linha", codigo_linha),
                    TTL_AO_VIVO,
                    lambda codigo=codigo_linha: _posicoes_linha(session, codigo),
                )
                if posicoes.get("hr"):
                    horarios_referencia.append(str(posicoes["hr"]))
                for veiculo in posicoes.get("vs", []):
                    if not isinstance(veiculo, dict):
                        continue
                    identificador = str(veiculo.get("p") or id(veiculo))
                    veiculos[identificador] = veiculo
            programacao.update({
                "hr": max(horarios_referencia, default=""),
                "veiculos_ativos": len(veiculos),
            })
            return programacao

        melhor_sem_veiculos = None
        for linha_api, parada, horario_referencia in tentativas[:4]:
            veiculos = [
                veiculo for veiculo in parada.get("vs", [])
                if isinstance(veiculo, dict) and veiculo.get("t")
            ]
            resultado = {
                "tipo": "previsao",
                "hr": horario_referencia,
                "linha": f"{linha_api.get('lt', numero)}-{linha_api.get('tl', 10)}",
                "sentido": linha_api.get("sl"),
                "destino": _destino_linha_sptrans(linha_api),
                "parada": parada.get("np"),
                "endereco": parada.get("ed", ""),
                "veiculos": veiculos,
            }
            if veiculos:
                return resultado
            melhor_sem_veiculos = melhor_sem_veiculos or resultado
        return melhor_sem_veiculos or {"erro": "A SPTrans não devolveu previsão para esse ponto."}
    except (requests.RequestException, ValueError, TypeError, KeyError) as err:
        print(f"[circulares] Erro ao consultar previsão: {type(err).__name__}: {err}")
        programacao = _programacao_gtfs(
            numero, ponto, sentido_esperado=sentido_esperado
        )
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A API Olho Vivo não respondeu agora."
        return programacao


def consultar_circulares(
    linha: str | None = None,
    destino_ou_ponto: str | None = None,
    origem: str | None = None,
    detalhes: bool = False,
    _pergunta: str | None = None,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Consulta itinerários ou previsão de chegada em uma parada."""
    fontes: list[str] = []
    token = os.getenv("SPTRANS_TOKEN", "").strip()

    termo_linha = normalizar(linha or "")
    termo_destino = normalizar(destino_ou_ponto or "")
    termo_origem = normalizar(origem or "")

    if termo_origem and termo_destino:
        plano = _planejar_trajeto_gtfs(
            origem or "", destino_ou_ponto or ""
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
            partes.append(
                f"De **{nome_origem}** até **{nome_destino}**, a melhor opção é "
                f"ir a pé: são cerca de **{melhor['total_estimado_min']} minutos** "
                f"({melhor['distancia_aproximada_m']} m)."
            )
            if plano.get("aviso"):
                partes.append(str(plano["aviso"]))
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

        # Só vale pagar a consulta ao vivo quando a pergunta pede o estado de
        # agora. Se houver ETA, ele substitui a espera programada no contrato e
        # o total é recalculado; nunca anexamos dois relógios incompatíveis.
        previsao = None
        if token and facetas.tempo_real:
            numero = str(melhor["linha"]).split("-", 1)[0]
            previsao = cache(
                (
                    "circulares", "previsao-rota", numero,
                    normalizar(melhor["embarque"]),
                    normalizar(melhor["sentido"]),
                    str(melhor["embarque_id"]),
                ),
                TTL_AO_VIVO,
                lambda: _obter_previsao_sptrans(
                    numero,
                    str(melhor["embarque"]),
                    token,
                    str(melhor["sentido"]),
                    str(melhor["embarque_id"]),
                ),
            )
            fontes.append(FONTE_API)

        resultado = _resultado_trajeto_publico(plano, previsao)
        texto = renderizar_trajeto(resultado, facetas)
        fontes.insert(0, FONTE_GTFS)
        fontes = list(dict.fromkeys(fontes))
        return RespostaFerramenta(
            texto,
            fontes,
            resultado.public_view(facetas),
        )

    # Perguntas como "quais linhas passam no Biênio?" são uma consulta reversa
    # de parada. Não escolha candidatas pelo catálogo manual: o GTFS é a fonte
    # oficial e deve devolver todas as linhas associadas ao stop_id.
    if not termo_linha and termo_destino:
        atendimento = _linhas_por_ponto_gtfs(destino_ou_ponto or "")
        if not atendimento.get("erro"):
            linhas_ponto = atendimento.get("linhas", [])
            partes = [
                f"Segundo o GTFS oficial da SPTrans, a parada "
                f"{atendimento['parada']} é atendida por {len(linhas_ponto)} linhas:"
            ]
            partes.extend(
                f"- {item['linha']} — {item['nome']}" for item in linhas_ponto
            )
            partes.append(
                f"Total oficial cadastrado para essa parada: {len(linhas_ponto)} linhas."
            )
            partes.append(_nota_atualizacao_gtfs())
            return "\n".join(partes), [FONTE_GTFS]
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

    # Previsão é o caso prioritário: uma única execução da ferramenta resolve
    # linha, parada e horários, sem exigir outra rodada do modelo/Groq.
    if numero and termo_destino:
        if token:
            previsao = cache(
                ("circulares", "previsao", numero, termo_destino),
                TTL_AO_VIVO,
                lambda: _obter_previsao_sptrans(
                    numero, destino_ou_ponto or "", token
                ),
            )
        else:
            previsao = _programacao_gtfs(numero, destino_ou_ponto or "")
        if previsao.get("erro"):
            return str(previsao["erro"]), [FONTE_GTFS]

        resultado_chegada = _resultado_chegada_publico(
            previsao,
            api_consultada=bool(token),
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
        if previsao.get("tipo") == "programacao":
            fontes_programacao = [FONTE_GTFS]
            if token:
                fontes_programacao.insert(0, FONTE_API)
            return RespostaFerramenta(
                texto,
                fontes_programacao,
                dados_publicos,
            )
        return RespostaFerramenta(texto, [FONTE_API], dados_publicos)

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
