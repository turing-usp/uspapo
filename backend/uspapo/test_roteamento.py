import unittest
from unittest.mock import Mock

from uspapo import roteamento


class TestRoteamento(unittest.TestCase):
    def test_extrai_origem_e_destino_de_perguntas_de_trajeto(self):
        casos = {
            (
                "Eu venho do portão da entrada de pedestres da cidade universitária, "
                "perto do P1. Qual o melhor ônibus pra chegar ao Biênio?"
            ): {"origem": "p1", "destino_ou_ponto": "bienio"},
            "Qual o melhor ônibus pra ir do Biênio até a Química?": {
                "origem": "bienio", "destino_ou_ponto": "quimica"
            },
            (
                "Aonde fica o prédio da Engenharia Mecânica e como chegar lá "
                "do Metrô Butantã?"
            ): {"origem": "metro_butanta", "destino_ou_ponto": "mecanica"},
            "Qual o melhor ônibus da FEA até Letras?": {
                "origem": "fea", "destino_ou_ponto": "letras"
            },
        }

        for pergunta, esperado in casos.items():
            with self.subTest(pergunta=pergunta):
                self.assertEqual(roteamento.pedido_trajeto(pergunta), esperado)

    def test_nome_oficial_exato_encontra_imemorias(self):
        pagina = roteamento.pagina_por_titulo("O que é o imemórias?")

        self.assertEqual(pagina["titulo"], "IMEmórias")
        self.assertEqual(pagina["url"], "https://www.ime.usp.br/imemorias/")
        self.assertIn("entrevistas em vídeo", pagina["texto"])

    def test_nome_generico_nao_chuta_pagina(self):
        self.assertIsNone(roteamento.pagina_por_titulo("O que é memória?"))

    def test_tipo_generico_nao_impede_titulo_exato(self):
        pagina = roteamento.pagina_por_titulo("Explique o projeto IMEmórias")

        self.assertEqual(pagina["titulo"], "IMEmórias")

    def test_extrai_linha_e_ponto_do_bienio(self):
        pedido = roteamento.pedido_circular(
            "Quando que chega o próximo 8084 no ponto do biênio?"
        )

        self.assertEqual(pedido, {"linha": "8084", "destino_ou_ponto": "biênio"})

    def test_extrai_ponto_mesmo_sem_numero_de_linha(self):
        pedido = roteamento.pedido_circular(
            "Quais linhas de ônibus passam pelo ponto do Biênio?"
        )

        self.assertEqual(pedido, {"linha": "", "destino_ou_ponto": "Biênio"})

    def test_preconsulta_executa_ferramenta_sem_modelo(self):
        registro = Mock()
        registro.nomes = {"consultar_circulares"}
        registro.executar_direto.return_value = ("Chega às 21:04.", ["sptrans"])

        resultado = roteamento.preconsultar(
            registro, "Quando chega o 8084 no ponto do biênio?"
        )

        registro.executar_direto.assert_called_once_with(
            "consultar_circulares", linha="8084", destino_ou_ponto="biênio"
        )
        self.assertEqual(resultado, ("Chega às 21:04.", ["sptrans"], "consultar_circulares"))


if __name__ == "__main__":
    unittest.main()
