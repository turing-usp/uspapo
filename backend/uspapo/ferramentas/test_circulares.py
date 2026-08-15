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
            ("reitoria", "bienio"): "8084-10",
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

        self.assertIn(
            "deve passar em **Biênio** por volta de **11:36**",
            texto,
        )
        self.assertIn("espera típica", texto)
        self.assertIn("6 minutos", texto)
        self.assertIn("12 minutos", texto)
        self.assertIn("estimativa baseada na programação", texto)
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
        for origem, embarque_esperado in (
            ("restaurante_central", "CrUSP II"),
            ("reitoria", "Reitoria"),
        ):
            with self.subTest(origem=origem):
                plano = circulares._planejar_trajeto_gtfs(
                    origem, "bienio", agora
                )
                melhor = plano["melhor"]
                self.assertEqual(melhor["modo"], "onibus")
                self.assertEqual(melhor["linha"], "8084-10")
                self.assertEqual(melhor["embarque"], embarque_esperado)
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
        self.assertIn("**CrUSP II**", texto)
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
        self.assertEqual(melhor["viagem_s"], 990)
        self.assertEqual(melhor["espera_programada_s"], 450)
        self.assertAlmostEqual(melhor["total_estimado_s"], 1507.23, places=2)

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
        self.assertIn("23 minutos no total", texto)
        self.assertNotIn("25 minutos", texto)
        self.assertIn(circulares.FONTE_API, fontes)

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

        resultado = circulares._obter_previsao_sptrans("8084", "Biênio", "token-teste")

        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["destino"], "CIDADE UNIVERSITARIA")
        self.assertEqual(resultado["parada"], "AV. PROF. LUCIANO GUALBERTO")
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

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertIn("nenhum ETA do sentido oposto", resultado["aviso_api"])
        self.assertEqual(
            [caminho for caminho, _parametros in sessao.consultas],
            ["Buscar"],
        )

    def test_destino_sptrans_respeita_o_sentido_da_api(self):
        linha = {"tp": "TERMINAL PRINCIPAL", "ts": "TERMINAL SECUNDARIO"}
        self.assertEqual(
            circulares._destino_linha_sptrans({**linha, "sl": 1}),
            "TERMINAL SECUNDARIO",
        )
        self.assertEqual(
            circulares._destino_linha_sptrans({**linha, "sl": 2}),
            "TERMINAL PRINCIPAL",
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

        obter.assert_called_once_with("8084", "Biênio", "token-teste")
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

        resposta = circulares.consultar_circulares(
            "8084",
            "Biênio",
            _pergunta="Quando vai passar o 8084 no Biênio?",
        )
        texto, fontes = resposta

        self.assertIn("11:42, 11:54, 12:06", texto)
        self.assertIn("estimativa baseada na programação", texto)
        self.assertNotIn("SPTRANS_TOKEN", texto)
        self.assertNotIn("GTFS", texto)
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
