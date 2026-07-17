import json
import os
import hashlib
import glob  # <-- Importação essencial para varrer diretórios
import chromadb
from tqdm import tqdm   # <-- para ver uma barra de progresso na hora de criar os embeddings
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

def gerar_hash_chunk(texto: str) -> str:
    """Gera um identificador único universal (MD5) baseado exclusivamente no texto."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()

def construir_banco():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    # Apontamos para a PASTA e não mais para um arquivo fixo
    pasta_processed = os.path.join(diretorio_atual, "..", "data", "processed")
    caminho_db = os.path.join(diretorio_atual, "chroma_data")

    # Busca TODOS os arquivos .json dentro de data/processed/ E em suas subpastas
    arquivos_json = glob.glob(os.path.join(pasta_processed, "**", "*.json"), recursive=True)

    if not arquivos_json:
        print(f"[ERRO] Nenhum arquivo JSON encontrado em {pasta_processed}. Rode os limpadores primeiro.")
        return

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    # Inicializamos as estruturas FORA do loop de arquivos para unificar o lote
    documentos = []
    metadados = []
    ids = []
    hashes_vistos_no_lote = set()

    print(f"-> Encontrados {len(arquivos_json)} arquivos para processamento.")
    print("-> Fatiando textos e gerando assinaturas digitais (Hashes)...")
    
    # Loop que lê arquivo por arquivo encontrado na pasta
    for caminho_arquivo in arquivos_json:
        nome_arquivo = os.path.basename(caminho_arquivo)
        print(f"   Processando: {nome_arquivo}")
        
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
        except Exception as e:
            print(f"   [ERRO] Falha ao ler o arquivo {nome_arquivo}: {e}")
            continue

        for pagina in dados:
            chunks = text_splitter.split_text(pagina["texto_limpo"])
            
            for chunk in chunks:
                chunk_hash = gerar_hash_chunk(chunk)
                
                # O set impede duplicatas mesmo se o mesmo texto aparecer em JSONs diferentes
                if chunk_hash in hashes_vistos_no_lote:
                    continue
                    
                hashes_vistos_no_lote.add(chunk_hash)
                
                documentos.append(chunk)
                metadados.append({
                    "url": pagina["url"],
                    "titulo": pagina["titulo"],
                    "arquivo_origem": nome_arquivo  # Ganhamos esse metadado de graça sem esforço
                })
                ids.append(chunk_hash)

    print(f"-> Total de blocos únicos combinados neste lote: {len(documentos)}")

    print("-> Conectando ao banco de dados ChromaDB...")
    cliente = chromadb.PersistentClient(path=caminho_db)
    
    funcao_embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    colecao = cliente.get_or_create_collection(
        name="poli_chatbot",
        embedding_function=funcao_embedding
    )

    print("-> Sincronizando dados de forma incremental (Upserting)...")
    if documentos:
        # Define um lote seguro, abaixo do limite de 5461 do ChromaDB
        tamanho_lote = 5000 
        
        # O tqdm vai criar aquela barra de progresso visual no terminal
        for i in tqdm(range(0, len(documentos), tamanho_lote), desc="Enviando lotes ao ChromaDB"):
            lote_docs = documentos[i : i + tamanho_lote]
            lote_metas = metadados[i : i + tamanho_lote]
            lote_ids = ids[i : i + tamanho_lote]
            
            colecao.upsert(
                documents=lote_docs,
                metadatas=lote_metas,
                ids=lote_ids
            )
    
    total_gavetas = colecao.count()
    print("\n[SUCESSO NA ARQUITETURA]")
    print(f"O banco incremental possui agora um total de {total_gavetas} gavetas armazenadas.")

if __name__ == "__main__":
    construir_banco()