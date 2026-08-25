"""Pré-roteamento de intenções inequívocas para fontes oficiais.

O modelo continua escolhendo ferramentas em perguntas ambíguas. Aqui entram só
casos em que deixar essa escolha ao acaso reduz precisão e gasta uma chamada de
LLM: uma linha de ônibus explícita ou um nome que casa exatamente com o título
de uma página oficial presente no corpus.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from uspapo.ferramentas import normalizar, palavras
from uspapo.consulta_transporte import interpretar_consulta_transporte
from uspapo.locais_usp import _mencoes_com_posicao, mencoes_locais

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PASTA_PROCESSADOS = os.path.join(RAIZ, "data", "processed")
PALAVRAS_PERGUNTA = frozenset(
    "que quem quando onde como qual quais seria significa explique sobre diga fale".split()
)
TIPOS_DE_ENTIDADE = frozenset(
    "projeto programa iniciativa servico sistema plataforma portal site".split()
)
PADRAO_LINHA = re.compile(r"(?<!\w)(\d{4}|\d{3}[A-Za-z])(?:\s*-\s*\d{2})?(?!\w)")
TERMOS_ONIBUS = frozenset(
    "onibus circular circulares linha linhas ponto pontos parada paradas chega "
    "chegada horario horarios previsao previsoes busp".split()
)
TERMOS_TRAJETO = frozenset(
    "caminho chegar demora demorar distancia ir leva levar melhor rota "
    "trajeto tempo transporte vou".split()
)
TERMOS_CHEGADA = frozenset(
    "agora chega chegada horario horarios hoje passando passa previsao previsoes "
    "proximo proxima quando".split()
)
MAX_TURNOS_CONTEXTO_PONTO = 5
PADROES_PONTO = (
    re.compile(r"\b(?:ponto|parada)\s+(?:do|da|de)?\s*(.+?)(?:\?|$)", re.I),
    re.compile(
        r"\b(?:no|na|ao|pelo|pela)\s+"
        r"(?:ponto\s+(?:do|da|de)\s+)?(.+?)(?:\?|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:chega|passa|passando)\s+(?:ao|a|no|na)\s+(.+?)(?:\?|$)",
        re.I,
    ),
)
SUFIXO_PONTO = re.compile(
    r"\s*(?:,|;)?\s+"
    r"(?:saindo|partindo|vindo|a\s+partir|hoje|amanh[ãa]|"
    r"neste|nesse|este|esse|pr[oó]ximo|passado|aos?\s+finais?)\b.*$",
    re.I,
)


def _pediu_detalhes_transporte(pergunta: str) -> bool:
    texto = normalizar(pergunta)
    return any(
        trecho in texto
        for trecho in (
            "por que",
            "porque",
            "calcul",
            "de onde vem",
            "qual a fonte",
            "quais dados",
            "explique o tempo",
            "explique esse horario",
            "mais detalhes",
        )
    )


def _termo_principal(pergunta: str) -> str:
    termos = [p for p in palavras(pergunta) if p not in PALAVRAS_PERGUNTA]
    return " ".join(termos)


@lru_cache(maxsize=1)
def catalogo_titulos() -> dict[str, list[dict[str, str]]]:
    """Índice lexical leve: não mantém os 23 MB do corpus na memória."""
    catalogo: dict[str, list[dict[str, str]]] = {}
    if not os.path.isdir(PASTA_PROCESSADOS):
        return catalogo
    for nome in sorted(os.listdir(PASTA_PROCESSADOS)):
        if not nome.endswith(".json"):
            continue
        try:
            with open(os.path.join(PASTA_PROCESSADOS, nome), encoding="utf-8") as arquivo:
                paginas = json.load(arquivo)
        except (OSError, json.JSONDecodeError):
            continue
        for pagina in paginas if isinstance(paginas, list) else []:
            titulo = str(pagina.get("titulo") or "").strip()
            url = str(pagina.get("url") or "").strip()
            chave = normalizar(titulo)
            if titulo and pagina.get("texto_limpo") and url and len(chave) >= 4:
                catalogo.setdefault(chave, []).append(
                    {"titulo": titulo, "url": url, "arquivo": nome}
                )
    return catalogo


def pagina_por_titulo(pergunta: str) -> dict[str, str] | None:
    termo = _termo_principal(pergunta)
    if not termo:
        return None
    catalogo = catalogo_titulos()
    candidatos = catalogo.get(normalizar(termo), [])
    if not candidatos:
        sem_tipo = " ".join(p for p in palavras(termo) if p not in TIPOS_DE_ENTIDADE)
        candidatos = catalogo.get(normalizar(sem_tipo), [])
    if len(candidatos) != 1:
        return None
    candidato = candidatos[0]
    try:
        with open(
            os.path.join(PASTA_PROCESSADOS, candidato["arquivo"]), encoding="utf-8"
        ) as arquivo:
            paginas = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        return None
    for pagina in paginas if isinstance(paginas, list) else []:
        if pagina.get("url") == candidato["url"]:
            return {
                "titulo": candidato["titulo"],
                "url": candidato["url"],
                "texto": str(pagina.get("texto_limpo") or "").strip(),
            }
    return None


def pedido_trajeto(pergunta: str) -> dict[str, str] | None:
    """Extrai dois locais conhecidos e seus papéis de origem/destino."""
    texto = normalizar(pergunta)
    mencoes = _mencoes_com_posicao(texto)
    tem_intencao = bool(set(palavras(texto)) & TERMOS_TRAJETO)
    if len(mencoes) >= 2 and not tem_intencao:
        entre_locais = texto[mencoes[0][1]:mencoes[1][0]]
        tem_intencao = bool(re.search(r"\b(?:ate|ao|para|pra)\b", entre_locais))
    if not tem_intencao:
        return None
    unicas: list[tuple[int, int, str]] = []
    chaves_vistas: set[str] = set()
    for mencao in mencoes:
        if mencao[2] not in chaves_vistas:
            chaves_vistas.add(mencao[2])
            unicas.append(mencao)
    if len(unicas) < 2:
        return None

    # "como chegar lá do metrô": o local depois de "chegar lá" é a origem;
    # o prédio mencionado antes é o destino.
    chegar_la = re.search(r"\bchegar\s+la\b", texto)
    if chegar_la:
        origens = [m for m in unicas if m[0] > chegar_la.end()]
        destinos = [m for m in unicas if m[0] < chegar_la.start()]
        if origens and destinos:
            return {"origem": origens[0][2], "destino_ou_ponto": destinos[-1][2]}

    destino = None
    marcador_destino = re.compile(
        r"(?:\b(?:ao|aos)|\bate(?:\s+[ao])?|\b(?:para|pra)(?:\s+[ao])?|"
        r"\b(?:chegar|chego|ir|vou)\s+(?:ate\s+|para\s+|pra\s+)?"
        r"(?:ao|a|no|na))\s*$"
    )
    for mencao in mencoes:
        antes = texto[max(0, mencao[0] - 45):mencao[0]]
        if marcador_destino.search(antes):
            destino = mencao
    destino = destino or unicas[-1]
    origem = next((m for m in unicas if m[2] != destino[2]), None)
    if not origem:
        return None
    return {"origem": origem[2], "destino_ou_ponto": destino[2]}


def pedido_circular(pergunta: str) -> dict[str, str] | None:
    match = PADRAO_LINHA.search(pergunta)
    termos = set(palavras(pergunta))
    if not (termos & TERMOS_ONIBUS or "chega" in termos):
        return None
    # Primeiro recortamos o trecho sintaticamente ligado a ponto/parada. Só
    # então aplicamos aliases conhecidos; um local mencionado como origem não
    # pode sobrescrever uma parada explícita fora do catálogo.
    ponto = ""
    for padrao in PADROES_PONTO:
        achado = padrao.search(pergunta)
        if not achado:
            continue
        trecho = SUFIXO_PONTO.sub("", achado.group(1)).strip(" .?!")
        locais_trecho = list(dict.fromkeys(mencoes_locais(trecho)))
        if len(locais_trecho) > 1:
            return None
        ponto = locais_trecho[0] if len(locais_trecho) == 1 else trecho
        break
    if not ponto:
        locais = list(dict.fromkeys(mencoes_locais(pergunta)))
        ponto = locais[0] if len(locais) == 1 else ""
    if not match and not ponto:
        return None
    return {
        "linha": match.group(1) if match else "",
        "destino_ou_ponto": ponto,
    }


def _pediu_chegada(pergunta: str) -> bool:
    """Se a linha precisa de uma parada, e não apenas de seu itinerário."""
    return bool(set(palavras(pergunta)) & TERMOS_CHEGADA)


def _linhas_mencionadas(texto: str) -> set[str]:
    return {
        normalizar(match.group(1)).upper()
        for match in PADRAO_LINHA.finditer(texto or "")
    }


def _ponto_recente_associado(
    linha: str, historico: list[dict] | None
) -> str | None:
    """Recupera um ponto anterior somente quando o vínculo é inequívoco.

    A pergunta do turno é a única fonte do local. A resposta anterior serve só
    para confirmar que aquele turno tratou da linha atual — nunca extraímos um
    ponto dela, pois um itinerário pode mencionar dezenas de paradas. Se o turno
    associado mais recente contém dois locais, a referência é ambígua e paramos
    em vez de ressuscitar um ponto mais antigo.
    """
    alvo = normalizar(linha).split("-", 1)[0].upper()
    if not alvo or not isinstance(historico, list):
        return None

    ponto_de_contexto: str | None = None
    destino_de_rota_fallback: str | None = None
    for turno in reversed(historico[-MAX_TURNOS_CONTEXTO_PONTO:]):
        if not isinstance(turno, dict):
            continue
        pergunta_anterior = str(turno.get("pergunta") or "").strip()
        resposta_anterior = str(turno.get("resposta") or "").strip()
        if not pergunta_anterior:
            continue

        rota_anterior = pedido_trajeto(pergunta_anterior)
        termos = set(palavras(pergunta_anterior))
        if not (
            termos & TERMOS_ONIBUS
            or _linhas_mencionadas(pergunta_anterior)
            or rota_anterior
        ):
            continue

        locais = list(dict.fromkeys(mencoes_locais(pergunta_anterior)))
        # Em um turno de rota com dois locais, a pergunta do usuário pode
        # identificar inequivocamente origem e destino. Nesse caso "lá" no
        # turno seguinte significa o destino; ainda não lemos locais da
        # resposta do assistente, que poderia listar muitas paradas.
        ponto_da_rota = (
            rota_anterior.get("destino_ou_ponto")
            if rota_anterior and rota_anterior.get("destino_ou_ponto")
            else None
        )
        linhas = _linhas_mencionadas(
            pergunta_anterior + "\n" + resposta_anterior
        )
        if alvo in linhas:
            if len(locais) == 1:
                return locais[0]
            # Um turno que associa explicitamente a linha a dois locais não
            # determina em qual parada o aluno espera o ônibus.
            return None
        if ponto_de_contexto is None and len(locais) == 1:
            # Uma consulta recente de "quais linhas passam no Biênio" mantém o
            # Biênio como assunto mesmo quando a resposta correta exclui a linha
            # perguntada agora. Turnos origem→destino (dois locais) são ignorados.
            ponto_de_contexto = locais[0]
        # Uma rota anterior menciona origem e destino, mas não associa a linha
        # atual a nenhum deles. Não deixe, por exemplo, o destino de uma rota
        # recente substituir uma parada explicitamente discutida antes.
        if destino_de_rota_fallback is None and ponto_da_rota:
            destino_de_rota_fallback = ponto_da_rota
    return ponto_de_contexto or destino_de_rota_fallback


def _continuacao_de_esclarecimento(
    pergunta: str,
    historico: list[dict] | None,
) -> tuple[dict[str, str], str] | None:
    """Liga uma resposta curta de local ao pedido de parada do turno anterior."""
    locais = list(dict.fromkeys(mencoes_locais(pergunta)))
    if len(locais) != 1 or not historico:
        return None
    ultimo = historico[-1] if isinstance(historico[-1], dict) else {}
    pergunta_anterior = str(ultimo.get("pergunta") or "")
    resposta_anterior = normalizar(ultimo.get("resposta") or "")
    linhas = _linhas_mencionadas(pergunta_anterior)
    if (
        len(linhas) != 1
        or not _pediu_chegada(pergunta_anterior)
        or "qual parada" not in resposta_anterior
    ):
        return None
    linha = next(iter(linhas))
    pergunta_operacional = (
        pergunta_anterior + "\nParada informada na continuação: " + pergunta
    )
    return (
        {"linha": linha, "destino_ou_ponto": locais[0]},
        pergunta_operacional,
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
