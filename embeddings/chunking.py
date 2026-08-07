"""Chunking: como uma página vira os blocos que o e5 vetoriza.

Duas coisas mudaram em relação ao que estava dentro do `build_vector.py`.

**O fatiamento de bloco grande não corta mais no meio da palavra.** O
`fatiar_texto_gigante` antigo contava 1100 caracteres e cortava ali, ponto.
2.586 dos 7.994 chunks do índice (32%) nasceram assim: começando e terminando
no meio de uma frase, às vezes no meio de uma palavra. Um trecho desses é ruim
para o embedding e é pior ainda para o usuário, que recebe a citação truncada.
Agora a divisão respeita, em ordem: parágrafo, linha, fim de sentença,
pontuação, e só em último caso o espaço.

**Sobre o overlap, uma decisão explícita: ele NÃO existe entre chunks formados
por parágrafos, só dentro do fatiamento de um bloco grande.** A tentação é
óbvia: overlap melhora recall na emenda de dois chunks. Mas o rechunking
ancorado reaproveita um chunk antigo quando a sequência de hashes de parágrafo
bate, e reaproveita o objeto inteiro, texto inclusive. Se o texto carregasse a
cauda do chunk anterior, bastaria o parágrafo anterior mudar para o texto
reaproveitado ficar desatualizado sem que nenhum hash acusasse: um vetor
mentindo em silêncio. Fronteira de parágrafo já é fronteira semântica; a emenda
que realmente machuca é a que acontece dentro de um muro de texto corrido, e
essa tem overlap.
"""

import hashlib

from embeddings import config_vetor as cfg
from embeddings.texto import separar_sentencas

# Ordem de preferência para partir um bloco grande: do corte mais natural para o
# mais violento. O "" no fim é a rendição — só é usado se não houver nem espaço.
SEPARADORES = ["\n\n", "\n", ". ", "! ", "? ", "; ", ": ", ", ", " ", ""]


def gerar_hash(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def montar_chunk(paragrafos: list[str]) -> dict:
    """O formato único de chunk. Antes isto estava copiado nove vezes."""
    junto = "\n\n".join(paragrafos)
    return {
        "texto": junto,
        "hash_chunk": gerar_hash(junto),
        "hashes_p": [gerar_hash(p) for p in paragrafos],
    }


def texto_para_embedding(titulo: str, chunk: str) -> str:
    """O que de fato é vetorizado.

    O `passage:` é convenção do e5 (a busca manda `query:` do outro lado). O
    título entra junto porque ancora o trecho na unidade a que ele pertence: um
    chunk que só diz "As inscrições vão até dia 30" não tem como ser recuperado
    por "prazo de matrícula na Poli" sem isso.
    """
    titulo = (titulo or "").strip()
    if titulo:
        return f"passage: {titulo}\n\n{chunk}"
    return f"passage: {chunk}"


# ─────────────────────────────────────────────
# Fatiamento de bloco grande
# ─────────────────────────────────────────────
def _fatiador_langchain(max_size: int, overlap: int):
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        return None
    return RecursiveCharacterTextSplitter(
        chunk_size=max_size,
        chunk_overlap=overlap,
        separators=SEPARADORES,
        keep_separator=True,
        length_function=len,
    )


def _fatiar_por_sentenca(texto: str, max_size: int, overlap: int) -> list[str]:
    """Plano B, sem dependência externa: agrupa sentenças até o teto."""
    sentencas = separar_sentencas(texto) or [texto]
    fatias: list[str] = []
    atual: list[str] = []
    tamanho = 0

    for sentenca in sentencas:
        # Sentença que sozinha estoura o teto (tabela colada, lista sem
        # pontuação): parte no espaço, que ainda é melhor que no meio da palavra.
        if len(sentenca) > max_size:
            if atual:
                fatias.append(" ".join(atual))
                atual, tamanho = [], 0
            palavras = sentenca.split(" ")
            pedaco: list[str] = []
            for palavra in palavras:
                if sum(len(x) + 1 for x in pedaco) + len(palavra) > max_size and pedaco:
                    fatias.append(" ".join(pedaco))
                    pedaco = []
                pedaco.append(palavra)
            if pedaco:
                fatias.append(" ".join(pedaco))
            continue

        if tamanho + len(sentenca) + 1 > max_size and atual:
            fatias.append(" ".join(atual))
            # Carrega a última sentença para a fatia seguinte, se couber no
            # orçamento de overlap.
            cauda = atual[-1] if len(atual[-1]) <= overlap else ""
            atual = [cauda] if cauda else []
            tamanho = len(cauda)

        atual.append(sentenca)
        tamanho += len(sentenca) + 1

    if atual:
        fatias.append(" ".join(atual))
    return [f.strip() for f in fatias if f.strip()]


def dividir_bloco_grande(
    texto: str, max_size: int | None = None, overlap: int | None = None
) -> list[str]:
    """Parte um bloco maior que o teto sem cortar palavra."""
    max_size = max_size or cfg.CHUNK_MAX
    overlap = cfg.CHUNK_OVERLAP if overlap is None else overlap

    if len(texto) <= max_size:
        return [texto]

    fatiador = _fatiador_langchain(max_size, overlap)
    if fatiador is not None:
        fatias = [f.strip() for f in fatiador.split_text(texto) if f.strip()]
        # O RecursiveCharacterTextSplitter pode estourar o teto quando nem o
        # separador "" resolve. Se isso acontecer, o plano B assume.
        if fatias and all(len(f) <= max_size for f in fatias):
            return fatias

    return _fatiar_por_sentenca(texto, max_size, overlap)


# ─────────────────────────────────────────────
# Agrupamento por parágrafo
# ─────────────────────────────────────────────
def _fundir_curtos(grupos: list[list[str]], min_size: int, max_size: int) -> list[list[str]]:
    """Funde grupo curto no vizinho, em vez de deixá-lo virar vetor inútil.

    É o conserto na origem dos 742 chunks com menos de 200 caracteres: quase
    todos eram sobra de fim de página, e sobra tem onde caber.
    """
    if len(grupos) <= 1:
        return grupos

    resultado = [list(g) for g in grupos]
    i = 0
    while i < len(resultado):
        tamanho = len("\n\n".join(resultado[i]))
        if tamanho >= min_size or len(resultado) == 1:
            i += 1
            continue

        anterior = i - 1 if i > 0 else None
        seguinte = i + 1 if i + 1 < len(resultado) else None

        def cabe(indice):
            if indice is None:
                return False
            return len("\n\n".join(resultado[indice] + resultado[i])) <= max_size

        # Prefere o anterior: mantém a ordem de leitura do documento.
        if cabe(anterior):
            resultado[anterior].extend(resultado[i])
            del resultado[i]
            i = max(0, anterior)
        elif cabe(seguinte):
            resultado[seguinte][:0] = resultado[i]
            del resultado[i]
        else:
            i += 1
    return resultado


def agrupar_paragrafos(
    paragrafos: list[str],
    alvo: int | None = None,
    max_size: int | None = None,
    min_size: int | None = None,
) -> list[dict]:
    """Empacota parágrafos em chunks, gulosamente, respeitando o teto."""
    alvo = alvo or cfg.CHUNK_ALVO
    max_size = max_size or cfg.CHUNK_MAX
    min_size = cfg.CHUNK_MIN if min_size is None else min_size

    grupos: list[list[str]] = []
    atual: list[str] = []
    tamanho = 0

    def fechar():
        nonlocal atual, tamanho
        if atual:
            grupos.append(atual)
            atual, tamanho = [], 0

    for paragrafo in paragrafos:
        if len(paragrafo) > max_size:
            fechar()
            for fatia in dividir_bloco_grande(paragrafo, max_size):
                grupos.append([fatia])
            continue

        projetado = tamanho + len(paragrafo) + (2 if atual else 0)
        if projetado <= alvo:
            atual.append(paragrafo)
            tamanho = projetado
        elif projetado <= max_size:
            atual.append(paragrafo)
            fechar()
        else:
            fechar()
            atual = [paragrafo]
            tamanho = len(paragrafo)

    fechar()
    grupos = _fundir_curtos(grupos, min_size, max_size)
    return [montar_chunk(g) for g in grupos]


# ─────────────────────────────────────────────
# Rechunking ancorado
# ─────────────────────────────────────────────
def rechunking_ancorado(
    old_chunks: list[dict],
    novos_paragrafos: list[str],
    alvo: int | None = None,
    max_size: int | None = None,
    min_size: int | None = None,
) -> list[dict]:
    """Reagrupa a página aproveitando os chunks que não mudaram.

    A ideia, que já estava certa no código antigo: se uma sequência de
    parágrafos reproduz exatamente a assinatura de hashes de um chunk que já
    existe, aquele chunk é o mesmo, reaproveita o objeto e o `chunk_id`, e o
    Pinecone nem fica sabendo. O que sobra entre as âncoras é reagrupado
    normalmente.

    Devolve a lista final de chunks; os reaproveitados vêm com `chunk_id`, os
    novos vêm sem. Quem decide o que nasce e o que morre é o `build_vector.py`,
    que é quem tem a contagem de referência na mão.
    """
    alvo = alvo or cfg.CHUNK_ALVO
    max_size = max_size or cfg.CHUNK_MAX
    min_size = cfg.CHUNK_MIN if min_size is None else min_size

    ancoras: dict[str, list[dict]] = {}
    for chunk in old_chunks:
        hashes = chunk.get("hashes_p") or []
        if not hashes:
            continue
        ancoras.setdefault(hashes[0], []).append(
            {"assinatura": "".join(hashes), "tamanho": len(hashes), "chunk": chunk}
        )

    hashes_novos = [gerar_hash(p) for p in novos_paragrafos]
    total = len(novos_paragrafos)

    finais: list[dict] = []
    pendentes: list[str] = []  # parágrafos ainda sem chunk, a reagrupar
    usados: set[str] = set()
    indice = 0

    def drenar_pendentes():
        nonlocal pendentes
        if pendentes:
            finais.extend(agrupar_paragrafos(pendentes, alvo, max_size, min_size))
            pendentes = []

    while indice < total:
        ancorado = False
        for candidato in ancoras.get(hashes_novos[indice], []):
            chunk_id = candidato["chunk"].get("chunk_id")
            if chunk_id and chunk_id in usados:
                continue
            tamanho = candidato["tamanho"]
            if indice + tamanho > total:
                continue
            if "".join(hashes_novos[indice : indice + tamanho]) != candidato["assinatura"]:
                continue

            drenar_pendentes()
            finais.append(candidato["chunk"])
            if chunk_id:
                usados.add(chunk_id)
            indice += tamanho
            ancorado = True
            break

        if not ancorado:
            pendentes.append(novos_paragrafos[indice])
            indice += 1

    drenar_pendentes()
    return finais
