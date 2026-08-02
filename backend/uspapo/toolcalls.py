"""Tudo que vira uma tool call: os parsers do formato inline e o coletor.

Nem todo runtime tem parser de tool call. Quando não tem, o modelo cospe a
chamada como texto — em JSON (formato Hermes) ou em XML — e é aqui que isso
volta a ser uma chamada estruturada.
"""

import json
import re
from typing import Iterator

FUNCAO_XML = re.compile(r"<function=([^>\s]+)\s*>(.*?)(?:</function>|\Z)", re.S)
PARAMETRO_XML = re.compile(r"<parameter=([^>\s]+)\s*>(.*?)(?:</parameter>|\Z)", re.S)


def converter_por_schema(registro, nome: str, args: dict[str, str]) -> dict:
    """Tipa os argumentos do formato XML, onde tudo chega como string.

    O JSON Schema da ferramenta diz o tipo esperado de cada campo; o que não
    converter continua string e a ferramenta decide o que fazer com ele.
    """
    propriedades = registro.propriedades(nome)
    convertidos: dict[str, object] = {}

    for chave, valor in args.items():
        tipo = (propriedades.get(chave) or {}).get("type")
        try:
            if tipo == "integer":
                convertidos[chave] = int(valor)
            elif tipo == "number":
                convertidos[chave] = float(valor)
            elif tipo == "boolean":
                convertidos[chave] = valor.lower() in ("true", "1", "sim", "yes")
            elif tipo in ("object", "array"):
                convertidos[chave] = json.loads(valor)
            else:
                convertidos[chave] = valor
        except (TypeError, ValueError, json.JSONDecodeError):
            convertidos[chave] = valor

    return convertidos


def ler_tool_calls(registro, bruto: str) -> list[tuple[str, str]]:
    """Lê um bloco de tool call inline nos formatos que os modelos usam.

    Devolve pares (nome, argumentos como string JSON), lista vazia se o bloco
    não for reconhecível. Nunca levanta: formato estranho é caso esperado aqui.
    """
    texto = bruto.strip()
    if not texto:
        return []

    # Formato Hermes (Qwen, Mistral): um objeto JSON solto, ou uma lista deles
    # quando o modelo pede duas coisas de uma vez. "name"/"arguments" é o mais
    # comum; "parameters" aparece em alguns Llama. Os argumentos podem vir como
    # objeto ou já como string JSON.
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        dados = None

    chamadas = []
    for item in dados if isinstance(dados, list) else [dados]:
        if not isinstance(item, dict):
            continue

        nome = str(item.get("name") or item.get("nome") or "")
        if not nome:
            continue

        args = item.get("arguments", item.get("parameters", {}))
        chamadas.append(
            (nome, args if isinstance(args, str) else json.dumps(args, ensure_ascii=False))
        )

    if chamadas:
        return chamadas

    # Formato XML. Pode trazer mais de uma função no mesmo bloco.
    for achado in FUNCAO_XML.finditer(texto):
        nome = achado.group(1).strip()
        crus = {
            chave.strip(): valor.strip()
            for chave, valor in PARAMETRO_XML.findall(achado.group(2))
        }
        args = converter_por_schema(registro, nome, crus)
        chamadas.append((nome, json.dumps(args, ensure_ascii=False)))

    if not chamadas:
        print(f"[ferramenta] tool call inline em formato desconhecido, ignorada: {texto[:200]}")

    return chamadas


class ColetorDeChamadas:
    """Junta as tool calls de uma rodada, venham da API ou do texto.

    Guarda a contabilidade chata (o nome que chega picotado, o índice de cada
    chamada, o que já foi anunciado para a UI) fora do laço da conversa.
    """

    def __init__(self, registro):
        self._registro = registro
        self._nomes = registro.nomes
        self._pendentes: dict[int, dict] = {}
        self._anunciadas: set[int] = set()

    def __bool__(self) -> bool:
        """Houve pedido de ferramenta nesta rodada?"""
        return bool(self._pendentes)

    def _anunciar(self, indice: int, nome: str) -> Iterator[dict]:
        if indice in self._anunciadas:
            return
        self._anunciadas.add(indice)
        yield {"tipo": "ferramenta", "estado": "inicio", "indice": indice, "nome": nome}

    def absorver_delta(self, tc) -> Iterator[dict]:
        """Acumula um pedaço de tool call vindo estruturado da API."""
        slot = self._pendentes.setdefault(tc.index, {"id": "", "nome": "", "args": ""})

        if tc.id:
            slot["id"] = tc.id
        if tc.function and tc.function.name:
            slot["nome"] += tc.function.name
        if tc.function and tc.function.arguments:
            slot["args"] += tc.function.arguments

        # O nome chega picotado ("buscar_" + "documentos"), então anunciamos
        # assim que o acumulado casa com uma ferramenta conhecida: ainda é cedo
        # (os argumentos nem fecharam) e a UI já recebe o rótulo certo para
        # "Pesquisando nos documentos".
        if slot["nome"] in self._nomes:
            yield from self._anunciar(tc.index, slot["nome"])

    def absorver_inline(self, bruto: str) -> Iterator[dict]:
        """Converte um bloco que veio no texto em chamada de verdade."""
        for nome, args_str in ler_tool_calls(self._registro, bruto):
            if not nome:
                continue

            indice = (max(self._pendentes) + 1) if self._pendentes else 0
            self._pendentes[indice] = {"id": "", "nome": nome, "args": args_str}
            yield from self._anunciar(indice, nome)

    def fechar(self, rodada: int) -> list[dict]:
        """As chamadas da rodada, em ordem estável e com id garantido."""
        chamadas = []

        for posicao, indice in enumerate(sorted(self._pendentes)):
            chamada = self._pendentes[indice]
            chamada["indice"] = indice  # casa com o evento "inicio"
            # Alguns provedores não mandam id; precisamos de um para casar a
            # resposta da ferramenta com a chamada.
            chamada["id"] = chamada["id"] or f"call_{rodada}_{posicao}"
            chamadas.append(chamada)

        return chamadas
