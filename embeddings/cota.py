"""Medidor mensal de tokens de embedding, para não bater na cota do Pinecone.

O `multilingual-e5-large` no plano atual tem um teto de tokens de embedding POR
MÊS e POR ORGANIZAÇÃO. Estourá-lo devolve

    [429] You've reached the embedding token limit (5000000) for model
    multilingual-e5-large for the current month across your organization.

e esse 429 é diferente de todos os outros: ele não passa com backoff, porque não
é excesso de requisições por segundo — é a cota do mês inteiro, e ela só volta no
dia 1º. Tentar de novo seis vezes só atrasa a falha.

O disjuntor de `build_vector` (ORCAMENTO_UPSERTS, LIMIAR_ABORTO_PCT) protege o
BANCO contra uma escrita em massa acidental, mas ele é por execução: doze rondas
dentro do teto ainda somam doze vezes o custo. Este módulo é a trava que faltava,
e é acumulativa: guarda quantos tokens já foram gastos no mês corrente e recusa a
próxima remessa antes de mandá-la, em vez de descobrir no meio do upsert.

A contagem é uma estimativa: a tokenização real é do servidor, e não temos como
reproduzi-la aqui sem trazer o tokenizer do modelo. Por isso ela é deliberadamente
pessimista (ver `TOKENS_POR_CARACTERE`) e reserva uma fatia para as consultas dos
alunos, que consomem a MESMA cota a cada pergunta feita no site.

O arquivo fica em `data/index/cota_embeddings.json` e é versionado junto com o
ledger: sem isso, cada runner do GitHub Actions começaria o mês do zero.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from embeddings import config_vetor as cfg

ARQUIVO = os.path.join(cfg.PASTA_INDEX, "cota_embeddings.json")

# Teto do plano, em tokens por mês. Sobrescreva por variável de ambiente ao
# mudar de plano; o número não é descoberto pela API.
LIMITE_MENSAL = int(os.getenv("LIMITE_TOKENS_EMBEDDING_MES", "5000000"))

# Fatia reservada para `buscar_documentos`: toda pergunta de aluno vetoriza a
# consulta no mesmo modelo e sai da mesma cota. São ~20 tokens por pergunta, o
# que dá folga para ~25 mil perguntas no mês.
RESERVA_CONSULTAS = int(os.getenv("RESERVA_TOKENS_CONSULTA_MES", "500000"))

# Margem de segurança sobre o que sobra para a indexação. A estimativa de tokens
# é aproximada e o mês não pode terminar com o pipeline morto por 2%.
MARGEM = 0.10

# Caracteres por token, para estimar sem o tokenizer do modelo. Medido no corpus
# real do USPapo: os chunks têm mediana de ~896 caracteres. 3,0 é pessimista de
# propósito (o valor observado em português fica perto de 3,5): é melhor parar
# cedo demais do que descobrir a cota no meio de uma remessa.
TOKENS_POR_CARACTERE = 1 / 3.0


def orcamento_de_indexacao() -> int:
    """Quantos tokens a indexação pode gastar no mês, já com reserva e margem."""
    return max(0, int((LIMITE_MENSAL - RESERVA_CONSULTAS) * (1 - MARGEM)))


def estimar_tokens(textos) -> int:
    """Estimativa pessimista do custo de vetorizar estes textos."""
    return sum(int(len(str(texto)) * TOKENS_POR_CARACTERE) + 1 for texto in textos)


def _numero(valor: int) -> str:
    """Separador de milhar em português, sem tocar nas vírgulas da frase."""
    return f"{int(valor):,}".replace(",", ".")


def _mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def carregar() -> dict:
    """Estado do mês corrente; um mês novo zera o contador sozinho."""
    try:
        with open(ARQUIVO, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        dados = {}
    if not isinstance(dados, dict) or dados.get("mes") != _mes_atual():
        return {"mes": _mes_atual(), "tokens": 0, "lotes": 0}
    return {
        "mes": str(dados.get("mes")),
        "tokens": int(dados.get("tokens", 0)),
        "lotes": int(dados.get("lotes", 0)),
    }


def salvar(estado: dict) -> None:
    os.makedirs(cfg.PASTA_INDEX, exist_ok=True)
    temporario = ARQUIVO + ".tmp"
    with open(temporario, "w", encoding="utf-8") as arquivo:
        json.dump(estado, arquivo, indent=2, ensure_ascii=False)
    os.replace(temporario, ARQUIVO)


def disponivel() -> int:
    """Tokens de indexação que ainda cabem neste mês."""
    return max(0, orcamento_de_indexacao() - carregar()["tokens"])


def cabe(tokens: int) -> tuple[bool, str]:
    """Se esta remessa cabe no que resta do mês, e o porquê quando não cabe."""
    estado = carregar()
    orcamento = orcamento_de_indexacao()
    restante = max(0, orcamento - estado["tokens"])
    if tokens <= restante:
        return True, ""
    return False, (
        f"a remessa custaria ~{_numero(tokens)} tokens de embedding, mas só "
        f"restam ~{_numero(restante)} no orçamento de {_numero(orcamento)} deste "
        f"mês ({_numero(estado['tokens'])} já gastos em {estado['lotes']} "
        "lote(s) enviado(s)). Espere a virada do mês, reduza a ronda com "
        "--somente, ou aumente LIMITE_TOKENS_EMBEDDING_MES se o plano mudou."
    )


def registrar(tokens: int) -> dict:
    """Contabiliza uma remessa já enviada."""
    estado = carregar()
    estado["tokens"] += max(0, int(tokens))
    estado["lotes"] += 1
    salvar(estado)
    return estado


def resumo() -> str:
    estado = carregar()
    orcamento = orcamento_de_indexacao()
    pct = (100 * estado["tokens"] / orcamento) if orcamento else 100.0
    return (
        f"Cota de embeddings em {estado['mes']}: ~{_numero(estado['tokens'])} de "
        f"{_numero(orcamento)} tokens ({pct:.0f}%), em {estado['lotes']} lote(s)."
    )


__all__ = [
    "ARQUIVO",
    "LIMITE_MENSAL",
    "MARGEM",
    "RESERVA_CONSULTAS",
    "cabe",
    "carregar",
    "disponivel",
    "estimar_tokens",
    "orcamento_de_indexacao",
    "registrar",
    "resumo",
    "salvar",
]
