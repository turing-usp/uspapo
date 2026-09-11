"""Caracterização T5/T6/T7: roteamento, conversa e composição dos entrypoints.

Os provedores usam respostas locais e a telemetria é interceptada. Os imports
de app/app_stub só acontecem dentro do teste, após instalar os SDKs falsos.
Executar pela barreira offline de scripts/testar_offline.py.
"""

import copy
import importlib.util
import json
import os
import sys
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from uspapo import ferramentas, gtfs_sptrans, roteamento
from uspapo.contexto import Orcamento, estimar_tokens
from uspapo.conversa import executar_conversa
from uspapo.ferramentas import Registro, RespostaFerramenta
from uspapo.provedores import Provedor
from uspapo.saida import agregar, gerar_sse
from uspapo.test_naturalizador_transporte import (
    FALLBACK,
    PUBLIC_VIEW,
    _completion,
    _Completions,
)
from uspapo.test_preconsulta_conversa import chunk_de_texto


def provedor_falso(nome, respostas, modelo="modelo-de-teste"):
    completions = _Completions(respostas)
    cliente = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return Provedor(
        nome, {"model": modelo, "max_tokens_contexto": 16000}, cliente
    ), completions


def chamada_inline(*consultas):
    chamadas = [
        {"name": "buscar_documentos", "arguments": {"consulta": consulta}}
        for consulta in consultas
    ]
    return chunk_de_texto(
        "<tool_call>" + json.dumps(chamadas) + "</tool_call>"
    )


class TestT5PreRoteamento(unittest.TestCase):
    def setUp(self):
        self.registro = Registro()
        self.fatos = {"tipo": "fixture-transporte"}
        self.circular = Mock(return_value=RespostaFerramenta(
            "Resposta factual.", ["https://transporte.invalid/"], self.fatos
        ))
        self.registro.ferramenta(
            nome="consultar_circulares", descricao="Fixture local",
            parametros={"type": "object", "properties": {}},
        )(self.circular)

    def test_transporte_precede_titulo_e_preserva_envelope_publico(self):
        casos = [
            ("Como vou do Metrô Butantã ao IME?", {
                "linha": "", "origem": "metro_butanta", "destino_ou_ponto": "ime",
            }),
            ("Quando chega o 8084 no ponto do Biênio?", {
                "linha": "8084", "destino_ou_ponto": "bienio",
            }),
        ]
        for pergunta, argumentos in casos:
            with self.subTest(pergunta=pergunta):
                self.circular.reset_mock()
                with patch("uspapo.roteamento.pagina_por_titulo") as titulo:
                    resultado = roteamento.preconsultar(self.registro, pergunta)
                titulo.assert_not_called()
                self.circular.assert_called_once_with(
                    detalhes=False, _pergunta=pergunta, **argumentos
                )
                self.assertEqual(resultado[:3], (
                    "Resposta factual.", ["https://transporte.invalid/"],
                    "consultar_circulares",
                ))
                self.assertIs(resultado[3], self.fatos)

    def test_falha_de_transporte_devolve_none_sem_tentar_titulo(self):
        self.circular.side_effect = RuntimeError("fixture indisponível")
        for pergunta in (
            "Como vou do Metrô Butantã ao IME?",
            "Quando chega o 8084 no ponto do Biênio?",
        ):
            with self.subTest(pergunta=pergunta):
                with patch("uspapo.roteamento.pagina_por_titulo") as titulo:
                    resultado = roteamento.preconsultar(self.registro, pergunta)
                self.assertIsNone(resultado)
                titulo.assert_not_called()

    def test_titulo_preconsultado_limita_texto_e_mantem_fonte_separada(self):
        pagina = {
            "titulo": "Projeto de teste", "url": "https://documento.invalid/",
            "texto": "A" * 4500 + "TRECHO EXCEDENTE",
        }
        with patch("uspapo.roteamento.pagina_por_titulo", return_value=pagina):
            resultado = roteamento.preconsultar(Registro(), "Explique o projeto")
        self.assertEqual(resultado, (
            "Fonte oficial encontrada por correspondência exata de título:\n\n"
            "### Projeto de teste\n" + "A" * 4500,
            ["https://documento.invalid/"], "buscar_documentos", None,
        ))

    def test_titulo_ambiguo_ou_ausente_deixa_escolha_para_llm(self):
        candidatos = [
            {"titulo": "Memórias", "url": "https://a.invalid/", "arquivo": "a.json"},
            {"titulo": "Memórias", "url": "https://b.invalid/", "arquivo": "b.json"},
        ]
        for catalogo in ({}, {"memorias": candidatos}):
            with self.subTest(catalogo=catalogo):
                with patch("uspapo.documentos_locais.catalogo_titulos", return_value=catalogo):
                    self.assertIsNone(roteamento.preconsultar(
                        self.registro, "O que é Memórias?"
                    ))
        self.circular.assert_not_called()

    def test_historico_tem_janela_de_cinco_e_nao_resolve_parada_ambigua(self):
        associado = {"pergunta": "Quais ônibus passam no Biênio?", "resposta": "8084-10"}
        neutros = [{"pergunta": f"Tema {n}", "resposta": "Outro assunto"} for n in range(5)]
        ambiguo = {
            "pergunta": "O 8084 vai do Metrô Butantã ao Biênio?",
            "resposta": "Sim, nesse sentido.",
        }
        pergunta = "Quando chega o próximo 8084 hoje?"
        for historico in ([associado] + neutros, [associado, ambiguo]):
            with self.subTest(historico=historico):
                self.circular.reset_mock()
                roteamento.preconsultar(self.registro, pergunta, historico)
                self.circular.assert_called_once_with(
                    detalhes=False, _pergunta=pergunta, _historico=historico[-5:],
                    linha="8084", destino_ou_ponto="",
                )

    def test_continuacao_de_esclarecimento_preserva_pergunta_operacional(self):
        anterior = "Quando chega o próximo 8084 hoje?"
        historico = [{"pergunta": anterior, "resposta": "Em qual parada você quer consultar?"}]
        roteamento.preconsultar(self.registro, "No Biênio", historico)
        self.circular.assert_called_once_with(
            detalhes=False,
            _pergunta=anterior + "\nParada informada na continuação: No Biênio",
            _historico=historico, linha="8084", destino_ou_ponto="bienio",
        )


class TestT6Conversa(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch(
            "uspapo.conversa.saude.ordenar", side_effect=lambda nomes: list(nomes)
        ))
        self.patches.enter_context(patch("uspapo.conversa.saude.espera_restante", return_value=0))
        self.sucesso = self.patches.enter_context(patch("uspapo.conversa.saude.marcar_sucesso"))
        self.patches.enter_context(patch("uspapo.conversa.saude.marcar_falha"))
        self.registrar = self.patches.enter_context(patch("uspapo.analytics.registrar"))

    def executar(self, provedores, registro=None):
        registro = registro if registro is not None else Registro()
        return list(executar_conversa(
            provedores, registro, Orcamento(registro, max_tokens=16000, reserva=4000),
            "Pergunta de contrato.", [], user_id="fixture-usuario", session_id="fixture-conversa",
        ))

    def test_none_chega_ao_llm_e_preserva_eventos_raciocinio_uso_e_saida(self):
        usage = SimpleNamespace(
            choices=[], usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7)
        )
        provedor, sdk = provedor_falso("primario", [[
            chunk_de_texto("<think>Verificando.</think>Resposta final."), usage,
        ]])
        with patch("uspapo.conversa.preconsultar", return_value=None):
            eventos = self.executar([provedor])
        self.assertEqual(eventos, [
            {"tipo": "provedor", "nome": "primario", "indice": 0},
            {"tipo": "pensando", "delta": "Verificando."},
            {"tipo": "texto", "delta": "Resposta final."},
            {"tipo": "fontes", "urls": []}, {"tipo": "fim"},
        ])
        self.assertEqual(len(sdk.chamadas), 1)
        self.assertTrue(sdk.chamadas[0]["stream"])
        self.assertEqual(sdk.chamadas[0]["stream_options"], {"include_usage": True})
        self.assertEqual(self.registrar.call_args.kwargs["total_tokens"], 18)
        self.assertEqual(agregar(iter(eventos)), ({"resposta": "Resposta final.", "fontes": []}, 200))
        sse = list(gerar_sse(iter(eventos)))
        self.assertEqual(sse[0], ": ok\n\n")
        self.assertEqual(sse[1:], [
            f"data: {json.dumps(evento, ensure_ascii=False)}\n\n" for evento in eventos
        ])

    def test_preconsulta_deterministica_emite_fontes_sem_chamar_sdk(self):
        provedor, sdk = provedor_falso("primario", [])
        preconsulta = (
            "Resposta factual.", ["https://z.invalid/", "https://a.invalid/", "https://z.invalid/"],
            "consultar_circulares", None,
        )
        with patch("uspapo.conversa.preconsultar", return_value=preconsulta):
            eventos = self.executar([provedor])
        self.assertEqual(eventos, [
            {"tipo": "provedor", "nome": "primario", "indice": 0},
            {"tipo": "ferramenta", "estado": "inicio", "indice": -1, "nome": "consultar_circulares"},
            {"tipo": "ferramenta", "estado": "fim", "indice": -1, "nome": "consultar_circulares", "args": {}, "resultados": 3},
            {"tipo": "texto", "delta": "Resposta factual."},
            {"tipo": "fontes", "urls": ["https://a.invalid/", "https://z.invalid/"]},
            {"tipo": "fim"},
        ])
        self.assertEqual(sdk.chamadas, [])
        self.sucesso.assert_not_called()
        self.assertEqual(self.registrar.call_args.kwargs["provedor"], "backend-deterministico")
        self.assertEqual(self.registrar.call_args.kwargs["total_tokens"], 0)

    def test_naturalizador_rejeita_antes_de_emitir_e_atribui_uso_ao_respondente(self):
        texto = "Conte com cerca de 25 minutos no total. Pegue o 8082-10."
        primeiro, sdk1 = provedor_falso("oss-chave-1", [
            _completion("Pegue o 9999-10.", prompt_tokens=10, completion_tokens=5),
        ], "openai/gpt-oss-120b")
        segundo, sdk2 = provedor_falso("oss-chave-2", [
            _completion(texto, prompt_tokens=20, completion_tokens=7),
        ], "openai/gpt-oss-120b")
        with patch("uspapo.conversa.preconsultar", return_value=(
            FALLBACK, ["https://transporte.invalid/"], "consultar_circulares", copy.deepcopy(PUBLIC_VIEW),
        )):
            eventos = self.executar([primeiro, segundo])
        self.assertEqual([e for e in eventos if e["tipo"] == "texto"], [{"tipo": "texto", "delta": texto}])
        self.assertEqual([e["nome"] for e in eventos if e["tipo"] == "provedor"], ["oss-chave-1"])
        for sdk in (sdk1, sdk2):
            self.assertEqual(len(sdk.chamadas), 1)
            self.assertFalse(sdk.chamadas[0]["stream"])
            self.assertNotIn("tools", sdk.chamadas[0])
            self.assertTrue(sdk.chamadas[0]["response_format"]["json_schema"]["strict"])
        self.sucesso.assert_called_once_with("oss-chave-2")
        log = self.registrar.call_args.kwargs
        self.assertEqual((log["provedor"], log["prompt_tokens"], log["completion_tokens"]), ("oss-chave-2", 30, 12))
        self.assertEqual([t["resultado"] for t in log["metadata"]["naturalizador_tentativas"]], ["rejeitada", "aceita"])
        self.assertEqual(eventos[-2:], [
            {"tipo": "fontes", "urls": ["https://transporte.invalid/"]}, {"tipo": "fim"},
        ])

    def test_naturalizacao_rejeitada_entrega_fallback_mas_conta_tokens_medidos(self):
        provedor, _ = provedor_falso("oss", [
            _completion("Pegue o 9999-10.", prompt_tokens=10, completion_tokens=5),
        ], "openai/gpt-oss-120b")
        with patch("uspapo.conversa.preconsultar", return_value=(
            FALLBACK, [], "consultar_circulares", copy.deepcopy(PUBLIC_VIEW),
        )):
            eventos = self.executar([provedor])
        self.assertEqual([e["delta"] for e in eventos if e["tipo"] == "texto"], [FALLBACK])
        log = self.registrar.call_args.kwargs
        self.assertEqual((log["provedor"], log["total_tokens"]), ("oss", 15))
        self.assertEqual(log["metadata"]["naturalizador_tentativas"][0]["resultado"], "rejeitada")

    def test_fallback_reutiliza_memo_mas_descarta_fontes_da_tentativa_falha(self):
        registro = Registro()
        consultas = []

        @registro.ferramenta(
            nome="buscar_documentos", descricao="Fixture local",
            parametros={"type": "object", "properties": {"consulta": {"type": "string"}}},
        )
        def buscar_documentos(consulta):
            consultas.append(consulta)
            return f"Documento {consulta}.", [f"https://{consulta}.invalid/"]

        primeiro, sdk1 = provedor_falso("primario", [
            [chamada_inline("comum", "descartada")], RuntimeError("fixture indisponível"),
        ])
        segundo, sdk2 = provedor_falso("secundario", [
            [chamada_inline("comum")], [chunk_de_texto("Resposta recuperada.")],
        ])
        with patch("uspapo.conversa.preconsultar", return_value=None):
            eventos = self.executar([primeiro, segundo], registro)
        self.assertEqual(consultas, ["comum", "descartada"])
        self.assertEqual((len(sdk1.chamadas), len(sdk2.chamadas)), (2, 2))
        self.assertEqual([e["nome"] for e in eventos if e["tipo"] == "provedor"], ["primario", "secundario"])
        self.assertEqual([(e["estado"], e["indice"]) for e in eventos if e["tipo"] == "ferramenta"], [
            ("inicio", 0), ("inicio", 1), ("fim", 0), ("fim", 1), ("inicio", 0), ("fim", 0),
        ])
        self.assertEqual(eventos[-3:], [
            {"tipo": "texto", "delta": "Resposta recuperada."},
            {"tipo": "fontes", "urls": ["https://comum.invalid/"]}, {"tipo": "fim"},
        ])

    def test_erro_apos_texto_nao_tenta_proximo_e_json_mantem_resposta_parcial(self):
        def stream_interrompido():
            yield chunk_de_texto("Trecho entregue.")
            raise RuntimeError("fixture interrompida")

        primeiro, _ = provedor_falso("primario", [stream_interrompido()])
        segundo, sdk2 = provedor_falso("secundario", [[chunk_de_texto("Não executar.")]])
        with patch("uspapo.conversa.preconsultar", return_value=None):
            eventos = self.executar([primeiro, segundo])
        self.assertEqual(eventos, [
            {"tipo": "provedor", "nome": "primario", "indice": 0},
            {"tipo": "texto", "delta": "Trecho entregue."},
            {"tipo": "erro", "mensagem": "A resposta parou no meio do caminho. Pode mandar a pergunta de novo?"},
            {"tipo": "fim"},
        ])
        self.assertEqual(sdk2.chamadas, [])
        self.assertEqual(agregar(iter(eventos)), ({"resposta": "Trecho entregue.", "fontes": []}, 200))

    def test_falha_sem_texto_esgota_cadeia_e_json_retorna_500(self):
        primeiro, _ = provedor_falso("primario", [RuntimeError("fixture 1")])
        segundo, _ = provedor_falso("secundario", [RuntimeError("fixture 2")])
        with patch("uspapo.conversa.preconsultar", return_value=None):
            eventos = self.executar([primeiro, segundo])
        mensagem = "Ops! Muitas pessoas estão utilizando o USPapo. Tente novamente em breve."
        self.assertEqual(eventos, [
            {"tipo": "provedor", "nome": "primario", "indice": 0},
            {"tipo": "provedor", "nome": "secundario", "indice": 1},
            {"tipo": "erro", "mensagem": mensagem}, {"tipo": "fim"},
        ])
        self.assertEqual(agregar(iter(eventos)), ({"erro": mensagem}, 500))


@contextmanager
def modulos_de_busca_isolados():
    """Restaura só os dois módulos mutáveis de busca e seus atributos de pacote."""
    ausente = object()
    nomes = ("busca", "simuladas")
    modulos = {nome: sys.modules.get(f"uspapo.ferramentas.{nome}", ausente) for nome in nomes}
    atributos = {nome: vars(ferramentas).get(nome, ausente) for nome in nomes}
    try:
        for nome in nomes:
            sys.modules.pop(f"uspapo.ferramentas.{nome}", None)
            vars(ferramentas).pop(nome, None)
        yield
    finally:
        for nome in nomes:
            chave = f"uspapo.ferramentas.{nome}"
            if modulos[nome] is ausente:
                sys.modules.pop(chave, None)
            else:
                sys.modules[chave] = modulos[nome]
            if atributos[nome] is ausente:
                vars(ferramentas).pop(nome, None)
            else:
                setattr(ferramentas, nome, atributos[nome])


class TestT7Composicao(unittest.TestCase):
    def test_entrypoints_instanciam_sdks_e_orcamento_com_registros_completos(self):
        # O import do Supabase monta headers com platform.system(). No Python
        # 3.14/Windows, seu fallback chama "ver" e abre NUL via subprocess.
        # O diagnóstico de T0 comprovou essa stack. Isola somente a sondagem;
        # NUL, subprocessos e demais escritas continuam bloqueados pelo runner.
        with (
            patch("platform._syscmd_ver", return_value=("Windows", "", "10.0.0")),
            patch("platform._uname_cache", None),
        ):
            from uspapo import web

        configuracao = [
            {"nome": "fixture-1", "model": "modelo-1", "base_url": "https://um.invalid/v1", "api_key": "fixture-chave-1"},
            {"nome": "fixture-2", "model": "modelo-2", "base_url": "https://dois.invalid/v1", "api_key": "fixture-chave-2", "timeout": 7},
        ]
        ambiente = {
            "LLM_PROVIDERS": json.dumps(configuracao), "PYTHON_DOTENV_DISABLED": "1",
            "PINECONE_API_KEY": "fixture-pinecone", "PINECONE_INDEX": "fixture-indice",
            "PINECONE_NAMESPACE": "fixture-namespace", "STUB_DELAY": "0", "SPTRANS_TOKEN": "",
        }
        proibido = Mock(side_effect=AssertionError("SDK não deve consultar serviços no boot"))
        indice = SimpleNamespace(query=proibido)
        pinecone = SimpleNamespace(Index=Mock(return_value=indice), inference=SimpleNamespace(embed=proibido))
        cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=proibido)))
        orcamentos = []

        def construir_orcamento(registro):
            nomes = [s["function"]["name"] for s in registro.schemas]
            orcamento = Orcamento(registro)
            orcamentos.append((registro, nomes, orcamento))
            return orcamento

        with (
            patch.dict(os.environ, ambiente, clear=True),
            patch("pinecone.Pinecone", return_value=pinecone) as sdk_pinecone,
            patch("uspapo.provedores.OpenAI", return_value=cliente) as sdk_openai,
            patch.object(web, "Orcamento", side_effect=construir_orcamento),
            modulos_de_busca_isolados(), redirect_stdout(StringIO()),
        ):
            entradas = []
            for nome in ("app", "app_stub"):
                caminho = Path(__file__).resolve().parents[1] / f"{nome}.py"
                spec = importlib.util.spec_from_file_location(f"fixture_{nome}", caminho)
                modulo = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(modulo)
                entradas.append(modulo)

            sdk_pinecone.assert_called_once_with(api_key="fixture-pinecone")
            pinecone.Index.assert_called_once_with("fixture-indice")
            sdk_openai.assert_has_calls([
                call(api_key="fixture-chave-1", base_url="https://um.invalid/v1", timeout=60.0, max_retries=0),
                call(api_key="fixture-chave-2", base_url="https://dois.invalid/v1", timeout=7.0, max_retries=0),
            ] * 2)
            self.assertEqual(sdk_openai.call_count, 4)
            proibido.assert_not_called()
            self.assertEqual(len(orcamentos), 2)
            real, stub = [item[0] for item in orcamentos]
            comuns = [
                "consultar_bandejao", "buscar_disciplina", "consultar_turmas",
                "consultar_grade_curricular", "consultar_avaliacoes_professor",
                "consultar_sala", "consultar_circulares", "consultar_wikipedia",
            ]
            self.assertEqual(orcamentos[0][1], ["buscar_documentos"] + comuns)
            self.assertEqual(orcamentos[1][1], ["buscar_documentos", "calculadora"] + comuns)
            self.assertIsNot(real, stub)
            self.assertIs(entradas[0].busca.registro, real)
            self.assertIs(entradas[1].simuladas.registro, stub)
            self.assertIsNot(entradas[0].app, entradas[1].app)
            self.assertEqual(entradas[0].busca.PINECONE_NAMESPACE, "fixture-namespace")
            for registro, _, orcamento in orcamentos:
                self.assertEqual(orcamento.custo_ferramentas, estimar_tokens(registro.json_schemas))
                self.assertEqual(json.loads(registro.json_schemas), registro.schemas)
                self.assertIs(registro.schemas, registro.schemas)
            esquemas_real = {s["function"]["name"]: s for s in real.schemas}
            esquemas_stub = {s["function"]["name"]: s for s in stub.schemas}
            for nome in comuns:
                self.assertEqual(esquemas_real[nome], esquemas_stub[nome])
                self.assertIs(real._ferramentas[nome].executar, stub._ferramentas[nome].executar)
            self.assertIsNot(real._ferramentas["buscar_documentos"].executar, stub._ferramentas["buscar_documentos"].executar)
            for esquema in (esquemas_real, esquemas_stub):
                parametros = esquema["buscar_documentos"]["function"]["parameters"]
                self.assertEqual(parametros["required"], ["consulta"])
                self.assertEqual(parametros["properties"]["consulta"]["type"], "string")
                self.assertEqual(parametros["properties"]["limite"]["default"], 3)
                self.assertEqual(parametros["properties"]["limite"]["type"], "integer")
            self.assertEqual(esquemas_real["buscar_documentos"]["function"]["parameters"]["properties"]["limite"]["description"], "Quantos trechos retornar de 1 a 5 (número inteiro sem aspas).")
            self.assertEqual(esquemas_stub["buscar_documentos"]["function"]["parameters"]["properties"]["limite"]["description"], "Quantos trechos retornar (1 a 5).")
            calculadora = esquemas_stub["calculadora"]["function"]["parameters"]
            self.assertEqual(calculadora["required"], ["operador_1", "operador_2", "operacao"])
            self.assertEqual(calculadora["properties"]["operacao"]["enum"], [1, 2, 3, 4])

    def test_caminhos_e_fachada_apontam_para_dados_e_motor_existentes(self):
        from uspapo.ferramentas import circulares
        from uspapo.transporte import consultas_circulares

        raiz = Path(__file__).resolve().parents[2]
        self.assertEqual(Path(roteamento.PASTA_PROCESSADOS).resolve(), raiz / "data" / "processed")
        self.assertEqual(gtfs_sptrans.ARQUIVO, raiz / "backend" / "uspapo" / "dados_sptrans.json")
        self.assertEqual(circulares.ARQUIVO_GTFS, gtfs_sptrans.ARQUIVO)
        self.assertIs(circulares, consultas_circulares)
        self.assertEqual(roteamento.catalogo_titulos.cache_parameters(), {"maxsize": 1, "typed": False})

    def test_cache_ttl_compartilhado_mantem_escopo_e_expira_no_limite(self):
        from uspapo.ferramentas import bandejao, circulares, jupiter, salas, uspavalia, wikipedia

        self.assertNotIn("cache", vars(bandejao))
        self.assertIsNot(bandejao._CACHE, ferramentas._CACHE)
        for modulo in (circulares, jupiter, salas, uspavalia, wikipedia):
            self.assertIs(modulo.cache, ferramentas.cache)
        produzir = Mock(side_effect=["primeiro", "outro-escopo", "renovado"])
        with patch.object(ferramentas, "_CACHE", {}), patch("uspapo.ferramentas.time.monotonic", return_value=100) as relogio:
            self.assertEqual(ferramentas.cache(("a", "chave"), 20, produzir), "primeiro")
            self.assertEqual(ferramentas.cache(("b", "chave"), 20, produzir), "outro-escopo")
            relogio.return_value = 119
            self.assertEqual(ferramentas.cache(("a", "chave"), 20, produzir), "primeiro")
            relogio.return_value = 120
            self.assertEqual(ferramentas.cache(("a", "chave"), 20, produzir), "renovado")
        self.assertEqual(produzir.call_count, 3)


if __name__ == "__main__":
    unittest.main()
