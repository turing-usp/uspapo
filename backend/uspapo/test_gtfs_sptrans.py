"""Testes do motor de horários sobre o recorte GTFS oficial.

Boa parte deles roda contra o recorte de verdade versionado no repositório, e não
contra fixtures: é ele que o servidor lê, e um erro de semântica do GTFS só
aparece nos dados reais. Os casos com catálogo sintético existem para fixar
regras que o recorte atual não exercita — ``exact_times=1``, viagem depois das
24:00, exceção de calendário e a lacuna entre duas faixas de frequência.

Rodar: python -m unittest backend.uspapo.test_gtfs_sptrans -v, com PYTHONPATH=backend.
"""

import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

from uspapo import gtfs_sptrans
from uspapo.ferramentas import normalizar
from uspapo.locais_usp import CATALOGO_LOCAIS, coordenada_local

FUSO = gtfs_sptrans.FUSO_SP


def _catalogo_sintetico(frequencias, *, servico="util") -> dict:
    return {
        "criterio": {"linhas_com_parada_na_area_do_campus": {
            "latitude_min": -23.5705, "latitude_max": -23.5450,
            "longitude_min": -46.7500, "longitude_max": -46.7100,
        }},
        "calendarios": {
            servico: {
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
                    "servico": servico,
                    "destino": "Destino de teste",
                    "frequencias": frequencias,
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


class TestCalendario(unittest.TestCase):
    def test_calendar_dates_tem_precedencia_sobre_calendario_semanal(self):
        catalogo = {
            "calendarios": {
                "util": {
                    "dias": [1, 1, 1, 1, 1, 0, 0],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {"util": {"20260814": 2, "20260815": 1}},
        }

        self.assertFalse(
            gtfs_sptrans.servico_ativo(catalogo, "util", date(2026, 8, 14))
        )
        self.assertTrue(
            gtfs_sptrans.servico_ativo(catalogo, "util", date(2026, 8, 15))
        )

    def test_snapshot_vencido_e_exposto_na_nota(self):
        with patch(
            "uspapo.gtfs_sptrans.catalogo",
            return_value={"gerado_em": "2026-08-01T12:00:00+00:00"},
        ):
            nota = gtfs_sptrans.nota_atualizacao(
                datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
            )

        self.assertIn("01/08/2026", nota)
        self.assertIn("há 9 dias sem atualização", nota)


class TestEsperaProgramada(unittest.TestCase):
    """A semântica de ``frequencies.txt``, que é onde o motor mais errava."""

    def setUp(self):
        gtfs_sptrans.limpar_caches()

    def tearDown(self):
        gtfs_sptrans.limpar_caches()

    def test_dentro_da_faixa_a_espera_e_meio_intervalo(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 11 * 3600, "fim": 12 * 3600,
             "intervalo": 600, "exact_times": 0},
        ])
        viagem = catalogo["linhas"]["9999"][0]["viagens"][0]

        espera = gtfs_sptrans.espera_no_ponto(
            catalogo, viagem, viagem["paradas"][0],
            datetime(2026, 8, 14, 11, 30, tzinfo=FUSO),
        )

        self.assertEqual(espera.esperada_s, 300)
        self.assertEqual(espera.minima_s, 0)
        self.assertEqual(espera.maxima_s, 600)
        self.assertEqual(espera.intervalo_s, 600)

    def test_lacuna_entre_faixas_nunca_vira_espera_de_segundos(self):
        """A regressão que embaralhava o ranking inteiro do planejador.

        A SPTrans publica as janelas como [inicio, inicio+3540], deixando 60 s
        de lacuna até a próxima. Quem caísse nessa lacuna recebia "o ônibus
        passa em 40 segundos" — e vencia todas as outras linhas.
        """
        catalogo = _catalogo_sintetico([
            {"inicio": 10 * 3600, "fim": 10 * 3600 + 3540,
             "intervalo": 600, "exact_times": 0},
            {"inicio": 11 * 3600, "fim": 11 * 3600 + 3540,
             "intervalo": 900, "exact_times": 0},
        ])
        viagem = catalogo["linhas"]["9999"][0]["viagens"][0]
        parada = viagem["paradas"][0]

        # 10:59:30 cai exatamente na lacuna entre as duas faixas.
        na_lacuna = gtfs_sptrans.espera_no_ponto(
            catalogo, viagem, parada,
            datetime(2026, 8, 14, 10, 59, 30, tzinfo=FUSO),
        )
        self.assertEqual(na_lacuna.intervalo_s, 900)
        self.assertEqual(na_lacuna.esperada_s, 30 + 450)
        self.assertEqual(na_lacuna.minima_s, 30)

        # E a espera cresce ao longo da lacuna, em vez de despencar para zero.
        for segundo in range(0, 60, 10):
            instante = datetime(2026, 8, 14, 10, 59, tzinfo=FUSO) + timedelta(
                seconds=segundo
            )
            with self.subTest(instante=instante.strftime("%H:%M:%S")):
                espera = gtfs_sptrans.espera_no_ponto(
                    catalogo, viagem, parada, instante
                )
                self.assertGreaterEqual(espera.esperada_s, 450)

    def test_exact_times_um_usa_a_proxima_partida_da_grade(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 11 * 3600 + 30 * 60, "fim": 12 * 3600,
             "intervalo": 600, "exact_times": 1},
        ])
        viagem = catalogo["linhas"]["9999"][0]["viagens"][0]

        espera = gtfs_sptrans.espera_no_ponto(
            catalogo, viagem, viagem["paradas"][0],
            datetime(2026, 8, 14, 11, 33, tzinfo=FUSO),
        )

        self.assertEqual(espera.esperada_s, 7 * 60)
        self.assertIsNone(espera.intervalo_s)
        self.assertEqual(espera.minima_s, espera.maxima_s)

    def test_viagem_apos_24h_pertence_ao_dia_de_servico_anterior(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 24 * 3600 + 30 * 60, "fim": 25 * 3600,
             "intervalo": 600, "exact_times": 0},
        ])
        viagem = catalogo["linhas"]["9999"][0]["viagens"][0]

        # 00:35 de sábado ainda é a madrugada do serviço de sexta.
        espera = gtfs_sptrans.espera_no_ponto(
            catalogo, viagem, {"deslocamento": 0},
            datetime(2026, 8, 15, 0, 35, tzinfo=FUSO),
        )

        self.assertEqual(espera.esperada_s, 300)
        self.assertEqual(espera.intervalo_s, 600)

    def test_dia_sem_servico_nao_produz_espera(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 11 * 3600, "fim": 12 * 3600,
             "intervalo": 600, "exact_times": 0},
        ])
        viagem = catalogo["linhas"]["9999"][0]["viagens"][0]

        # 16/08/2026 é domingo, e o serviço é de segunda a sexta.
        self.assertIsNone(gtfs_sptrans.espera_no_ponto(
            catalogo, viagem, viagem["paradas"][0],
            datetime(2026, 8, 16, 11, 30, tzinfo=FUSO),
        ))

    def test_faixa_de_headway_nunca_vira_partida_exata(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 11 * 3600, "fim": 12 * 3600,
             "intervalo": 600, "exact_times": 0},
        ])
        viagem = catalogo["linhas"]["9999"][0]["viagens"][0]

        self.assertIsNone(gtfs_sptrans.proxima_partida_exata(
            catalogo, viagem, viagem["paradas"][0],
            datetime(2026, 8, 14, 11, 30, tzinfo=FUSO),
        ))


class TestProgramacao(unittest.TestCase):
    @staticmethod
    def agora_dia_util() -> datetime:
        gerado = datetime.fromisoformat(
            gtfs_sptrans.catalogo()["gerado_em"].replace("Z", "+00:00")
        ).astimezone(FUSO)
        dia = gerado.date()
        while dia.weekday() >= 5:
            dia += timedelta(days=1)
        return datetime.combine(dia, time(11, 30), tzinfo=FUSO)

    def test_encontra_o_bienio_e_a_faixa_ativa(self):
        resultado = gtfs_sptrans.programacao(
            "8084", "Biênio", self.agora_dia_util()
        )

        self.assertEqual(resultado["tipo"], "programacao")
        self.assertEqual(resultado["linha"], "8084-10")
        self.assertEqual(resultado["parada"], "Biênio")
        self.assertEqual(resultado["parada_id"], "120010357")
        # O feed marca as frequências da 8084 com exact_times=0: os múltiplos
        # do headway não são partidas cravadas e não podem virar "previsões".
        self.assertEqual(resultado["horarios"], [])
        self.assertEqual(resultado["faixas"][0]["intervalo_min"], 12)
        self.assertTrue(resultado["faixas"][0]["ativa_agora"])
        self.assertEqual(resultado["faixas"][0]["espera_tipica_min"], 6)
        self.assertEqual(
            resultado["faixas"][0]["proxima_referencia_texto"], "11:36"
        )

    def test_respeita_o_sentido_escolhido(self):
        resultado = gtfs_sptrans.programacao(
            "8082", "metro_butanta", self.agora_dia_util(), "Cid. Universitária"
        )

        self.assertEqual(resultado["linha"], "8082-10")
        self.assertEqual(resultado["destino"], "Cid. Universitária")
        self.assertEqual(resultado["parada"], "Terminal Metrô Butantã")

    def test_sentido_inexistente_nao_responde_o_sentido_oposto(self):
        """Silenciar o filtro devolvia o ônibus que vai para o outro lado."""
        resultado = gtfs_sptrans.programacao(
            "8082", "metro_butanta", self.agora_dia_util(), "Aeroporto de Guarulhos"
        )

        self.assertIn("erro", resultado)
        self.assertIn("Aeroporto de Guarulhos", resultado["erro"])
        self.assertNotIn("destino", resultado)

    def test_sem_sentido_nao_mistura_headsigns(self):
        resultado = gtfs_sptrans.programacao(
            "177H", "Terminal USP", self.agora_dia_util()
        )

        self.assertGreaterEqual(len(resultado["sentidos"]), 2)
        destinos = {item["destino"] for item in resultado["sentidos"]}
        self.assertIn("Cid. Universitária", destinos)
        self.assertIn("Metrô Santana", destinos)
        for item in resultado["sentidos"]:
            self.assertNotIn("sentidos", item)

    def test_multiplos_sentidos_usam_o_nome_canonico_da_parada(self):
        """O texto que o aluno digitou não pode virar nome de parada."""
        resultado = gtfs_sptrans.programacao(
            "8082", "metro butanta", self.agora_dia_util()
        )

        self.assertEqual(resultado["parada"], "Terminal Metrô Butantã")
        self.assertTrue(resultado["parada_id"])
        for sentido in resultado["sentidos"]:
            self.assertEqual(sentido["parada"], "Terminal Metrô Butantã")

    def test_horarios_cravados_so_com_exact_times_um(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 11 * 3600 + 30 * 60, "fim": 12 * 3600,
             "intervalo": 600, "exact_times": 1},
        ])
        with patch("uspapo.gtfs_sptrans.catalogo", return_value=catalogo):
            resultado = gtfs_sptrans.programacao(
                "9999", "Biênio", datetime(2026, 8, 14, 11, 30, tzinfo=FUSO)
            )

        self.assertEqual(resultado["horarios"], ["11:30", "11:40", "11:50"])
        self.assertNotIn("faixas", resultado)

    def test_madrugada_pertence_ao_dia_de_servico_anterior(self):
        catalogo = _catalogo_sintetico([
            {"inicio": 24 * 3600 + 30 * 60, "fim": 25 * 3600,
             "intervalo": 600, "exact_times": 1},
        ])
        with patch("uspapo.gtfs_sptrans.catalogo", return_value=catalogo):
            resultado = gtfs_sptrans.programacao(
                "9999", "Biênio", datetime(2026, 8, 15, 0, 20, tzinfo=FUSO)
            )

        self.assertEqual(resultado["horarios"], ["00:30", "00:40", "00:50"])

    def test_matching_nao_confunde_siglas_com_ruas_fora_da_usp(self):
        agora = self.agora_dia_util()

        self.assertNotIn(
            "policia",
            normalizar(gtfs_sptrans.programacao("8084", "Poli", agora)["parada"]),
        )
        self.assertIn(
            "erro", gtfs_sptrans.programacao("7725", "Metrô Butantã", agora)
        )
        for sigla, falso in (("FAU", "faustolo"), ("IP", "ipiranga"), ("HU", "hugo")):
            with self.subTest(sigla=sigla):
                atendimento = gtfs_sptrans.linhas_por_ponto(sigla)
                self.assertNotIn(falso, normalizar(atendimento["parada"]))

    def test_linha_fora_do_recorte_explica_em_vez_de_negar(self):
        resultado = gtfs_sptrans.programacao("1234", "Biênio")

        self.assertIn("NÃO conclua que a linha não existe", resultado["erro"])


class TestConsultaPorParada(unittest.TestCase):
    def test_consulta_reversa_lista_as_linhas_do_bienio(self):
        resultado = gtfs_sptrans.linhas_por_ponto("Biênio")

        linhas = {item["linha"] for item in resultado["linhas"]}
        self.assertIn("8084-10", linhas)
        self.assertNotIn("8032-10", linhas)

    def test_todas_as_paradas_da_area_oficial_sao_consultaveis(self):
        paradas = gtfs_sptrans.catalogo()["paradas_na_area_selecao"]
        self.assertGreaterEqual(len(paradas), 100)
        for stop_id, parada in paradas.items():
            with self.subTest(stop_id=stop_id, nome=parada["nome"]):
                atendimento = gtfs_sptrans.linhas_por_ponto(parada["nome"])
                self.assertNotIn("erro", atendimento)
                self.assertTrue(atendimento["linhas"])

    def test_nomes_de_parada_do_catalogo_existem_no_gtfs_oficial(self):
        nomes_gtfs = {
            normalizar(parada["nome"])
            for rotas in gtfs_sptrans.catalogo()["linhas"].values()
            for rota in rotas
            for viagem in rota["viagens"]
            for parada in viagem["paradas"]
        }
        declarados = 0
        for chave, local in CATALOGO_LOCAIS.items():
            for nome in local["nomes_parada"]:
                declarados += 1
                with self.subTest(chave=chave, nome=nome):
                    self.assertIn(normalizar(nome), nomes_gtfs)
        self.assertGreaterEqual(declarados, 40)

    def test_todo_local_canonico_tem_parada_caminhavel(self):
        paradas = list({
            str(parada["id"]): parada
            for rotas in gtfs_sptrans.catalogo()["linhas"].values()
            for rota in rotas
            for viagem in rota["viagens"]
            for parada in viagem["paradas"]
        }.values())
        for chave in CATALOGO_LOCAIS:
            coordenada = coordenada_local(chave)
            menor = min(
                gtfs_sptrans.distancia_m(parada, coordenada)
                for parada in paradas
            )
            with self.subTest(chave=chave, distancia=round(menor)):
                self.assertLessEqual(menor, gtfs_sptrans.RAIO_ACESSO_M)

    def test_area_de_selecao_nao_corta_as_bordas_do_campus(self):
        for chave in CATALOGO_LOCAIS:
            dentro = gtfs_sptrans.dentro_do_campus(coordenada_local(chave))
            with self.subTest(chave=chave):
                # O Metrô Butantã é o hub externo: ele fica fora de propósito, e
                # é justamente essa diferença que sustenta a regra anti-desvio.
                self.assertEqual(dentro, chave != "metro_butanta")

    def test_nome_repetido_na_cidade_fica_no_grupo_do_campus(self):
        """A média entre dois grupos distantes caía longe dos dois."""
        catalogo = _catalogo_sintetico([])
        perto = {
            "id": "perto", "nome": "Terminal Repetido",
            "latitude": -23.5578, "longitude": -46.7323,
            "sequencia": 1, "deslocamento": 0, "horario": 0,
        }
        longe = {
            "id": "longe", "nome": "Terminal Repetido",
            "latitude": -23.5024, "longitude": -46.6240,
            "sequencia": 2, "deslocamento": 60, "horario": 60,
        }
        catalogo["linhas"]["9999"][0]["viagens"][0]["paradas"] = [perto, longe]

        gtfs_sptrans.limpar_caches()
        try:
            with patch("uspapo.gtfs_sptrans.catalogo", return_value=catalogo):
                coordenada = gtfs_sptrans.coordenada_do_ponto("Terminal Repetido")
                distancia = gtfs_sptrans.distancia_m(perto, coordenada)
        finally:
            gtfs_sptrans.limpar_caches()

        self.assertLess(distancia, 50)


class TestPlanejador(unittest.TestCase):
    @staticmethod
    def agora_dia_util() -> datetime:
        return TestProgramacao.agora_dia_util()

    def test_compara_origem_destino_e_sentido(self):
        agora = self.agora_dia_util()
        casos = {("p1", "bienio"): "8084-10", ("metro_butanta", "mecanica"): "8082-10"}

        for (origem, destino), linha_esperada in casos.items():
            with self.subTest(origem=origem, destino=destino):
                plano = gtfs_sptrans.planejar_trajeto(origem, destino, agora)
                self.assertEqual(plano["melhor"]["linha"], linha_esperada)
                self.assertGreater(plano["melhor"]["viagem_min"], 0)
                self.assertLessEqual(
                    plano["melhor"]["caminhada_origem_m"],
                    gtfs_sptrans.RAIO_ACESSO_M,
                )

    def test_componentes_brutos_sobrevivem_ate_a_apresentacao(self):
        melhor = gtfs_sptrans.planejar_trajeto(
            "metro_butanta", "mecanica",
            datetime(2026, 8, 14, 12, 4, tzinfo=FUSO),
        )["melhor"]

        self.assertEqual(melhor["linha"], "8082-10")
        self.assertEqual(melhor["viagem_s"], 990)
        self.assertEqual(melhor["espera_programada_s"], 450)
        self.assertEqual(melhor["espera_minima_s"], 0)
        self.assertEqual(melhor["espera_maxima_s"], 900)
        self.assertAlmostEqual(melhor["total_estimado_s"], 1507.23, places=2)

    def test_a_linha_recomendada_nao_muda_a_cada_minuto(self):
        """Cada lacuna entre faixas fazia uma linha diferente "ganhar"."""
        inicio = self.agora_dia_util().replace(hour=14, minute=0)
        for origem, destino in (
            ("restaurante_central", "bienio"),
            ("p1", "bienio"),
            ("metro_butanta", "mecanica"),
        ):
            escolhas = {
                gtfs_sptrans.planejar_trajeto(
                    origem, destino, inicio + timedelta(minutes=minuto)
                )["melhor"].get("linha")
                for minuto in range(30)
            }
            with self.subTest(origem=origem, destino=destino):
                self.assertEqual(len(escolhas), 1, f"a escolha oscilou: {escolhas}")

    def test_nenhuma_opcao_tem_espera_irreal(self):
        agora = self.agora_dia_util()
        chaves = list(CATALOGO_LOCAIS)
        for origem in chaves:
            for destino in chaves:
                if origem == destino:
                    continue
                plano = gtfs_sptrans.planejar_trajeto(origem, destino, agora)
                opcoes = [plano["melhor"], *plano.get("alternativas", [])]
                for opcao in opcoes:
                    if opcao.get("modo") != "onibus":
                        continue
                    with self.subTest(origem=origem, destino=destino,
                                      linha=opcao["linha"]):
                        # Uma espera de segundos era artefato da lacuna entre
                        # faixas; uma de horas era a partida do dia seguinte.
                        self.assertGreaterEqual(opcao["espera_programada_s"], 30)
                        self.assertLessEqual(
                            opcao["espera_programada_s"],
                            gtfs_sptrans.MAX_ESPERA_MIN * 60,
                        )

    def test_onibus_nunca_vence_uma_caminhada_mais_rapida(self):
        agora = self.agora_dia_util()
        chaves = list(CATALOGO_LOCAIS)
        for origem in chaves:
            for destino in chaves:
                if origem == destino:
                    continue
                plano = gtfs_sptrans.planejar_trajeto(origem, destino, agora)
                melhor = plano["melhor"]
                if melhor["modo"] != "onibus":
                    continue
                a_pe_s = (
                    plano["caminhada_direta_m"]
                    / gtfs_sptrans.VELOCIDADE_CAMINHADA_M_MIN
                    * 60
                )
                with self.subTest(origem=origem, destino=destino):
                    self.assertLess(melhor["total_estimado_s"], a_pe_s)

    def test_domingo_devolve_caminhada_dizendo_que_a_linha_nao_circula(self):
        domingo = datetime(2026, 8, 16, 14, 0, tzinfo=FUSO)

        plano = gtfs_sptrans.planejar_trajeto("metro_butanta", "bienio", domingo)

        self.assertEqual(plano["melhor"]["modo"], "a_pe")
        self.assertEqual(plano["alternativas"], [])
        self.assertIn("não têm passagem programada", plano["aviso"])

    def test_trajeto_interno_nunca_desvia_pelo_terminal(self):
        # 07:10 é o horário do feedback reproduzido no print do usuário.
        agora = self.agora_dia_util().replace(hour=7, minute=10)
        for origem in ("restaurante_central", "reitoria", "praca_relogio"):
            plano = gtfs_sptrans.planejar_trajeto(origem, "bienio", agora)
            with self.subTest(origem=origem):
                for opcao in [plano["melhor"], *plano.get("alternativas", [])]:
                    self.assertFalse(opcao.get("passa_metro_butanta"))

    def test_regra_anti_desvio_vale_para_parada_em_texto_livre(self):
        """A regra já foi pertencimento ao catálogo manual de locais.

        Com isso, bastava uma das pontas ser um nome de parada solto para ela
        desligar sozinha e o desvio até o terminal voltar. Os dois pontos abaixo
        existem no GTFS, ficam dentro do campus e NÃO estão em CATALOGO_LOCAIS.
        """
        agora = self.agora_dia_util().replace(hour=7, minute=10)
        origem, destino = "Parada Caxingui", "Energia E Ambiente"
        for ponto in (origem, destino):
            self.assertIsNone(gtfs_sptrans.chave_local(ponto))
            self.assertTrue(
                gtfs_sptrans.dentro_do_campus(
                    gtfs_sptrans.coordenada_do_ponto(ponto)
                )
            )

        plano = gtfs_sptrans.planejar_trajeto(origem, destino, agora)

        self.assertNotIn("erro", plano)
        for opcao in [plano["melhor"], *plano.get("alternativas", [])]:
            self.assertFalse(opcao.get("passa_metro_butanta"))

    def test_sair_do_terminal_ainda_pode_passar_pelo_terminal(self):
        """A regra vale para trajeto interno, e não para quem embarca no metrô."""
        agora = self.agora_dia_util().replace(hour=7, minute=10)

        plano = gtfs_sptrans.planejar_trajeto(
            "metro_butanta", "Energia E Ambiente", agora
        )

        self.assertEqual(plano["melhor"]["modo"], "onibus")
        self.assertTrue(plano["melhor"]["passa_metro_butanta"])

    def test_matriz_de_todos_os_locais_tem_resultado_e_invariantes(self):
        agora = self.agora_dia_util()
        chaves = list(CATALOGO_LOCAIS)
        pares_testados = 0
        for origem in chaves:
            self.assertIsNotNone(coordenada_local(origem))
            for destino in chaves:
                if origem == destino:
                    continue
                pares_testados += 1
                plano = gtfs_sptrans.planejar_trajeto(origem, destino, agora)
                with self.subTest(origem=origem, destino=destino):
                    self.assertNotIn("erro", plano)
                    self.assertIn(plano["melhor"]["modo"], {"onibus", "a_pe"})
                    opcoes = [plano["melhor"], *plano.get("alternativas", [])]
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
                            gtfs_sptrans.RAIO_ACESSO_M,
                        )
                        self.assertLessEqual(
                            opcao["caminhada_destino_m"],
                            gtfs_sptrans.RAIO_ACESSO_M,
                        )
                        self.assertAlmostEqual(
                            opcao["total_estimado_s"],
                            opcao["caminhada_origem_s"]
                            + opcao["espera_programada_s"]
                            + opcao["viagem_s"]
                            + opcao["caminhada_destino_s"],
                            places=6,
                        )
                    totais = [
                        opcao["total_estimado_s"]
                        for opcao in opcoes
                        if opcao.get("modo") == "onibus"
                    ]
                    self.assertEqual(totais, sorted(totais))
        self.assertEqual(pares_testados, len(chaves) * (len(chaves) - 1))


if __name__ == "__main__":
    unittest.main()
