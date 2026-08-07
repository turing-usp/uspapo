"""Extração de conteúdo: HTML e PDF viram parágrafos limpos.

Aqui mora o conserto da causa-raiz de quase todos os problemas de qualidade do
índice. O extrator antigo fazia duas coisas erradas ao mesmo tempo:

    tags_de_bloco = corpo.css('p, li, h1, ..., .field-items div')
    textos_internos = tag.css('*::text, ::text').getall()

O `.field-items div` (Drupal) casa o container externo **e** os `<p>` dentro
dele. E `'*::text, ::text'` é a união de "todo texto descendente" com "texto
filho direto" — o que duplica cada nó de texto direto. Resultado medido: para
`<div class="field-items"><div><p>Ola <b>mundo</b></p><p>Segundo</p></div></div>`
saíam três blocos: `'Ola mundoSegundo'`, `'Ola mundo'` e `'Segundo'` — o
container inteiro grudado (sem espaço entre "mundo" e "Segundo") mais as duas
duplicatas.

No corpus real isso produziu 467 "parágrafos" com mais de 1100 caracteres
carregando **36,2% de todo o texto**, o maior deles com 491.210 caracteres — uma
página inteira num bloco só. E aí:

- o fatiador cortava esses blocos de 1100 em 1100 caracteres, no meio da palavra
  (32% dos chunks do índice nasceram assim);
- a detecção de boilerplate ficava cega, porque dois rodapés idênticos estavam
  escondidos dentro de blobs que nunca se repetiam byte a byte;
- e uma regra de limpeza com `.*?` passou a alcançar o documento inteiro, porque
  não havia mais quebra de linha para segurá-la (foi assim que uma regra apagou
  51% de uma página legítima do IQ).

A regra nova é simples: **cada trecho de texto é contado exatamente uma vez**,
pelo bloco mais próximo que o contém.
"""

import io
import re
from collections import Counter
from urllib.parse import unquote, urlsplit

from embeddings.texto import normalizar

# Blocos que viram parágrafo. Ordem não importa: a saída segue a ordem do documento.
TAGS_BLOCO = (
    "p", "li", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "td", "th", "caption", "figcaption", "pre",
)
SELETORES_BLOCO = ", ".join(TAGS_BLOCO)

# Onde o conteúdo de verdade costuma estar, do mais específico para o mais burro.
SELETORES_RAIZ = (
    "main", "article", "[role=main]", "#content", "#main-content", "#conteudo",
    ".region-content", ".entry-content", ".node__content", ".post-content",
    ".field-items", "body",
)

# Casca do tema: nada aqui é conteúdo. É a lista antiga mais o que apareceu nos
# sites novos (cookie banner, "pular para o conteúdo", widget de tradução).
RUIDO_ESTRUTURAL = (
    "nav", "footer", "header", "aside", "button", "script", "style", "noscript",
    "form", "iframe", "svg",
    ".menu", ".sidebar", "#header", "#footer", ".breadcrumb", ".redes-sociais",
    ".compartilhar", ".tags", ".subfooter-area", "#subfooter-inside",
    ".skip-link", ".cookie", ".cookies", ".widget", ".pagination", ".paginacao",
    ".social", ".related", ".menu-lateral", ".wp-block-navigation",
    ".elementor-nav-menu", ".goog-te-banner-frame", "[aria-hidden=true]",
    "[role=navigation]", "[role=banner]", "[role=contentinfo]",
)

MIN_CHARS_RAIZ = 200
_IGNORAR_TEXTO = {"script", "style", "noscript"}

# Tags que saem sempre, sem passar pela trava de proporção abaixo: não são
# conteúdo em nenhuma hipótese, e um JSON-LD inline pode ser enorme.
_RUIDO_INCONDICIONAL = {"script", "style", "noscript", "svg", "iframe"}

# Um seletor de casca que casa mais do que esta fatia do texto da página não
# está casando casca — está casando a página. Ele é ignorado.
#
# Sem isto o `www5.usp.br` (o portal principal da USP) devolvia **0 caracteres**
# em 315 páginas: o tema põe `class="sidebar"` no próprio `<body>`, e a regra
# `.sidebar` derrubava o documento inteiro. Sai um site com título e sem texto,
# e nada no log dizendo por quê.
LIMITE_RUIDO = 0.5


# ─────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────
def _texto_proprio(elemento) -> str:
    """Texto que pertence a ESTE bloco, sem o que é de um bloco descendente.

    É o que garante a contagem única. Um `<li>` que contém um `<ul><li>` aninhado
    devolve só o seu próprio rótulo; o item de dentro sai como parágrafo próprio,
    na ordem do documento. Nada se perde e nada se repete.
    """
    partes: list[str] = []

    def caminhar(no, raiz: bool = False):
        marcador = no.tag
        if not isinstance(marcador, str):  # comentário, PI
            return
        marcador = marcador.lower()
        if marcador in _IGNORAR_TEXTO:
            return
        if not raiz and marcador in TAGS_BLOCO:
            return  # a subárvore é de outro bloco; ele se apresenta sozinho
        if no.text:
            partes.append(no.text)
        for filho in no:
            caminhar(filho)
            # A cauda de um filho ignorado ainda é texto DESTE bloco.
            if filho.tail:
                partes.append(filho.tail)

    caminhar(elemento, raiz=True)
    # Junta com espaço, não com "": era o `''.join` antigo que colava
    # "mundo" em "Segundo".
    return re.sub(r"\s+", " ", " ".join(partes)).strip()


def _tamanho_do_texto(no) -> int:
    return len(re.sub(r"\s+", " ", " ".join(no.css("::text").getall())).strip())


def escolher_raiz(seletor):
    """O contêiner mais rico em texto, não o primeiro que aparecer.

    Pegar o primeiro candidato com texto suficiente parece razoável e não é: numa
    home de unidade o conteúdo vem repartido em várias regiões, e o primeiro
    `<main>` costuma ter só o carrossel de notícias. Medido no portal do IF, essa
    regra derrubava a página de 2.530 para 240 caracteres.

    Como o ruído estrutural já foi removido antes desta escolha, deixar o `body`
    ganhar quando ele é de fato o único contêiner abrangente é seguro. O empate
    (dentro de 10%) fica com o candidato mais específico, que vem antes na lista.
    """
    melhor = None
    melhor_tamanho = 0
    for candidato in SELETORES_RAIZ:
        for no in seletor.css(candidato)[:1]:
            tamanho = _tamanho_do_texto(no)
            if tamanho > melhor_tamanho * 1.1:
                melhor, melhor_tamanho = no, tamanho

    if melhor is not None and melhor_tamanho >= MIN_CHARS_RAIZ:
        return melhor
    corpo = seletor.css("body")
    return corpo[0] if corpo else seletor


def remover_ruido(raiz) -> None:
    total = _tamanho_do_texto(raiz)
    for seletor in RUIDO_ESTRUTURAL:
        try:
            for elemento in raiz.css(seletor):
                marcador = getattr(elemento.root, "tag", "")
                marcador = marcador.lower() if isinstance(marcador, str) else ""

                if marcador not in _RUIDO_INCONDICIONAL:
                    # `<html>` e `<body>` nunca saem: dropá-los esvazia a página.
                    if marcador in ("html", "body"):
                        continue
                    if total and _tamanho_do_texto(elemento) > total * LIMITE_RUIDO:
                        continue

                elemento.drop()
        except Exception:
            # Seletor que o parsel não digere, ou nó já removido junto do pai.
            continue


def blocos_semanticos(raiz) -> list[str]:
    """Os parágrafos da página, na ordem, cada texto uma única vez."""
    blocos = []
    for seletor in raiz.css(SELETORES_BLOCO):
        texto = _texto_proprio(seletor.root)
        if texto:
            blocos.append(texto)
    return blocos


def _titulo_da_url(url: str) -> str:
    caminho = urlsplit(url).path.rstrip("/")
    ultimo = unquote(caminho.rsplit("/", 1)[-1]) if caminho else ""
    ultimo = re.sub(r"\.(html?|php|aspx?)$", "", ultimo, flags=re.IGNORECASE)
    ultimo = re.sub(r"[-_+]+", " ", ultimo).strip()
    return ultimo.capitalize()


def extrair_titulo(response) -> str:
    """Cascata de fontes até sobrar alguma coisa utilizável.

    O antigo usava `response.css('h1::text').get()`, que pega só o PRIMEIRO nó de
    texto do h1 — num `<h1>Pós <span>Graduação</span></h1>` devolvia "Pós" — e
    devolvia vazio quando o h1 era uma imagem. Eram 79 páginas com título vazio,
    e o título vai junto no texto vetorizado.
    """
    for candidato in response.css("h1"):
        texto = _texto_proprio(candidato.root)
        if texto:
            return texto

    for meta in ("meta[property='og:title']::attr(content)", "meta[name='title']::attr(content)"):
        valor = (response.css(meta).get() or "").strip()
        if valor:
            return _sem_sufixo_do_site(valor)

    bruto = (response.css("title::text").get() or "").strip()
    if bruto:
        return _sem_sufixo_do_site(bruto)

    return _titulo_da_url(response.url) or "Sem título"


def _sem_sufixo_do_site(bruto: str) -> str:
    """"Editais – PRIP – Pró-Reitoria de Inclusão – USP" -> "Editais".

    Quase todo CMS cola o nome do site depois de um separador. Guardar isso em
    todo título é ruído repetido em cada vetor, já que o título vai junto no
    texto vetorizado.
    """
    limpo = re.sub(r"\s+", " ", bruto).strip()
    primeiro = re.split(r"\s+[|–—»-]\s+", limpo)[0].strip()
    return primeiro if len(primeiro) >= 4 else limpo


def extrair_html(response) -> dict:
    # O título sai PRIMEIRO. Muito tema de WordPress põe o `<h1>` da página
    # dentro de um `<header class="entry-header">`, e a remoção de ruído leva o
    # header junto — aí sobra só o `<title>`, que vem com o nome do site colado.
    titulo = extrair_titulo(response)

    # O ruído sai antes da escolha da raiz: assim a comparação de tamanho entre
    # candidatos mede conteúdo, e não quanto menu cada um carrega.
    remover_ruido(response)
    raiz = escolher_raiz(response)
    blocos = blocos_semanticos(raiz)
    return {"titulo": titulo, "texto_limpo": normalizar("\n\n".join(blocos))}


# ─────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────
def paragrafos_de_pdf(paginas_texto: list[str]) -> list[str]:
    """Reconstrói parágrafos e joga fora cabeçalho/rodapé repetido.

    O `"\\n".join(páginas)` antigo entregava o PDF inteiro como um único blob sem
    linha em branco nenhuma. É dele que veio o "parágrafo" de 491.210
    caracteres. Aqui cada página é quebrada em parágrafos de verdade, e a linha
    que se repete em mais de 60% das páginas (numeração, título corrente) sai.
    """
    if not paginas_texto:
        return []

    linhas_por_pagina = [
        [linha.strip() for linha in (texto or "").split("\n") if linha.strip()]
        for texto in paginas_texto
    ]

    repetidas: set[str] = set()
    if len(linhas_por_pagina) >= 4:
        contagem: Counter = Counter()
        for linhas in linhas_por_pagina:
            contagem.update(set(linhas))
        corte = len(linhas_por_pagina) * 0.6
        repetidas = {
            linha for linha, n in contagem.items() if n >= corte and len(linha) < 120
        }

    paragrafos: list[str] = []
    atual: list[str] = []
    for linhas in linhas_por_pagina:
        for linha in linhas:
            if linha in repetidas or re.fullmatch(r"[\d\s\-–—/|.]+", linha):
                continue
            atual.append(linha)
            # Fim de parágrafo: a linha termina em pontuação terminal.
            if re.search(r"[.!?:;]$", linha):
                paragrafos.append(" ".join(atual))
                atual = []
        if atual:
            paragrafos.append(" ".join(atual))
            atual = []
    if atual:
        paragrafos.append(" ".join(atual))
    return [p for p in paragrafos if p.strip()]


def extrair_pdf(response) -> dict:
    from pypdf import PdfReader

    nome = unquote(response.url.split("/")[-1]) or "documento.pdf"
    try:
        leitor = PdfReader(io.BytesIO(response.body))
        paginas = [(p.extract_text() or "") for p in leitor.pages]
        titulo = ""
        if leitor.metadata and leitor.metadata.title:
            titulo = str(leitor.metadata.title).strip()
        return {
            "titulo": titulo or nome,
            "texto_limpo": normalizar("\n\n".join(paragrafos_de_pdf(paginas))),
        }
    except Exception as erro:
        print(f"[PDF] Falha ao ler {response.url}: {erro}")
        return {"titulo": nome, "texto_limpo": ""}


def eh_pdf(response) -> bool:
    """Sufixo OU Content-Type. Muito PDF da USP é servido por URL sem extensão."""
    if response.url.lower().split("?")[0].endswith(".pdf"):
        return True
    tipo = response.headers.get("Content-Type", b"").decode("latin-1", "ignore").lower()
    return "application/pdf" in tipo
