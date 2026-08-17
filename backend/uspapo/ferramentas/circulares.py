"""Ônibus que atendem a USP, pelos dados oficiais e gratuitos da SPTrans.

A ferramenta responde quatro perguntas diferentes conforme os argumentos que
chegam, e cada uma tem uma fonte própria:

* ``origem`` + ``destino_ou_ponto`` — qual é o melhor ônibus direto entre dois
  lugares, comparando caminhada, sentido, percurso e frequência programada;
* ``linha`` + ``destino_ou_ponto`` — quando essa linha passa naquela parada;
* só ``destino_ou_ponto`` — quais linhas atendem aquela parada;
* só ``linha``, ou nada — o itinerário da linha, ou o que existe no recorte.

O cálculo não mora aqui. ``uspapo.gtfs_sptrans`` é o motor de horários sobre o
recorte oficial versionado no repositório, ``uspapo.olhovivo`` fala com a API em
tempo real, ``uspapo.locais_usp`` resolve nomes e apelidos de prédios do campus e
``uspapo.transporte_resposta`` decide o que vale a pena dizer. Este módulo faz o
despacho, escreve a prosa de falha e declara o schema.

Limites de escopo que a resposta nunca deve esconder: o recorte cobre apenas as
linhas com ao menos uma parada na área da Cidade Universitária, o horário
programado não é previsão de chegada, e sem ``SPTRANS_TOKEN`` não existe tempo
real — só programação. Só há trajeto direto: baldeação não é modelada.

Ao contrário da ``buscar_documentos``, esta ferramenta é a MESMA nos dois
backends, por isso ela não cria um `Registro` próprio: quem escolhe o registro é
o entrypoint, através de ``registrar(registro)``.
"""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Any

from uspapo import gtfs_sptrans, olhovivo
from uspapo.ferramentas import (
    Registro,
    RespostaFerramenta,
    cache,
    em_lista,
    normalizar,
)
from uspapo.locais_usp import dados_local
from uspapo.transporte_resposta import (
    AlternativaPublica,
    EstimativaEspera,
    FaixaPassagemProgramada,
    LocalPublico,
    PassagensPorSentido,
    PrevisaoChegada,
    ResultadoCaminhada,
    ResultadoChegada,
    ResultadoTrajeto,
    facetas_da_pergunta,
    renderizar_caminhada,
    renderizar_chegada,
    renderizar_trajeto,
)

FONTE_GTFS = gtfs_sptrans.FONTE
FONTE_API = olhovivo.FONTE
# Listar as 54 variantes do recorte inteiro consome contexto que a resposta
# seguinte vai precisar. Toda ferramenta do projeto corta e diz que cortou.
MAX_LINHAS_LISTA = 25
# Verdadeiro em JSON chega como booleano, mas o modelo também manda "true",
# "sim" e 1. String não vazia é sempre verdadeira em Python: sem esta lista,
# `detalhes="false"` ligava a explicação técnica.
VERDADEIROS = frozenset({"true", "1", "sim", "yes", "y", "s", "verdadeiro"})


# ─────────────────────────────────────────────
# Higiene dos argumentos
# ─────────────────────────────────────────────
def _texto(valor: Any) -> str:
    """Aceita o que o modelo mandar (None, número, lista) e devolve texto."""
    if valor is None:
        return ""
    if isinstance(valor, (list, tuple, set)):
        itens = em_lista(valor, [])
        return itens[0].strip() if itens else ""
    return str(valor).strip()


def _booleano(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    return normalizar(_texto(valor)) in VERDADEIROS


# ─────────────────────────────────────────────
# Tradução para o contrato de apresentação
# ─────────────────────────────────────────────
def _local_publico(chave: str, dados: dict[str, Any] | None) -> LocalPublico:
    if not dados:
        nome = str(chave).replace("_", " ").strip().title()
        return LocalPublico(
            chave=chave,
            nome=nome,
            nome_curto=nome,
            localizacao="na região da Cidade Universitária",
        )
    return LocalPublico(
        chave=chave,
        nome=str(dados.get("nome") or chave),
        nome_curto=str(dados.get("nome_curto") or dados.get("nome") or chave),
        localizacao=str(dados.get("localizacao") or "na Cidade Universitária"),
    )


def _locais_do_plano(plano: dict[str, Any]) -> tuple[LocalPublico, LocalPublico]:
    chave_origem = str(plano.get("origem") or "")
    chave_destino = str(plano.get("destino") or "")
    return (
        _local_publico(chave_origem, dados_local(chave_origem)),
        _local_publico(chave_destino, dados_local(chave_destino)),
    )


def _alternativas_publicas(plano: dict[str, Any]) -> tuple[AlternativaPublica, ...]:
    return tuple(
        AlternativaPublica(
            linha=str(item["linha"]),
            sentido=str(item["sentido"]),
            total_s=float(item["total_estimado_s"]),
        )
        for item in plano.get("alternativas", [])
        if item.get("modo") == "onibus"
    )


def _resultado_caminhada(plano: dict[str, Any]) -> ResultadoCaminhada:
    melhor = plano["melhor"]
    origem, destino = _locais_do_plano(plano)
    return ResultadoCaminhada(
        origem=origem,
        destino=destino,
        distancia_m=float(melhor["distancia_aproximada_m"]),
        duracao_s=float(melhor["total_estimado_s"]),
        alternativas=_alternativas_publicas(plano),
        aviso=str(plano.get("aviso") or "") or gtfs_sptrans.aviso_se_necessario(),
    )


def _resultado_trajeto(
    plano: dict[str, Any], previsao: dict[str, Any] | None = None
) -> ResultadoTrajeto:
    melhor = plano["melhor"]
    intervalo_s = melhor.get("intervalo_programado_s")
    espera = EstimativaEspera(
        base="frequencia_media" if intervalo_s is not None else "programacao_exata",
        esperada_s=float(melhor["espera_programada_s"]),
        minima_s=float(melhor["espera_minima_s"]),
        maxima_s=float(melhor["espera_maxima_s"]),
        intervalo_s=float(intervalo_s) if intervalo_s is not None else None,
    )
    ao_vivo = olhovivo.espera_ao_vivo(
        previsao or {}, float(melhor["caminhada_origem_s"])
    )
    if ao_vivo:
        espera = ao_vivo

    origem, destino = _locais_do_plano(plano)
    return ResultadoTrajeto(
        origem=origem,
        destino=destino,
        linha=str(melhor["linha"]),
        sentido=str(melhor["sentido"]),
        embarque=str(melhor["embarque"]),
        desembarque=str(melhor["desembarque"]),
        caminhada_origem_m=float(melhor["caminhada_origem_m"]),
        caminhada_destino_m=float(melhor["caminhada_destino_m"]),
        caminhada_origem_s=float(melhor["caminhada_origem_s"]),
        caminhada_destino_s=float(melhor["caminhada_destino_s"]),
        viagem_s=float(melhor["viagem_s"]),
        espera=espera,
        previsao_consultada=previsao is not None,
        veiculos_ativos=(
            int(previsao["veiculos_ativos"])
            if previsao and previsao.get("veiculos_ativos") is not None
            else None
        ),
        alternativas=_alternativas_publicas(plano),
        aviso=gtfs_sptrans.aviso_se_necessario(),
    )


def _passagens_por_sentido(
    programacao: dict[str, Any], linha_padrao: str, ponto_pedido: str
) -> PassagensPorSentido:
    faixas = tuple(
        FaixaPassagemProgramada(
            referencia=str(faixa.get("proxima_referencia_texto", "")),
            referencia_instante=str(
                faixa.get("proxima_referencia")
                or faixa.get("proxima_janela_inicio", "")
            ),
            inicio=str(faixa.get("proxima_janela_inicio", "")),
            fim=str(faixa.get("proxima_janela_fim", "")),
            inicio_texto=str(faixa.get("proxima_janela_inicio_texto", "")),
            fim_texto=str(faixa.get("proxima_janela_fim_texto", "")),
            intervalo_min=max(1, int(faixa.get("intervalo_min", 1))),
            espera_tipica_min=max(0, int(faixa.get("espera_tipica_min", 0))),
            espera_maxima_min=max(0, int(faixa.get("espera_maxima_min", 0))),
            ativa_agora=bool(faixa.get("ativa_agora")),
        )
        for faixa in programacao.get("faixas", [])
    )
    return PassagensPorSentido(
        linha=str(programacao.get("linha") or linha_padrao),
        parada=str(programacao.get("parada") or ponto_pedido),
        sentido=str(programacao.get("destino") or ""),
        horarios_programados=tuple(
            str(item) for item in programacao.get("horarios", [])
        ),
        instantes_programados=tuple(
            str(item) for item in programacao.get("instantes", [])
        ),
        faixas_programadas=faixas,
    )


def _resultado_chegada(
    previsao: dict[str, Any], *, api_consultada: bool, ponto_pedido: str
) -> ResultadoChegada:
    """Traduz respostas SPTrans/GTFS para um contrato estável de apresentação."""
    if previsao.get("tipo") == "programacao":
        linha = str(previsao.get("linha") or "")
        sentidos = tuple(
            _passagens_por_sentido(item, linha, ponto_pedido)
            for item in (previsao.get("sentidos") or [previsao])
        )
        return ResultadoChegada(
            linha=linha or sentidos[0].linha,
            parada=str(previsao.get("parada") or sentidos[0].parada),
            sentidos=sentidos,
            api_consultada=api_consultada,
            observado_em=str(previsao.get("hr") or "") or None,
            veiculos_ativos=(
                int(previsao["veiculos_ativos"])
                if previsao.get("veiculos_ativos") is not None
                else None
            ),
            aviso_api=str(previsao.get("aviso_api") or ""),
            aviso=gtfs_sptrans.aviso_se_necessario(),
        )

    veiculos = tuple(
        PrevisaoChegada(
            horario=str(item["t"]),
            acessivel=bool(item["a"]) if item.get("a") is not None else None,
        )
        for item in previsao.get("veiculos", [])[:3]
        if isinstance(item, dict) and item.get("t")
    )
    linha = str(previsao.get("linha") or "")
    parada = str(previsao.get("parada") or ponto_pedido)
    return ResultadoChegada(
        linha=linha,
        parada=parada,
        sentidos=(PassagensPorSentido(
            linha=linha,
            parada=parada,
            sentido=str(previsao.get("destino") or ""),
            previsoes_ao_vivo=veiculos,
        ),),
        api_consultada=api_consultada,
        observado_em=str(previsao.get("hr") or "") or None,
        aviso_api=str(previsao.get("aviso_api") or ""),
    )


# ─────────────────────────────────────────────
# Os quatro modos de consulta
# ─────────────────────────────────────────────
def _responder_trajeto(
    origem: str, destino: str, detalhes: bool, pergunta: str | None
) -> tuple[str, list[str]] | RespostaFerramenta:
    plano = gtfs_sptrans.planejar_trajeto(origem, destino)
    if plano.get("erro"):
        return str(plano["erro"]), [FONTE_GTFS]

    facetas = facetas_da_pergunta(pergunta)
    if detalhes:
        facetas = replace(facetas, explicacao=True)

    fontes = [FONTE_GTFS]
    for chave in ("origem", "destino"):
        info = dados_local(str(plano.get(chave, "")))
        if info:
            fontes.append(str(info["fonte"]))

    if plano["melhor"].get("modo") == "a_pe":
        resultado = _resultado_caminhada(plano)
        return RespostaFerramenta(
            renderizar_caminhada(resultado, facetas),
            list(dict.fromkeys(fontes)),
            resultado.public_view(facetas),
        )

    # Só vale pagar a consulta ao vivo quando a pergunta pede o estado de agora.
    # Se houver ETA, ele substitui a espera programada no contrato e o total é
    # recalculado; nunca anexamos dois relógios incompatíveis.
    melhor = plano["melhor"]
    previsao = None
    token = os.getenv("SPTRANS_TOKEN", "").strip()
    if token and facetas.tempo_real:
        numero = str(melhor["linha"]).split("-", 1)[0]
        previsao = cache(
            (
                "circulares", "previsao-rota", numero,
                normalizar(melhor["embarque"]),
                normalizar(melhor["sentido"]),
                str(melhor["embarque_id"]),
            ),
            olhovivo.TTL_AO_VIVO,
            lambda: olhovivo.previsao_de_chegada(
                numero,
                str(melhor["embarque"]),
                token,
                str(melhor["sentido"]),
                str(melhor["embarque_id"]),
            ),
        )
        # A fonte é o que respondeu, não o que foi tentado: quando a API cai
        # para a programação, creditá-la mandaria o aluno para a página errada.
        if previsao.get("tipo") == "previsao":
            fontes.append(FONTE_API)

    resultado = _resultado_trajeto(plano, previsao)
    return RespostaFerramenta(
        renderizar_trajeto(resultado, facetas),
        list(dict.fromkeys(fontes)),
        resultado.public_view(facetas),
    )


def _responder_chegada(
    numero: str, ponto: str, detalhes: bool, pergunta: str | None
) -> tuple[str, list[str]] | RespostaFerramenta:
    token = os.getenv("SPTRANS_TOKEN", "").strip()
    if token:
        previsao = cache(
            ("circulares", "previsao", numero, normalizar(ponto)),
            olhovivo.TTL_AO_VIVO,
            lambda: olhovivo.previsao_de_chegada(numero, ponto, token),
        )
    else:
        previsao = gtfs_sptrans.programacao(numero, ponto)
    if previsao.get("erro"):
        return str(previsao["erro"]), [FONTE_GTFS]

    resultado = _resultado_chegada(
        previsao, api_consultada=bool(token), ponto_pedido=ponto
    )
    explicar = detalhes or facetas_da_pergunta(pergunta).explicacao
    texto = renderizar_chegada(resultado, detalhes=explicar)
    dados_publicos = resultado.public_view(pergunta, detalhes=explicar)
    if previsao.get("tipo") != "programacao":
        return RespostaFerramenta(texto, [FONTE_API], dados_publicos)
    fontes = [FONTE_API, FONTE_GTFS] if token else [FONTE_GTFS]
    return RespostaFerramenta(texto, fontes, dados_publicos)


def _responder_linhas_do_ponto(ponto: str) -> tuple[str, list[str]]:
    """Perguntas como "quais linhas passam no Biênio?".

    Não escolha candidatas pelo catálogo manual: o GTFS é a fonte oficial e deve
    devolver todas as linhas associadas ao stop_id.
    """
    atendimento = gtfs_sptrans.linhas_por_ponto(ponto)
    if atendimento.get("erro"):
        return str(atendimento["erro"]), [FONTE_GTFS]

    linhas = atendimento["linhas"]
    partes = [
        f"Segundo o GTFS oficial da SPTrans, a parada "
        f"{atendimento['parada']} é atendida por {len(linhas)} linhas:"
    ]
    partes.extend(
        f"- {item['linha']} — {item['nome']}" for item in linhas[:MAX_LINHAS_LISTA]
    )
    # A contagem é repetida depois da lista de propósito. Esta resposta chega ao
    # modelo como contexto pré-consultado, e um total isolado no cabeçalho é o
    # primeiro detalhe que uma paráfrase deixa cair.
    if len(linhas) > MAX_LINHAS_LISTA:
        partes.append(
            f"Total oficial cadastrado para essa parada: {len(linhas)} linhas; "
            f"listei as {MAX_LINHAS_LISTA} primeiras."
        )
    else:
        partes.append(
            f"Total oficial cadastrado para essa parada: {len(linhas)} linhas."
        )
    partes.append(gtfs_sptrans.nota_atualizacao())
    return "\n".join(partes), [FONTE_GTFS]


def _responder_itinerario(numero: str, pedido: str) -> tuple[str, list[str]]:
    resumos = gtfs_sptrans.resumo_da_linha(numero)
    if not resumos:
        return (
            f"A linha {pedido} não aparece no recorte oficial atual da SPTrans. "
            "Ela pode ter sido desativada, renumerada ou não atender a área da "
            "USP. NÃO conclua que a linha não existe: avise o aluno e sugira "
            "conferir o número.",
            [FONTE_GTFS],
        )
    partes = []
    for resumo in resumos[:2]:
        partes.append(f"### Linha {resumo['linha']} — {resumo['nome']}")
        if resumo["paradas"]:
            partes.append(
                "**Paradas oficiais do itinerário:** "
                + ", ".join(resumo["paradas"])
                + "."
            )
    partes.append(gtfs_sptrans.nota_atualizacao())
    return "\n\n".join(partes), [FONTE_GTFS]


def _responder_recorte() -> tuple[str, list[str]]:
    """Sem argumentos, mostra o que existe — nunca uma lista de "principais"."""
    rotas = gtfs_sptrans.rotas_do_recorte()
    partes = [
        f"O recorte GTFS atual contém {len(rotas)} variantes de linhas "
        "que possuem ao menos uma parada na área geográfica da USP:"
    ]
    partes.extend(
        f"- {linha} — {nome}" for linha, nome in rotas[:MAX_LINHAS_LISTA]
    )
    if len(rotas) > MAX_LINHAS_LISTA:
        partes.append(
            f"São {len(rotas)} variantes no total; listei as "
            f"{MAX_LINHAS_LISTA} primeiras. Peça uma linha específica ao aluno "
            "para ver o itinerário completo."
        )
    partes.append(gtfs_sptrans.nota_atualizacao())
    return "\n".join(partes), [FONTE_GTFS]


# ─────────────────────────────────────────────
# A ferramenta
# ─────────────────────────────────────────────
def consultar_circulares(
    linha=None,
    destino_ou_ponto=None,
    origem=None,
    detalhes=False,
    _pergunta=None,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Consulta trajetos, itinerários ou previsão de chegada em uma parada."""
    pedido_linha = _texto(linha)
    ponto = _texto(destino_ou_ponto)
    partida = _texto(origem)
    explicar = _booleano(detalhes)
    pergunta = _texto(_pergunta) or None
    numero = normalizar(pedido_linha).split("-", 1)[0].upper()

    if partida and ponto:
        return _responder_trajeto(partida, ponto, explicar, pergunta)
    if not numero and ponto:
        return _responder_linhas_do_ponto(ponto)
    if numero and ponto:
        # Previsão é o caso prioritário: uma única execução resolve linha,
        # parada e horários, sem exigir outra rodada do modelo.
        return _responder_chegada(numero, ponto, explicar, pergunta)
    if numero:
        return _responder_itinerario(numero, pedido_linha)
    return _responder_recorte()


def registrar(registro: Registro) -> None:
    """Registra a ferramenta no registro dado.

    Ao contrário da `buscar_documentos`, esta ferramenta é a mesma nos dois
    backends, por isso quem escolhe o registro é o entrypoint, e não este
    módulo.
    """
    registro.ferramenta(
        nome="consultar_circulares",
        descricao=(
            "Consulta o catálogo GTFS atual e a API Olho Vivo da SPTrans para "
            "itinerários, paradas, sentidos e previsões dos ônibus que atendem "
            "a USP (Cidade Universitária / Butantã). Os nomes das linhas e das "
            "paradas vêm dos dados oficiais atuais; não use uma lista manual nem "
            "deduza o embarque pelo nome da linha. "
            "Use esta ferramenta sempre que a pergunta mencionar ônibus, circular, "
            "linha, ponto, parada, chegada ou horário de ônibus. Quando o aluno "
            "perguntar quando uma linha chega a um local, envie tanto `linha` "
            "quanto `destino_ou_ponto`; a ferramenta devolve os horários em uma "
            "única chamada. Quando perguntar qual é o melhor ônibus ou como ir de "
            "um local a outro, envie `origem` e `destino_ou_ponto`; a ferramenta "
            "compara caminhada, sentido, percurso e frequência programada, e pode "
            "responder que ir a pé é melhor. ATENÇÃO: só existe trajeto DIRETO, "
            "e o horário programado NÃO é previsão de chegada. Se a ferramenta "
            "não achar a parada, isso NÃO significa que nenhuma linha passa por lá."
        ),
        parametros={
            "type": "object",
            "properties": {
                "linha": {
                    "type": "string",
                    "description": (
                        "Número oficial da linha de ônibus (ex: '8012', '8082', "
                        "'8084-10', '8022'). Omita se o aluno perguntar de forma "
                        "genérica."
                    ),
                },
                "destino_ou_ponto": {
                    "type": "string",
                    "description": (
                        "Destino ou instituto desejado (ex: 'Poli', 'FFLCH', "
                        "'Metrô Butantã', 'FEA', 'CRUSP', 'Biênio'). Para previsão "
                        "de chegada, este campo é obrigatório."
                    ),
                },
                "origem": {
                    "type": "string",
                    "description": (
                        "Local de partida quando o aluno pedir o melhor ônibus ou "
                        "um trajeto (ex: 'P1', 'Central', 'Reitoria', 'Biênio', "
                        "'Metrô Butantã'). Central significa o Restaurante "
                        "Universitário Central; Administração Central e Reitoria "
                        "são locais distintos."
                    ),
                },
                "detalhes": {
                    "type": "boolean",
                    "description": (
                        "Use true somente quando o aluno pedir para explicar o "
                        "cálculo, a origem dos dados ou a confiabilidade."
                    ),
                },
            },
            # Nenhum argumento é obrigatório: sem nada, a ferramenta devolve as
            # linhas do recorte atual. O que muda a resposta é a COMBINAÇÃO,
            # descrita na `descricao`.
            "required": [],
        },
    )(consultar_circulares)
