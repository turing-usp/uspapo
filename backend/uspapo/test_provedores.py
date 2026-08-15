import json
import unittest
from unittest.mock import patch

from uspapo.provedores import carregar_provedores


class TestProvedores(unittest.TestCase):
    def test_nomes_repetidos_nao_eliminam_credenciais_de_fallback(self):
        configuracao = [
            {
                "nome": "groq-modelo",
                "base_url": "https://exemplo.invalid/v1",
                "api_key": "chave-a",
                "model": "modelo",
            },
            {
                "nome": "groq-modelo",
                "base_url": "https://exemplo.invalid/v1",
                "api_key": "chave-b",
                "model": "modelo",
            },
        ]
        with (
            patch.dict(
                "os.environ",
                {"LLM_PROVIDERS": json.dumps(configuracao)},
                clear=True,
            ),
            patch("uspapo.provedores.OpenAI") as cliente,
        ):
            provedores = carregar_provedores()

        self.assertEqual(
            [provedor.nome for provedor in provedores],
            ["groq-modelo", "groq-modelo-2"],
        )
        self.assertEqual(cliente.call_count, 2)
        self.assertNotEqual(provedores[0].nome, provedores[1].nome)


if __name__ == "__main__":
    unittest.main()
