"""Registro de ferramentas que o modelo pode chamar.

Cada módulo de ferramenta cria o seu `Registro` e decora as próprias funções
nele; o entrypoint escolhe qual registro entregar ao servidor. É isso que deixa
o backend real (Pinecone) e o backend falso (documentos canned) usarem o MESMO
motor sem uma linha de código duplicada.
"""

from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable


# ─────────────────────────────────────────────
# Higiene dos argumentos que o modelo manda
# ─────────────────────────────────────────────
# Mora aqui, e não num módulo de ferramenta, porque toda ferramenta precisa
# disso: o modelo erra a caixa, o acento e o tipo do argumento em qualquer uma.
def normalizar(texto) -> str:
    """Baixa a caixa, tira acento e apara: 'Física' e 'fisica' viram a mesma coisa."""
    bruto = unicodedata.normalize("NFKD", str(texto).strip().lower())
    return "".join(c for c in bruto if not unicodedata.combining(c))


# Palavras que aparecem no nome das coisas e não distinguem nada: quem procura
# "engenharia de computação" e quem procura "engenharia da computação" quer o
# mesmo curso, e o "de/da" é a única diferença entre as duas buscas.
LIGACOES = frozenset(
    "de da do das dos e em no na nos nas a o as os um uma com para".split()
)


def palavras(texto) -> list[str]:
    """As palavras que importam num pedido: sem acento, sem pontuação, sem ligação.

    Hífen, barra e ponto viram separador, e não caractere: 'segunda-feira',
    'segunda feira' e 'segunda.feira' têm que dar na mesma lista.
    """
    limpo = "".join(c if c.isalnum() else " " for c in normalizar(texto))
    return [p for p in limpo.split() if p not in LIGACOES]


def casa(pedido, alvo) -> bool:
    """O `pedido` casa com o `alvo` se cada palavra dele aparece lá dentro.

    Cada palavra do pedido precisa ser uma palavra do alvo ou o começo de uma
    ('eng comp' casa com 'engenharia de computação'). A ordem não importa e as
    ligações somem, que são as duas coisas que o aluno mais varia ao escrever.

    Deliberadamente não é busca aproximada: sem erro de digitação tolerado, um
    pedido que casa casa por um motivo explicável. Chutar o curso errado é bem
    pior do que dizer que não encontrou — o aluno pode reescrever, mas não tem
    como saber que a grade que ele leu era de outro curso.
    """
    pedidas = palavras(pedido)
    if not pedidas:
        return False

    disponiveis = palavras(alvo)
    return all(
        any(tinha.startswith(procurada) for tinha in disponiveis)
        for procurada in pedidas
    )


def em_lista(valor, padrao: list[str]) -> list[str]:
    """Aceita None, string ou lista e devolve sempre uma lista de strings.

    Modelo manda string onde o schema pede lista com frequência — e às vezes
    manda "central, fisica" numa string só.
    """
    if valor is None:
        return list(padrao)

    if isinstance(valor, str):
        itens = valor.split(",")
    elif isinstance(valor, (list, tuple, set)):
        itens = [item for valor_bruto in valor for item in str(valor_bruto).split(",")]
    else:
        itens = [str(valor)]

    limpos = [item.strip() for item in itens if str(item).strip()]
    return limpos or list(padrao)


# ─────────────────────────────────────────────
# Memo por TTL, entre perguntas
# ─────────────────────────────────────────────
# O `memo` do `Registro.rodar` só vale dentro de uma pergunta. Site externo é
# lento e o dado dele muda em dias, não em segundos: sem isto, cada aluno paga
# uma ida à rede pelo mesmo fato. Mora aqui, e não num módulo de ferramenta,
# porque toda ferramenta que sai para a rede precisa da mesma coisa.
_CACHE: dict[tuple, tuple[float, object]] = {}


def cache(chave: tuple, ttl: int, produzir):
    """Memo por TTL, compartilhado por todas as ferramentas.

    A `chave` é uma tupla e o primeiro elemento deve identificar quem está
    guardando: o dicionário é um só para o backend inteiro.

    Sem lock: atribuição em dict é atômica e dois workers produzindo o mesmo
    valor ao mesmo tempo é desperdício, não erro.
    """
    guardado = _CACHE.get(chave)
    if guardado and (time.monotonic() - guardado[0]) < ttl:
        return guardado[1]

    valor = produzir()
    _CACHE[chave] = (time.monotonic(), valor)
    return valor


@dataclass(frozen=True)
class Ferramenta:
    """Uma ferramenta que o modelo pode chamar.

    `executar` recebe os argumentos do modelo por nome e devolve
    (texto_para_o_modelo, fontes). Ferramenta que não tem fonte: um cálculo,
    por exemplo, devolve lista vazia.

    Os dois canais são disjuntos de propósito: a URL vai SÓ na lista de fontes,
    nunca no texto. O frontend já as renderiza embaixo da resposta, e ver link
    no resultado da ferramenta faz o modelo copiar uma lista de links por
    conta própria — duplicando o que o site mostra.
    """

    nome: str
    descricao: str
    parametros: dict  # JSON Schema dos argumentos
    executar: Callable[..., tuple[str, list[str]] | "RespostaFerramenta"]


@dataclass(frozen=True)
class RespostaFerramenta:
    """Resposta pública e, opcionalmente, fatos estruturados para apresentação.

    O desempacotamento em ``texto, fontes`` continua funcionando em todo o
    código existente. ``dados_publicos`` é um canal interno: ele permite que a
    camada de conversa peça a uma LLM para verbalizar os fatos sem precisar
    reconstruí-los a partir da prosa de fallback.
    """

    texto: str
    fontes: list[str]
    dados_publicos: dict[str, Any] | None = None

    def __iter__(self):
        yield self.texto
        yield self.fontes


@dataclass(frozen=True)
class ResultadoExecucao:
    """Resultado de uma tool call com status fora do conteúdo textual.

    O objeto continua desempacotável como ``resultado, fontes, args`` para não
    quebrar os chamadores existentes. ``sucesso`` fica separado porque inferir
    falha pelo texto faria uma mensagem de validação parecer uma resposta de
    transporte pronta para o aluno.
    """

    resultado: str
    fontes: list[str]
    args: dict
    sucesso: bool
    dados_publicos: dict[str, Any] | None = None

    def __iter__(self):
        yield self.resultado
        yield self.fontes
        yield self.args


class Registro:
    """As ferramentas disponíveis para uma instância do backend."""

    def __init__(self):
        self._ferramentas: dict[str, Ferramenta] = {}
        self._derivados: dict = {}

    # ─────────────────────────────────────────────
    # Registro
    # ─────────────────────────────────────────────
    def ferramenta(self, nome: str, descricao: str, parametros: dict):
        """Registra a função decorada como ferramenta disponível ao modelo.

        O schema fica junto da implementação: adicionar uma ferramenta nova é
        escrever uma função decorada, sem tocar em mais nada. Cada ferramenta
        valida os próprios argumentos e devolve texto, mas nunca levanta.
        """

        def registrar(fn):
            if nome in self._ferramentas:
                raise RuntimeError(f"Ferramenta '{nome}' foi registrada duas vezes.")
            self._ferramentas[nome] = Ferramenta(nome, descricao, parametros, fn)
            self._derivados.clear()  # schemas/nomes/custo mudaram
            return fn

        return registrar

    # ─────────────────────────────────────────────
    # Derivados: nada aqui precisa saber quais ferramentas existem
    # ─────────────────────────────────────────────
    # Calculados sob demanda, e não no import: as ferramentas são registradas
    # por outro módulo, depois que este aqui já foi carregado.
    @property
    def schemas(self) -> list[dict]:
        """As ferramentas no formato que a API espera em `tools`."""
        if "schemas" not in self._derivados:
            self._derivados["schemas"] = [
                {
                    "type": "function",
                    "function": {
                        "name": f.nome,
                        "description": f.descricao,
                        "parameters": f.parametros,
                    },
                }
                for f in self._ferramentas.values()
            ]
        return self._derivados["schemas"]

    @property
    def nomes(self) -> set[str]:
        return set(self._ferramentas)

    @property
    def json_schemas(self) -> str:
        """Os schemas serializados, para estimar quanto custam em tokens."""
        if "json" not in self._derivados:
            self._derivados["json"] = json.dumps(self.schemas, ensure_ascii=False)
        return self._derivados["json"]

    def propriedades(self, nome: str) -> dict:
        """O `properties` do JSON Schema de uma ferramenta, para tipar argumentos."""
        ferr = self._ferramentas.get(nome)
        return (ferr.parametros.get("properties") if ferr else None) or {}

    def executar_direto(self, nome: str, **args) -> tuple[str, list[str]]:
        """Executa uma ferramenta conhecida sem passar pela escolha do modelo.

        É usado apenas pelo roteador determinístico para intenções inequívocas.
        Mantém a mesma implementação e o mesmo contrato da tool call normal.
        """
        ferr = self._ferramentas.get(nome)
        if ferr is None:
            raise KeyError(nome)
        return ferr.executar(**args)

    # ─────────────────────────────────────────────
    # Execução
    # ─────────────────────────────────────────────
    def rodar(
        self,
        chamada: dict,
        memo: dict,
        extras_internos: dict | None = None,
    ) -> ResultadoExecucao:
        """Executa uma tool call. Nunca levanta: falha vira texto para o modelo ler."""
        try:
            args = json.loads(chamada["args"] or "{}")
        except json.JSONDecodeError:
            return ResultadoExecucao(
                "Os argumentos não são um JSON válido. Chame a ferramenta de novo.",
                [],
                {},
                False,
            )

        if not isinstance(args, dict):
            return ResultadoExecucao(
                "Os argumentos precisam ser um objeto JSON.", [], {}, False
            )

        # Argumentos iniciados por sublinhado pertencem ao backend e nunca ao
        # modelo. Além disso, qualquer chave fornecida em ``extras_internos`` é
        # autoritativa: removê-la dos argumentos públicos evita tanto colisão de
        # kwargs quanto uma tentativa de sobrescrever contexto confiável.
        extras_internos = extras_internos or {}
        reservados = set(extras_internos)
        args = {
            chave: valor
            for chave, valor in args.items()
            if not str(chave).startswith("_") and chave not in reservados
        }

        ferr = self._ferramentas.get(chamada["nome"])
        if ferr is None:
            return ResultadoExecucao(
                f"Ferramenta desconhecida: {chamada['nome']}.", [], args, False
            )

        # O nome entra na chave do cache: sem ele, duas ferramentas que aceitem
        # um argumento de mesmo nome leriam o resultado cacheado uma da outra.
        chave = (
            ferr.nome,
            json.dumps(args, sort_keys=True, ensure_ascii=False),
            json.dumps(extras_internos, sort_keys=True, ensure_ascii=False),
        )

        if chave not in memo:
            try:
                memo[chave] = ferr.executar(**args, **extras_internos)
            except TypeError as erro:
                # Argumento a mais ou faltando: devolve para o modelo se corrigir.
                return ResultadoExecucao(
                    f"Argumentos inválidos para '{ferr.nome}': {erro}",
                    [],
                    args,
                    False,
                )
            except Exception as erro:
                print(f"[ferramenta] '{ferr.nome}' falhou: {type(erro).__name__}: {erro}")
                return ResultadoExecucao(
                    "A ferramenta falhou por um erro temporário. Avise o aluno.",
                    [],
                    args,
                    False,
                )

        bruto = memo[chave]
        resultado, fontes = bruto
        dados_publicos = getattr(bruto, "dados_publicos", None)
        return ResultadoExecucao(
            resultado, fontes, args, True, dados_publicos=dados_publicos
        )
