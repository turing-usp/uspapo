"""Gera o recorte GTFS das linhas que atendem a USP usado pelo backend.

O arquivo completo da SPTrans tem cerca de 14 MB e muda com frequencia. Este
script reduz o feed a rotas, calendarios, intervalos e paradas relevantes, para
que o servidor nao precise baixar o GTFS a cada cold start.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile


URL_GTFS = "https://www.sptrans.com.br/umbraco/Surface/PerfilDesenvolvedor/BaixarGTFS"
# Retângulo conservador da Cidade Universitária Armando de Salles Oliveira.
# A seleção é geográfica para não repetir o erro de manter uma lista manual de
# linhas: se a SPTrans criar ou renumerar uma linha, a próxima geração a inclui.
LIMITE_CAMPUS = {
    # Inclui a borda sul (ICB) e a borda leste (P1, EEFE e CPTM). O limite
    # anterior cortava esses quatro destinos do próprio catálogo e só os
    # mantinha por acaso quando a mesma linha também cruzava o miolo do campus.
    "latitude_min": -23.5705,
    "latitude_max": -23.5450,
    "longitude_min": -46.7500,
    "longitude_max": -46.7100,
}
RAIZ = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = RAIZ / "backend" / "uspapo" / "dados_sptrans.json"
MIN_ROTAS_RECORTE = 5
MIN_PARADAS_AREA = 20


def _segundos(horario: str) -> int:
    horas, minutos, segundos = (int(parte) for parte in horario.split(":"))
    return horas * 3600 + minutos * 60 + segundos


def _linhas(zip_gtfs: ZipFile, nome: str) -> list[dict[str, str]]:
    with zip_gtfs.open(nome) as arquivo:
        leitor = csv.DictReader(TextIOWrapper(arquivo, encoding="utf-8-sig"))
        return list(leitor)


def _linhas_opcionais(zip_gtfs: ZipFile, nome: str) -> list[dict[str, str]]:
    """Lê um arquivo GTFS opcional, devolvendo uma lista vazia se ele faltar."""
    try:
        return _linhas(zip_gtfs, nome)
    except KeyError:
        return []


def _indexar_frequencias(
    linhas: list[dict[str, str]], ids_viagens: set[str]
) -> dict[str, list[dict[str, int]]]:
    """Converte ``frequencies.txt`` sem perder a semântica de ``exact_times``.

    Pelo GTFS, ``exact_times=0`` (e o campo ausente) descreve uma janela com
    intervalo esperado, não horários cravados. O consumidor precisa dessa
    informação para não transformar cada múltiplo de ``headway_secs`` em uma
    previsão exata de partida.
    """
    frequencias_por_viagem: dict[str, list[dict[str, int]]] = {}
    for frequencia in linhas:
        trip_id = frequencia.get("trip_id")
        if not trip_id or trip_id not in ids_viagens:
            continue

        texto_exact_times = (frequencia.get("exact_times") or "0").strip()
        try:
            exact_times = int(texto_exact_times)
        except ValueError as err:
            raise ValueError(
                f"exact_times inválido na viagem {trip_id}: {texto_exact_times!r}"
            ) from err
        if exact_times not in (0, 1):
            raise ValueError(
                f"exact_times inválido na viagem {trip_id}: {exact_times}"
            )

        intervalo = int(frequencia["headway_secs"])
        if intervalo <= 0:
            raise ValueError(
                f"headway_secs deve ser positivo na viagem {trip_id}"
            )
        frequencias_por_viagem.setdefault(trip_id, []).append({
            "inicio": _segundos(frequencia["start_time"]),
            "fim": _segundos(frequencia["end_time"]),
            "intervalo": intervalo,
            "exact_times": exact_times,
        })
    return frequencias_por_viagem


def _indexar_excecoes_calendario(
    linhas: list[dict[str, str]], ids_servicos: set[str]
) -> dict[str, dict[str, int]]:
    """Converte ``calendar_dates.txt`` em serviço -> data -> tipo de exceção."""
    excecoes: dict[str, dict[str, int]] = {}
    for excecao in linhas:
        service_id = excecao.get("service_id")
        if not service_id or service_id not in ids_servicos:
            continue

        data = (excecao.get("date") or "").strip()
        try:
            datetime.strptime(data, "%Y%m%d")
        except ValueError as err:
            raise ValueError(
                f"data inválida em calendar_dates para {service_id}: {data!r}"
            ) from err

        tipo = int(excecao["exception_type"])
        if tipo not in (1, 2):
            raise ValueError(
                f"exception_type inválido para {service_id} em {data}: {tipo}"
            )
        excecoes.setdefault(service_id, {})[data] = tipo
    return excecoes


def gerar(arquivo_gtfs: Path | None, saida: Path) -> None:
    if arquivo_gtfs:
        origem = arquivo_gtfs.open("rb")
    else:
        requisicao = Request(URL_GTFS, headers={"User-Agent": "USPapo/1.0"})
        origem = BytesIO(urlopen(requisicao, timeout=60).read())

    with origem, ZipFile(origem) as zip_gtfs:
        todas_rotas = _linhas(zip_gtfs, "routes.txt")
        todas_viagens = _linhas(zip_gtfs, "trips.txt")
        todas_paradas = _linhas(zip_gtfs, "stops.txt")
        todos_tempos = _linhas(zip_gtfs, "stop_times.txt")

        ids_paradas_campus = {
            parada["stop_id"]
            for parada in todas_paradas
            if (
                LIMITE_CAMPUS["latitude_min"] <= float(parada["stop_lat"])
                <= LIMITE_CAMPUS["latitude_max"]
                and LIMITE_CAMPUS["longitude_min"] <= float(parada["stop_lon"])
                <= LIMITE_CAMPUS["longitude_max"]
            )
        }
        ids_viagens_campus = {
            tempo["trip_id"]
            for tempo in todos_tempos
            if tempo.get("stop_id") in ids_paradas_campus
        }
        ids_rotas = {
            viagem["route_id"]
            for viagem in todas_viagens
            if viagem.get("trip_id") in ids_viagens_campus
        }
        rotas = [rota for rota in todas_rotas if rota.get("route_id") in ids_rotas]
        viagens = [
            viagem for viagem in todas_viagens
            if viagem.get("route_id") in ids_rotas
        ]
        ids_viagens = {viagem["trip_id"] for viagem in viagens}

        frequencias_por_viagem = _indexar_frequencias(
            _linhas_opcionais(zip_gtfs, "frequencies.txt"), ids_viagens
        )

        tempos_por_viagem: dict[str, list[dict[str, str | int]]] = {}
        ids_paradas: set[str] = set()
        for tempo in todos_tempos:
            trip_id = tempo.get("trip_id")
            if trip_id not in ids_viagens:
                continue
            ids_paradas.add(tempo["stop_id"])
            tempos_por_viagem.setdefault(trip_id, []).append({
                "id": tempo["stop_id"],
                "sequencia": int(tempo["stop_sequence"]),
                "horario": _segundos(tempo["arrival_time"]),
            })

        paradas = {
            parada["stop_id"]: {
                "nome": parada["stop_name"],
                "latitude": float(parada["stop_lat"]),
                "longitude": float(parada["stop_lon"]),
            }
            for parada in todas_paradas
            if parada.get("stop_id") in ids_paradas
        }
        paradas_na_area = {
            stop_id: paradas[stop_id]
            for stop_id in sorted(ids_paradas_campus)
            if stop_id in paradas
        }

        ids_servicos = {viagem["service_id"] for viagem in viagens}
        calendarios = {
            calendario["service_id"]: {
                "dias": [
                    int(calendario[dia]) for dia in (
                        "monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday",
                    )
                ],
                "inicio": calendario["start_date"],
                "fim": calendario["end_date"],
            }
            for calendario in _linhas(zip_gtfs, "calendar.txt")
            if calendario.get("service_id") in ids_servicos
        }
        excecoes_calendario = _indexar_excecoes_calendario(
            _linhas_opcionais(zip_gtfs, "calendar_dates.txt"), ids_servicos
        )

        viagens_por_rota: dict[str, list[dict[str, object]]] = {}
        for viagem in viagens:
            tempos = sorted(
                tempos_por_viagem.get(viagem["trip_id"], []),
                key=lambda item: int(item["sequencia"]),
            )
            if not tempos:
                continue
            horario_inicial = int(tempos[0]["horario"])
            paradas_da_viagem = []
            for tempo in tempos:
                dados_parada = paradas.get(str(tempo["id"]))
                if not dados_parada:
                    continue
                paradas_da_viagem.append({
                    "id": tempo["id"],
                    "nome": dados_parada["nome"],
                    "latitude": dados_parada["latitude"],
                    "longitude": dados_parada["longitude"],
                    "sequencia": tempo["sequencia"],
                    "deslocamento": int(tempo["horario"]) - horario_inicial,
                    "horario": tempo["horario"],
                })
            viagens_por_rota.setdefault(viagem["route_id"], []).append({
                "id": viagem["trip_id"],
                "servico": viagem["service_id"],
                "sentido": viagem.get("direction_id", ""),
                "destino": viagem.get("trip_headsign", ""),
                "frequencias": frequencias_por_viagem.get(viagem["trip_id"], []),
                "paradas": paradas_da_viagem,
            })

        catalogo: dict[str, list[dict[str, object]]] = {}
        for rota in rotas:
            numero = rota["route_short_name"].split("-", 1)[0]
            catalogo.setdefault(numero, []).append({
                "id": rota["route_id"],
                "linha": rota["route_short_name"],
                "nome": rota["route_long_name"],
                "viagens": viagens_por_rota.get(rota["route_id"], []),
            })

    quantidade_rotas = sum(len(rotas_numero) for rotas_numero in catalogo.values())
    if quantidade_rotas < MIN_ROTAS_RECORTE:
        raise RuntimeError(
            "Recorte GTFS recusado: somente "
            f"{quantidade_rotas} rotas (mínimo seguro: {MIN_ROTAS_RECORTE})."
        )
    if len(paradas_na_area) < MIN_PARADAS_AREA:
        raise RuntimeError(
            "Recorte GTFS recusado: somente "
            f"{len(paradas_na_area)} paradas na área de seleção "
            f"(mínimo seguro: {MIN_PARADAS_AREA})."
        )

    documento = {
        "versao_esquema": 2,
        "fonte": URL_GTFS,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "criterio": {"linhas_com_parada_na_area_do_campus": LIMITE_CAMPUS},
        "estatisticas": {
            "numeros_linha": len(catalogo),
            "rotas": quantidade_rotas,
            "viagens": sum(
                len(rota.get("viagens", []))
                for rotas_numero in catalogo.values()
                for rota in rotas_numero
            ),
            "paradas_unicas_itinerarios": len(paradas),
            "paradas_na_area_selecao": len(paradas_na_area),
        },
        "paradas_na_area_selecao": paradas_na_area,
        "calendarios": calendarios,
        "excecoes_calendario": excecoes_calendario,
        "linhas": catalogo,
    }
    saida.parent.mkdir(parents=True, exist_ok=True)
    # Publicação atômica: uma interrupção durante a escrita não deixa o backend
    # lendo metade de um JSON e fingindo que não existem linhas.
    temporaria = saida.with_suffix(saida.suffix + ".tmp")
    temporaria.write_text(
        json.dumps(documento, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporaria.replace(saida)
    print(f"Recorte GTFS gravado em {saida} ({saida.stat().st_size} bytes).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--arquivo",
        type=Path,
        help="GTFS ZIP ja baixado; sem este argumento, baixa da SPTrans.",
    )
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args()
    gerar(argumentos.arquivo, argumentos.saida)


if __name__ == "__main__":
    main()
