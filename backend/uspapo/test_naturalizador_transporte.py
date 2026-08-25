import copy
import json
import unittest
from types import SimpleNamespace

from uspapo.naturalizador_transporte import (
    naturalizar_resposta_transporte,
    validar_resposta_transporte,
)


FALLBACK = (
    "De Terminal Metrô Butantã até Engenharia Mecânica da Escola Politécnica, "
    "conte com cerca de 25 minutos. A melhor opção é pegar o 8082-10, sentido "
    "Cidade Universitária. Caminhe 62 m até Terminal Metrô Butantã. O trecho de "
    "ônibus leva 16 minutos. Desça em Mecânica II, a 28 m do destino. Neste "
    "momento há 2 ônibus em circulação, sem previsão exata para o ponto."
)

PUBLIC_VIEW = {
    "tipo": "trajeto",
    "origem": "Terminal Metrô Butantã",
    "destino": "Engenharia Mecânica da Escola Politécnica",
    "linha": "8082-10",
    "sentido": "Cidade Universitária",
    "embarque": "Terminal Metrô Butantã",
    "desembarque": "Mecânica II",
    "tempo_total_min": 25,
    "tempo_onibus_min": 16,
    "espera_estimada_min": 8,
    "caminhada_origem_m": 62,
    "caminhada_destino_m": 28,
    "veiculos_ativos": 2,
    "previsao_exata": False,
}


def _completion(texto, prompt_tokens=40, completion_tokens=20):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=json.dumps({"resposta": texto}, ensure_ascii=False)
            )
        )],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


class _Completions:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta


def _provedor(modelo, respostas, nome="groq-teste"):
    completions = _Completions(respostas)
    provedor = SimpleNamespace(
        nome=nome,
        cfg={"model": modelo},
        cliente=SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        ),
    )
    return provedor, completions


class TestNaturalizadorTransporte(unittest.TestCase):
    def test_naturalizador_nao_altera_confianca_calculada_pelo_backend(self):
        vista = {
            "tipo": "chegada_onibus",
            "linha": "8084-10",
            "parada": "Biênio",
            "sentidos": [{
                "chegadas": [{
                    "horario": "10:05",
                    "minutos_ate_chegada": 5,
                    "source": "live",
                    "confidence": "high",
                }],
            }],
            "fatos_obrigatorios": ["8084-10", "Biênio"],
            "horarios_obrigatorios": ["10:05"],
        }
        original = copy.deepcopy(vista)
        fallback = "O 8084-10 chega no Biênio às 10:05."
        provedor, _ = _provedor(
            "openai/gpt-oss-120b", [_completion(fallback)]
        )

        naturalizar_resposta_transporte(
            [provedor], "Quando passa?", vista, fallback
        )

        self.assertEqual(vista, original)

    def test_naturalizador_nao_pode_declarar_outro_nivel_de_confianca(self):
        vista = {
            "tipo": "chegada_onibus",
            "fatos_obrigatorios": ["8084-10", "Biênio"],
            "sentidos": [{"chegadas": [{
                "horario": "10:05", "source": "live", "confidence": "high",
            }]}],
        }
        valida, motivo = validar_resposta_transporte(
            "O 8084-10 chega no Biênio às 10:05 com baixa confiança.",
            vista,
            "O 8084-10 chega no Biênio às 10:05.",
        )

        self.assertFalse(valida)
        self.assertIn("confiança", motivo)

    def test_nao_permite_inverter_estado_sem_servico(self):
        vista = {
            "tipo": "chegada_onibus",
            "linha": "8084-10",
            "parada": "Biênio",
            "status_operacao": "sem_servico",
            "fatos_obrigatorios": ["8084-10", "Biênio"],
            "frases_obrigatorias": ["não tem serviço programado"],
        }
        fallback = (
            "A linha 8084-10 não tem serviço programado na parada Biênio hoje."
        )

        valida, motivo = validar_resposta_transporte(
            "A linha 8084-10 tem serviço programado na parada Biênio hoje.",
            vista,
            fallback,
        )

        self.assertFalse(valida)
        self.assertIn("estado operacional ausente", motivo)

    def test_horario_indisponivel_nao_reaproveita_distancia_como_tempo(self):
        vista = {
            "tipo": "trajeto_onibus_sem_horario",
            "linha": "8012-10",
            "caminhada_m": 114,
            "status_programacao": "horario_indisponivel",
            "fatos_obrigatorios": ["8012-10"],
            "frases_obrigatorias": [
                "não é seguro informar a espera nem o tempo total"
            ],
        }
        fallback = (
            "Use a 8012-10; não é seguro informar a espera nem o tempo total."
        )

        valida, motivo = validar_resposta_transporte(
            "Use a 8012-10. Não é seguro informar a espera nem o tempo total, "
            "mas a viagem leva 114 minutos.",
            vista,
            fallback,
        )

        self.assertFalse(valida)
        self.assertIn("horário indisponível", motivo)

    def test_aceita_parafrase_natural_sem_mudar_fatos(self):
        texto = (
            "O prédio fica na Escola Politécnica. Saindo do Terminal Metrô "
            "Butantã, conte com cerca de 25 minutos no total: 16 minutos no "
            "ônibus e o restante entre a espera e as caminhadas. Pegue o "
            "8082-10, sentido Cidade Universitária, e desça em Mecânica II."
        )
        provedor, completions = _provedor(
            "openai/gpt-oss-120b", [_completion(texto)]
        )

        resultado = naturalizar_resposta_transporte(
            [provedor], "Onde fica e como chegar do metrô?", PUBLIC_VIEW, FALLBACK
        )

        self.assertTrue(resultado.usou_llm)
        self.assertEqual(resultado.texto, texto)
        self.assertEqual(resultado.prompt_tokens, 40)
        self.assertEqual(resultado.completion_tokens, 20)
        self.assertEqual(resultado.total_tokens, 60)
        self.assertEqual(resultado.modelo, "openai/gpt-oss-120b")
        chamada = completions.chamadas[0]
        self.assertFalse(chamada["stream"])
        self.assertNotIn("tools", chamada)
        self.assertEqual(chamada["reasoning_effort"], "low")
        self.assertLessEqual(chamada["max_completion_tokens"], 400)
        self.assertTrue(
            chamada["response_format"]["json_schema"]["strict"]
        )

    def test_prefere_120b_mesmo_se_aparecer_depois_na_lista(self):
        texto = "Conte com cerca de 25 minutos no total. Pegue o 8082-10."
        llama, chamadas_llama = _provedor(
            "llama-3.3-70b-versatile", [_completion("não deveria rodar")]
        )
        menor, chamadas_menor = _provedor(
            "openai/gpt-oss-20b", [_completion(texto)], nome="oss20"
        )
        maior, chamadas_maior = _provedor(
            "openai/gpt-oss-120b", [_completion(texto)], nome="oss120"
        )

        resultado = naturalizar_resposta_transporte(
            [llama, menor, maior], "Como chegar?", PUBLIC_VIEW, FALLBACK
        )

        self.assertTrue(resultado.usou_llm)
        self.assertEqual(resultado.provedor, "oss120")
        self.assertEqual(len(chamadas_maior.chamadas), 1)
        self.assertEqual(chamadas_menor.chamadas, [])
        self.assertEqual(chamadas_llama.chamadas, [])

    def test_preserva_credenciais_repetidas_do_mesmo_modelo(self):
        texto = "Conte com cerca de 25 minutos no total. Pegue o 8082-10."
        primeira, chamadas_primeira = _provedor(
            "openai/gpt-oss-120b", [TimeoutError("primeira chave falhou")],
            nome="oss120-chave-1",
        )
        segunda, chamadas_segunda = _provedor(
            "openai/gpt-oss-120b", [_completion(texto)],
            nome="oss120-chave-2",
        )
        menor, chamadas_menor = _provedor(
            "openai/gpt-oss-20b", [_completion(texto)], nome="oss20"
        )

        resultado = naturalizar_resposta_transporte(
            [primeira, menor, segunda], "Como chegar?", PUBLIC_VIEW, FALLBACK
        )

        self.assertTrue(resultado.usou_llm)
        self.assertEqual(resultado.provedor, "oss120-chave-2")
        self.assertEqual(len(chamadas_primeira.chamadas), 1)
        self.assertEqual(len(chamadas_segunda.chamadas), 1)
        self.assertEqual(chamadas_menor.chamadas, [])

    def test_rejeita_linha_inventada(self):
        texto = "Pegue o 8084-10 e conte com cerca de 25 minutos."
        valido, motivo = validar_resposta_transporte(
            texto, PUBLIC_VIEW, FALLBACK
        )

        self.assertFalse(valido)
        self.assertIn("linha não permitida", motivo)

    def test_rejeita_numero_inventado(self):
        texto = "Conte com cerca de 26 minutos e pegue o 8082-10."
        valido, motivo = validar_resposta_transporte(
            texto, PUBLIC_VIEW, FALLBACK
        )

        self.assertFalse(valido)
        self.assertIn("número não permitido", motivo)

    def test_rejeita_local_inventado(self):
        texto = (
            "Conte com cerca de 25 minutos. Pegue o 8082-10 no Terminal "
            "Pinheiros e desça em Mecânica II."
        )
        valido, motivo = validar_resposta_transporte(
            texto, PUBLIC_VIEW, FALLBACK
        )

        self.assertFalse(valido)
        self.assertIn("Pinheiros", motivo)

    def test_rejeita_resposta_que_omite_os_fatos_necessarios(self):
        fatos = {
            **PUBLIC_VIEW,
            "fatos_obrigatorios": ["8082-10", "Mecânica II"],
            "numeros_obrigatorios": [25],
        }

        valido, motivo = validar_resposta_transporte(
            "parece adequado.", fatos, FALLBACK
        )

        self.assertFalse(valido)
        self.assertIn("obrigatório ausente", motivo)

    def test_saida_invalida_cai_no_fallback(self):
        provedor, _ = _provedor(
            "openai/gpt-oss-120b",
            [SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="isto não é JSON")
                )],
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3),
            )],
        )

        resultado = naturalizar_resposta_transporte(
            [provedor], "Como chegar?", PUBLIC_VIEW, FALLBACK
        )

        self.assertFalse(resultado.usou_llm)
        self.assertEqual(resultado.texto, FALLBACK)
        # O provedor respondeu e cobrou tokens mesmo que seu texto não tenha sido usado.
        self.assertEqual(resultado.total_tokens, 12)
        self.assertEqual(resultado.motivo_fallback, "JSONDecodeError")
        self.assertEqual(resultado.tentativas[0]["prompt_tokens"], 9)
        self.assertEqual(resultado.tentativas[0]["completion_tokens"], 3)

    def test_timeout_cai_no_fallback(self):
        provedor, _ = _provedor(
            "openai/gpt-oss-120b", [TimeoutError("demorou")]
        )

        resultado = naturalizar_resposta_transporte(
            [provedor], "Como chegar?", PUBLIC_VIEW, FALLBACK
        )

        self.assertFalse(resultado.usou_llm)
        self.assertEqual(resultado.texto, FALLBACK)
        self.assertEqual(resultado.motivo_fallback, "TimeoutError")

    def test_erro_no_120b_tenta_20b(self):
        texto = "Conte com cerca de 25 minutos no total. Pegue o 8082-10."
        maior, _ = _provedor(
            "openai/gpt-oss-120b", [RuntimeError("falhou")], nome="oss120"
        )
        menor, _ = _provedor(
            "openai/gpt-oss-20b", [_completion(texto, 7, 4)], nome="oss20"
        )

        resultado = naturalizar_resposta_transporte(
            [maior, menor], "Como chegar?", PUBLIC_VIEW, FALLBACK
        )

        self.assertTrue(resultado.usou_llm)
        self.assertEqual(resultado.provedor, "oss20")
        self.assertEqual(resultado.total_tokens, 11)

    def test_resposta_inventada_do_120b_pode_cair_no_20b(self):
        invalida = "Pegue o 8084-10 e conte com 30 minutos."
        valida = "Pegue o 8082-10 e conte com cerca de 25 minutos no total."
        maior, _ = _provedor(
            "openai/gpt-oss-120b", [_completion(invalida, 5, 3)], nome="oss120"
        )
        menor, _ = _provedor(
            "openai/gpt-oss-20b", [_completion(valida, 6, 4)], nome="oss20"
        )

        resultado = naturalizar_resposta_transporte(
            [maior, menor], "Como chegar?", PUBLIC_VIEW, FALLBACK
        )

        self.assertTrue(resultado.usou_llm)
        self.assertEqual(resultado.texto, valida)
        self.assertEqual(resultado.total_tokens, 18)

    def test_sem_fallback_explicito_usa_resposta_factual_do_payload(self):
        fatos = {**PUBLIC_VIEW, "resposta_factual": FALLBACK}

        resultado = naturalizar_resposta_transporte(
            [], "Como chegar?", fatos
        )

        self.assertFalse(resultado.usou_llm)
        self.assertEqual(resultado.texto, FALLBACK)


if __name__ == "__main__":
    unittest.main()
