"""Limpeza do content: raciocínio e tool calls que vieram inline.

Não existe campo padronizado para o raciocínio: a DeepSeek manda
"reasoning_content", a Groq e a OpenRouter mandam "reasoning", e vários modelos
abertos simplesmente cospem <think>...</think> no meio do content.
"""

CAMPOS_RACIOCINIO = ("reasoning_content", "reasoning", "reasoning_text")

# Tags que alguns modelos cospem DENTRO do content em vez de usar os campos
# estruturados da API. Cada entrada é (abre, fecha, transmitir_ao_vivo).
# O `ao vivo` diz se o miolo pode ser repassado token a token (raciocínio) ou
# se precisa ser bufferizado até fechar para virar uma coisa só (JSON de tool
# call). Suportar um formato novo é acrescentar uma linha aqui.
TAGS_CONTEUDO = {
    "pensando": ("<think>", "</think>", True),
    "ferramenta_inline": ("<tool_call>", "</tool_call>", False),
    "ferramenta_xml": ("<function=", "</function>", False),
}

# Rótulos que viram tool call em vez de texto no chat. O valor é o prefixo que
# o separador comeu ao abrir a tag e que o parser precisa de volta.
ROTULOS_FERRAMENTA = {"ferramenta_inline": "", "ferramenta_xml": "<function="}


def extrair_raciocinio(delta) -> str:
    """Pesca o token de raciocínio do delta, seja lá como o provedor o chame."""
    extra = getattr(delta, "model_extra", None) or {}
    for campo in CAMPOS_RACIOCINIO:
        valor = getattr(delta, campo, None) or extra.get(campo)
        if isinstance(valor, str) and valor:
            return valor
    return ""


class SeparadorConteudo:
    """Separa do content as tags que o modelo emitiu inline.

    As tags chegam partidas entre chunks ("<too" + "l_call>"), então seguramos
    no buffer o pedaço do fim que ainda pode ser o começo de uma tag.
    """

    def __init__(self):
        self._buffer = ""
        self._rotulo = "texto"   # bloco em que estamos agora
        self._acumulado = ""     # miolo dos blocos que não vão ao vivo

    def _fecha_atual(self) -> str:
        return TAGS_CONTEUDO[self._rotulo][1]

    def _tamanho_tail(self) -> int:
        """Quantos chars do fim do buffer ainda podem virar uma tag."""
        if self._rotulo == "texto":
            alvos = [abre for abre, _, _ in TAGS_CONTEUDO.values()]
        else:
            alvos = [self._fecha_atual()]

        maior = 0
        for alvo in alvos:
            for tamanho in range(min(len(alvo) - 1, len(self._buffer)), 0, -1):
                if alvo.startswith(self._buffer[-tamanho:]):
                    maior = max(maior, tamanho)
                    break
        return maior

    def _emitir(self, saida: list, trecho: str, fechou: bool) -> None:
        """Entrega o miolo do bloco atual conforme a política da tag."""
        if TAGS_CONTEUDO[self._rotulo][2]:      # ao vivo
            if trecho:
                saida.append((self._rotulo, trecho))
            return

        self._acumulado += trecho
        if fechou:
            saida.append((self._rotulo, self._acumulado))
            self._acumulado = ""

    def processar(self, pedaco: str) -> list[tuple[str, str]]:
        self._buffer += pedaco
        saida: list[tuple[str, str]] = []

        while True:
            if self._rotulo == "texto":
                # abre no ponto mais próximo, qualquer que seja a tag
                achado = None
                for rotulo, (abre, _, _) in TAGS_CONTEUDO.items():
                    posicao = self._buffer.find(abre)
                    if posicao != -1 and (achado is None or posicao < achado[0]):
                        achado = (posicao, rotulo, abre)
                if achado is None:
                    break

                posicao, rotulo, abre = achado
                if posicao:
                    saida.append(("texto", self._buffer[:posicao]))
                self._buffer = self._buffer[posicao + len(abre):]
                self._rotulo = rotulo
                self._acumulado = ""
            else:
                fecha = self._fecha_atual()
                posicao = self._buffer.find(fecha)
                if posicao == -1:
                    break

                self._emitir(saida, self._buffer[:posicao], fechou=True)
                self._buffer = self._buffer[posicao + len(fecha):]
                self._rotulo = "texto"

        seguro = len(self._buffer) - self._tamanho_tail()
        if seguro > 0:
            trecho, self._buffer = self._buffer[:seguro], self._buffer[seguro:]
            if self._rotulo == "texto":
                saida.append(("texto", trecho))
            else:
                self._emitir(saida, trecho, fechou=False)

        return saida

    def finalizar(self) -> list[tuple[str, str]]:
        resto, self._buffer = self._buffer, ""

        if self._rotulo == "texto":
            return [("texto", resto)] if resto else []

        if TAGS_CONTEUDO[self._rotulo][2]:
            return [(self._rotulo, resto)] if resto else []

        # Bloco bufferizado que nunca fechou: entregamos assim mesmo, porque
        # uma tool call cortada no fim ainda costuma ter nome e argumentos
        # legíveis. Quem recebe é o parser, nunca o chat.
        incompleto, self._acumulado = self._acumulado + resto, ""
        if not incompleto.strip():
            return []

        print(f"[conteudo] bloco '{self._rotulo}' não fechou: {incompleto[:120]}")
        return [(self._rotulo, incompleto)]
