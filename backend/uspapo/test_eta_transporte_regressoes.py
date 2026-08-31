"""Regressoes estruturadas para previsoes de chegada de circulares."""

from datetime import datetime
import unittest
from unittest.mock import patch

from uspapo.transporte import consultas_circulares as circulares
from uspapo.transporte_resposta import (
    PassagensPorSentido,
    PrevisaoChegada,
    ResultadoChegada,
    renderizar_chegada,
)


class RegressaoEtaGpsCircularTests(unittest.TestCase):
    def test_regressao_no_shape_depois_do_alvo_nao_descarta_eta_antes_do_alvo(self):
        """Uma ambiguidade posterior ao alvo nao invalida o trecho observado."""
        referencia = datetime(2026, 8, 26, 13, 0, tzinfo=circulares.FUSO_SP)
        viagem = {"shape_id": "circular", "paradas": []}
        shape = [
            {"sequencia": 1, "latitude": -23.0, "longitude": -46.0},
            {"sequencia": 2, "latitude": -23.1, "longitude": -46.1},
        ]
        paradas_projetadas = [
            {
                "id": "origem",
                "nome": "Origem",
                "shape_m": 0.0,
                "erro_shape_m": 2.0,
                "deslocamento_s": 0.0,
            },
            {
                "id": "antes-do-alvo",
                "nome": "Antes do alvo",
                "shape_m": 100.0,
                "erro_shape_m": 2.0,
                "deslocamento_s": 100.0,
            },
            {
                "id": "alvo",
                "nome": "Parada alvo",
                "shape_m": 200.0,
                "erro_shape_m": 2.0,
                "deslocamento_s": 200.0,
            },
            {
                # Em uma linha circular, a projecao de uma parada posterior
                # pode cair em um ramo anterior/duplicado do mesmo shape.
                "id": "depois-do-alvo",
                "nome": "Depois do alvo",
                "shape_m": 150.0,
                "erro_shape_m": 2.0,
                "deslocamento_s": 300.0,
            },
        ]
        veiculo = {
            "p": "veiculo-8084-like",
            "ta": "13:00:00",
            "py": -23.05,
            "px": -46.05,
        }

        with (
            patch.object(circulares, "_instante_referencia_sptrans", return_value=referencia),
            patch.object(circulares, "_shape_da_viagem", return_value=shape),
            patch.object(
                circulares,
                "_paradas_projetadas_na_viagem",
                return_value=paradas_projetadas,
            ),
            patch.object(
                circulares,
                "_projetar_ponto_no_shape",
                side_effect=(
                    {"shape_m": 50.0, "distancia_m": 3.0},
                    {"shape_m": 0.0, "distancia_m": 50.0},
                ),
            ),
        ):
            resultado = circulares._eta_derivado_de_gps(
                viagem,
                "alvo",
                veiculo,
                "13:00",
            )

        self.assertIsNotNone(resultado)
        assert resultado is not None
        self.assertEqual(resultado["source"], "live_gps_estimate")
        self.assertEqual(resultado["t"], "13:03")
        self.assertEqual(resultado["gps_trecho_de"], "Origem")
        self.assertEqual(resultado["gps_trecho_para"], "Antes do alvo")

    def test_ramos_circulares_geograficamente_ambiguos_recusam_eta(self):
        referencia = datetime(2026, 8, 26, 13, 0, tzinfo=circulares.FUSO_SP)
        viagem = {
            "shape_id": "ida-e-volta-proximas",
            "paradas": [
                {
                    "id": "origem", "nome": "Origem", "sequencia": 1,
                    "latitude": 0.0, "longitude": 0.0, "deslocamento": 0,
                },
                {
                    "id": "alvo", "nome": "Alvo", "sequencia": 2,
                    "latitude": 0.0, "longitude": 0.001,
                    "deslocamento": 600,
                },
                {
                    "id": "depois", "nome": "Depois", "sequencia": 3,
                    "latitude": 0.00005, "longitude": 0.0,
                    "deslocamento": 900,
                },
            ],
        }
        shape = [
            {"sequencia": 1, "latitude": 0.0, "longitude": 0.0},
            {"sequencia": 2, "latitude": 0.0, "longitude": 0.001},
            {"sequencia": 3, "latitude": 0.00005, "longitude": 0.001},
            {"sequencia": 4, "latitude": 0.00005, "longitude": 0.0},
        ]
        veiculo = {
            "p": "ramo-ambiguo", "ta": "13:00:00",
            "py": 0.0, "px": 0.0002,
        }

        with (
            patch.object(circulares, "_instante_referencia_sptrans",
                         return_value=referencia),
            patch.object(circulares, "_shape_da_viagem", return_value=shape),
        ):
            resultado = circulares._eta_derivado_de_gps(
                viagem, "alvo", veiculo, "13:00"
            )

        self.assertIsNone(resultado)


class RegressaoSentidoLinhaOlhoVivoTests(unittest.TestCase):
    def test_destino_operacional_respeita_semantica_oficial_do_sl(self):
        linha_base = {
            "tp": "Terminal principal",
            "ts": "Terminal secundario",
        }

        with self.subTest(sl=1):
            self.assertEqual(
                circulares._destino_linha_sptrans({**linha_base, "sl": 1}),
                "Terminal principal",
            )

        with self.subTest(sl=2):
            self.assertEqual(
                circulares._destino_linha_sptrans({**linha_base, "sl": 2}),
                "Terminal secundario",
            )


class RegressaoContratoPublicoChegadasTests(unittest.TestCase):
    def test_public_view_mescla_ordena_deduplica_e_limita_todas_as_fontes(self):
        resultado = ResultadoChegada(
            linha="8084-10",
            parada="Bienio",
            api_consultada=True,
            observado_em="13:10",
            sentidos=(
                PassagensPorSentido(
                    linha="8084-10",
                    parada="Bienio",
                    sentido="Cid. Universitaria",
                    previsoes_ao_vivo=(
                        PrevisaoChegada(
                            horario="13:20",
                            source="live",
                            confidence="high",
                            minutos_ate_chegada=10,
                        ),
                    ),
                    horarios_programados=("13:15",),
                    estimativas_programadas=(
                        PrevisaoChegada(
                            horario="13:20",
                            source="scheduled_estimate",
                            confidence="scheduled",
                            intervalo_programado_min=7,
                        ),
                        PrevisaoChegada(
                            horario="13:22",
                            source="scheduled_estimate",
                            confidence="scheduled",
                            intervalo_programado_min=7,
                        ),
                        PrevisaoChegada(
                            horario="13:30",
                            source="scheduled_estimate",
                            confidence="scheduled",
                            intervalo_programado_min=7,
                        ),
                    ),
                ),
            ),
        )

        chegadas = resultado.public_view()["sentidos"][0]["chegadas"]

        self.assertEqual(len(chegadas), 3)
        self.assertEqual(
            [(item["horario"], item["source"]) for item in chegadas],
            [
                ("13:20", "live"),
                ("13:22", "scheduled_estimate"),
                ("13:30", "scheduled_estimate"),
            ],
        )

    def test_falha_http_nao_e_rotulada_como_api_sem_eta(self):
        resultado = ResultadoChegada(
            linha="8084-10",
            parada="Bienio",
            api_consultada=True,
            api_falhou=True,
            aviso_api="A API Olho Vivo nao respondeu agora.",
            sentidos=(PassagensPorSentido(
                linha="8084-10",
                parada="Bienio",
                sentido="Cid. Universitaria",
                estimativas_programadas=(PrevisaoChegada(
                    horario="13:25",
                    source="scheduled_estimate",
                    confidence="scheduled",
                    intervalo_programado_min=7,
                ),),
            ),),
        )

        self.assertEqual(resultado.public_view()["status_api"], "indisponivel")
        texto = renderizar_chegada(resultado)
        self.assertIn("não respondeu", texto)
        self.assertNotIn("não publicou", texto)

    def test_mescla_relogio_legado_com_instante_iso_na_mesma_escala(self):
        resultado = ResultadoChegada(
            linha="8084-10",
            parada="Bienio",
            api_consultada=True,
            observado_em="13:10",
            sentidos=(PassagensPorSentido(
                linha="8084-10",
                parada="Bienio",
                sentido="Cid. Universitaria",
                previsoes_ao_vivo=(PrevisaoChegada(
                    horario="13:20", source="live", confidence="high",
                    instante="2026-08-26T13:20:00-03:00",
                ),),
                estimativas_programadas=(
                    PrevisaoChegada(
                        horario="13:22", source="scheduled_estimate",
                        confidence="scheduled", intervalo_programado_min=7,
                    ),
                    PrevisaoChegada(
                        horario="13:29", source="scheduled_estimate",
                        confidence="scheduled", intervalo_programado_min=7,
                    ),
                ),
            ),),
        )

        chegadas = resultado.public_view()["sentidos"][0]["chegadas"]
        self.assertEqual(
            [(item["horario"], item["source"]) for item in chegadas],
            [
                ("13:20", "live"),
                ("13:22", "scheduled_estimate"),
                ("13:29", "scheduled_estimate"),
            ],
        )

    def test_iso_sem_offset_e_ancorado_sem_misturar_datetime_naive(self):
        resultado = ResultadoChegada(
            linha="8084-10",
            parada="Bienio",
            api_consultada=True,
            sentidos=(PassagensPorSentido(
                linha="8084-10",
                parada="Bienio",
                sentido="Cid. Universitaria",
                previsoes_ao_vivo=(PrevisaoChegada(
                    horario="13:20", source="live", confidence="high",
                    instante="2026-08-26T13:20:00-03:00",
                ),),
                estimativas_programadas=(PrevisaoChegada(
                    horario="13:22", source="scheduled_estimate",
                    confidence="scheduled", intervalo_programado_min=7,
                    instante="2026-08-26T13:22:00",
                ),),
            ),),
        )

        chegadas = resultado.public_view()["sentidos"][0]["chegadas"]
        self.assertEqual(
            [(item["horario"], item["source"]) for item in chegadas],
            [("13:20", "live"), ("13:22", "scheduled_estimate")],
        )

    def test_falha_http_sem_fallback_temporal_continua_explicita(self):
        resultado = ResultadoChegada(
            linha="8084-10",
            parada="Bienio",
            api_consultada=True,
            api_falhou=True,
            sentidos=(PassagensPorSentido(
                linha="8084-10", parada="Bienio",
                sentido="Cid. Universitaria",
            ),),
        )

        self.assertEqual(resultado.public_view()["status_api"], "indisponivel")
        self.assertEqual(
            resultado.como_payload()["api_olho_vivo"]["status"],
            "indisponivel",
        )
        self.assertIn("não respondeu", renderizar_chegada(resultado))


class RegressaoIntencaoChegadaTests(unittest.TestCase):
    def test_plural_e_perguntas_de_tempo_restante_sao_arrival(self):
        from uspapo.consulta_transporte import interpretar_consulta_transporte

        perguntas = (
            "Quais sao os proximos tres 8084 no Bienio?",
            "Proximos 3 onibus 8084 no Bienio",
            "Quanto falta pro 8084 chegar no Bienio?",
            "Daqui a quanto tempo passa o 8084 no Bienio?",
        )
        for pergunta in perguntas:
            with self.subTest(pergunta=pergunta):
                consulta = interpretar_consulta_transporte(pergunta)
                self.assertEqual(consulta.task, "arrival")
                self.assertTrue(consulta.period.pede_chegada)
                self.assertTrue(consulta.period.tempo_real)


class RegressaoComplementoProgramadoTests(unittest.TestCase):
    def test_eta_tardio_recalcula_os_slots_programados_seguintes(self):
        referencia = datetime(2026, 8, 26, 13, 10, tzinfo=circulares.FUSO_SP)

        def programacao(horarios):
            return {
                "tipo": "programacao",
                "linha": "8084-10",
                "parada": "Bienio",
                "parada_id": "stop-bienio",
                "destino": "Cid. Universitaria",
                "sentido_gtfs": "0",
                "horarios": [],
                "instantes": [],
                "estimativas": [
                    {
                        "horario": horario,
                        "instante": f"2026-08-26T{horario}:00-03:00",
                        "intervalo_min": 7,
                        "source": "scheduled_estimate",
                        "confidence": "scheduled",
                    }
                    for horario in horarios
                ],
            }

        inicial = programacao(("13:15", "13:18", "13:19"))
        posterior = programacao(("13:25", "13:32", "13:39"))
        linha_api = {
            "cl": 2607, "lt": "8084", "tl": 10, "sl": 1,
            "tp": "CID. UNIVERSITARIA", "ts": "METRO BUTANTA",
        }
        previsao_api = {
            "hr": "13:10",
            "ps": [{
                "cp": "stop-bienio", "np": "Bienio", "ed": "Poli",
                "vs": [{
                    "p": "veiculo-live", "t": "13:20", "ta": "13:09:30",
                    "py": -23.55, "px": -46.73,
                }],
            }],
        }

        with (
            patch.object(
                circulares, "_programacao_gtfs",
                side_effect=(inicial, posterior),
            ) as calcular_programacao,
            patch.object(circulares, "_plataformas_gtfs_ambíguas",
                         return_value=False),
            patch.object(circulares, "_autenticar_sptrans", return_value=True),
            patch.object(circulares, "_linhas_sptrans", return_value=[linha_api]),
            patch.object(circulares, "_previsoes_linha",
                         return_value=previsao_api),
            patch.object(circulares, "_instante_referencia_sptrans",
                         return_value=referencia),
            patch.object(circulares, "_agora_sptrans", return_value=referencia),
            patch.object(circulares, "cache",
                         side_effect=lambda _c, _t, produzir: produzir()),
        ):
            previsao = circulares._obter_previsao_sptrans(
                "8084", "Bienio", "token",
                sentido_esperado="Cid. Universitaria",
            )
            contrato = circulares._resultado_chegada_publico(
                previsao, api_consultada=True, ponto_pedido="Bienio"
            )

        self.assertEqual(calcular_programacao.call_count, 2)
        chegadas = contrato.public_view()["sentidos"][0]["chegadas"]
        self.assertEqual(
            [(item["horario"], item["source"]) for item in chegadas],
            [
                ("13:20", "live"),
                ("13:25", "scheduled_estimate"),
                ("13:32", "scheduled_estimate"),
            ],
        )


class RegressaoDedupeVeiculosTests(unittest.TestCase):
    def test_hr_antigo_descarta_payload_inteiro_ainda_que_ta_seja_coerente(self):
        agora = datetime(2026, 8, 26, 13, 0, tzinfo=circulares.FUSO_SP)
        veiculos = [
            {
                "p": "payload-antigo",
                "t": "11:05",
                "ta": "11:00:00",
                "py": -23.55,
                "px": -46.73,
            },
            {
                "p": "payload-antigo-sem-ta",
                "t": "11:06",
                "py": -23.55,
                "px": -46.73,
            },
        ]

        with patch.object(circulares, "_agora_sptrans", return_value=agora):
            self.assertFalse(circulares._referencia_api_recente("11:00"))
            self.assertFalse(circulares._referencia_api_recente(None))

        programacao = {
            "tipo": "programacao", "linha": "8084-10", "parada": "Bienio",
            "parada_id": "stop-bienio", "destino": "Destino",
            "sentido_gtfs": "0", "horarios": ["13:15"],
        }
        linha_api = {
            "cl": 1, "lt": "8084", "tl": 10, "sl": 1,
            "tp": "Destino", "ts": "Origem",
        }
        with (
            patch.object(circulares, "_programacao_gtfs",
                         return_value=programacao),
            patch.object(circulares, "_plataformas_gtfs_ambíguas",
                         return_value=False),
            patch.object(circulares, "_autenticar_sptrans", return_value=True),
            patch.object(circulares, "_linhas_sptrans",
                         return_value=[linha_api]),
            patch.object(circulares, "_previsoes_linha", return_value={
                "hr": "11:00",
                "ps": [{"cp": "stop-bienio", "vs": veiculos}],
            }),
            patch.object(circulares, "_posicoes_linha", return_value={
                "hr": "11:00", "vs": veiculos,
            }),
            patch.object(circulares, "_agora_sptrans", return_value=agora),
            patch.object(circulares, "cache",
                         side_effect=lambda _c, _t, produzir: produzir()),
        ):
            resultado = circulares._obter_previsao_sptrans(
                "8084", "Bienio", "token", sentido_esperado="Destino"
            )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertNotIn("veiculos", resultado)
        self.assertIn("temporal antiga", resultado["aviso_api"])

    def test_registro_stale_nao_oculta_atualizacao_fresca_do_mesmo_veiculo(self):
        referencia = datetime(2026, 8, 26, 13, 0, tzinfo=circulares.FUSO_SP)
        veiculos = [
            {
                "p": "mesmo-id",
                "t": "13:08",
                "ta": "12:30:00",
                "py": -23.55,
                "px": -46.73,
            },
            {
                "p": "mesmo-id",
                "t": "13:05",
                "ta": "12:59:30",
                "py": -23.55,
                "px": -46.73,
            },
        ]

        with patch.object(
            circulares,
            "_instante_referencia_sptrans",
            return_value=referencia,
        ), patch.object(
            circulares,
            "_agora_sptrans",
            return_value=referencia,
        ):
            ordenados = circulares._veiculos_ao_vivo_ordenados(
                veiculos,
                "13:00",
            )

        self.assertEqual(len(ordenados), 1)
        self.assertEqual(ordenados[0]["p"], "mesmo-id")
        self.assertEqual(ordenados[0]["t"], "13:05")
        self.assertEqual(ordenados[0]["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
