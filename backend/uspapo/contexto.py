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


def cortar(texto: str, teto_tokens: int) -> str:
    """Corta um texto que não cabe no orçamento, avisando que foi cortado.

    O aviso não é gentileza: uma tabela truncada em silêncio é lida pelo modelo
    como a lista completa, e ele responde "o curso tem 8 disciplinas" olhando
    para as 8 que sobraram de 40.
    """
    if estimar_tokens(texto) <= teto_tokens:
        return texto

    limite = max(int(teto_tokens * config.CHARS_POR_TOKEN), 200)
    return (
        texto[:limite].rstrip()
        + "\n\n[Resultado cortado por tamanho: havia mais conteúdo além deste "
        "ponto. Diga isso ao aluno e ofereça uma consulta mais específica.]"
    )


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

    def reserva_para(self, teto: int) -> int:
        """O espaço guardado para os resultados de ferramenta, dado o teto.

        São duas perguntas diferentes, e vale a menor resposta. RESERVA_
        FERRAMENTAS diz quanto as ferramentas PRECISAM: uma grade curricular
        completa dá ~2.600 tokens, o cardápio da semana dos quatro bandejões
        ~2.300 — e isso é propriedade delas, não do modelo. O terço do teto diz
        quanto DÁ para pagar: num orçamento de 6.000 uma reserva de 4.000 não
        deixaria espaço nem para a pergunta do aluno.

        Na prática o valor configurado manda de 12.000 para cima (o modelo
        local) e a fração manda nos tetos apertados das APIs.
        """
        return min(self.reserva, teto // 3)

    def montar(
        self, pergunta: str, historico: list[dict], teto: int | None = None
    ) -> tuple[list[dict], int]:
        """Monta as messages cabendo no orçamento.

        Devolve também o índice onde o turno de agora começa: dali para a frente
        as mensagens são intocáveis (a pergunta e o par assistant/tool das
        ferramentas), e só o prefixo de histórico pode ser podado mais tarde.

        O `teto` permite um orçamento menor que o padrão nesta pergunta. Serve
        para dois casos: um provedor cuja janela de token é menor que a do
        modelo local, e a segunda tentativa depois de o provedor ter recusado a
        requisição por tamanho.
        """
        teto = teto or self.max_tokens
        sistema = {"role": "system", "content": montar_prompt_sistema()}
        atual = {"role": "user", "content": pergunta}

        disponivel = (
            teto
            - custo_mensagem(sistema)
            - self.custo_ferramentas
            - self.reserva_para(teto)
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

    def podar(
        self, mensagens: list[dict], inicio_turno: int, teto: int | None = None
    ) -> int:
        """Descarta turnos antigos até o total caber de novo no orçamento.

        Roda entre as rodadas de ferramenta, quando os resultados já entraram na
        lista. Mexe só no prefixo de histórico: tirar uma mensagem 'tool' ou o
        'assistant' que a chamou deixa um tool_call_id órfão, e aí o provedor
        recusa a requisição inteira.
        """
        teto = teto or self.max_tokens
        total = self.custo_ferramentas + sum(
            custo_mensagem(mensagem) for mensagem in mensagens
        )

        # O índice 0 é o prompt de sistema; o histórico vai dali até inicio_turno.
        while total > teto and inicio_turno > 1:
            # Os pares saem juntos, para a conversa nunca começar por uma
            # resposta sem a pergunta que a gerou.
            removidas = mensagens[1:3]
            del mensagens[1:3]
            inicio_turno -= len(removidas)
            total -= sum(custo_mensagem(mensagem) for mensagem in removidas)

        return inicio_turno
