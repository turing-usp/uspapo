"""O que uma falha de provedor significa, e o que fazer a respeito.

O SDK da OpenAI levanta a mesma família de exceções para situações que pedem
respostas opostas: uma cota estourada passa sozinha em segundos, uma chave
inválida não passa nunca. Tratar as duas igual, como o motor fazia antes, dá
o pior dos dois mundos: desiste cedo demais de quem ia voltar e insiste com
quem não ia.

Este módulo separa as duas perguntas:

    descrever(erro)    o que a API disse, em uma linha, para o log
    classificar(erro)  o que o motor deve fazer agora

O `descrever` existe porque o diagnóstico estava impossível: um provedor que
recusa a requisição inteira por tamanho (413) e um que recusa por rajada (429)
apareciam no log exatamente iguais, e são problemas diferentes, com correções
diferentes. O corpo do erro da Groq diz qual limite estourou e de quanto ele é;
essa informação era jogada fora.
"""

import random
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

# Quanto tempo a pergunta de um aluno pode ficar parada esperando uma cota
# liberar. Passou disso, cair para o próximo provedor responde mais rápido do
# que esperar — e o aluno está olhando para a tela.
TETO_ESPERA = 8.0

# Tentativas no MESMO provedor antes de passar para o próximo da cadeia.
MAX_TENTATIVAS = 3

# Base do backoff exponencial para falha de rede e 5xx.
BASE_BACKOFF = 0.5

# Quem falhou por cota volta sozinho; quem falhou por configuração (chave
# errada, modelo inexistente) só volta com alguém mexendo no .env, então fica
# de castigo por mais tempo para não custar um round-trip por pergunta.
COOLDOWN_CONFIGURACAO = 300.0

# Quem esgotou as tentativas por rede ou 5xx fica pouco tempo de castigo: pode
# voltar a qualquer momento, mas enquanto está fora não vale a pena cada
# pergunta pagar as três tentativas antes de cair para o próximo da cadeia.
COOLDOWN_TRANSITORIO = 15.0

# 400 que NÃO é configuração: o provedor recusou porque o próprio modelo
# produziu uma tool call inválida. Acontece de vez em quando com os modelos
# abertos e passa na tentativa seguinte, então seria péssimo tirar o provedor
# do ar por cinco minutos por causa disso.
CODIGOS_DO_MODELO = ("tool_use_failed", "json_validate_failed", "failed_generation")


@dataclass(frozen=True)
class Falha:
    """O veredito sobre uma falha: o que aconteceu e o que fazer agora."""

    motivo: str
    # Repetir a MESMA requisição neste mesmo provedor, depois de `espera`.
    repetir: bool = False
    espera: float = 0.0
    # Repetir, mas com o orçamento de contexto menor: a requisição não coube.
    encolher: bool = False
    # Não adianta insistir: o provedor precisa de intervenção humana.
    descartar: bool = False
    cooldown: float = 0.0


def _status(erro: Exception) -> int | None:
    """O código HTTP, quando a falha veio com resposta do servidor."""
    return getattr(erro, "status_code", None)


def _corpo(erro: Exception) -> dict:
    """O objeto `error` de dentro do corpo da resposta, se houver.

    Cada provedor põe o detalhe útil num lugar: a Groq manda
    {"error": {"message": ..., "type": ..., "code": "request_too_large"}}, que
    é onde está a diferença entre "requisição grande demais" e "rápido demais".
    """
    corpo = getattr(erro, "body", None)
    if isinstance(corpo, dict):
        interno = corpo.get("error")
        return interno if isinstance(interno, dict) else corpo
    return {}


def _codigo(erro: Exception) -> str:
    """O código de erro do provedor, em minúsculas ('' se não veio)."""
    return str(_corpo(erro).get("code") or getattr(erro, "code", "") or "").lower()


def _retry_after(erro: Exception) -> float | None:
    """Os segundos que o provedor pediu para esperar, se ele pediu.

    A Groq manda `retry-after` em segundos, às vezes fracionário. Respeitar o
    número dela é melhor do que qualquer backoff que a gente invente: ela sabe
    quando a janela abre, nós não.
    """
    resposta = getattr(erro, "response", None)
    cabecalhos = getattr(resposta, "headers", None)
    if cabecalhos is None:
        return None

    for nome in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        bruto = cabecalhos.get(nome)
        if not bruto:
            continue
        try:
            return max(float(str(bruto).rstrip("s")), 0.0)
        except ValueError:
            continue
    return None


def descrever(erro: Exception) -> str:
    """Uma linha de log com tudo que dá para saber sobre a falha.

    É o que transforma "o provedor falhou" em "a Groq recusou 18k tokens num
    modelo de 6k por minuto" — ou seja, em algo que se conserta.
    """
    partes = [type(erro).__name__]

    status = _status(erro)
    if status:
        partes.append(f"HTTP {status}")

    corpo = _corpo(erro)
    codigo = corpo.get("code") or corpo.get("type")
    if codigo:
        partes.append(str(codigo))

    espera = _retry_after(erro)
    if espera is not None:
        partes.append(f"retry-after={espera}s")

    mensagem = str(corpo.get("message") or erro).strip()
    if mensagem:
        partes.append(mensagem[:300])

    return " | ".join(partes)


def classificar(erro: Exception, tentativa: int, maximo: int = MAX_TENTATIVAS) -> Falha:
    """O que fazer com esta falha, na `tentativa`-ésima ida a este provedor.

    A ordem dos testes importa: `RateLimitError` e as demais são subclasses de
    `APIStatusError`, então o específico vem antes do genérico.
    """
    motivo = descrever(erro)
    esgotou = tentativa + 1 >= maximo
    status = _status(erro)

    # Requisição grande demais para a janela de token do modelo. Repetir igual
    # daria o mesmo 413 para sempre: o que muda o resultado é mandar menos.
    # A Groq responde 413; outros provedores usam 400 com o código no corpo.
    if status == 413 or "too_large" in _codigo(erro) or "context_length" in _codigo(erro):
        return Falha(motivo, encolher=True)

    # Cota estourada. O provedor diz quando a janela abre; se for logo, esperar
    # sai mais barato que trocar de modelo no meio da pergunta.
    if isinstance(erro, RateLimitError):
        espera = _retry_after(erro)
        if espera is None:
            espera = min(BASE_BACKOFF * (2**tentativa), TETO_ESPERA)

        if espera > TETO_ESPERA or esgotou:
            # Não vale segurar o aluno: vai para o próximo, e este fica de
            # castigo o tempo que ele mesmo pediu.
            return Falha(motivo, cooldown=espera)
        return Falha(motivo, repetir=True, espera=espera)

    # Configuração errada: chave inválida, sem permissão para o modelo, modelo
    # que não existe nesse provedor. Nada disso passa sozinho.
    if isinstance(erro, (AuthenticationError, PermissionDeniedError, NotFoundError)):
        return Falha(motivo, descartar=True, cooldown=COOLDOWN_CONFIGURACAO)

    # Rede, 5xx e o modelo tropeçando na própria tool call: o clássico "tenta
    # de novo daqui a pouco". O jitter existe para dois workers que caíram
    # juntos não voltarem juntos.
    transitorio = (
        isinstance(erro, (APITimeoutError, APIConnectionError))
        or (status is not None and status >= 500)
        or _codigo(erro) in CODIGOS_DO_MODELO
    )
    if transitorio:
        if esgotou:
            return Falha(motivo, cooldown=COOLDOWN_TRANSITORIO)
        espera = BASE_BACKOFF * (2**tentativa) + random.uniform(0, 0.3)
        return Falha(motivo, repetir=True, espera=min(espera, TETO_ESPERA))

    # 400 e 422 que sobraram: requisição malformada para ESTE provedor (uma
    # flag que ele não aceita, um schema que ele valida mais apertado). Repetir
    # não muda nada, mas os outros da cadeia podem aceitar.
    if isinstance(erro, APIStatusError):
        return Falha(motivo, descartar=True, cooldown=COOLDOWN_CONFIGURACAO)

    # O que sobra é falha nossa (RuntimeError do laço de ferramentas, stream
    # sem resposta utilizável): próximo provedor, sem castigo.
    return Falha(motivo)
