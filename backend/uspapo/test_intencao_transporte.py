from datetime import date, datetime, timezone
import unittest

from uspapo.intencao_transporte import FUSO_SP, analisar_intencao_transporte


QUARTA = datetime(2026, 8, 12, 14, 30, tzinfo=FUSO_SP)
SABADO = datetime(2026, 8, 15, 14, 30, tzinfo=FUSO_SP)
DOMINGO = datetime(2026, 8, 16, 14, 30, tzinfo=FUSO_SP)


class TestIntencaoTransporte(unittest.TestCase):
    def test_fim_de_semana_aponta_para_o_proximo_ou_atual(self):
        for agora in (QUARTA, SABADO, DOMINGO):
            with self.subTest(agora=agora):
                intencao = analisar_intencao_transporte(
                    "Quais ônibus passam no Biênio neste fim de semana?", agora
                )
                self.assertEqual(
                    intencao.datas,
                    (date(2026, 8, 15), date(2026, 8, 16)),
                )

    def test_hoje_tem_prioridade_quando_tambem_menciona_fim_de_semana(self):
        intencao = analisar_intencao_transporte(
            "Quais ônibus passam hoje, neste fim de semana?", SABADO
        )

        self.assertEqual(intencao.periodo, "hoje")
        self.assertEqual(intencao.datas, (date(2026, 8, 15),))

    def test_sabado_e_domingo_isolados_tambem_criam_horizonte(self):
        casos = (
            ("Quais ônibus passam sábado?", date(2026, 8, 15)),
            ("Quais ônibus passam domingo?", date(2026, 8, 16)),
        )
        for pergunta, dia in casos:
            with self.subTest(pergunta=pergunta):
                intencao = analisar_intencao_transporte(pergunta, QUARTA)
                self.assertEqual(intencao.datas, (dia,))

    def test_plural_proximo_e_passado_de_fim_de_semana(self):
        casos = (
            (
                "Aos finais de semana",
                (date(2026, 8, 15), date(2026, 8, 16)),
            ),
            (
                "No próximo fim de semana",
                (date(2026, 8, 22), date(2026, 8, 23)),
            ),
            (
                "No fim de semana passado",
                (date(2026, 8, 8), date(2026, 8, 9)),
            ),
        )
        for pergunta, datas in casos:
            with self.subTest(pergunta=pergunta):
                intencao = analisar_intencao_transporte(pergunta, SABADO)
                self.assertEqual(intencao.datas, datas)
                self.assertFalse(intencao.pede_chegada)

    def test_previsoes_no_plural_pedem_chegada(self):
        intencao = analisar_intencao_transporte(
            "Previsões do 8084 no Biênio", SABADO
        )

        self.assertTrue(intencao.pede_chegada)
        self.assertTrue(intencao.tempo_real)

    def test_chegada_sem_data_fica_limitada_a_hoje(self):
        intencao = analisar_intencao_transporte(
            "Quando chega o próximo 8084?", SABADO
        )

        self.assertTrue(intencao.pede_chegada)
        self.assertTrue(intencao.tempo_real)
        self.assertEqual(intencao.datas, (date(2026, 8, 15),))

    def test_qual_onibus_circular_ou_linha_restringe_o_modo(self):
        perguntas = (
            "Qual ônibus eu pego?",
            "Que circular devo pegar?",
            "Qual BUSP serve o local?",
            "Qual linha devo pegar?",
        )
        for pergunta in perguntas:
            with self.subTest(pergunta=pergunta):
                intencao = analisar_intencao_transporte(pergunta, QUARTA)
                self.assertEqual(intencao.modo_solicitado, "onibus")

    def test_pergunta_generica_usa_dia_util_tipico(self):
        intencao = analisar_intencao_transporte(
            "Quanto tempo demora do metrô ao IME?", SABADO
        )

        referencia = intencao.instante_para_planejamento(SABADO)
        self.assertEqual(referencia.date(), date(2026, 8, 17))
        self.assertEqual((referencia.hour, referencia.minute), (10, 0))

    def test_instante_utc_e_convertido_para_sao_paulo(self):
        instante_utc = datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc)

        intencao = analisar_intencao_transporte("Quais ônibus passam hoje?", instante_utc)

        self.assertEqual(intencao.datas, (date(2026, 8, 15),))


if __name__ == "__main__":
    unittest.main()
