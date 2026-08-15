"""A cadeia de provedores de LLM.

Qualquer API compatível com o protocolo OpenAI serve (Groq, OpenRouter,
DeepSeek, OpenAI, Together, Ollama local...). A ordem de LLM_PROVIDERS é a
ordem de prioridade: se o primário falhar, a pergunta cai para o próximo.
"""

import json
import os
from dataclasses import dataclass

from openai import OpenAI

from uspapo import config


@dataclass(frozen=True)
class Provedor:
    """Um provedor da cadeia, já com o cliente pronto."""

    nome: str
    cfg: dict
    cliente: OpenAI

    def parametros(self, mensagens: list[dict], tools: list[dict]) -> dict:
        """Monta o kwargs do chat.completions.create deste provedor."""
        parametros = {
            "model": self.cfg["model"],
            "messages": mensagens,
            "tools": tools,
            "temperature": float(
                self.cfg.get("temperature", config.TEMPERATURA_PADRAO)
            ),
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if self.cfg.get("max_tokens"):
            parametros["max_tokens"] = int(self.cfg["max_tokens"])
        if self.cfg.get("extra_body"):
            parametros["extra_body"] = self.cfg["extra_body"]

        return parametros

    def teto_contexto(self) -> int:
        """Quanto contexto cabe numa requisição para ESTE provedor.

        O padrão do .env é calibrado para o modelo local, que aceita o que a
        gente mandar. Uma API cobrada por token costuma ter uma janela por
        minuto bem menor e recusa a requisição inteira quando ela sozinha passa
        do limite: não adianta ter orçamento de 16k se o provedor corta em 6k.
        """
        return int(self.cfg.get("max_tokens_contexto") or config.MAX_TOKENS_CONTEXTO)


def carregar_provedores() -> list[Provedor]:
    """Lê LLM_PROVIDERS (JSON) e instancia um cliente OpenAI por provedor.

    A ordem da lista é a ordem de prioridade: o primeiro é o primário, o
    segundo é secundário...
    """
    bruto = (os.getenv("LLM_PROVIDERS") or "").strip()
    if not bruto:
        raise RuntimeError(
            "LLM_PROVIDERS não foi definida no .env! Copie o .env.example da raiz."
        )

    try:
        entradas = json.loads(bruto)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            f"LLM_PROVIDERS não é um JSON válido ({erro}). "
            "Ele precisa ser uma lista JSON em UMA linha só! Veja o .env.example."
        ) from erro

    if not isinstance(entradas, list) or not entradas:
        raise RuntimeError("LLM_PROVIDERS precisa ser uma lista JSON não vazia.")

    provedores: list[Provedor] = []
    ocorrencias_por_nome: dict[str, int] = {}

    for posicao, cfg in enumerate(entradas):
        if not isinstance(cfg, dict):
            raise RuntimeError(f"LLM_PROVIDERS[{posicao}] não é um objeto JSON.")

        nome_configurado = str(
            cfg.get("nome") or f"provedor-{posicao + 1}"
        ).strip()
        ocorrencia = ocorrencias_por_nome.get(nome_configurado, 0) + 1
        ocorrencias_por_nome[nome_configurado] = ocorrencia
        nome = (
            nome_configurado
            if ocorrencia == 1
            else f"{nome_configurado}-{ocorrencia}"
        )
        if ocorrencia > 1:
            print(
                f"   [!] nome de provedor repetido '{nome_configurado}'; "
                f"esta instância será identificada como '{nome}'."
            )

        faltando = [campo for campo in ("base_url", "model") if not cfg.get(campo)]
        if faltando:
            raise RuntimeError(
                f"LLM_PROVIDERS[{posicao}] ('{nome}'): faltam os campos {faltando}."
            )

        # A chave vem inteira aqui dentro: nada de apontar para outra variável.
        chave = str(cfg.get("api_key") or "").strip()
        if not chave:
            print(f"   [!] provedor '{nome}' ignorado: 'api_key' vazia no LLM_PROVIDERS.")
            continue

        # max_retries=0 de propósito: quem repete é o conversa.py, que sabe
        # respeitar o Retry-After do provedor, encolher o contexto quando a
        # recusa foi por tamanho e desistir para o próximo da cadeia. O retry
        # do SDK não sabe nada disso e só atrasaria a queda para o próximo.
        cliente = OpenAI(
            api_key=chave,
            base_url=cfg["base_url"],
            timeout=float(cfg.get("timeout", config.TIMEOUT_PADRAO)),
            max_retries=0,
        )
        provedores.append(Provedor(
            nome=nome,
            cfg={
                **cfg,
                "nome": nome,
                "nome_configurado": nome_configurado,
            },
            cliente=cliente,
        ))

    if not provedores:
        raise RuntimeError(
            "Nenhum provedor de LLM utilizável em LLM_PROVIDERS! "
            "Todos estão com a 'api_key' vazia."
        )

    return provedores
