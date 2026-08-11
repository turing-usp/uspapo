"""Quem pode usar o USPapo: a whitelist de emails do .env.

O contas.py estabelece QUEM é quem pergunta; aqui se decide se essa pessoa pode.
São perguntas diferentes e por isso moram em módulos diferentes. Misturar as
duas é o que tornaria o contas.py difícil de ler.

A lista inteira cabe numa variável de ambiente porque o beta fechado é isso
mesmo: uma turma pequena, que muda por deploy e não por tela de admin. Quando
isso deixar de ser verdade o lugar dela é uma tabela no Supabase, e o que muda
aqui é só de onde a Whitelist é construída.

Três formas de escrever a WHITELIST_EMAILS:

    todos                       qualquer conta logada entra (whitelist desligada)
    ninguem                     ninguém entra, nem quem está logado
    a@usp.br, @turingusp.com    só estes; a entrada com @ na frente vale o
                                domínio inteiro

Ausente ou vazia vale "todos": um valor em branco por acidente não pode derrubar
o /chat inteiro, e "todos" aqui já significa "qualquer conta autenticada", nunca
o mundo aberto — o login continua obrigatório de qualquer jeito.
"""

from uspapo import config

TODOS = "todos"
NINGUEM = "ninguem"
LISTA = "lista"

# Aceitos com e sem acento: o .env é um arquivo de texto sem garantia nenhuma de
# encoding, e quem escreve "ninguém" quer dizer a mesma coisa que "ninguem".
_SINONIMOS_TODOS = {"todos", "todas", "tudo", "all", "*"}
_SINONIMOS_NINGUEM = {"ninguem", "ninguém", "nenhum", "nenhuma", "none"}


class Whitelist:
    """A lista já interpretada: o parse acontece uma vez, na construção.

    É uma classe e não um punhado de constantes de módulo para poder existir mais
    de uma na mesma execução. Sem isso, testar dez configurações diferentes
    exigiria recarregar o módulo dez vezes.
    """

    def __init__(self, bruto: str) -> None:
        itens = {
            parte.strip().lower()
            for parte in (bruto or "").replace(";", ",").replace("\n", ",").split(",")
        }
        itens.discard("")

        # "todos" ganha de qualquer coisa na mesma linha: quem escreveu
        # "todos, fulano@usp.br" quis abrir, e a lista ao lado é sobra de edição.
        if not itens or itens & _SINONIMOS_TODOS:
            self.modo, self.entradas = TODOS, frozenset()
        elif itens <= _SINONIMOS_NINGUEM:
            self.modo, self.entradas = NINGUEM, frozenset()
        else:
            self.modo = LISTA
            self.entradas = frozenset(itens - _SINONIMOS_NINGUEM)

    def liberado(self, email: str) -> bool:
        """Este email pode perguntar?

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
        """O estado da portaria para o /health, sem vazar os emails da lista."""
        if self.modo != LISTA:
            return self.modo
        return f"{len(self.entradas)} entrada{'s' if len(self.entradas) != 1 else ''}"

    def aviso(self) -> str:
        """Uma linha para o boot dizer quem está entrando hoje."""
        if self.modo == TODOS:
            return "qualquer conta logada pode perguntar (WHITELIST_EMAILS=todos)."
        if self.modo == NINGUEM:
            return "o /chat está fechado para todo mundo (WHITELIST_EMAILS=ninguem)."

        aviso = f"{self.panorama()} na whitelist."
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


ROLES_AUTORIZADAS = {"admin", "membro", "early_access"}


def liberado(email: str, role: str = "") -> bool:
    """Valida se o usuário pode perguntar no chat.
    
    Liberado EXCLUSIVAMENTE para contas que possuam role autorizada:
    - 'admin'
    - 'membro'
    - 'early_access'
    
    Contas sem uma dessas roles são bloqueadas por padrão.
    """
    role = (role or "").strip().lower()
    if role in ROLES_AUTORIZADAS:
        return True
    return False


def panorama() -> str:
    return WHITELIST.panorama()


def aviso_de_configuracao() -> str:
    return WHITELIST.aviso()
