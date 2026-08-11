"""Quem pode usar o USPapo: permissões da coluna uspapo_role na tabela Perfis.

O contas.py estabelece QUEM é quem pergunta; aqui se decide se essa pessoa pode.
São perguntas diferentes e por isso moram em módulos diferentes.

A coluna ``uspapo_role`` na tabela ``Perfis`` do Supabase controla o acesso:

    admin           acesso total: chat + painel de analytics
    early_access    acesso ao chat durante o beta fechado
    NULL / vazio    sem acesso ao chat (conta aguardando liberação)

Para dar acesso a alguém, basta editar a coluna ``uspapo_role`` no Table Editor
do Supabase (tabela Perfis) ou rodar: python scripts/cargos.py definir <email> <role>
"""

import os

from supabase import create_client

from uspapo import config

ROLES_CHAT = {"admin", "early_access"}

_supabase = None


def _obter_supabase():
    """Cliente Supabase lazy: só cria na primeira chamada."""
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        if url and key:
            _supabase = create_client(url, key)
    return _supabase


def obter_role(user_id: str) -> str:
    """Busca a uspapo_role do usuario na tabela Perfis pelo user_id."""
    client = _obter_supabase()
    if not client:
        return ""
    try:
        res = client.table("Perfis").select("uspapo_role").eq("id", user_id).limit(1).execute()
        if res.data:
            return (res.data[0].get("uspapo_role") or "").strip().lower()
    except Exception:
        pass
    return ""


def liberado(user_id: str) -> bool:
    """Valida se o usuario pode usar o chat do USPapo.

    Liberado EXCLUSIVAMENTE para contas com uspapo_role 'admin' ou 'early_access'
    na tabela Perfis do Supabase.
    """
    role = obter_role(user_id)
    return role in ROLES_CHAT


def e_admin(user_id: str) -> bool:
    """Valida se o usuario e admin do USPapo."""
    return obter_role(user_id) == "admin"


def panorama() -> str:
    """Resumo do estado de acesso para o /health."""
    return "uspapo_role na tabela Perfis"


def aviso_de_configuracao() -> str:
    """Linha para o boot."""
    return "Acesso controlado pela coluna uspapo_role na tabela Perfis."
