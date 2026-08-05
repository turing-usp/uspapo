"""Memória curta sobre quais provedores estão de castigo.

Sem isto, a cadeia é percorrida do zero a cada pergunta: um provedor que
estourou a cota há dois segundos é tentado primeiro de novo, gasta o
round-trip, toma o mesmo 429 e só então a pergunta anda. Com dez alunos
perguntando ao mesmo tempo, isso multiplica as chamadas justamente no momento
em que a cota é o problema.

O estado é o mesmo tipo de coisa que o `limites.py` guarda: um dict com uma
tranca, vivo enquanto o processo viver. Não é preciso mais do que isso: perder
o castigo num restart apenas faz a primeira pergunta pagar um round-trip.
"""

import threading
import time

_castigos: dict[str, float] = {}  # nome do provedor -> time.monotonic() de soltura
_tranca = threading.Lock()


def marcar_falha(nome: str, segundos: float) -> None:
    """Põe o provedor de castigo por `segundos` a partir de agora.

    Castigo mais curto não encurta um que já esteja valendo: se a chave está
    inválida (cinco minutos) e por acaso um 429 chegar depois, seria errado
    soltar o provedor em três segundos.
    """
    if segundos <= 0:
        return

    ate = time.monotonic() + segundos
    with _tranca:
        _castigos[nome] = max(_castigos.get(nome, 0.0), ate)


def marcar_sucesso(nome: str) -> None:
    """Provedor respondeu: solta o castigo, se havia."""
    with _tranca:
        _castigos.pop(nome, None)


def espera_restante(nome: str) -> float:
    """Segundos que faltam do castigo deste provedor (0.0 se está livre)."""
    with _tranca:
        ate = _castigos.get(nome)
        if ate is None:
            return 0.0

        restante = ate - time.monotonic()
        if restante <= 0:
            del _castigos[nome]
            return 0.0
        return restante


def ordenar(nomes: list[str]) -> list[str]:
    """A cadeia reordenada: quem está livre primeiro, na ordem original.

    Devolve TODOS os nomes, nunca uma lista menor. Um provedor de castigo é
    despriorizado, não eliminado — se todos estiverem de castigo, a pergunta
    ainda tem que ser tentada, começando por quem sai antes. Filtrar aqui faria
    o castigo virar a causa do erro que ele existe para evitar.
    """
    livres = [nome for nome in nomes if espera_restante(nome) == 0.0]
    presos = sorted(
        (nome for nome in nomes if nome not in livres), key=espera_restante
    )
    return livres + presos


def panorama(nomes: list[str]) -> dict[str, float]:
    """Quanto falta de castigo para cada provedor, para o /health."""
    return {nome: round(espera_restante(nome), 1) for nome in nomes}
