"""Backend do USPapo — RAG sobre documentos oficiais da USP.

Fala com qualquer API compatível com o protocolo OpenAI (Groq, OpenRouter,
DeepSeek, OpenAI, Together, Ollama local...) através de uma cadeia de
provedores lida de LLM_PROVIDERS no .env: se o primário falhar, cai
automaticamente para o próximo. Veja o .env.example na raiz.

A busca vetorial no Pinecone é uma toolcall que o modelo aciona
quando a pergunta exige um fato sobre a USP. As outras vão buscar o dado ao vivo
na fonte oficial: o cardápio dos bandejões no RUCard, e a disciplina, as turmas
e a grade curricular no JupiterWeb. As exceções são a avaliação de professor,
que lê o USP Avalia (site de alunos, não da USP, marcado como opinião), e a
Wikipedia, usada apenas para contexto enciclopédico geral.

    POST /chat  {"pergunta": "..."}                  -> {"resposta", "fontes"}
    POST /chat  {"pergunta": "...", "stream": true}  -> text/event-stream
    GET  /health

O corpo do /chat aceita ainda "historico": [{"pergunta", "resposta"}, ...] com os
turnos anteriores da conversa. O que não couber no orçamento de tokens é
descartado, do turno mais antigo para o mais novo.

O /chat exige login: o site manda o access token do Supabase no Authorization e
o backend confere a assinatura pelo JWKS do projeto. Sem token válido é 401,
sem uspapo_role e fora da whitelist de emails é 403, e cada conta tem um limite
de perguntas por janela de tempo que devolve 429 ao estourar.

No modo stream, cada evento é uma linha `data: {json}` com um campo "tipo":
provedor, pensando, ferramenta, texto, fontes, erro, fim.

Deste arquivo só é dele a escolha das ferramentas; todo o resto do backend mora
no pacote uspapo/ e é o mesmo que o app_stub.py usa.

    python backend/app.py                  # desenvolvimento
    gunicorn --chdir backend app:app       # produção (Render)
"""

from uspapo.ferramentas import bandejao, busca, circulares, curriculo, disciplinas, salas, uspavalia, wikipedia
from uspapo.web import criar_app, rodar

# Cardápio, disciplinas, grade curricular, avaliações, salas, circulares e Wikipedia
# são iguais nos dois backends: vêm de suas fontes ao vivo, não do Pinecone, então
# as mesmas ferramentas entram nos dois registros. Antes do criar_app: é dele que
# sai o orçamento de tokens, calculado sobre os schemas já registrados.
bandejao.registrar(busca.registro)
disciplinas.registrar(busca.registro)
curriculo.registrar(busca.registro)
uspavalia.registrar(busca.registro)
salas.registrar(busca.registro)
circulares.registrar(busca.registro)
wikipedia.registrar(busca.registro)

# `app` no escopo do módulo é o que o gunicorn importa: não renomeie.
app = criar_app(busca.registro, rotulo_indice=busca.PINECONE_INDEX)

if __name__ == "__main__":
    print("-> Servidor USPapo ativado com Pinecone!")
    rodar(app)
