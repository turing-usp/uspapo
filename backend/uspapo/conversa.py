"""O núcleo: um gerador de eventos.

Uma pergunta vira uma sequência de dicts com um campo "tipo" (provedor,
pensando, ferramenta, texto, fontes, erro, fim). Quem transforma isso em SSE ou
no JSON legado é o saida.py — aqui não se sabe nada de HTTP.
"""

import time
from typing import Iterator

from uspapo import config, saude
from uspapo.conteudo import ROTULOS_FERRAMENTA, SeparadorConteudo, extrair_raciocinio
from uspapo.contexto import Orcamento, cortar
from uspapo.erros import MAX_TENTATIVAS, classificar, descrever
from uspapo.provedores import Provedor
from uspapo.toolcalls import ColetorDeChamadas

# O que o aluno lê quando a coisa dá errado. Nada de "provedor", "LLM" ou
# "servidor": para quem está do outro lado é só o USPapo que não respondeu.
MSG_INDISPONIVEL = (
    "Ops! Muitas pessoas estão utilizando o USPapo. Tente novamente em breve."
)
MSG_INTERROMPIDO = (
    "A resposta parou no meio do caminho. Pode mandar a pergunta de novo?"
)

# Quantas vezes reduzir o orçamento quando o provedor recusa a requisição por
# tamanho, e o quanto cortar de cada vez.
MAX_ENCOLHIMENTOS = 2
FATOR_ENCOLHIMENTO = 0.6
# Abaixo disto não sobra espaço nem para o prompt de sistema: insistir seria
# trocar um erro de tamanho por uma resposta sem contexto nenhum.
TETO_MINIMO = 3000


class ContextoGrandeDemais(Exception):
    """O provedor recusou a requisição inteira por tamanho.

    Vale a pena separar das outras falhas: é a única em que repetir a MESMA
    requisição é garantidamente inútil, e em que repetir uma requisição MENOR
    tem chance real de funcionar.
    """


def abrir_stream(provedor: Provedor, mensagens: list[dict], tools: list[dict]):
    """Abre o stream do provedor, repetindo o que vale a pena repetir.

    É aqui que o retry mora, e não em volta do laço inteiro, porque com
    stream=True o SDK dispara o HTTP e levanta 429/413/401 dentro do `create`,
    antes do primeiro chunk. Enquanto nada foi enviado ao aluno, tentar de novo
    é invisível para ele; depois do primeiro token, não dá mais para reescrever
    o que ele já viu.
    """
    # Provedor de castigo só está sendo tentado porque não havia melhor: uma
    # chance basta. Insistir com backoff em quem acabou de falhar atrasaria a
    # queda para o próximo justamente quando ela é mais provável.
    maximo = 1 if saude.espera_restante(provedor.nome) else MAX_TENTATIVAS
    tentativa = 0

    while True:
        try:
            return provedor.cliente.chat.completions.create(
                **provedor.parametros(mensagens, tools)
            )
        except Exception as erro:
            falha = classificar(erro, tentativa, maximo)
            print(f"[llm] '{provedor.nome}': {falha.motivo}")

            if falha.cooldown:
                saude.marcar_falha(provedor.nome, falha.cooldown)
            if falha.encolher:
                raise ContextoGrandeDemais(falha.motivo) from erro
            if not falha.repetir:
                raise

            print(f"[llm] '{provedor.nome}': tentando de novo em {falha.espera:.1f}s")
            time.sleep(falha.espera)
            tentativa += 1


def _despachar(
    blocos: list[tuple[str, str]], coletor: ColetorDeChamadas, texto: list[str]
) -> Iterator[dict]:
    """Traduz os blocos que saem do separador em eventos do stream.

    O que for resposta ao aluno é acumulado em `texto`: é ele que diz, no fim
    da rodada, se o provedor produziu algo aproveitável.
    """
    for rotulo, trecho in blocos:
        # Tool call que veio como texto vira chamada de verdade em vez de
        # aparecer crua no chat.
        if rotulo in ROTULOS_FERRAMENTA:
            yield from coletor.absorver_inline(ROTULOS_FERRAMENTA[rotulo] + trecho)
            continue

        if rotulo == "texto":
            texto.append(trecho)
        yield {"tipo": rotulo, "delta": trecho}


def conversar_com_provedor(
    provedor: Provedor,
    registro,
    orcamento: Orcamento,
    pergunta: str,
    historico: list[dict],
    urls_turno: set[str],
    memo: dict,
    teto: int,
) -> Iterator[dict]:
    """Roda o laço de ferramentas num provedor. Levanta se a API falhar.

    O laço só termina quando o modelo para de pedir ferramenta: quem modera o
    uso é o prompt de sistema. TETO_RODADAS_FERRAMENTA (0 = desligado) existe
    como freio de emergência para um modelo que entre em loop.

    O `teto` é o orçamento de contexto desta tentativa: cada provedor tem o
    seu, e ele encolhe se o provedor recusar a requisição por tamanho.
    """
    mensagens, inicio_turno = orcamento.montar(pergunta, historico, teto)
    rodada = 0

    # Fora do laço: cada rodada de ferramenta é uma chamada cobrada, e é
    # justamente nas últimas que o prompt engorda com o resultado das buscas.
    # Zerando aqui dentro, o turno inteiro era reportado como se fosse só a
    # última rodada.
    usage_prompt_tokens = 0
    usage_completion_tokens = 0

    while True:
        # Os resultados das ferramentas entraram na lista desde a última volta e
        # podem ter estourado o orçamento; quem paga são os turnos mais velhos.
        inicio_turno = orcamento.podar(mensagens, inicio_turno, teto)

        separador = SeparadorConteudo()
        coletor = ColetorDeChamadas(registro)
        texto: list[str] = []

        for chunk in abrir_stream(provedor, mensagens, registro.schemas):
            if hasattr(chunk, "usage") and chunk.usage:
                p_u = getattr(chunk.usage, "prompt_tokens", 0) or 0
                c_u = getattr(chunk.usage, "completion_tokens", 0) or 0
                if p_u or c_u:
                    usage_prompt_tokens += p_u
                    usage_completion_tokens += c_u
            if not chunk.choices:
                continue  # chunk só de usage, no fim do stream

            delta = chunk.choices[0].delta
            if delta is None:
                continue

            raciocinio = extrair_raciocinio(delta)
            if raciocinio:
                yield {"tipo": "pensando", "delta": raciocinio}

            if delta.content:
                yield from _despachar(separador.processar(delta.content), coletor, texto)

            for tc in (delta.tool_calls or []):
                yield from coletor.absorver_delta(tc)

        yield from _despachar(separador.finalizar(), coletor, texto)

        # Sem usage no stream o turno vale zero token, e não uma estimativa: o
        # chute anterior media len(pergunta)//4, ignorando prompt de sistema,
        # histórico e resultado das ferramentas, ou seja, quase todo o prompt.
        # O painel prefere medir menos a somar número inventado com medição.

        # Nenhuma ferramenta pedida: esta rodada é a resposta ao aluno.
        if not coletor:
            if not "".join(texto).strip():
                raise RuntimeError("o provedor terminou o stream sem resposta utilizável")
            return usage_prompt_tokens, usage_completion_tokens

        chamadas = coletor.fechar(rodada)

        mensagens.append({
            "role": "assistant",
            "content": "".join(texto),
            "tool_calls": [
                {
                    "id": chamada["id"],
                    "type": "function",
                    "function": {
                        "name": chamada["nome"],
                        "arguments": chamada["args"] or "{}",
                    },
                }
                for chamada in chamadas
            ],
        })

        # O que as ferramentas devolverem tem que caber na reserva: ela guarda
        # o espaço, mas nada impedia uma grade de 120 linhas de passar por cima
        # dele e estourar a requisição seguinte. Quando são várias chamadas na
        # mesma rodada, elas dividem a reserva.
        cota = max(orcamento.reserva_para(teto) // len(chamadas), 300)

        for chamada in chamadas:
            resultado, urls, args = registro.rodar(chamada, memo)
            urls_turno.update(urls)

            yield {
                "tipo": "ferramenta",
                "estado": "fim",
                "indice": chamada["indice"],
                "nome": chamada["nome"],
                "args": args,
                "resultados": len(urls),
            }

            mensagens.append({
                "role": "tool",
                "tool_call_id": chamada["id"],
                "content": cortar(resultado, cota),
            })

        rodada += 1
        if config.TETO_RODADAS_FERRAMENTA and rodada >= config.TETO_RODADAS_FERRAMENTA:
            raise RuntimeError(
                "o modelo pediu ferramenta em todas as "
                f"{config.TETO_RODADAS_FERRAMENTA} rodadas"
            )


def executar_conversa(
    provedores: list[Provedor],
    registro,
    orcamento: Orcamento,
    pergunta: str,
    historico: list[dict],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> Iterator[dict]:
    """Percorre a cadeia de provedores até um deles responder.

    Quem falhou há pouco vai para o fim da fila, não para fora dela: se todos
    estiverem de castigo a pergunta ainda tem que ser tentada, começando por
    quem sai antes.
    """
    memo: dict = {}  # buscas já feitas neste turno, para não repagar embed+query
    emitiu_texto = False
    ultimo_erro = None

    por_nome = {p.nome: p for p in provedores}
    cadeia = [por_nome[nome] for nome in saude.ordenar(list(por_nome))]

    inicio_conversa = time.time()
    for indice, provedor in enumerate(cadeia):
        yield {"tipo": "provedor", "nome": provedor.nome, "indice": indice}

        teto = provedor.teto_contexto()
        encolhimentos = 0
        concluiu = False

        while True:
            # Cada tentativa tem suas próprias fontes: as do provedor que falhou
            # não correspondem à resposta que o aluno vai ler.
            urls_turno: set[str] = set()

            try:
                eventos = conversar_com_provedor(
                    provedor, registro, orcamento, pergunta, historico,
                    urls_turno, memo, teto,
                )
                # O uso de tokens é o valor de retorno do gerador. Um ``for``
                # o descarta, fazendo o log da resposta falhar silenciosamente.
                while True:
                    try:
                        evento = next(eventos)
                    except StopIteration as fim:
                        usage_prompt_tokens, usage_completion_tokens = fim.value or (0, 0)
                        break
                    # Só conta como resposta entregue o que o aluno de fato
                    # leria: senão um provedor que cuspiu espaço em branco e
                    # morreu seria tratado como resposta pela metade e não
                    # cairia para o próximo.
                    if evento["tipo"] == "texto" and evento["delta"].strip():
                        emitiu_texto = True
                    yield evento
                concluiu = True

            except ContextoGrandeDemais as erro:
                ultimo_erro = erro
                # Vale refazer com menos contexto: as ferramentas já rodadas
                # estão no memo, então repetir a rodada não custa consulta nova.
                if not emitiu_texto and encolhimentos < MAX_ENCOLHIMENTOS:
                    encolhimentos += 1
                    teto = max(int(teto * FATOR_ENCOLHIMENTO), TETO_MINIMO)
                    print(f"[llm] '{provedor.nome}': refazendo com teto={teto} tokens")
                    continue

            except Exception as erro:
                ultimo_erro = erro
                print(f"[llm] provedor '{provedor.nome}' falhou: {descrever(erro)}")
                try:
                    from uspapo.analytics import registrar
                    registrar(
                        categoria="SISTEMA",
                        nome_evento="ERRO_PROVEDOR",
                        session_id=session_id,
                        user_id=user_id,
                        provedor=provedor.nome,
                        modelo=provedor.cfg.get("model", provedor.nome),
                        metadata={"erro": str(erro)}
                    )
                except Exception:
                    pass

            break

        if concluiu:
            saude.marcar_sucesso(provedor.nome)
            try:
                from uspapo.analytics import registrar
                duracao_ms = int((time.time() - inicio_conversa) * 1000)
                tot_tok = usage_prompt_tokens + usage_completion_tokens
                registrar(
                    categoria="CHAT",
                    nome_evento="RESPOSTA_CONCLUIDA",
                    session_id=session_id,
                    user_id=user_id,
                    provedor=provedor.nome,
                    modelo=provedor.cfg.get("model", provedor.nome),
                    prompt_tokens=usage_prompt_tokens,
                    completion_tokens=usage_completion_tokens,
                    total_tokens=tot_tok,
                    latencia_ms=duracao_ms,
                    metadata={"urls_fontes": len(urls_turno)}
                )
            except Exception as erro:
                # Telemetria não derruba a resposta, mas não pode falhar calada.
                print(f"[ERRO ANALYTICS] Falha ao registrar resposta concluida: {erro}")
            # Registrar antes do evento terminal evita perder o insert caso o
            # navegador encerre a conexão logo após receber ``fim``.
            yield {"tipo": "fontes", "urls": sorted(urls_turno)}
            yield {"tipo": "fim"}
            return

        # Depois que o cliente já começou a receber a resposta não dá para
        # reescrever o que ele viu: aí a falha é terminal.
        if emitiu_texto:
            yield {"tipo": "erro", "mensagem": MSG_INTERROMPIDO}
            yield {"tipo": "fim"}
            return

    print(f"[llm] todos os provedores falharam. Último erro: {ultimo_erro}")
    yield {"tipo": "erro", "mensagem": MSG_INDISPONIVEL}
    yield {"tipo": "fim"}
