"""Caracterização do motor ativo de transporte antes das extrações da Fase 3A.

As referências abaixo são explícitas: não são geradas por outro planejador nem
pelo próprio renderer. O catálogo é sintético, o relógio é fixo e nenhuma
consulta usa dados operacionais do repositório ou uma sessão HTTP real.
"""

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import patch

from uspapo import ferramentas, gtfs_sptrans, olhovivo
from uspapo.ferramentas import RespostaFerramenta
from uspapo.transporte import consultas_circulares as circulares, planejamento, programacao


AGORA = datetime(2026, 8, 14, 10, 0, tzinfo=circulares.FUSO_SP)
SABADO = datetime(2026, 8, 15, 10, 0, tzinfo=circulares.FUSO_SP)
FONTE_GTFS = "https://www.sptrans.com.br/desenvolvedores/"
BASE_API = "https://api.olhovivo.sptrans.com.br/v2.1"
HEADERS_API = {"User-Agent": "USPapo/1.0 (chatbot de alunos da USP)"}


class _DatetimeFixo(datetime):
    @classmethod
    def now(cls, tz=None):
        return AGORA.replace(tzinfo=None) if tz is None else AGORA.astimezone(tz)


def _catalogo(*, exact_times=1, linha="9001"):
    return {
        "gerado_em": "2026-08-14T13:00:00+00:00",
        "calendarios": {
            "S": {"dias": [1] * 7, "inicio": "20260101", "fim": "20261231"},
        },
        "excecoes_calendario": {},
        "shapes": {
            "shape-teste": [
                {"sequencia": 1, "latitude": -23.55, "longitude": -46.735},
                {"sequencia": 2, "latitude": -23.55, "longitude": -46.730},
                {"sequencia": 3, "latitude": -23.55, "longitude": -46.725},
            ],
        },
        "linhas": {
            linha: [{
                "id": "rota-teste", "linha": linha + "-10", "nome": "Linha Teste",
                "viagens": [{
                    "id": "viagem-teste", "servico": "S", "sentido": "0",
                    "destino": "Destino Teste", "shape_id": "shape-teste",
                    "frequencias": [{
                        "inicio": 9 * 3600, "fim": 11 * 3600,
                        "intervalo": 600, "exact_times": exact_times,
                    }],
                    "paradas": [
                        {"id": "a", "nome": "Embarque Teste", "sequencia": 1,
                         "latitude": -23.55, "longitude": -46.735,
                         "deslocamento": 0, "horario": 9 * 3600},
                        {"id": "b", "nome": "Intermediária Teste", "sequencia": 2,
                         "latitude": -23.55, "longitude": -46.730,
                         "deslocamento": 600, "horario": 9 * 3600 + 600},
                        {"id": "c", "nome": "Parada Teste", "sequencia": 3,
                         "latitude": -23.55, "longitude": -46.725,
                         "deslocamento": 1200, "horario": 9 * 3600 + 1200},
                    ],
                }],
            }],
        },
    }


def _programacao_exata_esperada():
    return {
        "tipo": "programacao", "linha": "9001-10", "parada": "Parada Teste",
        "parada_id": "c", "destino": "Destino Teste", "sentido_gtfs": "0",
        "horarios": ["10:00", "10:10", "10:20"],
        "instantes": [
            "2026-08-14T10:00:00-03:00", "2026-08-14T10:10:00-03:00",
            "2026-08-14T10:20:00-03:00",
        ],
        "estimativas": [], "programacao_incompleta": False,
        "servico_cadastrado": True, "programacao_planoper": False,
    }


def _consulta_esperada(*, task, origin=None, destination=None, line=None,
                       stop=None, duration=False, esclarecimentos=()):
    """Template literal do envelope público, sem chamar o interpretador."""
    return {
        "task": task,
        "entities": {"origin": origin, "destination": destination,
                     "line": line, "stop": stop},
        "period": {"kind": "hoje", "dates": ["2026-08-14"], "label": "hoje"},
        "facets": {
            "duration": duration, "realtime": True, "alternatives": False,
            "confidence": False, "details": False, "more_arrivals": False,
            "service_window": False, "service_at_stop": False,
        },
        "needs_clarification": list(esclarecimentos),
        "interpretation": "tool_arguments",
    }


def _candidato_exato_esperado():
    return {
        "linha": "9001-10", "nome": "Linha Teste", "viagem_id": "viagem-teste",
        "sentido": "Destino Teste", "embarque": "Embarque Teste",
        "embarque_id": "a", "embarque_sequencia": 1,
        "desembarque": "Parada Teste", "desembarque_id": "c",
        "desembarque_sequencia": 3,
        "caminhada_origem_m": 0, "caminhada_destino_m": 0,
        "caminhada_origem_s": 0.0, "caminhada_destino_s": 0.0,
        "viagem_s": 1200, "viagem_min": 20, "passa_metro_butanta": False,
        "modo": "onibus", "espera_programada_s": 0.0,
        "intervalo_programado_s": None, "total_estimado_s": 1200.0,
        "espera_programada_min": 0, "intervalo_programado_min": None,
        "total_estimado_min": 20,
        "espera_source": "scheduled", "espera_confidence": "scheduled",
    }


class _RespostaHTTP:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return deepcopy(self.payload)

    def raise_for_status(self):
        return None


class _SessaoHTTP:
    """Fake estrito; não herda requests.Session e não possui transporte HTTP."""

    def __init__(self, *, previsoes=None, posicoes=None, falha_previsao=False):
        self.chamadas = []
        self.previsoes = previsoes if previsoes is not None else {"hr": "10:00", "ps": []}
        self.posicoes = posicoes if posicoes is not None else {"hr": "10:00", "vs": []}
        self.falha_previsao = falha_previsao

    def post(self, url, **kwargs):
        self.chamadas.append(("POST", url, deepcopy(kwargs)))
        if url != BASE_API + "/Login/Autenticar?token=token-ficticio":
            raise AssertionError("POST não previsto pela fixture")
        return _RespostaHTTP(True)

    def get(self, url, **kwargs):
        self.chamadas.append(("GET", url, deepcopy(kwargs)))
        if url == BASE_API + "/Linha/Buscar":
            return _RespostaHTTP([{
                "cl": 123, "lt": "9001", "tl": 10, "sl": 1,
                "tp": "DESTINO TESTE", "ts": "ORIGEM TESTE",
            }])
        if url == BASE_API + "/Previsao/Linha":
            if self.falha_previsao:
                raise circulares.requests.ConnectionError("falha simulada")
            return _RespostaHTTP(self.previsoes)
        if url == BASE_API + "/Posicao/Linha":
            return _RespostaHTTP(self.posicoes)
        raise AssertionError("GET não previsto pela fixture")


def _chamada_api(metodo, caminho, parametros=None):
    argumentos = {"headers": HEADERS_API, "timeout": 10}
    if parametros is not None:
        argumentos["params"] = parametros
    return metodo, BASE_API + caminho, argumentos


class _CasoTransporte(unittest.TestCase):
    def setUp(self):
        self.catalogo = _catalogo()
        self.contextos = ExitStack()
        self.addCleanup(self.contextos.close)
        self.contextos.enter_context(patch.dict("os.environ", {"SPTRANS_TOKEN": ""}))
        self.contextos.enter_context(patch.object(circulares, "datetime", _DatetimeFixo))
        self.contextos.enter_context(patch.object(programacao, "datetime", _DatetimeFixo))
        self.contextos.enter_context(patch.object(
            circulares, "_catalogo_gtfs", side_effect=lambda: deepcopy(self.catalogo),
        ))
        self.contextos.enter_context(patch.object(
            programacao, "_catalogo_gtfs", side_effect=lambda: deepcopy(self.catalogo),
        ))
        self.contextos.enter_context(patch.object(
            planejamento, "_catalogo_gtfs", side_effect=lambda: deepcopy(self.catalogo),
        ))
        self.contextos.enter_context(patch.object(ferramentas, "_CACHE", {}))
        self.monotonic = self.contextos.enter_context(patch.object(
            ferramentas.time, "monotonic", return_value=1000.0,
        ))
        self.contextos.enter_context(patch.object(
            circulares.requests, "Session",
            side_effect=AssertionError("Este caso não autorizou uma sessão HTTP"),
        ))

    def assertResposta(self, resposta, texto, fontes, dados):
        self.assertIsInstance(resposta, RespostaFerramenta)
        self.assertEqual(tuple(resposta), (texto, fontes))
        self.assertEqual(resposta.dados_publicos, dados)
        self.assertEqual(resposta.resultado_transporte.como_publico(), {
            "query": dados["consulta_transporte"], "kind": dados["tipo"], "facts": dados,
        })

    def geometria_de_planejamento(self, caminhada_direta_m):
        """Distâncias controladas isolam a decisão temporal, sem mock de ranking."""
        origem, destino = (1.0, 1.0), (2.0, 2.0)

        def coordenada(nome):
            return origem if nome == "Origem Teste" else destino

        def distancia(parada, referencia):
            if "id" not in parada:
                return caminhada_direta_m / 1.15
            alvo = "a" if referencia == origem else "c"
            return 0.0 if parada["id"] == alvo else 1000.0

        self.contextos.enter_context(patch.object(
            planejamento, "_coordenada_ponto", side_effect=coordenada,
        ))
        self.contextos.enter_context(patch.object(
            planejamento, "_distancia_parada_gtfs", side_effect=distancia,
        ))

    def usar_sessao(self, sessao):
        self.contextos.enter_context(patch.object(
            circulares.requests, "Session", return_value=sessao,
        ))


class TestBindingsTransporteCaracterizacao(unittest.TestCase):
    def test_alias_historico_e_dez_bindings_efetivos_apos_import(self):
        from uspapo.ferramentas import circulares as historico

        self.assertIs(historico, circulares)
        bindings = {
            "_catalogo_gtfs": gtfs_sptrans.catalogo,
            "_mesmo_nome": gtfs_sptrans.mesmo_nome,
            "_servico_ativo": gtfs_sptrans.servico_ativo,
            "_distancia_parada_gtfs": gtfs_sptrans.distancia_m,
            "_autenticar_sptrans": olhovivo._autenticar,
            "_get_json": olhovivo._get_json,
            "_linhas_sptrans": olhovivo._linhas,
            "_previsoes_linha": olhovivo._previsoes_linha,
            "_posicoes_linha": olhovivo._posicoes_linha,
            "_destino_linha_sptrans": olhovivo.destino_da_linha,
        }
        for nome, funcao in bindings.items():
            with self.subTest(nome=nome):
                self.assertIs(getattr(circulares, nome), funcao)


class TestT1ContratosPublicos(_CasoTransporte):
    def test_chegada_programada_preserva_texto_fontes_fatos_e_envelope(self):
        resposta = circulares.consultar_circulares(
            "9001", "Parada Teste",
            _pergunta="Quando chega o 9001 na Parada Teste hoje?",
        )
        dados = {
            "tipo": "chegada_onibus", "facetas": {"tempo_real": True, "explicacao": False},
            "linha": "9001-10", "parada": "Parada Teste", "status_api": "nao_consultada",
            "sentidos": [{
                "linha": "9001-10", "sentido": "Destino Teste", "parada": "Parada Teste",
                "base_previsao": "horario_programado", "horarios": ["10:00", "10:10", "10:20"],
                "chegadas": [
                    {"horario": "10:00", "source": "scheduled", "confidence": "scheduled"},
                    {"horario": "10:10", "source": "scheduled", "confidence": "scheduled"},
                    {"horario": "10:20", "source": "scheduled", "confidence": "scheduled"},
                ],
            }],
            "fatos_obrigatorios": ["9001-10", "Parada Teste"],
            "horarios_obrigatorios": ["10:00"],
            "consulta_transporte": _consulta_esperada(task="arrival", line="9001", stop="Parada Teste"),
        }
        self.assertResposta(resposta, (
            "Pela programação, as próximas passagens do **9001-10, sentido Destino Teste** "
            "na parada **Parada Teste** são **10:00, 10:10, 10:20**.\n\n"
            "É uma estimativa baseada na programação da linha, não uma confirmação em tempo real."
        ), [FONTE_GTFS], dados)

    def test_esclarecimento_preserva_formato_publico(self):
        resposta = circulares.consultar_circulares(
            "9001", _pergunta="Quando chega o 9001 hoje?",
        )
        self.assertResposta(resposta,
            "Em qual parada você quer saber a chegada da linha **9001**?", [], {
                "tipo": "esclarecimento_transporte", "linha": "9001",
                "campo_necessario": "parada", "fatos_obrigatorios": ["9001"],
                "consulta_transporte": _consulta_esperada(
                    task="arrival", line="9001", esclarecimentos=("stop",),
                ),
            },
        )

    def test_sem_servico_preserva_estado_observavel(self):
        self.catalogo["calendarios"]["S"]["dias"] = [0] * 7
        resposta = circulares.consultar_circulares(
            "9001", "Parada Teste",
            _pergunta="Quando chega o 9001 na Parada Teste hoje?",
        )
        self.assertResposta(resposta, (
            "A linha **9001-10** não tem serviço programado na parada **Parada Teste** hoje."
        ), [FONTE_GTFS], {
            "tipo": "chegada_onibus", "facetas": {"tempo_real": True, "explicacao": False},
            "linha": "9001-10", "parada": "Parada Teste", "status_api": "nao_consultada",
            "sentidos": [{
                "linha": "9001-10", "sentido": "Destino Teste", "parada": "Parada Teste",
                "base_previsao": "indisponivel", "horarios": [],
            }],
            "fatos_obrigatorios": ["9001-10", "Parada Teste"],
            "status_operacao": "sem_servico", "periodo": "hoje",
            "frases_obrigatorias": ["não tem serviço programado"],
            "consulta_transporte": _consulta_esperada(task="arrival", line="9001", stop="Parada Teste"),
        })

    def test_rota_de_onibus_preserva_componentes_texto_e_fatos(self):
        plano = {"origem": "Origem Teste", "destino": "Destino Teste",
                 "melhor": _candidato_exato_esperado(), "alternativas": []}
        with patch.object(circulares, "_planejar_trajeto_gtfs", return_value=plano) as planejar:
            resposta = circulares.consultar_circulares(
                origem="Origem Teste", destino_ou_ponto="Destino Teste",
                _pergunta="Quanto tempo de Origem Teste para Destino Teste hoje?",
            )
        planejar.assert_called_once_with("Origem Teste", "Destino Teste", AGORA, None, None)
        self.assertResposta(resposta, (
            "Pela programação, reserve **cerca de 20 minutos no total**, incluindo a espera e as caminhadas.\n\n"
            "Saindo do **Origem Teste**, pegue o **9001-10, sentido Destino Teste**, "
            "no ponto **Embarque Teste**, e desça em **Parada Teste**. "
            "O destino fica praticamente em frente.\n\n"
            "Não há previsão exata de chegada para esse ponto neste momento."
        ), [FONTE_GTFS], {
            "tipo": "trajeto_onibus",
            "facetas": {"localizacao": False, "duracao": True, "tempo_real": True,
                        "alternativas": False, "explicacao": False},
            "origem": {"nome": "Origem Teste", "localizacao": "na região da Cidade Universitária"},
            "destino": {"nome": "Destino Teste", "localizacao": "na região da Cidade Universitária"},
            "melhor_opcao": {"linha": "9001-10", "sentido": "Destino Teste",
                             "embarque": "Embarque Teste", "desembarque": "Parada Teste",
                             "caminhada_origem_m": 0, "caminhada_destino_m": 0},
            "tempo": {"total_esperado_min": 20, "total_minimo_min": 20, "total_maximo_min": 20,
                      "viagem_onibus_min": "20", "caminhada_total_min": "0",
                      "espera": {"base": "programacao_exata", "source": "scheduled",
                                 "confidence": "scheduled", "esperada_min": "0",
                                 "minima_min": "0", "maxima_min": "0"}},
            "status_api": "nao_consultada", "fatos_obrigatorios": ["9001-10", "Parada Teste"],
            "numeros_obrigatorios": [20],
            "consulta_transporte": _consulta_esperada(
                task="route", origin="Origem Teste", destination="Destino Teste", duration=True,
            ),
        })

    def test_caminhada_preserva_contrato_manual_atual(self):
        plano = {"origem": "Origem Teste", "destino": "Destino Teste",
                 "melhor": {"modo": "a_pe", "distancia_aproximada_m": 1440,
                            "total_estimado_min": 18}, "alternativas": []}
        with patch.object(circulares, "_planejar_trajeto_gtfs", return_value=plano):
            resposta = circulares.consultar_circulares(
                origem="Origem Teste", destino_ou_ponto="Destino Teste",
                _pergunta="Quanto tempo de Origem Teste para Destino Teste hoje?",
            )
        self.assertResposta(resposta, (
            "De **Origem Teste** até **Destino Teste**, a opção estimada mais rápida é ir a pé: "
            "cerca de **18 minutos** (1440 m em uma aproximação, não em uma rota de pedestres)."
        ), [FONTE_GTFS], {
            "tipo": "trajeto_a_pe",
            "facetas": {"localizacao": False, "duracao": True, "tempo_real": True,
                        "alternativas": False, "explicacao": False},
            "origem": "Origem Teste", "destino": "Destino Teste",
            "melhor_opcao": {"modo": "a_pe", "distancia_m": 1440, "tempo_total_min": 18},
            "consulta_transporte": _consulta_esperada(
                task="route", origin="Origem Teste", destination="Destino Teste", duration=True,
            ),
        })


class TestT2Programacao(_CasoTransporte):
    def test_grade_exata_completa(self):
        self.assertEqual(circulares._programacao_gtfs(
            "9001", "Parada Teste", AGORA, datas_permitidas=(AGORA.date(),),
        ), _programacao_exata_esperada())

    def test_frequencia_preserva_slots_ancorados_e_janela_separada(self):
        self.catalogo = _catalogo(exact_times=0)
        esperado = _programacao_exata_esperada()
        esperado.update({
            "horarios": [], "instantes": [],
            "estimativas": [
                {"horario": horario, "instante": instante, "intervalo_min": 10,
                 "source": "scheduled_estimate", "confidence": "scheduled",
                 "origem_programacao": "gtfs_frequencia"}
                for horario, instante in (
                    ("10:10", "2026-08-14T10:10:00-03:00"),
                    ("10:20", "2026-08-14T10:20:00-03:00"),
                    ("10:30", "2026-08-14T10:30:00-03:00"),
                )
            ],
            "faixas": [{
                "inicio": "2026-08-14T10:00:00-03:00", "fim": "2026-08-14T11:20:00-03:00",
                "inicio_texto": "10:00", "fim_texto": "11:20", "intervalo_min": 10,
                "ativa_agora": True,
                "proxima_janela_inicio": "2026-08-14T10:00:00-03:00",
                "proxima_janela_fim": "2026-08-14T10:10:00-03:00",
                "proxima_janela_inicio_texto": "10:00", "proxima_janela_fim_texto": "10:10",
                "proxima_referencia": "2026-08-14T10:05:00-03:00",
                "proxima_referencia_texto": "10:05", "espera_tipica_min": 5,
                "espera_ate_referencia_min": 5, "espera_maxima_min": 10,
            }],
        })
        self.assertEqual(circulares._programacao_gtfs(
            "9001", "Parada Teste", AGORA, datas_permitidas=(AGORA.date(),),
        ), esperado)

    def test_planoper_substitui_grade_incompleta_sem_virar_eta(self):
        self.catalogo = _catalogo(linha="8012")
        self.catalogo["linhas"]["8012"][0]["planoper"] = {
            "itinerarios_id": {"0": {"itiIdIda": "shape-teste", "itiIdVolta": "outra"}},
            "partidas_ida": [{"tipoDia": 0, "horariosProgramados": [
                {"horario": "09:50", "veiculoAcessivel": True},
                {"horario": "10:10", "veiculoAcessivel": False},
                {"horario": "10:30"},
            ]}],
        }
        esperado = _programacao_exata_esperada()
        esperado.update({
            "linha": "8012-10", "horarios": [], "instantes": [], "programacao_planoper": True,
            "estimativas": [
                {"horario": horario, "instante": instante, "source": "scheduled_estimate",
                 "confidence": "scheduled", "origem_programacao": "planoper", "acessivel": acessivel}
                for horario, instante, acessivel in (
                    ("10:10", "2026-08-15T10:10:00-03:00", True),
                    ("10:30", "2026-08-15T10:30:00-03:00", False),
                    ("10:50", "2026-08-15T10:50:00-03:00", None),
                )
            ],
        })
        self.assertEqual(circulares._programacao_gtfs(
            "8012", "Parada Teste", SABADO, datas_permitidas=(SABADO.date(),),
        ), esperado)

    def test_ausencia_de_servico_e_fim_de_grade_tem_resultados_distintos(self):
        for servico_ativo, tipo in ((False, "sem_servico"), (True, "sem_passagem")):
            with self.subTest(tipo=tipo):
                self.catalogo = _catalogo()
                self.catalogo["calendarios"]["S"]["dias"] = [int(servico_ativo)] * 7
                viagem = self.catalogo["linhas"]["9001"][0]["viagens"][0]
                viagem["frequencias"] = [{
                    "inicio": 7 * 3600, "fim": 8 * 3600, "intervalo": 600, "exact_times": 1,
                }]
                self.assertEqual(circulares._programacao_gtfs(
                    "9001", "Parada Teste", AGORA, datas_permitidas=(AGORA.date(),),
                ), {
                    "tipo": tipo, "linha": "9001-10", "parada": "Parada Teste",
                    "parada_id": "c", "destino": "Destino Teste", "sentido_gtfs": "0",
                    "horarios": [], "instantes": [], "faixas": [],
                    "programacao_incompleta": False, "servico_cadastrado": servico_ativo, "aviso": "",
                })


class TestT3Planejamento(_CasoTransporte):
    def test_margem_atual_de_dois_minutos_e_onibus_explicito(self):
        self.geometria_de_planejamento(1440)
        esperado = {
            "origem": "Origem Teste", "destino": "Destino Teste", "horario_referencia": "10:00",
            "caminhada_direta_m": 1440, "caminhada_direta_min": 18,
            "comparacao_caminhada_aproximada": False,
            "melhor": _candidato_exato_esperado(), "alternativas": [],
        }
        self.assertEqual(circulares._planejar_trajeto_gtfs(
            "Origem Teste", "Destino Teste", AGORA,
        ), esperado)

        self.geometria_de_planejamento(1360)
        esperado.update({"caminhada_direta_m": 1360, "caminhada_direta_min": 17})
        esperado["melhor"] = {"modo": "a_pe", "distancia_aproximada_m": 1360, "total_estimado_min": 17}
        esperado["alternativas"] = [_candidato_exato_esperado()]
        self.assertEqual(circulares._planejar_trajeto_gtfs(
            "Origem Teste", "Destino Teste", AGORA,
        ), esperado)

        esperado["melhor"] = _candidato_exato_esperado()
        esperado["alternativas"] = []
        esperado["alternativas_sem_horario"] = []
        self.assertEqual(circulares._planejar_trajeto_gtfs(
            "Origem Teste", "Destino Teste", AGORA, "onibus",
        ), esperado)

    def test_ranking_preserva_identidade_da_viagem_e_ordem_das_alternativas(self):
        self.geometria_de_planejamento(8000)
        segunda = deepcopy(self.catalogo["linhas"]["9001"][0])
        segunda.update({"id": "rota-segunda", "linha": "9002-10"})
        segunda["viagens"][0]["id"] = "viagem-segunda"
        segunda["viagens"][0]["paradas"][2]["deslocamento"] = 600
        self.catalogo["linhas"]["9002"] = [segunda]
        melhor = _candidato_exato_esperado()
        melhor.update({"linha": "9002-10", "viagem_id": "viagem-segunda", "viagem_s": 600,
                       "viagem_min": 10, "total_estimado_s": 600.0, "total_estimado_min": 10})
        self.assertEqual(circulares._planejar_trajeto_gtfs(
            "Origem Teste", "Destino Teste", AGORA, "onibus",
        ), {
            "origem": "Origem Teste", "destino": "Destino Teste", "horario_referencia": "10:00",
            "caminhada_direta_m": 8000, "caminhada_direta_min": 100,
            "comparacao_caminhada_aproximada": False,
            "melhor": melhor, "alternativas": [_candidato_exato_esperado()],
            "alternativas_sem_horario": [],
        })

    def test_sem_horario_preserva_opcoes_sem_declarar_ranking_temporal(self):
        self.geometria_de_planejamento(1440)
        viagem = self.catalogo["linhas"]["9001"][0]["viagens"][0]
        viagem["frequencias"] = []
        segunda = deepcopy(self.catalogo["linhas"]["9001"][0])
        segunda.update({"id": "rota-segunda", "linha": "9002-10"})
        self.catalogo["linhas"]["9002"] = [segunda]
        candidato = _candidato_exato_esperado()
        candidato.pop("espera_source")
        candidato.pop("espera_confidence")
        candidato.update({
            "modo": "onibus_sem_horario", "espera_programada_s": None,
            "espera_programada_min": None, "total_estimado_s": None,
            "total_estimado_min": None, "ranking_s": 1200.0,
        })
        alternativa = {**candidato, "linha": "9002-10"}
        self.assertEqual(circulares._planejar_trajeto_gtfs(
            "Origem Teste", "Destino Teste", AGORA, "onibus",
        ), {
            "origem": "Origem Teste", "destino": "Destino Teste", "horario_referencia": "10:00",
            "caminhada_direta_m": 1440, "caminhada_direta_min": 18,
            "comparacao_caminhada_aproximada": False,
            "melhor": candidato, "alternativas": [alternativa],
            "ranking_temporal": "indeterminado", "aviso": "",
        })


class TestT4PrevisaoECache(_CasoTransporte):
    def consultar(self):
        return circulares._obter_previsao_sptrans(
            "9001", "Parada Teste", "token-ficticio", sentido_esperado="Destino Teste",
        )

    def test_http_ordenado_argumentos_cache_e_ttls_efetivos(self):
        veiculo = {"p": "veiculo-1", "t": "10:04", "ta": "10:00", "a": True,
                   "py": -23.55, "px": -46.73}
        sessao = _SessaoHTTP(previsoes={"hr": "10:00", "ps": [{
            "cp": "c", "np": "Parada Teste", "ed": "Endereço Teste", "vs": [veiculo],
        }]})
        self.usar_sessao(sessao)
        primeiro = self.consultar()
        segundo = self.consultar()
        self.assertEqual(primeiro, segundo)
        login = _chamada_api("POST", "/Login/Autenticar?token=token-ficticio")
        linhas = _chamada_api("GET", "/Linha/Buscar", {"termosBusca": "9001"})
        previsoes = _chamada_api("GET", "/Previsao/Linha", {"codigoLinha": 123})
        self.assertEqual(sessao.chamadas, [login, linhas, previsoes, login])
        self.assertEqual(set(ferramentas._CACHE), {
            ("circulares", "linhas", "9001"), ("circulares", "previsoes-linha", 123),
        })
        self.assertEqual(primeiro["veiculos"], [{
            **veiculo, "source": "live", "confidence": "high",
            "confidence_reasons": ["eta_valido", "gps_presente", "veiculo_identificado", "ta_muito_recente"],
        }])
        self.assertEqual(primeiro["horarios_programados"], ["10:10", "10:20", "10:30"])
        self.monotonic.return_value = 1021.0
        self.consultar()
        self.assertEqual(sessao.chamadas, [login, linhas, previsoes, login, login, previsoes])
        self.monotonic.return_value = 87401.0
        self.consultar()
        self.assertEqual(sessao.chamadas[-3:], [login, linhas, previsoes])

    def test_cp_sem_identidade_nao_usa_eta_por_nome_ou_proximidade(self):
        sessao = _SessaoHTTP(previsoes={"hr": "10:00", "ps": [{
            "cp": "outra-plataforma", "np": "Parada Teste", "py": -23.55, "px": -46.725,
            "vs": [{"p": "errado", "t": "10:04", "ta": "10:00"}],
        }]})
        self.usar_sessao(sessao)
        esperado = _programacao_exata_esperada()
        esperado.update({
            "hr": "10:00", "veiculos_ativos": 0, "api_consultada": True,
            "aviso_api": "A API Olho Vivo não publicou uma parada com associação GTFS inequívoca "
                         "para esse ponto e sentido; nenhum ETA foi usado.",
        })
        self.assertEqual(self.consultar(), esperado)
        self.assertEqual(sessao.chamadas, [
            _chamada_api("POST", "/Login/Autenticar?token=token-ficticio"),
            _chamada_api("GET", "/Linha/Buscar", {"termosBusca": "9001"}),
            _chamada_api("GET", "/Previsao/Linha", {"codigoLinha": 123}),
            _chamada_api("GET", "/Posicao/Linha", {"codigoLinha": 123}),
        ])

    def test_gps_real_sobre_shape_sintetico_gera_eta_com_confianca_media(self):
        sessao = _SessaoHTTP(posicoes={"hr": "10:00", "vs": [{
            "p": "gps-1", "ta": "10:00", "py": -23.55, "px": -46.735, "a": True,
        }]})
        self.usar_sessao(sessao)
        resultado = self.consultar()
        self.assertEqual(resultado["tipo"], "previsao")
        self.assertEqual(resultado["parada_id_gtfs"], "c")
        self.assertEqual(resultado["destino"], "Destino Teste")
        self.assertEqual(resultado["veiculos"], [{
            "p": "gps-1", "t": "10:20", "ta": "10:00", "py": -23.55, "px": -46.735, "a": True,
            "source": "live_gps_estimate", "confidence": "medium",
            "confidence_reasons": ["eta_valido", "gps_presente", "veiculo_identificado",
                                   "eta_derivado_da_posicao_gps", "gps_recente"],
        }])
        self.assertEqual(sessao.chamadas, [
            _chamada_api("POST", "/Login/Autenticar?token=token-ficticio"),
            _chamada_api("GET", "/Linha/Buscar", {"termosBusca": "9001"}),
            _chamada_api("GET", "/Previsao/Linha", {"codigoLinha": 123}),
            _chamada_api("GET", "/Posicao/Linha", {"codigoLinha": 123}),
        ])

    def test_falha_http_preserva_programacao_e_sinaliza_falha_distinta(self):
        sessao = _SessaoHTTP(falha_previsao=True)
        self.usar_sessao(sessao)
        esperado = _programacao_exata_esperada()
        esperado.update({"aviso_api": "A API Olho Vivo não respondeu agora.",
                         "api_consultada": True, "falha_api": True})
        self.assertEqual(self.consultar(), esperado)
        self.assertEqual(sessao.chamadas, [
            _chamada_api("POST", "/Login/Autenticar?token=token-ficticio"),
            _chamada_api("GET", "/Linha/Buscar", {"termosBusca": "9001"}),
            _chamada_api("GET", "/Previsao/Linha", {"codigoLinha": 123}),
        ])
