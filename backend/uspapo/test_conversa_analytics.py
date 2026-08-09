import unittest
from unittest.mock import patch

from uspapo.conversa import executar_conversa


class ProvedorFalso:
    nome = "teste"
    cfg = {"model": "modelo-teste"}

    def teto_contexto(self):
        return 4096


def resposta_com_uso():
    yield {"tipo": "texto", "delta": "Resposta medida"}
    return 11, 7


class TestConversaAnalytics(unittest.TestCase):
    def test_resposta_concluida_registra_tokens_e_sessao(self):
        provedor = ProvedorFalso()
        with (
            patch("uspapo.conversa.saude.ordenar", return_value=[provedor.nome]),
            patch("uspapo.conversa.saude.marcar_sucesso"),
            patch("uspapo.conversa.conversar_com_provedor", return_value=resposta_com_uso()),
            patch("uspapo.analytics.registrar") as registrar,
        ):
            fluxo = executar_conversa(
                [provedor], object(), object(), "pergunta", [],
                user_id="usuario-1", session_id="conversa-1",
            )
            eventos = []
            for evento in fluxo:
                if evento["tipo"] == "fim":
                    self.assertTrue(registrar.called)
                eventos.append(evento)

        self.assertEqual(eventos[-1], {"tipo": "fim"})
        registrar.assert_called_once_with(
            categoria="CHAT",
            nome_evento="RESPOSTA_CONCLUIDA",
            session_id="conversa-1",
            user_id="usuario-1",
            provedor="teste",
            modelo="modelo-teste",
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            latencia_ms=unittest.mock.ANY,
            metadata={"urls_fontes": 0},
        )


if __name__ == "__main__":
    unittest.main()
