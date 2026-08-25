"""Regressões de ponta a ponta para as perguntas que falharam localmente."""

from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from uspapo.ferramentas import Registro
from uspapo.transporte import consultas_circulares as circulares
from uspapo.roteamento import preconsultar


SABADO = datetime(2026, 8, 15, 13, 0, tzinfo=circulares.FUSO_SP)


class DatetimeCongelado(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return SABADO.replace(tzinfo=None)
        return SABADO.astimezone(tz)


class TestFluxosTransporteRegressoes(unittest.TestCase):
    def setUp(self):
        self.registro = Registro()
        circulares.registrar(self.registro)
        self._sem_token = patch.dict("os.environ", {"SPTRANS_TOKEN": ""})
        self._relogio = patch.object(circulares, "datetime", DatetimeCongelado)
        self._sem_token.start()
        self._relogio.start()

    def tearDown(self):
        self._relogio.stop()
        self._sem_token.stop()

    def test_bienio_no_fim_de_semana_lista_somente_8012(self):
        resposta = preconsultar(
            self.registro,
            "Quais ônibus estão passando no biênio esse final de semana?",
        )

        self.assertIsNotNone(resposta)
        texto, _fontes, _nome, dados = resposta
        self.assertIn("8012-10", texto)
        self.assertNotIn("8084-10", texto)
        self.assertNotIn("8086-10", texto)
        self.assertEqual(dados["total"], 1)
        self.assertEqual(
            [item["linha"] for item in dados["linhas"]], ["8012-10"]
        )

    def test_bienio_no_sabado_tambem_lista_somente_8012(self):
        resposta = preconsultar(
            self.registro,
            "Quais ônibus passam no Biênio sábado?",
        )

        self.assertIsNotNone(resposta)
        texto, _fontes, _nome, dados = resposta
        self.assertIn("8012-10", texto)
        self.assertNotIn("8084-10", texto)
        self.assertNotIn("8086-10", texto)
        self.assertEqual(dados["total"], 1)

    def test_proximo_8084_herda_bienio_e_diz_que_nao_opera_hoje(self):
        historico = [{
            "pergunta": "Quais ônibus passam no ponto do Biênio?",
            "resposta": "No fim de semana, somente a 8012-10 atende o ponto.",
        }, {
            "pergunta": "Para ir do Central até o IB, qual ônibus eu pego?",
            "resposta": "Use a 8022-10.",
        }]

        resposta = preconsultar(
            self.registro,
            "Quando chega o próximo 8084 hoje?",
            historico,
        )

        self.assertIsNotNone(resposta)
        texto, _fontes, _nome, dados = resposta
        self.assertIn("não tem serviço programado", texto)
        self.assertEqual(dados["status_operacao"], "sem_servico")
        self.assertEqual(dados["periodo"], "hoje")
        self.assertNotIn("17/08", texto)

    def test_proximo_8084_sem_contexto_pede_a_parada(self):
        resposta = preconsultar(
            self.registro,
            "Quando chega o próximo 8084 hoje?",
        )

        self.assertIsNotNone(resposta)
        texto, fontes, _nome, dados = resposta
        self.assertIn("Em qual parada", texto)
        self.assertEqual(fontes, [])
        self.assertEqual(dados["campo_necessario"], "parada")
        self.assertNotIn("Paradas oficiais do itinerário", texto)

    def test_resposta_ao_esclarecimento_preserva_linha_e_hoje(self):
        historico = [{
            "pergunta": "Quando chega o próximo 8084 hoje?",
            "resposta": "Em qual parada você quer saber a chegada da linha 8084?",
        }]

        resposta = preconsultar(self.registro, "Biênio", historico)

        self.assertIsNotNone(resposta)
        texto, _fontes, _nome, dados = resposta
        self.assertIn("não tem serviço programado", texto)
        self.assertEqual(dados["linha"], "8084-10")
        self.assertEqual(dados["parada"], "Biênio")
        self.assertEqual(dados["periodo"], "hoje")

    def test_perguntas_de_trajeto_nao_sao_substituidas_por_caminhada(self):
        perguntas = (
            "Quanto tempo demora pra chegar no IME a partir do metrô?",
            "Para ir do central até o IB, qual ônibus eu devo pegar?",
        )
        for pergunta in perguntas:
            with self.subTest(pergunta=pergunta):
                resposta = preconsultar(self.registro, pergunta)
                self.assertIsNotNone(resposta)
                texto, _fontes, _nome, dados = resposta
                self.assertEqual(dados["tipo"], "trajeto_onibus")
                self.assertEqual(dados["melhor_opcao"].get("modo", "onibus"), "onibus")
                self.assertNotIn("a melhor opção é ir a pé", texto)

    def test_sentido_explicito_incompativel_nunca_retorna_o_oposto(self):
        resposta = circulares.consultar_circulares(
            "8012",
            "Biênio",
            _pergunta="Quando passa o 8012 no Biênio sentido Metrô Butantã?",
        )

        dados = resposta.dados_publicos
        self.assertEqual(dados["tipo"], "sentido_incompativel")
        self.assertEqual(dados["sentido_solicitado"], "Metrô Butantã")
        self.assertNotIn("Cid. Universitária", str(dados))

    def test_sentido_cidade_universitaria_nao_mistura_o_oposto(self):
        resposta = circulares.consultar_circulares(
            "8012",
            "Biênio",
            _pergunta="Quando passa o 8012 no Biênio sentido Cidade Universitária?",
        )

        dados = resposta.dados_publicos
        self.assertEqual(dados["tipo"], "chegada_onibus")
        self.assertEqual(dados["consulta_transporte"]["task"], "arrival")
        self.assertTrue(dados["sentidos"])
        self.assertTrue(all(
            item["sentido"] == "Cid. Universitária"
            for item in dados["sentidos"]
        ))

    def test_passa_sem_restricao_temporal_e_atendimento_booleano(self):
        resposta = circulares.consultar_circulares(
            "8012", "Biênio", _pergunta="O 8012 passa no Biênio?"
        )

        self.assertEqual(resposta.dados_publicos["tipo"], "atendimento_linha_parada")
        self.assertEqual(
            resposta.dados_publicos["consulta_transporte"]["task"], "service_info"
        )

    def test_quando_passa_e_consulta_de_chegada_nao_atendimento(self):
        resposta = circulares.consultar_circulares(
            "8012", "Biênio", _pergunta="Quando passa o 8012 no Biênio?"
        )

        self.assertEqual(resposta.dados_publicos["tipo"], "chegada_onibus")
        self.assertEqual(
            resposta.dados_publicos["consulta_transporte"]["task"], "arrival"
        )

    def test_tem_com_faixa_horaria_consulta_programacao_em_vez_de_booleano(self):
        perguntas = (
            "Tem 8012 no Biênio depois da meia-noite hoje?",
            "Tem 8012 no Biênio amanhã de manhã?",
        )
        for pergunta in perguntas:
            with self.subTest(pergunta=pergunta):
                resposta = circulares.consultar_circulares(
                    "8012", "Biênio", _pergunta=pergunta
                )
                dados = resposta.dados_publicos
                self.assertEqual(dados["tipo"], "chegada_onibus")
                self.assertEqual(dados["consulta_transporte"]["task"], "arrival")
                self.assertTrue(dados["consulta_transporte"]["period"]["dates"])


if __name__ == "__main__":
    unittest.main()
