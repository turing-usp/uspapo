"""Orçamento de contexto: o teto do que é enviado ao modelo por pergunta.

Não importa o tamanho da conversa acumulada no frontend: o que não couber é
descartado, do turno mais antigo para o mais novo.
"""

from uspapo import config
from uspapo.prompt import montar_prompt_sistema


def estimar_tokens(texto: str) -> int:
    """Estimativa por caracteres.

    Não há tokenizer instalado e a cadeia de provedores é heterogênea (Qwen,
    gpt-oss, DeepSeek), então nenhuma contagem exata valeria para todos. A razão
    é conservadora de propósito: sobrar contexto é bem melhor do que a API
    recusar a requisição inteira.
    """
    return int(len(texto) / config.CHARS_POR_TOKEN) + 1


def custo_mensagem(mensagem: dict) -> int:
    """Tokens de uma mensagem, contando o enquadramento de role e formato."""
    custo = 4 + estimar_tokens(str(mensagem.get("content") or ""))

    for chamada in mensagem.get("tool_calls") or []:
        funcao = chamada.get("function", {})
        custo += estimar_tokens(funcao.get("name", "") + funcao.get("arguments", ""))

    return custo


def normalizar_historico(bruto: object) -> list[dict]:
    """Filtra os turnos anteriores que vieram do frontend.

    Item torto é descartado calado: localStorage estragado não pode impedir o
    aluno de fazer a pergunta de agora.
    """
    if not isinstance(bruto, list):
        return []

    limpo = []
    for item in bruto[-config.MAX_MENSAGENS_HISTORICO:]:
        if not isinstance(item, dict):
            continue

        pergunta = str(item.get("pergunta") or "").strip()
        resposta = str(item.get("resposta") or "").strip()
        if pergunta and resposta:
            limpo.append({"pergunta": pergunta, "resposta": resposta})

    return limpo


class Orcamento:
    """Monta e poda a lista de mensagens dentro do teto de tokens.

    Recebe o registro de ferramentas porque o schema delas vai em toda
    requisição e ocupa contexto como qualquer outra coisa.
    """

    def __init__(
        self,
        registro,
        max_tokens: int = config.MAX_TOKENS_CONTEXTO,
        reserva: int = config.RESERVA_FERRAMENTAS,
    ):
        self.max_tokens = max_tokens
        self.reserva = reserva
        self.custo_ferramentas = estimar_tokens(registro.json_schemas)

    def montar(self, pergunta: str, historico: list[dict]) -> tuple[list[dict], int]:
        """Monta as messages cabendo no orçamento.

        Devolve também o índice onde o turno de agora começa: dali para a frente
        as mensagens são intocáveis (a pergunta e o par assistant/tool das
        ferramentas), e só o prefixo de histórico pode ser podado mais tarde.
        """
        sistema = {"role": "system", "content": montar_prompt_sistema()}
        atual = {"role": "user", "content": pergunta}

        disponivel = (
            self.max_tokens
            - custo_mensagem(sistema)
            - self.custo_ferramentas
            - self.reserva
        )

        # A pergunta de agora entra sempre. Se ela sozinha estourar o orçamento,
        # é ela que encolhe: sem pergunta não há o que responder.
        if custo_mensagem(atual) > disponivel:
            atual["content"] = pergunta[
                : max(int(disponivel * config.CHARS_POR_TOKEN), 500)
            ]

        sobra = disponivel - custo_mensagem(atual)
        anteriores: list[dict] = []

        # Do turno mais recente para o mais antigo: o fim da conversa é o que
        # importa para entender a pergunta atual.
        for turno in reversed(historico):
            par = [
                {"role": "user", "content": turno["pergunta"]},
                {"role": "assistant", "content": turno["resposta"]},
            ]
            custo = sum(custo_mensagem(mensagem) for mensagem in par)

            # Para no primeiro que não cabe em vez de continuar procurando um
            # menor: buraco no meio da conversa confunde mais do que ajuda.
            if custo > sobra:
                break

            sobra -= custo
            anteriores[:0] = par

        mensagens = [sistema] + anteriores + [atual]
        return mensagens, len(mensagens) - 1

    def podar(self, mensagens: list[dict], inicio_turno: int) -> int:
        """Descarta turnos antigos até o total caber de novo no orçamento.

        Roda entre as rodadas de ferramenta, quando os resultados já entraram na
        lista. Mexe só no prefixo de histórico: tirar uma mensagem 'tool' ou o
        'assistant' que a chamou deixa um tool_call_id órfão, e aí o provedor
        recusa a requisição inteira.
        """
        total = self.custo_ferramentas + sum(
            custo_mensagem(mensagem) for mensagem in mensagens
        )

        # O índice 0 é o prompt de sistema; o histórico vai dali até inicio_turno.
        while total > self.max_tokens and inicio_turno > 1:
            # Os pares saem juntos, para a conversa nunca começar por uma
            # resposta sem a pergunta que a gerou.
            removidas = mensagens[1:3]
            del mensagens[1:3]
            inicio_turno -= len(removidas)
            total -= sum(custo_mensagem(mensagem) for mensagem in removidas)

        return inicio_turno
