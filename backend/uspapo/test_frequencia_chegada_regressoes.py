from datetime import date, datetime
import unittest
from unittest.mock import patch

from uspapo.transporte import consultas_circulares as circulares


class FrequenciaChegadaRegressoesTest(unittest.TestCase):
    @staticmethod
    def _catalogo(frequencias):
        return {
            "calendarios": {
                "todos": {
                    "dias": [1, 1, 1, 1, 1, 1, 1],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {},
            "linhas": {
                "9998": [{
                    "linha": "9998-10",
                    "nome": "Linha de teste",
                    "viagens": [{
                        "id": "viagem-frequencia",
                        "servico": "todos",
                        "destino": "Destino",
                        "sentido": "0",
                        "frequencias": frequencias,
                        "paradas": [{
                            "id": "ponto-gtfs",
                            "nome": "Ponto de teste",
                            "latitude": -23.55,
                            "longitude": -46.73,
                            "sequencia": 1,
                            "deslocamento": 0,
                            "horario": 12 * 3600,
                        }],
                    }],
                }],
            },
        }

    def _programacao(self, frequencias, agora, **kwargs):
        with (
            patch.object(
                circulares, "_catalogo_gtfs",
                return_value=self._catalogo(frequencias),
            ),
            patch.object(
                circulares, "horario_gtfs_confiavel", return_value=True,
            ),
            patch.object(
                circulares, "parada_atendida_na_data", return_value=True,
            ),
        ):
            return circulares._programacao_gtfs(
                "9998", "Ponto de teste", agora,
                sentido_esperado="Destino",
                **kwargs,
            )

    def test_faixa_futura_nao_pula_o_slot_inicial(self):
        agora = datetime(2026, 8, 26, 11, 55, tzinfo=circulares.FUSO_SP)
        resultado = self._programacao(
            [{
                "inicio": 12 * 3600,
                "fim": 15 * 3600,
                "intervalo": 15 * 60,
                "exact_times": 0,
            }],
            agora,
        )

        self.assertEqual(
            [item["horario"] for item in resultado["estimativas"]],
            ["12:00", "12:15", "12:30"],
        )

    def test_janela_ativa_nao_e_ocultada_por_slots_da_faixa_seguinte(self):
        agora = datetime(2026, 8, 26, 12, 58, tzinfo=circulares.FUSO_SP)
        resultado = self._programacao(
            [
                {
                    "inicio": 12 * 3600,
                    "fim": 13 * 3600,
                    "intervalo": 15 * 60,
                    "exact_times": 0,
                },
                {
                    "inicio": 13 * 3600,
                    "fim": 15 * 3600,
                    "intervalo": 10 * 60,
                    "exact_times": 0,
                },
            ],
            agora,
        )
        contrato = circulares._resultado_chegada_publico(
            resultado,
            api_consultada=False,
            ponto_pedido="Ponto de teste",
        )

        sentido = contrato.public_view()["sentidos"][0]
        self.assertEqual(
            sentido["base_previsao"], "frequencia_programada_estimada"
        )
        self.assertEqual(sentido["horarios"][0], "12:59")
        self.assertNotIn("intervalo_programado_min", sentido)
        texto = circulares.renderizar_chegada(contrato)
        self.assertIn("15 minutos", texto)
        self.assertIn("10 minutos", texto)

    def test_data_futura_nao_recebe_slots_do_dia_civil_anterior(self):
        agora = datetime(2026, 8, 26, 13, 0, tzinfo=circulares.FUSO_SP)
        resultado = self._programacao(
            [{
                # A faixa do dia de serviço anterior cruza a meia-noite e é
                # necessária, mas somente sua porção no dia pedido é válida.
                "inicio": 23 * 3600,
                "fim": 26 * 3600,
                "intervalo": 15 * 60,
                "exact_times": 0,
            }],
            agora,
            datas_permitidas=(date(2026, 8, 27),),
        )

        instantes = [
            datetime.fromisoformat(item["instante"])
            for item in resultado["estimativas"]
        ]
        self.assertTrue(instantes)
        self.assertTrue(
            all(instante.date() == date(2026, 8, 27) for instante in instantes)
        )
        self.assertEqual(
            [instante.strftime("%H:%M") for instante in instantes],
            ["00:00", "00:15", "00:30"],
        )

    def test_proxima_chegada_agora_pode_cruzar_meia_noite_civil(self):
        agora = datetime(2026, 8, 26, 23, 59, tzinfo=circulares.FUSO_SP)
        resultado = self._programacao(
            [{
                "inicio": 24 * 3600 + 6 * 60,
                "fim": 25 * 3600,
                "intervalo": 12 * 60,
                "exact_times": 1,
            }],
            agora,
            datas_permitidas=(date(2026, 8, 26),),
        )

        self.assertEqual(resultado["tipo"], "programacao")
        primeiro = datetime.fromisoformat(resultado["instantes"][0])
        self.assertGreater(primeiro, agora)
        self.assertEqual(primeiro.strftime("%d/%m %H:%M"), "27/08 00:06")

    def test_plataformas_opostas_ficam_separadas_no_fallback_gtfs(self):
        def viagem(destino, stop_id, longitude):
            return {
                "id": f"viagem-{stop_id}",
                "servico": "todos",
                "destino": destino,
                "sentido": "0",
                "frequencias": [{
                    "inicio": 13 * 3600,
                    "fim": 15 * 3600,
                    "intervalo": 15 * 60,
                    "exact_times": 1,
                }],
                "paradas": [{
                    "id": stop_id,
                    "nome": "Ponto de teste",
                    "latitude": -23.55,
                    "longitude": longitude,
                    "sequencia": 1,
                    "deslocamento": 0,
                    "horario": 13 * 3600,
                }],
            }

        catalogo = self._catalogo([])
        catalogo["linhas"]["9998"][0]["viagens"] = [
            viagem("Sentido A", "plataforma-a", -46.7300),
            viagem("Sentido B", "plataforma-b", -46.7301),
        ]
        agora = datetime(2026, 8, 26, 12, 50, tzinfo=circulares.FUSO_SP)
        with (
            patch.object(circulares, "_catalogo_gtfs", return_value=catalogo),
            patch.object(circulares, "horario_gtfs_confiavel", return_value=True),
            patch.object(circulares, "parada_atendida_na_data", return_value=True),
        ):
            resultado = circulares._programacao_gtfs(
                "9998", "Ponto de teste", agora
            )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(
            {
                (sentido["destino"], sentido["parada_id"])
                for sentido in resultado["sentidos"]
            },
            {
                ("Sentido A", "plataforma-a"),
                ("Sentido B", "plataforma-b"),
            },
        )

if __name__ == "__main__":
    unittest.main()
