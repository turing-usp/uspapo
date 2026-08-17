"""Cliente da API Olho Vivo da SPTrans, com queda para a programação oficial.

A Olho Vivo fornece posições de GPS e, quando disponíveis, previsões de chegada
em tempo real. Ela exige um token gratuito (``SPTRANS_TOKEN``) e tem dois limites
que definem o desenho deste módulo:

* o catálogo ``/Parada/*`` cobre apenas corredores e devolve lista vazia dentro
  da USP, então quem responde por parada aqui é ``/Previsao/Linha``, que traz
  todas as paradas monitoradas da linha;
* a previsão pode simplesmente não existir para um ponto, mesmo com ônibus em
  circulação.

Por isso nenhuma falha vira erro para o aluno: toda saída deste módulo é ou uma
previsão ao vivo, ou a programação do ``gtfs_sptrans`` acompanhada de um
``aviso_api`` dizendo o que não deu certo. O chamador distingue os dois casos
pelo campo ``tipo`` e só credita a API como fonte quando ela produziu o ETA.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
import math
from typing import Any

import requests

from uspapo import gtfs_sptrans
from uspapo.ferramentas import cache, casa, normalizar
from uspapo.transporte_resposta import EstimativaEspera

BASE_URL = "https://api.olhovivo.sptrans.com.br/v2.1"
FONTE = "https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/"
TIMEOUT = 10
# Posições de GPS e previsões mudam rápido: 20 segundos.
# Mapeamento de códigos de linha na SPTrans: 24 horas.
TTL_AO_VIVO = 20
TTL_LINHAS = 86400
MAX_TENTATIVAS_PARADA = 4

CABECALHOS = {"User-Agent": "USPapo/1.0 (chatbot de alunos da USP)"}


# ─────────────────────────────────────────────
# Rede
# ─────────────────────────────────────────────
def _autenticar(sessao: requests.Session, token: str) -> bool:
    """Autentica a sessão do requests com o token da SPTrans."""
    try:
        resposta = sessao.post(
            f"{BASE_URL}/Login/Autenticar?token={token}",
            headers=CABECALHOS,
            timeout=TIMEOUT,
        )
        return resposta.status_code == 200 and resposta.json() is True
    except Exception as erro:
        print(f"[olhovivo] falha na autenticação: {type(erro).__name__}: {erro}")
        return False


def _get_json(sessao: requests.Session, caminho: str, **parametros: Any) -> Any:
    resposta = sessao.get(
        f"{BASE_URL}/{caminho}",
        params=parametros,
        headers=CABECALHOS,
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def _linhas(sessao: requests.Session, numero: str) -> list[dict[str, Any]]:
    """Resolve os códigos por sentido; eles podem mudar e não devem ser fixos."""
    dados = _get_json(sessao, "Linha/Buscar", termosBusca=numero)
    if not isinstance(dados, list):
        return []
    alvo = normalizar(numero).split("-")[0]
    return [
        item for item in dados
        if isinstance(item, dict) and normalizar(item.get("lt", "")) == alvo
    ]


def _previsoes_linha(sessao: requests.Session, codigo_linha: int) -> dict[str, Any]:
    """Previsões e paradas da linha, inclusive fora dos corredores."""
    dados = _get_json(sessao, "Previsao/Linha", codigoLinha=codigo_linha)
    return dados if isinstance(dados, dict) else {}


def _posicoes_linha(sessao: requests.Session, codigo_linha: int) -> dict[str, Any]:
    dados = _get_json(sessao, "Posicao/Linha", codigoLinha=codigo_linha)
    return dados if isinstance(dados, dict) else {}


def destino_da_linha(linha: dict[str, Any]) -> str:
    """Destino operacional conforme o sentido documentado pela SPTrans."""
    destino = linha.get("ts") if linha.get("sl") == 1 else linha.get("tp")
    return str(destino or "")


# ─────────────────────────────────────────────
# Escolha da parada monitorada
# ─────────────────────────────────────────────
def _distancia_parada_api(
    parada: dict[str, Any], coordenada: tuple[float, float]
) -> float:
    """A Olho Vivo publica a coordenada como ``py``/``px``, não latitude/longitude."""
    lat, lon = coordenada
    dy = (float(parada.get("py", 0)) - lat) * 111_320
    dx = (float(parada.get("px", 0)) - lon) * 111_320 * math.cos(math.radians(lat))
    return math.hypot(dx, dy)


def ordenar_paradas(
    paradas: list[dict[str, Any]],
    ponto: str,
    parada_id_esperada: str | None = None,
) -> list[dict[str, Any]]:
    """Prioriza o stop_id que o planejador escolheu, depois nome, depois distância."""
    if parada_id_esperada:
        por_id = [
            parada for parada in paradas
            if str(parada.get("cp", "")) == str(parada_id_esperada)
        ]
        if por_id:
            return por_id

    textuais = [
        parada for parada in paradas
        if (
            gtfs_sptrans.mesmo_nome(ponto, str(parada.get("np", "")))
            or gtfs_sptrans.mesmo_nome(ponto, str(parada.get("ed", "")))
        )
    ]
    if textuais:
        return textuais

    coordenada = gtfs_sptrans.coordenada_do_ponto(ponto)
    if not coordenada:
        return []
    perto = [
        parada for parada in paradas
        if _distancia_parada_api(parada, coordenada) <= gtfs_sptrans.RAIO_ACESSO_M
    ]
    return sorted(
        perto, key=lambda item: _distancia_parada_api(item, coordenada)
    )


# ─────────────────────────────────────────────
# Espera ao vivo
# ─────────────────────────────────────────────
def instante_referencia(horario: str | None) -> datetime:
    """Converte o ``hr`` da API no instante de hoje mais próximo de agora."""
    agora = datetime.now(gtfs_sptrans.FUSO_SP)
    try:
        hora, minuto = (int(parte) for parte in str(horario).split(":")[:2])
        referencia = datetime.combine(
            agora.date(), time(hora, minuto), tzinfo=gtfs_sptrans.FUSO_SP
        )
        if referencia - agora > timedelta(hours=12):
            referencia -= timedelta(days=1)
        elif agora - referencia > timedelta(hours=12):
            referencia += timedelta(days=1)
        return referencia
    except (TypeError, ValueError):
        return agora


def espera_ao_vivo(
    previsao: dict[str, Any], caminhada_origem_s: float
) -> EstimativaEspera | None:
    """Converte ETAs da parada em espera após a caminhada até o embarque."""
    if previsao.get("tipo") != "previsao":
        return None
    referencia = instante_referencia(previsao.get("hr"))
    candidatas: list[tuple[float, str]] = []
    for veiculo in previsao.get("veiculos", []):
        horario = str(veiculo.get("t") or "").strip()
        try:
            hora, minuto = (int(parte) for parte in horario.split(":")[:2])
            chegada = datetime.combine(
                referencia.date(), time(hora, minuto), tzinfo=gtfs_sptrans.FUSO_SP
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
    espera_s = max(0, ate_chegada_s - caminhada_origem_s)
    return EstimativaEspera(
        base="eta_ao_vivo",
        esperada_s=espera_s,
        minima_s=espera_s,
        maxima_s=espera_s,
        eta=horario,
        observado_em=str(previsao.get("hr") or "") or None,
    )


# ─────────────────────────────────────────────
# Orquestração
# ─────────────────────────────────────────────
def _programacao_com_aviso(
    numero: str, ponto: str, sentido_esperado: str | None, aviso: str
) -> dict[str, Any]:
    """Cai para o GTFS explicando por quê; erro do GTFS tem prioridade."""
    resultado = gtfs_sptrans.programacao(
        numero, ponto, sentido_esperado=sentido_esperado
    )
    if not resultado.get("erro") and aviso:
        resultado["aviso_api"] = aviso
    return resultado


def previsao_de_chegada(
    numero: str,
    ponto: str,
    token: str,
    sentido_esperado: str | None = None,
    parada_id_esperada: str | None = None,
) -> dict[str, Any]:
    """Busca a previsão linha+ponto usando uma única sessão autenticada."""
    with requests.Session() as sessao:
        if not _autenticar(sessao, token):
            return _programacao_com_aviso(
                numero, ponto, sentido_esperado,
                "A autenticação da API Olho Vivo falhou.",
            )
        try:
            return _previsao_autenticada(
                sessao, numero, ponto, sentido_esperado, parada_id_esperada
            )
        except (requests.RequestException, ValueError, TypeError, KeyError) as erro:
            print(
                f"[olhovivo] previsão de {numero} falhou: "
                f"{type(erro).__name__}: {erro}"
            )
            return _programacao_com_aviso(
                numero, ponto, sentido_esperado,
                "A API Olho Vivo não respondeu agora.",
            )


def _previsao_autenticada(
    sessao: requests.Session,
    numero: str,
    ponto: str,
    sentido_esperado: str | None,
    parada_id_esperada: str | None,
) -> dict[str, Any]:
    linhas = cache(
        ("olhovivo", "linhas", normalizar(numero)),
        TTL_LINHAS,
        lambda: _linhas(sessao, numero),
    )
    if not linhas:
        return _programacao_com_aviso(numero, ponto, sentido_esperado, "")

    if sentido_esperado:
        no_sentido = [
            item for item in linhas
            if (
                casa(sentido_esperado, destino_da_linha(item))
                or casa(destino_da_linha(item), sentido_esperado)
            )
        ]
        if not no_sentido:
            return _programacao_com_aviso(
                numero, ponto, sentido_esperado,
                "A API Olho Vivo não identificou o sentido escolhido; "
                "nenhum ETA do sentido oposto foi usado.",
            )
        linhas = no_sentido

    tentativas: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for linha_api in linhas:
        codigo_linha = int(linha_api["cl"])
        previsoes = cache(
            ("olhovivo", "previsoes-linha", codigo_linha),
            TTL_AO_VIVO,
            lambda codigo=codigo_linha: _previsoes_linha(sessao, codigo),
        )
        paradas = previsoes.get("ps", []) if isinstance(previsoes, dict) else []
        for parada in ordenar_paradas(paradas, ponto, parada_id_esperada)[:2]:
            tentativas.append((linha_api, parada, previsoes.get("hr", "")))

    if not tentativas:
        return _programacao_com_veiculos(sessao, linhas, numero, ponto, sentido_esperado)

    melhor_sem_veiculos = None
    for linha_api, parada, horario_referencia in tentativas[:MAX_TENTATIVAS_PARADA]:
        veiculos = [
            veiculo for veiculo in parada.get("vs", [])
            if isinstance(veiculo, dict) and veiculo.get("t")
        ]
        resultado = {
            "tipo": "previsao",
            "hr": horario_referencia,
            "linha": f"{linha_api.get('lt', numero)}-{linha_api.get('tl', 10)}",
            "sentido": linha_api.get("sl"),
            "destino": destino_da_linha(linha_api),
            "parada": parada.get("np"),
            "endereco": parada.get("ed", ""),
            "veiculos": veiculos,
        }
        if veiculos:
            return resultado
        melhor_sem_veiculos = melhor_sem_veiculos or resultado
    if melhor_sem_veiculos:
        return melhor_sem_veiculos
    return _programacao_com_aviso(
        numero, ponto, sentido_esperado,
        "A SPTrans não devolveu previsão para esse ponto.",
    )


def _programacao_com_veiculos(
    sessao: requests.Session,
    linhas: list[dict[str, Any]],
    numero: str,
    ponto: str,
    sentido_esperado: str | None,
) -> dict[str, Any]:
    """Sem parada monitorada, ainda dá para dizer quantos ônibus estão rodando."""
    resultado = gtfs_sptrans.programacao(
        numero, ponto, sentido_esperado=sentido_esperado
    )
    if resultado.get("erro"):
        return resultado

    veiculos: dict[str, dict[str, Any]] = {}
    horarios_referencia: list[str] = []
    for linha_api in linhas:
        codigo_linha = int(linha_api["cl"])
        posicoes = cache(
            ("olhovivo", "posicoes-linha", codigo_linha),
            TTL_AO_VIVO,
            lambda codigo=codigo_linha: _posicoes_linha(sessao, codigo),
        )
        if posicoes.get("hr"):
            horarios_referencia.append(str(posicoes["hr"]))
        for veiculo in posicoes.get("vs", []):
            if not isinstance(veiculo, dict):
                continue
            veiculos[str(veiculo.get("p") or id(veiculo))] = veiculo
    resultado.update({
        "hr": max(horarios_referencia, default=""),
        "veiculos_ativos": len(veiculos),
    })
    return resultado


__all__ = [
    "BASE_URL",
    "FONTE",
    "TTL_AO_VIVO",
    "TTL_LINHAS",
    "destino_da_linha",
    "espera_ao_vivo",
    "instante_referencia",
    "ordenar_paradas",
    "previsao_de_chegada",
]
