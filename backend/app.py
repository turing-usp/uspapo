"""Backend do USPapo — RAG sobre documentos oficiais da USP.

Fala com qualquer API compatível com o protocolo OpenAI (Groq, OpenRouter,
DeepSeek, OpenAI, Together, Ollama local...) através de uma cadeia de
provedores lida de LLM_PROVIDERS no .env: se o primário falhar, cai
automaticamente para o próximo. Veja o .env.example na raiz.

A busca vetorial no Pinecone é uma toolcall que o modelo aciona
quando a pergunta exige um fato sobre a USP.

    POST /chat  {"pergunta": "..."}                  -> {"resposta", "fontes"}
    POST /chat  {"pergunta": "...", "stream": true}  -> text/event-stream
    GET  /health

O corpo do /chat aceita ainda "historico": [{"pergunta", "resposta"}, ...] com os
turnos anteriores da conversa (o frontend guarda tudo no localStorage). O que não
couber no orçamento de tokens é descartado, do turno mais antigo para o mais novo.

Cada cliente identifica seu aparelho no header X-Device-Id e tem um limite de
perguntas por janela de tempo; estourar devolve 429.

No modo stream, cada evento é uma linha `data: {json}` com um campo "tipo":
provedor, pensando, ferramenta, texto, fontes, erro, fim.

Deste arquivo só é dele a escolha das ferramentas; todo o resto do backend mora
no pacote uspapo/ e é o mesmo que o app_stub.py usa.

    python backend/app.py                  # desenvolvimento
    gunicorn --chdir backend app:app       # produção (Render)
"""

from uspapo.ferramentas import busca
from uspapo.web import criar_app, rodar

# `app` no escopo do módulo é o que o gunicorn importa: não renomeie.
app = criar_app(busca.registro, rotulo_indice=busca.PINECONE_INDEX)

if __name__ == "__main__":
    print("-> Servidor USPapo ativado e super leve! 🚀")
    rodar(app)
