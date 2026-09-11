"""Pré-roteamento de intenções inequívocas para fontes oficiais.

O modelo continua escolhendo ferramentas em perguntas ambíguas. Aqui entram só
casos em que deixar essa escolha ao acaso reduz precisão e gasta uma chamada de
LLM: uma linha de ônibus explícita ou um nome que casa exatamente com o título
de uma página oficial presente no corpus.
"""

from __future__ import annotations

from uspapo.documentos_locais import (
    RAIZ,
    PASTA_PROCESSADOS,
    catalogo_titulos,
    pagina_por_titulo,
)
from uspapo.consulta_transporte import (
    interpretar_consulta_transporte,
    MAX_TURNOS_CONTEXTO_PONTO,
    _pediu_detalhes_transporte,
    pedido_trajeto,
    pedido_circular,
    _pediu_chegada,
    _ponto_recente_associado,
    _continuacao_de_esclarecimento,
)

def preconsultar(
    registro, pergunta: str, historico: list[dict] | None = None
) -> tuple[str, list[str], str, dict | None] | None:
    historico = list((historico or [])[-MAX_TURNOS_CONTEXTO_PONTO:])
    internos = {"_pergunta": pergunta}
    if historico:
        internos["_historico"] = historico

    trajeto = pedido_trajeto(pergunta)
    consulta_trajeto = (
        interpretar_consulta_transporte(
            pergunta,
            origin=trajeto["origem"],
            destination=trajeto["destino_ou_ponto"],
            interpretation="preconsulta",
        )
        if trajeto else None
    )
    if (
        trajeto
        and consulta_trajeto
        and consulta_trajeto.task == "route"
        and "consultar_circulares" in registro.nomes
    ):
        try:
            resposta = registro.executar_direto(
                "consultar_circulares",
                linha="",
                detalhes=_pediu_detalhes_transporte(pergunta),
                **internos,
                **trajeto,
            )
            texto, fontes = resposta
        except Exception as erro:
            print(f"[roteamento] pré-consulta de trajeto falhou: {type(erro).__name__}: {erro}")
            return None
        print(
            f"[roteamento] trajeto: origem={trajeto['origem']!r}, "
            f"destino={trajeto['destino_ou_ponto']!r}"
        )
        return (
            texto,
            fontes,
            "consultar_circulares",
            getattr(resposta, "dados_publicos", None),
        )

    circular = pedido_circular(pergunta)
    pergunta_operacional = pergunta
    if not circular:
        continuacao = _continuacao_de_esclarecimento(pergunta, historico)
        if continuacao:
            circular, pergunta_operacional = continuacao
    consulta_circular = (
        interpretar_consulta_transporte(
            pergunta_operacional,
            line=circular["linha"],
            stop=circular["destino_ou_ponto"],
            interpretation="preconsulta",
        )
        if circular else None
    )
    if (
        circular
        and consulta_circular
        and consulta_circular.task != "general"
        and "consultar_circulares" in registro.nomes
    ):
        if (
            circular["linha"]
            and not circular["destino_ou_ponto"]
            and _pediu_chegada(pergunta)
        ):
            ponto_contextual = _ponto_recente_associado(
                circular["linha"], historico
            )
            if ponto_contextual:
                circular = {
                    **circular,
                    "destino_ou_ponto": ponto_contextual,
                }
        try:
            internos_circular = {
                **internos,
                "_pergunta": pergunta_operacional,
            }
            resposta = registro.executar_direto(
                "consultar_circulares",
                detalhes=_pediu_detalhes_transporte(pergunta),
                **internos_circular,
                **circular,
            )
            texto, fontes = resposta
        except Exception as erro:
            print(f"[roteamento] pré-consulta de circular falhou: {type(erro).__name__}: {erro}")
            return None
        print(f"[roteamento] consultar_circulares: linha={circular['linha']}, ponto={circular['destino_ou_ponto']!r}")
        return (
            texto,
            fontes,
            "consultar_circulares",
            getattr(resposta, "dados_publicos", None),
        )

    pagina = pagina_por_titulo(pergunta)
    if pagina:
        # A introdução costuma definir a entidade; limitar aqui evita entregar ao
        # modelo páginas enormes só porque o título casou exatamente.
        texto = (
            f"Fonte oficial encontrada por correspondência exata de título:\n\n"
            f"### {pagina['titulo']}\n{pagina['texto'][:4500]}"
        )
        print(f"[roteamento] título oficial exato: {pagina['titulo']!r}")
        return texto, [pagina["url"]], "buscar_documentos", None
    return None
