from datetime import datetime
import unittest
from unittest.mock import patch

from uspapo.consulta_transporte import interpretar_consulta_transporte
from uspapo.ferramentas import RespostaFerramenta
from uspapo.transporte import consultas_circulares as circulares
from uspapo.intencao_transporte import FUSO_SP
from uspapo import roteamento


AGORA = datetime(2026, 8, 12, 14, 30, tzinfo=FUSO_SP)


class TestConsultaTransporte(unittest.TestCase):
    def test_rota_composta_trata_duracao_como_faceta(self):
        consulta = interpretar_consulta_transporte(
            "Qual ônibus pego do metrô pro IME e quanto demora?", now=AGORA
        )

        self.assertEqual(consulta.task, "route")
        self.assertEqual(consulta.entities.origin, "metro_butanta")
        self.assertEqual(consulta.entities.destination, "ime")
        self.assertTrue(consulta.facets.duration)

    def test_rota_com_alternativas_nao_precisa_de_outra_intencao(self):
        consulta = interpretar_consulta_transporte(
            "Qual é o melhor ônibus do metrô pro IME e quais alternativas eu tenho?",
            now=AGORA,
        )

        self.assertEqual(consulta.task, "route")
        self.assertTrue(consulta.facets.alternatives)

    def test_chegada_composta_reune_tempo_real_e_confianca(self):
        consulta = interpretar_consulta_transporte(
            "Quando chega o 8084 no IME e ele está confiável?", now=AGORA
        )

        self.assertEqual(consulta.task, "arrival")
        self.assertEqual(consulta.entities.line, "8084")
        self.assertEqual(consulta.entities.stop, "ime")
        self.assertTrue(consulta.facets.realtime)
        self.assertTrue(consulta.facets.confidence)

    def test_proximo_e_outro_depois_pedem_mais_chegadas_sem_chutar_parada(self):
        consulta = interpretar_consulta_transporte(
            "Quando chega o próximo 8084 e tem outro depois?", now=AGORA
        )

        self.assertEqual(consulta.task, "arrival")
        self.assertEqual(consulta.needs_clarification, ("stop",))
        self.assertTrue(consulta.facets.more_arrivals)

    def test_operacao_e_janela_tem_tarefa_propria(self):
        consulta = interpretar_consulta_transporte(
            "O 8084 passa no IME hoje à noite e até que horas?", now=AGORA
        )

        self.assertEqual(consulta.task, "service_info")
        self.assertTrue(consulta.facets.service_window)
        self.assertEqual(consulta.entities.stop, "ime")

    def test_atendimento_de_linha_em_parada_tem_tarefa_operacional(self):
        consulta = interpretar_consulta_transporte(
            "A 8012 passa no Biênio hoje?", now=AGORA,
        )

        self.assertEqual(consulta.task, "service_info")
        self.assertTrue(consulta.facets.service_at_stop)
        self.assertEqual(consulta.entities.line, "8012")
        self.assertEqual(consulta.entities.stop, "bienio")

    def test_pergunta_aberta_permanece_general(self):
        consulta = interpretar_consulta_transporte(
            "O circular é uma boa ideia para conhecer a USP?", now=AGORA
        )

        self.assertEqual(consulta.task, "general")
        self.assertEqual(consulta.needs_clarification, ())

    def test_consulta_aberta_nao_e_preconsultada_e_fica_para_llm(self):
        registro = type("RegistroFalso", (), {"nomes": {"consultar_circulares"}})()

        resultado = roteamento.preconsultar(
            registro, "O circular é uma boa ideia para conhecer a USP?"
        )

        self.assertIsNone(resultado)

    def test_ferramenta_anexa_consulta_sem_alterar_motor_factual(self):
        resposta_motor = RespostaFerramenta(
            "Rota factual.", ["gtfs"], {"tipo": "trajeto_onibus"}
        )
        with patch(
            "uspapo.transporte.consultas_circulares._consultar_circulares_calcular",
            return_value=resposta_motor,
        ):
            resposta = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="ime",
                _pergunta="Qual ônibus pego do metrô pro IME e quanto demora?",
            )

        assert isinstance(resposta, RespostaFerramenta)
        self.assertEqual(resposta.dados_publicos["consulta_transporte"]["task"], "route")
        self.assertIsNotNone(resposta.resultado_transporte)
        self.assertEqual(resposta.resultado_transporte.kind, "trajeto_onibus")

    def test_service_info_nao_e_forcado_para_motor_de_chegadas(self):
        with patch(
            "uspapo.transporte.consultas_circulares._consultar_circulares_calcular"
        ) as calcular:
            resposta = circulares.consultar_circulares(
                linha="8084",
                destino_ou_ponto="ime",
                _pergunta="O 8084 passa no IME hoje e até que horas?",
            )

        assert isinstance(resposta, RespostaFerramenta)
        calcular.assert_not_called()
        self.assertEqual(resposta.dados_publicos["consulta_transporte"]["task"], "service_info")


if __name__ == "__main__":
    unittest.main()
