"""Contrato flexível entre interpretação de transporte e cálculo factual.

Esta camada não tenta enumerar todas as perguntas que um aluno pode fazer. Ela
apenas registra o que foi resolvido com segurança, as facetas pedidas e o que
ainda falta. Os motores GTFS/Olho Vivo continuam sendo a autoridade factual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Literal, Mapping

from uspapo.ferramentas import normalizar, palavras
from uspapo.intencao_transporte import IntencaoTransporte, analisar_intencao_transporte
from uspapo.locais_usp import _mencoes_com_posicao, mencoes_locais, resolver_local


TarefaTransporte = Literal[
    "route", "arrival", "stop_info", "service_info", "general",
]
_PADRAO_LINHA = re.compile(r"(?<!\w)(\d{4}|\d{3}[A-Za-z])(?:\s*-\s*\d{2})?(?!\w)")
_TERMOS_TRANSITO = frozenset(
    "onibus circular circulares linha linhas ponto pontos parada paradas "
    "chega chegada horario horarios previsao previsoes busp transporte".split()
)
_TERMOS_TRAJETO = frozenset(
    "caminho chegar demora demorar distancia ir leva levar melhor rota trajeto "
    "tempo vou pegar".split()
)


@dataclass(frozen=True)
class FacetasTransporte:
    """Aspectos combináveis de uma pergunta; não formam uma enumeração fechada."""

    duration: bool = False
    realtime: bool = False
    alternatives: bool = False
    confidence: bool = False
    details: bool = False
    more_arrivals: bool = False
    service_window: bool = False
    service_at_stop: bool = False
    extras: Mapping[str, bool] = field(default_factory=dict)

    def como_publico(self) -> dict[str, bool]:
        return {
            "duration": self.duration,
            "realtime": self.realtime,
            "alternatives": self.alternatives,
            "confidence": self.confidence,
            "details": self.details,
            "more_arrivals": self.more_arrivals,
            "service_window": self.service_window,
            "service_at_stop": self.service_at_stop,
            **dict(self.extras),
        }


@dataclass(frozen=True)
class EntidadesTransporte:
    """Entidades já resolvidas; texto não resolvido nunca vira fato operacional."""

    origin: str | None = None
    destination: str | None = None
    line: str | None = None
    stop: str | None = None

    def como_publico(self) -> dict[str, str | None]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "line": self.line,
            "stop": self.stop,
        }


@dataclass(frozen=True)
class TransitQuery:
    """Consulta interpretada, independente do formato do resultado factual."""

    task: TarefaTransporte = "general"
    entities: EntidadesTransporte = field(default_factory=EntidadesTransporte)
    period: IntencaoTransporte = field(default_factory=IntencaoTransporte)
    facets: FacetasTransporte = field(default_factory=FacetasTransporte)
    needs_clarification: tuple[str, ...] = ()
    raw_question: str = ""
    interpretation: str = "deterministic"

    def como_publico(self) -> dict[str, object]:
        periodo: dict[str, object] = {
            "kind": self.period.periodo,
            "dates": [dia.isoformat() for dia in self.period.datas],
            "label": self.period.rotulo_periodo or None,
        }
        if self.period.restricao_temporal is not None:
            periodo["time_window"] = (
                self.period.restricao_temporal.como_publico()
            )
        return {
            "task": self.task,
            "entities": self.entities.como_publico(),
            "period": periodo,
            "facets": self.facets.como_publico(),
            "needs_clarification": list(self.needs_clarification),
            "interpretation": self.interpretation,
        }


@dataclass(frozen=True)
class ResultadoConsultaTransporte:
    """Envelope comum sem apagar os dataclasses específicos de cada motor."""

    query: TransitQuery
    kind: str
    facts: Mapping[str, object]

    def como_publico(self) -> dict[str, object]:
        return {
            "query": self.query.como_publico(),
            "kind": self.kind,
            "facts": dict(self.facts),
        }


def _resolver_entidade(valor: str | None) -> str | None:
    texto = str(valor or "").strip()
    if not texto:
        return None
    return resolver_local(texto) or texto


def _linha_da_pergunta(pergunta: str) -> str | None:
    achado = _PADRAO_LINHA.search(pergunta)
    return achado.group(1).upper() if achado else None


def _rota_inequivoca(pergunta: str) -> tuple[str | None, str | None]:
    """Resolve papéis apenas quando dois aliases têm conectores direcionais."""
    texto = normalizar(pergunta)
    mencoes = []
    vistos: set[str] = set()
    for inicio, fim, chave in _mencoes_com_posicao(texto):
        if chave not in vistos:
            vistos.add(chave)
            mencoes.append((inicio, fim, chave))
    if len(mencoes) != 2:
        return None, None
    origem, destino = mencoes
    entre = texto[origem[1]:destino[0]]
    antes = texto[max(0, origem[0] - 12):origem[0]]
    tem_origem = bool(re.search(r"\b(?:de|do|da)\s*$", antes))
    tem_destino = bool(re.search(r"\b(?:para|pra|pro|ate|ao|a)\b", entre))
    if tem_origem and tem_destino:
        return origem[2], destino[2]
    return None, None


def _local_unico(pergunta: str) -> str | None:
    locais = list(dict.fromkeys(chave for _, _, chave in _mencoes_com_posicao(pergunta)))
    return locais[0] if len(locais) == 1 else None


def interpretar_consulta_transporte(
    pergunta: str | None,
    *,
    origin: str | None = None,
    destination: str | None = None,
    line: str | None = None,
    stop: str | None = None,
    period: IntencaoTransporte | None = None,
    now: datetime | None = None,
    interpretation: str = "deterministic",
) -> TransitQuery:
    """Forma uma consulta somente a partir de evidência suficiente.

    Chamadores mediados por LLM podem preencher entidades explícitas. Se elas
    não vierem, o parser resolve apenas rota com marcadores direcionais claros;
    fora disso devolve ``general`` em vez de chutar uma tarefa próxima.
    """
    texto_original = str(pergunta or "")
    texto = normalizar(texto_original)
    intencao = period or analisar_intencao_transporte(texto_original, now)
    origem = _resolver_entidade(origin)
    destino = _resolver_entidade(destination)
    parada = _resolver_entidade(stop)
    linha = str(line or _linha_da_pergunta(texto_original) or "").strip().upper() or None
    if not origem and not destino:
        origem, destino = _rota_inequivoca(texto_original)
    if not parada and not origem and not destino:
        parada = _local_unico(texto)

    termos = set(palavras(texto))
    duration = bool(termos & {"demora", "demorar", "tempo", "leva", "levar", "quanto"})
    alternatives = bool(termos & {"alternativa", "alternativas", "opcao", "opcoes", "outro", "outra"})
    confidence = bool(re.search(r"\bconfi(?:anca|avel)\b", texto))
    details = bool(re.search(r"\b(?:por que|porque|detalhes|fonte|dados)\b", texto))
    more_arrivals = bool(re.search(
        r"\b(?:outro|outra|depois|segundo|proximos|proximas)\b", texto
    ))
    service_window = bool(re.search(
        r"\b(?:primeiro|ultimo|ultima|opera|operacao|ate que horas|ate quando|"
        r"comeca(?:r)?(?:\s+a)?\s+(?:rodar|circular|operar))\b",
        texto,
    ))
    # "passa/atende/tem [linha] [nesta parada] [hoje]" pergunta sobre a
    # operação da linha naquele stop, não sobre o itinerário completo nem
    # sobre o próximo ETA.
    service_at_stop = bool(re.search(
        r"\b(?:passa|atende|tem)\b", texto,
    ))
    facets = FacetasTransporte(
        duration=duration,
        realtime=intencao.tempo_real,
        alternatives=alternatives,
        confidence=confidence,
        details=details,
        more_arrivals=more_arrivals,
        service_window=service_window,
        service_at_stop=service_at_stop,
    )
    entities = EntidadesTransporte(origem, destino, linha, parada)

    if origem and destino:
        task: TarefaTransporte = "route"
        esclarecimentos: tuple[str, ...] = ()
    elif service_window and (linha or parada):
        task = "service_info"
        esclarecimentos = ()
    elif linha and parada and intencao.pede_chegada:
        task = "arrival"
        esclarecimentos = ()
    elif linha and parada and service_at_stop:
        task = "service_info"
        esclarecimentos = ()
    elif linha and intencao.pede_chegada:
        task = "arrival"
        esclarecimentos = ("stop",)
    elif parada:
        task = "stop_info"
        esclarecimentos = ()
    elif linha and not intencao.pede_chegada:
        task = "stop_info"
        esclarecimentos = ()
    else:
        task = "general"
        esclarecimentos = ()

    return TransitQuery(
        task=task,
        entities=entities,
        period=intencao,
        facets=facets,
        needs_clarification=esclarecimentos,
        raw_question=texto_original,
        interpretation=interpretation,
    )


def resultado_consulta_transporte(
    query: TransitQuery,
    kind: str,
    facts: Mapping[str, object],
) -> ResultadoConsultaTransporte:
    return ResultadoConsultaTransporte(query=query, kind=kind, facts=facts)


__all__ = [
    "EntidadesTransporte",
    "FacetasTransporte",
    "ResultadoConsultaTransporte",
    "TransitQuery",
    "interpretar_consulta_transporte",
    "resultado_consulta_transporte",
]


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
