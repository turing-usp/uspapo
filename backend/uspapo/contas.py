"""Quem está perguntando: a conta do Supabase, provada pela assinatura do token.

O login mora todo no frontend (Supabase Auth) e o site manda o access token no
cabeçalho Authorization. Aqui a assinatura é conferida de verdade, sem nenhum
round-trip no caminho da pergunta.

O token é um JWT assinado com chave ASSIMÉTRICA (ES256, ou RS256 em projeto mais
antigo). A parte pública mora no JWKS do projeto, em
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, e é ela que valida: do lado do
backend não existe mais segredo compartilhado. As chaves novas do Supabase
(`sb_publishable_…` e `sb_secret_…`) NÃO entram nesta conta, não são JWT e não
assinam nada; a `sb_secret_` é credencial de `apikey`, herdeira da service_role.

Este módulo mudou de regra de ouro. Antes ele nunca recusava: token vencido ou
forjado virava anônimo calado, porque anônimo também podia perguntar. Agora o
login é obrigatório e recusar é o trabalho. O que ele continua NÃO fazendo é
decidir quem pode entrar, isso é do acesso.py. Aqui só se estabelece quem é.

Três respostas possíveis, e a diferença entre elas é o que o aluno precisa fazer:

    Conta(...)            o token vale; siga
    None                  não veio token, ou o que veio não vale -> faça login
    FalhaDeVerificacao    o JWKS não respondeu, ou falta configuração aqui;
                          não dá para afirmar nem para negar -> tente de novo
"""

import os
from typing import NamedTuple

from flask import request

from uspapo import config  # noqa: F401  (carrega o .env antes do getenv abaixo)

try:
    import jwt
    from jwt import PyJWKClient
    from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
except ImportError:  # pragma: no cover - só acontece se faltar instalar
    jwt = None

URL_PROJETO = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")

# O Supabase põe esta audiência em todo token de usuário autenticado. Conferir
# evita aceitar um token de service_role, que é de outra natureza.
AUDIENCIA = "authenticated"

# Só os assimétricos: aceitar HS256 aqui seria aceitar que a chave pública do
# JWKS fosse usada como segredo de HMAC, que é o ataque clássico de confusão de
# algoritmo.
ALGORITMOS = ["ES256", "RS256"]

# O Supabase cacheia o JWKS na borda por 10 minutos. Guardar pelo mesmo tempo
# evita uma ida à rede por pergunta sem atrasar uma rotação de chave além do que
# o próprio Supabase já atrasa.
CACHE_JWKS = 600
# O padrão do PyJWKClient é 30s, tempo demais para segurar uma pergunta: se o
# JWKS não respondeu em 5s, é melhor devolver "tente de novo" do que pendurar.
TIMEOUT_JWKS = 5


class FalhaDeVerificacao(Exception):
    """Não deu para conferir o token — o que é diferente de conferir e recusar.

    JWKS fora do ar, DNS caído, SUPABASE_URL faltando: são problemas daqui, e
    quem chamar deve responder "tente de novo em instantes", nunca mandar o
    aluno fazer login de uma sessão que provavelmente está boa.
    """


class Conta(NamedTuple):
    """A identidade provada pelo token."""

    id: str     # o `sub` do JWT: estável, é a chave do rate limit
    email: str  # normalizado (minúsculas); é por ele que a whitelist decide


_cliente_jwks = None
if URL_PROJETO and jwt is not None:
    _cliente_jwks = PyJWKClient(
        f"{URL_PROJETO}/auth/v1/.well-known/jwks.json",
        # De propósito sem `cache_keys=True`: aquele cache é um lru_cache por
        # `kid`, sem prazo, e uma chave revogada continuaria valendo até alguém
        # reiniciar o worker. O cache do conjunto abaixo já evita a ida à rede
        # por pergunta, e esse expira.
        cache_jwk_set=True,
        lifespan=CACHE_JWKS,
        timeout=TIMEOUT_JWKS,
    )


def disponivel() -> bool:
    """Dá para reconhecer contas nesta instância?"""
    return _cliente_jwks is not None


def aviso_de_configuracao() -> str:
    """Uma linha para o boot dizer por que ninguém vai conseguir perguntar."""
    if jwt is None:
        return "PyJWT[crypto] não está instalado: NINGUÉM consegue perguntar."
    if not URL_PROJETO:
        return "SUPABASE_URL não está no .env: NINGUÉM consegue perguntar."
    return ""


def _token_do_cabecalho() -> str:
    """O Bearer do Authorization, se veio um."""
    bruto = (request.headers.get("Authorization") or "").strip()
    if not bruto.lower().startswith("bearer "):
        return ""
    return bruto[7:].strip()


def conta_do_pedido() -> Conta | None:
    """A conta que assina este pedido, ou None se não dá para provar quem é.

    Não distingue "não mandou token" de "mandou token inválido" de propósito: as
    duas levam ao mesmo lugar, a tela de login, e separá-las só criaria um jeito
    de descobrir se um token qualquer é válido.

    O email pode vir vazio: cadastro só por telefone e anonymous sign-in geram
    token sem a claim. Quem cuida disso é o acesso.py, que reprova email vazio
    em qualquer modo de whitelist que não seja "todos".
    """
    if _cliente_jwks is None:
        # Falta de configuração é problema do servidor. Devolver None aqui
        # mandaria todo mundo fazer login de novo para nada.
        raise FalhaDeVerificacao(aviso_de_configuracao())

    token = _token_do_cabecalho()
    if not token:
        return None

    try:
        chave = _cliente_jwks.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError as erro:
        raise FalhaDeVerificacao(f"JWKS inacessível: {erro}") from erro
    except PyJWKClientError:
        # `kid` que não está no JWKS: token de outro projeto ou forjado.
        return None
    except Exception:
        # Token malformado o bastante para nem ter cabeçalho legível.
        return None

    try:
        conteudo = jwt.decode(
            token,
            chave.key,
            algorithms=ALGORITMOS,
            audience=AUDIENCIA,
            # O Supabase não põe `iss` em todos os projetos, e aqui ele não
            # acrescentaria garantia: a URL do JWKS já vem do SUPABASE_URL, então
            # a assinatura bater é a prova de que o token é deste projeto.
            options={"verify_iss": False},
        )
    except Exception:
        # Expirado, adulterado, algoritmo errado: nada disso vira conta.
        return None

    sub = str(conteudo.get("sub") or "").strip()
    if not sub:
        return None

    email = str(conteudo.get("email") or "").strip().lower()
    return Conta(sub, email)
