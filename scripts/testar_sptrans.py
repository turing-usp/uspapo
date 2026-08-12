"""Script auxiliar para testar o status de ativação da chave SPTrans Olho Vivo no .env.

Usa apenas a biblioteca padrão do Python (urllib), sem depender de pacotes externos
como requests ou python-dotenv, permitindo rodar em qualquer interpreter Python.
"""

import os
import re
import urllib.request
import urllib.parse
from pathlib import Path


def ler_token_do_env() -> str:
    """Procura a variável SPTRANS_TOKEN no ambiente ou lê do arquivo .env."""
    token = os.environ.get("SPTRANS_TOKEN", "").strip()
    if token:
        return token

    # Procurar arquivo .env na raiz do projeto
    raiz = Path(__file__).resolve().parent.parent
    caminho_env = raiz / ".env"

    if caminho_env.exists():
        with open(caminho_env, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha.startswith("SPTRANS_TOKEN="):
                    val = linha.split("=", 1)[1].strip()
                    # Remover aspas se houver
                    return val.strip("\"'")

    return ""


def main():
    token = ler_token_do_env()

    if not token:
        print("[ERRO] SPTRANS_TOKEN não foi encontrado no seu arquivo .env!")
        print("Adicione a linha abaixo no seu .env:")
        print("SPTRANS_TOKEN=sua_chave_aqui")
        return

    print("-> Testando chave SPTrans no servidor Olho Vivo...")
    print(f"-> Token: {token[:10]}...{token[-6:]}")

    url = f"https://api.olhovivo.sptrans.com.br/v2.1/Login/Autenticar?token={urllib.parse.quote(token)}"

    try:
        req = urllib.request.Request(url, method="POST")
        req.add_header("User-Agent", "USPapo/1.0")

        with urllib.request.urlopen(req, timeout=10) as resp:
            corpo = resp.read().decode("utf-8").strip().lower()
            if corpo == "true":
                print("\n[OK] SUCESSO! A chave foi ATIVADA pela SPTrans (retornou true).")
                print("O rastreamento de GPS e frota em tempo real já está funcionando!")
            else:
                print("\n[PENDENTE] A SPTrans respondeu HTTP 200, mas a chave ainda retornou 'false'.")
                print("Aguarde a sincronização de banco da SPTrans e execute este script novamente em alguns minutos.")
    except Exception as err:
        print(f"\n[ERRO] Falha de conexão: {err}")


if __name__ == "__main__":
    main()
