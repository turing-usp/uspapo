"""Filtros de URL e detecção de site invadido.

Este módulo existe por causa do `iri.usp.br`. O `sitemap.xml` daquele domínio
lista onze sub-sitemaps — `sitemap-bonusesr.xml`, `-games`, `-store`, `-order`,
`-hot`, `-dell`, `-android`, `-recomendados`, `-plataforma`, `-video`,
`-article` — e cada um traz **cerca de 48 mil URLs** de spam de aposta, no
formato `https://iri.usp.br/bonusesr/47tetags4wdf2i4uswrjzn9pekdz4im2jyhjnx9/`.
São mais de 400 mil páginas injetadas num domínio `usp.br`, e há link para elas
em toda página legítima, inclusive na home.

O crawler antigo não tinha filtro de URL, nem teto de páginas, nem profundidade.
Apontado para ali, ele obedeceria — e foi isso que encheu o índice.

Três camadas, porque uma só sempre tem um furo:

1. `url_permitida` — nega por padrão conhecido antes de baixar qualquer coisa.
2. `segmento_aleatorio` — pega a *forma* da URL de spam, não a palavra. É o que
   continua funcionando quando o invasor troca "bonusesr" por outra coisa.
3. `DetectorAnomalia` — se, apesar dos dois, uma fatia grande do site cheira
   mal, a rodada inteira é descartada em vez de entrar no índice pela metade.
"""

import re
from urllib.parse import urlsplit

# Vocabulário de spam de aposta/cassino, que é o que se injeta em site .br
# comprometido. Casado contra o CAMINHO da URL, não contra o domínio.
TOKENS_SPAM = (
    "bonus", "bonuses", "bonusesr", "casino", "cassino", "slot", "slots", "gacor",
    "togel", "situs", "judi", "aposta", "apostas", "poker", "pragmatic", "maxwin",
    "rtp", "jackpot", "betting", "sportsbook", "spaceman", "mahjong",
)

# ─────────────────────────────────────────────
# Duas listas, e a separação entre elas importa mais do que parece.
#
# `NEGAR_SPAM` é *evidência de invasão*: uma URL assim num domínio usp.br não é
# uma página ruim, é sinal de que alguém escreve no servidor. Ela alimenta o
# DetectorAnomalia, que descarta a rodada inteira quando a proporção sobe.
#
# `NEGAR_HIGIENE` é só faxina: paginação, `/category/`, imagem, busca. Todo
# WordPress do mundo tem isso às centenas e não significa absolutamente nada
# sobre a saúde do site.
#
# Estavam numa lista só, e o resultado foi previsível: o `prpi.usp.br` — um
# WordPress comum, sitemap de 200 URLs, nada de errado — foi classificado como
# "97% spam, domínio comprometido" e abortado com 0 páginas, porque 28 URLs de
# `/category/` contaram como prova de invasão. Um alarme que dispara em site
# saudável é um alarme que alguém desliga.
# ─────────────────────────────────────────────
NEGAR_SPAM = [
    # O padrão exato do IRI, mais o vocabulário em volta.
    r"/(?:" + "|".join(TOKENS_SPAM) + r")(?:[0-9a-z]*)?/",
    r"/(?:games?|store|order|hot|dell|android|recomendados|plataforma)/",
]

NEGAR_HIGIENE = [
    # Encanamento de CMS: nada disso é conteúdo para aluno nenhum.
    r"/(?:wp-login|wp-admin|wp-json|xmlrpc|wp-content/plugins)",
    r"/(?:feed|rss|atom)/?$",
    r"/(?:comment|comments|trackback|replytocom)",
    r"/(?:author|tag|category|categoria|autor|etiqueta)/",
    # Intranet é conteúdo interno, não serve para aluno nenhum — e costuma ser
    # arquivo cumulativo. Uma única página de comunicados da EESC
    # (`/intranet/comunicados.php`) traz 2.803.609 caracteres e 21.700
    # parágrafos, o equivalente a metade do acervo inteiro.
    r"/intranet/",
    r"/page/\d+/?$",
    r"/\d{4}/\d{2}/\d{2}/",  # arquivo por data: muita URL, pouco conteúdo novo
    # Busca e ordenação geram URL infinita sem conteúdo novo. `q=` NÃO entra:
    # no Drupal ele é o parâmetro de caminho, e o portal do IQ inteiro
    # (437 páginas, o maior site do acervo) vive em `?q=pt-br/...`.
    r"[?&](?:s|search|busca|share|print|orderby|add-to-cart|filter|replytocom|like)=",
    # Binário que não é PDF. PDF passa: muita norma da USP só existe em PDF.
    r"\.(?:jpe?g|png|gif|svg|webp|ico|css|js|zip|rar|7z|tar|gz|mp[34]|avi|mov|"
    r"docx?|xlsx?|pptx?|odt|ods|exe|dmg)(?:$|\?)",
    # Idiomas e utilidades que só duplicam conteúdo.
    r"/(?:en|es|fr|de|it)/",
    r"(?:^|/)(?:login|logout|signin|carrinho|cart|checkout)(?:/|$)",
]

# Mantido como união das duas para quem só quer saber "esta URL entra?".
NEGAR_GLOBAL = NEGAR_SPAM + NEGAR_HIGIENE

_SPAM_COMPILADO = [re.compile(p, re.IGNORECASE) for p in NEGAR_SPAM]
_HIGIENE_COMPILADO = [re.compile(p, re.IGNORECASE) for p in NEGAR_HIGIENE]

# Os motivos que o DetectorAnomalia lê como evidência de domínio invadido. Um
# motivo fora desta lista recusa a URL e para por aí.
MOTIVOS_SPAM = frozenset({"spam_conhecido", "segmento_aleatorio", "vocabulario_spam", "sitemap_gigante"})

# Um segmento de URL legítimo é uma palavra ou um slug com hífen. O spam do IRI
# usa cadeias longas geradas por máquina; é isso que a heurística mede.
_VOGAIS = set("aeiouáéíóúâêôãõà")
MIN_SEGMENTO_SUSPEITO = 14


def segmento_aleatorio(url: str) -> bool:
    """Detecta segmento gerado por máquina, como `/47tetags4wdf2i4uswrjzn9pek/`.

    O teste é a proporção de vogais: `graduacao` e `pos-graduacao` têm bastante;
    `shtegugp49vj2v9ek3jvdr9pnjhgduwbgvju4zn` quase nenhuma. Slug com hífen é
    poupado, porque é a forma normal de título em WordPress.
    """
    for segmento in urlsplit(url).path.split("/"):
        if len(segmento) < MIN_SEGMENTO_SUSPEITO or "-" in segmento or "." in segmento:
            continue
        letras = [c for c in segmento.lower() if c.isalpha()]
        if not letras:
            continue
        proporcao = sum(1 for c in letras if c in _VOGAIS) / len(letras)
        digitos = sum(1 for c in segmento if c.isdigit()) / len(segmento)
        if proporcao < 0.28 or digitos > 0.35:
            return True
    return False


def url_permitida(url: str, config: dict | None = None) -> tuple[bool, str]:
    """`(permitida, motivo)`. O motivo é o que vai para o log e o relatório."""
    config = config or {}

    if not url or len(url) > 300:
        return False, "url_invalida"

    partes = urlsplit(url)
    if partes.scheme not in ("http", "https"):
        return False, "esquema"

    caminho = partes.path or "/"
    alvo = caminho + (("?" + partes.query) if partes.query else "")

    # A allowlist, quando existe, é a regra mais forte: nada fora dela passa.
    # É assim que o IRI entra sem trazer o resto do domínio junto.
    permitir = config.get("permitir") or []
    if permitir and not any(re.search(p, caminho, re.IGNORECASE) for p in permitir):
        return False, "fora_da_allowlist"

    for regex in _SPAM_COMPILADO:
        if regex.search(alvo):
            return False, "spam_conhecido"

    for regex in _HIGIENE_COMPILADO:
        if regex.search(alvo):
            return False, "higiene"

    for padrao in config.get("negar") or []:
        if re.search(padrao, alvo, re.IGNORECASE):
            return False, "negado_do_site"

    if segmento_aleatorio(url):
        return False, "segmento_aleatorio"

    return True, "ok"


def parece_spam(url: str, titulo: str = "", texto: str = "") -> tuple[bool, str]:
    """Segunda opinião, agora com a página na mão."""
    permitida, motivo = url_permitida(url)
    if not permitida and motivo in MOTIVOS_SPAM:
        return True, motivo

    alvo = f"{titulo} {texto[:3000]}".lower()
    if not alvo.strip():
        return False, "ok"

    achados = sum(1 for token in TOKENS_SPAM if token in alvo)
    por_mil = achados / max(len(alvo) / 1000, 1)
    if achados >= 3 and por_mil >= 1:
        return True, "vocabulario_spam"
    return False, "ok"


class DetectorAnomalia:
    """Conta o que foi recusado e decide se o site inteiro está perdido.

    Um site com uma página estranha é um site com uma página estranha. Um site
    em que 15% do que se vê é spam não tem um problema: ele foi invadido, e o
    certo é descartar a rodada inteira em vez de deixar entrar o que passou.
    """

    def __init__(self, limiar: float = 0.15, amostra_minima: int = 40):
        self.limiar = limiar
        self.amostra_minima = amostra_minima
        self.vistas = 0
        self.spam = 0
        self.recusadas: dict[str, int] = {}
        self._julgadas: dict[str, str] = {}

    def registrar(self, resultado: str, url: str | None = None) -> None:
        """Contabiliza um veredito. Passando `url`, a URL conta uma única vez.

        Sem esse cuidado a proporção era ficção: uma URL recusada nunca entra na
        fila, então ela reaparecia na lista candidata a cada sub-sitemap que
        chegava e era recontada. No `prpi` isso transformou 28 `/category/` em
        62 "spams" e disparou o aborto.

        Uma URL pode ser julgada duas vezes de verdade — aprovada pelo filtro de
        URL e reprovada depois, com a página na mão. Nesse caso o veredito é
        revisto, não somado: senão toda página boa contaria duas vezes e diluiria
        a proporção justamente do que o detector procura.
        """
        if url is not None:
            anterior = self._julgadas.get(url)
            if anterior == resultado:
                return
            self._julgadas[url] = resultado
            if anterior is not None:
                self._contabilizar(anterior, -1)
                self._contabilizar(resultado, +1)
                return

        self.vistas += 1
        self._contabilizar(resultado, +1)

    def _contabilizar(self, resultado: str, sinal: int) -> None:
        if resultado == "ok":
            return
        self.recusadas[resultado] = self.recusadas.get(resultado, 0) + sinal
        if self.recusadas[resultado] <= 0:
            self.recusadas.pop(resultado, None)
        if resultado in MOTIVOS_SPAM:
            self.spam += sinal

    def deve_abortar(self) -> tuple[bool, str]:
        if self.vistas < self.amostra_minima:
            return False, ""
        proporcao = self.spam / self.vistas
        if proporcao > self.limiar:
            return True, (
                f"{100 * proporcao:.0f}% das {self.vistas} URLs vistas são spam "
                f"(limite: {100 * self.limiar:.0f}%). O domínio parece comprometido."
            )
        return False, ""

    def resumo(self) -> dict:
        return {
            "urls_vistas": self.vistas,
            "urls_spam": self.spam,
            "recusadas_por_motivo": dict(self.recusadas),
        }
