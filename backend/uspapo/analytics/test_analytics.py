import unittest
from unittest.mock import patch, MagicMock
from backend.uspapo.analytics import (
    registrar,
    obter_dau_mau,
    obter_consumo_tokens,
    obter_consumo_por_usuario,
    obter_desempenho_provedores,
    obter_resumo_executivo
)

class TestAnalytics(unittest.TestCase):

    def test_registrar_evento_valido(self):
        with patch("backend.uspapo.analytics.logger._inserir_assincrono") as mock_inserir:
            registrar(
                categoria="CHAT",
                nome_evento="RESPOSTA_CONCLUIDA",
                session_id="sess_123",
                user_id="user_456",
                provedor="Groq",
                modelo="llama-3.1-70b-versatile",
                prompt_tokens=100,
                completion_tokens=50,
                latencia_ms=300
            )
            # Como roda em thread, aguardamos uma fração de segundo para verificar se a função interna foi chamada
            import time
            time.sleep(0.1)
            self.assertTrue(mock_inserir.called)
            dados = mock_inserir.call_args[0][0]
            self.assertEqual(dados["evento"], "chat_query_completed")
            self.assertEqual(dados["total_tokens"], 150)
            self.assertEqual(dados["provedor"], "Groq")

    def test_metricas_com_logs_mockados(self):
        logs_falsos = [
            {
                "evento": "chat_query_completed",
                "user_id": "usr_1",
                "provedor": "Groq",
                "modelo": "llama-3.1-70b",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latencia_ms": 200,
                "created_at": "2026-08-08T00:00:00Z"
            },
            {
                "evento": "chat_query_completed",
                "user_id": "usr_2",
                "provedor": "OpenAI",
                "modelo": "gpt-4o-mini",
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
                "latencia_ms": 500,
                "created_at": "2026-08-08T01:00:00Z"
            }
        ]

        with patch("backend.uspapo.analytics.metricas._buscar_dados_reais_supabase", return_value=([], [], logs_falsos)):
            dau_mau = obter_dau_mau()
            self.assertIn("dau", dau_mau)
            self.assertIn("mau", dau_mau)

            tokens = obter_consumo_tokens(dias=30)
            self.assertEqual(tokens["acumulado_30d"]["total_tokens"], 450)
            self.assertIn("Groq", tokens["por_provedor"])
            self.assertIn("OpenAI", tokens["por_provedor"])

            ranking = obter_consumo_por_usuario(top_k=5)
            self.assertEqual(len(ranking), 2)
            self.assertEqual(ranking[0]["user_id"], "usr_2")  # 300 tokens vem primeiro

            desempenho = obter_desempenho_provedores()
            self.assertEqual(desempenho["Groq"]["latencia_media_ms"], 200.0)

            resumo = obter_resumo_executivo()
            self.assertIn("usuarios", resumo)
            self.assertIn("tokens", resumo)

if __name__ == "__main__":
    unittest.main()
