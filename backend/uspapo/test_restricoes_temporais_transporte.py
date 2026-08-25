"""Regressões para horários e faixas preservados na consulta de transporte."""

from __future__ import annotations

from datetime import datetime
import os
import unittest
from unittest.mock import patch

from uspapo.consulta_transporte import interpretar_consulta_transporte
from uspapo.transporte import consultas_circulares as circulares
from uspapo.intencao_transporte import FUSO_SP, analisar_intencao_transporte


DOMINGO = datetime(2026, 8, 23, 14, 10, tzinfo=FUSO_SP)


class TestRestricoesTemporaisTransporte(unittest.TestCase):
    def test_depois_da_meia_noite_preserva_inicio_no_dia_civil_seguinte(self):
        pergunta = "Tem 8012 no Biênio depois da meia-noite hoje?"

        consulta = interpretar_consulta_transporte(pergunta, now=DOMINGO)
        restricao = consulta.period.restricao_temporal

        self.assertIsNotNone(restricao)
        self.assertEqual(restricao.tipo, "apos_meia_noite")
        self.assertEqual(
            restricao.inicio,
            datetime(2026, 8, 24, 0, 0, tzinfo=FUSO_SP),
        )
        self.assertIsNone(restricao.fim)
        self.assertEqual(
            consulta.como_publico()["period"]["time_window"]["start"],
            "2026-08-24T00:00:00-03:00",
        )

    def test_amanha_as_oito_preserva_data_e_horario_alvo(self):
        pergunta = "Quando passa o 8012 amanhã às 8h no Biênio?"

        consulta = interpretar_consulta_transporte(pergunta, now=DOMINGO)
        restricao = consulta.period.restricao_temporal

        self.assertEqual(consulta.como_publico()["period"]["dates"], ["2026-08-24"])
        self.assertIsNotNone(restricao)
        self.assertEqual(restricao.tipo, "horario_alvo")
        self.assertEqual(restricao.horario_alvo, "08:00")
        self.assertEqual(
            restricao.inicio,
            datetime(2026, 8, 24, 8, 0, tzinfo=FUSO_SP),
        )

    def test_domingo_de_manha_preserva_data_e_faixa_sem_hora_falsa(self):
        pergunta = "Tem 8012 no domingo de manhã?"

        consulta = interpretar_consulta_transporte(pergunta, now=DOMINGO)
        restricao = consulta.period.restricao_temporal

        self.assertIsNotNone(restricao)
        self.assertEqual(restricao.tipo, "parte_do_dia")
        self.assertEqual(restricao.parte_do_dia, "manha")
        self.assertIsNone(restricao.horario_alvo)
        self.assertEqual(
            restricao.inicio,
            datetime(2026, 8, 23, 6, 0, tzinfo=FUSO_SP),
        )
        self.assertEqual(
            restricao.fim,
            datetime(2026, 8, 23, 12, 0, tzinfo=FUSO_SP),
        )

    def test_saida_as_2350_alimenta_a_referencia_do_planejador(self):
        pergunta = (
            "Quero sair do metrô às 23:50 e ir pro Biênio. "
            "Ainda tem ônibus?"
        )
        intencao = analisar_intencao_transporte(pergunta, DOMINGO)

        self.assertEqual(
            intencao.instante_para_planejamento(DOMINGO),
            datetime(2026, 8, 23, 23, 50, tzinfo=FUSO_SP),
        )

        plano = {
            "origem": "metro_butanta",
            "destino": "bienio",
            "melhor": {
                "modo": "a_pe",
                "distancia_aproximada_m": 1,
                "total_estimado_min": 1,
            },
            "alternativas": [],
        }
        with (
            patch.object(
                circulares, "_planejar_trajeto_gtfs", return_value=plano,
            ) as planejar,
            patch("uspapo.transporte.consultas_circulares.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = DOMINGO
            datetime_mock.combine.side_effect = datetime.combine
            datetime_mock.fromisoformat.side_effect = datetime.fromisoformat
            resposta = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="bienio",
                _pergunta=pergunta,
            )

        self.assertEqual(
            planejar.call_args.args[2],
            datetime(2026, 8, 23, 23, 50, tzinfo=FUSO_SP),
        )
        self.assertEqual(
            resposta.dados_publicos["consulta_transporte"]["period"]
            ["time_window"]["target_time"],
            "23:50",
        )

    def test_programacao_respeita_janela_depois_da_meia_noite(self):
        intencao = analisar_intencao_transporte(
            "Tem 8012 no Biênio depois da meia-noite hoje?", DOMINGO,
        )

        resultado = circulares._programacao_gtfs(
            "8012",
            "Biênio",
            DOMINGO,
            datas_permitidas=intencao.datas,
            restricao_temporal=intencao.restricao_temporal,
        )
        instantes = [
            datetime.fromisoformat(item["instante"])
            for item in resultado.get("estimativas", [])
        ]

        self.assertTrue(instantes)
        self.assertTrue(all(
            intencao.restricao_temporal.contem(instante)
            for instante in instantes
        ))
        self.assertTrue(all(
            instante.date().isoformat() == "2026-08-24"
            for instante in instantes
        ))

    def test_programacao_de_manha_nao_escapa_da_faixa(self):
        intencao = analisar_intencao_transporte(
            "Tem 8012 no domingo de manhã?", DOMINGO,
        )

        resultado = circulares._programacao_gtfs(
            "8012",
            "Biênio",
            DOMINGO,
            datas_permitidas=intencao.datas,
            restricao_temporal=intencao.restricao_temporal,
        )
        instantes = [
            datetime.fromisoformat(item["instante"])
            for item in resultado.get("estimativas", [])
        ]

        self.assertTrue(instantes)
        self.assertTrue(all(
            intencao.restricao_temporal.contem(instante)
            for instante in instantes
        ))

    def test_live_fora_da_janela_nao_compete_com_programacao(self):
        intencao = analisar_intencao_transporte(
            "Tem 8012 no Biênio depois da meia-noite hoje?", DOMINGO,
        )
        veiculos = [
            {"p": "antes", "t": "23:59", "ta": "23:55", "py": -23.5, "px": -46.7},
            {"p": "dentro", "t": "00:10", "ta": "23:55", "py": -23.5, "px": -46.7},
        ]
        with patch("uspapo.transporte.consultas_circulares.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(
                2026, 8, 23, 23, 55, tzinfo=FUSO_SP,
            )
            datetime_mock.combine.side_effect = datetime.combine
            datetime_mock.fromisoformat.side_effect = datetime.fromisoformat
            ordenados = circulares._veiculos_ao_vivo_ordenados(
                veiculos,
                "23:55",
                intencao.restricao_temporal,
            )

        self.assertEqual([veiculo["p"] for veiculo in ordenados], ["dentro"])

    def test_consulta_sem_restricao_nao_ganha_janela_nova(self):
        consulta = interpretar_consulta_transporte(
            "Quando passa o 8012 no Biênio?", now=DOMINGO,
        )

        self.assertIsNone(consulta.period.restricao_temporal)
        self.assertNotIn("time_window", consulta.como_publico()["period"])

    def test_hora_citada_em_pedido_de_explicacao_permanece_estruturada(self):
        consulta = interpretar_consulta_transporte(
            "Por que você acha que o 8012 passa às 21:41 no Biênio?",
            now=DOMINGO,
        )

        self.assertEqual(consulta.task, "arrival")
        self.assertEqual(
            consulta.period.restricao_temporal.horario_alvo,
            "21:41",
        )

    def test_primeiro_horario_e_reconhecido_como_janela_de_servico(self):
        consulta = interpretar_consulta_transporte(
            "E amanhã, que horas começa a rodar o 8012?", now=DOMINGO,
        )

        self.assertEqual(consulta.task, "service_info")
        self.assertTrue(consulta.facets.service_window)
        self.assertEqual(consulta.period.datas[0].isoformat(), "2026-08-24")

    def test_casos_de_chegada_preservam_janela_no_resultado_end_to_end(self):
        casos = (
            (
                "Tem 8012 no Biênio depois da meia-noite hoje?",
                "apos_meia_noite",
            ),
            ("Quando passa o 8012 amanhã às 8h no Biênio?", "horario_alvo"),
            ("Tem 8012 no domingo de manhã?", "parte_do_dia"),
        )
        with (
            patch("uspapo.transporte.consultas_circulares.datetime") as datetime_mock,
            patch.dict(os.environ, {"SPTRANS_TOKEN": ""}),
        ):
            datetime_mock.now.return_value = DOMINGO
            datetime_mock.combine.side_effect = datetime.combine
            datetime_mock.fromisoformat.side_effect = datetime.fromisoformat
            for pergunta, tipo in casos:
                with self.subTest(pergunta=pergunta):
                    resposta = circulares.consultar_circulares(
                        "8012",
                        "Biênio",
                        _pergunta=pergunta,
                    )
                    periodo = resposta.dados_publicos[
                        "consulta_transporte"
                    ]["period"]
                    self.assertEqual(periodo["time_window"]["type"], tipo)

        intencao = analisar_intencao_transporte(casos[0][0], DOMINGO)
        programacao = circulares._programacao_gtfs(
            "8012", "Biênio", DOMINGO,
            datas_permitidas=intencao.datas,
            restricao_temporal=intencao.restricao_temporal,
        )
        chegadas_meia_noite = programacao.get("estimativas", [])
        self.assertTrue(chegadas_meia_noite)
        self.assertTrue(all(
            datetime.fromisoformat(item["instante"])
            >= datetime(2026, 8, 24, 0, 0, tzinfo=FUSO_SP)
            for item in chegadas_meia_noite
        ))


if __name__ == "__main__":
    unittest.main()
