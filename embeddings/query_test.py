import os
from dotenv import load_dotenv
from pinecone import Pinecone
from groq import Groq

# ─────────────────────────────────────────────
# 1. Configurações Iniciais
# ─────────────────────────────────────────────
load_dotenv()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not PINECONE_API_KEY or not GROQ_API_KEY:
    raise RuntimeError("Chaves da API faltando no arquivo .env!")

print("-> Conectando aos serviços na nuvem (Pinecone & Groq)...")
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("uspapo-embeddings")
groq_client = Groq(api_key=GROQ_API_KEY)


def buscar_contexto_no_pinecone(pergunta: str, top_k: int = 3):
    """Busca os textos na nuvem e retorna os blocos crus e as fontes."""
    texto_busca = f"query: {pergunta}"
    
    embed_result = pc.inference.embed(
        model="multilingual-e5-large",
        inputs=[texto_busca],
        parameters={"input_type": "query"}
    )
    
    vetor_pergunta = embed_result[0].values
    
    resultados = index.query(
        namespace="uspapo",
        vector=vetor_pergunta,
        top_k=top_k,
        include_metadata=True
    )
    
    textos_recuperados = []
    fontes = []
    
    for match in resultados.matches:
        metadado = match.metadata
        textos_recuperados.append(metadado.get("text", ""))
        # Formata a fonte para exibição
        fontes.append(f"- {metadado.get('titulo', 'Sem título')} ({metadado.get('url', 'Sem URL')})")
        
    return textos_recuperados, fontes


def montar_prompt(pergunta: str, textos_contexto: list) -> str:
    contexto_unido = "\n\n---\n\n".join(textos_contexto)
    return f"""Você é o chatbot veterano da USP. Responda à pergunta do aluno de forma clara, amigável e direta, usando APENAS as informações do contexto fornecido abaixo.
Se a informação não estiver no contexto, diga que não tem certeza e recomende procurar a secretaria.

Contexto da Base de Dados:
{contexto_unido}

Pergunta do Aluno:
{pergunta}
"""


# ─────────────────────────────────────────────
# 2. O Loop Interativo do Terminal
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🔬 LABORATÓRIO DE TESTES RAG (PINECONE + GROQ)")
    print("="*60)
    
    while True:
        print("\n" + "-"*60)
        pergunta_usuario = input("👤 VOCÊ: ")
        
        if pergunta_usuario.lower().strip() in ['sair', 'exit', 'quit', 'fechar']:
            print("\nEncerrando o laboratório. Até logo!")
            break
            
        if not pergunta_usuario.strip():
            continue
            
        # ETAPA 1: O Retriever (Pinecone)
        print("\n🔍 PESQUISANDO NO PINECONE...")
        textos, fontes = buscar_contexto_no_pinecone(pergunta_usuario)
        
        print("\n[BLOCOS DE TEXTO RECUPERADOS (CRUS)]")
        for i, texto in enumerate(textos, 1):
            # Imprime o texto gigante inteiro
            print(f"  Bloco {i}: {texto}\n")
            
        # ETAPA 2: O Generator (Groq)
        print("\n🧠 PROCESSANDO RESPOSTA NO GROQ...")
        prompt = montar_prompt(pergunta_usuario, textos)
        
        resposta = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        
        print("\n🤖 USPAPO:")
        print(resposta.choices[0].message.content)
        
        print("\n📚 FONTES:")
        # Remove URLs duplicadas usando set()
        for fonte in set(fontes):
            print(fonte)