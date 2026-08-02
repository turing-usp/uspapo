import os
import json
import glob
import statistics

def simulador_de_chunks(texto, chunk_size=1000, chunk_overlap=200):
    """Simula o fatiamento de texto 100% nativo, sem bibliotecas externas."""
    if not texto:
        return []
    chunks = []
    i = 0
    while i < len(texto):
        chunks.append(texto[i:i + chunk_size])
        i += chunk_size - chunk_overlap
    return chunks

def relatorio_diagnostico():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    raiz_projeto = os.path.abspath(os.path.join(diretorio_atual, ".."))
    pasta_processed = os.path.join(raiz_projeto, "data", "processed")
    
    arquivos_limpos = glob.glob(os.path.join(pasta_processed, "**", "*_limpo.json"), recursive=True)
    
    if not arquivos_limpos:
        print("[ERRO] Nenhum arquivo limpo encontrado.")
        return

    todas_paginas = []
    total_chunks_geral = 0

    print("Processando arquivos para diagnóstico...\n")

    for caminho_arquivo in arquivos_limpos:
        instituto = os.path.basename(caminho_arquivo).replace("_limpo.json", "")
        
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            
        for doc in dados:
            texto = doc.get("texto_limpo", "")
            url = doc.get("url", "Sem URL")
            
            caracteres = len(texto)
            paragrafos = len(texto.split("\n\n"))
            
            # Simulando os chunks com nossa função nativa
            chunks = simulador_de_chunks(texto, chunk_size=1000, chunk_overlap=200)
            qtd_chunks = len(chunks)
            total_chunks_geral += qtd_chunks
            
            todas_paginas.append({
                "instituto": instituto.upper(),
                "url": url,
                "caracteres": caracteres,
                "paragrafos": paragrafos,
                "chunks": qtd_chunks
            })

    if not todas_paginas:
        print("Nenhuma página válida encontrada.")
        return

    # Cálculos Estatísticos
    lista_caracteres = [p["caracteres"] for p in todas_paginas]
    lista_chunks = [p["chunks"] for p in todas_paginas]
    
    media_chars = statistics.mean(lista_caracteres)
    mediana_chars = statistics.median(lista_caracteres)
    media_chunks = statistics.mean(lista_chunks)
    
    # Ordenando para pegar os Top 20 e Bottom 20
    paginas_ordenadas = sorted(todas_paginas, key=lambda x: x["chunks"], reverse=True)
    top_20 = paginas_ordenadas[:20]
    bottom_20 = paginas_ordenadas[-20:]

    # ==========================================
    # IMPRESSÃO DO RELATÓRIO
    # ==========================================
    print("="*60)
    print(" 📊 RELATÓRIO DE BENCHMARK DO CLEAN_DATA")
    print("="*60)
    print(f"Total de Páginas Limpas: {len(todas_paginas)}")
    print(f"Total de Chunks Simulados: {total_chunks_geral}")
    print(f"Média de Chunks por Página: {media_chunks:.2f}")
    print(f"Média de Caracteres por Página: {media_chars:.2f}")
    print(f"Mediana de Caracteres por Página: {mediana_chars:.2f}")
    print("="*60)
    
    print("\n🔥 TOP 20 PÁGINAS QUE MAIS GERARAM CHUNKS (Os 'Livros'):")
    print(f"{'INSTITUTO':<10} | {'CHUNKS':<6} | {'PARÁG.':<6} | {'CHARS':<8} | URL")
    print("-" * 80)
    for p in top_20:
        print(f"{p['instituto']:<10} | {p['chunks']:<6} | {p['paragrafos']:<6} | {p['caracteres']:<8} | {p['url'][:50]}...")

    print("\n🧊 BOTTOM 20 PÁGINAS QUE MENOS GERARAM CHUNKS (Os 'Avisos Curtos'):")
    print(f"{'INSTITUTO':<10} | {'CHUNKS':<6} | {'PARÁG.':<6} | {'CHARS':<8} | URL")
    print("-" * 80)
    for p in bottom_20:
        print(f"{p['instituto']:<10} | {p['chunks']:<6} | {p['paragrafos']:<6} | {p['caracteres']:<8} | {p['url'][:50]}...")
    print("\n")

if __name__ == "__main__":
    relatorio_diagnostico()