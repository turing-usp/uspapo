import os
import json
import threading
from pathlib import Path
from dotenv import load_dotenv

# Carrega as variáveis de ambiente
load_dotenv()

# Instância lazy do Supabase para evitar crash se credenciais não existirem em dev local
_supabase_client = None

def _obter_supabase():
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
    except Exception as e:
        print(f"[AVISO ANALYTICS] Supabase não inicializado: {e}")
        return None

# Carrega o dicionário de eventos seguro
caminho_json = Path(__file__).parent / "eventos.json"
try:
    with open(caminho_json, "r", encoding="utf-8") as f:
        DICIONARIO_EVENTOS = json.load(f)
except Exception:
    DICIONARIO_EVENTOS = {}

def _inserir_assincrono(dados_log: dict):
    """Roda em background em thread assíncrona para não travar o Flask."""
    client = _obter_supabase()
    if not client:
        return
    try:
        client.table("analytics_logs").insert(dados_log).execute()
    except Exception as e:
        print(f"[ERRO ANALYTICS] Falha ao registrar log: {e}")

def registrar(
    categoria: str,
    nome_evento: str,
    session_id: str = None,
    user_id: str = None,
    provedor: str = None,
    modelo: str = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latencia_ms: int = 0,
    metadata: dict = None
):
    """
    Função principal para ser chamada em qualquer ponto do backend.
    
    Exemplo:
        registrar(
            categoria="CHAT",
            nome_evento="RESPOSTA_CONCLUIDA",
            session_id="sess_123",
            user_id="user_456",
            provedor="Groq",
            modelo="llama-3.1-70b-versatile",
            prompt_tokens=150,
            completion_tokens=80,
            total_tokens=230,
            latencia_ms=450
        )
    """
    try:
        evento_oficial = DICIONARIO_EVENTOS.get(categoria, {}).get(nome_evento)
        if not evento_oficial:
            evento_oficial = f"{categoria.lower()}_{nome_evento.lower()}"
    except Exception:
        evento_oficial = f"{categoria.lower()}_{nome_evento.lower()}"

    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens

    dados = {
        "evento": evento_oficial,
        "session_id": session_id,
        "user_id": user_id,
        "provedor": provedor,
        "modelo": modelo,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latencia_ms": latencia_ms,
        "metadata": metadata or {}
    }
    
    # Dispara em thread separada
    threading.Thread(target=_inserir_assincrono, args=(dados,), daemon=True).start()