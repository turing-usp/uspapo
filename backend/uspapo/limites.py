"""Rate limit: quantas perguntas cada conta pode fazer por janela de tempo.

Uma escada só, porque só existe um tipo de cliente: o login é obrigatório, então
quem chega até aqui já provou a conta em contas.py. Antes havia uma segunda
escada, mais apertada, para quem perguntava sem login: identificado pelo
X-Device-Id, que o próprio navegador gera e trocar custa um clique. Ela existia
para sustentar o uso anônimo, e foi embora junto com ele.

As quatro janelas valem ao mesmo tempo: a de minuto segura a rajada, a de dia
segura o uso crônico. Todas em 0 desligam o rate limit, que é a configuração
esperada quando a whitelist do acesso.py é quem segura a porta.

Limitação conhecida: `_batidas` é um dicionário deste processo. Com mais de um
worker do gunicorn cada worker conta por si, e reiniciar zera a contagem. Isso
já valia antes e continua valendo: para segurar uso acidental e abuso casual
é o suficiente; para um atacante dedicado nunca foi a defesa certa.
"""

import threading
import time
from collections import deque

from uspapo import config

_batidas: dict[str, deque[float]] = {}
_tranca = threading.Lock()

JANELA_MAXIMA = max(segundos for _, segundos, _ in config.LIMITES_TAXA)


def desligado() -> bool:
    """Nenhuma janela ligada — nem vale a pena contar nada."""
    return not any(maximo > 0 for _, _, maximo in config.LIMITES_TAXA)


def verificar_limite(chave: str) -> tuple[str, int] | None:
    """Registra a pergunta, ou devolve (janela estourada, segundos de espera)."""
    # Sem nenhuma janela ligada, contar batida seria encher `_batidas` de
    # registro que ninguém vai ler e ainda varrer tudo isso a cada pergunta.
    if desligado():
        return None

    agora = time.monotonic()

    with _tranca:
        # Sem esta limpeza o dicionário cresce para sempre, um registro por
        # conta que passou pelo site.
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
