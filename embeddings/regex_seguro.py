"""Execução de regex de limpeza sem travar o pipeline e sem comer conteúdo.

Este módulo existe por causa de uma linha:

    "Como Chegar.*?Sobre.*?Graduação.*?Pós-Graduação.*?Pesquisa.*?Cultura e Extensão"

Cinco `.*?` em sequência, com `re.DOTALL`, e um final que numa página real nunca
casa. Quando o final não casa, cada `.*?` tem que tentar todas as posições
possíveis para cada posição do anterior: o custo é O(n⁵). Medido nesta máquina:
0,0002s com 500 caracteres, 1,2s com 3.000, 6,2s com 4.000. Numa página de 30
mil caracteres não termina — e páginas de 30 mil caracteres são comuns.

Foi isso que travou a execução que "derrubou o banco". O `try/except` que
colocaram em volta na emergência não pegava nada, porque um travamento não é uma
exceção: o processo simplesmente fica lá, e o GitHub Actions mata o job seis
horas depois.

Três defesas, em profundidade:

1. **Validação estática no carregamento.** Padrão com mais de um quantificador
   ilimitado é recusado antes de rodar uma vez. É a defesa que resolve, porque
   impede a regra perigosa de existir.
2. **`DOTALL` deixa de ser padrão.** Antes ele era aplicado a TODAS as regras,
   inclusive às que já tinham `(?=\\n|$)`, o que transformava um delimitador de
   linha em "até o fim do documento". Agora é opt-in por regra.
3. **Watchdog de tempo.** `signal.setitimer` interrompe o match em 250 ms
   (verificado: o motor de regex do CPython responde ao sinal durante o
   backtracking). Estourou, o texto volta intacto e a regra é marcada.

Mais a **trava de proporção**, que é de outra natureza: regra que apaga mais que
sua cota do texto tem a remoção revertida. Não é sobre tempo, é sobre dano, a
regra `Seção Técnica de Informática.*?(?=\\n|$)` rodava rápido e apagou 14.806
caracteres de uma vez, 51% de uma página legítima do IQ.
"""

import re
import signal
from dataclasses import dataclass, field

# Quanto do texto de uma página uma única regra pode remover antes de ser
# considerada suspeita. Calibrável por regra no JSON.
MAX_REMOCAO_PCT = 0.20

# ...mas só a partir de um volume que importe. A trava é sobre DANO, e dano é
# grandeza absoluta: o desastre do IQ foram 14.806 caracteres de uma vez. Um
# rodapé de 130 caracteres é 43% de uma página curta e continua sendo só um
# rodapé: barrá-lo por causa da porcentagem seria a trava atrapalhando o
# trabalho que ela deveria proteger.
MIN_REMOCAO_LIVRE = 400

LIMITE_MS = 250

TEM_ALARME = hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")


class PadraoInseguro(ValueError):
    """Padrão recusado no carregamento, antes de rodar."""


class TempoEsgotado(Exception):
    pass


# ─────────────────────────────────────────────
# Validação estática
# ─────────────────────────────────────────────
def _percorrer(padrao: str):
    """Gera (indice, caractere, dentro_de_classe) ignorando o que está escapado."""
    escapado = False
    classe = False
    for i, c in enumerate(padrao):
        if escapado:
            escapado = False
            continue
        if c == "\\":
            escapado = True
            continue
        if c == "[" and not classe:
            classe = True
            continue
        if c == "]" and classe:
            classe = False
            continue
        yield i, c, classe


def contar_quantificadores_ilimitados(padrao: str) -> int:
    """Conta `.*`, `.+`, `.*?`, `.+?` e classes negadas com `*`/`+`.

    São os construtos que podem varrer o documento inteiro. Um só é
    administrável; dois já multiplicam; cinco é a regra do IRI.
    """
    total = 0
    anterior_curinga = False
    for _, c, classe in _percorrer(padrao):
        if classe:
            continue
        if c in "*+" and anterior_curinga:
            total += 1
            anterior_curinga = False
            continue
        anterior_curinga = c == "."
    # Classe de caracteres com quantificador ilimitado tem o mesmo efeito.
    total += len(re.findall(r"\[[^\]]*\][*+]", padrao))
    return total


def tem_quantificador_aninhado(padrao: str) -> bool:
    """`(algo+)*` e parentes: o caso clássico de explosão exponencial."""
    for grupo in re.findall(r"\(([^()]*)\)[*+]", padrao):
        if re.search(r"[*+]", grupo):
            return True
    return False


def contar_literais(padrao: str) -> int:
    return sum(1 for _, c, classe in _percorrer(padrao) if not classe and c.isalnum())


def validar_padrao(padrao: str) -> list[str]:
    """Levanta `PadraoInseguro` no que é perigoso; devolve avisos do que é só feio."""
    try:
        re.compile(padrao)
    except re.error as erro:
        raise PadraoInseguro(f"regex inválida: {erro}") from erro

    ilimitados = contar_quantificadores_ilimitados(padrao)
    if ilimitados > 1:
        raise PadraoInseguro(
            f"{ilimitados} quantificadores ilimitados em sequência (limite: 1). "
            "É a forma da regra que travou o pipeline: o custo cresce O(n^k) "
            "quando o final não casa. Quebre em regras separadas ou ancore o "
            "trecho do meio."
        )
    if tem_quantificador_aninhado(padrao):
        raise PadraoInseguro("quantificador aninhado (ex.: `(\\w+)*`) — risco exponencial")

    avisos = []
    if contar_literais(padrao) < 8:
        avisos.append("poucos caracteres literais: risco de casar muito mais que o esperado")
    return avisos


# ─────────────────────────────────────────────
# Regra compilada
# ─────────────────────────────────────────────
@dataclass
class RegraCompilada:
    dominio: str
    padrao: str
    regex: re.Pattern
    max_remocao_pct: float = MAX_REMOCAO_PCT
    ocorrencias: int = 0
    chars_removidos: int = 0
    paginas_afetadas: int = 0
    vezes_lenta: int = 0
    vezes_barrada: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.vezes_lenta:
            return "lenta"
        if self.vezes_barrada:
            return "reprovada_por_proporcao"
        if self.ocorrencias == 0:
            return "morta"
        return "ativa"

    def para_relatorio(self) -> dict:
        return {
            "dominio": self.dominio,
            "padrao": self.padrao,
            "status": self.status,
            "ocorrencias": self.ocorrencias,
            "chars_removidos": self.chars_removidos,
            "paginas_afetadas": self.paginas_afetadas,
            "vezes_lenta": self.vezes_lenta,
            "vezes_barrada": self.vezes_barrada,
            "avisos": self.avisos,
        }


def compilar(dominio: str, especificacao) -> RegraCompilada:
    """Aceita string crua (formato v1) ou dict (v2), para o JSON antigo carregar."""
    if isinstance(especificacao, str):
        especificacao = {"padrao": especificacao}

    padrao = especificacao["padrao"]
    letras = especificacao.get("flags", "i")

    flags = 0
    if "i" in letras:
        flags |= re.IGNORECASE
    if "m" in letras:
        flags |= re.MULTILINE
    if "s" in letras:  # DOTALL: agora só quando a regra pede
        flags |= re.DOTALL

    avisos = validar_padrao(padrao)
    return RegraCompilada(
        dominio=dominio,
        padrao=padrao,
        regex=re.compile(padrao, flags),
        max_remocao_pct=float(especificacao.get("max_remocao_pct", MAX_REMOCAO_PCT * 100)) / 100
        if especificacao.get("max_remocao_pct", None) is not None
        else MAX_REMOCAO_PCT,
        avisos=avisos,
    )


# ─────────────────────────────────────────────
# Execução protegida
# ─────────────────────────────────────────────
def _estourou(_sinal, _quadro):
    raise TempoEsgotado()


def aplicar_com_limite(regra: RegraCompilada, texto: str, limite_ms: int = LIMITE_MS) -> str:
    """Aplica uma regra. Devolve o texto original se algo der errado.

    O watchdog só funciona no processo principal e em POSIX. O `clean_data.py`
    roda como processo próprio, então vale; se um dia a limpeza for paralelizada
    com threads, isto vira no-op silencioso e a validação estática passa a ser a
    única defesa — nesse caso, troque por `ProcessPoolExecutor` + `terminate()`.
    """
    if not texto:
        return texto

    anterior = None
    if TEM_ALARME:
        anterior = signal.signal(signal.SIGALRM, _estourou)
        signal.setitimer(signal.ITIMER_REAL, limite_ms / 1000)

    try:
        novo, quantos = regra.regex.subn("", texto)
    except TempoEsgotado:
        regra.vezes_lenta += 1
        print(
            f"      [REGEX LENTA] '{regra.padrao[:60]}' passou de {limite_ms}ms. "
            "Texto mantido intacto."
        )
        return texto
    except re.error as erro:
        regra.vezes_lenta += 1
        print(f"      [REGEX ERRO] '{regra.padrao[:60]}': {erro}")
        return texto
    finally:
        if TEM_ALARME:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if anterior is not None:
                signal.signal(signal.SIGALRM, anterior)

    if quantos == 0:
        return texto

    removido = len(texto) - len(novo)
    if removido > MIN_REMOCAO_LIVRE and removido / len(texto) > regra.max_remocao_pct:
        regra.vezes_barrada += 1
        print(
            f"      [REGEX BARRADA] '{regra.padrao[:60]}' removeria {removido} chars "
            f"({100 * removido / len(texto):.0f}% da página). Remoção revertida."
        )
        return texto

    regra.ocorrencias += quantos
    regra.chars_removidos += removido
    regra.paginas_afetadas += 1
    return novo
