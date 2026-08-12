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
            resposta_json({"query": {"search": [{"title": "Universidade de São Paulo"}, {"title": "Cidade Universitária Armando de Salles Oliveira"}]}}),
            resposta_json({"query": {"pages": [
                {"title": "Universidade de São Paulo", "extract": "A USP é uma universidade pública."},
                {"title": "Cidade Universitária Armando de Salles Oliveira", "extract": "É o campus principal."},
            ]}}),
        ]

        texto, fontes = wikipedia.consultar_wikipedia("Universidade de São Paulo", "pt")

        self.assertIn("### Universidade de São Paulo", texto)
        self.assertIn("A USP é uma universidade pública.", texto)
        self.assertEqual(fontes, [
            "https://pt.wikipedia.org/wiki/Universidade_de_S%C3%A3o_Paulo",
            "https://pt.wikipedia.org/wiki/Cidade_Universit%C3%A1ria_Armando_de_Salles_Oliveira",
        ])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["list"], "search")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["prop"], "extracts")

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
        self.assertIn("história de unidade da USP", schema["description"])


if __name__ == "__main__":
    unittest.main()
