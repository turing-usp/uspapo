import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import Mock, patch

from uspapo.ferramentas import circulares
from uspapo.locais_usp import CATALOGO_LOCAIS, coordenada_local


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
                 "tp": "CIDADE UNIVERSITARIA", "ts": "METRO BUTANTA"}
            ]
        elif caminho == "Linha":
            resposta.json.return_value = {
                "hr": "21:00",
                "ps": [
                    {"cp": 120010357, "np": "Biênio", "ed": "POLI USP",
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
                 "tp": "METRO BUTANTA", "ts": "CIDADE UNIVERSITARIA"}
            ]
        elif "/Previsao/Linha" in url:
            resposta.json.return_value = {"hr": "11:30", "ps": []}
        elif "/Posicao/Linha" in url:
            resposta.json.return_value = {
                "hr": "11:30", "vs": [{"p": "1"}, {"p": "2"}],
            }
        else:
            raise AssertionError(f"Endpoint inesperado: {url}")
        return resposta


class SessaoChegadasControlada:
    """Fixture mínima do Olho Vivo com cp, sentido e campos operacionais."""

    def __init__(self, linhas, previsoes, posicoes=None):
        self.linhas = linhas
        self.previsoes = previsoes
        self.posicoes = posicoes or {}
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
            resposta.json.return_value = self.linhas
        elif "/Previsao/Linha" in url:
            resposta.json.return_value = self.previsoes.get(
                params["codigoLinha"], {"hr": "10:00", "ps": []}
            )
        elif "Posicao/Linha" in url:
            resposta.json.return_value = self.posicoes.get(
                params["codigoLinha"], {"hr": "10:00", "vs": []}
            )
        else:
            raise AssertionError(f"Endpoint inesperado: {url}")
        return resposta

class TestCirculares(unittest.TestCase):
    def setUp(self):
        # A máquina do desenvolvedor pode ter o token no .env. Teste unitário
        # nunca deve fazer chamada de rede nem depender desse segredo.
        self._sem_token = patch.dict("os.environ", {"SPTRANS_TOKEN": ""})
        self._sem_token.start()

    def tearDown(self):
        self._sem_token.stop()

    @staticmethod
    def _agora_dia_util() -> datetime:
        gerado = datetime.fromisoformat(
            circulares._catalogo_gtfs()["gerado_em"].replace("Z", "+00:00")
        ).astimezone(circulares.FUSO_SP)
        dia = gerado.date()
        while dia.weekday() >= 5:
            dia += timedelta(days=1)
        return datetime.combine(dia, time(11, 30), tzinfo=circulares.FUSO_SP)

    def test_planejador_compara_origem_destino_e_sentido(self):
        agora = self._agora_dia_util()
        casos = {
            ("p1", "bienio"): "8084-10",
            ("metro_butanta", "mecanica"): "8082-10",
            # A grade por frequência agora usa slots ancorados, logo outra
            # linha direta pode vencer o ranking sem mudar o sentido/ordem.
            ("reitoria", "bienio"): "7181-10",
        }

        for (origem, destino), linha_esperada in casos.items():
            with self.subTest(origem=origem, destino=destino):
                plano = circulares._planejar_trajeto_gtfs(origem, destino, agora)
                self.assertEqual(plano["melhor"]["linha"], linha_esperada)
                self.assertGreater(plano["melhor"]["viagem_min"], 0)
                self.assertLessEqual(
                    plano["melhor"]["caminhada_origem_m"],
                    circulares.RAIO_ACESSO_M,
                )
                self.assertLessEqual(
                    plano["melhor"]["caminhada_destino_m"],
                    circulares.RAIO_ACESSO_M,
                )

    def test_consulta_reversa_lista_todas_as_linhas_do_bienio(self):
        resultado = circulares._linhas_por_ponto_gtfs("Biênio")

        linhas = {item["linha"] for item in resultado["linhas"]}
        self.assertIn("8084-10", linhas)
        self.assertNotIn("8032-10", linhas)

        texto, fontes = circulares.consultar_circulares(None, "Biênio")
        self.assertIn(f"atendida por {len(linhas)} linhas", texto)
        self.assertIn("8084-10", texto)
        self.assertIn("Recorte GTFS oficial gerado em", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_linha_descoberta_pelo_gtfs_nao_depende_do_catalogo_manual(self):
        texto, fontes = circulares.consultar_circulares("177H", None)

        self.assertIn("177H-10", texto)
        self.assertIn("Metrô Santana", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_programacao_gtfs_encontra_bienio_e_proximos_horarios(self):
        agora = self._agora_dia_util()

        resultado = circulares._programacao_gtfs("8084", "Biênio", agora)

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["parada"], "Biênio")
        self.assertEqual(resultado["parada_id"], "120010357")
        # O feed marca as frequências da 8084 com exact_times=0: os múltiplos
        # do headway não são partidas cravadas e não podem virar "previsões".
        self.assertEqual(resultado["horarios"], [])
        self.assertEqual(
            [item["horario"] for item in resultado["estimativas"]],
            ["11:42", "11:54", "12:06"],
        )
        self.assertTrue(all(
            item["source"] == "scheduled_estimate"
            for item in resultado["estimativas"]
        ))
        self.assertTrue(resultado["faixas"])
        self.assertEqual(resultado["faixas"][0]["intervalo_min"], 12)
        self.assertTrue(resultado["faixas"][0]["ativa_agora"])
        self.assertEqual(resultado["faixas"][0]["espera_tipica_min"], 6)
        self.assertEqual(resultado["faixas"][0]["espera_maxima_min"], 12)
        self.assertEqual(
            resultado["faixas"][0]["proxima_referencia_texto"], "11:36"
        )

    def test_resposta_exibe_janela_programada_sem_fingir_eta_ao_vivo(self):
        agora = self._agora_dia_util()
        with patch(
            "uspapo.ferramentas.circulares.datetime"
        ) as datetime_mock:
            datetime_mock.now.return_value = agora
            datetime_mock.fromisoformat.side_effect = datetime.fromisoformat
            datetime_mock.combine.side_effect = datetime.combine
            texto, fontes = circulares.consultar_circulares("8084", "Biênio")

        self.assertIn("passagens estimadas", texto)
        self.assertIn("**~11:42, ~11:54, ~12:06**", texto)
        self.assertIn("slots estimados", texto)
        self.assertIn("12 minutos", texto)
        self.assertIn("não confirmações em tempo real", texto)
        self.assertNotIn("GTFS", texto)
        self.assertNotIn("Faixas de operação", texto)
        self.assertNotIn("Próximos horários programados: 11:36", texto)
        self.assertEqual(fontes, [circulares.FONTE_GTFS])

    def test_programacao_de_rota_respeita_o_sentido_escolhido(self):
        resultado = circulares._programacao_gtfs(
            "8082",
            "metro_butanta",
            self._agora_dia_util(),
            "Cid. Universitária",
        )

        self.assertEqual(resultado["linha"], "8082-10")
        self.assertEqual(resultado["destino"], "Cid. Universitária")
        self.assertEqual(resultado["parada"], "Terminal Metrô Butantã")

    def test_programacao_sem_sentido_nao_mistura_headsigns(self):
        resultado = circulares._programacao_gtfs(
            "177H", "Terminal USP", self._agora_dia_util()
        )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertGreaterEqual(len(resultado["sentidos"]), 2)
        destinos = {item["destino"] for item in resultado["sentidos"]}
        self.assertIn("Cid. Universitária", destinos)
        self.assertIn("Metrô Santana", destinos)
        for item in resultado["sentidos"]:
            self.assertNotIn("sentidos", item)

    def test_exact_times_um_e_o_unico_caso_que_gera_horarios_cravados(self):
        agora = datetime(2026, 8, 14, 11, 30, tzinfo=circulares.FUSO_SP)
        catalogo = {
            "calendarios": {
                "util": {
                    "dias": [1, 1, 1, 1, 1, 0, 0],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {},
            "linhas": {
                "9999": [{
                    "linha": "9999-10",
                    "nome": "Linha de teste",
                    "viagens": [{
                        "servico": "util",
                        "destino": "Destino de teste",
                        "frequencias": [{
                            "inicio": 11 * 3600 + 30 * 60,
                            "fim": 12 * 3600,
                            "intervalo": 600,
                            "exact_times": 1,
                        }],
                        "paradas": [{
                            "id": "bienio-teste",
                            "nome": "Biênio",
                            "latitude": -23.557818,
                            "longitude": -46.732322,
                            "sequencia": 1,
                            "deslocamento": 0,
                            "horario": 11 * 3600 + 30 * 60,
                        }],
                    }],
                }],
            },
        }

        with patch(
            "uspapo.ferramentas.circulares._catalogo_gtfs",
            return_value=catalogo,
        ):
            resultado = circulares._programacao_gtfs("9999", "Biênio", agora)

        self.assertEqual(resultado["horarios"], ["11:30", "11:40", "11:50"])
        self.assertNotIn("faixas", resultado)

    def test_exact_times_zero_gera_slots_estimados_ancorados_na_frequencia(self):
        agora = datetime(2026, 8, 14, 12, 32, tzinfo=circulares.FUSO_SP)
        catalogo = {
            "calendarios": {"S": {
                "dias": [1] * 7, "inicio": "20260101", "fim": "20261231",
            }},
            "excecoes_calendario": {},
            "linhas": {"F": [{
                "linha": "F-10", "viagens": [{
                    "servico": "S", "destino": "Destino",
                    "frequencias": [{
                        "inicio": 12 * 3600, "fim": 15 * 3600,
                        "intervalo": 15 * 60, "exact_times": 0,
                    }],
                    "paradas": [{
                        "id": "p", "nome": "Ponto", "sequencia": 1,
                        "deslocamento": 0, "horario": 12 * 3600,
                        "latitude": -23.55, "longitude": -46.73,
                    }],
                }],
            }]},
        }
        with patch.object(circulares, "_catalogo_gtfs", return_value=catalogo):
            resultado = circulares._programacao_gtfs("F", "Ponto", agora)

        self.assertEqual(resultado["horarios"], [])
        self.assertEqual(
            [item["horario"] for item in resultado["estimativas"]],
            ["12:45", "13:00", "13:15"],
        )
        self.assertTrue(all(
            item["source"] == "scheduled_estimate"
            and item["confidence"] == "scheduled"
            and item["intervalo_min"] == 15
            for item in resultado["estimativas"]
        ))

    def test_grade_utilizavel_mas_menos_confiavel_permanece_disponivel(self):
        agora = datetime(2026, 8, 14, 12, 32, tzinfo=circulares.FUSO_SP)
        catalogo = {
            "calendarios": {"S": {
                "dias": [1] * 7, "inicio": "20260101", "fim": "20261231",
            }},
            "excecoes_calendario": {},
            "linhas": {"F": [{
                "linha": "F-10", "viagens": [{
                    "servico": "S", "destino": "Destino",
                    "frequencias": [{
                        "inicio": 12 * 3600, "fim": 15 * 3600,
                        "intervalo": 15 * 60, "exact_times": 0,
                    }],
                    "paradas": [{
                        "id": "p", "nome": "Ponto", "sequencia": 1,
                        "deslocamento": 0, "horario": 12 * 3600,
                        "latitude": -23.55, "longitude": -46.73,
                    }],
                }],
            }]},
        }
        with (
            patch.object(circulares, "_catalogo_gtfs", return_value=catalogo),
            patch.object(circulares, "horario_gtfs_confiavel", return_value=False),
        ):
            resultado = circulares._programacao_gtfs("F", "Ponto", agora)

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertTrue(resultado["programacao_incompleta"])
        self.assertEqual(
            resultado["estimativas"][0]["confidence"], "scheduled_uncertain",
        )

    def test_fallback_gtfs_com_estimativas_nao_depende_de_bloco_ao_vivo(self):
        resultado = circulares._resultado_chegada_publico(
            {
                "tipo": "programacao",
                "linha": "F-10",
                "parada": "Ponto",
                "horarios": [],
                "estimativas": [{
                    "horario": "12:45",
                    "source": "scheduled_estimate",
                    "confidence": "scheduled",
                    "intervalo_min": 15,
                }],
            },
            api_consultada=False,
            ponto_pedido="Ponto",
        )

        self.assertEqual(
            resultado.sentidos[0].estimativas_programadas[0].horario,
            "12:45",
        )

    def test_ranking_usa_proxima_partida_quando_exact_times_um(self):
        catalogo = {
            "calendarios": {
                "util": {
                    "dias": [1, 1, 1, 1, 1, 0, 0],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {},
        }
        viagem = {
            "servico": "util",
            "frequencias": [{
                "inicio": 11 * 3600 + 30 * 60,
                "fim": 12 * 3600,
                "intervalo": 600,
                "exact_times": 1,
            }],
        }
        parada = {"deslocamento": 0}
        pronto = datetime(2026, 8, 14, 11, 33, tzinfo=circulares.FUSO_SP)

        espera, intervalo = circulares._espera_media_gtfs(
            catalogo, viagem, parada, pronto
        )

        self.assertEqual(espera, 7)
        self.assertIsNone(intervalo)

    def test_viagem_apos_24h_pertence_ao_dia_de_servico_anterior(self):
        agora = datetime(2026, 8, 15, 0, 20, tzinfo=circulares.FUSO_SP)
        catalogo = {
            "calendarios": {
                "util": {
                    "dias": [1, 1, 1, 1, 1, 0, 0],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {},
            "linhas": {
                "9999": [{
                    "linha": "9999-10",
                    "nome": "Madrugada de teste",
                    "viagens": [{
                        "servico": "util",
                        "destino": "Destino de teste",
                        "frequencias": [{
                            "inicio": 24 * 3600 + 30 * 60,
                            "fim": 25 * 3600,
                            "intervalo": 600,
                            "exact_times": 1,
                        }],
                        "paradas": [{
                            "id": "bienio-madrugada",
                            "nome": "Biênio",
                            "latitude": -23.557818,
                            "longitude": -46.732322,
                            "sequencia": 1,
                            "deslocamento": 0,
                            "horario": 24 * 3600 + 30 * 60,
                        }],
                    }],
                }],
            },
        }

        with patch(
            "uspapo.ferramentas.circulares._catalogo_gtfs",
            return_value=catalogo,
        ):
            resultado = circulares._programacao_gtfs("9999", "Biênio", agora)

        self.assertEqual(resultado["horarios"], ["00:30", "00:40", "00:50"])

        catalogo["linhas"]["9999"][0]["viagens"][0]["frequencias"][0][
            "exact_times"
        ] = 0
        espera, intervalo = circulares._espera_media_gtfs(
            catalogo,
            catalogo["linhas"]["9999"][0]["viagens"][0],
            {"deslocamento": 0},
            datetime(2026, 8, 15, 0, 35, tzinfo=circulares.FUSO_SP),
        )
        self.assertEqual((espera, intervalo), (5, 10))

    def test_calendar_dates_tem_precedencia_sobre_calendario_semanal(self):
        catalogo = {
            "calendarios": {
                "util": {
                    "dias": [1, 1, 1, 1, 1, 0, 0],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {
                "util": {"20260814": 2, "20260815": 1}
            },
        }

        self.assertFalse(
            circulares._servico_ativo(catalogo, "util", date(2026, 8, 14))
        )
        self.assertTrue(
            circulares._servico_ativo(catalogo, "util", date(2026, 8, 15))
        )

    def test_snapshot_gtfs_vencido_e_exposto_na_resposta(self):
        with patch(
            "uspapo.ferramentas.circulares._catalogo_gtfs",
            return_value={"gerado_em": "2026-08-01T12:00:00+00:00"},
        ):
            nota = circulares._nota_atualizacao_gtfs(
                datetime(2026, 8, 10, 12, 0, tzinfo=circulares.timezone.utc)
            )

        self.assertIn("01/08/2026", nota)
        self.assertIn("há 9 dias sem atualização", nota)

    def test_nomes_de_parada_do_catalogo_existem_no_gtfs_oficial(self):
        nomes_gtfs = {
            circulares.normalizar(parada["nome"])
            for rotas in circulares._catalogo_gtfs()["linhas"].values()
            for rota in rotas
            for viagem in rota["viagens"]
            for parada in viagem["paradas"]
        }
        declarados = 0
        for chave, local in CATALOGO_LOCAIS.items():
            for nome in local["nomes_parada"]:
                declarados += 1
                with self.subTest(chave=chave, nome=nome):
                    self.assertIn(circulares.normalizar(nome), nomes_gtfs)
        self.assertGreaterEqual(declarados, 40)

    def test_todas_as_paradas_da_area_oficial_sao_consultaveis(self):
        paradas = circulares._catalogo_gtfs()["paradas_na_area_selecao"]
        self.assertGreaterEqual(len(paradas), 100)
        for stop_id, parada in paradas.items():
            with self.subTest(stop_id=stop_id, nome=parada["nome"]):
                atendimento = circulares._linhas_por_ponto_gtfs(parada["nome"])
                self.assertNotIn("erro", atendimento)
                self.assertTrue(atendimento["linhas"])

    def test_todo_local_canonico_tem_parada_caminhavel_no_gtfs(self):
        paradas = list({
            str(parada["id"]): parada
            for rotas in circulares._catalogo_gtfs()["linhas"].values()
            for rota in rotas
            for viagem in rota["viagens"]
            for parada in viagem["paradas"]
        }.values())
        for chave in CATALOGO_LOCAIS:
            coordenada = coordenada_local(chave)
            menor = min(
                circulares._distancia_parada_gtfs(parada, coordenada)
                for parada in paradas
            )
            with self.subTest(chave=chave, distancia=round(menor)):
                self.assertLessEqual(menor, circulares.RAIO_ACESSO_M)

    def test_area_de_selecao_nao_corta_as_bordas_do_campus(self):
        limites = circulares._catalogo_gtfs()["criterio"][
            "linhas_com_parada_na_area_do_campus"
        ]
        for chave in CATALOGO_LOCAIS:
            if chave == "metro_butanta":  # hub externo, intencionalmente fora
                continue
            latitude, longitude = coordenada_local(chave)
            with self.subTest(chave=chave):
                self.assertLessEqual(limites["latitude_min"], latitude)
                self.assertLessEqual(latitude, limites["latitude_max"])
                self.assertLessEqual(limites["longitude_min"], longitude)
                self.assertLessEqual(longitude, limites["longitude_max"])

    def test_matching_nao_confunde_siglas_com_ruas_fora_da_usp(self):
        agora = self._agora_dia_util()

        programacao_poli = circulares._programacao_gtfs(
            "8084", "Poli", agora
        )
        self.assertNotIn(
            "policia", circulares.normalizar(programacao_poli["parada"])
        )
        self.assertIn(
            "erro",
            circulares._programacao_gtfs("7725", "Metrô Butantã", agora),
        )
        for sigla, falso in (
            ("FAU", "faustolo"),
            ("IP", "ipiranga"),
            ("HU", "hugo"),
        ):
            with self.subTest(sigla=sigla):
                atendimento = circulares._linhas_por_ponto_gtfs(sigla)
                self.assertNotIn(
                    falso, circulares.normalizar(atendimento["parada"])
                )

    def test_central_e_reitoria_ate_bienio_nunca_voltam_ao_metro(self):
        # 07:10 é o horário do feedback reproduzido no print do usuário.
        agora = self._agora_dia_util().replace(hour=7, minute=10)
        for origem in ("restaurante_central", "reitoria"):
            with self.subTest(origem=origem):
                plano = circulares._planejar_trajeto_gtfs(
                    origem, "bienio", agora
                )
                melhor = plano["melhor"]
                self.assertEqual(melhor["modo"], "onibus")
                self.assertEqual(melhor["linha"], "8084-10")
                self.assertEqual(melhor["desembarque"], "Biênio")
                self.assertFalse(melhor["passa_metro_butanta"])
                self.assertLess(
                    melhor["embarque_sequencia"],
                    melhor["desembarque_sequencia"],
                )

        planejar = circulares._planejar_trajeto_gtfs
        with patch(
            "uspapo.ferramentas.circulares._planejar_trajeto_gtfs",
            side_effect=lambda origem, destino: planejar(
                origem, destino, agora
            ),
        ):
            texto, _fontes = circulares.consultar_circulares(
                origem="restaurante_central", destino_ou_ponto="bienio"
            )
        self.assertIn("Saindo do **Central**", texto)
        self.assertIn("**8084-10, sentido", texto)
        self.assertNotIn("Terminal Metrô Butantã", texto)

    def test_matriz_de_todos_os_locais_tem_resultado_e_invariantes(self):
        agora = self._agora_dia_util()
        chaves = list(CATALOGO_LOCAIS)
        pares_testados = 0
        for origem in chaves:
            self.assertIsNotNone(coordenada_local(origem))
            for destino in chaves:
                if origem == destino:
                    continue
                pares_testados += 1
                plano = circulares._planejar_trajeto_gtfs(
                    origem, destino, agora
                )
                with self.subTest(origem=origem, destino=destino):
                    self.assertNotIn("erro", plano)
                    self.assertIn(plano["melhor"]["modo"], {"onibus", "a_pe"})
                    opcoes = [
                        plano["melhor"], *plano.get("alternativas", [])
                    ]
                    self.assertTrue(
                        any(opcao.get("modo") == "onibus" for opcao in opcoes),
                        "o par perdeu toda cobertura direta de ônibus",
                    )
                    for opcao in opcoes:
                        if opcao.get("modo") != "onibus":
                            continue
                        self.assertTrue(opcao["embarque_id"])
                        self.assertTrue(opcao["desembarque_id"])
                        self.assertLess(
                            opcao["embarque_sequencia"],
                            opcao["desembarque_sequencia"],
                        )
                        self.assertLessEqual(
                            opcao["caminhada_origem_m"],
                            circulares.RAIO_ACESSO_M,
                        )
                        self.assertLessEqual(
                            opcao["caminhada_destino_m"],
                            circulares.RAIO_ACESSO_M,
                        )
                        self.assertAlmostEqual(
                            opcao["total_estimado_s"],
                            opcao["caminhada_origem_s"]
                            + opcao["espera_programada_s"]
                            + opcao["viagem_s"]
                            + opcao["caminhada_destino_s"],
                            places=6,
                        )
                    totais_onibus = [
                        opcao["total_estimado_s"]
                        for opcao in opcoes
                        if opcao.get("modo") == "onibus"
                    ]
                    self.assertEqual(totais_onibus, sorted(totais_onibus))
        self.assertEqual(pares_testados, len(chaves) * (len(chaves) - 1))

    def test_metro_mecanica_preserva_componentes_brutos_ate_a_apresentacao(self):
        agora = datetime(2026, 8, 14, 12, 4, tzinfo=circulares.FUSO_SP)

        melhor = circulares._planejar_trajeto_gtfs(
            "metro_butanta", "mecanica", agora
        )["melhor"]

        self.assertEqual(melhor["linha"], "8082-10")
        self.assertEqual(melhor["espera_source"], "scheduled_estimate")
        self.assertAlmostEqual(
            melhor["total_estimado_s"],
            melhor["caminhada_origem_s"] + melhor["espera_programada_s"]
            + melhor["viagem_s"] + melhor["caminhada_destino_s"],
            places=6,
        )

    def test_eta_ao_vivo_vira_espera_depois_da_caminhada(self):
        referencia = datetime(2026, 8, 14, 12, 4, tzinfo=circulares.FUSO_SP)
        previsao = {
            "tipo": "previsao",
            "hr": "12:04",
            "veiculos": [{"t": "12:03"}, {"t": "12:10"}],
        }
        with patch(
            "uspapo.ferramentas.circulares._instante_referencia_sptrans",
            return_value=referencia,
        ):
            espera = circulares._espera_ao_vivo(previsao, 46.24)

        self.assertIsNotNone(espera)
        self.assertEqual(espera.base, "eta_ao_vivo")
        self.assertEqual(espera.eta, "12:10")
        self.assertAlmostEqual(espera.esperada_s, 313.76, places=2)

    def test_eta_ao_vivo_recalcula_o_total_mostrado(self):
        agora = datetime(2026, 8, 14, 12, 4, tzinfo=circulares.FUSO_SP)
        plano = circulares._planejar_trajeto_gtfs(
            "metro_butanta", "mecanica", agora
        )
        previsao = {
            "tipo": "previsao",
            "hr": "12:04",
            "linha": "8082-10",
            "parada": "Terminal Metrô Butantã",
            "veiculos": [{"t": "12:10"}],
        }
        with (
            patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"}),
            patch(
                "uspapo.ferramentas.circulares._planejar_trajeto_gtfs",
                return_value=plano,
            ),
            patch(
                "uspapo.ferramentas.circulares._obter_previsao_sptrans",
                return_value=previsao,
            ),
            patch(
                "uspapo.ferramentas.circulares._instante_referencia_sptrans",
                return_value=agora,
            ),
            patch(
                "uspapo.ferramentas.circulares.cache",
                side_effect=lambda _chave, _ttl, produzir: produzir(),
            ),
        ):
            texto, fontes = circulares.consultar_circulares(
                origem="metro_butanta",
                destino_ou_ponto="mecanica",
                _pergunta="Quanto tempo demora agora do metrô até a Mecânica?",
            )

        self.assertIn("chegada prevista para **12:10**", texto)
        # A consulta agora reavalia as alternativas diretas com o ETA da
        # plataforma/sentido de cada uma; sob este mock, a opção de 21 min
        # supera a primeira opção programada.
        self.assertIn("21 minutos no total", texto)
        self.assertNotIn("25 minutos", texto)
        self.assertIn(circulares.FONTE_API, fontes)

    def test_eta_compativel_reordena_alternativas_diretas(self):
        agora = datetime(2026, 8, 14, 12, 0, tzinfo=circulares.FUSO_SP)
        base = {
            "modo": "onibus", "sentido": "Cidade Universitária",
            "embarque": "Ponto A", "desembarque": "Ponto B",
            "embarque_sequencia": 1, "desembarque_sequencia": 2,
            "caminhada_origem_m": 80, "caminhada_destino_m": 80,
            "caminhada_origem_s": 60, "caminhada_destino_s": 60,
            "viagem_s": 600, "intervalo_programado_s": None,
            "espera_programada_s": 540, "total_estimado_s": 1260,
            "espera_programada_min": 9, "intervalo_programado_min": None,
            "total_estimado_min": 21,
        }
        opcao_a = {**base, "linha": "8000-10", "embarque_id": "a", "desembarque_id": "b"}
        opcao_b = {**base, "linha": "8001-10", "embarque_id": "c", "desembarque_id": "d"}
        plano = {
            "origem": "metro_butanta", "destino": "ime", "melhor": opcao_a,
            "alternativas": [opcao_b],
        }

        def previsao(numero, *_args):
            # A chega tarde; B é alcançável e chega antes. As duas previsões
            # são vinculadas pela chamada ao stop_id/headsign de cada opção.
            return {"tipo": "previsao", "api_consultada": True, "hr": "12:00", "veiculos": [
                {"t": "12:20" if numero == "8000" else "12:06"},
            ]}

        with (
            patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"}),
            patch("uspapo.ferramentas.circulares._planejar_trajeto_gtfs", return_value=plano),
            patch("uspapo.ferramentas.circulares._obter_previsao_sptrans", side_effect=previsao),
            patch("uspapo.ferramentas.circulares._instante_referencia_sptrans", return_value=agora),
            patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, produzir: produzir()),
        ):
            resposta = circulares.consultar_circulares(
                origem="metro_butanta", destino_ou_ponto="ime",
                _pergunta="Qual ônibus pego agora do metrô para o IME?",
            )

        self.assertEqual(resposta.dados_publicos["melhor_opcao"]["linha"], "8001-10")
        self.assertEqual(resposta.dados_publicos["tempo"]["espera"]["source"], "live")

    @patch(
        "uspapo.ferramentas.circulares.cache",
        side_effect=lambda _chave, _ttl, produzir: produzir(),
    )
    @patch("uspapo.ferramentas.circulares.requests.Session")
    def test_previsao_resolve_linha_parada_e_horarios(
        self, criar_sessao, _cache
    ):
        sessao = SessaoSPTransFalsa()
        criar_sessao.return_value = sessao

        instante_api = datetime(
            2026, 8, 20, 21, 0, tzinfo=circulares.FUSO_SP
        )
        with patch(
            "uspapo.ferramentas.circulares._agora_sptrans",
            return_value=instante_api,
        ):
            resultado = circulares._obter_previsao_sptrans(
                "8084", "Biênio", "token-teste"
            )

        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["destino"], "Cid. Universitária")
        self.assertEqual(resultado["parada"], "Biênio")
        self.assertEqual([v["t"] for v in resultado["veiculos"]], ["21:04", "21:18"])
        self.assertEqual([caminho for caminho, _ in sessao.consultas], [
            "Buscar", "Linha"
        ])
        self.assertEqual(sessao.consultas[-1][1], {"codigoLinha": 35812})

    @patch(
        "uspapo.ferramentas.circulares.cache",
        side_effect=lambda _chave, _ttl, produzir: produzir(),
    )
    @patch("uspapo.ferramentas.circulares.requests.Session")
    def test_previsao_nunca_cai_no_sentido_oposto(
        self, criar_sessao, _cache
    ):
        sessao = SessaoSPTransFalsa()
        criar_sessao.return_value = sessao

        resultado = circulares._obter_previsao_sptrans(
            "8084", "Biênio", "token-teste", "SENTIDO INEXISTENTE"
        )

        self.assertEqual(resultado["tipo"], "sentido_incompativel")
        self.assertEqual(resultado["sentido_solicitado"], "SENTIDO INEXISTENTE")
        self.assertEqual(
            [caminho for caminho, _parametros in sessao.consultas],
            [],
        )

    def test_destino_sptrans_respeita_o_sentido_da_api(self):
        linha = {"tp": "TERMINAL PRINCIPAL", "ts": "TERMINAL SECUNDARIO"}
        self.assertEqual(
            circulares._destino_linha_sptrans({**linha, "sl": 1}),
            "TERMINAL PRINCIPAL",
        )
        self.assertEqual(
            circulares._destino_linha_sptrans({**linha, "sl": 2}),
            "TERMINAL SECUNDARIO",
        )

    def test_stop_id_do_plano_tem_prioridade_na_previsao_ao_vivo(self):
        paradas = [
            {"cp": 1, "np": "Reitoria", "ed": "lado oposto"},
            {"cp": 120010355, "np": "Reitoria", "ed": "embarque correto"},
        ]

        resultado = circulares._ordenar_paradas(
            paradas, "Reitoria", "120010355"
        )

        self.assertEqual([parada["cp"] for parada in resultado], [120010355])

    @patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"})
    @patch("uspapo.ferramentas.circulares.cache", side_effect=lambda _c, _t, produzir: produzir())
    @patch("uspapo.ferramentas.circulares._obter_previsao_sptrans")
    def test_consulta_formata_previsao_em_uma_chamada(self, obter, _cache):
        obter.return_value = {
            "hr": "21:00", "linha": "8084-10", "destino": "METRO BUTANTA",
            "parada": "BIENIO", "endereco": "POLI USP",
            "veiculos": [{"t": "21:04", "a": True}, {"t": "21:18", "a": False}],
        }

        resposta = circulares.consultar_circulares(
            "8084",
            "Biênio",
            _pergunta="Quando chega o próximo 8084 no Biênio?",
        )
        texto, fontes = resposta

        obter.assert_called_once_with(
            "8084",
            "Biênio",
            "token-teste",
            datas_permitidas=(
                circulares.datetime.now(circulares.FUSO_SP).date(),
            ),
        )
        self.assertIn("21:04, 21:18", texto)
        self.assertEqual(
            resposta.dados_publicos["status_api"], "eta_disponivel"
        )
        self.assertEqual(
            resposta.dados_publicos["sentidos"][0]["base_previsao"],
            "eta_ao_vivo",
        )
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
            "parada_id": "120010357", "destino": "METRO BUTANTA",
            "horarios": ["11:42", "11:54", "12:06"],
        }

        instante_api = datetime(
            2026, 8, 20, 11, 30, tzinfo=circulares.FUSO_SP
        )
        with patch(
            "uspapo.ferramentas.circulares._agora_sptrans",
            return_value=instante_api,
        ):
            resultado = circulares._obter_previsao_sptrans(
                "8084", "Biênio", "token-teste"
            )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["veiculos_ativos"], 2)
        self.assertEqual(resultado["hr"], "11:30")
        self.assertTrue(any("/Posicao/Linha" in url for url in sessao.consultas))
        self.assertIn("posição GPS", resultado["aviso_api"])
        self.assertNotIn("associação GTFS", resultado["aviso_api"])

    @staticmethod
    def _programacao_ao_vivo(stop_id="gtfs-bienio", destino="TERMINAL A"):
        return {
            "tipo": "programacao",
            "linha": "8084-10",
            "parada": "Biênio",
            "parada_id": stop_id,
            "destino": destino,
            "sentido_gtfs": "0",
            "horarios": ["10:20"],
        }

    def _consultar_chegadas_controladas(self, programacao, linhas, previsoes, posicoes=None):
        sessao = SessaoChegadasControlada(linhas, previsoes, posicoes)
        referencia = datetime(2026, 8, 20, 10, 0, tzinfo=circulares.FUSO_SP)
        with (
            patch("uspapo.ferramentas.circulares.requests.Session", return_value=sessao),
            patch("uspapo.ferramentas.circulares._programacao_gtfs", return_value=programacao),
            patch("uspapo.ferramentas.circulares._instante_referencia_sptrans", return_value=referencia),
            patch("uspapo.ferramentas.circulares._agora_sptrans", return_value=referencia),
            patch(
                "uspapo.ferramentas.circulares.cache",
                side_effect=lambda _c, _t, produzir: produzir(),
            ),
        ):
            resultado = circulares._obter_previsao_sptrans(
                "8084", "Biênio", "token-teste"
            )
        return resultado, sessao

    def test_classificacao_de_confianca_usa_freshness_gps_e_identificador(self):
        referencia = datetime(2026, 8, 20, 10, 0, tzinfo=circulares.FUSO_SP)
        base = {"p": "v1", "t": "10:08", "py": -23.5, "px": -46.7}

        alta = circulares._classificar_confianca_chegada(
            {**base, "ta": "09:59:30"}, "10:00", referencia=referencia,
        )
        media = circulares._classificar_confianca_chegada(
            {**base, "ta": "09:57"}, "10:00", referencia=referencia,
        )
        baixa = circulares._classificar_confianca_chegada(
            {**base, "ta": "09:50"}, "10:00", referencia=referencia,
        )

        self.assertEqual(alta["level"], "high")
        self.assertEqual(media["level"], "medium")
        self.assertEqual(baixa["level"], "low")
        self.assertIn("ta_antigo", baixa["reasons"])

    def test_classificacao_descarta_ta_velho_eta_invalido_e_nao_promove_ta_ausente(self):
        referencia = datetime(2026, 8, 20, 10, 0, tzinfo=circulares.FUSO_SP)
        base = {"p": "v1", "t": "10:08", "py": -23.5, "px": -46.7}
        velho = circulares._classificar_confianca_chegada(
            {**base, "ta": "09:44"}, "10:00", referencia=referencia,
        )
        sem_ta = circulares._classificar_confianca_chegada(
            base, "10:00", referencia=referencia,
        )
        eta_invalido = circulares._classificar_confianca_chegada(
            {**base, "t": "09:40", "ta": "09:59"}, "10:00",
            referencia=referencia,
        )

        self.assertFalse(velho["valid"])
        self.assertIn("ta_antigo_demais", velho["reasons"])
        self.assertEqual(sem_ta["level"], "low")
        self.assertFalse(eta_invalido["valid"])

    def test_tres_etAs_podem_ter_confiancas_distintas_sem_perder_ordenacao(self):
        referencia = datetime(2026, 8, 20, 10, 0, tzinfo=circulares.FUSO_SP)
        veiculos = [
            {"p": "low", "t": "10:09", "ta": "09:52", "py": -23.5, "px": -46.7},
            {"p": "high", "t": "10:05", "ta": "09:59:30", "py": -23.5, "px": -46.7},
            {"p": "medium", "t": "10:07", "ta": "09:57", "py": -23.5, "px": -46.7},
        ]
        with patch(
            "uspapo.ferramentas.circulares._instante_referencia_sptrans",
            return_value=referencia,
        ):
            resultado = circulares._veiculos_ao_vivo_ordenados(veiculos, "10:00")

        self.assertEqual([item["t"] for item in resultado], ["10:05", "10:07", "10:09"])
        self.assertEqual(
            [item["confidence"] for item in resultado],
            ["high", "medium", "low"],
        )

    def test_fallback_gtfs_publica_origem_e_confianca_scheduled(self):
        contrato = circulares._resultado_chegada_publico(
            {
                "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
                "destino": "Terminal A", "horarios": ["10:20", "10:32"],
            },
            api_consultada=False,
            ponto_pedido="Biênio",
        )

        chegadas = contrato.public_view()["sentidos"][0]["chegadas"]
        self.assertEqual(
            [(item["source"], item["confidence"]) for item in chegadas],
            [("scheduled", "scheduled"), ("scheduled", "scheduled")],
        )
        self.assertEqual(
            contrato.como_payload()["sentidos"][0]["programacao"]["chegadas"][0],
            {"horario": "10:20", "source": "scheduled", "confidence": "scheduled"},
        )

    def test_eta_ao_vivo_ordena_deduplica_e_preserva_evidencia_operacional(self):
        linha = {
            "cl": 1, "lt": "8084", "tl": 10, "sl": 1,
            "tp": "TERMINAL A", "ts": "TERMINAL B",
        }
        resultado, _ = self._consultar_chegadas_controladas(
            self._programacao_ao_vivo(), [linha], {
                1: {"hr": "10:00", "ps": [{
                    "cp": "gtfs-bienio", "np": "Biênio", "ed": "Poli",
                    "py": -23.55, "px": -46.72,
                    "vs": [
                        {"p": "4", "t": "10:30", "ta": "10:00", "py": -23.5, "px": -46.7},
                        {"p": "1", "t": "10:10", "ta": "10:00", "py": -23.5, "px": -46.7},
                        {"p": "2", "t": "10:20", "ta": "10:00", "py": -23.5, "px": -46.7},
                        {"p": "3", "t": "10:15", "ta": "10:00", "py": -23.5, "px": -46.7},
                        {"p": "1", "t": "10:10", "ta": "10:00", "py": -23.5, "px": -46.7},
                    ],
                }]},
            },
        )

        self.assertEqual([item["t"] for item in resultado["veiculos"]], [
            "10:10", "10:15", "10:20",
        ])
        operacional = resultado["operacional"]
        self.assertEqual(operacional["parada_gtfs"]["stop_id"], "gtfs-bienio")
        self.assertEqual(operacional["parada_olho_vivo"]["cp"], "gtfs-bienio")
        self.assertEqual(operacional["veiculos"][0]["ta"], "10:00")
        self.assertIn("py", operacional["veiculos"][0])
        self.assertIn("px", operacional["veiculos"][0])
        contrato = circulares._resultado_chegada_publico(
            resultado, api_consultada=True, ponto_pedido="Biênio"
        )
        self.assertEqual(
            contrato.sentidos[0].dados_operacionais[0]["veiculos"][0]["t"],
            "10:10",
        )
        vista = contrato.public_view()["sentidos"][0]
        self.assertNotIn("dados_operacionais", vista)
        self.assertEqual(vista["chegadas"][0]["source"], "live")
        self.assertEqual(vista["chegadas"][0]["confidence"], "high")

    def test_8084_sem_eta_direto_usa_gps_do_sentido_oficial(self):
        linhas = [
            {
                "cl": 2607, "lt": "8084", "tl": 10, "sl": 1,
                "tp": "CID. UNIVERSITÁRIA", "ts": "METRÔ BUTANTÃ",
            },
            {
                "cl": 35375, "lt": "8084", "tl": 10, "sl": 2,
                "tp": "CID. UNIVERSITÁRIA", "ts": "METRÔ BUTANTÃ",
            },
        ]
        posicoes = {
            2607: {
                "hr": "13:28",
                "vs": [
                    {
                        "p": "82494", "a": True,
                        "ta": "2026-08-26T16:28:29Z",
                        "py": -23.5711535, "px": -46.709219,
                    },
                    {
                        "p": "82638", "a": True,
                        "ta": "2026-08-26T16:28:12Z",
                        "py": -23.564584, "px": -46.7133085,
                    },
                ],
            },
            35375: {
                "hr": "13:28",
                "vs": [{
                    "p": "sentido-oposto", "a": True,
                    "ta": "2026-08-26T16:28:30Z",
                    "py": -23.559268, "px": -46.72992025,
                }],
            },
        }
        sessao = SessaoChegadasControlada(
            linhas,
            {
                2607: {"hr": "13:28", "ps": []},
                35375: {"hr": "13:28", "ps": []},
            },
            posicoes,
        )
        referencia = datetime(
            2026, 8, 26, 13, 28, tzinfo=circulares.FUSO_SP
        )
        with (
            patch(
                "uspapo.ferramentas.circulares.requests.Session",
                return_value=sessao,
            ),
            patch(
                "uspapo.ferramentas.circulares._programacao_gtfs",
                return_value=self._programacao_ao_vivo(
                    "120010357", "Cid. Universitária"
                ),
            ),
            patch(
                "uspapo.ferramentas.circulares._instante_referencia_sptrans",
                return_value=referencia,
            ),
            patch(
                "uspapo.ferramentas.circulares._agora_sptrans",
                return_value=referencia,
            ),
            patch(
                "uspapo.ferramentas.circulares.cache",
                side_effect=lambda _c, _t, produzir: produzir(),
            ),
        ):
            resultado = circulares._obter_previsao_sptrans(
                "8084", "Biênio", "token-teste",
                sentido_esperado="Cid. Universitária",
            )

        self.assertEqual(resultado["tipo"], "previsao")
        self.assertEqual(resultado["destino"], "Cid. Universitária")
        self.assertEqual(
            [item["p"] for item in resultado["veiculos"]],
            ["82638"],
        )
        self.assertNotIn(
            "82494",
            {item["p"] for item in resultado["veiculos"]},
        )
        self.assertTrue(all(
            item["source"] == "live_gps_estimate"
            for item in resultado["veiculos"]
        ))
        self.assertNotIn(
            "sentido-oposto",
            {item["p"] for item in resultado["veiculos"]},
        )

    def test_plataforma_proxima_ou_cp_sem_mapeamento_nunca_viram_eta(self):
        linha = {
            "cl": 1, "lt": "8084", "tl": 10, "sl": 1,
            "tp": "TERMINAL A", "ts": "TERMINAL B",
        }
        programacao = self._programacao_ao_vivo()
        resultado, _ = self._consultar_chegadas_controladas(programacao, [linha], {
            1: {"hr": "10:00", "ps": [{
                # Mesmo nome/coordenada não comprovam que é a plataforma GTFS.
                "cp": "olho-vivo-outra-plataforma", "np": "Biênio", "ed": "Poli",
                "py": -23.55, "px": -46.72,
                "vs": [{"p": "errado", "t": "10:05"}],
            }]},
        })

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertNotIn("veiculos", resultado)
        self.assertIn("inequívoca", resultado["aviso_api"])

    def test_duas_plataformas_gtfs_de_sentidos_distintos_exigem_sentido(self):
        catalogo = {"linhas": {"8084": [{"viagens": [
            {"destino": "TERMINAL A", "paradas": [{"id": "a", "nome": "Ponto X", "latitude": -23.5, "longitude": -46.7}]},
            {"destino": "TERMINAL B", "paradas": [{"id": "b", "nome": "Ponto X", "latitude": -23.5, "longitude": -46.7}]},
        ]}]}}
        with patch("uspapo.ferramentas.circulares._catalogo_gtfs", return_value=catalogo):
            self.assertTrue(circulares._plataformas_gtfs_ambíguas(
                "8084", "Ponto X", sentido_esperado=None,
                parada_id_esperada=None,
            ))
            self.assertFalse(circulares._plataformas_gtfs_ambíguas(
                "8084", "Ponto X", sentido_esperado="TERMINAL A",
                parada_id_esperada=None,
            ))

    def test_dois_sentidos_na_mesma_parada_ficam_separados(self):
        linhas = [
            {"cl": 1, "lt": "8084", "tl": 10, "sl": 1, "tp": "TERMINAL A", "ts": "TERMINAL B"},
            {"cl": 2, "lt": "8084", "tl": 10, "sl": 2, "tp": "TERMINAL A", "ts": "TERMINAL B"},
        ]
        programacao = {
            "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
            "sentidos": [
                self._programacao_ao_vivo("gtfs-a", "TERMINAL A"),
                self._programacao_ao_vivo("gtfs-b", "TERMINAL B"),
            ],
        }
        resultado, _ = self._consultar_chegadas_controladas(programacao, linhas, {
            1: {"hr": "10:00", "ps": [{"cp": "gtfs-a", "vs": [{"p": "a", "t": "10:05"}]}]},
            2: {"hr": "10:00", "ps": [{"cp": "gtfs-b", "vs": [{"p": "b", "t": "10:07"}]}]},
        })

        self.assertEqual(
            [(item["destino"], item["veiculos"][0]["t"])
             for item in resultado["previsoes_por_sentido"]],
            [("TERMINAL A", "10:05"), ("TERMINAL B", "10:07")],
        )
        contrato = circulares._resultado_chegada_publico(
            resultado, api_consultada=True, ponto_pedido="Biênio"
        )
        self.assertEqual(len(contrato.sentidos), 2)

    def test_sentido_sem_eta_nao_some_quando_o_oposto_tem_live(self):
        linhas = [
            {"cl": 1, "lt": "8084", "tl": 10, "sl": 1,
             "tp": "TERMINAL A", "ts": "TERMINAL B"},
            {"cl": 2, "lt": "8084", "tl": 10, "sl": 2,
             "tp": "TERMINAL A", "ts": "TERMINAL B"},
        ]
        programacao = {
            "tipo": "programacao", "linha": "8084-10", "parada": "Biênio",
            "sentidos": [
                self._programacao_ao_vivo("gtfs-a", "TERMINAL A"),
                self._programacao_ao_vivo("gtfs-b", "TERMINAL B"),
            ],
        }
        resultado, _ = self._consultar_chegadas_controladas(
            programacao,
            linhas,
            {
                1: {"hr": "10:00", "ps": [{
                    "cp": "gtfs-a",
                    "vs": [{"p": "a", "t": "10:05"}],
                }]},
                2: {"hr": "10:00", "ps": []},
            },
        )

        contrato = circulares._resultado_chegada_publico(
            resultado, api_consultada=True, ponto_pedido="Biênio"
        )

        self.assertEqual(
            [item.sentido for item in contrato.sentidos],
            ["TERMINAL A", "TERMINAL B"],
        )
        self.assertTrue(contrato.sentidos[0].previsoes_ao_vivo)
        self.assertEqual(
            contrato.sentidos[1].horarios_programados,
            ("10:20",),
        )
        texto = circulares.renderizar_chegada(contrato)
        self.assertIn("TERMINAL B", texto)
        self.assertIn("10:20", texto)

    def test_sentido_explicito_exclui_eta_do_oposto(self):
        linhas = [
            {"cl": 1, "lt": "8084", "tl": 10, "sl": 1, "tp": "TERMINAL A", "ts": "TERMINAL B"},
            {"cl": 2, "lt": "8084", "tl": 10, "sl": 2, "tp": "TERMINAL A", "ts": "TERMINAL B"},
        ]
        resultado, _ = self._consultar_chegadas_controladas(
            self._programacao_ao_vivo("gtfs-b", "TERMINAL B"), linhas, {
                1: {"hr": "10:00", "ps": [{"cp": "gtfs-b", "vs": [{"p": "a", "t": "10:05"}]}]},
                2: {"hr": "10:00", "ps": [{"cp": "gtfs-b", "vs": [{"p": "b", "t": "10:07"}]}]},
            },
        )

        self.assertEqual(resultado["destino"], "TERMINAL B")
        self.assertEqual([item["t"] for item in resultado["veiculos"]], ["10:07"])

    def test_eta_stale_faz_fallback_programado(self):
        linha = {
            "cl": 1, "lt": "8084", "tl": 10, "sl": 1,
            "tp": "TERMINAL A", "ts": "TERMINAL B",
        }
        resultado, _ = self._consultar_chegadas_controladas(
            self._programacao_ao_vivo(), [linha], {
                1: {"hr": "10:00", "ps": [{
                    "cp": "gtfs-bienio", "vs": [{"p": "stale", "t": "09:40"}],
                }]},
            }, {1: {"hr": "10:00", "vs": [{"p": "stale"}]}},
        )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["veiculos_ativos"], 1)
        self.assertIn("não publicou um ETA", resultado["aviso_api"])

    @patch.dict("os.environ", {}, clear=True)
    @patch("uspapo.ferramentas.circulares._programacao_gtfs")
    def test_sem_token_informa_que_horario_e_programado(self, programacao):
        programacao.return_value = {
            "tipo": "programacao",
            "linha": "8084-10",
            "parada": "Biênio",
            "horarios": ["11:42", "11:54", "12:06"],
        }

        resposta = circulares.consultar_circulares(
            "8084",
            "Biênio",
            _pergunta="Quando vai passar o 8084 no Biênio?",
        )
        texto, fontes = resposta

        self.assertIn("11:42, 11:54, 12:06", texto)
        self.assertIn("estimativa baseada na programação", texto)
        self.assertNotIn("SPTRANS_TOKEN", texto)
        self.assertEqual(
            resposta.dados_publicos["status_api"], "nao_consultada"
        )
        self.assertEqual(
            resposta.dados_publicos["sentidos"][0]["base_previsao"],
            "horario_programado",
        )
        self.assertEqual(fontes, [circulares.FONTE_GTFS])


if __name__ == "__main__":
    unittest.main()
