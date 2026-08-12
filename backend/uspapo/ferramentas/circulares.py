"""Rastreamento dos Circulares da USP em tempo real (API Olho Vivo da SPTrans).

Este módulo consulta a API pública Olho Vivo da SPTrans (v2.1) para obter a
posição exata em tempo real (GPS) e a previsão de chegada dos ônibus circulares
da USP (Butantã), incluindo as linhas diurnas e noturnas:

    - 8012-10: Circular 1 (Metrô Butantã / Praça do Relógio / Poli / FEA)
    - 8022-10: Circular 2 (Metrô Butantã / InovaUSP / FFLCH / Raia)
    - 8032-10: Circular 3 (Metrô Butantã / Politécnica)
    - 8082-10: Circular 1 Noturno (Cidade Universitária / Metrô Butantã)
    - 8083-10: Circular 2 Noturno (Cidade Universitária / Metrô Butantã)
    - 8084-10: Circular 3 Noturno (Cidade Universitária / Metrô Butantã)
    - 8085-10: Circular 4 Noturno (Cidade Universitária / Metrô Butantã)
    - 701U-10: Vila Mariana / Cidade Universitária
    - 702U-10: Metrô Belém / Cidade Universitária
    - 7725-10: Metrô Vila Madalena / Terminal USP

Sobre a API da SPTrans:
    A API é pública e gratuita (`api.olhovivo.sptrans.com.br/v2.1`).
    Exige autenticação via POST no `/Login/Autenticar?token={SPTRANS_TOKEN}`.
    Se o token não estiver configurado no `.env`, a ferramenta degrada para
    uma resposta informativa com itinerários conhecidos e links universais do
    Google Maps, sem estourar exceção.
"""

import os
import urllib.parse
from typing import Any

import requests

from uspapo.ferramentas import Registro, cache, casa, normalizar

BASE_URL = "https://api.olhovivo.sptrans.com.br/v2.1"
TIMEOUT = 10

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
    "poli": ("-23.5550", "-46.7314", "Escola Politécnica da USP"),
    "fflch": ("-23.5593", "-46.7297", "FFLCH USP"),
    "fea": ("-23.5583", "-46.7258", "FEA USP"),
    "ime": ("-23.5567", "-46.7330", "IME USP"),
    "if": ("-23.5574", "-46.7320", "Instituto de Física USP"),
    "iq": ("-23.5588", "-46.7328", "Instituto de Química USP"),
    "reitoria": ("-23.5606", "-46.7265", "Reitoria USP"),
    "crusp": ("-23.5615", "-46.7300", "CRUSP"),
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


def _obter_posicao_sptrans(codigo_linha: int, token: str) -> dict[str, Any] | None:
    """Busca a posição dos ônibus de uma linha em tempo real."""
    session = requests.Session()
    if not _autenticar_sptrans(session, token):
        return None

    try:
        res = session.get(
            f"{BASE_URL}/Posicao/Linha?codigoLinha={codigo_linha}",
            headers=CABECALHOS,
            timeout=TIMEOUT,
        )
        if res.status_code == 200:
            return res.json()
    except Exception as err:
        print(f"[circulares] Erro ao buscar posicao linha {codigo_linha}: {err}")
    return None


def _gerar_link_google_maps(destino_nome: str) -> str:
    """Gera link universal do Google Maps com navegação de transporte público."""
    destino_clean = normalizar(destino_nome)
    coord = None

    for chave, (lat, lon, nome_oficial) in PONTOS_INTERESSE.items():
        if casa(destino_clean, chave) or casa(destino_clean, nome_oficial):
            coord = f"{lat},{lon}"
            break

    if not coord:
        coord = urllib.parse.quote(f"{destino_nome} USP Cidade Universitaria São Paulo")

    return f"https://www.google.com/maps/dir/?api=1&destination={coord}&travelmode=transit"


def consultar_circulares(linha: str | None = None, destino_ou_ponto: str | None = None) -> tuple[str, list[str]]:
    """Consulta em tempo real a posição dos circulares da USP via API da SPTrans."""
    fontes = ["http://www.sptrans.com.br/olhovivo"]
    token = os.getenv("SPTRANS_TOKEN", "").strip()

    termo_linha = normalizar(linha or "")
    termo_destino = normalizar(destino_ou_ponto or "")

    # Identificar linhas candidatas
    linhas_casadas = []
    if termo_linha:
        for num, info in LINHAS_USP.items():
            if num in termo_linha or casa(termo_linha, info["nome"]) or casa(termo_linha, info["linha"]):
                linhas_casadas.append((num, info))
    
    if not linhas_casadas and termo_destino:
        for num, info in LINHAS_USP.items():
            for d in info["destinos"]:
                if casa(termo_destino, d):
                    linhas_casadas.append((num, info))
                    break

    # Se não especificou nada ou não casou, traz as principais (8012, 8022, 8032, 8082)
    if not linhas_casadas:
        linhas_casadas = [(k, LINHAS_USP[k]) for k in ("8012", "8022", "8032", "8082") if k in LINHAS_USP]

    partes = []
    
    if not token:
        partes.append(
            "*(Aviso: Integração em tempo real com GPS desativada temporariamente. "
            "Exibindo itinerários oficiais das linhas que atendem a USP).*\n"
        )
    
    for num, info in linhas_casadas[:4]:  # limita em 4 linhas para não estourar tokens
        partes.append(f"### Linha {info['linha']} — {info['nome']}")
        partes.append(f"**Itinerário e Principais Paradas:** {info['descricao']}")
        partes.append(f"**Locais Atendidos:** {', '.join(info['destinos'])}")

        if token:
            chave_cache = ("circulares", "posicao", info["codigo_sptrans"])
            posicao_dados = cache(
                chave_cache,
                TTL_AO_VIVO,
                lambda: _obter_posicao_sptrans(info["codigo_sptrans"], token),
            )

            if posicao_dados and "vs" in posicao_dados and isinstance(posicao_dados["vs"], list):
                veiculos = posicao_dados["vs"]
                qtd = len(veiculos)
                hr_ref = posicao_dados.get("hr", "")
                if qtd > 0:
                    partes.append(
                        f"🚍 **Frota em Circulação (às {hr_ref}):** Existem {qtd} veículos "
                        "operando nesta linha ao longo do trajeto."
                    )
                else:
                    partes.append(
                        f"⚠️ **Frota em Circulação (às {hr_ref}):** Nenhum veículo "
                        "registrado em circulação nesta linha no momento."
                    )
            else:
                partes.append(
                    "*(Sinal de GPS em tempo real indisponível no momento na SPTrans. "
                    "Consulte o trajeto completo no link abaixo).* "
                )

    alvo_link = destino_ou_ponto or (linhas_casadas[0][1]["destinos"][0] if linhas_casadas else "Cidade Universitária USP")
    link_maps = _gerar_link_google_maps(alvo_link)
    partes.append(f"\n📍 [Clique para acompanhar a rota e horários ao vivo no Google Maps]({link_maps})")
    fontes.append(link_maps)

    return "\n\n".join(partes), fontes


def registrar(registro: Registro) -> None:
    """Registra a ferramenta consultar_circulares no registro do backend."""
    registro.ferramenta(
        nome="consultar_circulares",
        descricao=(
            "Consulta os itinerários, paradas e frota em tempo real dos ônibus "
            "circulares da USP (Cidade Universitária / Butantã), incluindo as "
            "linhas diurnas (8012-10, 8022-10, 8032-10) e noturnas (8082-10, "
            "8083-10, 8084-10, 8085-10, 701U-10, 702U-10, 7725-10). Note que uma "
            "linha tem MÚLTIPLOS veículos operando ao longo do trajeto. "
            "Use para informar o itinerário da linha, institutos atendidos, "
            "quantidade de veículos na frota e o link de rota do Maps."
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
                        "'Metrô Butantã', 'FEA', 'CRUSP')."
                    ),
                },
            },
        },
    )(consultar_circulares)
