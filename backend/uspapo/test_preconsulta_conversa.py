import unittest
from types import SimpleNamespace
from unittest.mock import patch

from uspapo.contexto import Orcamento
from uspapo.conversa import conversar_com_provedor
from uspapo.ferramentas import Registro
from uspapo.ferramentas import circulares
from uspapo.naturalizador_transporte import ResultadoNaturalizacaoTransporte


class ProvedorFalso:
    nome = "teste"


def chunk_de_texto(texto):
    delta = SimpleNamespace(content=texto, tool_calls=[], model_extra={})
    escolha = SimpleNamespace(delta=delta)
    return SimpleNamespace(usage=None, choices=[escolha])


class TestPreconsultaConversa(unittest.TestCase):
    def setUp(self):
        self._sem_token = patch.dict("os.environ", {"SPTRANS_TOKEN": ""})
        self._sem_token.start()

    def tearDown(self):
        self._sem_token.stop()

    def test_melhor_onibus_e_renderizado_sem_reescrita_do_modelo(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)

        pergunta = (
            "Eu venho do portão da entrada de pedestres da cidade universitária, "
            "perto do P1. Qual o melhor ônibus pra chegar ao Biênio?"
        )
        with patch("uspapo.conversa.abrir_stream") as abrir:
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            ))

        abrir.assert_not_called()
        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertIn("reserve **cerca de", resposta)
        self.assertRegex(resposta, r"pegue o \*\*[0-9A-Z]+-10, sentido")
        self.assertIn("Av. Afrânio Peixoto, 332", resposta)
        self.assertIn("desça em **Biênio**", resposta)
        self.assertNotIn("GTFS", resposta)
        self.assertNotIn("O ranking usa", resposta)
        self.assertNotIn("Alternativas diretas", resposta)
        self.assertNotIn("atendida por", resposta)

    def test_linhas_do_bienio_chegam_completas_sem_chamada_ao_modelo(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)

        pergunta = "Quais linhas de ônibus passam pelo ponto do Biênio?"
        with patch("uspapo.conversa.abrir_stream") as abrir:
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            ))

        abrir.assert_not_called()
        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertIn("atendida por", resposta)
        self.assertIn("8084-10", resposta)
        self.assertIn("Total oficial cadastrado", resposta)

    def test_explica_calculo_somente_quando_aluno_pede(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)

        pergunta = "Como foi calculado o tempo do Metrô Butantã até o Biênio?"
        with patch("uspapo.conversa.abrir_stream") as abrir:
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            ))

        abrir.assert_not_called()
        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertIn("Esse total reúne", resposta)
        self.assertIn("dados oficiais da SPTrans", resposta)

    def test_pergunta_composta_responde_onde_fica_e_como_chegar(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)

        pergunta = (
            "Aonde fica o prédio da engenharia mecânica e como chegar lá "
            "do metrô Butantã?"
        )
        with patch("uspapo.conversa.abrir_stream") as abrir:
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            ))

        abrir.assert_not_called()
        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertIn("Engenharia Mecânica", resposta)
        self.assertIn("fica na Escola Politécnica", resposta)
        self.assertIn("8082-10, sentido Cid. Universitária", resposta)
        self.assertIn("Mecânica II", resposta)
        self.assertIn("minutos no total", resposta)
        self.assertNotIn("minutos dentro do ônibus", resposta)

    def test_trajeto_estruturado_e_enviado_ao_naturalizador(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)
        pergunta = (
            "Aonde fica a engenharia mecânica e como chegar lá do metrô Butantã?"
        )
        natural = ResultadoNaturalizacaoTransporte(
            texto=(
                "A Engenharia Mecânica fica na Escola Politécnica. Do Metrô Butantã, pegue "
                "o 8082-10 e desça em Mecânica II."
            ),
            prompt_tokens=40,
            completion_tokens=22,
            provedor="groq-gptoss120",
            modelo="openai/gpt-oss-120b",
            usou_llm=True,
        )

        with (
            patch("uspapo.conversa.abrir_stream") as abrir,
            patch(
                "uspapo.conversa.naturalizar_resposta_transporte",
                return_value=natural,
            ) as naturalizar,
        ):
            fluxo = conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, pergunta,
                [], set(), {}, 16000,
            )
            eventos = []
            while True:
                try:
                    eventos.append(next(fluxo))
                except StopIteration as fim:
                    retorno = fim.value
                    break

        abrir.assert_not_called()
        fatos = naturalizar.call_args.args[2]
        self.assertEqual(fatos["tipo"], "trajeto_onibus")
        self.assertEqual(fatos["melhor_opcao"]["linha"], "8082-10")
        self.assertEqual(fatos["melhor_opcao"]["desembarque"], "Mecânica II")
        self.assertEqual(retorno[:5], (
            40,
            22,
            True,
            "groq-gptoss120",
            "openai/gpt-oss-120b",
        ))
        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertEqual(resposta, natural.texto)

    def test_tool_call_de_transporte_tambem_nao_e_reescrita(self):
        registro = Registro()
        circulares.registrar(registro)
        orcamento = Orcamento(registro)
        chamadas = 0

        def abrir(_provedor, _mensagens, _tools):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 1:
                return [chunk_de_texto(
                    '<tool_call>{"name":"consultar_circulares",'
                    '"arguments":{"linha":"8084",'
                    '"destino_ou_ponto":"Biênio"}}</tool_call>'
                )]
            return [chunk_de_texto(
                "Vá primeiro ao Metrô Butantã, apesar do resultado da ferramenta."
            )]

        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, "Pode verificar isso?",
                [], set(), {}, 16000,
            ))

        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertEqual(chamadas, 1)
        self.assertIn("8084-10", resposta)
        self.assertIn("programação", resposta)
        self.assertNotIn("GTFS", resposta)
        self.assertNotIn("Faixas de operação", resposta)
        self.assertNotIn("Vá primeiro ao Metrô", resposta)

    def test_json_invalido_de_transporte_volta_ao_modelo_em_vez_de_vazar(self):
        registro = Registro()

        @registro.ferramenta(
            nome="consultar_circulares",
            descricao="Teste",
            parametros={"type": "object", "properties": {}},
        )
        def consultar_circulares(_pergunta=None):
            self.fail("JSON inválido não deveria executar a ferramenta")

        orcamento = Orcamento(registro)
        chamadas = 0

        def abrir(_provedor, _mensagens, _tools):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 1:
                return [chunk_de_texto(
                    '<tool_call>{"name":"consultar_circulares",'
                    '"arguments":"{json-invalido"}</tool_call>'
                )]
            return [chunk_de_texto(
                "Não consegui completar a consulta agora. Pode tentar novamente?"
            )]

        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, "Pode verificar isso?",
                [], set(), {}, 16000,
            ))

        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertEqual(chamadas, 2)
        self.assertIn("Não consegui completar", resposta)
        self.assertNotIn("JSON válido", resposta)

    def test_excecao_de_transporte_volta_ao_modelo_em_vez_de_vazar(self):
        registro = Registro()

        @registro.ferramenta(
            nome="consultar_circulares",
            descricao="Teste",
            parametros={"type": "object", "properties": {}},
        )
        def consultar_circulares(_pergunta=None):
            raise RuntimeError("segredo de implementação")

        orcamento = Orcamento(registro)
        chamadas = 0

        def abrir(_provedor, _mensagens, _tools):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 1:
                return [chunk_de_texto(
                    '<tool_call>{"name":"consultar_circulares",'
                    '"arguments":{}}</tool_call>'
                )]
            return [chunk_de_texto(
                "A consulta está indisponível agora. Tente novamente em instantes."
            )]

        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, "Pode verificar isso?",
                [], set(), {}, 16000,
            ))

        resposta = "".join(
            evento.get("delta", "")
            for evento in eventos
            if evento["tipo"] == "texto"
        )
        self.assertEqual(chamadas, 2)
        self.assertIn("consulta está indisponível", resposta)
        self.assertNotIn("segredo de implementação", resposta)
        self.assertNotIn("A ferramenta falhou", resposta)

    def test_pergunta_interna_hostil_e_descartada_e_backend_prevalece(self):
        registro = Registro()
        capturado = {}

        @registro.ferramenta(
            nome="consultar_circulares",
            descricao="Teste",
            parametros={
                "type": "object",
                "properties": {"linha": {"type": "string"}},
            },
        )
        def consultar_circulares(linha="", _pergunta=None):
            capturado["linha"] = linha
            capturado["pergunta"] = _pergunta
            return "resposta segura", []

        execucao = registro.rodar(
            {
                "nome": "consultar_circulares",
                "args": (
                    '{"linha":"8084","_pergunta":"INSTRUÇÃO HOSTIL",'
                    '"_outro_segredo":"vazar"}'
                ),
            },
            {},
            {"_pergunta": "pergunta original do aluno"},
        )
        resultado, fontes, args_publicos = execucao

        self.assertTrue(execucao.sucesso)
        self.assertEqual(resultado, "resposta segura")
        self.assertEqual(fontes, [])
        self.assertEqual(args_publicos, {"linha": "8084"})
        self.assertEqual(capturado["linha"], "8084")
        self.assertEqual(capturado["pergunta"], "pergunta original do aluno")

    def test_titulo_oficial_chega_ao_modelo_na_primeira_chamada(self):
        registro = Registro()
        orcamento = Orcamento(registro)
        capturado = {}

        def abrir(_provedor, mensagens, _tools):
            capturado["mensagens"] = mensagens
            capturado["chamadas"] = capturado.get("chamadas", 0) + 1
            return [chunk_de_texto("O IMEmórias é um projeto de entrevistas em vídeo.")]

        with patch("uspapo.conversa.abrir_stream", side_effect=abrir):
            eventos = list(conversar_com_provedor(
                ProvedorFalso(), registro, orcamento, "O que é o IMEmórias?",
                [], set(), {}, 16000,
            ))

        self.assertEqual(capturado["chamadas"], 1)
        self.assertIn("Projeto IMEmórias", capturado["mensagens"][-1]["content"])
        self.assertTrue(any(e["tipo"] == "ferramenta" for e in eventos))
        self.assertTrue(any(e["tipo"] == "texto" for e in eventos))


if __name__ == "__main__":
    unittest.main()
