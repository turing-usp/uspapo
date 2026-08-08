import os
import json
import threading
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega as variáveis de ambiente
load_dotenv()

# Inicializa o cliente do Supabase para o Backend
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(URL, KEY)

# Carrega o dicionário de eventos seguro
caminho_json = Path(__file__).parent / "eventos.json"
with open(caminho_json, "r", encoding="utf-8") as f:
    DICIONARIO_EVENTOS = json.load(f)

def _inserir_assincrono(dados_log):
    """Roda em background para não travar a resposta do Flask"""
    try:
        supabase.table("analytics_logs").insert(dados_log).execute()
    except Exception as e:
        print(f"[ERRO ANALYTICS] Falha ao registrar log: {e}")

def registrar(categoria: str, nome_evento: str, session_id: str, user_id: str = None, tokens: int = 0, latencia: int = 0):
    """
    Função principal para ser chamada em qualquer lugar do backend.
    Exemplo de uso: registrar("CHAT", "NOVA_PERGUNTA", session_id)
    """
    # Valida se o evento existe no JSON para padronizar o banco
    try:
        evento_oficial = DICIONARIO_EVENTOS[categoria][nome_evento]
    except KeyError:
        print(f"[AVISO] Evento {categoria}.{nome_evento} não mapeado no eventos.json!")
        evento_oficial = f"unknown_{nome_evento}"

    dados = {
        "evento": evento_oficial,
        "session_id": session_id,
        "user_id": user_id,
        "tokens_gastos": tokens,
        "latencia_ms": latencia
    }
    
    # Dispara a thread para não atrasar a vida do usuário
    threading.Thread(target=_inserir_assincrono, args=(dados,)).start()