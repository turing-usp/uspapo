"""Descoberta de URLs: sitemap, seletores CSS ou links do próprio domínio.

O jeito antigo era um só: alguém abria o site, olhava o HTML, e escrevia um
seletor CSS para o menu. Isso tem dois problemas que já custaram caro.

Primeiro, quebra em silêncio. O seletor do `fea` (`.menu-principal`,
`#nice-menu-1`) não casa nada no site atual. O site usa `.block-nice-menus-1` e
`.barra-menu-principal`. O resultado foi `data/raw/fea_raw.json` com zero
páginas, gravado por cima do arquivo bom, e `last_update` avançando como se
tivesse dado tudo certo. O `poli` depende de `ul#menu-1-7a1b5c55`, um id gerado
pelo Elementor que muda quando alguém reeditar o menu.

Segundo, não escala. São 34 sites novos entrando; calibrar CSS para cada um, e
recalibrar a cada reforma de site, não é trabalho que se sustente.

A estratégia `hibrido` resolve os dois: tenta o sitemap, cai para os seletores se
houver, e cai para o link do próprio domínio se ainda faltar página. Só quem tem
comportamento esquisito precisa de seletor.

E o sitemap tem um teto **por sub-sitemap**, não só no total: um sub-sitemap que
sozinho traz dezenas de milhares de URLs é sinal de invasão, não de site grande.
Os do `iri.usp.br` tinham ~48 mil cada.
"""

import re
from urllib.parse import urljoin, urlsplit

# Caminhos onde um sitemap costuma estar, na ordem em que vale tentar.
CAMINHOS_SITEMAP = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml")

# Acima disto, um único sitemap não é um site grande: é um site invadido.
# Os sub-sitemaps de spam do `iri.usp.br` traziam ~48 mil URLs cada.
TETO_POR_SITEMAP = 5000

# O mesmo teste, agora somando o site inteiro: dá para diluir 48 mil URLs em
# muitos arquivos pequenos, e o teto acima não veria nada.
TETO_URLS_TOTAL = 20000

# Este NÃO é um detector de invasão, é orçamento de requisição — cada
# sub-sitemap é um GET antes de a primeira página de conteúdo ser baixada.
#
# Ele já foi 12, na suposição de que "muitos sub-sitemaps" fosse sinal de
# domínio comprometido. Era o oposto: o `iri.usp.br` invadido tinha **11**, e
# teria passado, enquanto `fuvest.br` (59 arquivos, 553 URLs no total) e
# `iee.usp.br` (15 arquivos, 1.165 URLs) foram barrados sem ter nada de errado.
# WordPress com Yoast fatia o sitemap por mês e por tipo de post; contar
# arquivos mede o plugin, não a saúde do site. Quem mede é o volume de URL.
TETO_SUB_SITEMAPS = 80

# O que interessa a quem pergunta ao chatbot. Ordem = prioridade.
PREFIXOS_RELEVANTES = (
    "graduacao", "pos-graduacao", "pos", "ensino", "aluno", "alunos", "estudante",
    "matricula", "calendario", "disciplina", "curso", "cursos", "grade",
    "edital", "editais", "bolsa", "bolsas", "auxilio", "assistencia", "moradia",
    "estagio", "monitoria", "intercambio", "transferencia", "ingresso", "vestibular",
    "secretaria", "servico", "servicos", "atendimento", "biblioteca", "contato",
    "sobre", "institucional", "quem-somos", "faq", "perguntas", "normas", "regulamento",
)

_RE_DATA = re.compile(r"/\d{4}/\d{2}/")


def urls_de_sitemap(corpo: bytes) -> tuple[list[str], list[str]]:
    """Devolve `(urls_de_conteudo, sub_sitemaps)`.

    Usa o parser do próprio scrapy, que já lida com sitemapindex, urlset e
    namespace. Se o XML vier quebrado (ou vier HTML, que é o caso de vários
    sites da USP que respondem 200 numa página de erro), devolve vazio.
    """
    try:
        from scrapy.utils.sitemap import Sitemap

        mapa = Sitemap(corpo)
    except Exception:
        return [], []

    urls: list[str] = []
    subs: list[str] = []
    for item in mapa:
        localizacao = item.get("loc")
        if not localizacao:
            continue
        if mapa.type == "sitemapindex":
            subs.append(localizacao)
        else:
            urls.append(localizacao)
    return urls, subs


def sitemaps_do_robots(corpo: str, base: str) -> list[str]:
    achados = []
    for linha in corpo.splitlines():
        if linha.strip().lower().startswith("sitemap:"):
            achados.append(urljoin(base, linha.split(":", 1)[1].strip()))
    return achados


def candidatos_de_sitemap(base: str) -> list[str]:
    return [urljoin(base, caminho) for caminho in CAMINHOS_SITEMAP]


def _pontuacao(url: str) -> tuple[int, int]:
    """Menor é melhor: (prioridade do prefixo, profundidade do caminho)."""
    caminho = urlsplit(url).path.lower().strip("/")
    if not caminho:
        return (0, 0)  # a home entra sempre

    segmentos = caminho.split("/")
    prioridade = len(PREFIXOS_RELEVANTES) + 1
    for segmento in segmentos:
        limpo = re.sub(r"[^a-z-]", "", segmento)
        for indice, prefixo in enumerate(PREFIXOS_RELEVANTES):
            if limpo == prefixo or limpo.startswith(prefixo + "-"):
                prioridade = min(prioridade, indice + 1)
                break

    # Notícia datada vai para o fim: envelhece rápido e responde pouco.
    if _RE_DATA.search(url):
        prioridade += len(PREFIXOS_RELEVANTES)

    return (prioridade, len(segmentos))


def ordenar_por_relevancia(urls: list[str]) -> list[str]:
    """Põe na frente o que responde pergunta de aluno.

    Importa porque `max_paginas` corta a lista: com 3.000 URLs e teto de 250, a
    diferença entre ordenar e não ordenar é pegar a página de matrícula ou pegar
    250 notícias de 2019.
    """
    return sorted(dict.fromkeys(urls), key=lambda u: (_pontuacao(u), u))


def links_por_seletores(response, fontes: list[dict]) -> list[str]:
    """Os seletores CSS configurados, quando existem."""
    achados: list[str] = []
    for fonte in fontes or []:
        seletor = fonte.get("selector", "")
        if not seletor:
            continue
        try:
            achados.extend(response.css(seletor).getall())
        except Exception:
            continue
    return [response.urljoin(link) for link in achados if link and not link.startswith("#")]


def links_genericos(response, dominios: list[str]) -> list[str]:
    """Todo link do próprio domínio, sem depender de seletor nenhum."""
    from scrapy.linkextractors import LinkExtractor

    extrator = LinkExtractor(allow_domains=dominios, canonicalize=True, unique=True)
    try:
        return [link.url for link in extrator.extract_links(response)]
    except Exception:
        return []
