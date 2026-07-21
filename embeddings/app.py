import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
from flask import Flask, request, jsonify
from flask_cors import CORS

# ─────────────────────────────────────────────
# 1. Configurações Iniciais
# ─────────────────────────────────────────────
CAMINHO_DB = "chroma_data"
NOME_COLECAO = "poli_chatbot"
NOME_MODELO_EMBEDDING = "intfloat/multilingual-e5-base"

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # em produção, troque "*" pela URL da Vercel

# Conecta ao servidor local do Ollama
cliente_llm = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

# ─────────────────────────────────────────────
# Inicialização ÚNICA (roda uma vez, ao subir o servidor)
# Evita recarregar o ChromaDB e o modelo de embedding a cada pergunta.
# ─────────────────────────────────────────────
print("-> Conectando ao ChromaDB e carregando modelo de embedding...")
_cliente_chroma = chromadb.PersistentClient(path=CAMINHO_DB)
_funcao_embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=NOME_MODELO_EMBEDDING
)
_colecao = _cliente_chroma.get_collection(
    name=NOME_COLECAO, embedding_function=_funcao_embedding
)
print("-> Pronto.")


# ─────────────────────────────────────────────
# 2. Funções do RAG (praticamente iguais às suas)
# ─────────────────────────────────────────────
def buscar_contexto(pergunta: str, limite: int = 3):
    """Transforma a pergunta em vetor e busca as gavetas mais próximas."""
    # IMPORTANTE: o modelo E5 exige o prefixo "query: " para perguntas
    pergunta_formatada = f"query: {pergunta}"

    resultados = _colecao.query(
        query_texts=[pergunta_formatada],
        n_results=limite
    )

    textos_encontrados = resultados["documents"][0]
    metadados_encontrados = resultados["metadatas"][0]

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
    resposta = cliente_llm.chat.completions.create(
        model="qwen2.5:7b",
        messages=[
            {"role": "user", "content": prompt_montado}
        ],
        temperature=0.1
    )
    return resposta.choices[0].message.content


# ─────────────────────────────────────────────
# 3. Endpoint da API
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
        textos, metadados = buscar_contexto(pergunta, limite=3)
        prompt = montar_prompt(pergunta, textos)
        resposta_ia = gerar_resposta(prompt)

        # Fontes consultadas, sem duplicar URLs repetidas
        urls_unicas = sorted(set(
            meta.get("url", "URL Desconhecida") for meta in metadados
        ))

        return jsonify({
            "resposta": resposta_ia,
            "fontes": urls_unicas
        })

    except Exception as e:
        print(f"Erro ao processar pergunta: {e}")
        return jsonify({"erro": "Erro ao processar a pergunta"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
