"""Regressões dos erros de planejamento observados em produção.

Os horários são deliberadamente fixos. Estes testes não podem mudar de
resultado conforme o dia em que a suíte é executada nem transformar ausência de
uma grade GTFS confiável em uma espera de várias horas.
"""

from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from uspapo.transporte import consultas_circulares as circulares
SABADO = datetime(2026, 8, 15, 13, 0, tzinfo=circulares.FUSO_SP)
QUARTA = datetime(2026, 8, 19, 13, 0, tzinfo=circulares.FUSO_SP)
DOMINGO = datetime(2026, 8, 23, 12, 0, tzinfo=circulares.FUSO_SP)


def _datetime_congelado(instante: datetime):
    class DatetimeCongelado(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instante.replace(tzinfo=None)
            return instante.astimezone(tz)

    return DatetimeCongelado


class TestRegressoesPlanejamento(unittest.TestCase):
    def test_grade_incompleta_ainda_consulta_eta_ao_vivo(self):
        previsao = {
            "tipo": "previsao",
            "api_consultada": True,
            "hr": "13:00",
            "linha": "8022-10",
            "parada": "Terminal Metrô Butantã",
            "destino": "Cid. Universitária",
            "veiculos": [{"t": "13:10", "a": True}],
        }
        with (
            patch.object(circulares, "datetime", _datetime_congelado(SABADO)),
            patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"}),
            patch.object(
                circulares,
                "_obter_previsao_sptrans",
                return_value=previsao,
            ) as obter,
        ):
            resposta = circulares.consultar_circulares(
                linha="",
                origem="metro_butanta",
                destino_ou_ponto="ime",
                _pergunta="Qual ônibus devo pegar agora do metrô até o IME?",
            )

        self.assertGreater(obter.call_count, 0)
        self.assertEqual(resposta.dados_publicos["tipo"], "trajeto_onibus")
        self.assertEqual(resposta.dados_publicos["status_api"], "eta_disponivel")

    def test_eta_atrasado_nao_vira_espera_de_um_dia(self):
        with patch.object(
            circulares,
            "_instante_referencia_sptrans",
            return_value=datetime(
                2026, 8, 15, 11, 40, tzinfo=circulares.FUSO_SP
            ),
        ):
            espera = circulares._espera_ao_vivo(
                {
                    "tipo": "previsao",
                    "hr": "11:40",
                    "veiculos": [{"t": "11:39"}],
                },
                0,
            )

        self.assertIsNone(espera)

    def test_eta_pode_cruzar_meia_noite_sem_ser_descartado(self):
        with patch.object(
            circulares,
            "_instante_referencia_sptrans",
            return_value=datetime(
                2026, 8, 15, 23, 59, tzinfo=circulares.FUSO_SP
            ),
        ):
            espera = circulares._espera_ao_vivo(
                {
                    "tipo": "previsao",
                    "hr": "23:59",
                    "veiculos": [{"t": "00:05"}],
                },
                0,
            )

        self.assertIsNotNone(espera)
        self.assertEqual(espera.esperada_s, 6 * 60)

    def test_eta_atrasado_tambem_e_descartado_na_consulta_direta(self):
        referencia = datetime(
            2026, 8, 15, 11, 40, tzinfo=circulares.FUSO_SP
        )
        with patch.object(
            circulares,
            "_instante_referencia_sptrans",
            return_value=referencia,
        ):
            resultado = circulares._resultado_chegada_publico(
                {
                    "tipo": "previsao",
                    "hr": "11:40",
                    "linha": "8084-10",
                    "parada": "Biênio",
                    "veiculos": [{"t": "11:39"}],
                },
                api_consultada=True,
                ponto_pedido="Biênio",
            )

        self.assertEqual(resultado.sentidos[0].previsoes_ao_vivo, ())

    def test_modo_onibus_no_fim_de_semana_preserva_linha_sem_inventar_tempo(self):
        # As duas circulares ligam o Terminal ao entorno do IME aos fins de
        # semana. Sem uma grade confiável, o ranking pode preferir a 8022 pelo
        # menor trecho a pé; o contrato importante é não fabricar uma espera.
        casos = (
            ("metro_butanta", "ime", {"8012-10", "8022-10"}),
            ("restaurante_central", "ib", {"8022-10"}),
        )

        for origem, destino, linhas_validas in casos:
            with self.subTest(origem=origem, destino=destino):
                plano = circulares._planejar_trajeto_gtfs(
                    origem,
                    destino,
                    SABADO,
                    modo_solicitado="onibus",
                )
                melhor = plano["melhor"]

                self.assertIn(melhor["linha"], linhas_validas)
                self.assertEqual(melhor["modo"], "onibus_sem_horario")
                self.assertIsNone(melhor["espera_programada_s"])
                self.assertIsNone(melhor["total_estimado_s"])

    def test_pergunta_generica_nao_herda_o_sabado_do_relogio(self):
        pergunta = "Quanto tempo demora pra chegar no IME a partir do metrô?"
        resultados = []

        for agora in (SABADO, QUARTA):
            with (
                patch.object(
                    circulares, "datetime", _datetime_congelado(agora)
                ),
                patch.dict("os.environ", {"SPTRANS_TOKEN": ""}),
            ):
                resposta = circulares.consultar_circulares(
                    linha="",
                    origem="metro_butanta",
                    destino_ou_ponto="ime",
                    _pergunta=pergunta,
                )

            dados = resposta.dados_publicos
            self.assertEqual(dados["tipo"], "trajeto_onibus")
            melhor = dados["melhor_opcao"]
            resultados.append((
                melhor["linha"],
                melhor["embarque"],
                melhor["desembarque"],
            ))

        self.assertEqual(resultados[0], resultados[1])

    def test_empate_de_chegada_prefere_parada_com_menor_caminhada(self):
        catalogo = {
            "calendarios": {
                "S": {
                    "dias": [1, 1, 1, 1, 1, 1, 1],
                    "inicio": "20260101",
                    "fim": "20261231",
                }
            },
            "excecoes_calendario": {},
            "linhas": {
                "TESTE": [{
                    "id": "rota-teste",
                    "linha": "TESTE-10",
                    "nome": "Linha de teste",
                    "viagens": [{
                        "id": "viagem-teste",
                        "servico": "S",
                        "destino": "Destino",
                        "frequencias": [],
                        # A parada distante aparece primeiro no itinerário. As
                        # duas opções chegam ao destino no mesmo instante.
                        "paradas": [
                            {
                                "id": "distante",
                                "nome": "Parada distante",
                                "sequencia": 1,
                                "deslocamento": 0,
                                "horario": 0,
                            },
                            {
                                "id": "perto",
                                "nome": "Parada perto",
                                "sequencia": 2,
                                "deslocamento": 60,
                                "horario": 60,
                            },
                            {
                                "id": "destino",
                                "nome": "Parada destino",
                                "sequencia": 3,
                                "deslocamento": 120,
                                "horario": 120,
                            },
                        ],
                    }],
                }],
            },
        }
        coordenada_origem = (1.0, 1.0)
        coordenada_destino = (2.0, 2.0)

        def coordenada(ponto: str):
            return coordenada_origem if ponto == "origem" else coordenada_destino

        def distancia(parada, referencia):
            parada_id = parada.get("id")
            if parada_id is None:  # comparação da caminhada direta
                return 10_000.0
            if referencia == coordenada_origem:
                return {
                    "distante": 150.0,
                    "perto": 50.0,
                    "destino": 1_000.0,
                }[parada_id]
            return {
                "distante": 1_000.0,
                "perto": 1_000.0,
                "destino": 50.0,
            }[parada_id]

        def espera(_catalogo, _viagem, parada, _pronto, ate=None):
            del ate
            # Distante: 112,5 s andando + 487,5 s esperando + 120 s no
            # ônibus. Perto: 37,5 + 622,5 + 60. Com os 37,5 s finais,
            # ambas totalizam exatamente 757,5 s.
            return (
                (487.5 / 60, None)
                if parada["id"] == "distante"
                else (622.5 / 60, None)
            )

        with (
            patch.object(circulares, "_catalogo_gtfs", return_value=catalogo),
            patch.object(circulares, "_coordenada_ponto", side_effect=coordenada),
            patch.object(circulares, "_distancia_parada_gtfs", side_effect=distancia),
            patch.object(circulares, "_espera_media_gtfs", side_effect=espera),
        ):
            plano = circulares._planejar_trajeto_gtfs(
                "origem",
                "destino",
                QUARTA,
                modo_solicitado="onibus",
            )

        self.assertEqual(plano["melhor"]["embarque_id"], "perto")
        self.assertEqual(plano["melhor"]["caminhada_origem_m"], 50)

    def test_rota_direta_usa_mesma_viagem_e_nunca_o_sentido_inverso(self):
        catalogo = {
            "calendarios": {"S": {"dias": [1] * 7, "inicio": "20260101", "fim": "20261231"}},
            "excecoes_calendario": {},
            "linhas": {"T": [{"linha": "T-10", "viagens": [
                {"id": "ida", "servico": "S", "destino": "Destino", "frequencias": [], "paradas": [
                    {"id": "origem", "nome": "Origem", "sequencia": 1, "deslocamento": 0, "horario": 13 * 3600 + 300},
                    {"id": "destino", "nome": "Destino", "sequencia": 2, "deslocamento": 600, "horario": 13 * 3600 + 900},
                ]},
                {"id": "volta", "servico": "S", "destino": "Origem", "frequencias": [], "paradas": [
                    {"id": "destino-volta", "nome": "Destino", "sequencia": 1, "deslocamento": 0, "horario": 13 * 3600 + 300},
                    {"id": "origem-volta", "nome": "Origem", "sequencia": 2, "deslocamento": 600, "horario": 13 * 3600 + 900},
                ]},
            ]}]},
        }

        def coordenada(ponto):
            return (1.0, 1.0) if ponto == "origem" else (2.0, 2.0)

        def distancia(parada, referencia):
            if parada.get("id") is None:
                return 10_000
            nomes = {"origem", "origem-volta"} if referencia == (1.0, 1.0) else {"destino", "destino-volta"}
            return 20 if parada["id"] in nomes else 1_000

        with (
            patch.object(circulares, "_catalogo_gtfs", return_value=catalogo),
            patch.object(circulares, "_coordenada_ponto", side_effect=coordenada),
            patch.object(circulares, "_distancia_parada_gtfs", side_effect=distancia),
            patch.object(circulares, "horario_gtfs_confiavel", return_value=True),
            patch.object(circulares, "parada_atendida_na_data", return_value=True),
        ):
            plano = circulares._planejar_trajeto_gtfs("origem", "destino", QUARTA, "onibus")

        self.assertEqual(plano["melhor"]["sentido"], "Destino")
        self.assertLess(
            plano["melhor"]["embarque_sequencia"],
            plano["melhor"]["desembarque_sequencia"],
        )

    def test_pos_meia_noite_considera_viagem_do_servico_anterior(self):
        catalogo = {
            "calendarios": {"S": {"dias": [1] * 7, "inicio": "20260101", "fim": "20261231"}},
            "excecoes_calendario": {},
            "linhas": {"N": [{"linha": "N-10", "viagens": [{
                "id": "noite", "servico": "S", "destino": "Destino", "frequencias": [], "paradas": [
                    {"id": "a", "nome": "Origem", "sequencia": 1, "deslocamento": 0, "horario": 24 * 3600 + 10 * 60},
                    {"id": "b", "nome": "Destino", "sequencia": 2, "deslocamento": 600, "horario": 24 * 3600 + 20 * 60},
                ],
            }]}]},
        }

        def coordenada(ponto):
            return (1.0, 1.0) if ponto == "origem" else (2.0, 2.0)

        def distancia(parada, referencia):
            if parada.get("id") is None:
                return 10_000
            return 0 if (parada["id"] == "a") == (referencia == (1.0, 1.0)) else 1_000

        instante = datetime(2026, 8, 20, 0, 5, tzinfo=circulares.FUSO_SP)
        with (
            patch.object(circulares, "_catalogo_gtfs", return_value=catalogo),
            patch.object(circulares, "_coordenada_ponto", side_effect=coordenada),
            patch.object(circulares, "_distancia_parada_gtfs", side_effect=distancia),
            patch.object(circulares, "horario_gtfs_confiavel", return_value=True),
            patch.object(circulares, "parada_atendida_na_data", return_value=True),
        ):
            plano = circulares._planejar_trajeto_gtfs("origem", "destino", instante, "onibus")

        self.assertEqual(plano["melhor"]["modo"], "onibus")
        self.assertEqual(plano["melhor"]["linha"], "N-10")
        self.assertLess(plano["melhor"]["espera_programada_s"], 6 * 60)

    def test_rota_sem_grade_confiavel_nao_declara_caminhada_mais_rapida(self):
        pergunta = "Qual o melhor jeito de ir do metrô até o Biênio agora?"
        with (
            patch.object(circulares, "datetime", _datetime_congelado(DOMINGO)),
            patch.dict("os.environ", {"SPTRANS_TOKEN": ""}),
        ):
            plano = circulares._planejar_trajeto_gtfs(
                "metro_butanta", "bienio", DOMINGO,
            )
            resposta = circulares.consultar_circulares(
                origem="metro_butanta", destino_ou_ponto="bienio", _pergunta=pergunta,
            )

        candidatas = [plano["melhor"], *plano["alternativas"]]
        self.assertEqual(plano["melhor"]["modo"], "onibus_sem_horario")
        self.assertIn("8012-10", {item["linha"] for item in candidatas})
        self.assertEqual(resposta.dados_publicos["tipo"], "trajeto_onibus_sem_horario")
        self.assertEqual(resposta.dados_publicos["ranking_temporal"], "indeterminado")
        self.assertIsNone(resposta.dados_publicos["melhor_opcao"])
        self.assertEqual(
            {item["linha"] for item in resposta.dados_publicos["opcoes_diretas"]},
            {"8012-10", "8022-10"},
        )
        self.assertNotIn("opção estimada mais rápida é ir a pé", resposta.texto)

    def test_eta_de_rota_sem_grade_confiavel_entra_na_comparacao(self):
        pergunta = "Qual o melhor jeito de ir do metrô até o Biênio agora?"
        previsao = {
            "tipo": "previsao", "api_consultada": True, "hr": "12:00",
            "veiculos": [{"t": "12:10"}],
        }
        with (
            patch.object(circulares, "datetime", _datetime_congelado(DOMINGO)),
            patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"}),
            patch.object(circulares, "_obter_previsao_sptrans", return_value=previsao),
            patch.object(circulares, "cache", side_effect=lambda _k, _t, produzir: produzir()),
            patch.object(circulares, "_instante_referencia_sptrans", return_value=DOMINGO),
        ):
            resposta = circulares.consultar_circulares(
                origem="metro_butanta", destino_ou_ponto="bienio", _pergunta=pergunta,
            )

        self.assertEqual(resposta.dados_publicos["tipo"], "trajeto_onibus")
        self.assertEqual(resposta.dados_publicos["tempo"]["espera"]["source"], "live")

    def test_um_eta_valido_restaura_ranking_temporal_das_opcoes_sem_horario(self):
        pergunta = "Qual o melhor jeito de ir do metro ate o bienio agora?"

        def previsao(numero, *_args, **_kwargs):
            if numero == "8012":
                return {
                    "tipo": "previsao", "api_consultada": True, "hr": "12:00",
                    "veiculos": [{"t": "12:10"}],
                }
            return {"tipo": "programacao", "api_consultada": True}

        with (
            patch.object(circulares, "datetime", _datetime_congelado(DOMINGO)),
            patch.dict("os.environ", {"SPTRANS_TOKEN": "token-teste"}),
            patch.object(circulares, "_obter_previsao_sptrans", side_effect=previsao),
            patch.object(circulares, "cache", side_effect=lambda _k, _t, produzir: produzir()),
            patch.object(circulares, "_instante_referencia_sptrans", return_value=DOMINGO),
        ):
            resposta = circulares.consultar_circulares(
                origem="metro_butanta", destino_ou_ponto="bienio", _pergunta=pergunta,
            )

        self.assertEqual(resposta.dados_publicos["tipo"], "trajeto_onibus")
        self.assertEqual(resposta.dados_publicos["melhor_opcao"]["linha"], "8012-10")

    def test_atendimento_contextual_da_linha_nao_cai_no_itinerario(self):
        primeiro_turno = "Qual o melhor jeito de ir do metrô até o Biênio agora?"
        segundo_turno = "Mas e a linha 8012? Ela não passa lá hoje?"
        historico = [{"pergunta": primeiro_turno, "resposta": "resposta anterior"}]
        with patch.object(circulares, "datetime", _datetime_congelado(DOMINGO)):
            resposta = circulares.consultar_circulares(
                linha="8012", _pergunta=segundo_turno, _historico=historico,
            )

        self.assertEqual(resposta.dados_publicos["tipo"], "atendimento_linha_parada")
        self.assertEqual(resposta.dados_publicos["estado"], "atende")
        self.assertEqual(resposta.dados_publicos["parada"], "Biênio")
        self.assertNotIn("Paradas oficiais do itinerário", resposta.texto)
        consulta = resposta.dados_publicos["consulta_transporte"]
        self.assertEqual(consulta["task"], "service_info")
        self.assertEqual(consulta["entities"]["stop"], "bienio")

    def test_atendimento_direto_distingue_servico_de_presenca_no_itinerario(self):
        with patch.object(circulares, "datetime", _datetime_congelado(DOMINGO)):
            ativo = circulares.consultar_circulares(
                linha="8012", destino_ou_ponto="bienio",
                _pergunta="A 8012 passa no Biênio hoje?",
            )
            inativo = circulares.consultar_circulares(
                linha="8084", destino_ou_ponto="bienio",
                _pergunta="A 8084 passa no Biênio hoje?",
            )

        self.assertEqual(ativo.dados_publicos["estado"], "atende")
        self.assertEqual(inativo.dados_publicos["estado"], "sem_servico")
        self.assertIn("inclui a parada", inativo.texto)

    def test_pergunta_de_atendimento_sem_parada_pede_esclarecimento_e_itinerario_permanece(self):
        with patch.object(circulares, "datetime", _datetime_congelado(DOMINGO)):
            sem_contexto = circulares.consultar_circulares(
                _pergunta="Ela passa lá hoje?",
            )
            itinerario = circulares.consultar_circulares(
                linha="8012", _pergunta="Quais são as paradas da 8012?",
            )

        self.assertEqual(sem_contexto.dados_publicos["tipo"], "esclarecimento_transporte")
        self.assertIn("Qual linha e qual parada", sem_contexto.texto)
        texto_itinerario = itinerario.texto if hasattr(itinerario, "texto") else itinerario[0]
        self.assertIn("Paradas oficiais do itinerário", texto_itinerario)


if __name__ == "__main__":
    unittest.main()
