"""Quem pode usar o USPapo: o cargo no Supabase OU a whitelist de emails.

O contas.py estabelece QUEM é quem pergunta; aqui se decide se essa pessoa pode.
São perguntas diferentes e por isso moram em módulos diferentes.

São duas portas, e basta passar por uma:

    uspapo_role       a coluna na tabela ``Perfis`` do Supabase. Vale para a
                      conta e muda sem deploy, pelo Table Editor ou pelo
                      scripts/cargos.py. É a única que dá admin.

        admin         acesso total: chat + painel de analytics
        early_access  acesso ao chat durante o beta fechado
        NULL / vazio  esta porta não abre (a outra ainda pode)

    WHITELIST_EMAILS  a lista no .env, por email da conta. Vale para convidar
                      uma turma de uma vez, sem passar de um em um no painel.
                      Não dá admin nem analytics, só chat.

A whitelist NÃO abre sozinha por descuido: ausente ou vazia, ela não libera
ninguém e quem decide é o cargo. É o contrário do que valia quando ela era a
única porta, ali um valor em branco tinha que significar "todos", senão um
.env incompleto derrubava o /chat inteiro. Hoje um branco que significasse
"todos" abriria o beta fechado para qualquer conta logada sem ninguém pedir.

Três formas de escrever a WHITELIST_EMAILS, e a primeira é a recomendada:

    ["fulano@usp.br", "@turingusp.com"]   lista JSON, igual à LLM_PROVIDERS
    fulano@usp.br, @turingusp.com         separada por vírgula, ; ou quebra de
                                          linha
    todos                                 qualquer conta logada entra
    ninguem                               igual a vazia: só o cargo decide

A entrada começando com @ libera o domínio inteiro.
"""

import json
import os

from supabase import create_client

from uspapo import config

ROLES_CHAT = {"admin", "early_access"}

TODOS = "todos"
NINGUEM = "ninguem"
LISTA = "lista"

# Aceitos com e sem acento: o .env é um arquivo de texto sem garantia nenhuma de
# encoding, e quem escreve "ninguém" quer dizer a mesma coisa que "ninguem".
_SINONIMOS_TODOS = {"todos", "todas", "tudo", "all", "*"}
_SINONIMOS_NINGUEM = {"ninguem", "ninguém", "nenhum", "nenhuma", "none"}

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


class Whitelist:
    """A lista já interpretada: o parse acontece uma vez, na construção.

    É uma classe e não um punhado de constantes de módulo para poder existir mais
    de uma na mesma execução. Sem isso, testar dez configurações diferentes
    exigiria recarregar o módulo dez vezes.
    """

    def __init__(self, bruto: str) -> None:
        itens = {parte.lower() for parte in _separar(bruto)}
        itens.discard("")

        # "todos" ganha de qualquer coisa na mesma linha: quem escreveu
        # "todos, fulano@usp.br" quis abrir, e a lista ao lado é sobra de edição.
        if itens & _SINONIMOS_TODOS:
            self.modo, self.entradas = TODOS, frozenset()
        elif not itens or itens <= _SINONIMOS_NINGUEM:
            self.modo, self.entradas = NINGUEM, frozenset()
        else:
            self.modo = LISTA
            self.entradas = frozenset(itens - _SINONIMOS_NINGUEM)

    def liberado(self, email: str) -> bool:
        """Este email passa por ESTA porta?

        Um "não" daqui não é um 403: quem chama confere o cargo também. O que
        esta função responde é só a parte da whitelist.

        Email vazio é reprovado em tudo que não seja o modo "todos". É o que
        trata os tokens sem a claim (cadastro por telefone, anonymous sign-in)
        sem precisar de um caso especial lá no contas.py.
        """
        if self.modo == TODOS:
            return True
        if self.modo == NINGUEM:
            return False

        email = (email or "").strip().lower()
        if "@" not in email:
            return False
        if email in self.entradas:
            return True
        return email[email.rfind("@"):] in self.entradas

    def panorama(self) -> str:
        """O estado da lista para o /health, sem vazar os emails dela."""
        if self.modo != LISTA:
            return self.modo
        return f"{len(self.entradas)} entrada{'s' if len(self.entradas) != 1 else ''}"

    def aviso(self) -> str:
        """Uma linha para o boot dizer o que a lista está liberando hoje."""
        if self.modo == TODOS:
            return (
                "ATENÇÃO: WHITELIST_EMAILS=todos, então QUALQUER conta logada "
                "pergunta, com ou sem uspapo_role."
            )
        if self.modo == NINGUEM:
            return "whitelist vazia (só a uspapo_role libera)."

        aviso = f"{self.panorama()} na whitelist, além de quem tem uspapo_role."
        # Entrada sem '@' não casa nem email nem domínio: quase sempre é o
        # domínio escrito sem o arroba, e o dono só descobriria pelo 403 de quem
        # ficou de fora.
        orfas = sorted(entrada for entrada in self.entradas if "@" not in entrada)
        if orfas:
            aviso += (
                f" Sem '@', então não liberam ninguém (faltou o arroba do"
                f" domínio?): {', '.join(orfas)}"
            )
        return aviso


def _separar(bruto: str) -> list[str]:
    """Os pedaços da WHITELIST_EMAILS, já sem espaço em volta.

    Duas escritas, e a diferença é o tamanho. Uma lista de cinquenta emails
    separada por vírgula vira uma linha ilegível onde um espaço a mais no lugar
    errado não aparece em revisão nenhuma; em JSON cada entrada tem aspas em
    volta e um erro de digitação estoura no boot em vez de virar um 403 calado
    meses depois. É o mesmo formato da LLM_PROVIDERS, que já é a lista comprida
    deste .env.
    """
    bruto = (bruto or "").strip()
    # O '{' entra na guarda junto com o '[' para o objeto JSON escrito por
    # engano ({"emails": [...]}) morrer com uma mensagem, em vez de virar três
    # entradas de lixo que não liberam ninguém e não avisam nada.
    if not bruto.startswith(("[", "{")):
        return [parte.strip() for parte in bruto.replace(";", ",").replace("\n", ",").split(",")]

    try:
        entradas = json.loads(bruto)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            f"WHITELIST_EMAILS parece JSON mas não é um JSON válido ({erro}). "
            "Ela precisa ser uma lista JSON em UMA linha só! Veja o .env.example."
        ) from erro

    if not isinstance(entradas, list):
        raise RuntimeError(
            "WHITELIST_EMAILS em JSON precisa ser uma LISTA de textos, "
            'como ["fulano@usp.br", "@turingusp.com"]. Veja o .env.example.'
        )

    for posicao, entrada in enumerate(entradas):
        if not isinstance(entrada, str):
            raise RuntimeError(
                f"WHITELIST_EMAILS[{posicao}] não é texto: cada entrada da lista "
                "é um email ('fulano@usp.br') ou um domínio ('@usp.br')."
            )

    return [entrada.strip() for entrada in entradas]


WHITELIST = Whitelist(config.WHITELIST_EMAILS)


def liberado(user_id: str, email: str = "") -> bool:
    """Esta conta pode usar o chat do USPapo?

    Basta uma das duas portas: uspapo_role 'admin'/'early_access' na tabela
    Perfis, ou o email na WHITELIST_EMAILS.

    A whitelist é conferida primeiro de propósito: ela é um frozenset em
    memória e o cargo é uma consulta ao Supabase, então quem está na lista nem
    chega a pagar a ida à rede.
    """
    if WHITELIST.liberado(email):
        return True
    return obter_role(user_id) in ROLES_CHAT


def e_admin(user_id: str) -> bool:
    """Valida se o usuario e admin do USPapo.

    Só pelo cargo, e a whitelist não entra aqui nem quando está em "todos":
    convidar alguém para o beta não pode dar o painel de analytics junto.
    """
    return obter_role(user_id) == "admin"


def panorama() -> str:
    """Resumo do estado de acesso para o /health, sem vazar email nenhum."""
    return f"uspapo_role + whitelist ({WHITELIST.panorama()})"


def aviso_de_configuracao() -> str:
    """Linha para o boot."""
    return f"uspapo_role na tabela Perfis; {WHITELIST.aviso()}"
