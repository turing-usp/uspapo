"""Ajustes do backend, lidos do .env uma única vez.

Este módulo é quem chama o load_dotenv(), então TODO módulo que for ler
os.getenv precisa importar este aqui antes — senão lê o ambiente sem o .env.

Aqui mora só o que mais de um módulo usa. O que é de um módulo só fica com
ele: as chaves do Pinecone em ferramentas/busca.py, o STUB_DELAY em
ferramentas/simuladas.py.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Provedores de LLM
# ─────────────────────────────────────────────
TEMPERATURA_PADRAO = 0.1
TIMEOUT_PADRAO = 60

# Quantas rodadas de ferramenta uma pergunta pode ter. 0 = sem limite, que é o
# padrão: quem modera o uso de ferramenta é o prompt de sistema, não um teto.
# Ligar isto (um número > 0) é o freio de emergência para um modelo que entre em
# loop de tool call — a rodada excedente levanta e a pergunta cai para o próximo
# provedor da cadeia.
TETO_RODADAS_FERRAMENTA = int(os.getenv("TETO_RODADAS_FERRAMENTA", "0"))

# ─────────────────────────────────────────────
# Busca
# ─────────────────────────────────────────────
# Valem para qualquer ferramenta de busca (a real e a simulada), para as duas
# terem exatamente o mesmo schema.
TOP_K_PADRAO = 3
TOP_K_MAX = 5

# ─────────────────────────────────────────────
# Portaria: limite de uso e orçamento de contexto
# ─────────────────────────────────────────────
# Duas defesas para o mesmo problema, o custo por pergunta: o rate limit cuida
# de quantas perguntas cada um faz, o orçamento cuida do tamanho de cada uma.

# Quantas perguntas cada aparelho pode fazer por janela de tempo. As janelas
# valem todas ao mesmo tempo: a de minuto segura a rajada, a de dia segura o uso
# crônico. Basta pôr 0 para desligar uma delas.
LIMITES_TAXA = [
    ("minuto",     60,    int(os.getenv("RATE_LIMIT_MINUTO", "8"))),
    ("10 minutos", 600,   int(os.getenv("RATE_LIMIT_10MIN",  "30"))),
    ("hora",       3600,  int(os.getenv("RATE_LIMIT_HORA",   "100"))),
    ("dia",        86400, int(os.getenv("RATE_LIMIT_DIA",    "400"))),
]

# Teto do que vai para o modelo, não importa o tamanho da conversa no frontend.
MAX_TOKENS_CONTEXTO = int(os.getenv("MAX_TOKENS_CONTEXTO", "16000"))
# Espaço guardado para o que as ferramentas ainda vão devolver nesta pergunta.
RESERVA_FERRAMENTAS = int(os.getenv("RESERVA_FERRAMENTAS", "4000"))
# Corte grosso antes de qualquer contagem, para não estimar tokens à toa.
MAX_MENSAGENS_HISTORICO = 40
CHARS_POR_TOKEN = 3.5

# ─────────────────────────────────────────────
# Servidor
# ─────────────────────────────────────────────
# Liberamos o acesso tanto para o domínio oficial do Turing quanto para os
# testes locais!
ORIGENS_CORS = [
    "https://turingusp.com",       # Para o site público
    "https://www.turingusp.com",   # Garantia caso alguém digite www
    "http://localhost:3000",       # Para continuar testando na sua máquina
    "https://uspapo.turingusp.com",
    "https://www.uspapo.turingusp.com",
]

# X-Device-Id é header customizado: sem ele liberado aqui, o navegador barra a
# requisição já no preflight OPTIONS.
HEADERS_CORS = ["Content-Type", "X-Device-Id"]

# O Render atribui a porta via variável de ambiente.
PORTA = int(os.getenv("PORT", "5000"))
