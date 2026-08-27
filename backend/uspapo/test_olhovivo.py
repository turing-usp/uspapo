"""Testes do cliente da API Olho Vivo.

O que se protege aqui não é o formato do JSON da SPTrans: é a promessa de que
nenhuma falha da API vira erro para o aluno, e de que um ETA do sentido errado
nunca é apresentado como se fosse o certo. As sessões falsas devolvem recortes
das respostas reais da API (agosto de 2026), incluindo os casos patológicos:
previsão vazia dentro da USP e linha só encontrada no sentido oposto.

Rodar: python -m unittest backend.uspapo.test_olhovivo -v, com PYTHONPATH=backend.
"""

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from uspapo import olhovivo
from uspapo.gtfs_sptrans import FUSO_SP


class SessaoFalsa:
    """Base com o protocolo de context manager que o cliente usa."""

    def __init__(self):
        self.consultas = []

    def __enter__(self):
        return self

    def __exit__(self, *_excecao):
        return False

    def post(self, url, **kwargs):
        resposta = Mock(status_code=200)
        resposta.json.return_value = True
        return resposta


class SessaoComPrevisao(SessaoFalsa):
    def get(self, url, params=None, **kwargs):
        caminho = url.rsplit("/", 1)[-1]
        self.consultas.append((caminho, params))
        resposta = Mock()
        resposta.raise_for_status.return_value = None
        if caminho == "Buscar":
            resposta.json.return_value = [
                {"cl": 35812, "lt": "8084", "tl": 10, "sl": 1,
                 "tp": "CIDADE UNIVERSITARIA", "ts": "METRO BUTANTA"}
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


class SessaoSemPrevisao(SessaoFalsa):
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
                "hr": "11:30", "vs": [{"p": "1"}, {"p": "2"}]
            }
        else:
            raise AssertionError(f"Endpoint inesperado: {url}")
        return resposta


class SessaoDe8082(SessaoFalsa):
    """A API só conhece a 8082 no sentido Cidade Universitária."""

    def get(self, url, params=None, **kwargs):
        caminho = url.rsplit("/", 1)[-1]
        self.consultas.append((caminho, params))
        resposta = Mock()
        resposta.raise_for_status.return_value = None
        if caminho == "Buscar":
            resposta.json.return_value = [
                {"cl": 1234, "lt": "8082", "tl": 10, "sl": 1,
                 "tp": "CID. UNIVERSITARIA", "ts": "METRO BUTANTA"}
            ]
        else:
            raise AssertionError(f"Endpoint inesperado: {url}")
        return resposta


class SessaoQueExplode(SessaoFalsa):
    def __init__(self):
        super().__init__()
        self.fechada = False

    def __exit__(self, *_excecao):
        self.fechada = True
        return False

    def get(self, url, params=None, **kwargs):
        raise olhovivo.requests.RequestException("timeout simulado")


def _sem_cache():
    return patch(
        "uspapo.olhovivo.cache", side_effect=lambda _chave, _ttl, produzir: produzir()
    )


class TestPrevisaoDeChegada(unittest.TestCase):
    def test_resolve_linha_parada_e_horarios(self):
        sessao = SessaoComPrevisao()
        with _sem_cache(), patch(
            "uspapo.olhovivo.requests.Session", return_value=sessao
        ):
            resultado = olhovivo.previsao_de_chegada("8084", "Biênio", "token-teste")

        self.assertEqual(resultado["tipo"], "previsao")
        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["destino"], "CIDADE UNIVERSITARIA")
        self.assertEqual(resultado["parada"], "AV. PROF. LUCIANO GUALBERTO")
        self.assertEqual(
            [veiculo["t"] for veiculo in resultado["veiculos"]], ["21:04", "21:18"]
        )
        self.assertEqual(
            [caminho for caminho, _ in sessao.consultas], ["Buscar", "Linha"]
        )
        self.assertEqual(sessao.consultas[-1][1], {"codigoLinha": 35812})

    def test_nunca_cai_no_sentido_oposto(self):
        """Pedimos o sentido Metrô Butantã; a API só publica o oposto."""
        sessao = SessaoDe8082()
        with _sem_cache(), patch(
            "uspapo.olhovivo.requests.Session", return_value=sessao
        ):
            resultado = olhovivo.previsao_de_chegada(
                "8082", "Terminal Metrô Butantã", "token-teste", "Metrô Butantã"
            )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["destino"], "Metrô Butantã")
        self.assertIn("nenhum ETA do sentido oposto", resultado["aviso_api"])
        # Nem chegou a pedir a previsão: o sentido já não batia.
        self.assertEqual(
            [caminho for caminho, _parametros in sessao.consultas], ["Buscar"]
        )

    def test_api_sem_previsao_combina_gtfs_com_veiculos_em_circulacao(self):
        sessao = SessaoSemPrevisao()
        with (
            _sem_cache(),
            patch("uspapo.olhovivo.requests.Session", return_value=sessao),
            patch("uspapo.gtfs_sptrans.programacao", return_value={
                "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
                "horarios": ["11:42", "11:54", "12:06"],
            }),
        ):
            resultado = olhovivo.previsao_de_chegada(
                "8084", "Biênio", "token-teste"
            )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["veiculos_ativos"], 2)
        self.assertEqual(resultado["hr"], "11:30")
        self.assertTrue(any("/Posicao/Linha" in url for url in sessao.consultas))

    def test_autenticacao_falha_vira_programacao_com_aviso(self):
        sessao = SessaoComPrevisao()
        sessao.post = lambda url, **kwargs: Mock(status_code=401)
        with _sem_cache(), patch(
            "uspapo.olhovivo.requests.Session", return_value=sessao
        ):
            resultado = olhovivo.previsao_de_chegada("8084", "Biênio", "token-ruim")

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertIn("autenticação", resultado["aviso_api"])
        self.assertEqual(sessao.consultas, [])

    def test_api_fora_do_ar_vira_programacao_e_nao_excecao(self):
        with _sem_cache(), patch(
            "uspapo.olhovivo.requests.Session", return_value=SessaoQueExplode()
        ):
            resultado = olhovivo.previsao_de_chegada("8084", "Biênio", "token-teste")

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertIn("não respondeu", resultado["aviso_api"])

    def test_a_sessao_e_fechada_mesmo_com_falha(self):
        sessao = SessaoQueExplode()
        with _sem_cache(), patch(
            "uspapo.olhovivo.requests.Session", return_value=sessao
        ):
            olhovivo.previsao_de_chegada("8084", "Biênio", "token-teste")

        self.assertTrue(sessao.fechada)


class TestEsperaAoVivo(unittest.TestCase):
    def test_eta_vira_espera_depois_da_caminhada(self):
        referencia = datetime(2026, 8, 14, 12, 4, tzinfo=FUSO_SP)
        previsao = {
            "tipo": "previsao",
            "hr": "12:04",
            "veiculos": [{"t": "12:03"}, {"t": "12:10"}],
        }
        with patch(
            "uspapo.olhovivo.instante_referencia", return_value=referencia
        ):
            espera = olhovivo.espera_ao_vivo(previsao, 46.24)

        # O ônibus das 12:03 passa antes de o aluno alcançar o ponto.
        self.assertEqual(espera.base, "eta_ao_vivo")
        self.assertEqual(espera.eta, "12:10")
        self.assertAlmostEqual(espera.esperada_s, 313.76, places=2)

    def test_programacao_nao_vira_eta(self):
        self.assertIsNone(
            olhovivo.espera_ao_vivo({"tipo": "programacao", "horarios": []}, 0)
        )

    def test_sem_onibus_alcancavel_nao_ha_estimativa(self):
        referencia = datetime(2026, 8, 14, 12, 4, tzinfo=FUSO_SP)
        with patch(
            "uspapo.olhovivo.instante_referencia", return_value=referencia
        ):
            espera = olhovivo.espera_ao_vivo(
                {"tipo": "previsao", "hr": "12:04", "veiculos": [{"t": "12:05"}]},
                caminhada_origem_s=600,
            )

        self.assertIsNone(espera)


class TestParadas(unittest.TestCase):
    def test_destino_respeita_o_sentido_da_api(self):
        linha = {"tp": "TERMINAL PRINCIPAL", "ts": "TERMINAL SECUNDARIO"}
        self.assertEqual(
            olhovivo.destino_da_linha({**linha, "sl": 1}), "TERMINAL PRINCIPAL"
        )
        self.assertEqual(
            olhovivo.destino_da_linha({**linha, "sl": 2}), "TERMINAL SECUNDARIO"
        )

    def test_stop_id_do_plano_tem_prioridade(self):
        paradas = [
            {"cp": 1, "np": "Reitoria", "ed": "lado oposto"},
            {"cp": 120010355, "np": "Reitoria", "ed": "embarque correto"},
        ]

        resultado = olhovivo.ordenar_paradas(paradas, "Reitoria", "120010355")

        self.assertEqual([parada["cp"] for parada in resultado], [120010355])

    def test_parada_longe_demais_nao_e_aceita_por_proximidade(self):
        # A 400 m ao sul do Biênio já não é a parada do Biênio.
        paradas = [{"cp": 9, "np": "SEM RELACAO", "ed": "", "py": -23.60, "px": -46.70}]

        self.assertEqual(olhovivo.ordenar_paradas(paradas, "Biênio"), [])


if __name__ == "__main__":
    unittest.main()
