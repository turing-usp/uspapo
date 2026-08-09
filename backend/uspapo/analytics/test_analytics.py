import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from . import (
    obter_consumo_por_usuario,
    obter_consumo_tokens,
    obter_dau_mau,
    obter_desempenho_provedores,
    obter_resumo_executivo,
    obter_serie_temporal_diaria,
    registrar,
)
from .metricas import _buscar_tabela


class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.agora = datetime.now(timezone.utc)

    def test_registrar_persiste_o_evento_completo(self):
        with patch(f"{registrar.__module__}._inserir", return_value=True) as inserir:
            resultado = registrar(
                categoria="CHAT",
                nome_evento="RESPOSTA_CONCLUIDA",
                session_id="conversa-1",
                user_id="user-456",
                provedor="Groq",
                modelo="llama-3.1-70b-versatile",
                prompt_tokens=100,
                completion_tokens=50,
                latencia_ms=300,
            )

        self.assertTrue(resultado)
        dados = inserir.call_args.args[0]
        self.assertEqual(dados["evento"], "chat_query_completed")
        self.assertEqual(dados["session_id"], "conversa-1")
        self.assertEqual(dados["total_tokens"], 150)

    def test_tokens_usam_apenas_logs_de_respostas_do_periodo(self):
        recente = self.agora.isoformat()
        antigo = (self.agora - timedelta(days=31)).isoformat()
        logs = [
            {"evento": "chat_query_completed", "created_at": recente, "user_id": "u1", "provedor": "Groq", "modelo": "m1", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            {"evento": "sys_provider_error", "created_at": recente, "user_id": "u1", "prompt_tokens": 999, "completion_tokens": 999, "total_tokens": 1998},
            {"evento": "chat_query_completed", "created_at": antigo, "user_id": "u2", "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        ]
        mensagens = [{"pergunta": "texto muito longo", "resposta": "resposta longa", "criada_em": recente}]

        with patch(f"{obter_consumo_tokens.__module__}._buscar_dados_reais_supabase", return_value=([], mensagens, logs)):
            consumo = obter_consumo_tokens()

        self.assertEqual(consumo["hoje"]["total_tokens"], 150)
        self.assertEqual(consumo["acumulado_30d"]["total_tokens"], 150)
        self.assertEqual(consumo["por_modelo"]["m1"]["chamadas"], 1)

    def test_balde_por_modelo_nao_herda_o_acumulado_global(self):
        """O defaultdict semeava cada modelo novo com o total corrente."""
        recente = self.agora.isoformat()
        logs = [
            {"evento": "chat_query_completed", "created_at": recente, "provedor": "Groq", "modelo": "m1", "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            {"evento": "chat_query_completed", "created_at": recente, "provedor": "Groq", "modelo": "m1", "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            {"evento": "chat_query_completed", "created_at": recente, "provedor": "Outro", "modelo": "m2", "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        ]

        with patch(f"{obter_consumo_tokens.__module__}._buscar_dados_reais_supabase", return_value=([], [], logs)):
            consumo = obter_consumo_tokens()

        m1, m2 = consumo["por_modelo"]["m1"], consumo["por_modelo"]["m2"]
        self.assertEqual((m1["prompt_tokens"], m1["completion_tokens"], m1["total_tokens"]), (30, 15, 45))
        self.assertEqual((m2["prompt_tokens"], m2["completion_tokens"], m2["total_tokens"]), (1, 1, 2))
        # A soma dos baldes tem que fechar com o acumulado geral.
        self.assertEqual(m1["total_tokens"] + m2["total_tokens"], consumo["acumulado_30d"]["total_tokens"])
        self.assertEqual(consumo["por_provedor"]["Outro"]["total_tokens"], 2)

    def test_dau_mau_e_serie_contam_usuarios_reais_sem_inventar_latencia(self):
        data = self.agora.isoformat()
        conversas = [{"id": "c1", "user_id": "u1", "criada_em": data, "atualizada_em": data}]
        mensagens = [{"conversa_id": "c1", "pergunta": "Oi", "resposta": "Ola", "criada_em": data}]
        logs = [
            {"evento": "chat_query_completed", "session_id": "c1", "user_id": "u1", "created_at": data, "prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "latencia_ms": 200},
            {"evento": "chat_query_completed", "session_id": "c2", "created_at": data, "total_tokens": 999, "latencia_ms": 500},
        ]
        with patch(f"{obter_dau_mau.__module__}._buscar_dados_reais_supabase", return_value=(conversas, mensagens, logs)):
            usuarios = obter_dau_mau()
            serie = obter_serie_temporal_diaria()

        self.assertEqual((usuarios["dau"], usuarios["mau"]), (1, 1))
        hoje = serie[-1]
        # Duas respostas concluidas: a pergunta agora vem da telemetria, nao da
        # tabela de mensagens (que nao tem data para filtrar).
        self.assertEqual(hoje["perguntas"], 2)
        self.assertEqual(hoje["total_tokens"], 1006)
        self.assertEqual(hoje["latencia_media_ms"], 350.0)
        self.assertEqual((hoje["usuarios_unicos"], hoje["mau"]), (1, 1))

    def test_serie_de_mau_acumula_a_janela_e_o_dau_so_o_dia(self):
        hoje = self.agora.isoformat()
        ha_vinte_dias = (self.agora - timedelta(days=20)).isoformat()
        ha_cinquenta_dias = (self.agora - timedelta(days=50)).isoformat()
        logs = [
            {"evento": "chat_query_completed", "user_id": "u_hoje", "created_at": hoje},
            {"evento": "chat_query_completed", "user_id": "u_20d", "created_at": ha_vinte_dias},
            {"evento": "chat_query_completed", "user_id": "u_50d", "created_at": ha_cinquenta_dias},
        ]

        with patch(f"{obter_serie_temporal_diaria.__module__}._buscar_dados_reais_supabase", return_value=([], [], logs)):
            serie = obter_serie_temporal_diaria()

        ultimo = serie[-1]
        # DAU conta so quem apareceu no dia; MAU pega a janela de 30 dias, que
        # alcanca o usuario de 20 dias atras mas ja deixou o de 50 para tras.
        self.assertEqual(ultimo["usuarios_unicos"], 1)
        self.assertEqual(ultimo["mau"], 2)
        self.assertTrue(all(ponto["mau"] >= ponto["usuarios_unicos"] for ponto in serie))
        self.assertEqual(len(serie), 30)

    def test_ranking_usa_perguntas_persistidas_e_tokens_medidos(self):
        data = self.agora.isoformat()
        conversas = [{"id": "c1", "user_id": "u1"}, {"id": "c2", "user_id": "u2"}]
        mensagens = [{"conversa_id": "c1", "criada_em": data}, {"conversa_id": "c1", "criada_em": data}]
        logs = [
            {"evento": "chat_query_completed", "user_id": "u2", "created_at": data, "total_tokens": 100},
            {"evento": "chat_query_completed", "user_id": "u1", "created_at": data, "total_tokens": 40},
        ]
        with patch(f"{obter_consumo_por_usuario.__module__}._buscar_dados_reais_supabase", return_value=(conversas, mensagens, logs)):
            ranking = obter_consumo_por_usuario()

        self.assertEqual(ranking[0]["user_id"], "u2")
        self.assertEqual(ranking[1]["perguntas"], 2)
        self.assertEqual(ranking[1]["total_tokens"], 40)

    def test_desempenho_nao_conta_eventos_irrelevantes(self):
        data = self.agora.isoformat()
        logs = [
            {"evento": "chat_query_completed", "created_at": data, "modelo": "m1", "latencia_ms": 100},
            {"evento": "sys_provider_error", "created_at": data, "modelo": "m1"},
            {"evento": "auth_user_login", "created_at": data, "modelo": "m1", "latencia_ms": 900},
        ]
        with patch(f"{obter_desempenho_provedores.__module__}._buscar_dados_reais_supabase", return_value=([], [], logs)):
            desempenho = obter_desempenho_provedores()

        self.assertEqual(desempenho["m1"]["total_chamadas"], 2)
        self.assertEqual(desempenho["m1"]["erros"], 1)
        self.assertEqual(desempenho["m1"]["latencia_media_ms"], 100.0)

    def test_busca_paginada_le_todos_os_registros(self):
        primeira = [{"id": indice} for indice in range(1000)]
        segunda = [{"id": 1000}]
        consulta = MagicMock()
        consulta.select.return_value = consulta
        consulta.range.return_value = consulta
        consulta.execute.side_effect = [MagicMock(data=primeira), MagicMock(data=segunda)]
        cliente = MagicMock()
        cliente.table.return_value = consulta

        linhas = _buscar_tabela(cliente, "analytics_logs")

        self.assertEqual(len(linhas), 1001)
        self.assertEqual(consulta.range.call_args_list[0].args, (0, 999))
        self.assertEqual(consulta.range.call_args_list[1].args, (1000, 1999))

    def test_resumo_usa_uma_unica_leitura_coerente(self):
        dados = ([], [], [])
        with patch(f"{obter_resumo_executivo.__module__}._buscar_dados_reais_supabase", return_value=dados) as buscar:
            resumo = obter_resumo_executivo()

        self.assertEqual(buscar.call_count, 1)
        self.assertEqual(resumo["tokens"]["acumulado_30d"]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
