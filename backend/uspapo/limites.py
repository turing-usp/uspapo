"""Rate limit: quantas perguntas cada aparelho pode fazer por janela de tempo."""

import re
import threading
import time
from collections import deque

from flask import request

from uspapo import config

_batidas: dict[str, deque[float]] = {}
_tranca = threading.Lock()

JANELA_MAXIMA = max(segundos for _, segundos, _ in config.LIMITES_TAXA)
FORMATO_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def identificar_cliente() -> str:
    """Chave do rate limit: o aparelho, não o IP.

    A rede da USP é toda NAT, então um laboratório inteiro sai pelo mesmo
    endereço; limitar por IP puniria a turma por causa de um usuário. O ID vem
    do navegador e é falsificável, mas o alvo aqui é uso acidental e abuso
    casual, não um atacante dedicado. Sem o header a chave cai para o IP, senão
    bastava omiti-lo para escapar do limite.
    """
    dispositivo = (request.headers.get("X-Device-Id") or "").strip()
    if FORMATO_ID.match(dispositivo):
        return f"disp:{dispositivo}"

    # O proxy do Render termina o TLS, então remote_addr é o proxy, não o aluno.
    encaminhado = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return f"ip:{encaminhado or request.remote_addr or 'desconhecido'}"


def verificar_limite(chave: str) -> tuple[str, int] | None:
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

        for nome, segundos, maximo in config.LIMITES_TAXA:
            if maximo <= 0:
                continue  # janela desligada

            dentro = [marca for marca in marcas if agora - marca <= segundos]
            if len(dentro) >= maximo:
                # A vaga abre quando a batida mais antiga da janela sair dela.
                return nome, max(int(segundos - (agora - dentro[0])) + 1, 1)

        marcas.append(agora)

    return None
