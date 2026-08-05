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

# Quantas perguntas cada um pode fazer por janela de tempo. As janelas valem
# todas ao mesmo tempo: a de minuto segura a rajada, a de dia segura o uso
# crônico. Basta pôr 0 para desligar uma delas.
#
# São duas escadas. Quem está logado é identificado pela conta (um token que o
# backend confere), então a cota vale para a pessoa e acompanha ela entre
# celular e computador; quem não está é identificado pelo aparelho, um id que o
# próprio navegador gera e qualquer um pode trocar. Por isso o anônimo é mais
# apertado: não é castigo, é o que dá para sustentar quando a chave é
# descartável.
LIMITES_TAXA_ANONIMO = [
    ("minuto",     60,    int(os.getenv("RATE_LIMIT_MINUTO", "8"))),
    ("10 minutos", 600,   int(os.getenv("RATE_LIMIT_10MIN",  "30"))),
    ("hora",       3600,  int(os.getenv("RATE_LIMIT_HORA",   "100"))),
    ("dia",        86400, int(os.getenv("RATE_LIMIT_DIA",    "400"))),
]

LIMITES_TAXA_CONTA = [
    ("minuto",     60,    int(os.getenv("RATE_LIMIT_CONTA_MINUTO", "15"))),
    ("10 minutos", 600,   int(os.getenv("RATE_LIMIT_CONTA_10MIN",  "80"))),
    ("hora",       3600,  int(os.getenv("RATE_LIMIT_CONTA_HORA",   "300"))),
    ("dia",        86400, int(os.getenv("RATE_LIMIT_CONTA_DIA",    "1200"))),
]

# Teto padrão do que vai para o modelo, não importa o tamanho da conversa no
# frontend. Cada provedor pode ter um teto menor (Provedor.teto_contexto).
MAX_TOKENS_CONTEXTO = int(os.getenv("MAX_TOKENS_CONTEXTO", "16000"))
# Espaço guardado para o que as ferramentas ainda vão devolver nesta pergunta.
# É o quanto elas PRECISAM, que depende das ferramentas e não do modelo; o
# quanto cabe é outra conta, e quem faz as duas é Orcamento.reserva_para().
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

# X-Device-Id e Authorization são headers customizados: sem eles liberados
# aqui, o navegador barra a requisição já no preflight OPTIONS, e aí o login
# não chegaria nem a ser conferido.
HEADERS_CORS = ["Content-Type", "X-Device-Id", "Authorization"]

# O Render atribui a porta via variável de ambiente.
PORTA = int(os.getenv("PORT", "5000"))
