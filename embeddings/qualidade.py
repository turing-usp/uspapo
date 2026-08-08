"""Portões de qualidade: o que não merece virar vetor.

O filtro antigo era um `len(texto) > 50` aplicado à PÁGINA inteira, em
`clean_data.py`. Uma página de 5.000 caracteres passava, e ninguém olhava o que
saía dela depois de fatiada, foi assim que 742 chunks com menos de 200
caracteres, e um chunk de **um único caractere**, acabaram embarcados no índice.

Cada um desses ocupa uma vaga no `top_k=3` da busca. Não é só desperdício de
cota: é uma vaga a menos para o trecho que responderia a pergunta.

A regra de ouro aqui é que descartar é o último recurso. Chunk curto quase
sempre é fim de página que ficou órfão, e a resposta certa para ele é fundir no
anterior (o `chunking.py` faz isso antes de chegar aqui). Só chega neste módulo
o que não tinha em que fundir.
"""

import re

from embeddings import config_vetor as cfg
from embeddings.texto import contar_palavras, proporcao_de_letras

# Uma lista de menu vira uma sequência de linhas curtíssimas sem verbo. Não dá
# para detectar isso semanticamente sem modelo, mas a forma entrega: muitas
# linhas, quase nenhuma pontuação de frase.
MIN_PALAVRAS = 25
RAZAO_MIN_LETRAS = 0.55

_RE_LINHA = re.compile(r"\n+")


def _parece_so_navegacao(texto: str) -> bool:
    linhas = [linha.strip() for linha in _RE_LINHA.split(texto) if linha.strip()]
    if len(linhas) < 4:
        return False
    curtas = sum(1 for linha in linhas if len(linha) <= 30)
    sem_ponto = sum(1 for linha in linhas if not re.search(r"[.!?]", linha))
    return curtas / len(linhas) > 0.8 and sem_ponto / len(linhas) > 0.8


def motivo_descarte(texto: str, unico_da_pagina: bool = False) -> str | None:
    """`None` = aprovado. String = por que este chunk não vira vetor.

    `unico_da_pagina` afrouxa o mínimo: um aviso curto que é o único conteúdo
    da página é conteúdo legítimo, e não há como fundi-lo em coisa nenhuma.
    """
    limpo = (texto or "").strip()
    if not limpo:
        return "vazio"

    minimo = 120 if unico_da_pagina else cfg.CHUNK_MIN
    if len(limpo) < minimo:
        return "curto"
    if contar_palavras(limpo) < MIN_PALAVRAS:
        return "poucas_palavras"
    if proporcao_de_letras(limpo) < RAZAO_MIN_LETRAS:
        return "pouca_letra"
    if _parece_so_navegacao(limpo):
        return "so_navegacao"
    return None


def filtrar_chunks(chunks: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Aplica os portões a uma lista de chunks já formada.

    Devolve `(aprovados, contagem_por_motivo)` — a contagem vai para o relatório,
    porque um motivo que dispara demais é sinal de que o portão está mal
    calibrado, não de que o site é ruim.
    """
    aprovados: list[dict] = []
    descartes: dict[str, int] = {}
    unico = len(chunks) == 1

    for chunk in chunks:
        texto = chunk.get("texto")
        # Chunk sem texto veio do ledger: é um reaproveitado do rechunking
        # ancorado, que já passou por estes portões quando nasceu. Reprová-lo
        # agora só o mataria e o faria renascer idêntico na execução seguinte.
        if texto is None:
            aprovados.append(chunk)
            continue

        motivo = motivo_descarte(texto, unico_da_pagina=unico)
        if motivo is None:
            aprovados.append(chunk)
        else:
            descartes[motivo] = descartes.get(motivo, 0) + 1

    return aprovados, descartes
