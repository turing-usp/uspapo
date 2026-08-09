import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_supabase_client = None


def _obter_supabase():
    """Create the service-role client only when analytics is actually used."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None

    try:
        from supabase import create_client

        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception as erro:
        print(f"[AVISO ANALYTICS] Supabase nao inicializado: {erro}")
        return None


caminho_json = Path(__file__).parent / "eventos.json"
try:
    with open(caminho_json, "r", encoding="utf-8") as arquivo:
        DICIONARIO_EVENTOS = json.load(arquivo)
except Exception:
    DICIONARIO_EVENTOS = {}


def _inserir(dados_log: dict) -> bool:
    """Persist one event before the request finishes.

    This intentionally does not use a daemon thread. Such a thread can be
    terminated with a web/serverless worker immediately after a streamed
    response, which made telemetry randomly disappear.
    """
    client = _obter_supabase()
    if not client:
        print("[ERRO ANALYTICS] Supabase nao configurado; evento nao registrado.")
        return False

    try:
        client.table("analytics_logs").insert(dados_log).execute()
        return True
    except Exception as erro:
        # Compatibility for the original, smaller schema. Do not retry fields
        # that may be the reason the current insert was rejected.
        if "PGRST204" in str(erro) or "column" in str(erro).lower():
            try:
                legado = {
                    "evento": dados_log.get("evento"),
                    "session_id": dados_log.get("session_id"),
                    "user_id": dados_log.get("user_id"),
                    "tokens_gastos": dados_log.get("total_tokens", 0),
                    "latencia_ms": dados_log.get("latencia_ms", 0),
                }
                client.table("analytics_logs").insert(legado).execute()
                return True
            except Exception as erro_legado:
                print(f"[ERRO ANALYTICS] Falha no fallback: {erro_legado}")
        else:
            print(f"[ERRO ANALYTICS] Falha ao registrar log: {erro}")
        return False


def registrar(
    categoria: str,
    nome_evento: str,
    session_id: str | None = None,
    user_id: str | None = None,
    provedor: str | None = None,
    modelo: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latencia_ms: int = 0,
    metadata: dict | None = None,
) -> bool:
    """Record an analytics event and return whether Supabase accepted it."""
    evento = DICIONARIO_EVENTOS.get(categoria, {}).get(nome_evento)
    if not evento:
        evento = f"{categoria.lower()}_{nome_evento.lower()}"

    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens

    if not session_id:
        prefixo = str(user_id)[:8] if user_id else "anon"
        session_id = f"sess_{prefixo}_{int(time.time())}"

    return _inserir({
        "evento": evento,
        "session_id": session_id,
        "user_id": user_id,
        "provedor": provedor,
        "modelo": modelo,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latencia_ms": latencia_ms,
        "metadata": metadata or {},
    })
