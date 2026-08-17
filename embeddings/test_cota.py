"""Testes do medidor mensal de tokens de embedding e do piso de frequência.

O que se protege aqui é o erro que derrubou a indexação em agosto de 2026:

    [429] You've reached the embedding token limit (5000000) for model
    multilingual-e5-large for the current month across your organization.

Ele não é um pico de requisições, é a cota do mês inteiro. As travas que já
existiam (`ORCAMENTO_UPSERTS`, `LIMIAR_ABORTO_PCT`) são por execução e somavam
sem ninguém contar; o rebuild completo do corpus custa mais que a cota sozinho.

Rodar: python -m unittest embeddings.test_cota -v, a partir da raiz do projeto.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from embeddings import cota
from scrapers.spiders import rodar_scrapers


class TestOrcamento(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.arquivo = os.path.join(self.pasta.name, "cota_embeddings.json")
        self._patch = patch.object(cota, "ARQUIVO", self.arquivo)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.pasta.cleanup()

    def test_reserva_uma_fatia_para_as_perguntas_dos_alunos(self):
        """Toda pergunta no site vetoriza a consulta na MESMA cota."""
        self.assertLess(cota.orcamento_de_indexacao(), cota.LIMITE_MENSAL)
        self.assertEqual(
            cota.orcamento_de_indexacao(),
            int((cota.LIMITE_MENSAL - cota.RESERVA_CONSULTAS) * (1 - cota.MARGEM)),
        )

    def test_estimativa_e_pessimista(self):
        """Melhor parar cedo demais do que descobrir a cota no meio da remessa."""
        # O corpus real tem ~3,5 caracteres por token em português.
        tokens = cota.estimar_tokens(["x" * 3500])
        self.assertGreater(tokens, 1000)

    def test_rebuild_completo_nao_cabe_em_um_mes(self):
        """Foi exatamente assim que o 429 apareceu."""
        corpus = ["x" * 896] * 24_794

        cabe, motivo = cota.cabe(cota.estimar_tokens(corpus))

        self.assertFalse(cabe)
        self.assertIn("só restam", motivo)
        self.assertIn("virada do mês", motivo)

    def test_ronda_semanal_cabe_com_folga(self):
        por_ronda = cota.estimar_tokens(["x" * 896] * 3000)
        mes = por_ronda * 4.3  # 4,3 segundas-feiras por mês

        self.assertLessEqual(mes, cota.orcamento_de_indexacao())

    def test_gasto_acumula_entre_execucoes(self):
        """A trava por execução somava sem ninguém contar o mês."""
        metade = cota.orcamento_de_indexacao() // 2 + 1000
        cota.registrar(metade)

        self.assertTrue(cota.cabe(1000)[0])
        self.assertFalse(cota.cabe(metade)[0])
        self.assertEqual(cota.carregar()["tokens"], metade)
        self.assertEqual(cota.carregar()["lotes"], 1)

    def test_mes_novo_zera_o_contador(self):
        cota.registrar(1_000_000)
        estado = cota.carregar()
        estado["mes"] = "2000-01"
        cota.salvar(estado)

        self.assertEqual(cota.carregar()["tokens"], 0)
        self.assertEqual(cota.disponivel(), cota.orcamento_de_indexacao())

    def test_arquivo_corrompido_nao_derruba_a_leitura(self):
        with open(self.arquivo, "w", encoding="utf-8") as arquivo:
            arquivo.write("{ isto não é json")

        self.assertEqual(cota.carregar()["tokens"], 0)

    def test_numeros_grandes_nao_estragam_a_frase(self):
        _cabe, motivo = cota.cabe(9_000_000)

        self.assertIn("~9.000.000 tokens de embedding, mas", motivo)


class TestCotaNoBuildVector(unittest.TestCase):
    def test_429_de_cota_mensal_nao_e_repetido_com_backoff(self):
        """Insistir seis vezes numa cota mensal só atrasa a falha."""
        from embeddings import build_vector

        erro_429 = (
            "[429] Request failed. You've reached the embedding token limit "
            "(5000000) for model multilingual-e5-large for the current month "
            "across your organization. To continue using this model, upgrade "
            "your plan."
        )
        tentativas = []

        def operacao():
            tentativas.append(1)
            raise RuntimeError(erro_429)

        with self.assertRaises(build_vector.CotaMensalEstourada):
            build_vector.executar_com_backoff(operacao, "upsert")

        self.assertEqual(len(tentativas), 1)

    def test_429_de_ritmo_continua_sendo_repetido(self):
        from embeddings import build_vector

        tentativas = []

        def operacao():
            tentativas.append(1)
            if len(tentativas) < 2:
                raise RuntimeError("[429] Too Many Requests")
            return "ok"

        with patch("embeddings.build_vector.time.sleep"):
            self.assertEqual(
                build_vector.executar_com_backoff(operacao, "upsert"), "ok"
            )
        self.assertEqual(len(tentativas), 2)


class TestPisoDeFrequencia(unittest.TestCase):
    """Raspar é barato; reindexar não é. Nenhum site volta antes de uma semana."""

    def test_frequencia_menor_que_o_piso_e_elevada(self):
        self.assertEqual(rodar_scrapers.dias_de_frequencia("1d"), 7)
        self.assertEqual(rodar_scrapers.dias_de_frequencia("3d"), 7)
        self.assertEqual(rodar_scrapers.dias_de_frequencia("7d"), 7)

    def test_frequencias_maiores_sao_preservadas(self):
        self.assertEqual(rodar_scrapers.dias_de_frequencia("14d"), 14)
        self.assertEqual(rodar_scrapers.dias_de_frequencia("21d"), 21)

    def test_frequencia_invalida_cai_no_piso(self):
        self.assertEqual(rodar_scrapers.dias_de_frequencia("semanal"), 7)
        self.assertEqual(rodar_scrapers.dias_de_frequencia(None), 7)

    def test_site_raspado_ontem_com_1d_nao_vence_hoje(self):
        from datetime import datetime, timedelta

        ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        self.assertFalse(rodar_scrapers.calcular_vencimento(ontem, "1d"))
        self.assertFalse(rodar_scrapers.calcular_vencimento(ontem, "7d"))

    def test_site_raspado_ha_oito_dias_vence(self):
        from datetime import datetime, timedelta

        antigo = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")

        self.assertTrue(rodar_scrapers.calcular_vencimento(antigo, "7d"))
        self.assertFalse(rodar_scrapers.calcular_vencimento(antigo, "14d"))

    def test_config_nao_declara_frequencia_abaixo_do_piso(self):
        """O piso mora no código, mas a config não deve contradizê-lo."""
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(raiz, "scrapers_config.json"), encoding="utf-8") as f:
            configuracoes = json.load(f)

        for site in configuracoes:
            with self.subTest(site=site["id_site"]):
                declarada = str(site.get("frequency", "7d")).replace("d", "")
                self.assertGreaterEqual(
                    int(declarada), rodar_scrapers.MIN_FREQUENCIA_DIAS
                )


if __name__ == "__main__":
    unittest.main()
