"""Ônibus que atendem a USP usando dados oficiais e gratuitos da SPTrans.

A API Olho Vivo fornece posições e, quando disponíveis, previsões em tempo
real. Como o endpoint de paradas cobre apenas corredores e às vezes devolve
zero previsões dentro da USP, o módulo usa o GTFS oficial como fallback para
paradas e horários programados, deixando explícito quando o resultado não é
uma estimativa ao vivo.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import os
import re
from pathlib import Path
from typing import Any

import requests

from uspapo import gtfs_sptrans, olhovivo
from uspapo.ferramentas import RespostaFerramenta, Registro, cache, normalizar
from uspapo.locais_usp import (
    dados_local,
)
from uspapo.intencao_transporte import (
    analisar_intencao_transporte,
)
from uspapo.consulta_transporte import (
    TransitQuery,
    interpretar_consulta_transporte,
    resultado_consulta_transporte,
)
from uspapo.operacao_sptrans import (
    aviso_programacao_incompleta,
    fontes_operacionais,
)
from uspapo.transporte_resposta import (
    AlternativaPublica,
    EstimativaEspera,
    FaixaPassagemProgramada,
    LocalPublico,
    PassagensPorSentido,
    PrevisaoChegada,
    ResultadoChegada,
    ResultadoTrajeto,
    facetas_da_pergunta,
    renderizar_chegada,
    renderizar_trajeto,
)
from uspapo.transporte.previsoes import (
    TTL_AO_VIVO,
    _obter_previsao_sptrans,
    _paradas_olho_vivo_do_stop_gtfs,
    _instante_referencia_sptrans,
    _referencia_api_recente,
    _melhor_eta_ao_vivo,
    _espera_ao_vivo,
    _segundos_ate_eta_sptrans,
    _classificar_confianca_chegada,
    _eta_derivado_de_gps,
    _plataformas_gtfs_ambíguas,
    _veiculos_ao_vivo_ordenados,
)
from uspapo.transporte.planejamento import (
    _chave_ranking_rota,
    _planejar_trajeto_gtfs,
)
from uspapo.transporte.programacao import (
    FUSO_SP,
    RAIO_ACESSO_M,
    _sentido_explicito_da_pergunta,
    _coordenada_ponto,
    _nota_atualizacao_gtfs,
    _aviso_gtfs_se_necessario,
    _programacao_gtfs,
    _resumo_gtfs,
    _atendimento_linha_na_parada_gtfs,
    _linhas_por_ponto_gtfs,
    _espera_media_gtfs,
)

FONTE_API = "https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/"
FONTE_GTFS = "https://www.sptrans.com.br/desenvolvedores/"
FONTE_PLANOPER = (
    "https://www.sptrans.com.br/itinerarios/"
)
ARQUIVO_GTFS = Path(__file__).resolve().parents[1] / "dados_sptrans.json"



def _distancia_aproximada(parada: dict[str, Any], coordenada: tuple[float, float]) -> float:
    """Distância local aproximada em metros, suficiente para ordenar paradas."""
    lat, lon = coordenada
    py, px = float(parada.get("py", 0)), float(parada.get("px", 0))
    dy = (py - lat) * 111_320
    dx = (px - lon) * 111_320 * math.cos(math.radians(lat))
    return math.hypot(dx, dy)


def _ordenar_paradas(
    paradas: list[dict[str, Any]],
    ponto: str,
    parada_id_esperada: str | None = None,
) -> list[dict[str, Any]]:
    if parada_id_esperada:
        # Para tempo real, stop GTFS conhecido elimina qualquer fallback por
        # texto ou coordenada: estes métodos não distinguem plataformas.
        return _paradas_olho_vivo_do_stop_gtfs(paradas, parada_id_esperada)

    textuais = [
        parada for parada in paradas
        if (
            _mesmo_nome(ponto, str(parada.get("np", "")))
            or _mesmo_nome(ponto, str(parada.get("ed", "")))
        )
    ]
    if textuais:
        return textuais

    coordenada = _coordenada_ponto(ponto)
    if coordenada:
        return [
            parada
            for parada in sorted(
                paradas,
                key=lambda item: _distancia_aproximada(item, coordenada),
            )
            if _distancia_aproximada(parada, coordenada) <= RAIO_ACESSO_M
        ]
    return []


def _pergunta_pede_atendimento_de_linha(pergunta: str | None) -> bool:
    """Distingue "passa nessa parada" de pedir a lista do itinerário."""
    texto = normalizar(pergunta or "")
    return bool(re.search(r"\b(?:passa|atende)\b", texto)) or bool(
        re.search(r"\btem\s+(?:a\s+)?(?:linha\s+)?[\d]", texto)
    )


def _local_publico(chave: str, dados: dict[str, Any] | None) -> LocalPublico:
    if not dados:
        nome = str(chave).replace("_", " ").strip().title()
        return LocalPublico(
            chave=chave,
            nome=nome,
            nome_curto=nome,
            localizacao="na região da Cidade Universitária",
        )
    return LocalPublico(
        chave=chave,
        nome=str(dados.get("nome") or chave),
        nome_curto=str(dados.get("nome_curto") or dados.get("nome") or chave),
        localizacao=str(dados.get("localizacao") or "na Cidade Universitária"),
    )


def _resultado_trajeto_publico(
    plano: dict[str, Any],
    previsao: dict[str, Any] | None = None,
) -> ResultadoTrajeto:
    melhor = plano["melhor"]
    api_consultada = bool(
        previsao
        and (
            previsao.get("api_consultada")
            or previsao.get("tipo") == "previsao"
            or "veiculos" in previsao
        )
    )
    intervalo_s = melhor.get("intervalo_programado_s")
    espera_programada_s = float(melhor["espera_programada_s"])
    if intervalo_s is not None:
        espera = EstimativaEspera(
            base="frequencia_media",
            esperada_s=espera_programada_s,
            minima_s=0,
            # Antes do início de uma faixa, a espera inclui o tempo até a
            # janela mais a incerteza de um headway. Dentro dela, o limite
            # continua sendo o próprio intervalo.
            maxima_s=max(float(intervalo_s), espera_programada_s),
            intervalo_s=float(intervalo_s),
        )
    else:
        espera = EstimativaEspera(
            base="programacao_exata",
            esperada_s=espera_programada_s,
            minima_s=espera_programada_s,
            maxima_s=espera_programada_s,
        )
    espera_source = str(
        melhor.get("espera_source")
        or ("scheduled_estimate" if intervalo_s is not None else "scheduled")
    )
    confianca_espera = str(melhor.get("espera_confidence") or "scheduled")
    ao_vivo = _melhor_eta_ao_vivo(
        previsao or {}, float(melhor["caminhada_origem_s"])
    )
    if ao_vivo:
        espera, confianca_espera = ao_vivo
        espera_source = "live"

    chave_origem = str(plano.get("origem") or "")
    chave_destino = str(plano.get("destino") or "")
    return ResultadoTrajeto(
        origem=_local_publico(chave_origem, dados_local(chave_origem)),
        destino=_local_publico(chave_destino, dados_local(chave_destino)),
        linha=str(melhor["linha"]),
        sentido=str(melhor["sentido"]),
        embarque=str(melhor["embarque"]),
        desembarque=str(melhor["desembarque"]),
        caminhada_origem_m=float(melhor["caminhada_origem_m"]),
        caminhada_destino_m=float(melhor["caminhada_destino_m"]),
        caminhada_origem_s=float(melhor["caminhada_origem_s"]),
        caminhada_destino_s=float(melhor["caminhada_destino_s"]),
        viagem_s=float(melhor["viagem_s"]),
        espera=espera,
        previsao_consultada=api_consultada,
        veiculos_ativos=(
            int(previsao["veiculos_ativos"])
            if (
                api_consultada
                and previsao
                and previsao.get("veiculos_ativos") is not None
            )
            else None
        ),
        alternativas=tuple(
            AlternativaPublica(
                linha=str(item["linha"]),
                sentido=str(item["sentido"]),
                total_s=float(item["total_estimado_s"]),
            )
            for item in plano.get("alternativas", [])
            if item.get("modo") == "onibus"
        ),
        aviso=" ".join(filter(None, (
            _aviso_gtfs_se_necessario(),
            (
                "As opções diretas estão muito próximas; a diferença de "
                "caminhada é apenas aproximada, não uma rota de pedestres."
                if plano.get("comparacao_caminhada_aproximada") else ""
            ),
        ))),
        embarque_id=str(melhor.get("embarque_id") or "") or None,
        desembarque_id=str(melhor.get("desembarque_id") or "") or None,
        espera_source=espera_source,
        espera_confidence=confianca_espera,
        tempo_bordo_source="gtfs_scheduled",
    )


def _resultado_chegada_publico(
    previsao: dict[str, Any],
    *,
    api_consultada: bool,
    ponto_pedido: str,
) -> ResultadoChegada:
    """Traduz respostas SPTrans/GTFS para um contrato estável de apresentação."""
    if previsao.get("tipo") in {"programacao", "sem_servico", "sem_passagem"}:
        dados_sentidos = previsao.get("sentidos") or [previsao]
        sentidos: list[PassagensPorSentido] = []
        for programacao in dados_sentidos:
            faixas = tuple(
                FaixaPassagemProgramada(
                    referencia=str(faixa.get("proxima_referencia_texto", "")),
                    referencia_instante=str(
                        faixa.get("proxima_referencia")
                        or faixa.get("proxima_janela_inicio", "")
                    ),
                    inicio=str(faixa.get("proxima_janela_inicio", "")),
                    fim=str(faixa.get("proxima_janela_fim", "")),
                    inicio_texto=str(
                        faixa.get("proxima_janela_inicio_texto", "")
                    ),
                    fim_texto=str(faixa.get("proxima_janela_fim_texto", "")),
                    intervalo_min=max(1, int(faixa.get("intervalo_min", 1))),
                    espera_tipica_min=max(
                        0, int(faixa.get("espera_tipica_min", 0))
                    ),
                    espera_maxima_min=max(
                        0, int(faixa.get("espera_maxima_min", 0))
                    ),
                    ativa_agora=bool(faixa.get("ativa_agora")),
                )
                for faixa in programacao.get("faixas", [])
            )
            sentidos.append(PassagensPorSentido(
                linha=str(programacao.get("linha") or previsao.get("linha") or ""),
                parada=str(programacao.get("parada") or ponto_pedido),
                sentido=str(programacao.get("destino") or ""),
                horarios_programados=tuple(
                    str(item) for item in programacao.get("horarios", [])
                ),
                instantes_programados=tuple(
                    str(item) for item in programacao.get("instantes", [])
                ),
                estimativas_programadas=tuple(
                    PrevisaoChegada(
                        horario=str(item["horario"]),
                        acessivel=(
                            bool(item["acessivel"])
                            if item.get("acessivel") is not None
                            else None
                        ),
                        source=str(
                            item.get("source")
                            or "scheduled_estimate"
                        ),
                        confidence=str(
                            item.get("confidence")
                            or "scheduled"
                        ),
                        intervalo_programado_min=(
                            int(item["intervalo_min"])
                            if item.get("intervalo_min") is not None
                            else None
                        ),
                        instante=str(item.get("instante") or "") or None,
                    )
                    for item in programacao.get("estimativas", [])
                    if isinstance(item, dict)
                    and item.get("horario")
                ),
                faixas_programadas=faixas,
                programacao_confidence=(
                    "scheduled_uncertain"
                    if programacao.get("programacao_incompleta")
                    else "scheduled"
                ),
            ))
        tem_programacao_util = any(
            item.horarios_programados
            or item.estimativas_programadas
            or item.faixas_programadas
            for item in sentidos
        )
        return ResultadoChegada(
            linha=str(previsao.get("linha") or sentidos[0].linha),
            parada=str(previsao.get("parada") or sentidos[0].parada),
            sentidos=tuple(sentidos),
            api_consultada=api_consultada,
            api_falhou=bool(previsao.get("falha_api")),
            observado_em=str(previsao.get("hr") or "") or None,
            veiculos_ativos=(
                int(previsao["veiculos_ativos"])
                if previsao.get("veiculos_ativos") is not None
                else None
            ),
            aviso_api=str(previsao.get("aviso_api") or ""),
            aviso=str(previsao.get("aviso") or _aviso_gtfs_se_necessario()),
            sem_servico=previsao.get("tipo") == "sem_servico",
            sem_passagem=previsao.get("tipo") == "sem_passagem",
            horario_indisponivel=(
                bool(previsao.get("programacao_incompleta"))
                and not tem_programacao_util
            ),
            periodo=str(previsao.get("periodo") or ""),
        )

    blocos_ao_vivo = previsao.get("previsoes_por_sentido") or [previsao]
    sentidos_ao_vivo: list[PassagensPorSentido] = []
    for bloco in blocos_ao_vivo:
        if not isinstance(bloco, dict):
            continue
        referencia_api = _instante_referencia_sptrans(bloco.get("hr"))
        veiculos = tuple(
            PrevisaoChegada(
                horario=str(item["t"]),
                acessivel=(
                    bool(item["a"]) if item.get("a") is not None else None
                ),
                source=str(item.get("source") or "live"),
                confidence=str(item.get("confidence") or "low"),
                minutos_ate_chegada=math.ceil(
                    _segundos_ate_eta_sptrans(str(item["t"]), referencia_api)
                    / 60
                ),
                instante=(
                    referencia_api + timedelta(seconds=float(
                        _segundos_ate_eta_sptrans(
                            str(item["t"]), referencia_api,
                        )
                    ))
                ).isoformat(),
            )
            for item in _veiculos_ao_vivo_ordenados(
                list(bloco.get("veiculos", [])), bloco.get("hr"),
            )
        )
        if not veiculos:
            fallback_programado = {
                "tipo": "programacao",
                "linha": bloco.get("linha") or previsao.get("linha", ""),
                "parada": bloco.get("parada") or ponto_pedido,
                "destino": bloco.get("destino", ""),
                "horarios": list(bloco.get("horarios_programados", [])),
                "instantes": list(bloco.get("instantes_programados", [])),
                "estimativas": list(bloco.get("estimativas_programadas", [])),
                "faixas": list(bloco.get("faixas_programadas", [])),
                "programacao_incompleta": bool(
                    bloco.get("programacao_incompleta")
                ),
            }
            sentidos_ao_vivo.extend(
                _resultado_chegada_publico(
                    fallback_programado,
                    api_consultada=api_consultada,
                    ponto_pedido=ponto_pedido,
                ).sentidos
            )
            continue
        estimativas_programadas = tuple(
            PrevisaoChegada(
                horario=str(item["horario"]),
                acessivel=(
                    bool(item["acessivel"])
                    if item.get("acessivel") is not None
                    else None
                ),
                source=str(
                    item.get("source")
                    or "scheduled_estimate"
                ),
                confidence=str(
                    item.get("confidence")
                    or "scheduled"
                ),
                intervalo_programado_min=(
                    int(item["intervalo_min"])
                    if item.get("intervalo_min") is not None
                    else None
                ),
                instante=str(item.get("instante") or "") or None,
            )
            for item in bloco.get(
                "estimativas_programadas",
                [],
            )
            if isinstance(item, dict)
            and item.get("horario")
        )
        sentidos_ao_vivo.append(PassagensPorSentido(
            linha=str(bloco.get("linha") or previsao.get("linha") or ""),
            parada=str(bloco.get("parada") or ponto_pedido),
            sentido=str(bloco.get("destino") or ""),
            previsoes_ao_vivo=veiculos,
            horarios_programados=tuple(
                str(item) for item in bloco.get("horarios_programados", [])
            ),
            instantes_programados=tuple(
                str(item) for item in bloco.get("instantes_programados", [])
            ),
            estimativas_programadas=estimativas_programadas,
            programacao_confidence=(
                "scheduled_uncertain"
                if bloco.get("programacao_incompleta")
                else "scheduled"
            ),
            dados_operacionais=(
                dict(bloco["operacional"])
                if isinstance(bloco.get("operacional"), dict)
                else {}
            ,),
        ))
    if not sentidos_ao_vivo:
        # Não deveria ocorrer para uma resposta produzida acima, mas nunca
        # transforma uma previsão inválida recebida de outro chamador em ETA.
        fallback = {
            "tipo": "programacao",
            "linha": previsao.get("linha", ""),
            "parada": previsao.get("parada", ponto_pedido),
            "horarios": [],
            "aviso_api": "A previsão ao vivo não tinha ETA válido.",
        }
        return _resultado_chegada_publico(
            fallback, api_consultada=api_consultada, ponto_pedido=ponto_pedido,
        )
    linha = str(previsao.get("linha") or sentidos_ao_vivo[0].linha)
    parada = str(previsao.get("parada") or sentidos_ao_vivo[0].parada)
    return ResultadoChegada(
        linha=linha,
        parada=parada,
        sentidos=tuple(sentidos_ao_vivo),
        api_consultada=api_consultada,
        api_falhou=bool(previsao.get("falha_api")),
        observado_em=str(
            previsao.get("hr")
            or blocos_ao_vivo[0].get("hr", "")
        ) or None,
        aviso_api=str(previsao.get("aviso_api") or ""),
    )


# A modularização que já existia na main continua sendo a autoridade para as
# responsabilidades compartilhadas e estáveis: leitura do recorte, calendário,
# geometria básica e acesso bruto ao Olho Vivo. As regras mais conservadoras de
# identidade GTFS↔Olho Vivo, sentido, confiança, ETA por GPS e ranking ficam
# neste motor, pois são justamente as garantias acrescentadas depois.
_catalogo_gtfs = gtfs_sptrans.catalogo
_mesmo_nome = gtfs_sptrans.mesmo_nome
_servico_ativo = gtfs_sptrans.servico_ativo
_distancia_parada_gtfs = gtfs_sptrans.distancia_m

_autenticar_sptrans = olhovivo._autenticar
_get_json = olhovivo._get_json
_linhas_sptrans = olhovivo._linhas
_previsoes_linha = olhovivo._previsoes_linha
_posicoes_linha = olhovivo._posicoes_linha
_destino_linha_sptrans = olhovivo.destino_da_linha


def _consultar_circulares_calcular(
    linha: str | None = None,
    destino_ou_ponto: str | None = None,
    origem: str | None = None,
    detalhes: bool = False,
    _pergunta: str | None = None,
    _historico: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Consulta itinerários ou previsão de chegada em uma parada."""
    fontes: list[str] = []
    token = os.getenv("SPTRANS_TOKEN", "").strip()
    agora = datetime.now(FUSO_SP)
    intencao = analisar_intencao_transporte(_pergunta, agora)

    termo_linha = normalizar(linha or "")
    termo_destino = normalizar(destino_ou_ponto or "")
    termo_origem = normalizar(origem or "")
    atendimento_pedido = (
        _pergunta_pede_atendimento_de_linha(_pergunta)
        and not intencao.pede_chegada
    )
    if (
        termo_linha
        and not termo_destino
        and _historico
        and (intencao.pede_chegada or atendimento_pedido)
    ):
        # Tool calls do modelo também podem chegar aqui sem a parada. Reuse a
        # mesma regra conservadora da pré-consulta, sem extrair locais das
        # respostas do bot.
        from uspapo.consulta_transporte import _ponto_recente_associado

        ponto_contextual = _ponto_recente_associado(termo_linha, _historico)
        if ponto_contextual:
            destino_ou_ponto = ponto_contextual
            termo_destino = normalizar(ponto_contextual)

    if termo_origem and termo_destino:
        referencia_planejamento = intencao.instante_para_planejamento(agora)
        if _pergunta is None and intencao.modo_solicitado is None:
            # Mantém a interface histórica para chamadas Python diretas. No
            # fluxo do chatbot, `_pergunta` sempre existe e fornece a referência
            # temporal estável ou explicitamente pedida.
            plano = _planejar_trajeto_gtfs(
                origem or "", destino_ou_ponto or ""
            )
        else:
            plano = _planejar_trajeto_gtfs(
                origem or "",
                destino_ou_ponto or "",
                referencia_planejamento,
                intencao.modo_solicitado,
                intencao.restricao_temporal,
            )
        if plano.get("erro"):
            return str(plano["erro"]), [FONTE_GTFS]
        melhor = plano["melhor"]
        info_origem = dados_local(str(plano.get("origem", "")))
        if info_origem:
            fontes.append(str(info_origem["fonte"]))
        info_destino = dados_local(str(plano.get("destino", "")))
        if info_destino:
            fontes.append(str(info_destino["fonte"]))
        nome_origem = (
            str(info_origem["nome"]) if info_origem else str(plano["origem"])
        )
        nome_destino = (
            str(info_destino["nome"]) if info_destino else str(plano["destino"])
        )
        facetas = facetas_da_pergunta(_pergunta)
        if detalhes:
            facetas = replace(facetas, explicacao=True)

        if melhor.get("modo") == "a_pe":
            partes = []
            if facetas.localizacao and info_destino:
                partes.append(
                    f"A **{info_destino.get('nome_curto') or nome_destino}** fica "
                    f"{info_destino.get('localizacao') or 'na Cidade Universitária'}."
                )
            if plano.get("modo_solicitado") == "onibus":
                partes.append(
                    f"Não encontrei uma linha direta em operação entre "
                    f"**{nome_origem}** e **{nome_destino}** no período pedido."
                )
                partes.append(
                    "Como alternativa apenas aproximada, a distância em linha "
                    f"reta ajustada para caminhada equivale a cerca de "
                    f"**{melhor['total_estimado_min']} minutos** "
                    f"({melhor['distancia_aproximada_m']} m); isso não é uma "
                    "rota de pedestres calculada por ruas e calçadas."
                )
            else:
                partes.append(
                    f"De **{nome_origem}** até **{nome_destino}**, a opção "
                    f"estimada mais rápida é ir a pé: cerca de "
                    f"**{melhor['total_estimado_min']} minutos** "
                    f"({melhor['distancia_aproximada_m']} m em uma aproximação, "
                    "não em uma rota de pedestres)."
                )
            if plano.get("aviso"):
                partes.append(str(plano["aviso"]))
            if intencao.periodo == "tipico":
                partes.append(
                    "A comparação considera um **dia útil típico**. Para uma "
                    "resposta operacional, informe “hoje” ou “agora”."
                )
            if facetas.alternativas:
                alternativas = [
                    item
                    for item in plano.get("alternativas", [])
                    if item.get("modo") == "onibus"
                ]
                if alternativas:
                    partes.append(
                        "Se preferir ônibus, as opções diretas são: "
                        + "; ".join(
                            f"**{item['linha']}** (cerca de "
                            f"{item['total_estimado_min']} min)"
                            for item in alternativas
                        )
                        + "."
                    )
            aviso_gtfs = _aviso_gtfs_se_necessario()
            if aviso_gtfs:
                partes.append(aviso_gtfs)
            fontes.insert(0, FONTE_GTFS)
            fontes = list(dict.fromkeys(fontes))
            dados_publicos: dict[str, object] = {
                "tipo": "trajeto_a_pe",
                "facetas": {
                    "localizacao": facetas.localizacao,
                    "duracao": facetas.duracao,
                    "tempo_real": facetas.tempo_real,
                    "alternativas": facetas.alternativas,
                    "explicacao": facetas.explicacao,
                },
                "origem": nome_origem,
                "destino": nome_destino,
                "melhor_opcao": {
                    "modo": "a_pe",
                    "distancia_m": int(melhor["distancia_aproximada_m"]),
                    "tempo_total_min": int(melhor["total_estimado_min"]),
                },
            }
            if facetas.alternativas:
                dados_publicos["alternativas"] = [
                    {
                        "modo": "onibus",
                        "linha": str(item["linha"]),
                        "sentido": str(item["sentido"]),
                        "tempo_total_min": int(item["total_estimado_min"]),
                    }
                    for item in plano.get("alternativas", [])
                    if item.get("modo") == "onibus"
                ]
            if plano.get("aviso") or aviso_gtfs:
                dados_publicos["aviso"] = str(plano.get("aviso") or aviso_gtfs)
            return RespostaFerramenta(
                "\n\n".join(partes),
                fontes,
                dados_publicos,
            )

        if melhor.get("modo") == "onibus_sem_horario":
            api_sem_eta = False
            if token and facetas.tempo_real:
                opcoes_ao_vivo: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
                linhas_testadas: set[str] = set()
                for opcao in [melhor, *plano.get("alternativas", [])][:3]:
                    linha_opcao = str(opcao.get("linha", ""))
                    if not linha_opcao or linha_opcao in linhas_testadas:
                        continue
                    linhas_testadas.add(linha_opcao)
                    numero_opcao = linha_opcao.split("-", 1)[0]
                    previsao_opcao = cache(
                        (
                            "circulares", "previsao-rota", numero_opcao,
                            normalizar(opcao.get("embarque", "")),
                            normalizar(opcao.get("sentido", "")),
                            str(opcao.get("embarque_id", "")),
                            tuple(dia.isoformat() for dia in intencao.datas),
                            (
                                intencao.restricao_temporal.chave_cache()
                                if intencao.restricao_temporal else ()
                            ),
                        ),
                        TTL_AO_VIVO,
                        lambda numero=numero_opcao, item=opcao: (
                            _obter_previsao_sptrans(
                                numero,
                                str(item.get("embarque", "")),
                                token,
                                str(item.get("sentido", "")),
                                str(item.get("embarque_id", "")),
                                intencao.datas,
                                intencao.restricao_temporal,
                            )
                        ),
                    )
                    api_opcao = bool(
                        previsao_opcao.get("api_consultada")
                        or previsao_opcao.get("tipo") == "previsao"
                    )
                    api_sem_eta = api_sem_eta or api_opcao
                    espera_viva = _espera_ao_vivo(
                        previsao_opcao,
                        float(opcao["caminhada_origem_s"]),
                    )
                    if espera_viva:
                        total_vivo = (
                            float(opcao["caminhada_origem_s"])
                            + espera_viva.esperada_s
                            + float(opcao["viagem_s"])
                            + float(opcao["caminhada_destino_s"])
                        )
                        opcoes_ao_vivo.append(
                            (total_vivo, opcao, previsao_opcao)
                        )

                if opcoes_ao_vivo:
                    total_vivo, opcao, previsao_viva = min(
                        opcoes_ao_vivo, key=lambda item: item[0]
                    )
                    caminhada_s = float(plano.get("caminhada_direta_min", 0)) * 60
                    if caminhada_s and caminhada_s < total_vivo:
                        # Agora há duas estimativas temporais comparáveis: a
                        # caminhada aproximada e a rota com ETA validado. Não
                        # use a ausência da grade GTFS como se fosse esse fato.
                        fontes.insert(0, FONTE_GTFS)
                        fontes.append(FONTE_API)
                        fontes.extend(fontes_operacionais(
                            [str(opcao["linha"])], intencao.datas
                        ))
                        return RespostaFerramenta(
                            (
                                f"Com o ETA ao vivo da linha **{opcao['linha']}**, "
                                f"o trajeto de ônibus leva cerca de "
                                f"**{round(total_vivo / 60)} minutos**. A caminhada "
                                f"aproximada leva cerca de "
                                f"**{plano['caminhada_direta_min']} minutos**, então "
                                "ela é a menor estimativa entre as opções com tempo "
                                "calculável agora."
                            ),
                            list(dict.fromkeys(fontes)),
                            {
                                "tipo": "comparacao_trajeto_com_eta",
                                "melhor_opcao": {"modo": "a_pe"},
                                "onibus": {
                                    "linha": str(opcao["linha"]),
                                    "sentido": str(opcao["sentido"]),
                                    "tempo_total_min": round(total_vivo / 60),
                                    "source": "live",
                                },
                                "caminhada_aproximada_min": plano["caminhada_direta_min"],
                            },
                        )
                    melhor_vivo = {
                        **opcao,
                        "modo": "onibus",
                        "espera_programada_s": 0,
                        "intervalo_programado_s": None,
                        "espera_programada_min": 0,
                        "intervalo_programado_min": None,
                        "total_estimado_s": total_vivo,
                        "total_estimado_min": round(total_vivo / 60),
                    }
                    plano_vivo = {
                        **plano,
                        "melhor": melhor_vivo,
                        "alternativas": [],
                    }
                    resultado_vivo = _resultado_trajeto_publico(
                        plano_vivo, previsao_viva
                    )
                    dados_vivos = resultado_vivo.public_view(facetas)
                    dados_vivos["periodo"] = intencao.rotulo_periodo or "agora"
                    fontes.insert(0, FONTE_GTFS)
                    fontes.append(FONTE_API)
                    fontes.extend(fontes_operacionais(
                        [str(melhor_vivo["linha"])], intencao.datas
                    ))
                    return RespostaFerramenta(
                        renderizar_trajeto(resultado_vivo, facetas),
                        list(dict.fromkeys(fontes)),
                        dados_vivos,
                    )

            if plano.get("ranking_temporal") == "indeterminado":
                # A ordem estrutural serve apenas para apresentar candidatas;
                # sem espera programada ou ETA, ela não é um ranking de tempo.
                opcoes_estruturais: list[dict[str, Any]] = []
                vistas: set[tuple[str, str]] = set()
                for opcao in [melhor, *plano.get("alternativas", [])]:
                    chave = (str(opcao["linha"]), str(opcao["sentido"]))
                    if chave not in vistas:
                        vistas.add(chave)
                        opcoes_estruturais.append(opcao)
                partes = [
                    (
                        f"Há {len(opcoes_estruturais)} opções diretas de ônibus "
                        f"entre **{nome_origem}** e **{nome_destino}**, mas não há "
                        "horário GTFS confiável nem ETA ao vivo para determinar qual "
                        "é mais rápida agora."
                    ),
                    *[
                        f"- **{opcao['linha']}**, sentido **{opcao['sentido']}**: "
                        f"embarque em **{opcao['embarque']}** e desça em "
                        f"**{opcao['desembarque']}** "
                        f"({round(float(opcao['caminhada_destino_m']))} m após o desembarque)."
                        for opcao in opcoes_estruturais
                    ],
                    (
                        "As linhas estão em operação, mas a espera desconhecida "
                        "pode inverter a ordem entre elas."
                    ),
                ]
                if api_sem_eta:
                    partes.append(
                        "A API Olho Vivo foi consultada, mas não publicou ETA "
                        "para esses pontos de embarque agora."
                    )
                fontes.insert(0, FONTE_GTFS)
                fontes.extend(fontes_operacionais(
                    [str(opcao["linha"]) for opcao in opcoes_estruturais],
                    intencao.datas or (referencia_planejamento.date(),),
                ))
                dados_publicos = {
                    "tipo": "trajeto_onibus_sem_horario",
                    "origem": nome_origem,
                    "destino": nome_destino,
                    "periodo": intencao.rotulo_periodo or "dia útil típico",
                    "ranking_temporal": "indeterminado",
                    "melhor_opcao": None,
                    "opcoes_diretas": [
                        {
                            "linha": str(opcao["linha"]),
                            "sentido": str(opcao["sentido"]),
                            "embarque": str(opcao["embarque"]),
                            "desembarque": str(opcao["desembarque"]),
                            "caminhada_apos_desembarque_m": int(opcao["caminhada_destino_m"]),
                        }
                        for opcao in opcoes_estruturais
                    ],
                    "status_programacao": "horario_indisponivel",
                    "status_api": "consultada_sem_eta" if api_sem_eta else "nao_consultada",
                    "fatos_obrigatorios": [
                        valor
                        for opcao in opcoes_estruturais
                        for valor in (
                            str(opcao["linha"]), str(opcao["embarque"]), str(opcao["desembarque"]),
                        )
                    ],
                }
                return RespostaFerramenta(
                    "\n\n".join(partes), list(dict.fromkeys(fontes)), dados_publicos,
                )

            linha_melhor = str(melhor["linha"])
            aviso = str(plano.get("aviso") or aviso_programacao_incompleta(
                linha_melhor, referencia_planejamento.date()
            ))
            partes = [
                f"Para ir de **{nome_origem}** até **{nome_destino}** de ônibus, "
                f"use a linha **{linha_melhor}**, sentido "
                f"**{melhor['sentido']}**.",
                f"Embarque em **{melhor['embarque']}** e desça em "
                f"**{melhor['desembarque']}**.",
                (
                    "A operação da linha nesse período é confirmada pela "
                    "SPTrans, mas a grade GTFS disponível está incompleta; "
                    "por isso não é seguro informar a espera nem o tempo total."
                ),
            ]
            if aviso:
                partes.append(aviso)
            if api_sem_eta:
                partes.append(
                    "A API Olho Vivo também foi consultada, mas não publicou "
                    "um ETA para os pontos de embarque agora."
                )
            if plano.get("caminhada_direta_min"):
                partes.append(
                    "A caminhada aparece apenas como alternativa aproximada de "
                    f"cerca de **{plano['caminhada_direta_min']} minutos**; sem "
                    "horário ou ETA válido, não é seguro dizer qual opção é mais rápida."
                )
            datas_operacionais = intencao.datas or (
                referencia_planejamento.date(),
            )
            fontes.insert(0, FONTE_GTFS)
            fontes.extend(fontes_operacionais(
                [linha_melhor], datas_operacionais
            ))
            fontes = list(dict.fromkeys(fontes))
            dados_publicos = {
                "tipo": "trajeto_onibus_sem_horario",
                "origem": nome_origem,
                "destino": nome_destino,
                "periodo": intencao.rotulo_periodo or "dia útil típico",
                "melhor_opcao": {
                    "modo": "onibus",
                    "linha": linha_melhor,
                    "sentido": str(melhor["sentido"]),
                    "embarque": str(melhor["embarque"]),
                    "desembarque": str(melhor["desembarque"]),
                    "caminhada_ate_embarque_m": int(
                        melhor["caminhada_origem_m"]
                    ),
                    "caminhada_apos_desembarque_m": int(
                        melhor["caminhada_destino_m"]
                    ),
                    "espera_min": None,
                    "tempo_total_min": None,
                },
                "status_programacao": "horario_indisponivel",
                "frases_obrigatorias": [
                    "não é seguro informar a espera nem o tempo total"
                ],
                "status_api": (
                    "consultada_sem_eta" if api_sem_eta else "nao_consultada"
                ),
                "fatos_obrigatorios": [
                    linha_melhor,
                    str(melhor["embarque"]),
                    str(melhor["desembarque"]),
                ],
                "aviso": aviso,
            }
            return RespostaFerramenta(
                "\n\n".join(dict.fromkeys(partes)),
                fontes,
                dados_publicos,
            )

        # Só vale pagar a consulta ao vivo quando a pergunta pede o estado de
        # agora. Se houver ETA, ele substitui a espera programada no contrato e
        # o total é recalculado; nunca anexamos dois relógios incompatíveis.
        previsao = None
        plano_para_resultado = plano
        if token and facetas.tempo_real:
            # O ETA substitui somente a espera da mesma plataforma e do mesmo
            # headsign que o GTFS escolheu. Reavalia as alternativas diretas
            # antes de eleger a melhor, em vez de consultar somente a primeira
            # opção programada.
            opcoes_com_eta: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
            for opcao in [melhor, *plano.get("alternativas", [])]:
                numero_opcao = str(opcao["linha"]).split("-", 1)[0]
                previsao_opcao = cache(
                    (
                        "circulares", "previsao-rota", numero_opcao,
                        normalizar(opcao["embarque"]),
                        normalizar(opcao["sentido"]),
                        str(opcao["embarque_id"]),
                        tuple(dia.isoformat() for dia in intencao.datas),
                        (
                            intencao.restricao_temporal.chave_cache()
                            if intencao.restricao_temporal else ()
                        ),
                    ),
                    TTL_AO_VIVO,
                    lambda numero=numero_opcao, item=opcao: _obter_previsao_sptrans(
                        numero, str(item["embarque"]), token,
                        str(item["sentido"]), str(item["embarque_id"]),
                        intencao.datas,
                        intencao.restricao_temporal,
                    ),
                )
                espera_viva = _melhor_eta_ao_vivo(
                    previsao_opcao, float(opcao["caminhada_origem_s"]),
                )
                recalculada = dict(opcao)
                confianca = "scheduled"
                if espera_viva:
                    espera, confianca = espera_viva
                    recalculada["total_estimado_s"] = (
                        float(opcao["caminhada_origem_s"])
                        + espera.esperada_s
                        + float(opcao["viagem_s"])
                        + float(opcao["caminhada_destino_s"])
                    )
                    recalculada["total_estimado_min"] = round(
                        float(recalculada["total_estimado_s"]) / 60
                    )
                    recalculada["espera_source"] = "live"
                    recalculada["espera_confidence"] = confianca
                qualidade_eta = {"high": 3, "medium": 2, "low": 1, "scheduled": 0}.get(
                    confianca, 0
                )
                chave = (
                    *_chave_ranking_rota(recalculada)[:2],
                    -qualidade_eta,
                    *_chave_ranking_rota(recalculada)[2:],
                )
                opcoes_com_eta.append((chave, recalculada, previsao_opcao))

            opcoes_com_eta.sort(key=lambda item: item[0])
            if opcoes_com_eta:
                _, melhor_recalculada, previsao = opcoes_com_eta[0]
                plano_para_resultado = {
                    **plano,
                    "melhor": melhor_recalculada,
                    "alternativas": [item[1] for item in opcoes_com_eta[1:3]],
                }
            if any(
                item[2].get("api_consultada") or item[2].get("tipo") == "previsao"
                for item in opcoes_com_eta
            ):
                fontes.append(FONTE_API)

        resultado = _resultado_trajeto_publico(plano_para_resultado, previsao)
        texto = renderizar_trajeto(resultado, facetas)
        dados_trajeto = resultado.public_view(facetas)
        if intencao.periodo == "tipico":
            texto += (
                "\n\nEsta orientação considera um **dia útil típico**. "
                "Se você pretende ir hoje, pergunte novamente com “hoje” ou “agora”."
            )
            dados_trajeto["periodo"] = "dia útil típico"
            fatos = list(dados_trajeto.get("fatos_obrigatorios", []))
            fatos.append("dia útil típico")
            dados_trajeto["fatos_obrigatorios"] = fatos
        fontes.insert(0, FONTE_GTFS)
        fontes.extend(fontes_operacionais(
            [str(plano_para_resultado["melhor"]["linha"])],
            intencao.datas or (referencia_planejamento.date(),),
        ))
        fontes = list(dict.fromkeys(fontes))
        return RespostaFerramenta(
            texto,
            fontes,
            dados_trajeto,
        )

    # Perguntas como "quais linhas passam no Biênio?" são uma consulta reversa
    # de parada. Não escolha candidatas pelo catálogo manual: o GTFS é a fonte
    # oficial e deve devolver todas as linhas associadas ao stop_id.
    if not termo_linha and termo_destino:
        atendimento = _linhas_por_ponto_gtfs(
            destino_ou_ponto or "", intencao.datas
        )
        if not atendimento.get("erro"):
            linhas_ponto = atendimento.get("linhas", [])
            if intencao.periodo_explicito:
                partes = [
                    f"{intencao.rotulo_periodo.capitalize()}, a parada "
                    f"**{atendimento['parada']}** tem serviço programado de "
                    f"**{len(linhas_ponto)} linha(s)**:"
                ]
            else:
                partes = [
                    f"No catálogo GTFS oficial da SPTrans, a parada "
                    f"**{atendimento['parada']}** aparece cadastrada como "
                    f"atendida por {len(linhas_ponto)} linhas. Isso indica cadastro "
                    "de itinerário, não circulação em tempo real:"
                ]
            for item in linhas_ponto:
                datas_item = [
                    datetime.fromisoformat(str(valor)).strftime("%d/%m")
                    for valor in item.get("datas", [])
                ]
                sufixo_datas = (
                    " (" + " e ".join(datas_item) + ")"
                    if len(intencao.datas) > 1 and datas_item
                    else ""
                )
                partes.append(
                    f"- **{item['linha']}** — {item['nome']}{sufixo_datas}"
                )
            partes.append(
                f"Total no período consultado: **{len(linhas_ponto)} linha(s)**."
                if intencao.periodo_explicito
                else f"Total oficial cadastrado: **{len(linhas_ponto)} linha(s)**."
            )
            partes.append(_nota_atualizacao_gtfs())
            fontes_atendimento = [FONTE_GTFS]
            fontes_atendimento.extend(
                str(item)
                for item in atendimento.get("fontes_operacionais", [])
            )
            linhas_texto = [str(item["linha"]) for item in linhas_ponto]
            dados_publicos = {
                "tipo": "linhas_por_parada",
                "parada": str(atendimento["parada"]),
                "periodo": intencao.rotulo_periodo or None,
                "natureza": (
                    "servico_programado"
                    if intencao.periodo_explicito
                    else "cadastro_de_itinerario"
                ),
                "linhas": [
                    {
                        "linha": str(item["linha"]),
                        "nome": str(item["nome"]),
                        "datas": list(item.get("datas", [])),
                    }
                    for item in linhas_ponto
                ],
                "total": len(linhas_ponto),
                "numeros_obrigatorios": [len(linhas_ponto)],
                "fatos_obrigatorios": [
                    str(atendimento["parada"]),
                    *linhas_texto,
                ],
            }
            return RespostaFerramenta(
                "\n".join(partes),
                list(dict.fromkeys(fontes_atendimento)),
                dados_publicos,
            )
        return str(atendimento["erro"]), [FONTE_GTFS]

    partes = []
    numero = termo_linha.split("-", 1)[0].upper() if termo_linha else ""
    resumos = _resumo_gtfs(numero) if numero else []
    if numero and not resumos:
        return (
            f"A linha {linha} não aparece no GTFS atual da SPTrans. "
            "Ela pode ter sido desativada, renumerada ou não atender a área da USP.",
            [FONTE_GTFS],
        )

    if numero and atendimento_pedido:
        if not termo_destino:
            return RespostaFerramenta(
                f"Em qual parada você quer verificar se a linha **{linha or numero}** passa?",
                [],
                {
                    "tipo": "esclarecimento_transporte",
                    "linha": str(linha or numero),
                    "campo_necessario": "parada",
                    "fatos_obrigatorios": [str(linha or numero)],
                },
            )
        atendimento = _atendimento_linha_na_parada_gtfs(
            numero, destino_ou_ponto or "", intencao.datas,
        )
        estado = str(atendimento["estado"])
        rotulo_periodo = intencao.rotulo_periodo or "na data informada"
        linha_publica = str((atendimento.get("linhas") or [linha or numero])[0])
        parada_publica = str((atendimento.get("paradas") or [destino_ou_ponto or ""])[0])
        if estado == "atende":
            texto = (
                f"Sim, a linha **{linha_publica}** atende a parada "
                f"**{parada_publica}** {rotulo_periodo}."
            )
        elif estado == "sem_servico":
            texto = (
                f"A linha **{linha_publica}** inclui a parada **{parada_publica}** "
                f"no itinerário, mas não tem serviço programado nessa parada "
                f"{rotulo_periodo}."
            )
        elif estado == "nao_atende":
            texto = (
                f"Não, a linha **{linha or numero}** não atende a parada "
                f"**{destino_ou_ponto}** no GTFS atual."
            )
        else:
            texto = (
                f"Não há dados suficientes para confirmar se a linha "
                f"**{linha or numero}** atende **{destino_ou_ponto}** "
                f"{rotulo_periodo}."
            )
        dados_atendimento = {
            "tipo": "atendimento_linha_parada",
            "estado": estado,
            "linha": linha_publica,
            "parada": parada_publica,
            "periodo": intencao.rotulo_periodo or None,
            "fatos_obrigatorios": [linha_publica, parada_publica],
        }
        return RespostaFerramenta(
            texto,
            [FONTE_GTFS, *fontes_operacionais(
                list(atendimento.get("linhas") or [linha_publica]), intencao.datas,
            )],
            dados_atendimento,
        )

    if numero and not termo_destino and intencao.pede_chegada:
        return RespostaFerramenta(
            f"Em qual parada você quer saber a chegada da linha **{linha or numero}**?",
            [],
            {
                "tipo": "esclarecimento_transporte",
                "linha": str(linha or numero),
                "campo_necessario": "parada",
                "fatos_obrigatorios": [str(linha or numero)],
            },
        )

    # Previsão é o caso prioritário: uma única execução da ferramenta resolve
    # linha, parada e horários, sem exigir outra rodada do modelo/Groq.
    if numero and termo_destino:
        sentido_esperado = _sentido_explicito_da_pergunta(numero, _pergunta)
        if token and intencao.tempo_real:
            def produzir_previsao() -> dict[str, Any]:
                argumentos: dict[str, Any] = {
                    "datas_permitidas": intencao.datas,
                }
                if intencao.restricao_temporal is not None:
                    argumentos["restricao_temporal"] = (
                        intencao.restricao_temporal
                    )
                if sentido_esperado:
                    argumentos["sentido_esperado"] = sentido_esperado
                return _obter_previsao_sptrans(
                    numero,
                    destino_ou_ponto or "",
                    token,
                    **argumentos,
                )

            previsao = cache(
                (
                    "circulares",
                    "previsao",
                    numero,
                    termo_destino,
                    normalizar(sentido_esperado or ""),
                    tuple(dia.isoformat() for dia in intencao.datas),
                    (
                        intencao.restricao_temporal.chave_cache()
                        if intencao.restricao_temporal else ()
                    ),
                ),
                TTL_AO_VIVO,
                produzir_previsao,
            )
        else:
            previsao = _programacao_gtfs(
                numero,
                destino_ou_ponto or "",
                agora,
                sentido_esperado=sentido_esperado,
                datas_permitidas=intencao.datas,
                restricao_temporal=intencao.restricao_temporal,
            )
        if previsao.get("tipo") == "sentido_incompativel":
            sentido = str(previsao.get("sentido_solicitado") or "")
            dados_incompativeis = {
                "tipo": "sentido_incompativel",
                "linha": str(previsao.get("linha") or linha or numero),
                "parada": str(previsao.get("parada") or destino_ou_ponto or ""),
                "sentido_solicitado": sentido,
                "fatos_obrigatorios": [
                    str(previsao.get("linha") or linha or numero),
                    str(previsao.get("parada") or destino_ou_ponto or ""),
                    sentido,
                ],
            }
            return RespostaFerramenta(
                f"A parada **{dados_incompativeis['parada']}** não é compatível "
                f"com o sentido **{sentido}** dessa linha; não usei o sentido oposto.",
                [FONTE_GTFS],
                dados_incompativeis,
            )
        if previsao.get("erro"):
            return str(previsao["erro"]), [FONTE_GTFS]

        if intencao.rotulo_periodo:
            previsao.setdefault("periodo", intencao.rotulo_periodo)

        api_consultada = bool(
            previsao.get("api_consultada")
            or previsao.get("tipo") == "previsao"
            or "veiculos" in previsao
        )
        resultado_chegada = _resultado_chegada_publico(
            previsao,
            api_consultada=api_consultada,
            ponto_pedido=destino_ou_ponto or "",
        )
        facetas_chegada = facetas_da_pergunta(_pergunta)
        texto = renderizar_chegada(
            resultado_chegada,
            detalhes=detalhes or facetas_chegada.explicacao,
        )
        dados_publicos = resultado_chegada.public_view(
            _pergunta,
            detalhes=detalhes or facetas_chegada.explicacao,
        )
        fontes_operacao = fontes_operacionais(
            [str(previsao.get("linha") or linha or numero)],
            intencao.datas,
        )
        if previsao.get("tipo") in {
            "programacao", "sem_servico", "sem_passagem"
        }:
            fontes_programacao = [FONTE_GTFS]

            if api_consultada:
                fontes_programacao.insert(0, FONTE_API)

            usa_planoper = bool(
                previsao.get("programacao_planoper")
            ) or any(
                isinstance(bloco, dict)
                and bloco.get("programacao_planoper")
                for bloco in previsao.get("sentidos", [])
            )

            if usa_planoper:
                fontes_programacao.append(
                    FONTE_PLANOPER
                )

            fontes_programacao.extend(
                fontes_operacao
            )

            return RespostaFerramenta(
                texto,
                list(dict.fromkeys(fontes_programacao)),
                dados_publicos,
            )
        fontes_chegada = [FONTE_API] if api_consultada else []
        fontes_chegada.extend(fontes_operacao)
        return RespostaFerramenta(
            texto, list(dict.fromkeys(fontes_chegada)), dados_publicos
        )

    if numero:
        for resumo in resumos[:2]:
            partes.append(f"### Linha {resumo['linha']} — {resumo['nome']}")
            if resumo["paradas"]:
                partes.append(
                    "**Paradas oficiais do itinerário:** "
                    + ", ".join(resumo["paradas"])
                    + "."
                )
        partes.append(_nota_atualizacao_gtfs())
        return "\n\n".join(partes), [FONTE_GTFS]

    # Sem argumentos, não inventa uma lista de "principais" linhas. Mostra o
    # conjunto efetivamente presente no recorte oficial atual.
    rotas_atuais = sorted(
        (
            (str(rota.get("linha", "")), str(rota.get("nome", "")))
            for rotas in _catalogo_gtfs().get("linhas", {}).values()
            for rota in rotas
        ),
        key=lambda item: normalizar(item[0]),
    )
    partes.append(
        f"O recorte GTFS atual contém {len(rotas_atuais)} variantes de linhas "
        "que possuem ao menos uma parada na área geográfica da USP:"
    )
    partes.extend(f"- {numero_linha} — {nome}" for numero_linha, nome in rotas_atuais)
    partes.append(_nota_atualizacao_gtfs())
    return "\n".join(partes), [FONTE_GTFS]


def _resposta_com_consulta_transporte(
    resposta: tuple[str, list[str]] | RespostaFerramenta,
    consulta: TransitQuery,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Anexa o contrato comum sem alterar a apresentação factual existente."""
    if not isinstance(resposta, RespostaFerramenta):
        return resposta
    dados = dict(resposta.dados_publicos or {})
    dados["consulta_transporte"] = consulta.como_publico()
    kind = str(dados.get("tipo") or "transporte")
    envelope = resultado_consulta_transporte(consulta, kind, dados)
    return RespostaFerramenta(
        resposta.texto,
        resposta.fontes,
        dados,
        resultado_transporte=envelope,
    )


def consultar_circulares(
    linha: str | None = None,
    destino_ou_ponto: str | None = None,
    origem: str | None = None,
    detalhes: bool = False,
    _pergunta: str | None = None,
    _historico: list[dict[str, str]] | None = None,
) -> tuple[str, list[str]] | RespostaFerramenta:
    """Interpreta uma consulta flexível antes de delegar aos motores atuais."""
    # A LLM pode fornecer entidades explícitas pela tool call; a pergunta fica
    # disponível para facetas e período, mas nunca para recalcular fatos.
    consulta = interpretar_consulta_transporte(
        _pergunta,
        origin=origem,
        destination=destino_ou_ponto if origem else None,
        line=linha,
        stop=destino_ou_ponto if not origem else None,
        now=datetime.now(FUSO_SP),
        interpretation="tool_arguments" if any((linha, destino_ou_ponto, origem)) else "deterministic",
    )
    # Deíticos de parada ("lá", "ali", "nesse ponto") podem aproveitar
    # somente o destino inequívoco de uma pergunta anterior do usuário. Isso
    # também deixa a TransitQuery final refletir a parada realmente consultada.
    linha_contextual = linha or consulta.entities.line
    if (
        linha_contextual
        and not origem
        and not destino_ou_ponto
        and _pergunta_pede_atendimento_de_linha(_pergunta)
        and _historico
    ):
        from uspapo.consulta_transporte import _ponto_recente_associado

        ponto_contextual = _ponto_recente_associado(
            str(linha_contextual), _historico,
        )
        if ponto_contextual:
            linha = str(linha_contextual)
            destino_ou_ponto = ponto_contextual
            consulta = interpretar_consulta_transporte(
                _pergunta,
                line=linha,
                stop=destino_ou_ponto,
                now=datetime.now(FUSO_SP),
                interpretation="contextual_user_message",
            )
    if (
        _pergunta_pede_atendimento_de_linha(_pergunta)
        and not (linha or consulta.entities.line)
        and re.search(r"\b(?:la|ali|nesse\s+ponto|neste\s+ponto)\b", normalizar(_pergunta or ""))
    ):
        texto = "Qual linha e qual parada você quer verificar?"
        return _resposta_com_consulta_transporte(
            RespostaFerramenta(
                texto,
                [],
                {
                    "tipo": "esclarecimento_transporte",
                    "campos_necessarios": ["linha", "parada"],
                    "fatos_obrigatorios": [],
                },
            ),
            consulta,
        )
    if consulta.task == "service_info" and (
        consulta.facets.service_window
        or not (consulta.entities.line and consulta.entities.stop)
    ):
        # Não há ainda um motor de primeiro/último horário. Recusar a resposta
        # parcial é mais seguro do que reutilizar o motor de próxima chegada.
        texto = (
            "Entendi que você quer a operação da linha, mas ainda não calculo "
            "com segurança o primeiro ou último horário. Posso informar as "
            "próximas chegadas, um trajeto direto ou as linhas de uma parada."
        )
        dados = {
            "tipo": "consulta_transporte_geral",
            "status": "nao_suportada_ainda",
            "fatos_obrigatorios": [],
        }
        return _resposta_com_consulta_transporte(
            RespostaFerramenta(texto, [], dados), consulta,
        )
    resposta = _consultar_circulares_calcular(
        linha=linha,
        destino_ou_ponto=destino_ou_ponto,
        origem=origem,
        detalhes=detalhes,
        _pergunta=_pergunta,
        _historico=_historico,
    )
    return _resposta_com_consulta_transporte(resposta, consulta)


def registrar(registro: Registro) -> None:
    """Registra a ferramenta consultar_circulares no registro do backend."""
    registro.ferramenta(
        nome="consultar_circulares",
        descricao=(
            "Consulta o catálogo GTFS atual e a API Olho Vivo da SPTrans para "
            "itinerários, paradas, sentidos e previsões dos ônibus que atendem "
            "a USP (Cidade Universitária / Butantã). Os nomes das linhas e das "
            "paradas vêm dos dados oficiais atuais; não use uma lista manual nem "
            "deduza o embarque pelo nome da linha. "
            "Use esta ferramenta sempre que a pergunta mencionar ônibus, circular, "
            "linha, ponto, parada, chegada ou horário de ônibus. Quando o aluno "
            "perguntar quando uma linha chega a um local, envie tanto `linha` "
            "quanto `destino_ou_ponto`; a ferramenta devolve os horários em uma "
            "única chamada. Quando perguntar qual é o melhor ônibus ou como ir de "
            "um local a outro, envie `origem` e `destino_ou_ponto`; a ferramenta "
            "compara caminhada, sentido, percurso e frequência programada."
        ),
        parametros={
            "type": "object",
            "properties": {
                "linha": {
                    "type": "string",
                    "description": (
                        "Número oficial da linha de ônibus (ex: '8012', '8082', "
                        "'8084-10', '8022'). Omita se o aluno perguntar de forma "
                        "genérica."
                    ),
                },
                "destino_ou_ponto": {
                    "type": "string",
                    "description": (
                        "Destino ou instituto desejado (ex: 'Poli', 'FFLCH', "
                        "'Metrô Butantã', 'FEA', 'CRUSP', 'Biênio'). Para previsão "
                        "de chegada, este campo é obrigatório."
                    ),
                },
                "origem": {
                    "type": "string",
                    "description": (
                        "Local de partida quando o aluno pedir o melhor ônibus ou "
                        "um trajeto (ex: 'P1', 'Central', 'Reitoria', 'Biênio', "
                        "'Metrô Butantã'). Central significa o Restaurante "
                        "Universitário Central; Administração Central e Reitoria "
                        "são locais distintos."
                    ),
                },
                "detalhes": {
                    "type": "boolean",
                    "description": (
                        "Use true somente quando o aluno pedir para explicar o "
                        "cálculo, a origem dos dados ou a confiabilidade."
                    ),
                },
            },
        },
    )(consultar_circulares)
