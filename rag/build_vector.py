import json
import os
import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

def construir_banco():
    # 1. Resolver caminhos de forma segura (igual fizemos no clean_data)
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_json = os.path.join(diretorio_atual, "..", "data", "processed", "poliscrap_limpo.json")
    
    # Esta é a pasta onde o banco de dados real vai nascer!
    caminho_db = os.path.join(diretorio_atual, "chroma_data")

    try:
        with open(caminho_json, 'r', encoding='utf-8') as f:
            dados = json.load(f)
    except FileNotFoundError:
        print("Erro: O arquivo 'poliscrap_limpo.json' não foi encontrado.")
        return

    # 2. A "Guilhotina" Semântica
    # Tenta cortar o texto nos pontos finais, para não quebrar frases no meio.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120, # Margem de segurança de 120 caracteres para manter o contexto
        separators=["\n\n", "\n", ".", " ", ""]
    )

    documentos = []
    metadados = []
    ids = []

    # O TRUQUE CONTRA O BLOATING: Um Set (conjunto) para guardar blocos únicos
    chunks_vistos = set()
    chunk_id_global = 0

    print("-> Fatiando textos e removendo duplicações...")
    
    for pagina in dados:
        chunks = text_splitter.split_text(pagina["texto_limpo"])
        
        for chunk in chunks:
            # Controle de Qualidade: Se o bloco já existe (ex: renderização dupla no HTML), ignore!
            if chunk in chunks_vistos:
                continue
                
            chunks_vistos.add(chunk)
            documentos.append(chunk)
            
            # Os metadados são essenciais para o Chatbot citar a fonte depois
            metadados.append({
                "url": pagina["url"],
                "titulo": pagina["titulo"]
            })
            ids.append(f"doc_{chunk_id_global}")
            chunk_id_global += 1

    print(f"-> Total de chunks únicos e limpos gerados: {len(documentos)}")

    # 3. Inicializar o ChromaDB e o Modelo de Embedding
    print("-> Baixando o modelo de linguagem e conectando ao banco...")
    cliente = chromadb.PersistentClient(path=caminho_db)
    
    # Usando o modelo multilíngue otimizado para a nossa arquitetura
    funcao_embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    # Cria a "tabela" dentro do banco de dados
    colecao = cliente.get_or_create_collection(
        name="poli_chatbot",
        embedding_function=funcao_embedding
    )

    # 4. A Vetorização (O processo mais pesado)
    print("-> Gerando embeddings e populando o banco... (Isso pode levar alguns minutos na primeira vez)")
    colecao.add(
        documents=documentos,
        metadatas=metadados,
        ids=ids
    )
    
    print("\n[SUCESSO ABSOLUTO]")
    print(f"O seu cérebro vetorial está pronto e salvo em: {os.path.abspath(caminho_db)}")

if __name__ == "__main__":
    construir_banco()