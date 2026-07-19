import json
import os
import chromadb
from chromadb.utils import embedding_functions

def testar_sistema_busca():
    # 1. Configurar caminhos absolutos locais
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_db = os.path.join(diretorio_atual, "chroma_data")
    
    # 2. Inicializar a mesma função de embedding usada na criação do banco
    funcao_embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="intfloat/multilingual-e5-base"
    )
    
    # 3. Conectar ao ChromaDB e carregar a coleção existente
    cliente = chromadb.PersistentClient(path=caminho_db)
    
    try:
        colecao = cliente.get_collection(
            name="poli_chatbot", 
            embedding_function=funcao_embedding
        )
    except Exception as e:
        print("\n[ERRO AO CARREGAR COLEÇÃO]")
        print("Verifique se o nome 'poli_chatbot' está idêntico ao build_vector.py")
        print(f"Detalhes do erro: {e}")
        return

    print("\n=========================================")
    print("=== SISTEMA DE BUSCA SEMÂNTICA PRONTO ===")
    print("=========================================")
    print("Digite sua dúvida sobre a Poli USP para testar o banco.")
    print("Para encerrar o programa, digite: sair")
    
    while True:
        pergunta = input("\nSua pergunta: ")
        
        if pergunta.strip().lower() == 'sair':
            print("\nEncerrando testes de embedding. Próximo passo: Pipeline RAG!")
            break
            
        if not pergunta.strip():
            continue
            
        # 4. Executar a consulta vetorial no banco
        # O ChromaDB vai converter a pergunta em vetor e calcular a distância
        resultados = colecao.query(
            query_texts=[pergunta],
            n_results=2, # Traz os 2 blocos de texto matematicamente mais próximos
            include=["documents", "metadatas", "distances"]
        )
        
        # 5. Exibir os resultados encontrados e as pontuações de distância
        print("\n" + "="*30)
        print("--- BLOCOS VETORIAIS RECUPERADOS ---")
        print("="*30)
        
        documentos = resultados.get("documents", [[]])[0]
        metadados = resultados.get("metadatas", [[]])[0]
        distancias = resultados.get("distances", [[]])[0]
        
        if not documentos:
            print("Nenhum bloco de texto relevante foi encontrado para esta consulta.")
            continue
            
        for i in range(len(documentos)):
            texto = documentos[i]
            meta = metadados[i]
            # No ChromaDB com essa métrica, quanto MENOR a distância, MAIS parecido é o texto
            score_distancia = distancias[i]
            
            print(f"\n[Resultado #{i+1}] | Distância Matemática: {score_distancia:.4f}")
            print(f"Título da Página: {meta['titulo']}")
            print(f"URL de Origem: {meta['url']}")
            print(f"Trecho do Bloco:\n{texto}")
            print("-" * 50)

if __name__ == "__main__":
    testar_sistema_busca()