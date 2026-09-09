"""Identidade, validade temporal e estimativas das previsões ao vivo."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
import math
from typing import Any

import requests

from uspapo import gtfs_sptrans, olhovivo
from uspapo.ferramentas import cache, normalizar
from uspapo.intencao_transporte import RestricaoTemporal
from uspapo.transporte_resposta import EstimativaEspera
from uspapo.transporte.geometria import (
    distancia_local_coordenadas_m as _distancia_local_coordenadas_m,
    paradas_projetadas_na_viagem as _paradas_projetadas_na_viagem,
    projetar_ponto_no_shape as _projetar_ponto_no_shape,
)
from uspapo.transporte.programacao import (
    FUSO_SP,
    RAIO_ACESSO_M,
    _coordenada_ponto,
    _normalizar_sentido_operacional,
    _programacao_gtfs,
)

# TTLs do cache:
# Posições de GPS e previsões mudam rápido: 20 segundos.
# Mapeamento de códigos de linha na SPTrans: 24 horas.
TTL_AO_VIVO = 20
TTL_LINHAS = 86400

# Limites iniciais deliberadamente conservadores para a idade de ``ta`` em
# relação a ``hr``. Eles são parâmetros de produto, não uma estimativa de
# probabilidade: até 90 s normalmente representa uma posição recém-publicada;
# até 5 min ainda é aproveitável; entre 5 e 15 min só merece baixa confiança;
# acima disso não anunciamos ETA ao vivo. Dados históricos poderão calibrá-los.
IDADE_TA_ALTA_S = 90
IDADE_TA_MEDIA_S = 5 * 60
IDADE_TA_MAXIMA_S = 15 * 60
ADIANTAMENTO_TA_MAXIMO_S = 60

# Salvaguardas do ETA derivado de GPS. O GPS precisa estar realmente próximo
# do itinerário e as paradas precisam encaixar de forma coerente no shape.
MAX_DISTANCIA_GPS_SHAPE_M = 100
MAX_ERRO_PARADA_SHAPE_M = 60
TOLERANCIA_ORDEM_SHAPE_M = 20

# ``cp`` e ``stop_id`` pertencem a bases diferentes. A igualdade literal pode
# ser usada como identidade comprovável, mas qualquer exceção precisa entrar
# aqui após validação dos dois cadastros; proximidade e nome nunca a substituem.
CPS_OLHO_VIVO_POR_STOP_GTFS: dict[str, frozenset[str]] = {}

_catalogo_gtfs = gtfs_sptrans.catalogo
_mesmo_nome = gtfs_sptrans.mesmo_nome
_distancia_parada_gtfs = gtfs_sptrans.distancia_m
_destino_linha_sptrans = olhovivo.destino_da_linha
_autenticar_sptrans = olhovivo._autenticar
_linhas_sptrans = olhovivo._linhas
_previsoes_linha = olhovivo._previsoes_linha
_posicoes_linha = olhovivo._posicoes_linha



def _linha_corresponde_ao_sentido_gtfs(
    linha: dict[str, Any], destino_gtfs: object,
) -> bool:
    """Não usa o casamento permissivo de busca para decidir o sentido."""
    destino = _normalizar_sentido_operacional(_destino_linha_sptrans(linha))
    esperado = _normalizar_sentido_operacional(destino_gtfs)
    return bool(destino and esperado and destino == esperado)


def _cps_olho_vivo_do_stop_gtfs(stop_id: object) -> frozenset[str]:
    stop = str(stop_id or "").strip()
    if not stop:
        return frozenset()
    return frozenset({stop, *CPS_OLHO_VIVO_POR_STOP_GTFS.get(stop, ())})


def _paradas_olho_vivo_do_stop_gtfs(
    paradas: list[dict[str, Any]], stop_id: object,
) -> list[dict[str, Any]]:
    """Retorna somente ``cp`` cuja equivalência ao stop GTFS é conhecida."""
    cps_permitidos = _cps_olho_vivo_do_stop_gtfs(stop_id)
    return [
        parada for parada in paradas
        if str(parada.get("cp", "")).strip() in cps_permitidos
    ]


def _agora_sptrans() -> datetime:
    """Relógio isolado para validar a atualidade dos payloads da API."""
    return datetime.now(FUSO_SP)


def _instante_referencia_sptrans(horario: str | None) -> datetime:
    agora = _agora_sptrans()
    try:
        hora, minuto = (int(parte) for parte in str(horario).split(":")[:2])
        referencia = datetime.combine(
            agora.date(), time(hora, minuto), tzinfo=FUSO_SP
        )
        if referencia - agora > timedelta(hours=12):
            referencia -= timedelta(days=1)
        elif agora - referencia > timedelta(hours=12):
            referencia += timedelta(days=1)
        return referencia
    except (TypeError, ValueError):
        return agora


def _referencia_api_recente(horario: str | None) -> bool:
    """Valida o relógio ``hr`` no limite de ingestão do Olho Vivo."""
    try:
        partes = str(horario or "").split(":")
        time(int(partes[0]), int(partes[1]))
    except (IndexError, TypeError, ValueError):
        return False
    referencia = _instante_referencia_sptrans(horario)
    idade_hr_s = (_agora_sptrans() - referencia).total_seconds()
    return (
        -ADIANTAMENTO_TA_MAXIMO_S
        <= idade_hr_s
        <= IDADE_TA_MAXIMA_S
    )


def _melhor_eta_ao_vivo(
    previsao: dict[str, Any], caminhada_origem_s: float,
) -> tuple[EstimativaEspera, str] | None:
    """Retorna o primeiro ETA válido alcançável, com sua confiança pronta."""
    if previsao.get("tipo") != "previsao":
        return None
    referencia = _instante_referencia_sptrans(previsao.get("hr"))
    candidatas: list[tuple[float, str, str]] = []
    for veiculo in previsao.get("veiculos", []):
        if not isinstance(veiculo, dict):
            continue
        horario = str(veiculo.get("t") or "").strip()
        ate_chegada_s = _segundos_ate_eta_sptrans(horario, referencia)
        if ate_chegada_s is None:
            continue
        # Um ônibus que passa antes de o aluno alcançar o ponto não pode ser
        # usado para recalcular o tempo total.
        if ate_chegada_s + 30 >= caminhada_origem_s:
            classificacao = _classificar_confianca_chegada(
                veiculo, previsao.get("hr"), referencia=referencia,
            )
            if classificacao["valid"]:
                candidatas.append((
                    max(0, ate_chegada_s), horario,
                    str(veiculo.get("confidence") or classificacao["level"]),
                ))
    if not candidatas:
        return None
    ate_chegada_s, horario, confianca = min(candidatas)
    espera_depois_da_caminhada_s = max(0, ate_chegada_s - caminhada_origem_s)
    return (
        EstimativaEspera(
            base="eta_ao_vivo",
            esperada_s=espera_depois_da_caminhada_s,
            minima_s=espera_depois_da_caminhada_s,
            maxima_s=espera_depois_da_caminhada_s,
            eta=horario,
            observado_em=str(previsao.get("hr") or "") or None,
        ),
        confianca,
    )


def _espera_ao_vivo(
    previsao: dict[str, Any], caminhada_origem_s: float,
) -> EstimativaEspera | None:
    """Compatibilidade para consumidores que só precisam da estimativa."""
    melhor = _melhor_eta_ao_vivo(previsao, caminhada_origem_s)
    return melhor[0] if melhor else None


def _segundos_ate_eta_sptrans(
    horario: str,
    referencia: datetime,
) -> float | None:
    """Valida um relógio Olho Vivo sem transformar dado stale em amanhã."""
    try:
        hora, minuto = (int(parte) for parte in horario.split(":")[:2])
        chegada = datetime.combine(
            referencia.date(), time(hora, minuto), tzinfo=FUSO_SP
        )
    except (TypeError, ValueError):
        return None
    if chegada < referencia - timedelta(seconds=30):
        if referencia.hour >= 20 and hora <= 4:
            chegada += timedelta(days=1)
        else:
            return None
    segundos = (chegada - referencia).total_seconds()
    if segundos < -30 or segundos > timedelta(hours=3).total_seconds():
        return None
    return max(0, segundos)


def _instante_atualizacao_sptrans(
    valor: object,
    referencia: datetime,
) -> datetime | None:
    """Interpreta ``ta`` sem transformar uma hora de ontem em dado novo."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    try:
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=FUSO_SP)
        return instante.astimezone(FUSO_SP)
    except ValueError:
        pass
    try:
        partes = texto.split(":")
        hora, minuto = int(partes[0]), int(partes[1])
        segundo = int(partes[2]) if len(partes) > 2 else 0
        instante = datetime.combine(
            referencia.date(), time(hora, minuto, segundo), tzinfo=FUSO_SP,
        )
    except (TypeError, ValueError):
        return None
    if instante - referencia > timedelta(hours=12):
        instante -= timedelta(days=1)
    elif referencia - instante > timedelta(hours=12):
        instante += timedelta(days=1)
    return instante


def _gps_valido(veiculo: dict[str, Any]) -> bool:
    try:
        latitude, longitude = float(veiculo["py"]), float(veiculo["px"])
    except (KeyError, TypeError, ValueError):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180 and bool(
        latitude or longitude
    )


def _classificar_confianca_chegada(
    veiculo: dict[str, Any],
    horario_referencia: str | None,
    *,
    referencia: datetime | None = None,
    source: str = "live",
) -> dict[str, Any]:
    """Classifica deterministamente uma chegada, sem interferência da LLM."""
    if source == "scheduled":
        return {"level": "scheduled", "reasons": ["gtfs_sem_eta_ao_vivo"], "valid": True}

    relogio = referencia or _instante_referencia_sptrans(horario_referencia)
    eta = _segundos_ate_eta_sptrans(str(veiculo.get("t") or ""), relogio)
    if eta is None:
        return {"level": "low", "reasons": ["eta_invalido"], "valid": False}

    reasons: list[str] = ["eta_valido"]
    gps_presente = _gps_valido(veiculo)
    if gps_presente:
        reasons.append("gps_presente")
    else:
        reasons.append("gps_ausente")
    identificador = str(veiculo.get("p") or "").strip()
    if identificador:
        reasons.append("veiculo_identificado")
    else:
        reasons.append("veiculo_nao_identificado")

    atualizado_em = _instante_atualizacao_sptrans(veiculo.get("ta"), relogio)
    if atualizado_em is None:
        reasons.append("ta_ausente_ou_invalido")

        if source == "live_gps_estimate":
            return {
                "level": "low",
                "reasons": reasons,
                "valid": False,
            }

        return {"level": "low", "reasons": reasons, "valid": True}
    idade_s = (relogio - atualizado_em).total_seconds()
    if idade_s < -ADIANTAMENTO_TA_MAXIMO_S:
        return {
            "level": "low",
            "reasons": [*reasons, "ta_posterior_ao_hr"],
            "valid": False,
        }
    idade_s = max(0, idade_s)
    if idade_s > IDADE_TA_MAXIMA_S:
        return {
            "level": "low",
            "reasons": [*reasons, "ta_antigo_demais"],
            "valid": False,
        }
    if source == "live_gps_estimate":
        if not gps_presente:
            return {
                "level": "low",
                "reasons": [
                    *reasons,
                    "gps_necessario_para_eta_derivado",
                ],
                "valid": False,
            }

        if idade_s <= IDADE_TA_MEDIA_S:
            return {
                "level": "medium",
                "reasons": [
                    *reasons,
                    "eta_derivado_da_posicao_gps",
                    "gps_recente",
                ],
                "valid": True,
            }

        return {
            "level": "low",
            "reasons": [
                *reasons,
                "eta_derivado_da_posicao_gps",
                "gps_pouco_recente",
            ],
            "valid": True,
        }
    if idade_s <= IDADE_TA_ALTA_S and gps_presente and identificador:
        level = "high"
        reasons.append("ta_muito_recente")
    elif idade_s <= IDADE_TA_MEDIA_S and gps_presente:
        level = "medium"
        reasons.append("ta_recente")
    elif idade_s <= IDADE_TA_MEDIA_S:
        level = "low"
        reasons.append("dados_operacionais_incompletos")
    else:
        level = "low"
        reasons.append("ta_antigo")
    return {"level": level, "reasons": reasons, "valid": True}


def _shape_da_viagem(
    viagem: dict[str, Any],
) -> list[dict[str, Any]]:
    """Obtém do recorte GTFS o shape associado à viagem."""
    shape_id = str(
        viagem.get("shape_id") or ""
    ).strip()

    if not shape_id:
        return []

    shapes = _catalogo_gtfs().get("shapes", {})

    if not isinstance(shapes, dict):
        return []

    pontos = shapes.get(shape_id, [])

    if not isinstance(pontos, list):
        return []

    validos = [
        ponto
        for ponto in pontos
        if isinstance(ponto, dict)
    ]

    try:
        return sorted(
            validos,
            key=lambda ponto: int(
                ponto.get("sequencia", 0)
            ),
        )
    except (TypeError, ValueError):
        return []


def _eta_derivado_de_gps(
    viagem: dict[str, Any],
    stop_id_alvo: str,
    veiculo: dict[str, Any],
    horario_referencia: str | None,
) -> dict[str, Any] | None:
    """Estima chegada usando GPS ao vivo + geometria/tempos relativos do GTFS.

    Não inventa uma grade horária. O GPS informa onde o veículo está agora;
    o GTFS fornece o shape da viagem e o tempo relativo entre suas paradas.

    Retorna None sempre que a associação não for suficientemente segura.
    """
    if not isinstance(viagem, dict) or not isinstance(veiculo, dict):
        return None

    stop_id_alvo = str(stop_id_alvo or "").strip()
    if not stop_id_alvo:
        return None

    # Um ETA derivado só existe se houver uma posição GPS válida.
    if not _gps_valido(veiculo):
        return None

    referencia = _instante_referencia_sptrans(
        horario_referencia
    )

    # O instante da posição GPS é a base temporal da estimativa.
    # Sem ta não sabemos quando o ônibus estava naquela coordenada.
    atualizado_em = _instante_atualizacao_sptrans(
        veiculo.get("ta"),
        referencia,
    )

    if atualizado_em is None:
        return None

    shape = _shape_da_viagem(viagem)

    if len(shape) < 2:
        return None

    paradas = _paradas_projetadas_na_viagem(
        viagem,
        shape,
    )

    if len(paradas) < 2:
        return None

    indices_alvo = [
        indice
        for indice, parada in enumerate(paradas)
        if parada["id"] == stop_id_alvo
    ]

    # Um mesmo stop_id repetido na viagem (por exemplo, o terminal inicial e
    # final de uma circular) não identifica sozinho qual ocorrência receberá
    # o veículo. Nesse caso continuamos recusando a inferência.
    if len(indices_alvo) != 1:
        return None

    indice_alvo = indices_alvo[0]
    paradas_ate_alvo = paradas[:indice_alvo + 1]

    if len(paradas_ate_alvo) < 2:
        return None

    # Para chegar ao alvo só precisamos validar o prefixo da viagem. Linhas
    # circulares podem repetir o terminal depois dele; projetar essa repetição
    # no primeiro ramo do shape não torna o trecho anterior ambíguo.
    if any(
        float(parada["erro_shape_m"])
        > MAX_ERRO_PARADA_SHAPE_M
        for parada in paradas_ate_alvo
    ):
        return None

    # A sequência das paradas deve avançar ao longo do shape.
    # Isso também protege contra projeções erradas em rotas que se cruzam.
    if any(
        float(atual["shape_m"])
        + TOLERANCIA_ORDEM_SHAPE_M
        < float(anterior["shape_m"])
        for anterior, atual in zip(
            paradas_ate_alvo,
            paradas_ate_alvo[1:],
        )
    ):
        return None

    alvo = paradas_ate_alvo[-1]

    try:
        latitude = float(veiculo["py"])
        longitude = float(veiculo["px"])
    except (KeyError, TypeError, ValueError):
        return None

    projecao_veiculo = _projetar_ponto_no_shape(
        latitude,
        longitude,
        shape,
    )

    if projecao_veiculo is None:
        return None

    distancia_shape_m = float(
        projecao_veiculo["distancia_m"]
    )

    if distancia_shape_m > MAX_DISTANCIA_GPS_SHAPE_M:
        return None

    posicao_veiculo_m = float(
        projecao_veiculo["shape_m"]
    )

    posicao_alvo_m = float(
        alvo["shape_m"]
    )

    # O veículo já chegou ou já passou pela parada pedida.
    # Não o anunciamos como "próximo".
    if posicao_veiculo_m >= posicao_alvo_m:
        return None

    # Em circulares, um ramo posterior ao alvo pode voltar muito perto do
    # trecho de ida. A projeção global sozinha escolheria um deles por poucos
    # metros e poderia anunciar como futuro um veículo que já passou. Reuse a
    # tolerância geométrica existente e recuse quando o GPS também encaixa no
    # sufixo da viagem sem margem espacial clara.
    acumulado_shape_m = 0.0
    indice_segmento_alvo: int | None = None
    for indice, (ponto_a, ponto_b) in enumerate(zip(shape, shape[1:])):
        try:
            tamanho_segmento_m = _distancia_local_coordenadas_m(
                float(ponto_a["latitude"]),
                float(ponto_a["longitude"]),
                float(ponto_b["latitude"]),
                float(ponto_b["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if acumulado_shape_m + tamanho_segmento_m >= posicao_alvo_m:
            indice_segmento_alvo = indice
            break
        acumulado_shape_m += tamanho_segmento_m

    if indice_segmento_alvo is None:
        return None
    projecao_pos_alvo = _projetar_ponto_no_shape(
        latitude,
        longitude,
        shape[indice_segmento_alvo:],
    )
    if (
        projecao_pos_alvo is not None
        and float(projecao_pos_alvo["distancia_m"])
        <= distancia_shape_m + TOLERANCIA_ORDEM_SHAPE_M
    ):
        return None

    # Descobre entre quais duas paradas GTFS o ônibus está.
    anterior: dict[str, Any] | None = None
    posterior: dict[str, Any] | None = None

    for parada_a, parada_b in zip(
        paradas_ate_alvo,
        paradas_ate_alvo[1:],
    ):
        posicao_a = float(
            parada_a["shape_m"]
        )
        posicao_b = float(
            parada_b["shape_m"]
        )

        if (
            posicao_a
            <= posicao_veiculo_m
            <= posicao_b
        ):
            anterior = parada_a
            posterior = parada_b
            break

    if anterior is None or posterior is None:
        return None

    inicio_m = float(
        anterior["shape_m"]
    )
    fim_m = float(
        posterior["shape_m"]
    )

    comprimento_trecho_m = (
        fim_m - inicio_m
    )

    # Duas paradas projetadas praticamente no mesmo ponto não permitem
    # uma interpolação espacial estável.
    if comprimento_trecho_m <= 1:
        return None

    tempo_anterior_s = float(
        anterior["deslocamento_s"]
    )
    tempo_posterior_s = float(
        posterior["deslocamento_s"]
    )

    if tempo_posterior_s < tempo_anterior_s:
        return None

    fracao = (
        posicao_veiculo_m - inicio_m
    ) / comprimento_trecho_m

    fracao = max(
        0.0,
        min(1.0, fracao),
    )

    tempo_atual_s = (
        tempo_anterior_s
        + fracao
        * (
            tempo_posterior_s
            - tempo_anterior_s
        )
    )

    tempo_alvo_s = float(
        alvo["deslocamento_s"]
    )

    restante_s = (
        tempo_alvo_s
        - tempo_atual_s
    )

    if restante_s <= 0:
        return None

    # A posição GPS foi observada em `ta`, portanto o ETA começa naquele
    # instante — e não no momento em que terminamos a requisição HTTP.
    chegada = (
        atualizado_em
        + timedelta(seconds=restante_s)
    )

    # A interface da Olho Vivo trabalha com HH:MM. Arredondamos para cima
    # para não publicar uma chegada anterior ao instante realmente calculado.
    chegada_relogio = chegada.replace(
        second=0,
        microsecond=0,
    )

    if chegada > chegada_relogio:
        chegada_relogio += timedelta(
            minutes=1
        )

    resultado: dict[str, Any] = {
        "p": veiculo.get("p"),
        "t": chegada_relogio.strftime("%H:%M"),
        "ta": veiculo.get("ta"),
        "py": veiculo.get("py"),
        "px": veiculo.get("px"),
        "source": "live_gps_estimate",

        # Evidência interna útil para diagnóstico. O normalizador atual
        # descarta estes campos antes de chegar ao renderer.
        "gps_eta_restante_s": restante_s,
        "gps_distancia_shape_m": distancia_shape_m,
        "gps_shape_m": posicao_veiculo_m,
        "gps_alvo_shape_m": posicao_alvo_m,
        "gps_tempo_relativo_s": tempo_atual_s,
        "gps_alvo_tempo_relativo_s": tempo_alvo_s,
        "gps_trecho_de": anterior["nome"],
        "gps_trecho_para": posterior["nome"],
    }

    if veiculo.get("a") is not None:
        resultado["a"] = veiculo.get("a")

    return resultado


def _contextos_ao_vivo_do_gtfs(
    programacao: dict[str, Any],
    parada_id_esperada: str | None,
) -> list[dict[str, str]]:
    """Extrai os pares stop/headsign que o GTFS já validou para a consulta."""
    blocos = programacao.get("sentidos") or [programacao]
    contextos: list[dict[str, str]] = []
    vistos: set[tuple[str, str]] = set()
    for bloco in blocos:
        stop_id = str(bloco.get("parada_id") or "").strip()
        destino = str(bloco.get("destino") or "").strip()
        if parada_id_esperada and stop_id != str(parada_id_esperada):
            continue
        chave = (stop_id, destino)
        if not stop_id or not destino or chave in vistos:
            continue
        vistos.add(chave)
        contextos.append({
            "stop_id": stop_id,
            "parada": str(bloco.get("parada") or ""),
            "destino": destino,
            "sentido_gtfs": str(bloco.get("sentido_gtfs") or ""),
        })
    return contextos


def _viagens_gtfs_do_contexto(
    numero: str,
    contexto: dict[str, str],
) -> list[dict[str, Any]]:
    """Templates GTFS compatíveis com parada + destino já validados."""

    stop_id = str(
        contexto.get("stop_id") or ""
    ).strip()

    destino_esperado = (
        _normalizar_sentido_operacional(
            contexto.get("destino")
        )
    )

    if not stop_id or not destino_esperado:
        return []

    rotas = (
        _catalogo_gtfs()
        .get("linhas", {})
        .get(
            normalizar(numero).upper(),
            [],
        )
    )

    # Trips de serviços diferentes podem representar exatamente o mesmo
    # itinerário/perfil temporal. Não queremos tratá-las como ambíguas.
    unicas: dict[
        tuple[
            str,
            tuple[tuple[str, int], ...],
        ],
        dict[str, Any],
    ] = {}

    for rota in rotas:
        if not isinstance(rota, dict):
            continue

        for viagem in rota.get("viagens", []):
            if not isinstance(viagem, dict):
                continue

            destino = (
                _normalizar_sentido_operacional(
                    viagem.get("destino")
                )
            )

            if destino != destino_esperado:
                continue

            paradas = [
                parada
                for parada in viagem.get(
                    "paradas", []
                )
                if isinstance(parada, dict)
            ]

            if not any(
                str(parada.get("id") or "")
                == stop_id
                for parada in paradas
            ):
                continue

            try:
                perfil = tuple(
                    (
                        str(
                            parada.get("id")
                            or ""
                        ),
                        int(
                            parada.get(
                                "deslocamento",
                                0,
                            )
                        ),
                    )
                    for parada in sorted(
                        paradas,
                        key=lambda item: int(
                            item.get(
                                "sequencia",
                                0,
                            )
                        ),
                    )
                )
            except (TypeError, ValueError):
                continue

            assinatura = (
                str(
                    viagem.get("shape_id")
                    or ""
                ),
                perfil,
            )

            unicas.setdefault(
                assinatura,
                viagem,
            )

    return list(unicas.values())


def _plataformas_gtfs_ambíguas(
    numero: str,
    ponto: str,
    *,
    sentido_esperado: str | None,
    parada_id_esperada: str | None,
) -> bool:
    """Evita inferir lado da via a partir de um nome/local genérico.

    A programação continua podendo escolher uma parada próxima para ser útil,
    mas o relógio ao vivo exige uma plataforma inequívoca. Um embarque já
    escolhido pelo planejador ou um sentido explicitamente escolhido resolvem
    essa ambiguidade operacional.
    """
    if parada_id_esperada or sentido_esperado:
        return False
    rotas = _catalogo_gtfs().get("linhas", {}).get(normalizar(numero).upper(), [])
    coordenada = _coordenada_ponto(ponto)
    candidatas: list[tuple[dict[str, Any], str]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            destino = str(viagem.get("destino") or "").strip()
            for parada in viagem.get("paradas", []):
                if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                    candidatas.append((parada, destino))
    if not candidatas and coordenada:
        todas = [
            (parada, str(viagem.get("destino") or "").strip())
            for rota in rotas
            for viagem in rota.get("viagens", [])
            for parada in viagem.get("paradas", [])
        ]
        if todas:
            menor = min(_distancia_parada_gtfs(parada, coordenada) for parada, _ in todas)
            if menor <= RAIO_ACESSO_M:
                candidatas = [
                    (parada, destino) for parada, destino in todas
                    if _distancia_parada_gtfs(parada, coordenada)
                    <= min(menor + 40, RAIO_ACESSO_M)
                ]
    plataformas: dict[str, set[str]] = {}
    for parada, destino in candidatas:
        stop_id = str(parada.get("id") or "").strip()
        if stop_id:
            plataformas.setdefault(stop_id, set()).add(destino)
    destinos = {
        destino for destinos_plataforma in plataformas.values()
        for destino in destinos_plataforma if destino
    }
    return len(plataformas) > 1 and len(destinos) > 1


def _veiculos_ao_vivo_ordenados(
    veiculos: list[dict[str, Any]], horario_referencia: str | None,
    restricao_temporal: RestricaoTemporal | None = None,
) -> list[dict[str, Any]]:
    """Valida, ordena e deduplica ETAs antes de limitar os próximos três."""
    referencia = _instante_referencia_sptrans(horario_referencia)
    melhores_por_veiculo: dict[
        tuple[str, ...],
        tuple[tuple[float, float, float], float, dict[str, Any]],
    ] = {}
    for veiculo in veiculos:
        if not isinstance(veiculo, dict):
            continue
        horario = str(veiculo.get("t") or "").strip()
        segundos = _segundos_ate_eta_sptrans(horario, referencia)
        if segundos is None:
            continue
        if (
            restricao_temporal is not None
            and not restricao_temporal.contem(
                referencia + timedelta(seconds=segundos)
            )
        ):
            continue

        identificador = str(veiculo.get("p") or "").strip()
        chave = (
            ("veiculo", identificador)
            if identificador
            else (
                "eta", horario, str(veiculo.get("ta") or ""),
                str(veiculo.get("py") or ""), str(veiculo.get("px") or ""),
            )
        )
        # Mantém a evidência operacional disponível no resultado interno sem
        # despejar campos técnicos no renderer/naturalizador.
        preservado = {
            campo: veiculo.get(campo)
            for campo in ("p", "t", "ta", "py", "px", "a")
            if veiculo.get(campo) is not None
        }

        source = str(veiculo.get("source") or "live")

        confianca = _classificar_confianca_chegada(
            veiculo,
            horario_referencia,
            referencia=referencia,
            source=source,
        )

        if not confianca["valid"]:
            continue

        preservado.update({
            "source": source,
            "confidence": confianca["level"],
            "confidence_reasons": list(confianca["reasons"]),
        })

        atualizado_em = _instante_atualizacao_sptrans(
            veiculo.get("ta"), referencia,
        )
        qualidade = {
            "high": 3.0,
            "medium": 2.0,
            "low": 1.0,
        }.get(str(confianca["level"]), 0.0)
        preferencia = (
            qualidade,
            atualizado_em.timestamp() if atualizado_em else -math.inf,
            -segundos,
        )
        anterior = melhores_por_veiculo.get(chave)
        if anterior is None or preferencia > anterior[0]:
            melhores_por_veiculo[chave] = (
                preferencia, segundos, preservado,
            )

    ordenados = sorted(
        melhores_por_veiculo.items(),
        key=lambda item: (item[1][1], item[0]),
    )
    return [item[1][2] for item in ordenados[:3]]


def _obter_previsao_sptrans(
    numero: str,
    ponto: str,
    token: str,
    sentido_esperado: str | None = None,
    parada_id_esperada: str | None = None,
    datas_permitidas: tuple[date, ...] = (),
    restricao_temporal: RestricaoTemporal | None = None,
) -> dict[str, Any]:
    """Busca a previsão linha+ponto usando uma única sessão autenticada."""
    # O GTFS escolhe primeiro a plataforma e os sentidos válidos. O Olho Vivo
    # só pode complementar esse fato, nunca substituí-lo por nome/proximidade.
    programacao = _programacao_gtfs(
        numero,
        ponto,
        sentido_esperado=sentido_esperado,
        datas_permitidas=datas_permitidas,
        restricao_temporal=restricao_temporal,
    )
    if programacao.get("erro"):
        return programacao
    contextos_gtfs = _contextos_ao_vivo_do_gtfs(
        programacao, parada_id_esperada,
    )
    blocos_programados = programacao.get("sentidos") or [programacao]

    def programacao_do_contexto(contexto: dict[str, str]) -> dict[str, Any]:
        for bloco in blocos_programados:
            if not isinstance(bloco, dict):
                continue
            if (
                str(bloco.get("parada_id") or "") == contexto["stop_id"]
                and _normalizar_sentido_operacional(bloco.get("destino"))
                == _normalizar_sentido_operacional(contexto["destino"])
            ):
                return bloco
        return programacao if isinstance(programacao, dict) else {}

    def programacao_apos_ultimo_eta(
        contexto: dict[str, str],
        veiculos: list[dict[str, Any]],
        horario_referencia: str,
    ) -> dict[str, Any]:
        """Obtém referências GTFS posteriores ao último ETA já conhecido.

        A programação inicial contém apenas as três próximas passagens. Se um
        ETA ao vivo vier depois delas, reaproveitá-la não permite completar a
        resposta mista. Reconsultar o motor local a partir do último ETA evita
        aumentar indefinidamente o payload interno e mantém o limite público.
        """
        fallback = programacao_do_contexto(contexto)
        referencia = _instante_referencia_sptrans(horario_referencia)
        segundos_validos = [
            segundos
            for segundos in (
                _segundos_ate_eta_sptrans(
                    str(veiculo.get("t") or ""), referencia
                )
                for veiculo in veiculos
            )
            if segundos is not None
        ]
        if not segundos_validos:
            return fallback
        ultimo_eta = referencia + timedelta(seconds=max(segundos_validos))

        restricao_restante = restricao_temporal
        if restricao_restante is not None:
            inicio_restante = max(restricao_restante.inicio, ultimo_eta)
            if (
                restricao_restante.fim is not None
                and inicio_restante >= restricao_restante.fim
            ):
                return fallback
            restricao_restante = replace(
                restricao_restante,
                inicio=inicio_restante,
            )

        posterior = _programacao_gtfs(
            numero,
            ponto,
            agora=ultimo_eta,
            sentido_esperado=contexto["destino"],
            datas_permitidas=(
                datas_permitidas
                if restricao_restante is not None
                else (ultimo_eta.date(),)
            ),
            restricao_temporal=restricao_restante,
        )
        if posterior.get("erro"):
            return fallback
        if str(posterior.get("parada_id") or "") != contexto["stop_id"]:
            # O complemento não pode trocar de plataforma só porque outra do
            # mesmo sentido ficou geograficamente mais próxima na nova busca.
            return fallback
        if not any(
            posterior.get(campo)
            for campo in ("horarios", "estimativas", "faixas")
        ):
            return fallback
        return posterior

    def completar_contextos_sem_eta(
        blocos: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Mantém programação dos sentidos que não receberam ETA ao vivo."""
        presentes = {
            (
                str(bloco.get("parada_id_gtfs") or ""),
                _normalizar_sentido_operacional(bloco.get("destino")),
            )
            for bloco in blocos
        }
        completos = list(blocos)
        for contexto in contextos_gtfs:
            chave = (
                contexto["stop_id"],
                _normalizar_sentido_operacional(contexto["destino"]),
            )
            if chave in presentes:
                continue
            fallback = programacao_do_contexto(contexto)
            completos.append({
                "linha": str(fallback.get("linha") or numero),
                "destino": contexto["destino"],
                "parada": str(
                    fallback.get("parada") or contexto["parada"] or ponto
                ),
                "parada_id_gtfs": contexto["stop_id"],
                "veiculos": [],
                "horarios_programados": list(fallback.get("horarios", [])),
                "instantes_programados": list(fallback.get("instantes", [])),
                "estimativas_programadas": list(fallback.get("estimativas", [])),
                "faixas_programadas": list(fallback.get("faixas", [])),
                "programacao_incompleta": bool(
                    fallback.get("programacao_incompleta")
                ),
            })
        return completos
    if sentido_esperado and not any(
        _normalizar_sentido_operacional(contexto["destino"])
        == _normalizar_sentido_operacional(sentido_esperado)
        for contexto in contextos_gtfs
    ):
        programacao.update({
            "api_consultada": False,
            "aviso_api": (
                "O GTFS não identificou o sentido escolhido; nenhum ETA do "
                "sentido oposto foi usado."
            ),
        })
        return programacao
    if _plataformas_gtfs_ambíguas(
        numero,
        ponto,
        sentido_esperado=sentido_esperado,
        parada_id_esperada=parada_id_esperada,
    ):
        aviso_ambiguidade = (
            "Há mais de uma plataforma para sentidos diferentes nesse local; "
            "informe o sentido ou destino do ônibus para eu identificar o "
            "ponto de embarque correto."
        )
        programacao.update({
            "api_consultada": False,
            "aviso_api": aviso_ambiguidade,
            "aviso": aviso_ambiguidade,
        })
        return programacao
    if not contextos_gtfs:
        programacao.update({
            "api_consultada": False,
            "aviso_api": (
                "Não há uma associação GTFS inequívoca de parada e sentido; "
                "o horário exibido é apenas o programado."
            ),
        })
        return programacao

    session = requests.Session()
    if not _autenticar_sptrans(session, token):
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A autenticação da API Olho Vivo falhou."
            programacao["api_consultada"] = True
            programacao["falha_api"] = True
        return programacao

    try:
        linhas = cache(
            ("circulares", "linhas", normalizar(numero)),
            TTL_LINHAS,
            lambda: _linhas_sptrans(session, numero),
        )
        if not linhas:
            programacao["api_consultada"] = True
            return programacao

        tentativas: list[
            tuple[dict[str, Any], dict[str, str], dict[str, Any], str]
        ] = []
        ha_linha_no_sentido = False
        publicou_paradas_no_sentido = False
        payload_ao_vivo_desatualizado = False
        for linha_api in linhas:
            codigo_linha = int(linha_api["cl"])
            previsoes = cache(
                ("circulares", "previsoes-linha", codigo_linha),
                TTL_AO_VIVO,
                lambda codigo=codigo_linha: _previsoes_linha(session, codigo),
            )
            paradas = previsoes.get("ps", []) if isinstance(previsoes, dict) else []
            for contexto in contextos_gtfs:
                if not _linha_corresponde_ao_sentido_gtfs(
                    linha_api, contexto["destino"],
                ):
                    continue
                ha_linha_no_sentido = True
                publicou_paradas_no_sentido = (
                    publicou_paradas_no_sentido or bool(paradas)
                )
                for parada in _paradas_olho_vivo_do_stop_gtfs(
                    paradas, contexto["stop_id"],
                ):
                    tentativas.append((
                        linha_api, contexto, parada, str(previsoes.get("hr") or ""),
                    ))

        previsoes_por_sentido: list[dict[str, Any]] = []
        for linha_api, contexto, parada, horario_referencia in tentativas:
            if not _referencia_api_recente(horario_referencia):
                # Um payload antigo pode ter ``ta`` e ``t`` coerentes entre si
                # e ainda assim descrever o passado. O TTL local não garante
                # frescor upstream.
                payload_ao_vivo_desatualizado = True
                continue
            veiculos = _veiculos_ao_vivo_ordenados(
                list(parada.get("vs", [])), horario_referencia,
                restricao_temporal,
            )
            if not veiculos:
                continue
            fallback_programado = programacao_apos_ultimo_eta(
                contexto, veiculos, horario_referencia
            )
            previsoes_por_sentido.append({
                "hr": horario_referencia,
                "linha": f"{linha_api.get('lt', numero)}-{linha_api.get('tl', 10)}",
                "sentido": linha_api.get("sl"),
                "destino": contexto["destino"],
                "parada_id_gtfs": contexto["stop_id"],
                "parada": contexto["parada"] or parada.get("np") or ponto,
                "endereco": parada.get("ed", ""),
                "veiculos": veiculos,
                "horarios_programados": list(fallback_programado.get("horarios", [])),
                "instantes_programados": list(fallback_programado.get("instantes", [])),
                "estimativas_programadas": list(
                    fallback_programado.get("estimativas", [])
                ),
                "faixas_programadas": list(fallback_programado.get("faixas", [])),
                "programacao_incompleta": bool(
                    fallback_programado.get("programacao_incompleta")
                ),
                "operacional": {
                    "origem": "live",
                    "hr": horario_referencia,
                    "linha_sptrans": linha_api.get("cl"),
                    "sentido_sptrans": linha_api.get("sl"),
                    "headsign_gtfs": contexto["destino"],
                    "sentido_gtfs": contexto["sentido_gtfs"],
                    "parada_gtfs": {
                        "stop_id": contexto["stop_id"],
                        "nome": contexto["parada"],
                    },
                    "parada_olho_vivo": {
                        campo: parada.get(campo)
                        for campo in ("cp", "np", "ed", "py", "px")
                        if parada.get(campo) is not None
                    },
                    "veiculos": veiculos,
                },
            })
        if previsoes_por_sentido:
            previsoes_por_sentido = completar_contextos_sem_eta(
                previsoes_por_sentido
            )
            resultado: dict[str, Any] = {
                "tipo": "previsao",
                "previsoes_por_sentido": previsoes_por_sentido,
                "api_consultada": True,
            }
            # Compatibilidade com o uso de ETA ao vivo no planejador de rota,
            # que sempre pede um único sentido já validado pelo GTFS.
            if len(previsoes_por_sentido) == 1:
                resultado.update(previsoes_por_sentido[0])
            return resultado

        if not ha_linha_no_sentido:
            programacao.update({
                "api_consultada": True,
                "aviso_api": (
                    "A API Olho Vivo não identificou o sentido escolhido; "
                    "nenhum ETA do sentido oposto foi usado."
                ),
            })
            return programacao

        previsoes_gps_por_sentido: list[
            dict[str, Any]
        ] = []

        veiculos_ativos: dict[
            str,
            dict[str, Any],
        ] = {}

        horarios_referencia: list[str] = []


        for contexto in contextos_gtfs:
            viagens_contexto = (
                _viagens_gtfs_do_contexto(
                    numero,
                    contexto,
                )
            )


            candidatos_gps: list[
                dict[str, Any]
            ] = []

            horarios_contexto: list[str] = []

            linha_contexto: (
                dict[str, Any] | None
            ) = None

            for linha_api in linhas:
                # Nunca misturar GPS do sentido oposto.
                if not _linha_corresponde_ao_sentido_gtfs(
                    linha_api,
                    contexto["destino"],
                ):
                    continue

                if linha_contexto is None:
                    linha_contexto = linha_api

                codigo_linha = int(
                    linha_api["cl"]
                )

                posicoes = cache(
                    (
                        "circulares",
                        "posicoes-linha",
                        codigo_linha,
                    ),
                    TTL_AO_VIVO,
                    lambda codigo=codigo_linha: (
                        _posicoes_linha(
                            session,
                            codigo,
                        )
                    ),
                )

                horario_referencia = str(
                    posicoes.get("hr") or ""
                )

                if not _referencia_api_recente(horario_referencia):
                    payload_ao_vivo_desatualizado = True
                    continue

                if horario_referencia:
                    horarios_contexto.append(
                        horario_referencia
                    )
                    horarios_referencia.append(
                        horario_referencia
                    )

                for veiculo in posicoes.get(
                    "vs",
                    [],
                ):
                    if not isinstance(
                        veiculo,
                        dict,
                    ):
                        continue

                    identificador = str(
                        veiculo.get("p")
                        or id(veiculo)
                    )

                    veiculos_ativos[
                        identificador
                    ] = veiculo

                    # A contagem operacional independe de haver geometria
                    # GTFS suficiente para derivar ETA. Sem essa separação,
                    # um fallback de programação reportava zero veículos mesmo
                    # quando a própria API acabara de listá-los.
                    if not viagens_contexto:
                        continue

                    # Um mesmo contexto pode ter mais de um template
                    # GTFS possível. Tentamos todos, mas só usamos o
                    # veículo quando exatamente um produz ETA válido.
                    estimativas_validas: list[
                        dict[str, Any]
                    ] = []

                    for viagem in viagens_contexto:
                        estimativa = (
                            _eta_derivado_de_gps(
                                viagem,
                                contexto["stop_id"],
                                veiculo,
                                horario_referencia,
                            )
                        )

                        if estimativa is not None:
                            estimativas_validas.append(
                                estimativa
                            )

                    if len(estimativas_validas) == 1:
                        candidatos_gps.append(
                            estimativas_validas[0]
                        )

                    # len == 0:
                    #   veículo fora do shape, já passou,
                    #   GPS inválido etc.
                    #
                    # len > 1:
                    #   mais de um template continua plausível;
                    #   preferimos não inventar qual é o correto.


            if (
                not candidatos_gps
                or linha_contexto is None
            ):
                continue

            horario_contexto = (
                horarios_contexto[-1]
                if horarios_contexto
                else ""
            )

            veiculos_estimados = (
                _veiculos_ao_vivo_ordenados(
                    candidatos_gps,
                    horario_contexto,
                    restricao_temporal,
                )
            )

            if not veiculos_estimados:
                continue

            fallback_programado = programacao_apos_ultimo_eta(
                contexto,
                veiculos_estimados,
                horario_contexto,
            )

            previsoes_gps_por_sentido.append({
                "hr": horario_contexto,
                "linha": (
                    f"{linha_contexto.get('lt', numero)}"
                    f"-{linha_contexto.get('tl', 10)}"
                ),
                "sentido": linha_contexto.get(
                    "sl"
                ),
                "destino": contexto["destino"],
                "parada_id_gtfs": contexto["stop_id"],
                "parada": (
                    contexto["parada"]
                    or ponto
                ),
                "endereco": "",
                "veiculos": veiculos_estimados,

                "horarios_programados": list(
                    fallback_programado.get(
                        "horarios",
                        [],
                    )
                ),
                "instantes_programados": list(
                    fallback_programado.get(
                        "instantes",
                        [],
                    )
                ),
                "estimativas_programadas": list(
                    fallback_programado.get(
                        "estimativas",
                        [],
                    )
                ),
                "faixas_programadas": list(
                    fallback_programado.get("faixas", [])
                ),

                "programacao_incompleta": bool(
                    fallback_programado.get(
                        "programacao_incompleta"
                    )
                ),

                "operacional": {
                    "origem": (
                        "live_gps_estimate"
                    ),
                    "hr": horario_contexto,
                    "linha_sptrans": (
                        linha_contexto.get("cl")
                    ),
                    "sentido_sptrans": (
                        linha_contexto.get("sl")
                    ),
                    "headsign_gtfs": (
                        contexto["destino"]
                    ),
                    "sentido_gtfs": (
                        contexto["sentido_gtfs"]
                    ),
                    "parada_gtfs": {
                        "stop_id": (
                            contexto["stop_id"]
                        ),
                        "nome": (
                            contexto["parada"]
                        ),
                    },
                    "veiculos": (
                        veiculos_estimados
                    ),
                },
            })


        if previsoes_gps_por_sentido:
            previsoes_gps_por_sentido = completar_contextos_sem_eta(
                previsoes_gps_por_sentido
            )
            resultado_gps: dict[
                str,
                Any,
            ] = {
                "tipo": "previsao",
                "previsoes_por_sentido": (
                    previsoes_gps_por_sentido
                ),
                "api_consultada": True,
            }

            if (
                len(
                    previsoes_gps_por_sentido
                )
                == 1
            ):
                resultado_gps.update(
                    previsoes_gps_por_sentido[
                        0
                    ]
                )

            return resultado_gps


        # A API tinha veículos, mas nenhum deles pôde
        # produzir um ETA derivado seguro.
        programacao.update({
            "hr": (
                horarios_referencia[-1]
                if horarios_referencia
                else ""
            ),
            "veiculos_ativos": len(
                veiculos_ativos
            ),
            "api_consultada": True,
            "aviso_api": (
                "A API Olho Vivo respondeu com uma referência temporal antiga; "
                "nenhum ETA desse payload foi usado."
                if payload_ao_vivo_desatualizado else
                "A API Olho Vivo não publicou uma parada com associação "
                "GTFS inequívoca para esse ponto e sentido; nenhum ETA foi usado."
                if publicou_paradas_no_sentido and not tentativas else
                "A API Olho Vivo não publicou um ETA e nenhuma posição GPS "
                "disponível permitiu calcular uma chegada com segurança para "
                "essa parada e esse sentido."
            ),
        })

        return programacao
    except (requests.RequestException, ValueError, TypeError, KeyError) as err:
        print(f"[circulares] Erro ao consultar previsão: {type(err).__name__}: {err}")
        if not programacao.get("erro"):
            programacao["aviso_api"] = "A API Olho Vivo não respondeu agora."
            programacao["api_consultada"] = True
            programacao["falha_api"] = True
        return programacao
