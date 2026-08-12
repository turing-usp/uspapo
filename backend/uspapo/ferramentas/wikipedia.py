"""Consulta pontual a artigos da Wikipedia pela Action API do MediaWiki.

O RAG do USPapo continua sendo a fonte para documentos e fatos institucionais
da USP. Esta ferramenta cobre o caso complementar: contexto enciclopédico geral
(inclusive história de pessoas, conceitos, eventos, lugares e unidades da USP),
sem precisar indexar a Wikipedia inteira no Pinecone.

A consulta é somente de leitura e usa dois módulos públicos da Action API:

* ``list=search`` encontra até três artigos do domínio principal;
* ``prop=extracts`` devolve a introdução de cada artigo em texto simples.

O resultado é propositalmente curto. Além de caber no orçamento da ferramenta,
isso encaminha o aluno para os artigos originais, que o frontend mostra como
fontes. Wikipedia é conteúdo colaborativo: serve para visão geral, não para
decisões, dados voláteis ou afirmações institucionais que tenham uma fonte
primária disponível.
"""

from __future__ import annotations

import math
import urllib.parse
from typing import Any

import requests

from uspapo.ferramentas import Registro, cache, normalizar, palavras

IDIOMAS = {
    "pt": ("Português", "https://pt.wikipedia.org"),
    "en": ("Inglês", "https://en.wikipedia.org"),
}

TIMEOUT = 10
TTL = 3600
MAX_CANDIDATOS = 5
MAX_RESULTADOS = 2
MAX_SENTENCAS = 4
MAX_CONSULTA = 160
TERMOS_DE_PERGUNTA = frozenset(
    "que quem quando onde como qual quais isso isto seria significa explique".split()
)

# A Wikimedia pede um User-Agent que identifique a aplicação. Não há segredo
# aqui, e a URL aponta para a página pública do projeto.
CABECALHOS = {"User-Agent": "USPapo/1.0 (https://uspapo.turingusp.com)"}


def _url_artigo(base: str, titulo: str) -> str:
    """URL estável e navegável de um título retornado pela API."""
    caminho = urllib.parse.quote(titulo.replace(" ", "_"), safe="")
    return f"{base}/wiki/{caminho}"


def _get_json(base: str, parametros: dict[str, Any]) -> dict[str, Any]:
    """Executa uma chamada de leitura à API e valida o formato mínimo."""
    resposta = requests.get(
        f"{base}/w/api.php",
        params={"format": "json", "formatversion": "2", **parametros},
        headers=CABECALHOS,
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if not isinstance(dados, dict):
        raise ValueError("A API da Wikipedia devolveu JSON fora do formato esperado.")
    return dados


def _tem_relevancia(consulta: str, *textos: str) -> bool:
    """Exige evidência lexical mínima antes de publicar texto ou URL.

    O ranking do MediaWiki pode devolver resultados fonéticos muito distantes
    para nomes próprios inexistentes. Sem esta barreira, a ferramenta anexava
    essas páginas como fontes embora elas não contivessem o tema pesquisado.
    """
    termos = {
        termo for termo in palavras(consulta)
        if len(termo) >= 3 and termo not in TERMOS_DE_PERGUNTA
    }
    if not termos:
        return False
    conteudo = normalizar(" ".join(textos))
    frase = normalizar(consulta)
    if frase and frase in conteudo:
        return True
    presentes = {termo for termo in termos if termo in palavras(conteudo)}
    # Consultas curtas costumam ser nomes próprios. Nelas, perder um termo muda
    # completamente o assunto ("Universidade de São Paulo" -> "São Paulo").
    # Em frases maiores toleramos um termo contextual ausente, mas nunca metade.
    minimo = len(termos) if len(termos) <= 3 else math.ceil(len(termos) * 0.75)
    return len(presentes) >= minimo


def _buscar(consulta: str, idioma: str) -> list[dict[str, str]]:
    """Busca títulos e suas introduções, preservando a ordem de relevância."""
    _, base = IDIOMAS[idioma]
    resultado_busca = _get_json(
        base,
        {
            "action": "query",
            "list": "search",
            "srsearch": consulta,
            "srnamespace": "0",
            "srlimit": str(MAX_CANDIDATOS),
            "srsort": "relevance",
        },
    )
    bloco_busca = resultado_busca.get("query")
    busca = bloco_busca.get("search", []) if isinstance(bloco_busca, dict) else []
    titulos = [
        str(item.get("title", "")).strip()
        for item in busca
        if isinstance(item, dict)
        and item.get("title")
        and _tem_relevancia(
            consulta,
            str(item.get("title", "")),
            str(item.get("snippet", "")),
        )
    ][:MAX_RESULTADOS]
    if not titulos:
        return []

    resultado_paginas = _get_json(
        base,
        {
            "action": "query",
            "prop": "extracts",
            "titles": "|".join(titulos),
            "redirects": "1",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": str(MAX_SENTENCAS),
        },
    )
    bloco_paginas = resultado_paginas.get("query")
    paginas = bloco_paginas.get("pages", []) if isinstance(bloco_paginas, dict) else []
    por_titulo = {
        pagina.get("title"): pagina
        for pagina in paginas
        if isinstance(pagina, dict) and pagina.get("title")
    }

    artigos = []
    for titulo in titulos:
        pagina = por_titulo.get(titulo)
        if not pagina or pagina.get("missing"):
            continue
        extrato = " ".join(str(pagina.get("extract", "")).split())
        if not _tem_relevancia(consulta, titulo, extrato):
            continue
        artigos.append({
            "titulo": titulo,
            "extrato": extrato,
            "url": _url_artigo(base, titulo),
        })
    return artigos


def consultar_wikipedia(consulta: str, idioma: str = "pt") -> tuple[str, list[str]]:
    """Busca resumos de artigos da Wikipedia e devolve texto e fontes."""
    consulta = str(consulta or "").strip()
    idioma = str(idioma or "pt").lower().strip()
    if idioma not in IDIOMAS:
        return "Idioma inválido. Escolha 'pt' para português ou 'en' para inglês.", []
    if len(consulta) < 2:
        return "Diga o tema ou o título que devo procurar na Wikipedia.", []
    if len(consulta) > MAX_CONSULTA:
        return (
            f"A consulta está longa demais (máximo de {MAX_CONSULTA} caracteres). "
            "Resuma o tema que deseja pesquisar.",
            [],
        )

    try:
        artigos = cache(("wikipedia", idioma, consulta.casefold()), TTL, lambda: _buscar(consulta, idioma))
    except (requests.RequestException, ValueError) as erro:
        print(f"[wikipedia] busca '{consulta}' falhou: {type(erro).__name__}: {erro}")
        return (
            "Não consegui consultar a Wikipedia agora. Avise o aluno e sugira "
            "tentar novamente daqui a pouco; não conclua que o artigo não existe.",
            [],
        )

    if not artigos:
        return (
            f"Não encontrei artigos da Wikipedia em {IDIOMAS[idioma][0].lower()} "
            f"para '{consulta}'. Tente outro termo, uma grafia mais específica ou o idioma inglês.",
            [],
        )

    partes = [
        f"Resultados da Wikipedia em {IDIOMAS[idioma][0]} para '{consulta}':"
    ]
    fontes = []
    for artigo in artigos:
        partes.append(f"### {artigo['titulo']}")
        partes.append(artigo["extrato"] or "A página não possui introdução disponível pela API.")
        fontes.append(artigo["url"])

    partes.append(
        "*A Wikipedia é uma enciclopédia colaborativa. Use estes resumos como "
        "contexto geral; para fatos institucionais da USP, datas, regras, "
        "estatísticas ou decisões, priorize a fonte oficial correspondente.*"
    )
    return "\n\n".join(partes), fontes


def registrar(registro: Registro) -> None:
    """Registra a consulta à Wikipedia no backend escolhido."""
    registro.ferramenta(
        nome="consultar_wikipedia",
        descricao=(
            "Busca no máximo dois artigos lexicalmente relevantes da Wikipedia "
            "e devolve as introduções, em "
            "português ou inglês. Use para contexto enciclopédico e histórico "
            "geral que as ferramentas específicas não cubram: pessoa, conceito, "
            "evento ou lugar. Para projetos, serviços, sistemas, unidades e "
            "iniciativas da USP, use primeiro `buscar_documentos`; só use a "
            "Wikipedia depois se a busca oficial disser que não encontrou. "
            "Wikipedia é fonte colaborativa, não oficial: NÃO use para regras, "
            "prazos, dados atuais ou fatos institucionais da USP quando houver "
            "fonte primária."
        ),
        parametros={
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Tema ou título a pesquisar, como o aluno escreveu.",
                },
                "idioma": {
                    "type": "string",
                    "enum": list(IDIOMAS),
                    "description": "'pt' (padrão) ou 'en'. Use 'en' se o aluno pedir em inglês ou o artigo não existir em português.",
                },
            },
            "required": ["consulta"],
        },
    )(consultar_wikipedia)
