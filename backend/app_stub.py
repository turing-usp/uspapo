"""Backend falso do USPapo para testes locais de UI.

Mesmo protocolo do app.py real (JSON legado e SSE) e literalmente o mesmo
motor, mas SEM Pinecone: as ferramentas vêm de uspapo/ferramentas/simuladas.py,
que devolve documentos canned. A LLM é de verdade: vem da mesma cadeia
LLM_PROVIDERS do .env — para dar para testar o streaming, os blocos de
"Pensando" e o de "Usando ferramenta" com tokens reais.

    python backend/app_stub.py

Variáveis de ambiente:
    LLM_PROVIDERS  obrigatória (mesma do app.py; veja o .env.example)
    PORT           porta do servidor (padrão 5000)
    STUB_DELAY     latência simulada da busca, em segundos (padrão 1.2)
    RATE_LIMIT_*   limites por janela; MAX_TOKENS_CONTEXTO, RESERVA_FERRAMENTAS

Não precisa de PINECONE_API_KEY.
"""

from uspapo.ferramentas import simuladas
from uspapo.web import criar_app, rodar

app = criar_app(simuladas.registro, rotulo_indice="STUB (documentos falsos)")

if __name__ == "__main__":
    print("-> Backend STUB do USPapo (LLM real, busca falsa)")
    rodar(app)
