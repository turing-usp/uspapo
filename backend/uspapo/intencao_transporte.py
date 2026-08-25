"""Interpreta tempo e modo em perguntas de transporte sem depender de LLM.

O planejador precisa distinguir uma pergunta genérica ("quanto demora?") de
uma consulta operacional ("hoje", "agora", "neste fim de semana").  Usar o
relógio do servidor para ambas fazia a mesma pergunta mudar de resposta entre
sexta e sábado.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from uspapo.ferramentas import normalizar


try:
    FUSO_SP = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # pragma: no cover - imagens Windows sem tzdata
    FUSO_SP = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class RestricaoTemporal:
    """Janela civil pedida pelo usuario, resolvida no fuso de Sao Paulo.

    ``fim`` e exclusivo. Um horario-alvo e uma consulta "depois de" possuem
    apenas limite inferior; partes do dia possuem uma faixa, sem fingir que o
    usuario informou um minuto exato.
    """

    tipo: str
    inicio: datetime
    fim: datetime | None = None
    horario_alvo: str | None = None
    parte_do_dia: str | None = None

    def contem(self, instante: datetime) -> bool:
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=FUSO_SP)
        else:
            instante = instante.astimezone(FUSO_SP)
        return instante >= self.inicio and (
            self.fim is None or instante < self.fim
        )

    def chave_cache(self) -> tuple[str, str, str, str, str]:
        return (
            self.tipo,
            self.inicio.isoformat(),
            self.fim.isoformat() if self.fim else "",
            self.horario_alvo or "",
            self.parte_do_dia or "",
        )

    def como_publico(self) -> dict[str, str | None]:
        return {
            "type": self.tipo,
            "start": self.inicio.isoformat(),
            "end": self.fim.isoformat() if self.fim else None,
            "target_time": self.horario_alvo,
            "day_part": self.parte_do_dia,
        }


@dataclass(frozen=True)
class IntencaoTransporte:
    """Decisões semânticas usadas pelo roteador e pela ferramenta."""

    periodo: str = "tipico"
    datas: tuple[date, ...] = ()
    rotulo_periodo: str = ""
    modo_solicitado: str | None = None
    pede_chegada: bool = False
    tempo_real: bool = False
    restricao_temporal: RestricaoTemporal | None = None

    @property
    def periodo_explicito(self) -> bool:
        return bool(self.datas)

    def instante_para_planejamento(self, agora: datetime) -> datetime:
        """Referência estável para ranking quando o aluno não informou data.

        Uma rota genérica representa um dia útil típico às 10h. Consultas com
        data continuam usando o instante real (ou o começo do período futuro).
        """
        if agora.tzinfo is None:
            agora = agora.replace(tzinfo=FUSO_SP)
        else:
            agora = agora.astimezone(FUSO_SP)
        if self.restricao_temporal is not None:
            return self.restricao_temporal.inicio
        if self.periodo != "tipico":
            if self.datas and agora.date() not in self.datas:
                return datetime.combine(self.datas[0], time(hour=10), tzinfo=FUSO_SP)
            return agora

        dia = agora.date()
        while dia.weekday() >= 5:
            dia += timedelta(days=1)
        return datetime.combine(dia, time(hour=10), tzinfo=FUSO_SP)


def _fim_de_semana_relevante(hoje: date) -> tuple[date, date]:
    if hoje.weekday() == 5:  # sábado
        sabado = hoje
    elif hoje.weekday() == 6:  # domingo ainda pertence ao fim de semana atual
        sabado = hoje - timedelta(days=1)
    else:
        sabado = hoje + timedelta(days=(5 - hoje.weekday()))
    return sabado, sabado + timedelta(days=1)


def _proximo_dia_da_semana(hoje: date, dia_da_semana: int) -> date:
    return hoje + timedelta(days=(dia_da_semana - hoje.weekday()) % 7)


def _data_escrita(texto: str, hoje: date) -> date | None:
    achado = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?!\d)", texto)
    if not achado:
        return None
    dia, mes = int(achado.group(1)), int(achado.group(2))
    ano_texto = achado.group(3)
    ano = hoje.year if not ano_texto else int(ano_texto)
    if ano < 100:
        ano += 2000
    try:
        candidata = date(ano, mes, dia)
    except ValueError:
        return None
    if not ano_texto and candidata < hoje - timedelta(days=1):
        try:
            candidata = candidata.replace(year=ano + 1)
        except ValueError:
            return None
    return candidata


def _horario_explicito(texto: str) -> time | None:
    """Extrai relogio somente quando ha um marcador linguistico de horario."""
    achado = re.search(
        r"\b(?:as|a partir d(?:as?|o)|desde as?|por volta d(?:as?|o))\s+"
        r"(\d{1,2})(?:(?:h)(\d{2})?|:(\d{2}))?\b",
        texto,
    )
    if not achado:
        return None
    hora = int(achado.group(1))
    minuto = int(achado.group(2) or achado.group(3) or 0)
    if hora > 23 or minuto > 59:
        return None
    return time(hour=hora, minute=minuto)


def _aplicar_restricao_temporal(
    intencao: IntencaoTransporte,
    texto: str,
    hoje: date,
) -> IntencaoTransporte:
    """Associa hora/faixa a data ja resolvida pela intencao principal."""
    datas = intencao.datas
    dia_base = datas[0] if datas else hoje

    depois_da_meia_noite = bool(re.search(
        r"\b(?:depois\s+d[ae]\s+meia\s*-?\s*noite|"
        r"apos\s+a\s+meia\s*-?\s*noite)\b",
        texto,
    ))
    if depois_da_meia_noite:
        inicio = datetime.combine(
            dia_base + timedelta(days=1), time.min, tzinfo=FUSO_SP,
        )
        return replace(
            intencao,
            restricao_temporal=RestricaoTemporal(
                tipo="apos_meia_noite",
                inicio=inicio,
            ),
        )

    horario = _horario_explicito(texto)
    if horario is not None:
        inicio = datetime.combine(dia_base, horario, tzinfo=FUSO_SP)
        # Uma hora sem marcador de data pertence ao dia civil corrente. Isso
        # evita que o planejador troque a referencia por um dia util tipico.
        if not datas:
            intencao = replace(
                intencao,
                periodo="hoje",
                datas=(hoje,),
                rotulo_periodo="hoje",
            )
        return replace(
            intencao,
            restricao_temporal=RestricaoTemporal(
                tipo="horario_alvo",
                inicio=inicio,
                horario_alvo=horario.strftime("%H:%M"),
            ),
        )

    partes_do_dia = (
        ("madrugada", 0, 6),
        ("manha", 6, 12),
        ("tarde", 12, 18),
        ("noite", 18, 24),
    )
    for nome, hora_inicio, hora_fim in partes_do_dia:
        if not re.search(rf"\b{nome}\b", texto):
            continue
        inicio = datetime.combine(
            dia_base, time(hour=hora_inicio), tzinfo=FUSO_SP,
        )
        fim = (
            datetime.combine(
                dia_base + timedelta(days=1), time.min, tzinfo=FUSO_SP,
            )
            if hora_fim == 24
            else datetime.combine(
                dia_base, time(hour=hora_fim), tzinfo=FUSO_SP,
            )
        )
        if not datas:
            intencao = replace(
                intencao,
                periodo="hoje",
                datas=(hoje,),
                rotulo_periodo="hoje",
            )
        return replace(
            intencao,
            restricao_temporal=RestricaoTemporal(
                tipo="parte_do_dia",
                inicio=inicio,
                fim=fim,
                parte_do_dia=nome,
            ),
        )

    return intencao


def analisar_intencao_transporte(
    pergunta: str | None,
    agora: datetime | None = None,
) -> IntencaoTransporte:
    texto = normalizar(pergunta or "")
    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    else:
        instante = instante.astimezone(FUSO_SP)
    hoje = instante.date()

    def finalizar(intencao: IntencaoTransporte) -> IntencaoTransporte:
        return _aplicar_restricao_temporal(intencao, texto, hoje)

    marcador_proximo = bool(re.search(r"\bproxim[oa]\b", texto))
    proximo_e_periodo = bool(re.search(
        r"\bproxim[oa]\s+(?:fim|final|sabado|domingo)\b", texto
    ))
    horario_explicito = _horario_explicito(texto)
    restricao_horaria = horario_explicito is not None or bool(re.search(
        r"\b(?:depois\s+d[ae]\s+meia\s*-?\s*noite|apos\s+a\s+meia\s*-?\s*noite|"
        r"meia\s*-?\s*noite|madrugada|manha|tarde|noite)\b",
        texto,
    ))
    pede_chegada = bool(
        re.search(
            r"\b(quando|chega|chegara|previsao|previsoes|horario|horarios|"
            r"que horas|vai passar)\b",
            texto,
        )
        or (marcador_proximo and not proximo_e_periodo)
        # "Tem a linha X depois da meia-noite?" pede programação em uma
        # janela, não apenas a existência da linha na parada.
        or restricao_horaria
    )
    tempo_real = bool(
        pede_chegada
        or re.search(
            r"\b(agora|hoje|neste momento|nesse momento|passando|circulando)\b",
            texto,
        )
    )

    modo_onibus = bool(
        re.search(
            r"\b(qual|que|melhor)\s+(?:e\s+|seria\s+)?(?:o\s+)?"
            r"(onibus|circular|busp|linha)\b",
            texto,
        )
        or re.search(r"\b(devo|posso|vou)\s+pegar\b", texto)
        or re.search(r"\b(?:ir|chegar|trajeto|rota)\s+de\s+onibus\b", texto)
        or "linha devo pegar" in texto
    )

    data_literal = _data_escrita(texto, hoje)
    if data_literal:
        return finalizar(IntencaoTransporte(
            periodo="data",
            datas=(data_literal,),
            rotulo_periodo=data_literal.strftime("em %d/%m/%Y"),
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=tempo_real and data_literal == hoje,
        ))

    marcador_hoje = bool(
        "hoje" in texto
        or re.search(r"\b(agora|neste momento|nesse momento)\b", texto)
    )
    if marcador_hoje:
        return finalizar(IntencaoTransporte(
            periodo="hoje",
            datas=(hoje,),
            rotulo_periodo="hoje",
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=tempo_real,
        ))

    if re.search(r"\b(?:fim|final|fins|finais) de semana\b", texto):
        sabado, domingo = _fim_de_semana_relevante(hoje)
        if "passado" in texto:
            sabado -= timedelta(days=7)
            domingo -= timedelta(days=7)
        elif marcador_proximo and hoje.weekday() >= 5:
            sabado += timedelta(days=7)
            domingo += timedelta(days=7)
        return finalizar(IntencaoTransporte(
            periodo="fim_de_semana",
            datas=(sabado, domingo),
            rotulo_periodo=(
                f"no fim de semana de {sabado.strftime('%d/%m')} e "
                f"{domingo.strftime('%d/%m')}"
            ),
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=False,
        ))

    if "amanha" in texto:
        amanha = hoje + timedelta(days=1)
        return finalizar(IntencaoTransporte(
            periodo="amanha",
            datas=(amanha,),
            rotulo_periodo="amanhã",
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=False,
        ))

    menciona_sabado = bool(re.search(r"\bsabado\b", texto))
    menciona_domingo = bool(re.search(r"\bdomingo\b", texto))
    if menciona_sabado and menciona_domingo:
        sabado, domingo = _fim_de_semana_relevante(hoje)
        return finalizar(IntencaoTransporte(
            periodo="fim_de_semana",
            datas=(sabado, domingo),
            rotulo_periodo=(
                f"no fim de semana de {sabado.strftime('%d/%m')} e "
                f"{domingo.strftime('%d/%m')}"
            ),
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=False,
        ))
    if menciona_sabado or menciona_domingo:
        alvo = 5 if menciona_sabado else 6
        dia = _proximo_dia_da_semana(hoje, alvo)
        nome_dia = "sábado" if alvo == 5 else "domingo"
        return finalizar(IntencaoTransporte(
            periodo=nome_dia,
            datas=(dia,),
            rotulo_periodo=f"no {nome_dia}, {dia.strftime('%d/%m')}",
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=tempo_real and dia == hoje,
        ))

    if tempo_real:
        return finalizar(IntencaoTransporte(
            periodo="hoje",
            datas=(hoje,),
            rotulo_periodo="hoje",
            modo_solicitado="onibus" if modo_onibus else None,
            pede_chegada=pede_chegada,
            tempo_real=tempo_real,
        ))

    return finalizar(IntencaoTransporte(
        modo_solicitado="onibus" if modo_onibus else None,
        pede_chegada=pede_chegada,
        tempo_real=False,
    ))


__all__ = [
    "IntencaoTransporte",
    "RestricaoTemporal",
    "analisar_intencao_transporte",
]
