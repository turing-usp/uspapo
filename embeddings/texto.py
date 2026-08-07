"""Funções puras de texto, compartilhadas pela extração e pela indexação.

Vive aqui, e não duplicado dos dois lados, por uma razão dura: a normalização
tem que ser **idêntica** na hora de extrair e na hora de comparar hash. Um
espaço a mais de um lado e o `hash_p` daquele parágrafo muda, o rechunking
ancorado deixa de reconhecê-lo, e a página inteira é reenviada como se fosse
nova. Duas cópias da mesma função é exatamente como esse tipo de divergência
começa.

Nada aqui importa scrapy, pinecone ou rede — é tudo testável direto.
"""

import re
import unicodedata

# ─────────────────────────────────────────────
# Normalização
# ─────────────────────────────────────────────
# Espaços que não são o espaço comum: NBSP, espaços tipográficos, e os de
# largura zero que vêm de CMS e de copiar-colar do Word. Todos viram ' ' ou nada.
_ESPACOS_ESQUISITOS = dict.fromkeys(
    [0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
     0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000],
    " ",
)
_INVISIVEIS = dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD], "")
_TRADUCAO = {**_ESPACOS_ESQUISITOS, **_INVISIVEIS}

# Hifenização de quebra de linha em PDF: "gradua-\nção" -> "graduação". Só une
# quando o que vem depois é minúscula, para não estragar "Norte-\nSul".
_HIFEN_QUEBRA = re.compile(r"(\w)-\s*\n\s*([a-zà-ÿ])")


def normalizar(texto: str) -> str:
    """Deixa o texto em forma canônica, sem alterar o conteúdo visível."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFC", texto)
    texto = texto.translate(_TRADUCAO)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _HIFEN_QUEBRA.sub(r"\1\2", texto)
    # Remove controles (menos \n e \t), que aparecem em PDF mal extraído.
    texto = "".join(
        c for c in texto if c in "\n\t" or unicodedata.category(c)[0] != "C"
    )
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def segmentar_paragrafos(texto: str) -> list[str]:
    """Quebra em parágrafos pela linha em branco, como o pipeline sempre fez."""
    if not texto:
        return []
    return [p.strip() for p in texto.split("\n\n") if p.strip()]


# ─────────────────────────────────────────────
# Sentenças
# ─────────────────────────────────────────────
# Sem esta lista, "Prof. Dr. João" vira três sentenças e o fatiamento corta no
# meio de um nome. São as abreviações que de fato aparecem em site de unidade da
# USP: título acadêmico, endereço, mês e latinismo de texto normativo.
_ABREVIACOES = [
    "prof", "profa", "profº", "profª", "dr", "dra", "drª", "sr", "sra", "srta",
    "exmo", "exma", "ilmo", "ilma", "me", "esp", "eng", "arq", "adv",
    "av", "r", "al", "pç", "trav", "rod", "km", "ed", "apto", "ap", "bl", "cj",
    "univ", "dept", "depto", "dep", "fac", "inst", "cia", "ltda", "cf", "op",
    "etc", "ex", "obs", "pág", "pag", "p", "pp", "art", "arts", "inc", "par",
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out",
    "nov", "dez", "séc", "sec", "aprox", "máx", "max", "mín", "min", "no", "nº",
]

_SENTINELA = "\x00"

_RE_ABREV = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ABREVIACOES) + r")\.", re.IGNORECASE
)
_RE_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
_RE_INICIAL = re.compile(r"\b([A-ZÀ-Þ])\.")
_RE_RETICENCIA = re.compile(r"\.\.\.")

# Fim de sentença: pontuação terminal, mais o fechamento de aspas/parênteses que
# venha grudado, desde que o próximo caractere seja espaço ou o fim do texto.
_RE_FIM = re.compile(r"[.!?…]+[\"'»”’\)\]]*(?=\s|$)")


def _proteger(texto: str) -> str:
    texto = _RE_RETICENCIA.sub(_SENTINELA * 3, texto)
    texto = _RE_ABREV.sub(lambda m: m.group(1) + _SENTINELA, texto)
    texto = _RE_DECIMAL.sub(_SENTINELA, texto)
    texto = _RE_INICIAL.sub(lambda m: m.group(1) + _SENTINELA, texto)
    return texto


def _desproteger(texto: str) -> str:
    return texto.replace(_SENTINELA, ".")


def separar_sentencas(texto: str) -> list[str]:
    """Divide em sentenças sem cortar dentro de abreviação, sigla ou decimal.

    É o que substitui o corte cego em caractere: 32% dos chunks do índice antigo
    começavam ou terminavam no meio de uma palavra porque o fatiador antigo
    simplesmente contava 1100 caracteres e cortava ali.
    """
    if not texto or not texto.strip():
        return []

    protegido = _proteger(texto)
    sentencas: list[str] = []
    inicio = 0
    for casamento in _RE_FIM.finditer(protegido):
        trecho = protegido[inicio : casamento.end()].strip()
        if trecho:
            sentencas.append(_desproteger(trecho))
        inicio = casamento.end()

    resto = protegido[inicio:].strip()
    if resto:
        sentencas.append(_desproteger(resto))
    return sentencas


# ─────────────────────────────────────────────
# Detecção de lixo
# ─────────────────────────────────────────────
_RE_LETRA = re.compile(r"[A-Za-zÀ-ÿ]")


def proporcao_de_letras(texto: str) -> float:
    if not texto:
        return 0.0
    return len(_RE_LETRA.findall(texto)) / len(texto)


def contar_palavras(texto: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]+", texto))


def eh_lixo(paragrafo: str) -> bool:
    """Parágrafo que não carrega informação nenhuma.

    Pega o `----------------------------------------` que o site do IQ repete
    164 vezes, célula de tabela só com número, e o item de menu solto.
    """
    limpo = paragrafo.strip()
    if not limpo:
        return True
    if not _RE_LETRA.search(limpo):
        return True
    if len(set(limpo)) <= 3:
        return True
    return False


def normalizar_bloco(texto: str) -> str:
    """Chave de agrupamento para detectar boilerplate.

    Casefold e sem pontuação de borda, para que "Contato" e "CONTATO:" contem
    como o mesmo bloco repetido. O que vai para o índice continua sendo o texto
    original — isto aqui é só a chave.
    """
    limpo = re.sub(r"\s+", " ", texto).strip().casefold()
    return limpo.strip(" .:;,-–—|•*/\\\t")
