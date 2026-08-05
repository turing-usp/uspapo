"""Rate limit: quantas perguntas cada um pode fazer por janela de tempo.

Há duas escadas, e a diferença entre elas é o quanto se sabe sobre quem
pergunta. A conta é provada (o token é conferido em contas.py), vale para a
pessoa e a segue entre aparelhos; o id de aparelho é gerado pelo próprio
navegador e trocá-lo custa um clique. Por isso quem tem conta pode mais: não é
prêmio, é o que dá para sustentar quando a identidade é verificável.

Limitação conhecida: `_batidas` é um dicionário deste processo. Com mais de um
worker do gunicorn cada worker conta por si, e reiniciar zera a contagem. Isso
já valia antes e continua valendo: para segurar uso acidental e abuso casual
é o suficiente; para um atacante dedicado nunca foi a defesa certa.
"""

import re
import threading
import time
from collections import deque

from flask import request

from uspapo import config
from uspapo.contas import usuario_do_pedido

_batidas: dict[str, deque[float]] = {}
_tranca = threading.Lock()

JANELA_MAXIMA = max(
    segundos
    for escada in (config.LIMITES_TAXA_ANONIMO, config.LIMITES_TAXA_CONTA)
    for _, segundos, _ in escada
)
FORMATO_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def identificar_cliente() -> tuple[str, list]:
    """Quem está perguntando e qual escada de limite se aplica a ele.

    Na ordem: a conta logada, o aparelho, o IP. A conta vem primeiro porque é a
    única das três que não dá para inventar. O IP é o último recurso porque a
    rede da USP é toda NAT: um laboratório inteiro sai pelo mesmo endereço, e
    limitar por IP puniria a turma por causa de um usuário. Mesmo assim ele
    precisa existir: sem ele, bastava omitir o header para escapar do limite.
    """
    usuario = usuario_do_pedido()
    if usuario:
        return f"conta:{usuario}", config.LIMITES_TAXA_CONTA

    dispositivo = (request.headers.get("X-Device-Id") or "").strip()
    if FORMATO_ID.match(dispositivo):
        return f"disp:{dispositivo}", config.LIMITES_TAXA_ANONIMO

    # O proxy do Render termina o TLS, então remote_addr é o proxy, não o aluno.
    encaminhado = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    endereco = encaminhado or request.remote_addr or "desconhecido"
    return f"ip:{endereco}", config.LIMITES_TAXA_ANONIMO


def verificar_limite(chave: str, escada: list) -> tuple[str, int] | None:
    """Registra a pergunta, ou devolve (janela estourada, segundos de espera)."""
    agora = time.monotonic()

    with _tranca:
        # Sem esta limpeza o dicionário cresce para sempre, um registro por
        # aparelho que passou pelo site.
        for antiga in [
            outra for outra, marcas in _batidas.items()
            if not marcas or agora - marcas[-1] > JANELA_MAXIMA
        ]:
            del _batidas[antiga]

        marcas = _batidas.setdefault(chave, deque())
        while marcas and agora - marcas[0] > JANELA_MAXIMA:
            marcas.popleft()

        for nome, segundos, maximo in escada:
            if maximo <= 0:
                continue  # janela desligada

            dentro = [marca for marca in marcas if agora - marca <= segundos]
            if len(dentro) >= maximo:
                # A vaga abre quando a batida mais antiga da janela sair dela.
                return nome, max(int(segundos - (agora - dentro[0])) + 1, 1)

        marcas.append(agora)

    return None
