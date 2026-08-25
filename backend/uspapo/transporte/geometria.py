"""Geometria local pura para shapes e paradas GTFS.

Não conhece linhas, APIs ou regras de ETA. Isso permite testar e reutilizar a
projeção de coordenadas sem acoplar o motor de transporte à ferramenta HTTP.
"""

from __future__ import annotations

import math
from typing import Any


def distancia_local_coordenadas_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Distância plana local aproximada em metros."""
    lat_ref = math.radians((lat1 + lat2) / 2)
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(lat_ref)
    return math.hypot(dx, dy)


def projetar_ponto_no_shape(
    latitude: float,
    longitude: float,
    shape: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Projeta uma coordenada no ponto mais próximo ao longo de um shape."""
    if len(shape) < 2:
        return None

    melhor: dict[str, Any] | None = None
    acumulado_m = 0.0
    for ponto_a, ponto_b in zip(shape, shape[1:]):
        try:
            lat_a, lon_a = float(ponto_a["latitude"]), float(ponto_a["longitude"])
            lat_b, lon_b = float(ponto_b["latitude"]), float(ponto_b["longitude"])
        except (KeyError, TypeError, ValueError):
            continue

        tamanho_segmento_m = distancia_local_coordenadas_m(lat_a, lon_a, lat_b, lon_b)
        ky = 111_320
        kx = 111_320 * math.cos(math.radians(latitude))
        ax, ay = (lon_a - longitude) * kx, (lat_a - latitude) * ky
        bx, by = (lon_b - longitude) * kx, (lat_b - latitude) * ky
        vx, vy = bx - ax, by - ay
        norma2 = vx * vx + vy * vy
        if norma2 <= 0:
            acumulado_m += tamanho_segmento_m
            continue

        t_original = -(ax * vx + ay * vy) / norma2
        t = max(0.0, min(1.0, t_original))
        qx, qy = ax + t * vx, ay + t * vy
        candidato = {
            "distancia_m": math.hypot(qx, qy),
            "shape_m": acumulado_m + t * tamanho_segmento_m,
            "fracao_segmento": t,
            "fracao_original": t_original,
            "sequencia_a": ponto_a.get("sequencia"),
            "sequencia_b": ponto_b.get("sequencia"),
        }
        if melhor is None or candidato["distancia_m"] < float(melhor["distancia_m"]):
            melhor = candidato
        acumulado_m += tamanho_segmento_m
    return melhor


def paradas_projetadas_na_viagem(
    viagem: dict[str, Any],
    shape: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Projeta paradas no shape preservando sequência e tempo relativo GTFS."""
    paradas = viagem.get("paradas", [])
    if not isinstance(paradas, list):
        return []
    try:
        ordenadas = sorted(
            (parada for parada in paradas if isinstance(parada, dict)),
            key=lambda parada: int(parada.get("sequencia", 0)),
        )
    except (TypeError, ValueError):
        return []

    resultado: list[dict[str, Any]] = []
    for parada in ordenadas:
        try:
            latitude, longitude = float(parada["latitude"]), float(parada["longitude"])
            deslocamento = int(parada.get("deslocamento", 0))
        except (KeyError, TypeError, ValueError):
            return []
        projecao = projetar_ponto_no_shape(latitude, longitude, shape)
        if projecao is None:
            return []
        resultado.append({
            "id": str(parada.get("id") or ""),
            "nome": str(parada.get("nome") or ""),
            "sequencia": int(parada.get("sequencia", 0)),
            "deslocamento_s": deslocamento,
            "shape_m": float(projecao["shape_m"]),
            "erro_shape_m": float(projecao["distancia_m"]),
        })
    return resultado
