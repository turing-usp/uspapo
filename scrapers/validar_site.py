"""Validação de site novo, antes de ele encostar no Pinecone.

Este é o portão que torna o incidente do IRI irrepetível. Ele raspa **um** site
para `data/raw/_quarentena/`, roda a limpeza e o chunking em memória, e mede.
Não escreve em `data/raw/`, não escreve em `data/processed/`, não fala com o
Pinecone.

Os portões são medidas objetivas, e três deles teriam barrado o `iri.usp.br`
sozinhos: dois antes mesmo de baixar uma página de conteúdo, só olhando o
sitemap (528 mil URLs em 11 sub-sitemaps).

Uso:
    python -m scrapers.validar_site --id sas
    python -m scrapers.validar_site --id iri --pular-crawl   # usa o que já está em _quarentena
"""

import argparse
import json
import os
import statistics
import subprocess
import sys

from embeddings import boilerplate, config_vetor as cfg
from embeddings.chunking import agrupar_paragrafos
from embeddings.clean_data import carregar_regras, limpar_texto
from embeddings.texto import segmentar_paragrafos
from scrapers.filtros import parece_spam

RAIZ = cfg.RAIZ_PROJETO
PASTA_QUARENTENA = os.path.join(RAIZ, "data", "raw", "_quarentena")

# Acima disto um "parágrafo" não é um parágrafo: é o sintoma do extrator antigo,
# que devolvia o container e os filhos juntos e colava a página inteira num
# bloco só. O limite NÃO é o tamanho do chunk (1100) — um parágrafo de prosa de
# 1.500 chars é comum e o `dividir_bloco_grande` corta em fronteira de frase
# sem problema nenhum. Medir contra 1100 reprovava site saudável por escrever
# parágrafo longo.
#
# Os números que calibram: no corpus extraído pelo código antigo, o `ee` tinha um
# parágrafo de 175.499 chars e 56,1% do texto acima deste limite; nos sites
# extraídos pelo código novo, o maior parágrafo tem 3.721 chars e a proporção é
# 0,0% em todos eles. A separação é limpa.
LIMITE_BLOB = 5 * cfg.CHUNK_MAX

# Duplicação só conta quando é de parágrafo LONGO. Repetir "OBJETO", uma data ou
# o nome do diretor numa página de licitações é como toda listagem funciona, e
# não faz mal nenhum ao índice: aquilo nunca vira um chunk sozinho.
#
# Medido nos dois corpora, a diferença é limpa. No corpus extraído com o bug de
# duplicação, o `if` tem 9,9% de repetição no total e **8,5%** dela em parágrafos
# longos; o `iq`, 6,8% e 4,2%. Num site saudável como o `cepeusp`, os mesmos
# 5,5% de repetição total viram **0,0%** quando se olha só o que é longo — era
# tudo rótulo curto. Contar tudo junto reprovava listagem legítima e passava
# perto demais do bug de verdade.
MIN_CHARS_DUPLICATA = 200

# (operador, limite). Cada um é uma barreira independente.
PORTOES = {
    "paginas": (">=", 10),
    "mediana_chars": (">=", 300),
    "pct_paginas_spam": ("<=", 0.02),
    "pct_chars_paragrafo_gigante": ("<=", 0.05),
    "pct_titulos_vazios": ("<=", 0.10),
    # 3%: o bug de duplicação marcava 8,5% (`if`), 4,2% (`iq`) e 3,5% (`ime`);
    # os sites sem o bug marcam 0,0%.
    "pct_duplicata_intra_pagina": ("<=", 0.03),
}


def rodar_crawl(id_site: str) -> str:
    os.makedirs(PASTA_QUARENTENA, exist_ok=True)
    destino = os.path.join(PASTA_QUARENTENA, f"{id_site}_raw.json")
    if os.path.exists(destino):
        os.remove(destino)
    subprocess.run(
        [sys.executable, "-m", "scrapy", "crawl", "spider_generico",
         "-a", f"config_id={id_site}", "-O", destino, "-L", "INFO"],
        check=False, cwd=RAIZ, timeout=2400,
    )
    return destino


def analisar(id_site: str, caminho: str) -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        brutos = json.load(f)

    regras, _ = carregar_regras()
    paginas = []
    for documento in brutos:
        url = documento.get("url", "")
        texto = limpar_texto(documento.get("texto_limpo", ""), url, regras)
        paginas.append(
            {"url": url, "titulo": (documento.get("titulo") or "").strip(), "texto_limpo": texto}
        )

    blocos_boilerplate = boilerplate.detectar_boilerplate(paginas)
    _, resumo_bp = boilerplate.remover_boilerplate(paginas, blocos_boilerplate)

    tamanhos, gigantes, chars, dup, spam, sem_titulo = [], 0, 0, 0, 0, 0
    total_chunks, chunks_curtos, maior_paragrafo = 0, 0, 0
    for pagina in paginas:
        texto = pagina["texto_limpo"]
        tamanhos.append(len(texto))
        if not pagina["titulo"]:
            sem_titulo += 1
        if parece_spam(pagina["url"], pagina["titulo"], texto)[0]:
            spam += 1

        paragrafos = segmentar_paragrafos(texto)
        chars += sum(len(p) for p in paragrafos)
        gigantes += sum(len(p) for p in paragrafos if len(p) > LIMITE_BLOB)
        maior_paragrafo = max([maior_paragrafo] + [len(p) for p in paragrafos])
        vistos: dict[str, int] = {}
        for p in paragrafos:
            vistos[p] = vistos.get(p, 0) + 1
        dup += sum(
            len(p) * (n - 1)
            for p, n in vistos.items()
            if n > 1 and len(p) >= MIN_CHARS_DUPLICATA
        )

        for chunk in agrupar_paragrafos(paragrafos):
            total_chunks += 1
            if len(chunk["texto"]) < cfg.CHUNK_MIN:
                chunks_curtos += 1

    n = max(len(paginas), 1)
    estatisticas = _ler_stats(id_site)
    return {
        "id_site": id_site,
        "paginas": len(paginas),
        "mediana_chars": statistics.median(tamanhos) if tamanhos else 0,
        "chars_totais": chars,
        "pct_paginas_spam": spam / n,
        "pct_chars_paragrafo_gigante": gigantes / max(chars, 1),
        "maior_paragrafo": maior_paragrafo,
        "pct_duplicata_intra_pagina": dup / max(chars, 1),
        "pct_titulos_vazios": sem_titulo / n,
        "pct_boilerplate": resumo_bp["chars_removidos"] / max(chars, 1),
        "blocos_boilerplate": resumo_bp["blocos"],
        "chunks_estimados": total_chunks,
        "chunks_curtos": chunks_curtos,
        "crawl": estatisticas,
        "amostra_urls": [p["url"] for p in paginas[:15]],
        "amostra_titulos": [p["titulo"] for p in paginas[:15]],
        "amostra_chunks": [
            c["texto"][:300]
            for pagina in paginas[:3]
            for c in agrupar_paragrafos(segmentar_paragrafos(pagina["texto_limpo"]))[:1]
        ],
    }


def _ler_stats(id_site: str) -> dict:
    caminho = os.path.join(RAIZ, "data", "raw", "_stats", f"{id_site}.json")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def avaliar_portoes(relatorio: dict) -> tuple[bool, list[str]]:
    reprovados = []
    for chave, (operador, limite) in PORTOES.items():
        valor = relatorio.get(chave, 0)
        passou = valor >= limite if operador == ">=" else valor <= limite
        if not passou:
            reprovados.append(f"{chave}={valor:.4g} (esperado {operador} {limite})")
    return not reprovados, reprovados


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida um site novo sem tocar no Pinecone.")
    parser.add_argument("--id", required=True, help="id_site em scrapers_config.json")
    parser.add_argument("--pular-crawl", action="store_true", help="Reaproveita o que já está em _quarentena.")
    argumentos = parser.parse_args()

    caminho = os.path.join(PASTA_QUARENTENA, f"{argumentos.id}_raw.json")
    if not argumentos.pular_crawl:
        caminho = rodar_crawl(argumentos.id)
    if not os.path.exists(caminho):
        print(f"[ERRO] Nada em {caminho}. O crawl não produziu saída.")
        raise SystemExit(2)

    relatorio = analisar(argumentos.id, caminho)
    aprovado, reprovados = avaliar_portoes(relatorio)
    relatorio["aprovado"] = aprovado
    relatorio["portoes_reprovados"] = reprovados

    os.makedirs(cfg.PASTA_RELATORIOS, exist_ok=True)
    destino = os.path.join(cfg.PASTA_RELATORIOS, f"onboarding_{argumentos.id}.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 56)
    print(f" VALIDAÇÃO DE '{argumentos.id}'")
    print("=" * 56)
    for chave in PORTOES:
        valor = relatorio.get(chave, 0)
        marca = "x" if any(chave in r for r in reprovados) else "ok"
        print(f"  [{marca:2s}] {chave:30s} {valor:.4g}")
    print(f"       {'maior parágrafo':30s} {relatorio['maior_paragrafo']} chars (blob > {LIMITE_BLOB})")
    print(f"       {'chunks estimados':30s} {relatorio['chunks_estimados']}")
    print(f"       {'boilerplate detectado':30s} {100 * relatorio['pct_boilerplate']:.1f}%")
    if relatorio["crawl"]:
        print(f"       crawl: {relatorio['crawl'].get('motivo_fim')} | "
              f"{relatorio['crawl'].get('urls_spam', 0)} URLs de spam recusadas")

    print("\n  Amostra de URLs:")
    for url in relatorio["amostra_urls"][:8]:
        print(f"    {url[:96]}")

    print("\n" + "=" * 56)
    if aprovado:
        print(" APROVADO. Para ativar, mude 'estado' para 'ativo' em scrapers_config.json.")
    else:
        print(" REPROVADO:")
        for item in reprovados:
            print(f"   - {item}")
    print(f" Relatório: {os.path.relpath(destino, RAIZ)}")
    print("=" * 56)
    raise SystemExit(0 if aprovado else 1)


if __name__ == "__main__":
    main()
