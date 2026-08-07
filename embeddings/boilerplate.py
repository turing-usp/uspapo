"""Detecção automática do que se repete em todas as páginas de um site.

Menu, rodapé, telefone da portaria, "Siga nossas redes sociais": conteúdo que
aparece em toda página e não responde pergunta nenhuma. Ele custa vetor, custa
cota, e pior: ocupa vaga no `top_k=3` competindo com o trecho que responderia.

Até aqui o combate a isso era manual: alguém abria o site, via o rodapé, e
escrevia uma regex em `regras_ruido.json`. Isso não escala e apodrece sozinho:
das regras escritas assim, 9 já não casavam mais nada, e ninguém tinha como
saber. E o resultado medido é ruim: no `hu`, 35,5% de todos os caracteres ainda
eram blocos repetidos que nenhuma regra pegava.

Aqui a conta é estatística e não precisa de manutenção: bloco que aparece em
muitas páginas do mesmo site é estrutura, não conteúdo. As regras manuais
continuam existindo para o caso específico, mas deixam de ser o mecanismo
principal.

Uma ressalva importante de calibração: isto só rende **depois** do extrator
novo. Enquanto metade do texto de um site vinha grudada num único blob por
página, dois rodapés idênticos ficavam escondidos dentro de blobs que nunca se
repetiam byte a byte. Medido, o detector achava 0,0% no `iq` e 0,4% no `if`.
"""

from collections import Counter

from embeddings.texto import normalizar_bloco

# Fração das páginas em que o bloco precisa aparecer para contar como estrutura.
LIMIAR_FREQUENCIA = 0.30
# Piso absoluto: num site de 6 páginas, 30% seriam 2, e duas coincidências não
# fazem um rodapé.
MIN_PAGINAS = 4
# Bloco curto demais é ruído de qualquer jeito; bloco longo demais que se repete
# costuma ser conteúdo real (ementa de disciplina, texto de edital republicado),
# e apagá-lo seria pior que mantê-lo.
MIN_CHARS = 15
MAX_CHARS = 400
# Nenhuma página pode perder mais que isto por boilerplate. Se passou, o
# diagnóstico está errado e é melhor manter tudo do que devolver página vazia.
TETO_REMOCAO = 0.60


def detectar_boilerplate(
    paginas: list[dict],
    limiar_frequencia: float = LIMIAR_FREQUENCIA,
    min_paginas: int = MIN_PAGINAS,
    min_chars: int = MIN_CHARS,
    max_chars: int = MAX_CHARS,
) -> dict[str, int]:
    """Devolve `{chave_normalizada: em_quantas_paginas}` do que é estrutura.

    Conta por PÁGINA, não por ocorrência: um bloco repetido 50 vezes dentro de
    uma página só é uma página, senão uma tabela longa viraria "boilerplate".
    """
    if not paginas:
        return {}

    frequencia: Counter = Counter()
    for pagina in paginas:
        vistos = set()
        for bloco in pagina.get("texto_limpo", "").split("\n\n"):
            bloco = bloco.strip()
            if not (min_chars <= len(bloco) <= max_chars):
                continue
            vistos.add(normalizar_bloco(bloco))
        frequencia.update(vistos)

    corte = max(min_paginas, int(len(paginas) * limiar_frequencia))
    return {chave: n for chave, n in frequencia.items() if n >= corte and chave}


def remover_boilerplate(
    paginas: list[dict], blocos: dict[str, int], teto_remocao: float = TETO_REMOCAO
) -> tuple[list[dict], dict]:
    """Tira os blocos detectados, respeitando o teto por página."""
    if not blocos:
        return paginas, {"blocos": 0, "chars_removidos": 0, "paginas_afetadas": 0}

    chars_removidos = 0
    paginas_afetadas = 0
    paginas_no_teto = 0
    saida = []

    for pagina in paginas:
        original = pagina.get("texto_limpo", "")
        partes = [p.strip() for p in original.split("\n\n") if p.strip()]
        mantidos = [p for p in partes if normalizar_bloco(p) not in blocos]

        novo = "\n\n".join(mantidos)
        removido = len(original) - len(novo)

        # Página que perderia quase tudo quase certamente teve o diagnóstico
        # errado (site de página única, ou um site em que tudo se parece).
        if original and removido / max(len(original), 1) > teto_remocao:
            paginas_no_teto += 1
            saida.append(pagina)
            continue

        if removido > 0:
            paginas_afetadas += 1
            chars_removidos += removido
            pagina = {**pagina, "texto_limpo": novo}
        saida.append(pagina)

    return saida, {
        "blocos": len(blocos),
        "chars_removidos": chars_removidos,
        "paginas_afetadas": paginas_afetadas,
        "paginas_no_teto": paginas_no_teto,
    }


def limpar_site(paginas: list[dict]) -> tuple[list[dict], dict]:
    """Atalho: detecta e remove numa chamada só."""
    blocos = detectar_boilerplate(paginas)
    return remover_boilerplate(paginas, blocos)
