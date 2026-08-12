import unittest
from types import SimpleNamespace
from unittest.mock import patch

from uspapo.contexto import Orcamento
from uspapo.conversa import conversar_com_provedor
from uspapo.ferramentas import Registro
from uspapo.ferramentas import circulares


class ProvedorFalso:
    nome = "teste"


def chunk_de_texto(texto):
    delta = SimpleNamespace(content=texto, tool_calls=[], model_extra={})
    escolha = SimpleNamespace(delta=delta)
    return SimpleNamespace(usage=None, choices=[escolha])


class TestPreconsultaConversa(unittest.TestCase):
    def test_melhor_onibus_recebe_trajeto_em_vez_de_lista_do_destino(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)
        capturado = {}

        def abrir(_provedor, mensagens, _tools):
            capturado["mensagens"] = mensagens
            capturado["chamadas"] = capturado.get("chamadas", 0) + 1
            return [chunk_de_texto("A melhor opção é a indicada no trajeto oficial.")]

        pergunta = (
            "Eu venho do portão da entrada de pedestres da cidade universitária, "
            "perto do P1. Qual o melhor ônibus pra chegar ao Biênio?"
        )
        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            ))

        contexto = capturado["mensagens"][-1]["content"]
        self.assertEqual(capturado["chamadas"], 1)
        self.assertIn("Melhor opção pelo GTFS", contexto)
        self.assertIn("Embarque em", contexto)
        self.assertNotIn("atendida por 11 linhas", contexto)

    def test_linhas_do_bienio_chegam_completas_na_primeira_chamada(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)
        capturado = {}

        def abrir(_provedor, mensagens, _tools):
            capturado["mensagens"] = mensagens
            capturado["chamadas"] = capturado.get("chamadas", 0) + 1
            return [chunk_de_texto("A parada é atendida pelas 11 linhas listadas.")]

        pergunta = "Quais linhas de ônibus passam pelo ponto do Biênio?"
        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            ))

        contexto = capturado["mensagens"][-1]["content"]
        self.assertEqual(capturado["chamadas"], 1)
        self.assertIn("atendida por 11 linhas", contexto)
        self.assertIn("177H-10", contexto)
        self.assertIn("8084-10", contexto)

    def test_titulo_oficial_chega_ao_modelo_na_primeira_chamada(self):
        registro = Registro()
        orcamento = Orcamento(registro)
        capturado = {}

        def abrir(_provedor, mensagens, _tools):
            capturado["mensagens"] = mensagens
            capturado["chamadas"] = capturado.get("chamadas", 0) + 1
            return [chunk_de_texto("O IMEmórias é um projeto de entrevistas em vídeo.")]

        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, "O que é o IMEmórias?",
                [], set(), {}, 16000,
            ))

        self.assertEqual(capturado["chamadas"], 1)
        self.assertIn("Projeto IMEmórias", capturado["mensagens"][-1]["content"])
        self.assertTrue(any(e["tipo"] == "ferramenta" for e in eventos))
        self.assertTrue(any(e["tipo"] == "texto" for e in eventos))


if __name__ == "__main__":
    unittest.main()
