"""Registro de ferramentas que o modelo pode chamar.

Cada módulo de ferramenta cria o seu `Registro` e decora as próprias funções
nele; o entrypoint escolhe qual registro entregar ao servidor. É isso que deixa
o backend real (Pinecone) e o backend falso (documentos canned) usarem o MESMO
motor sem uma linha de código duplicada.
"""

import json
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Ferramenta:
    """Uma ferramenta que o modelo pode chamar.

    `executar` recebe os argumentos do modelo por nome e devolve
    (texto_para_o_modelo, fontes). Ferramenta que não tem fonte: um cálculo,
    por exemplo, devolve lista vazia.
    """

    nome: str
    descricao: str
    parametros: dict  # JSON Schema dos argumentos
    executar: Callable[..., tuple[str, list[str]]]


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

    # ─────────────────────────────────────────────
    # Execução
    # ─────────────────────────────────────────────
    def rodar(self, chamada: dict, memo: dict) -> tuple[str, list[str], dict]:
        """Executa uma tool call. Nunca levanta: falha vira texto para o modelo ler."""
        try:
            args = json.loads(chamada["args"] or "{}")
        except json.JSONDecodeError:
            return "Os argumentos não são um JSON válido. Chame a ferramenta de novo.", [], {}

        if not isinstance(args, dict):
            return "Os argumentos precisam ser um objeto JSON.", [], {}

        ferr = self._ferramentas.get(chamada["nome"])
        if ferr is None:
            return f"Ferramenta desconhecida: {chamada['nome']}.", [], args

        # O nome entra na chave do cache: sem ele, duas ferramentas que aceitem
        # um argumento de mesmo nome leriam o resultado cacheado uma da outra.
        chave = (ferr.nome, json.dumps(args, sort_keys=True, ensure_ascii=False))

        if chave not in memo:
            try:
                memo[chave] = ferr.executar(**args)
            except TypeError as erro:
                # Argumento a mais ou faltando: devolve para o modelo se corrigir.
                return f"Argumentos inválidos para '{ferr.nome}': {erro}", [], args
            except Exception as erro:
                print(f"[ferramenta] '{ferr.nome}' falhou: {type(erro).__name__}: {erro}")
                return "A ferramenta falhou por um erro temporário. Avise o aluno.", [], args

        resultado, fontes = memo[chave]
        return resultado, fontes, args
