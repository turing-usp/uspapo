"""O núcleo: um gerador de eventos.

Uma pergunta vira uma sequência de dicts com um campo "tipo" (provedor,
pensando, ferramenta, texto, fontes, erro, fim). Quem transforma isso em SSE ou
no JSON legado é o saida.py — aqui não se sabe nada de HTTP.
"""

from typing import Iterator

from uspapo import config
from uspapo.conteudo import ROTULOS_FERRAMENTA, SeparadorConteudo, extrair_raciocinio
from uspapo.contexto import Orcamento
from uspapo.provedores import Provedor
from uspapo.toolcalls import ColetorDeChamadas


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
) -> Iterator[dict]:
    """Roda o laço de ferramentas num provedor. Levanta se a API falhar.

    O laço só termina quando o modelo para de pedir ferramenta: quem modera o
    uso é o prompt de sistema. TETO_RODADAS_FERRAMENTA (0 = desligado) existe
    como freio de emergência para um modelo que entre em loop.
    """
    mensagens, inicio_turno = orcamento.montar(pergunta, historico)
    rodada = 0

    while True:
        # Os resultados das ferramentas entraram na lista desde a última volta e
        # podem ter estourado o orçamento; quem paga são os turnos mais velhos.
        inicio_turno = orcamento.podar(mensagens, inicio_turno)

        separador = SeparadorConteudo()
        coletor = ColetorDeChamadas(registro)
        texto: list[str] = []

        for chunk in provedor.cliente.chat.completions.create(
            **provedor.parametros(mensagens, registro.schemas)
        ):
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

        # Nenhuma ferramenta pedida: esta rodada é a resposta ao aluno.
        if not coletor:
            if not "".join(texto).strip():
                raise RuntimeError("o provedor terminou o stream sem resposta utilizável")
            return

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
                "content": resultado,
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
) -> Iterator[dict]:
    """Percorre a cadeia de provedores até um deles responder."""
    memo: dict = {}  # buscas já feitas neste turno, para não repagar embed+query
    emitiu_texto = False
    ultimo_erro = None

    for indice, provedor in enumerate(provedores):
        yield {"tipo": "provedor", "nome": provedor.nome, "indice": indice}

        # Cada tentativa tem suas próprias fontes: as do provedor que falhou
        # não correspondem à resposta que o aluno vai ler.
        urls_turno: set[str] = set()

        try:
            eventos = conversar_com_provedor(
                provedor, registro, orcamento, pergunta, historico, urls_turno, memo
            )
            for evento in eventos:
                # Só conta como resposta entregue o que o aluno de fato leria:
                # senão um provedor que cuspiu espaço em branco e morreu seria
                # tratado como resposta pela metade e não cairia para o próximo.
                if evento["tipo"] == "texto" and evento["delta"].strip():
                    emitiu_texto = True
                yield evento
        except Exception as erro:
            ultimo_erro = erro
            print(f"[llm] provedor '{provedor.nome}' falhou: {type(erro).__name__}: {erro}")

            # Depois que o cliente já começou a receber a resposta não dá para
            # reescrever o que ele viu: aí a falha é terminal.
            if emitiu_texto:
                yield {
                    "tipo": "erro",
                    "mensagem": "Não consegui terminar a resposta. Pode perguntar de novo?",
                }
                yield {"tipo": "fim"}
                return
            continue

        yield {"tipo": "fontes", "urls": sorted(urls_turno)}
        yield {"tipo": "fim"}
        return

    print(f"[llm] todos os provedores falharam. Último erro: {ultimo_erro}")
    yield {"tipo": "erro", "mensagem": "Nenhum provedor de LLM está disponível no momento."}
    yield {"tipo": "fim"}
