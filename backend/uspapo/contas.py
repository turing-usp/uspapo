"""Quem está perguntando: a conta do Supabase, quando dá para provar que há uma.

O login mora todo no frontend (Supabase Auth), e até agora o backend não sabia
nada sobre ele: o `/chat` só via o `X-Device-Id`, um UUID que o próprio
navegador gera. Isso basta para limitar uso acidental, mas não serve de base
para dar cota MAIOR a quem tem conta — bastaria inventar um id.

Por isso o site passa a mandar o access token do Supabase e aqui a assinatura é
conferida de verdade. O token é um JWT assinado pelo projeto Supabase; com o
segredo do projeto dá para validar sem perguntar nada a ninguém, sem round-trip
no caminho da pergunta.

Regra de ouro deste módulo: **nunca levantar e nunca recusar a pergunta**. Um
token expirado, malformado ou de outro projeto devolve None, e quem perguntou
cai no limite de anônimo. Sessão vencida no meio de uma conversa é problema de
cota, não motivo para o aluno tomar um 401 na cara.
"""

import os

from flask import request

from uspapo import config  # noqa: F401  (carrega o .env antes do getenv abaixo)

try:
    import jwt
except ImportError:  # pragma: no cover - só acontece se faltar instalar
    jwt = None

SEGREDO = (os.getenv("SUPABASE_JWT_SECRET") or "").strip()

# O Supabase põe esta audiência em todo token de usuário autenticado. Conferir
# evita aceitar um token de service_role, que é de outra natureza.
AUDIENCIA = "authenticated"


def disponivel() -> bool:
    """Dá para reconhecer contas nesta instância?"""
    return bool(SEGREDO) and jwt is not None


def aviso_de_configuracao() -> str:
    """Uma linha para o boot dizer por que as contas não são reconhecidas."""
    if jwt is None:
        return "PyJWT não está instalado: todo mundo cai no limite de anônimo."
    if not SEGREDO:
        return "SUPABASE_JWT_SECRET não está no .env: todo mundo cai no limite de anônimo."
    return ""


def _token_do_cabecalho() -> str:
    """O Bearer do Authorization, se veio um."""
    bruto = (request.headers.get("Authorization") or "").strip()
    if not bruto.lower().startswith("bearer "):
        return ""
    return bruto[7:].strip()


def usuario_do_pedido() -> str | None:
    """O id (`sub`) do usuário logado, ou None se não dá para provar quem é.

    Não distingue "não mandou token" de "mandou token inválido" de propósito:
    as duas situações levam ao mesmo lugar, o limite de anônimo, e tratá-las
    diferente só criaria um jeito de descobrir se um token é válido.
    """
    if not disponivel():
        return None

    token = _token_do_cabecalho()
    if not token:
        return None

    try:
        conteudo = jwt.decode(
            token,
            SEGREDO,
            algorithms=["HS256"],
            audience=AUDIENCIA,
            # O Supabase não põe `iss` em todos os projetos e o que importa
            # aqui é a assinatura: se ela bate, o token é deste projeto.
            options={"verify_iss": False},
        )
    except Exception:
        # Expirado, adulterado, de outro projeto: tudo vira anônimo.
        return None

    sub = str(conteudo.get("sub") or "").strip()
    return sub or None
