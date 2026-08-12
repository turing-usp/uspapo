import unittest
from unittest.mock import Mock, patch

from uspapo.ferramentas import Registro
from uspapo.ferramentas import wikipedia


def resposta_json(dados):
    resposta = Mock()
    resposta.json.return_value = dados
    resposta.raise_for_status.return_value = None
    return resposta


class TestWikipedia(unittest.TestCase):
    @patch("uspapo.ferramentas.wikipedia.requests.get")
    def test_busca_retorna_introducoes_e_urls_dos_artigos(self, get):
        get.side_effect = [
            resposta_json({"query": {"search": [
                {"title": "Universidade de São Paulo"},
                {"title": "São Paulo", "snippet": "Capital do estado de São Paulo"},
            ]}}),
            resposta_json({"query": {"pages": [
                {"title": "Universidade de São Paulo", "extract": "A USP é uma universidade pública."},
            ]}}),
        ]

        texto, fontes = wikipedia.consultar_wikipedia("Universidade de São Paulo", "pt")

        self.assertIn("### Universidade de São Paulo", texto)
        self.assertIn("A USP é uma universidade pública.", texto)
        self.assertEqual(fontes, [
            "https://pt.wikipedia.org/wiki/Universidade_de_S%C3%A3o_Paulo",
        ])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["list"], "search")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["prop"], "extracts")

    @patch("uspapo.ferramentas.wikipedia.requests.get")
    def test_resultados_sem_relacao_nao_viram_fontes(self, get):
        get.return_value = resposta_json({"query": {"search": [
            {"title": "Carlos Alberto Barbosa Dantas", "snippet": "Estatístico brasileiro"},
            {"title": "Siang Wong Song", "snippet": "Professor e pesquisador"},
            {"title": "Super Nintendo Entertainment System", "snippet": "Console de jogos"},
        ]}})

        texto, fontes = wikipedia.consultar_wikipedia("imemórias")

        self.assertIn("Não encontrei artigos", texto)
        self.assertEqual(fontes, [])
        get.assert_called_once()

    @patch("uspapo.ferramentas.wikipedia.requests.get")
    def test_palavras_da_pergunta_nao_escondem_resultado_relevante(self, get):
        get.side_effect = [
            resposta_json({"query": {"search": [
                {"title": "Imemórias", "snippet": "Projeto de memória"},
            ]}}),
            resposta_json({"query": {"pages": [
                {"title": "Imemórias", "extract": "Imemórias é um projeto de memória."},
            ]}}),
        ]

        texto, fontes = wikipedia.consultar_wikipedia("O que é o Imemórias?")

        self.assertIn("### Imemórias", texto)
        self.assertEqual(fontes, ["https://pt.wikipedia.org/wiki/Imem%C3%B3rias"])

    @patch("uspapo.ferramentas.wikipedia.requests.get")
    def test_busca_sem_resultados_nao_finge_falha(self, get):
        get.return_value = resposta_json({"query": {"search": []}})

        texto, fontes = wikipedia.consultar_wikipedia("zzzz tema inexistente")

        self.assertIn("Não encontrei artigos", texto)
        self.assertEqual(fontes, [])
        get.assert_called_once()

    @patch(
        "uspapo.ferramentas.wikipedia.requests.get",
        side_effect=wikipedia.requests.ConnectionError("rede indisponível"),
    )
    def test_falha_temporaria_nao_vira_artigo_ausente(self, _get):
        texto, fontes = wikipedia.consultar_wikipedia("tema com falha")

        self.assertIn("Não consegui consultar", texto)
        self.assertEqual(fontes, [])

    def test_registro_expoe_schema_da_ferramenta(self):
        registro = Registro()
        wikipedia.registrar(registro)

        self.assertIn("consultar_wikipedia", registro.nomes)
        schema = registro.schemas[0]["function"]
        self.assertEqual(schema["parameters"]["required"], ["consulta"])
        self.assertIn("iniciativas da USP", schema["description"])


if __name__ == "__main__":
    unittest.main()
