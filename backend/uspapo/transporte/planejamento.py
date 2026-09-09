"""Construção, comparação e ranking dos trajetos diretos."""

from datetime import datetime, timedelta
import math
from typing import Any

from uspapo import gtfs_sptrans
from uspapo.ferramentas import normalizar
from uspapo.intencao_transporte import RestricaoTemporal
from uspapo.operacao_sptrans import (
    aviso_programacao_incompleta,
    horario_gtfs_confiavel,
    parada_atendida_na_data,
)
from uspapo.transporte.programacao import (
    FUSO_SP,
    RAIO_ACESSO_M,
    _coordenada_ponto,
    _chave_local,
    _espera_media_gtfs,
)

# As caminhadas abaixo são estimadas a partir da distância ao ponto, e não de
# uma malha de calçadas. Diferenças menores que dois minutos não justificam
# anunciar uma plataforma como objetivamente melhor por essa aproximação.
MARGEM_INCERTEZA_CAMINHADA_S = 2 * 60

_catalogo_gtfs = gtfs_sptrans.catalogo
_servico_ativo = gtfs_sptrans.servico_ativo
_distancia_parada_gtfs = gtfs_sptrans.distancia_m


def _chave_ranking_rota(candidato: dict[str, Any]) -> tuple[Any, ...]:
    """Desempate estável para planos diretos já estruturalmente válidos.

    O tempo total continua sendo o critério primário. A caminhada vem em
    seguida porque é a parte menos precisa do modelo; em empate prático ela
    evita escolher uma plataforma mais distante por ordem do arquivo GTFS.
    """
    caminhada = float(candidato["caminhada_origem_m"]) + float(
        candidato["caminhada_destino_m"]
    )
    # Uma partida explicitamente tabelada é um pouco mais informativa que a
    # metade de uma faixa de frequência, mas só é usada depois do total e da
    # caminhada, nunca para inverter uma opção materialmente mais rápida.
    qualidade_programacao = 1 if candidato.get("intervalo_programado_s") is None else 0
    return (
        float(candidato.get("total_estimado_s") or candidato.get("ranking_s") or math.inf),
        caminhada,
        -qualidade_programacao,
        normalizar(candidato.get("linha", "")),
        normalizar(candidato.get("sentido", "")),
        str(candidato.get("embarque_id", "")),
        str(candidato.get("desembarque_id", "")),
    )

def _planejar_trajeto_gtfs(
    origem: str,
    destino: str,
    agora: datetime | None = None,
    modo_solicitado: str | None = None,
    restricao_temporal: RestricaoTemporal | None = None,
) -> dict[str, Any]:
    """Ranqueia viagens diretas por caminhada, espera programada e tempo a bordo."""
    coordenada_origem = _coordenada_ponto(origem)
    coordenada_destino = _coordenada_ponto(destino)
    if not coordenada_origem or not coordenada_destino:
        return {
            "erro": (
                "Não reconheci a origem ou o destino com precisão suficiente para "
                "comparar os ônibus."
            )
        }

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    catalogo = _catalogo_gtfs()
    candidatos: list[dict[str, Any]] = []
    candidatos_sem_horario: list[dict[str, Any]] = []
    limite_caminhada = RAIO_ACESSO_M
    velocidade_caminhada_m_min = 80
    chave_origem = _chave_local(origem)
    chave_destino = _chave_local(destino)
    ambos_dentro_campus = bool(
        chave_origem
        and chave_destino
        and chave_origem != "metro_butanta"
        and chave_destino != "metro_butanta"
    )
    # A janela de planejamento cobre a proximidade da meia-noite (inclusive
    # viagens 24:xx do dia de serviço anterior), mas não transforma a primeira
    # faixa do dia seguinte em espera útil para uma pergunta feita à tarde.
    fim_horizonte = instante + timedelta(hours=4)
    if restricao_temporal is not None and restricao_temporal.fim is not None:
        fim_horizonte = min(fim_horizonte, restricao_temporal.fim)

    for rotas in catalogo.get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                embarques = [
                    parada for parada in viagem.get("paradas", [])
                    if _distancia_parada_gtfs(parada, coordenada_origem)
                    <= limite_caminhada
                ]
                desembarques = [
                    parada for parada in viagem.get("paradas", [])
                    if _distancia_parada_gtfs(parada, coordenada_destino)
                    <= limite_caminhada
                ]
                for embarque in embarques:
                    for desembarque in desembarques:
                        if int(desembarque["sequencia"]) <= int(embarque["sequencia"]):
                            continue
                        linha = str(rota.get("linha", ""))
                        # Depois da meia-noite, 00:15 pode pertencer à grade do
                        # serviço de ontem (por exemplo, 24:15 no GTFS). Nunca
                        # assumimos que a data civil atual é a data de serviço.
                        datas_servico = (instante.date(),)
                        if instante.hour < 6:
                            # A tolerância é deliberadamente limitada à
                            # madrugada: fora dela, aceitar a grade de ontem
                            # faria uma operação de fim de semana parecer ativa.
                            datas_servico = (
                                instante.date() - timedelta(days=1),
                                instante.date(),
                            )
                        datas_compativeis = [
                            dia for dia in datas_servico
                            if (
                                parada_atendida_na_data(linha, embarque, dia)
                                and parada_atendida_na_data(linha, desembarque, dia)
                                and _servico_ativo(
                                    catalogo, str(viagem.get("servico", "")), dia
                                )
                            )
                        ]
                        if not datas_compativeis:
                            continue
                        caminhada_origem = _distancia_parada_gtfs(
                            embarque, coordenada_origem
                        )
                        caminhada_destino = _distancia_parada_gtfs(
                            desembarque, coordenada_destino
                        )
                        minutos_ate_ponto = caminhada_origem / velocidade_caminhada_m_min
                        pronto_para_embarcar = instante + timedelta(
                            minutes=minutos_ate_ponto
                        )
                        viagem_s = (
                            int(desembarque["deslocamento"])
                            - int(embarque["deslocamento"])
                        )
                        viagem_min = viagem_s / 60
                        trecho = [
                            parada
                            for parada in viagem.get("paradas", [])
                            if int(embarque["sequencia"])
                            <= int(parada["sequencia"])
                            <= int(desembarque["sequencia"])
                        ]
                        passa_metro = any(
                            "metro butanta" in normalizar(parada.get("nome", ""))
                            for parada in trecho
                        )
                        # Uma viagem entre dois destinos internos nunca deve
                        # sair do campus até o terminal para depois voltar. É
                        # exatamente a regressão Central/Reitoria -> Biênio.
                        if ambos_dentro_campus and passa_metro:
                            continue
                        caminhada_origem_s = minutos_ate_ponto * 60
                        caminhada_destino_s = (
                            caminhada_destino / velocidade_caminhada_m_min * 60
                        )
                        candidato_base = {
                            "linha": linha,
                            "nome": rota.get("nome", ""),
                            "viagem_id": str(viagem.get("id", "")),
                            "sentido": viagem.get("destino", ""),
                            "embarque": embarque.get("nome", ""),
                            "embarque_id": str(embarque.get("id", "")),
                            "embarque_sequencia": int(embarque["sequencia"]),
                            "desembarque": desembarque.get("nome", ""),
                            "desembarque_id": str(desembarque.get("id", "")),
                            "desembarque_sequencia": int(desembarque["sequencia"]),
                            "caminhada_origem_m": round(caminhada_origem),
                            "caminhada_destino_m": round(caminhada_destino),
                            "caminhada_origem_s": caminhada_origem_s,
                            "caminhada_destino_s": caminhada_destino_s,
                            "viagem_s": viagem_s,
                            "viagem_min": round(viagem_min),
                            "passa_metro_butanta": passa_metro,
                        }
                        espera, intervalo = _espera_media_gtfs(
                            catalogo,
                            viagem,
                            embarque,
                            pronto_para_embarcar,
                            ate=fim_horizonte,
                        )
                        if not math.isfinite(espera):
                            candidatos_sem_horario.append({
                                **candidato_base,
                                "modo": "onibus_sem_horario",
                                "espera_programada_s": None,
                                "intervalo_programado_s": None,
                                "total_estimado_s": None,
                                "espera_programada_min": None,
                                "intervalo_programado_min": None,
                                "total_estimado_min": None,
                                "ranking_s": (
                                    caminhada_origem_s
                                    + viagem_s
                                    + caminhada_destino_s
                                ),
                            })
                            continue
                        espera_s = espera * 60
                        total_s = (
                            caminhada_origem_s + espera_s + viagem_s
                            + caminhada_destino_s
                        )
                        candidatos.append({
                            **candidato_base,
                            "modo": "onibus",
                            "espera_programada_s": espera_s,
                            "intervalo_programado_s": (
                                intervalo * 60 if intervalo is not None else None
                            ),
                            "total_estimado_s": total_s,
                            "espera_programada_min": round(espera),
                            "intervalo_programado_min": (
                                round(intervalo) if intervalo is not None else None
                            ),
                            "total_estimado_min": round(total_s / 60),
                            # A confiabilidade operacional deixa de ser um
                            # interruptor: se a grade é interpretável, ela
                            # ainda participa do plano, com rótulo de cautela.
                            "espera_source": (
                                "scheduled_estimate"
                                if intervalo is not None else "scheduled"
                            ),
                            "espera_confidence": (
                                "scheduled"
                                if any(
                                    horario_gtfs_confiavel(linha, dia)
                                    for dia in datas_compativeis
                                )
                                else "scheduled_uncertain"
                            ),
                        })

    # Não colapsar uma linha inteira em uma só opção: plataformas/sentidos
    # distintos podem ser candidatos válidos. Cada candidato abaixo vem de
    # uma mesma viagem GTFS e portanto já satisfaz sequência desembarque >
    # embarque, sem jamais cruzar o outro sentido.
    melhores_por_itinerario: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for candidato in candidatos:
        chave_itinerario = (
            str(candidato["linha"]), str(candidato["sentido"]),
            str(candidato["embarque_id"]), str(candidato["desembarque_id"]),
        )
        guardado = melhores_por_itinerario.get(chave_itinerario)
        if guardado is None or _chave_ranking_rota(candidato) < _chave_ranking_rota(guardado):
            melhores_por_itinerario[chave_itinerario] = candidato
    opcoes = sorted(
        melhores_por_itinerario.values(), key=_chave_ranking_rota,
    )
    melhores_sem_horario: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for candidato in candidatos_sem_horario:
        chave_itinerario = (
            str(candidato["linha"]), str(candidato["sentido"]),
            str(candidato["embarque_id"]), str(candidato["desembarque_id"]),
        )
        guardado = melhores_sem_horario.get(chave_itinerario)
        if guardado is None or _chave_ranking_rota(candidato) < _chave_ranking_rota(guardado):
            melhores_sem_horario[chave_itinerario] = candidato
    opcoes_sem_horario = sorted(
        melhores_sem_horario.values(), key=_chave_ranking_rota,
    )
    distancia_reta = _distancia_parada_gtfs(
        {
            "latitude": coordenada_destino[0],
            "longitude": coordenada_destino[1],
        },
        coordenada_origem,
    )
    # Ruas e calçadas raramente seguem a linha reta; 15% é uma aproximação
    # conservadora para decidir apenas se vale avisar que caminhar pode vencer.
    caminhada_direta_m = round(distancia_reta * 1.15)
    caminhada_direta_min = max(
        1, round(caminhada_direta_m / velocidade_caminhada_m_min)
    )
    plano_base = {
        "origem": chave_origem or origem,
        "destino": chave_destino or destino,
        "horario_referencia": instante.strftime("%H:%M"),
        "caminhada_direta_m": caminhada_direta_m,
        "caminhada_direta_min": caminhada_direta_min,
        "comparacao_caminhada_aproximada": bool(
            len(opcoes) > 1
            and abs(
                float(opcoes[0]["total_estimado_s"])
                - float(opcoes[1]["total_estimado_s"])
            ) <= MARGEM_INCERTEZA_CAMINHADA_S
        ),
    }

    caminhada = {
        "modo": "a_pe",
        "distancia_aproximada_m": caminhada_direta_m,
        "total_estimado_min": caminhada_direta_min,
    }
    if modo_solicitado == "onibus":
        if opcoes:
            return {
                **plano_base,
                "melhor": opcoes[0],
                "alternativas": opcoes[1:3],
                "alternativas_sem_horario": opcoes_sem_horario[:3],
            }
        if opcoes_sem_horario:
            return {
                **plano_base,
                "melhor": opcoes_sem_horario[0],
                "alternativas": opcoes_sem_horario[1:3],
                "ranking_temporal": (
                    "indeterminado" if len(opcoes_sem_horario) > 1 else "indisponivel"
                ),
                "aviso": aviso_programacao_incompleta(
                    str(opcoes_sem_horario[0]["linha"]), instante.date()
                ),
            }
        return {
            **plano_base,
            "melhor": caminhada,
            "alternativas": [],
            "aviso": (
                "Não encontrei uma linha direta em operação nesse período; "
                "a caminhada aparece somente como alternativa."
            ),
            "modo_solicitado": "onibus",
        }
    if not opcoes:
        # A falta de uma grade temporal confiável não transforma uma viagem
        # direta e operacional em inexistente. Mantém-na como melhor opção
        # factual para que o chamador possa tentar ETA ao vivo; sem ETA, não
        # há base para declarar a caminhada mais rápida.
        if opcoes_sem_horario:
            return {
                **plano_base,
                "melhor": opcoes_sem_horario[0],
                "alternativas": opcoes_sem_horario[1:3],
                "ranking_temporal": (
                    "indeterminado" if len(opcoes_sem_horario) > 1 else "indisponivel"
                ),
                "caminhada_alternativa": caminhada,
                "aviso": (
                    "Há linha direta em operação, mas faltam horários GTFS "
                    "confiáveis para comparar o tempo total com a caminhada."
                ),
            }
        return {
            **plano_base,
            "melhor": caminhada,
            "aviso": (
                "Não encontrei uma linha direta; a opção coberta é caminhar."
            ),
            "alternativas": [],
        }
    if caminhada_direta_min + 2 < opcoes[0]["total_estimado_min"]:
        return {
            **plano_base,
            "melhor": caminhada,
            "alternativas": opcoes[:3],
        }
    return {
        **plano_base,
        "melhor": opcoes[0],
        "alternativas": opcoes[1:3],
    }
