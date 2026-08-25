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
from uspapo.locais_usp import _mencoes_com_posicao, resolver_local


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
    more_arrivals = bool(re.search(r"\b(?:outro|outra|depois|segundo|proximos)\b", texto))
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
