"""Testes da ferramenta de transporte: despacho, prosa e schema.

O cálculo é testado em ``test_gtfs_sptrans.py`` e a API em ``test_olhovivo.py``.
Aqui o que se protege é o contrato com o modelo e com o aluno: qual dos quatro
modos de consulta responde cada combinação de argumentos, o que o texto pode e
não pode dizer, e que argumento malformado vira resposta em vez de exceção.

Rodar: python -m unittest backend.uspapo.ferramentas.test_circulares -v,
com PYTHONPATH=backend.
"""

import unittest
from datetime import datetime, time, timedelta
from unittest.mock import patch

from uspapo import gtfs_sptrans
from uspapo.ferramentas import Registro, circulares

FUSO = gtfs_sptrans.FUSO_SP


def _agora_dia_util() -> datetime:
    gerado = datetime.fromisoformat(
        gtfs_sptrans.catalogo()["gerado_em"].replace("Z", "+00:00")
    ).astimezone(FUSO)
    dia = gerado.date()
    while dia.weekday() >= 5:
        dia += timedelta(days=1)
    return datetime.combine(dia, time(11, 30), tzinfo=FUSO)


def _plano_fixo(agora: datetime):
    """Congela o instante do planejador sem congelar o resto do módulo."""
    planejar = gtfs_sptrans.planejar_trajeto
    return patch(
        "uspapo.gtfs_sptrans.planejar_trajeto",
        side_effect=lambda origem, destino, quando=None: planejar(
            origem, destino, agora
        ),
    )


class TestSemToken(unittest.TestCase):
    def setUp(self):
        # A máquina do desenvolvedor pode ter o token no .env. Teste unitário
        # nunca deve fazer chamada de rede nem depender desse segredo.
        self._sem_token = patch.dict("os.environ", {"SPTRANS_TOKEN": ""})
        self._sem_token.start()

    def tearDown(self):
        self._sem_token.stop()


class TestDespacho(TestSemToken):
    def test_sem_argumentos_lista_o_recorte_e_declara_o_corte(self):
        texto, fontes = circulares.consultar_circulares()

        self.assertIn("O recorte GTFS atual contém", texto)
        self.assertIn("Recorte GTFS oficial gerado em", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])
        itens = [linha for linha in texto.splitlines() if linha.startswith("- ")]
        self.assertLessEqual(len(itens), circulares.MAX_LINHAS_LISTA)
        self.assertIn("no total; listei as", texto)

    def test_so_a_linha_devolve_o_itinerario(self):
        texto, fontes = circulares.consultar_circulares("177H")

        self.assertIn("177H-10", texto)
        self.assertIn("Metrô Santana", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_so_o_ponto_faz_a_consulta_reversa(self):
        texto, fontes = circulares.consultar_circulares(None, "Biênio")

        linhas = gtfs_sptrans.linhas_por_ponto("Biênio")["linhas"]
        self.assertIn(f"atendida por {len(linhas)} linhas", texto)
        self.assertIn("8084-10", texto)
        # O total é repetido depois da lista: é a defesa contra o modelo
        # resumir a resposta pré-consultada e perder a contagem.
        self.assertIn(
            f"Total oficial cadastrado para essa parada: {len(linhas)} linhas",
            texto,
        )
        self.assertIn("Recorte GTFS oficial gerado em", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_linha_e_ponto_respondem_a_chegada(self):
        with patch("uspapo.gtfs_sptrans.programacao", return_value={
            "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
            "horarios": ["11:42", "11:54", "12:06"],
        }):
            resposta = circulares.consultar_circulares(
                "8084", "Biênio", _pergunta="Quando vai passar o 8084 no Biênio?"
            )
        texto, fontes = resposta

        self.assertIn("11:42, 11:54, 12:06", texto)
        self.assertIn("estimativa baseada na programação", texto)
        self.assertNotIn("SPTRANS_TOKEN", texto)
        self.assertNotIn("GTFS", texto)
        self.assertEqual(resposta.dados_publicos["status_api"], "nao_consultada")
        self.assertEqual(
            resposta.dados_publicos["sentidos"][0]["base_previsao"],
            "horario_programado",
        )
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_origem_e_destino_respondem_ao_trajeto(self):
        with _plano_fixo(_agora_dia_util()):
            resposta = circulares.consultar_circulares(
                origem="p1", destino_ou_ponto="bienio"
            )

        self.assertIn("Saindo do **P1**", resposta.texto)
        self.assertIn("**8084-10, sentido", resposta.texto)
        self.assertEqual(resposta.dados_publicos["tipo"], "trajeto_onibus")

    def test_erro_da_fonte_vira_prosa_dirigida_ao_modelo(self):
        texto, fontes = circulares.consultar_circulares("1234", "Biênio")

        self.assertIn("NÃO conclua que a linha não existe", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])


class TestHigieneDosArgumentos(TestSemToken):
    """O modelo erra a caixa, o acento e o tipo do argumento em qualquer chamada."""

    def test_lista_no_lugar_de_texto_nao_levanta(self):
        with _plano_fixo(_agora_dia_util()):
            resposta = circulares.consultar_circulares(
                origem=["p1"], destino_ou_ponto=["bienio"]
            )

        self.assertIn("Saindo do **P1**", resposta.texto)

    def test_numero_no_lugar_de_texto_e_aceito(self):
        with patch("uspapo.gtfs_sptrans.programacao") as programacao:
            programacao.return_value = {
                "tipo": "programacao", "linha": "8084-10",
                "parada": "Biênio", "horarios": ["11:42"],
            }
            circulares.consultar_circulares(linha=8084, destino_ou_ponto="Biênio")

        programacao.assert_called_once_with("8084", "Biênio")

    def test_detalhes_como_string_falsa_nao_liga_a_explicacao(self):
        programacao = {
            "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
            "horarios": ["11:42", "11:54", "12:06"],
        }
        with patch("uspapo.gtfs_sptrans.programacao", return_value=programacao):
            desligado = circulares.consultar_circulares(
                "8084", "Biênio", detalhes="false"
            )
            ligado = circulares.consultar_circulares(
                "8084", "Biênio", detalhes="true"
            )

        self.assertFalse(desligado.dados_publicos["facetas"]["explicacao"])
        self.assertTrue(ligado.dados_publicos["facetas"]["explicacao"])
        self.assertLess(len(desligado.texto), len(ligado.texto))

    def test_argumentos_vazios_caem_na_listagem_do_recorte(self):
        texto, _fontes = circulares.consultar_circulares(
            linha="", destino_ou_ponto="", origem=""
        )

        self.assertIn("O recorte GTFS atual contém", texto)


class TestTrajetoAPe(TestSemToken):
    def test_caminhada_passa_pelo_mesmo_contrato_do_onibus(self):
        domingo = datetime(2026, 8, 16, 14, 0, tzinfo=FUSO)
        with _plano_fixo(domingo):
            resposta = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="bienio",
                _pergunta="quais as opções de ônibus do metrô até o Biênio?",
            )

        vista = resposta.dados_publicos
        self.assertEqual(vista["tipo"], "trajeto_a_pe")
        # Sem fatos obrigatórios, o naturalizador podia devolver uma resposta
        # simpática que não dizia quantos minutos eram.
        self.assertEqual(vista["fatos_obrigatorios"], ["Biênio"])
        self.assertEqual(
            vista["numeros_obrigatorios"], [vista["melhor_opcao"]["tempo_total_min"]]
        )
        self.assertEqual(vista["origem"]["nome"], "Metrô Butantã")
        self.assertIn("ir a pé", resposta.texto)

    def test_domingo_nao_oferece_onibus_de_dez_horas(self):
        domingo = datetime(2026, 8, 16, 14, 0, tzinfo=FUSO)
        with _plano_fixo(domingo):
            resposta = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="bienio",
                _pergunta="quais as opções de ônibus do metrô até o Biênio?",
            )

        self.assertIn("não têm passagem programada", resposta.texto)
        self.assertNotIn("alternativas", resposta.dados_publicos)
        self.assertNotIn("8084-10", resposta.texto)


class TestNomesEFontes(TestSemToken):
    def test_texto_do_aluno_nunca_vira_nome_de_parada(self):
        resposta = circulares.consultar_circulares("8082", "metro butanta")

        self.assertIn("**Terminal Metrô Butantã**", resposta.texto)
        self.assertNotIn("metro butanta", resposta.texto)
        self.assertEqual(resposta.dados_publicos["parada"], "Terminal Metrô Butantã")

    def test_trajeto_interno_nao_menciona_o_terminal(self):
        agora = _agora_dia_util().replace(hour=7, minute=10)
        with _plano_fixo(agora):
            resposta = circulares.consultar_circulares(
                origem="restaurante_central", destino_ou_ponto="bienio"
            )

        self.assertIn("Saindo do **Central**", resposta.texto)
        self.assertIn("**8084-10, sentido", resposta.texto)
        self.assertIn("**CrUSP II**", resposta.texto)
        self.assertNotIn("Terminal Metrô Butantã", resposta.texto)

    def test_url_nunca_aparece_no_texto(self):
        chamadas = (
            {},
            {"linha": "177H"},
            {"destino_ou_ponto": "Biênio"},
            {"origem": "p1", "destino_ou_ponto": "bienio"},
        )
        for argumentos in chamadas:
            with self.subTest(**argumentos):
                resposta = circulares.consultar_circulares(**argumentos)
                texto, fontes = resposta
                self.assertNotIn("http", texto)
                self.assertTrue(fontes)


class TestComToken(unittest.TestCase):
    @patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"})
    @patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, p: p())
    @patch("uspapo.olhovivo.previsao_de_chegada")
    def test_previsao_ao_vivo_em_uma_unica_chamada(self, obter, _cache):
        obter.return_value = {
            "tipo": "previsao", "hr": "21:00", "linha": "8084-10",
            "destino": "METRO BUTANTA", "parada": "BIENIO", "endereco": "POLI USP",
            "veiculos": [{"t": "21:04", "a": True}, {"t": "21:18", "a": False}],
        }

        resposta = circulares.consultar_circulares(
            "8084", "Biênio", _pergunta="Quando chega o próximo 8084 no Biênio?"
        )
        texto, fontes = resposta

        obter.assert_called_once_with("8084", "Biênio", "token-teste")
        self.assertIn("21:04, 21:18", texto)
        self.assertEqual(resposta.dados_publicos["status_api"], "eta_disponivel")
        self.assertEqual(
            resposta.dados_publicos["sentidos"][0]["base_previsao"], "eta_ao_vivo"
        )
        self.assertEqual(fontes, [circulares.FONTE_API])

    @patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"})
    @patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, p: p())
    @patch("uspapo.olhovivo.previsao_de_chegada")
    def test_eta_ao_vivo_recalcula_o_total_do_trajeto(self, obter, _cache):
        agora = datetime(2026, 8, 14, 12, 4, tzinfo=FUSO)
        obter.return_value = {
            "tipo": "previsao", "hr": "12:04", "linha": "8082-10",
            "parada": "Terminal Metrô Butantã", "veiculos": [{"t": "12:10"}],
        }
        with (
            _plano_fixo(agora),
            patch("uspapo.olhovivo.instante_referencia", return_value=agora),
        ):
            texto, fontes = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="mecanica",
                _pergunta="Quanto tempo demora agora do metrô até a Mecânica?",
            )

        self.assertIn("chegada prevista para **12:10**", texto)
        self.assertIn("23 minutos no total", texto)
        self.assertNotIn("25 minutos", texto)
        self.assertIn(circulares.FONTE_API, fontes)

    @patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"})
    @patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, p: p())
    @patch("uspapo.olhovivo.previsao_de_chegada")
    def test_api_que_caiu_para_a_programacao_nao_vira_fonte(self, obter, _cache):
        """Creditar a API depois do fallback mandava o aluno à página errada."""
        agora = datetime(2026, 8, 14, 12, 4, tzinfo=FUSO)
        obter.return_value = {
            "tipo": "programacao", "linha": "8082-10",
            "parada": "Terminal Metrô Butantã", "horarios": [],
            "aviso_api": "A API Olho Vivo não respondeu agora.",
        }
        with _plano_fixo(agora):
            _texto, fontes = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="mecanica",
                _pergunta="Quando passa o próximo ônibus do metrô até a Mecânica?",
            )

        self.assertNotIn(circulares.FONTE_API, fontes)
        self.assertIn(circulares.FONTE_GTFS, fontes)


class TestSchema(unittest.TestCase):
    def test_registro_expoe_o_schema_da_ferramenta(self):
        registro = Registro()
        circulares.registrar(registro)

        self.assertIn("consultar_circulares", registro.nomes)
        schema = registro.schemas[0]["function"]
        # Nenhum argumento é obrigatório, mas a chave existe: sem ela, alguns
        # provedores recusam a definição da ferramenta.
        self.assertEqual(schema["parameters"]["required"], [])
        self.assertEqual(
            sorted(schema["parameters"]["properties"]),
            ["destino_ou_ponto", "detalhes", "linha", "origem"],
        )
        self.assertIn("trajeto DIRETO", schema["description"])
        self.assertIn("NÃO é previsão de chegada", schema["description"])


if __name__ == "__main__":
    unittest.main()
