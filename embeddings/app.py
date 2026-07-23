import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from pinecone import Pinecone
from groq import Groq

# ─────────────────────────────────────────────
# 1. Configurações Iniciais e Chaves (Segurança)
# ─────────────────────────────────────────────
load_dotenv()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not PINECONE_API_KEY or not GROQ_API_KEY:
    raise RuntimeError("As chaves PINECONE_API_KEY e/gsk GROQ_API_KEY não foram encontradas no arquivo .env!")

app = Flask(__name__)

# Liberamos o acesso tanto para o domínio oficial do Turing quanto para os seus testes locais!
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://turingusp.com",       # Para o site público do seu amigo
            "https://www.turingusp.com",   # Garantia caso alguém digite www
            "http://localhost:3000",       # Para você continuar testando na sua máquina
            "uspapo.vercel.app"            # Site teste
        ]
    }
})

# ─────────────────────────────────────────────
# Inicialização ÚNICA (Conecta à nuvem ao subir o servidor)
# ─────────────────────────────────────────────
print("-> Iniciando motor Cloud-Native...")
print("-> Conectando ao Pinecone e à Groq...")

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("uspapo-embeddings")
cliente_llm = Groq(api_key=GROQ_API_KEY)

print("-> Servidor USPapo ativado e super leve! 🚀")

# ─────────────────────────────────────────────
# 2. Funções do RAG (Agora rodando 100% na Nuvem)
# ─────────────────────────────────────────────
def buscar_contexto(pergunta: str, limite: int = 3):
    """Transforma a pergunta em vetor via API e busca no Pinecone."""
    texto_busca = f"query: {pergunta}"
    
    # 1. Pede pro Pinecone transformar a pergunta em vetor
    embed_result = pc.inference.embed(
        model="multilingual-e5-large",
        inputs=[texto_busca],
        parameters={"input_type": "query"}
    )
    vetor_pergunta = embed_result[0].values

    # 2. Faz a busca matemática
    resultados = index.query(
        namespace="uspapo",
        vector=vetor_pergunta,
        top_k=limite,
        include_metadata=True
    )

    textos_encontrados = []
    metadados_encontrados = []
    
    for match in resultados.matches:
        meta = match.metadata
        textos_encontrados.append(meta.get("text", ""))
        metadados_encontrados.append(meta)

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
    """Envia o prompt estruturado para o motor da Groq."""
    resposta = cliente_llm.chat.completions.create(
        model="openai/gpt-oss-120b", # Modelo mais recente da Groq
        messages=[
            {"role": "user", "content": prompt_montado}
        ],
        temperature=0.1
    )
    return resposta.choices[0].message.content

# ─────────────────────────────────────────────
# 3. Endpoint da API (A ponte com o Next.js)
# ─────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    dados = request.get_json(silent=True)

    if not dados or "pergunta" not in dados:
        return jsonify({"erro": "Campo 'pergunta' é obrigatório"}), 400

    pergunta = dados["pergunta"].strip()

    if not pergunta:
        return jsonify({"erro": "Pergunta vazia"}), 400

    try:
        # Pipeline do RAG acionado
        textos, metadados = buscar_contexto(pergunta, limite=3)
        prompt = montar_prompt(pergunta, textos)
        resposta_ia = gerar_resposta(prompt)

        # Extrai fontes únicas consultadas
        urls_unicas = sorted(set(
            meta.get("url", "URL Desconhecida") for meta in metadados
        ))

        return jsonify({
            "resposta": resposta_ia,
            "fontes": urls_unicas
        })

    except Exception as e:
        print(f"Erro ao processar pergunta: {e}")
        return jsonify({"erro": "Erro interno ao processar a pergunta no servidor."}), 500

if __name__ == "__main__":
    # Render atribui a porta via variável de ambiente 'PORT'
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)