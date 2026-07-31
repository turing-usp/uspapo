import json
import os
import glob
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==============================================================================
# 1. ALGORITMO NOVO (Compactador Semântico)
# ==============================================================================
def agrupar_lista_de_paragrafos(lista_textos_paragrafos: list, target_size=800, max_size=1100) -> list:
    chunks_formados = []
    chunk_atual_textos = []
    tamanho_atual = 0

    for p in lista_textos_paragrafos:
        tam_p = len(p)
        if tam_p > max_size:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_formados.append(texto_junto)
                chunk_atual_textos = []
                tamanho_atual = 0
            chunks_formados.append(p)
            continue

        tamanho_projetado = tamanho_atual + tam_p + (2 if chunk_atual_textos else 0)

        if tamanho_projetado <= target_size:
            chunk_atual_textos.append(p)
            tamanho_atual = tamanho_projetado
        elif tamanho_projetado <= max_size:
            chunk_atual_textos.append(p)
            texto_junto = "\n\n".join(chunk_atual_textos)
            chunks_formados.append(texto_junto)
            chunk_atual_textos = []
            tamanho_atual = 0
        else:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_formados.append(texto_junto)
            chunk_atual_textos = [p]
            tamanho_atual = tam_p

    if chunk_atual_textos:
        texto_junto = "\n\n".join(chunk_atual_textos)
        chunks_formados.append(texto_junto)

    return chunks_formados

# ==============================================================================
# 2. FUNÇÃO DE CÁLCULO DO P95
# ==============================================================================
def calcular_p95(tamanhos):
    if not tamanhos: return 0
    tamanhos_ordenados = sorted(tamanhos)
    idx = int(len(tamanhos_ordenados) * 0.95)
    return tamanhos_ordenados[idx]

# ==============================================================================
# 3. BENCHMARK COMPARATIVO
# ==============================================================================
def rodar_benchmark():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    pasta_processed = os.path.join(diretorio_atual, "..", "data", "processed")
    arquivos_json = glob.glob(os.path.join(pasta_processed, "**", "*.json"), recursive=True)

    if not arquivos_json:
        print("[ERRO] Nenhum JSON encontrado em processed.")
        return

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    tamanhos_antigo = []
    tamanhos_novo = []
    total_caracteres_puros = 0

    print("-> Lendo dados e processando chunks nos dois algoritmos...")

    for caminho_arquivo in arquivos_json:
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            paginas = json.load(f)
            
        for pagina in paginas:
            texto_cru = pagina.get("texto_limpo", "")
            
            # Conta apenas os caracteres de texto que importam (sem espaços/quebras nas pontas)
            texto_cru_limpo = texto_cru.strip()
            if not texto_cru_limpo:
                continue
                
            total_caracteres_puros += len(texto_cru_limpo)

            # --- RODA O ALGORITMO ANTIGO ---
            chunks_antigos = text_splitter.split_text(texto_cru)
            tamanhos_antigo.extend([len(c) for c in chunks_antigos])

            # --- RODA O ALGORITMO NOVO ---
            paragrafos_pagina = [p.strip() for p in texto_cru.split("\n\n") if p.strip()]
            chunks_novos = agrupar_lista_de_paragrafos(paragrafos_pagina)
            tamanhos_novo.extend([len(c) for c in chunks_novos])

    # --- CALCULA AS ESTATÍSTICAS ---
    total_chars_antigo = sum(tamanhos_antigo)
    total_chars_novo = sum(tamanhos_novo)

    print("\n" + "="*70)
    print("1. COBERTURA DE TEXTO (Nenhum dado se perdeu?)")
    print("="*70)
    print(f"Caracteres puros originais (Base real) : {total_caracteres_puros:,}")
    print(f"Caracteres gerados pelo LangChain (Antigo) : {total_chars_antigo:,} (Inflado pelo Overlap!)")
    print(f"Caracteres gerados pela Ancoragem (Novo)   : {total_chars_novo:,} (Otimizado!)")
    print(f" -> Taxa de Cobertura do Novo: ~{(total_chars_novo/total_caracteres_puros)*100:.1f}%")
    print("    (Espera-se ~100%. Uma pequena variação extra vem dos '\\n\\n' adicionados no agrupamento).")

    print("\n" + "="*70)
    print(f"{'2. DISTRIBUIÇÃO DOS CHUNKS':<40} | {'ANTIGO':<12} | {'NOVO':<12}")
    print("="*70)
    print(f"{'Total de Chunks gerados':<40} | {len(tamanhos_antigo):<12} | {len(tamanhos_novo):<12}")
    print(f"{'Média de caracteres por chunk':<40} | {int(total_chars_antigo/len(tamanhos_antigo)):<12} | {int(total_chars_novo/len(tamanhos_novo)):<12}")
    print(f"{'Mediana':<40} | {sorted(tamanhos_antigo)[len(tamanhos_antigo)//2]:<12} | {sorted(tamanhos_novo)[len(tamanhos_novo)//2]:<12}")
    print(f"{'Percentil 95 (95% dos chunks têm até)':<40} | {calcular_p95(tamanhos_antigo):<12} | {calcular_p95(tamanhos_novo):<12}")
    print(f"{'Máximo Absoluto':<40} | {max(tamanhos_antigo):<12} | {max(tamanhos_novo):<12}")

    print("\n" + "="*70)
    print("3. TESTE DOS 'GIGANTES' E ANOMALIAS")
    print("="*70)
    print(f"Chunks entre 0 e 100 caracteres (Micro-lixo):")
    print(f" - Antigo: {len([t for t in tamanhos_antigo if t <= 100])}")
    print(f" - Novo  : {len([t for t in tamanhos_novo if t <= 100])}")
    print(f"\nChunks maiores que 1100 caracteres:")
    print(f" - Antigo: {len([t for t in tamanhos_antigo if t > 1100])}")
    print(f" - Novo  : {len([t for t in tamanhos_novo if t > 1100])} (Blocos intocáveis para proteger semântica)")

if __name__ == "__main__":
    rodar_benchmark()