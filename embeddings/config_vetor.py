"""Ajustes da indexação vetorial, lidos do .env uma única vez.

Antes disto tudo era literal solto no meio do `build_vector.py`: o `DRY_RUN`
era uma constante na linha 11 (mudar exigia commit, e ele já foi virado de True
para False num commit de emergência), o nome do índice era string crua, o
namespace `"uspapo"` aparecia repetido em cada chamada, e não havia número
nenhum limitando o quanto uma execução podia escrever na nuvem.

Esse último ponto é o que importa. O incidente que derrubou o índice
`uspapo-embeddings` não foi um erro de lógica isolado: foi um erro a montante
(um site com 400 mil páginas de spam) que o pipeline aceitou sem questionar,
porque não existia nada perguntando "isto aqui é grande demais para ser
rotina?". Os três orçamentos abaixo existem para responder essa pergunta antes
de qualquer requisição sair da máquina.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _inteiro(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


def _decimal(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


def _booleano(nome: str, padrao: bool = False) -> bool:
    bruto = os.getenv(nome)
    if bruto is None:
        return padrao
    return bruto.strip().lower() in {"1", "true", "sim", "yes", "on"}


# ─────────────────────────────────────────────
# Pinecone
# ─────────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Os mesmos nomes que o backend lê em ferramentas/busca.py. Manter os dois lados
# na mesma variável é o que permite construir num namespace novo e virar a chave
# depois, sem tocar em código.
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "uspapo-rag")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "uspapo")

# Não escreve nada na nuvem; só calcula o plano e salva o ledger local.
DRY_RUN = _booleano("DRY_RUN", False)

# ─────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────
# Alvo e teto em caracteres. O e5 corta em 512 tokens (~1.800 chars em pt-BR),
# então 1100 tem folga confortável e nada é truncado em silêncio.
CHUNK_ALVO = _inteiro("CHUNK_ALVO", 800)
CHUNK_MAX = _inteiro("CHUNK_MAX", 1100)

# Overlap usado APENAS ao partir um bloco maior que o teto, nunca entre chunks
# formados por parágrafos. O motivo está no docstring do chunking.py: overlap
# entre chunks faria o rechunking ancorado reaproveitar texto desatualizado sem
# que hash nenhum acusasse. Fronteira de parágrafo já é fronteira semântica.
CHUNK_OVERLAP = _inteiro("CHUNK_OVERLAP", 150)

# Chunk menor que isto não vira vetor: ou é fundido no anterior, ou é descartado
# se não houver em que fundir. O filtro antigo era por PÁGINA (>50 chars), e por
# isso um chunk de 1 caractere chegou a ser embarcado.
CHUNK_MIN = _inteiro("CHUNK_MIN", 200)

# ─────────────────────────────────────────────
# Lotes e repetição
# ─────────────────────────────────────────────
# O upsert_records da inferência integrada aceita no máximo 96 registros.
LOTE_UPSERT = _inteiro("LOTE_UPSERT", 90)
LOTE_DELETE = _inteiro("LOTE_DELETE", 1000)
PAUSA_ENTRE_LOTES = _decimal("PAUSA_ENTRE_LOTES", 1.5)

# Substitui o `while not sucesso:` sem teto, que diante de um 429 persistente
# rodava até o GitHub Actions matar o job (6 horas).
MAX_TENTATIVAS = _inteiro("MAX_TENTATIVAS", 6)
BACKOFF_BASE = _decimal("BACKOFF_BASE", 5.0)
BACKOFF_TETO = _decimal("BACKOFF_TETO", 120.0)

# ─────────────────────────────────────────────
# Orçamento de escrita — o disjuntor
# ─────────────────────────────────────────────
# Três travas independentes, conferidas ANTES de a primeira requisição sair.
# Qualquer uma que estoure aborta a execução inteira sem escrever nada.
#
# As duas primeiras são tetos absolutos, para o caso de o ledger estar vazio ou
# pequeno (numa base de 100 vetores, 25% seriam 25, baixo demais para ser útil).
ORCAMENTO_UPSERTS = _inteiro("ORCAMENTO_UPSERTS", 2000)
ORCAMENTO_DELETES = _inteiro("ORCAMENTO_DELETES", 3000)

# A terceira é proporcional, e é a que teria barrado o IRI: mexer em mais de um
# quarto do banco de uma vez só não é manutenção de rotina, é migração. Migração
# é legítima, mas passa por PERMITIR_MIGRACAO_TOTAL=1 explícito na mão de alguém
# — nunca pelo cron das 5h da manhã.
LIMIAR_ABORTO_PCT = _decimal("LIMIAR_ABORTO_PCT", 0.25)
PERMITIR_MIGRACAO_TOTAL = _booleano("PERMITIR_MIGRACAO_TOTAL", False)

# ─────────────────────────────────────────────
# Caminhos
# ─────────────────────────────────────────────
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
RAIZ_PROJETO = os.path.abspath(os.path.join(DIRETORIO_ATUAL, ".."))

PASTA_PROCESSED = os.path.join(RAIZ_PROJETO, "data", "processed")
PASTA_INDEX = os.path.join(RAIZ_PROJETO, "data", "index")
PASTA_RELATORIOS = os.path.join(RAIZ_PROJETO, "data", "reports")

ARQUIVO_LEDGER = os.path.join(PASTA_INDEX, "ledger_avancado.json")

# Ids agendados para deleção mas ainda não confirmados. Existe para que uma
# queda entre "salvei o ledger" e "apaguei os órfãos" seja recuperável na
# execução seguinte, em vez de virar vetor fantasma pagando armazenamento.
ARQUIVO_PENDENCIAS = os.path.join(PASTA_INDEX, "pendencias.json")


def exigir_api_key() -> str:
    """Devolve a chave, ou explica o que fazer. Só chame fora do DRY_RUN."""
    if not PINECONE_API_KEY:
        raise RuntimeError(
            "PINECONE_API_KEY não encontrada. Preencha o .env (veja o "
            ".env.example) ou rode com DRY_RUN=1 para trabalhar offline."
        )
    return PINECONE_API_KEY
