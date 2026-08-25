"""Leitura conservadora da programação publicada no PlanOper."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import re
from typing import Any


NormalizarSentido = Callable[[object], str]


def tipo_dia(dia: date) -> int:
    """PlanOper: 1=dia útil, 0=sábado, 2=domingo."""
    return 1 if dia.weekday() <= 4 else 0 if dia.weekday() == 5 else 2


def sentido_da_viagem(
    rota: dict[str, Any],
    viagem: dict[str, Any],
    tipo_dia_consultado: int,
    normalizar_sentido: NormalizarSentido,
) -> str | None:
    """Associa uma viagem GTFS à ida/volta PlanOper sem heurística ampla."""
    planoper = rota.get("planoper")
    if not isinstance(planoper, dict):
        return None
    shape_id = str(viagem.get("shape_id") or "").strip()
    ids_por_dia = planoper.get("itinerarios_id", {})
    ids_dia = (
        ids_por_dia.get(str(tipo_dia_consultado)) or ids_por_dia.get(tipo_dia_consultado)
        if isinstance(ids_por_dia, dict) else None
    )
    if shape_id and isinstance(ids_dia, dict):
        ida = str(ids_dia.get("itiIdIda") or "").strip()
        volta = str(ids_dia.get("itiIdVolta") or "").strip()
        if shape_id == ida and shape_id != volta:
            return "ida"
        if shape_id == volta and shape_id != ida:
            return "volta"

    destino = normalizar_sentido(viagem.get("destino"))
    correspondencias = [
        sentido
        for sentido, letreiro in (
            ("ida", planoper.get("letreiro_ida")),
            ("volta", planoper.get("letreiro_volta")),
        )
        if destino and destino == normalizar_sentido(letreiro)
    ]
    return correspondencias[0] if len(correspondencias) == 1 else None


def partidas_da_viagem(
    rota: dict[str, Any],
    viagem: dict[str, Any],
    dia_servico: date,
    normalizar_sentido: NormalizarSentido,
) -> list[tuple[int, bool | None]]:
    """Partidas do PlanOper em segundos desde o início do dia de serviço."""
    planoper = rota.get("planoper")
    if not isinstance(planoper, dict):
        return []
    tipo = tipo_dia(dia_servico)
    sentido = sentido_da_viagem(rota, viagem, tipo, normalizar_sentido)
    if sentido is None:
        return []
    faixas = planoper.get(
        "partidas_ida" if sentido == "ida" else "partidas_volta", []
    )
    if not isinstance(faixas, list):
        return []

    resultado: list[tuple[int, bool | None]] = []
    deslocamento_dia = 0
    ultimo_relogio_s: int | None = None
    houve_virada = False
    for faixa in faixas:
        if not isinstance(faixa, dict):
            continue
        try:
            tipo_faixa = int(faixa.get("tipoDia"))
        except (TypeError, ValueError):
            continue
        if tipo_faixa != tipo or not isinstance(faixa.get("horariosProgramados"), list):
            continue
        for item in faixa["horariosProgramados"]:
            if not isinstance(item, dict):
                continue
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(item.get("horario") or "").strip())
            if not match:
                continue
            hora, minuto = int(match.group(1)), int(match.group(2))
            if hora > 23 or minuto > 59:
                continue
            relogio_s = hora * 3600 + minuto * 60
            if ultimo_relogio_s is not None and relogio_s < ultimo_relogio_s:
                if not houve_virada and ultimo_relogio_s >= 18 * 3600 and relogio_s <= 6 * 3600:
                    deslocamento_dia += 24 * 3600
                    houve_virada = True
                else:
                    return []
            acessivel = item.get("veiculoAcessivel")
            resultado.append((
                relogio_s + deslocamento_dia,
                bool(acessivel) if acessivel is not None else None,
            ))
            ultimo_relogio_s = relogio_s
    return resultado
