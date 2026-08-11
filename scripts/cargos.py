"""Gerenciador de cargos do USPapo na tabela Perfis no Supabase.

Subcomandos:
    listar                       Mostra todos os usuarios e seus cargos do USPapo
    definir <email> <cargo>      Atribui um cargo a um usuario na tabela Perfis
    lote <cargo> <email> ...     Atribui o mesmo cargo a varios usuarios de uma vez

Cargos validos: admin, early_access (ou 'remover' para limpar)

Exemplos:
    python scripts/cargos.py listar
    python scripts/cargos.py definir aluno@usp.br early_access
    python scripts/cargos.py lote early_access aluno1@usp.br aluno2@usp.br
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
from uspapo import config  # noqa: E402  (carrega .env)
from supabase import create_client  # noqa: E402

CARGOS = {"admin", "early_access", "remover"}


def _cliente():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("[ERRO] SUPABASE_URL ou SUPABASE_SERVICE_KEY nao configurados no .env")
        sys.exit(1)
    return create_client(url, key)


def _todos_perfis(sb):
    """Busca todas as linhas da tabela Perfis."""
    res = sb.table("Perfis").select("id, email, nome, uspapo_role").execute()
    return res.data or []


# ── Subcomando: listar ────────────────────────────────────────────────

def cmd_listar():
    sb = _cliente()
    perfis = _todos_perfis(sb)

    por_cargo = {}
    sem_cargo = []

    for p in perfis:
        cargo = (p.get("uspapo_role") or "").strip().lower()
        if cargo:
            por_cargo.setdefault(cargo, []).append(p)
        else:
            sem_cargo.append(p)

    print(f"\n{'='*60}")
    print(f"  USPapo - Cargos na tabela Perfis ({len(perfis)} contas)")
    print(f"{'='*60}\n")

    for cargo in sorted(por_cargo):
        lista = sorted(por_cargo[cargo], key=lambda x: x.get("email") or "")
        print(f"  [{cargo.upper()}] ({len(lista)} usuario(s))")
        for u in lista:
            print(f"    - {u.get('email')} ({u.get('nome') or 'Sem nome'})")
        print()

    if sem_cargo:
        sem_cargo.sort(key=lambda x: x.get("email") or "")
        print(f"  [SEM CARGO / BLOQUEADO] ({len(sem_cargo)} usuario(s))")
        for u in sem_cargo:
            print(f"    - {u.get('email') or '(sem email)'}")
        print()


# ── Subcomando: definir ───────────────────────────────────────────────

def cmd_definir(email: str, cargo: str):
    cargo = cargo.strip().lower()
    if cargo not in CARGOS:
        print(f"[ERRO] Cargo '{cargo}' invalido. Use: {', '.join(sorted(CARGOS))}")
        sys.exit(1)

    valor_role = None if cargo == "remover" else cargo

    sb = _cliente()
    email_clean = email.strip().lower()

    # Atualiza na tabela Perfis
    res = sb.table("Perfis").update({"uspapo_role": valor_role}).eq("email", email_clean).execute()

    if res.data:
        print(f"[OK] {email_clean} -> {cargo}")
    else:
        print(f"[FALHA] {email_clean} nao foi encontrado na tabela Perfis.")


# ── Subcomando: lote ──────────────────────────────────────────────────

def cmd_lote(cargo: str, emails: list[str]):
    cargo = cargo.strip().lower()
    if cargo not in CARGOS:
        print(f"[ERRO] Cargo '{cargo}' invalido. Use: {', '.join(sorted(CARGOS))}")
        sys.exit(1)

    valor_role = None if cargo == "remover" else cargo
    sb = _cliente()

    ok, falhas = 0, 0
    for email in emails:
        email_clean = email.strip().lower()
        if not email_clean:
            continue
        try:
            res = sb.table("Perfis").update({"uspapo_role": valor_role}).eq("email", email_clean).execute()
            if res.data:
                print(f"[OK] {email_clean} -> {cargo}")
                ok += 1
            else:
                print(f"[FALHA] {email_clean} -- conta nao encontrada na tabela Perfis")
                falhas += 1
        except Exception as e:
            print(f"[FALHA] {email_clean} -- {e}")
            falhas += 1

    print(f"\nResultado: {ok} atualizados, {falhas} falhas.")


# ── main ──────────────────────────────────────────────────────────────

AJUDA = """
Uso:
    python scripts/cargos.py listar
    python scripts/cargos.py definir <email> <cargo>
    python scripts/cargos.py lote <cargo> <email1> <email2> ...

Cargos validos: admin, early_access, remover
""".strip()

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "ajuda"):
        print(AJUDA)
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "listar":
        cmd_listar()
    elif cmd == "definir":
        if len(args) < 3:
            print("Uso: python scripts/cargos.py definir <email> <cargo>")
            sys.exit(1)
        cmd_definir(args[1], args[2])
    elif cmd == "lote":
        if len(args) < 3:
            print("Uso: python scripts/cargos.py lote <cargo> <email1> <email2> ...")
            sys.exit(1)
        cmd_lote(args[1], args[2:])
    else:
        print(f"Subcomando '{cmd}' nao reconhecido.\n")
        print(AJUDA)
        sys.exit(1)
