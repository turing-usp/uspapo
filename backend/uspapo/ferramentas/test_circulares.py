import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from uspapo.ferramentas import circulares


class SessaoSPTransFalsa:
    def __init__(self):
        self.consultas = []

    def post(self, url, **kwargs):
        resposta = Mock(status_code=200)
        resposta.json.return_value = True
        return resposta

    def get(self, url, params=None, **kwargs):
        caminho = url.rsplit("/", 1)[-1]
        self.consultas.append((caminho, params))
        resposta = Mock()
        resposta.raise_for_status.return_value = None
        if caminho == "Buscar":
            resposta.json.return_value = [
                {"cl": 35812, "lt": "8084", "tl": 10, "sl": 1,
                 "tp": "METRO BUTANTA", "ts": "CIDADE UNIVERSITARIA"}
            ]
        elif caminho == "Linha":
            resposta.json.return_value = {
                "hr": "21:00",
                "ps": [
                    {"cp": 1, "np": "AV. PROF. LUCIANO GUALBERTO", "ed": "POLI USP",
                     "py": -23.5551, "px": -46.7315, "vs": [
                        {"t": "21:04", "a": True},
                        {"t": "21:18", "a": False},
                     ]},
                    {"cp": 2, "np": "OUTRA PARADA", "ed": "FORA DO CAMPUS",
                     "py": -23.60, "px": -46.70, "vs": []},
                ],
            }
        else:
            raise AssertionError(f"Endpoint inesperado: {url}")
        return resposta


class SessaoSemPrevisaoFalsa:
    def __init__(self):
        self.consultas = []

    def post(self, url, **kwargs):
        resposta = Mock(status_code=200)
        resposta.json.return_value = True
        return resposta

    def get(self, url, params=None, **kwargs):
        self.consultas.append(url)
        resposta = Mock()
        resposta.raise_for_status.return_value = None
        if "/Linha/Buscar" in url:
            resposta.json.return_value = [
                {"cl": 2607, "lt": "8084", "tl": 10, "sl": 1,
                 "tp": "CIDADE UNIVERSITARIA", "ts": "METRO BUTANTA"}
            ]
        elif "/Previsao/Linha" in url:
            resposta.json.return_value = {"hr": "11:30", "ps": []}
        elif "/Posicao/Linha" in url:
            resposta.json.return_value = {
                "hr": "11:30",
                "vs": [{"p": "1"}, {"p": "2"}],
            }
        else:
            raise AssertionError(f"Endpoint inesperado: {url}")
        return resposta


class TestCirculares(unittest.TestCase):
    def test_planejador_compara_origem_destino_e_sentido(self):
        agora = datetime(2026, 8, 12, 11, 30, tzinfo=circulares.FUSO_SP)
        casos = {
            ("p1", "bienio"): "8084-10",
            ("bienio", "quimica"): "702U-10",
            ("metro_butanta", "mecanica"): "8082-10",
        }

        for (origem, destino), linha_esperada in casos.items():
            with self.subTest(origem=origem, destino=destino):
                plano = circulares._planejar_trajeto_gtfs(origem, destino, agora)
                self.assertEqual(plano["melhor"]["linha"], linha_esperada)
                self.assertGreater(plano["melhor"]["viagem_min"], 0)
                self.assertLessEqual(
                    plano["melhor"]["caminhada_origem_m"], 320
                )
                self.assertLessEqual(
                    plano["melhor"]["caminhada_destino_m"], 320
                )

    def test_consulta_reversa_lista_todas_as_linhas_do_bienio(self):
        resultado = circulares._linhas_por_ponto_gtfs("Biênio")

        linhas = {item["linha"] for item in resultado["linhas"]}
        self.assertEqual(linhas, {
            "177H-10", "701U-10", "702U-10", "7181-10", "7411-10",
            "7725-10", "8012-10", "8084-10", "8085-10", "8086-10",
            "809U-10",
        })

        texto, fontes = circulares.consultar_circulares(None, "Biênio")
        self.assertIn("atendida por 11 linhas", texto)
        self.assertIn("177H-10", texto)
        self.assertIn("8084-10", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_linha_descoberta_pelo_gtfs_nao_depende_do_catalogo_manual(self):
        texto, fontes = circulares.consultar_circulares("177H", None)

        self.assertIn("177H-10", texto)
        self.assertIn("Metrô Santana", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_programacao_gtfs_encontra_bienio_e_proximos_horarios(self):
        agora = datetime(2026, 8, 12, 11, 30, tzinfo=circulares.FUSO_SP)

        resultado = circulares._programacao_gtfs("8084", "Biênio", agora)

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["parada"], "Biênio")
        self.assertEqual(resultado["horarios"], ["11:30", "11:42", "11:54"])

    @patch("uspapo.ferramentas.circulares.requests.Session")
    def test_previsao_resolve_linha_parada_e_horarios(self, criar_sessao):
        sessao = SessaoSPTransFalsa()
        criar_sessao.return_value = sessao

        resultado = circulares._obter_previsao_sptrans("8084", "Biênio", "token-teste")

        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["parada"], "AV. PROF. LUCIANO GUALBERTO")
        self.assertEqual([v["t"] for v in resultado["veiculos"]], ["21:04", "21:18"])
        self.assertEqual([caminho for caminho, _ in sessao.consultas], [
            "Buscar", "Linha"
        ])
        self.assertEqual(sessao.consultas[-1][1], {"codigoLinha": 35812})

    @patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"})
    @patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, produzir: produzir())
    @patch("uspapo.ferramentas.circulares._obter_previsao_sptrans")
    def test_consulta_formata_previsao_em_uma_chamada(self, obter, _cache):
        obter.return_value = {
            "hr": "21:00", "linha": "8084-10", "destino": "METRO BUTANTA",
            "parada": "BIENIO", "endereco": "POLI USP",
            "veiculos": [{"t": "21:04", "a": True}, {"t": "21:18", "a": False}],
        }

        texto, fontes = circulares.consultar_circulares("8084", "Biênio")

        obter.assert_called_once_with("8084", "Biênio", "token-teste")
        self.assertIn("21:04, 21:18", texto)
        self.assertEqual(fontes, [circulares.FONTE_API])

    @patch("uspapo.ferramentas.circulares._programacao_gtfs")
    @patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, produzir: produzir())
    @patch("uspapo.ferramentas.circulares.requests.Session")
    def test_api_sem_previsao_combina_gtfs_com_veiculos(
        self, criar_sessao, _cache, programacao
    ):
        sessao = SessaoSemPrevisaoFalsa()
        criar_sessao.return_value = sessao
        programacao.return_value = {
            "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
            "horarios": ["11:42", "11:54", "12:06"],
        }

        resultado = circulares._obter_previsao_sptrans(
            "8084", "Biênio", "token-teste"
        )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["veiculos_ativos"], 2)
        self.assertEqual(resultado["hr"], "11:30")
        self.assertTrue(any("/Posicao/Linha" in url for url in sessao.consultas))

    @patch.dict("os.environ", {}, clear=True)
    @patch("uspapo.ferramentas.circulares._programacao_gtfs")
    def test_sem_token_informa_que_horario_e_programado(self, programacao):
        programacao.return_value = {
            "tipo": "programacao",
            "linha": "8084-10",
            "parada": "Biênio",
            "horarios": ["11:42", "11:54", "12:06"],
        }

        texto, fontes = circulares.consultar_circulares("8084", "Biênio")

        self.assertIn("11:42, 11:54, 12:06", texto)
        self.assertIn("não estimativas ao vivo", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])


if __name__ == "__main__":
    unittest.main()
