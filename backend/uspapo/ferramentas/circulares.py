"""Ônibus que atendem a USP usando dados oficiais e gratuitos da SPTrans.

A API Olho Vivo fornece posições e, quando disponíveis, previsões em tempo
real. Como o endpoint de paradas cobre apenas corredores e às vezes devolve
zero previsões dentro da USP, o módulo usa o GTFS oficial como fallback para
paradas e horários programados, deixando explícito quando o resultado não é
uma estimativa ao vivo.
"""

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
import math
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from uspapo.ferramentas import Registro, cache, casa, normalizar

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

CABECALHOS = {"User-Agent": "USPapo/1.0 (chatbot de alunos da USP)"}

# Catálogo de linhas que atendem a USP com seus nomes, trajetos e pontos atendidos
LINHAS_USP = {
    "8012": {
        "linha": "8012-10",
        "nome": "Circular 1 (Metrô Butantã - Cidade Universitária)",
        "destinos": ["Poli", "FEA", "Praça do Relógio", "Reitoria", "Metrô Butantã", "Biênio", "Civil"],
        "descricao": "Passa pela Praça do Relógio, Reitoria, FEA, Poli (Biênio, Civil, Elétrica) e Administração.",
        "codigo_sptrans": 33685,
    },
    "8022": {
        "linha": "8022-10",
        "nome": "Circular 2 (Metrô Butantã - Cidade Universitária)",
        "destinos": ["FFLCH", "InovaUSP", "Raia Olímpica", "Educacão", "Letras", "História", "Geografia", "Metrô Butantã"],
        "descricao": "Passa pela FFLCH (Letras, História, Geografia), InovaUSP, Psicologia, Educação e Raia.",
        "codigo_sptrans": 33686,
    },
    "8032": {
        "linha": "8032-10",
        "nome": "Circular 3 (Metrô Butantã - Politécnica)",
        "destinos": ["Poli", "Mecânica", "Produção", "Química", "Biênio", "Metrô Butantã"],
        "descricao": "Expressa para a Politécnica (Biênio, Mecânica, Química, Metalurgia).",
        "codigo_sptrans": 35492,
    },
    "8082": {
        "linha": "8082-10",
        "nome": "Circular Noturno 1 (Metrô Butantã - Cidade Universitária)",
        "destinos": ["Poli", "FEA", "CRUSP", "Reitoria", "Metrô Butantã"],
        "descricao": "Linha noturna que atende a Cidade Universitária e o CRUSP durante a madrugada.",
        "codigo_sptrans": 35810,
    },
    "8083": {
        "linha": "8083-10",
        "nome": "Circular Noturno 2 (Metrô Butantã - Cidade Universitária)",
        "destinos": ["FFLCH", "Educacão", "CRUSP", "Metrô Butantã"],
        "descricao": "Linha noturna que atende a FFLCH, Educação e conjunto residencial CRUSP.",
        "codigo_sptrans": 35811,
    },
    "8084": {
        "linha": "8084-10",
        "nome": "Circular Noturno 3 (Metrô Butantã - Cidade Universitária)",
        "destinos": ["Poli", "Educacão", "Metrô Butantã"],
        "descricao": "Linha noturna de apoio entre a Cidade Universitária e o Metrô Butantã.",
        "codigo_sptrans": 35812,
    },
    "8085": {
        "linha": "8085-10",
        "nome": "Circular Noturno 4 (Metrô Butantã - Cidade Universitária)",
        "destinos": ["Poli", "FFLCH", "CRUSP", "Metrô Butantã"],
        "descricao": "Linha noturna integrando os principais institutos da Cidade Universitária.",
        "codigo_sptrans": 35813,
    },
    "701U": {
        "linha": "701U-10",
        "nome": "Vila Mariana - Cidade Universitária",
        "destinos": ["Vila Mariana", "Metrô Ana Rosa", "Metrô Clinicas", "Poli", "Cidade Universitária"],
        "descricao": "Conecta a Cidade Universitária à Zona Sul/Central (Vila Mariana/Clínicas).",
        "codigo_sptrans": 1827,
    },
    "702U": {
        "linha": "702U-10",
        "nome": "Metrô Belém - Cidade Universitária",
        "destinos": ["Metrô Belém", "Rebouças", "Poli", "Cidade Universitária"],
        "descricao": "Conecta a Cidade Universitária à Zona Leste via Av. Rebouças.",
        "codigo_sptrans": 1829,
    },
    "7725": {
        "linha": "7725-10",
        "nome": "Metrô Vila Madalena - Terminal USP",
        "destinos": ["Metrô Vila Madalena", "Pinheiros", "Terminal USP", "Praça do Relógio"],
        "descricao": "Conecta o Metrô Vila Madalena diretamente ao Terminal USP.",
        "codigo_sptrans": 2276,
    },
}

# Coordenadas aproximadas para links do Google Maps
PONTOS_INTERESSE = {
    "metro_butanta": ("-23.5718", "-46.7082", "Metrô Butantã"),
    # Portaria 1: cruzamento oficial da Av. Afrânio Peixoto com a R. Alvarenga.
    "p1": ("-23.5661", "-46.7104", "Portaria 1 da USP"),
    "poli": ("-23.5550", "-46.7314", "Escola Politécnica da USP"),
    "fflch": ("-23.5593", "-46.7297", "FFLCH USP"),
    "fea": ("-23.5583", "-46.7258", "FEA USP"),
    "ime": ("-23.5567", "-46.7330", "IME USP"),
    "if": ("-23.5574", "-46.7320", "Instituto de Física USP"),
    "iq": ("-23.56533", "-46.72489", "Instituto de Química USP"),
    "quimica": ("-23.56533", "-46.72489", "Instituto de Química USP"),
    "mecanica": ("-23.5528", "-46.7284", "Engenharia Mecânica da Poli"),
    "reitoria": ("-23.5606", "-46.7265", "Reitoria USP"),
    "crusp": ("-23.5615", "-46.7300", "CRUSP"),
    # O nome cadastrado pela SPTrans nem sempre contém "Biênio". A coordenada
    # permite localizar, entre as paradas efetivamente atendidas pela linha, a
    # mais próxima do edifício quando a busca textual não casa.
    "bienio": ("-23.557818", "-46.732322", "Biênio da Poli"),
}

LOCAIS_OFICIAIS = {
    "p1": {
        "nome": "Portaria 1 da Cidade Universitária",
        "endereco": "cruzamento da Av. Afrânio Peixoto com a Rua Alvarenga",
        "fonte": "https://puspc.usp.br/usodocampus/funcionamento-de-portarias/",
    },
    "quimica": {
        "nome": "Instituto de Química da USP",
        "endereco": "Av. Prof. Lineu Prestes, 748",
        "fonte": "https://iq.usp.br/portaliqusp/?q=en%2Fnode%2F45",
    },
    "iq": {
        "nome": "Instituto de Química da USP",
        "endereco": "Av. Prof. Lineu Prestes, 748",
        "fonte": "https://iq.usp.br/portaliqusp/?q=en%2Fnode%2F45",
    },
    "mecanica": {
        "nome": "Prédio de Engenharia Mecânica, Mecatrônica e Naval da Poli",
        "endereco": "Av. Prof. Mello Moraes, 2231",
        "fonte": "https://www.poli.usp.br/departamentos/pme-engenharia-mecanica/",
    },
    "bienio": {
        "nome": "Prédio do Biênio da Poli",
        "endereco": "Av. Prof. Luciano Gualberto, 1380",
        "fonte": "https://www.poli.usp.br/wp-content/uploads/2020/02/Programa%C3%A7%C3%A3o-semana-de-recep%C3%A7%C3%A3o_VF.pdf",
    },
}


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
    for chave, (lat, lon, nome) in PONTOS_INTERESSE.items():
        if casa(ponto, chave) or casa(ponto, nome) or casa(chave, ponto):
            return float(lat), float(lon)
    # Nomes de parada que não estão no catálogo manual continuam roteáveis. A
    # média entre plataformas/lados da via representa o local, não o embarque;
    # o planejador escolhe depois o lado e o sentido corretos.
    paradas: dict[str, dict[str, Any]] = {}
    for rotas in _catalogo_gtfs().get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    if casa(ponto, parada.get("nome", "")):
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


def _ordenar_paradas(paradas: list[dict[str, Any]], ponto: str) -> list[dict[str, Any]]:
    textuais = [
        parada for parada in paradas
        if casa(ponto, f"{parada.get('np', '')} {parada.get('ed', '')}")
    ]
    if textuais:
        return textuais

    coordenada = _coordenada_ponto(ponto)
    if coordenada:
        return sorted(paradas, key=lambda parada: _distancia_aproximada(parada, coordenada))
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


def _servico_ativo(catalogo: dict[str, Any], servico: str, dia: date) -> bool:
    calendario = catalogo.get("calendarios", {}).get(servico)
    if not isinstance(calendario, dict):
        return False
    data_gtfs = dia.strftime("%Y%m%d")
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
    numero: str, ponto: str, agora: datetime | None = None
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
                if casa(ponto, parada.get("nome", "")):
                    candidatos.append(item)

    if not candidatos:
        coordenada = _coordenada_ponto(ponto)
        if coordenada and todas:
            menor = min(
                _distancia_parada_gtfs(item[2], coordenada) for item in todas
            )
            # Inclui a mesma parada em diferentes viagens/sentidos, mas nao uma
            # parada distante apenas porque ela tambem pertence a linha.
            candidatos = [
                item for item in todas
                if _distancia_parada_gtfs(item[2], coordenada) <= menor + 40
            ]
    if not candidatos:
        return {
            "erro": (
                f"Nao localizei no GTFS uma parada da linha {numero} "
                f"correspondente a '{ponto}'."
            )
        }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    chegadas: set[datetime] = set()
    for rota, viagem, parada in candidatos:
        deslocamento = int(parada.get("deslocamento", 0))
        for dias_a_frente in range(8):
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
                    for partida in range(inicio, fim, intervalo):
                        chegada = meia_noite + timedelta(
                            seconds=partida + deslocamento
                        )
                        if chegada >= instante - timedelta(seconds=30):
                            chegadas.add(chegada)
            else:
                chegada = meia_noite + timedelta(seconds=int(parada["horario"]))
                if chegada >= instante - timedelta(seconds=30):
                    chegadas.add(chegada)

    proximas = sorted(chegadas)[:3]
    if not proximas:
        return {"erro": "Nao ha horario programado no periodo coberto pelo GTFS."}

    rota, _viagem, parada = candidatos[0]
    horarios = [
        chegada.strftime("%H:%M")
        if chegada.date() == instante.date()
        else chegada.strftime("%d/%m as %H:%M")
        for chegada in proximas
    ]
    return {
        "tipo": "programacao",
        "linha": rota.get("linha", numero),
        "parada": parada.get("nome", ponto),
        "horarios": horarios,
        "instantes": [chegada.isoformat() for chegada in proximas],
    }


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
                    if casa(ponto, parada.get("nome", "")):
                        textuais.append(item)

    candidatas = textuais
    if not candidatas:
        coordenada = _coordenada_ponto(ponto)
        if coordenada and ocorrencias:
            menor = min(
                _distancia_parada_gtfs(parada, coordenada)
                for _rota, parada in ocorrencias
            )
            candidatas = [
                item for item in ocorrencias
                if _distancia_parada_gtfs(item[1], coordenada) <= menor + 40
            ]
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
    for chave, (_lat, _lon, nome) in PONTOS_INTERESSE.items():
        if casa(ponto, chave) or casa(ponto, nome) or casa(chave, ponto):
            return chave
    return None


def _proxima_passagem_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    depois_de: datetime,
) -> datetime | None:
    deslocamento = int(parada.get("deslocamento", 0))
    melhor: datetime | None = None
    for dias_a_frente in range(8):
        dia_servico = depois_de.date() + timedelta(days=dias_a_frente)
        if not _servico_ativo(catalogo, str(viagem.get("servico", "")), dia_servico):
            continue
        meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
        frequencias = viagem.get("frequencias", [])
        if frequencias:
            for frequencia in frequencias:
                for partida in range(
                    int(frequencia["inicio"]),
                    int(frequencia["fim"]),
                    int(frequencia["intervalo"]),
                ):
                    passagem = meia_noite + timedelta(
                        seconds=partida + deslocamento
                    )
                    if passagem >= depois_de and (melhor is None or passagem < melhor):
                        melhor = passagem
        else:
            passagem = meia_noite + timedelta(seconds=int(parada["horario"]))
            if passagem >= depois_de and (melhor is None or passagem < melhor):
                melhor = passagem
        if melhor is not None:
            break
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
    if _servico_ativo(catalogo, servico, pronto_para_embarcar.date()):
        segundos_dia = (
            pronto_para_embarcar.hour * 3600
            + pronto_para_embarcar.minute * 60
            + pronto_para_embarcar.second
        )
        for frequencia in viagem.get("frequencias", []):
            inicio_no_ponto = int(frequencia["inicio"]) + deslocamento
            fim_no_ponto = int(frequencia["fim"]) + deslocamento
            if inicio_no_ponto <= segundos_dia <= fim_no_ponto:
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
    limite_caminhada = 320
    velocidade_caminhada_m_min = 80

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
                        viagem_min = (
                            int(desembarque["deslocamento"])
                            - int(embarque["deslocamento"])
                        ) / 60
                        total = (
                            minutos_ate_ponto + espera + viagem_min
                            + caminhada_destino / velocidade_caminhada_m_min
                        )
                        candidatos.append({
                            "linha": rota.get("linha", ""),
                            "nome": rota.get("nome", ""),
                            "sentido": viagem.get("destino", ""),
                            "embarque": embarque.get("nome", ""),
                            "desembarque": desembarque.get("nome", ""),
                            "caminhada_origem_m": round(caminhada_origem),
                            "caminhada_destino_m": round(caminhada_destino),
                            "espera_programada_min": round(espera),
                            "intervalo_programado_min": (
                                round(intervalo) if intervalo is not None else None
                            ),
                            "viagem_min": round(viagem_min),
                            "total_estimado_min": round(total),
                        })

    melhores_por_linha: dict[str, dict[str, Any]] = {}
    for candidato in candidatos:
        linha = str(candidato["linha"])
        guardado = melhores_por_linha.get(linha)
        if not guardado or candidato["total_estimado_min"] < guardado["total_estimado_min"]:
            melhores_por_linha[linha] = candidato
    opcoes = sorted(
        melhores_por_linha.values(),
        key=lambda item: (
            item["total_estimado_min"],
            item["caminhada_origem_m"] + item["caminhada_destino_m"],
            normalizar(item["linha"]),
        ),
    )
    if not opcoes:
        return {"erro": "Não encontrei uma linha direta entre esses dois locais."}
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
    return {
        "origem": _chave_local(origem) or origem,
        "destino": _chave_local(destino) or destino,
        "melhor": opcoes[0],
        "alternativas": opcoes[1:3],
        "horario_referencia": instante.strftime("%H:%M"),
        "caminhada_direta_m": caminhada_direta_m,
        "caminhada_direta_min": round(caminhada_direta_m / velocidade_caminhada_m_min),
    }


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


def _obter_previsao_sptrans(numero: str, ponto: str, token: str) -> dict[str, Any]:
    """Busca a previsão linha+ponto usando uma única sessão autenticada."""
    session = requests.Session()
    if not _autenticar_sptrans(session, token):
        programacao = _programacao_gtfs(numero, ponto)
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
            return _programacao_gtfs(numero, ponto)

        tentativas: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for linha_api in linhas:
            codigo_linha = int(linha_api["cl"])
            previsoes = cache(
                ("circulares", "previsoes-linha", codigo_linha),
                TTL_AO_VIVO,
                lambda codigo=codigo_linha: _previsoes_linha(session, codigo),
            )
            paradas = previsoes.get("ps", []) if isinstance(previsoes, dict) else []
            for parada in _ordenar_paradas(paradas, ponto)[:2]:
                tentativas.append((linha_api, parada, previsoes.get("hr", "")))

        if not tentativas:
            programacao = _programacao_gtfs(numero, ponto)
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
                "destino": linha_api.get("tp") if linha_api.get("sl") == 1 else linha_api.get("ts"),
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
        programacao = _programacao_gtfs(numero, ponto)
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A API Olho Vivo não respondeu agora."
        return programacao


def consultar_circulares(
    linha: str | None = None,
    destino_ou_ponto: str | None = None,
    origem: str | None = None,
) -> tuple[str, list[str]]:
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
        partes = []
        info_origem = LOCAIS_OFICIAIS.get(str(plano.get("origem", "")))
        if info_origem:
            fontes.append(str(info_origem["fonte"]))
        info_destino = LOCAIS_OFICIAIS.get(str(plano.get("destino", "")))
        if info_destino:
            partes.append(
                f"{info_destino['nome']} fica em {info_destino['endereco']}."
            )
            fontes.append(str(info_destino["fonte"]))
        partes.append(
            f"Melhor opção pelo GTFS às {plano['horario_referencia']}: "
            f"linha {melhor['linha']}, sentido {melhor['sentido']}."
        )
        partes.append(
            f"Embarque em {melhor['embarque']}"
            f" (cerca de {melhor['caminhada_origem_m']} m da origem) e desça em "
            f"{melhor['desembarque']}"
            f" (cerca de {melhor['caminhada_destino_m']} m do destino)."
        )
        if melhor.get("intervalo_programado_min"):
            espera_texto = (
                f"espera média estimada de {melhor['espera_programada_min']} min"
            )
        else:
            espera_texto = (
                f"espera até a próxima passagem programada de cerca de "
                f"{melhor['espera_programada_min']} min"
            )
        estimativa = (
            f"Estimativa comparativa: {melhor['viagem_min']} min no ônibus, "
            f"{espera_texto} e aproximadamente "
            f"{melhor['total_estimado_min']} min no total."
        )
        if melhor.get("intervalo_programado_min"):
            estimativa += (
                f" Intervalo programado nessa faixa: "
                f"{melhor['intervalo_programado_min']} min."
            )
        partes.append(estimativa)
        if plano["caminhada_direta_min"] + 2 < melhor["total_estimado_min"]:
            partes.append(
                f"Embora {melhor['linha']} seja o melhor ônibus calculado, ir a pé "
                f"pode ser mais rápido: aproximadamente {plano['caminhada_direta_m']} m "
                f"e {plano['caminhada_direta_min']} min, contra "
                f"{melhor['total_estimado_min']} min combinando espera e ônibus."
            )
        alternativas = plano.get("alternativas", [])
        if alternativas:
            partes.append(
                "Alternativas diretas: "
                + "; ".join(
                    f"{item['linha']} (aprox. {item['total_estimado_min']} min)"
                    for item in alternativas
                )
                + "."
            )
        partes.append(
            "O ranking usa caminhada, sentido das paradas, tempo de percurso e "
            "frequência programada; não é uma previsão de trânsito em tempo real."
        )
        fontes.insert(0, FONTE_GTFS)
        return "\n\n".join(partes), list(dict.fromkeys(fontes))

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
            return "\n".join(partes), [FONTE_GTFS]

    # Identificar linhas candidatas
    linhas_casadas = []
    if termo_linha:
        numero_explicito = termo_linha.split("-", 1)[0].upper()
        resumos_explicitos = _resumo_gtfs(numero_explicito)
        if resumos_explicitos:
            primeiro = resumos_explicitos[0]
            linhas_casadas.append((numero_explicito, {
                "linha": primeiro["linha"],
                "nome": primeiro["nome"],
                "destinos": primeiro["paradas"],
                "descricao": primeiro["nome"],
            }))
        else:
            for num, info in LINHAS_USP.items():
                if (
                    num.lower() in termo_linha
                    or casa(termo_linha, info["nome"])
                    or casa(termo_linha, info["linha"])
                ):
                    linhas_casadas.append((num, info))
    
    if not linhas_casadas and termo_destino:
        for num, info in LINHAS_USP.items():
            for d in info["destinos"]:
                if casa(termo_destino, d):
                    linhas_casadas.append((num, info))
                    break

    # Se não especificou nada ou não casou, traz quatro linhas ativas principais.
    if not linhas_casadas:
        linhas_casadas = [
            (k, LINHAS_USP[k])
            for k in ("8012", "8022", "8082", "8084")
            if k in LINHAS_USP
        ]

    partes = []

    # Previsão é o caso prioritário: uma única execução da ferramenta resolve
    # linha, parada e horários, sem exigir outra rodada do modelo/Groq.
    if termo_linha and termo_destino and linhas_casadas:
        numero, info = linhas_casadas[0]
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
            if not previsao.get("erro"):
                previsao["aviso_api"] = (
                    "O token da API Olho Vivo não está configurado."
                )
        if previsao.get("erro"):
            return previsao["erro"], []

        if previsao.get("tipo") == "programacao":
            if previsao.get("aviso_api"):
                partes.append(str(previsao["aviso_api"]))
            else:
                partes.append(
                    "A API Olho Vivo não publicou uma previsão de chegada ao vivo "
                    "para essa parada agora."
                )
            partes.append(
                f"Programação oficial GTFS da linha {previsao['linha']} na parada "
                f"{previsao.get('parada') or destino_ou_ponto}."
            )
            partes.append(
                "Próximos horários programados: "
                + ", ".join(previsao.get("horarios", []))
                + "."
            )
            if previsao.get("hr"):
                quantidade = int(previsao.get("veiculos_ativos", 0))
                partes.append(
                    f"Às {previsao['hr']}, o GPS da SPTrans mostrava {quantidade} "
                    f"veículo{'s' if quantidade != 1 else ''} da linha em circulação."
                )
            partes.append(
                "Atenção: estes são horários programados, não estimativas ao vivo; "
                "trânsito e operação podem causar variações."
            )
            fontes_programacao = [FONTE_GTFS]
            if token:
                fontes_programacao.insert(0, FONTE_API)
            return "\n\n".join(partes), fontes_programacao

        veiculos = previsao.get("veiculos", [])
        cabecalho = (
            f"Previsão oficial da SPTrans para a linha {previsao['linha']} na parada "
            f"{previsao.get('parada') or destino_ou_ponto}"
        )
        if previsao.get("endereco"):
            cabecalho += f" ({previsao['endereco']})"
        partes.append(cabecalho + ".")
        partes.append(f"Horário de referência da SPTrans: {previsao.get('hr') or 'não informado'}.")
        if previsao.get("destino"):
            partes.append(f"Sentido/destino: {previsao['destino']}.")
        if veiculos:
            horarios = [str(v["t"]) for v in veiculos[:3]]
            partes.append("Próximas chegadas previstas: " + ", ".join(horarios) + ".")
            acessiveis = sum(1 for v in veiculos[:3] if v.get("a") is True)
            if acessiveis:
                partes.append(f"{acessiveis} dos próximos {len(horarios)} veículos consta como acessível.")
        else:
            partes.append("Nenhum veículo tem horário de chegada previsto nesse ponto agora.")
        return "\n\n".join(partes), [FONTE_API]
    
    if not token:
        partes.append(
            "*(Aviso: Integração em tempo real com GPS desativada temporariamente. "
            "Exibindo itinerários oficiais das linhas que atendem a USP).*\n"
        )
    
    for num, info in linhas_casadas[:4]:  # limita em 4 linhas para não estourar tokens
        resumos = _resumo_gtfs(num)
        if not resumos:
            if termo_linha:
                partes.append(
                    f"A linha {info['linha']} não aparece no GTFS atual da SPTrans. "
                    "Ela pode ter sido desativada ou renumerada."
                )
                if FONTE_GTFS not in fontes:
                    fontes.append(FONTE_GTFS)
            continue
        for resumo in resumos[:2]:
            partes.append(f"### Linha {resumo['linha']} — {resumo['nome']}")
            if resumo["paradas"]:
                partes.append(
                    "**Algumas paradas oficiais:** "
                    + ", ".join(resumo["paradas"][:14])
                    + "."
                )
        if FONTE_GTFS not in fontes:
            fontes.append(FONTE_GTFS)

    return "\n\n".join(partes), fontes


def registrar(registro: Registro) -> None:
    """Registra a ferramenta consultar_circulares no registro do backend."""
    registro.ferramenta(
        nome="consultar_circulares",
        descricao=(
            "Consulta itinerários e previsões oficiais de chegada dos ônibus "
            "que atendem a USP (Cidade Universitária / Butantã), incluindo "
            "8012-10, 8022-10, 8082-10, 8083-10, 8084-10, 8085-10, "
            "701U-10, 702U-10 e 7725-10. "
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
                        "Número ou nome da linha de ônibus (ex: '8012', '8082', "
                        "'circular 1', '8022'). Omita se o aluno perguntar de "
                        "forma genérica."
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
                        "um trajeto (ex: 'P1', 'Biênio', 'Metrô Butantã')."
                    ),
                },
            },
        },
    )(consultar_circulares)
