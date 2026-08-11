"""Gerenciador de cargos do USPapo no Supabase Auth.

Subcomandos:
    listar                       Mostra todos os usuarios e seus cargos
    definir <email> <cargo>      Atribui um cargo a um usuario
    lote <cargo> <email> ...     Atribui o mesmo cargo a varios usuarios de uma vez

Cargos validos: admin, membro, early_access, usuario_normal, ex_membro

Exemplos:
    python scripts/cargos.py listar
    python scripts/cargos.py definir aluno@usp.br early_access
    python scripts/cargos.py lote early_access aluno1@usp.br aluno2@usp.br aluno3@usp.br
"""

import os
import sys
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
from uspapo import config  # noqa: E402  (carrega .env)
from supabase import create_client  # noqa: E402

CARGOS = {"admin", "membro", "early_access"}


def _cliente():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("[ERRO] SUPABASE_URL ou SUPABASE_SERVICE_KEY nao configurados no .env")
        sys.exit(1)
    return create_client(url, key)


def _todos_usuarios(sb):
    """Busca paginada de todos os usuarios do Supabase Auth."""
    usuarios = []
    pagina = 1
    while True:
        lote = sb.auth.admin.list_users(page=pagina, per_page=50)
        if not lote:
            break
        usuarios.extend(lote)
        if len(lote) < 50:
            break
        pagina += 1
    return usuarios


def _cargo_uspapo(user) -> str:
    meta = (user.app_metadata or {}).get("uspapo") or {}
    return meta.get("role", "")


# ── Subcomando: listar ────────────────────────────────────────────────

def cmd_listar():
    sb = _cliente()
    usuarios = _todos_usuarios(sb)

    # Agrupa por cargo
    por_cargo = {}
    sem_cargo = []
    for u in usuarios:
        cargo = _cargo_uspapo(u)
        if cargo:
            por_cargo.setdefault(cargo, []).append(u)
        else:
            sem_cargo.append(u)

    print(f"\n{'='*60}")
    print(f"  USPapo - Cargos de {len(usuarios)} contas registradas")
    print(f"{'='*60}\n")

    for cargo in sorted(por_cargo):
        lista = sorted(por_cargo[cargo], key=lambda u: u.email or "")
        print(f"  [{cargo.upper()}] ({len(lista)} usuario(s))")
        for u in lista:
            print(f"    - {u.email}")
        print()

    if sem_cargo:
        sem_cargo.sort(key=lambda u: u.email or "")
        print(f"  [SEM CARGO] ({len(sem_cargo)} usuario(s))")
        for u in sem_cargo:
            print(f"    - {u.email or '(sem email)'}")
        print()


# ── Subcomando: definir ───────────────────────────────────────────────

def _encontrar_por_email(usuarios, email):
    email = email.strip().lower()
    for u in usuarios:
        if (u.email or "").strip().lower() == email:
            return u
    return None


def _aplicar_cargo(sb, user, cargo):
    app_meta = dict(user.app_metadata or {})
    uspapo_meta = dict(app_meta.get("uspapo") or {})

    antigo = uspapo_meta.get("role", "(nenhum)")
    uspapo_meta["role"] = cargo
    uspapo_meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    app_meta["uspapo"] = uspapo_meta

    sb.auth.admin.update_user_by_id(
        user.id,
        attributes={"app_metadata": app_meta},
    )
    return antigo


def cmd_definir(email, cargo):
    cargo = cargo.strip().lower()
    if cargo not in CARGOS:
        print(f"[ERRO] Cargo '{cargo}' invalido. Use: {', '.join(sorted(CARGOS))}")
        sys.exit(1)

    sb = _cliente()
    usuarios = _todos_usuarios(sb)
    user = _encontrar_por_email(usuarios, email)

    if not user:
        print(f"[ERRO] Nenhuma conta com email '{email}' encontrada.")
        sys.exit(1)

    antigo = _aplicar_cargo(sb, user, cargo)
    print(f"[OK] {email}: {antigo} -> {cargo}")


# ── Subcomando: lote ──────────────────────────────────────────────────

def cmd_lote(cargo, emails):
    cargo = cargo.strip().lower()
    if cargo not in CARGOS:
        print(f"[ERRO] Cargo '{cargo}' invalido. Use: {', '.join(sorted(CARGOS))}")
        sys.exit(1)

    sb = _cliente()
    usuarios = _todos_usuarios(sb)

    ok, falhas = 0, 0
    for email in emails:
        email = email.strip().lower()
        if not email:
            continue
        user = _encontrar_por_email(usuarios, email)
        if not user:
            print(f"[FALHA] {email} -- conta nao encontrada")
            falhas += 1
            continue
        try:
            antigo = _aplicar_cargo(sb, user, cargo)
            print(f"[OK] {email}: {antigo} -> {cargo}")
            ok += 1
        except Exception as e:
            print(f"[FALHA] {email} -- {e}")
            falhas += 1

    print(f"\nResultado: {ok} atualizados, {falhas} falhas.")


# ── main ──────────────────────────────────────────────────────────────

AJUDA = """
Uso:
    python scripts/cargos.py listar
    python scripts/cargos.py definir <email> <cargo>
    python scripts/cargos.py lote <cargo> <email1> <email2> ...

Cargos: admin, membro, early_access, usuario_normal, ex_membro
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
