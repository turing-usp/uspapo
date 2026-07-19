import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI  

# 1. Configurações Iniciais
CAMINHO_DB = "chroma_data"
NOME_COLECAO = "poli_chatbot"
NOME_MODELO_EMBEDDING = "intfloat/multilingual-e5-base"

# Conecta ao servidor local do Ollama
cliente_llm = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

def buscar_contexto(pergunta: str, limite: int = 3):
    """Transforma a pergunta em vetor e busca as gavetas mais próximas."""
    # print("-> Conectando ao cérebro (ChromaDB)...") # Omitido para não poluir o chat contínuo
    cliente = chromadb.PersistentClient(path=CAMINHO_DB)
    funcao_embedding = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=NOME_MODELO_EMBEDDING)
    
    colecao = cliente.get_collection(name=NOME_COLECAO, embedding_function=funcao_embedding)
    
    # IMPORTANTE: O modelo E5 exige o prefixo "query: " para perguntas
    pergunta_formatada = f"query: {pergunta}"
    
    resultados = colecao.query(
        query_texts=[pergunta_formatada],
        n_results=limite
    )
    
    textos_encontrados = resultados['documents'][0]
    metadados_encontrados = resultados['metadatas'][0]
    
    return textos_encontrados, metadados_encontrados

def montar_prompt(pergunta: str, textos_contexto: list) -> str:
    """Junta a pergunta com os textos da USP para enviar para a IA."""
    contexto_unido = "\n\n---\n\n".join(textos_contexto)
    
    prompt_final = f"""Você é o assistente virtual oficial da USP.
Responda à pergunta do aluno baseando-se ESTRITAMENTE nos documentos abaixo.
Se a resposta não estiver nos documentos, diga "Desculpe, não encontrei essa informação nos meus registros." Não invente informações.

DOCUMENTOS DE CONSULTA:
{contexto_unido}

PERGUNTA DO ALUNO:
{pergunta}

RESPOSTA:"""

    return prompt_final

def gerar_resposta(prompt_montado: str) -> str:
    """Envia o prompt estruturado para o Qwen 7B rodando localmente."""
    print("-> 🧠 O Qwen 7B está formulando a resposta...")
    resposta = cliente_llm.chat.completions.create(
        model="qwen2.5:7b",  
        messages=[
            {"role": "user", "content": prompt_montado}
        ],
        temperature=0.1  
    )
    return resposta.choices[0].message.content

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🎓 BEM-VINDO AO ASSISTENTE VIRTUAL DA USP (RAG LOCAL)")
    print("="*50)
    
    # O loop infinito cria a experiência de chat
    while True:
        print("\n" + "-"*50)
        # 1. Pede a entrada do usuário no terminal
        pergunta_usuario = input("👤 VOCÊ: ")
        
        # Condição de saída elegante
        if pergunta_usuario.lower().strip() in ['sair', 'exit', 'quit', 'fechar']:
            print("\nEncerrando o assistente. Até logo!")
            break
            
        # Impede que o usuário dê Enter com o terminal vazio e quebre o script
        if not pergunta_usuario.strip():
            continue
            
        # 2. Busca no banco ChromaDB (Retriever)
        textos, metadados = buscar_contexto(pergunta_usuario, limite=3)
        
        # 3. Monta o Prompt
        prompt = montar_prompt(pergunta_usuario, textos)
        
        # 4. Envia para a IA gerar a resposta (Generator)
        resposta_ia = gerar_resposta(prompt)
        
        print("\n🤖 CHATBOT:")
        print(resposta_ia)
        
        print("\n[Fontes consultadas:]")
        # Usamos um set() para remover URLs duplicadas caso o banco traga 2 parágrafos da mesma página
        urls_unicas = set(meta.get('url', 'URL Desconhecida') for meta in metadados)
        for url in urls_unicas:
            print(f"- {url}")