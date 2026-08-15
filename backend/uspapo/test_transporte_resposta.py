import re
import unittest

from uspapo.transporte_resposta import (
    AlternativaPublica,
    EstimativaEspera,
    FaixaPassagemProgramada,
    FacetasResposta,
    LocalPublico,
    PassagensPorSentido,
    PrevisaoChegada,
    ResultadoChegada,
    ResultadoTrajeto,
    facetas_da_pergunta,
    renderizar_chegada,
    renderizar_trajeto,
)


def resultado_metro_mecanica(espera=None):
    return ResultadoTrajeto(
        origem=LocalPublico(
            "metro_butanta", "Terminal Metrô Butantã", "Metrô Butantã",
            "junto à estação Butantã do metrô",
        ),
        destino=LocalPublico(
            "mecanica", "Engenharia Mecânica da Escola Politécnica",
            "Engenharia Mecânica",
            "na Escola Politécnica, dentro da Cidade Universitária",
        ),
        linha="8082-10",
        sentido="Cid. Universitária",
        embarque="Terminal Metrô Butantã",
        desembarque="Mecânica II",
        caminhada_origem_m=61.65,
        caminhada_destino_m=27.99,
        caminhada_origem_s=46.24,
        caminhada_destino_s=20.99,
        viagem_s=990,
        espera=espera or EstimativaEspera(
            base="frequencia_media",
            esperada_s=450,
            minima_s=0,
            maxima_s=900,
            intervalo_s=900,
        ),
        alternativas=(
            AlternativaPublica("177H-10", "Cid. Universitária", 2280),
        ),
    )


class TestTransporteResposta(unittest.TestCase):
    def test_pergunta_composta_responde_localizacao_rota_e_total_sem_contradicao(self):
        facetas = facetas_da_pergunta(
            "Aonde fica a engenharia mecânica e como chegar lá do metrô Butantã?"
        )
        texto = renderizar_trajeto(resultado_metro_mecanica(), facetas)

        self.assertIn("fica na Escola Politécnica", texto)
        self.assertIn("8082-10, sentido Cid. Universitária", texto)
        self.assertIn("Mecânica II", texto)
        self.assertIn("25 minutos no total", texto)
        self.assertNotIn("16 minutos", texto)
        self.assertEqual(len(re.findall(r"\d+(?:,\d+)?\s+minuto", texto)), 1)
        self.assertLessEqual(len(texto.split()), 90)
        for termo_tecnico in ("GTFS", "stop_id", "ranking", "recorte"):
            self.assertNotIn(termo_tecnico, texto)

    def test_explicacao_liga_componentes_ao_mesmo_total(self):
        texto = renderizar_trajeto(
            resultado_metro_mecanica(),
            FacetasResposta(duracao=True, explicacao=True),
        )

        self.assertIn("25 minutos no total", texto)
        self.assertIn("16,5 min dentro do ônibus", texto)
        self.assertIn("7,5 min de espera", texto)
        self.assertIn("1,1 min de caminhada", texto)
        self.assertIn("dados oficiais da SPTrans", texto)

    def test_total_e_derivado_dos_componentes_em_segundos(self):
        resultado = resultado_metro_mecanica()

        self.assertAlmostEqual(resultado.total_esperado_s, 1507.23, places=2)
        self.assertLessEqual(resultado.total_minimo_s, resultado.total_esperado_s)
        self.assertLessEqual(resultado.total_esperado_s, resultado.total_maximo_s)

    def test_eta_substitui_a_espera_e_recalcula_o_total(self):
        resultado = resultado_metro_mecanica(EstimativaEspera(
            base="eta_ao_vivo",
            esperada_s=313.76,
            minima_s=313.76,
            maxima_s=313.76,
            eta="12:10",
            observado_em="12:04",
        ))
        texto = renderizar_trajeto(
            resultado,
            FacetasResposta(duracao=True, tempo_real=True),
        )

        self.assertIn("chegada prevista para **12:10**", texto)
        self.assertIn("23 minutos no total", texto)
        self.assertNotIn("25 minutos", texto)

    def test_alternativas_so_aparecem_quando_sao_pedidas(self):
        resultado = resultado_metro_mecanica()

        conciso = renderizar_trajeto(resultado, FacetasResposta())
        com_alternativas = renderizar_trajeto(
            resultado, FacetasResposta(alternativas=True)
        )

        self.assertNotIn("177H-10", conciso)
        self.assertIn("outras opções diretas", com_alternativas)
        self.assertIn("177H-10", com_alternativas)

    def test_alternativas_nao_sao_comparadas_com_eta_como_se_fossem_ao_vivo(self):
        resultado = resultado_metro_mecanica(EstimativaEspera(
            base="eta_ao_vivo",
            esperada_s=300,
            minima_s=300,
            maxima_s=300,
            eta="12:10",
        ))

        texto = renderizar_trajeto(
            resultado, FacetasResposta(tempo_real=True, alternativas=True)
        )
        vista = resultado.public_view(
            FacetasResposta(tempo_real=True, alternativas=True)
        )

        self.assertIn("outras opções diretas pela programação", texto)
        self.assertEqual(vista["alternativas"][0]["base_tempo"], "programacao")

    def test_public_view_do_trajeto_expoe_fatos_sem_detalhes_internos(self):
        vista = resultado_metro_mecanica().public_view(FacetasResposta(
            duracao=True,
        ))

        self.assertEqual(vista["tipo"], "trajeto_onibus")
        self.assertEqual(vista["melhor_opcao"]["linha"], "8082-10")
        self.assertEqual(vista["tempo"]["total_esperado_min"], 25)
        self.assertEqual(vista["tempo"]["viagem_onibus_min"], "16,5")
        self.assertEqual(vista["status_api"], "nao_consultada")
        self.assertNotIn("alternativas", vista)


def faixa_8084(referencia="11:36", fim="11:42"):
    return FaixaPassagemProgramada(
        referencia=referencia,
        referencia_instante="2026-08-14T11:36:00-03:00",
        inicio="2026-08-14T11:30:00-03:00",
        fim="2026-08-14T11:42:00-03:00",
        inicio_texto="11:30",
        fim_texto=fim,
        intervalo_min=12,
        espera_tipica_min=6,
        espera_maxima_min=12,
        ativa_agora=True,
    )


def chegada_8084(*, api_consultada=False, eta=False, veiculos=None):
    return ResultadoChegada(
        linha="8084-10",
        parada="Biênio",
        sentidos=(PassagensPorSentido(
            linha="8084-10",
            parada="Biênio",
            sentido="Cid. Universitária",
            previsoes_ao_vivo=(
                (
                    PrevisaoChegada("11:34", True),
                    PrevisaoChegada("11:47", False),
                )
                if eta else ()
            ),
            faixas_programadas=(faixa_8084(),),
        ),),
        api_consultada=api_consultada,
        observado_em="11:30" if api_consultada else None,
        veiculos_ativos=veiculos,
    )


class TestChegadaResposta(unittest.TestCase):
    def test_facetas_reconhecem_quando_e_vai_passar(self):
        self.assertTrue(facetas_da_pergunta(
            "Quando chega o próximo 8084 no Biênio?"
        ).tempo_real)
        self.assertTrue(facetas_da_pergunta(
            "Que horas o 8084 vai passar no Biênio?"
        ).tempo_real)

    def test_sem_api_consultada_nao_afirma_ausencia_de_eta(self):
        texto = renderizar_chegada(chegada_8084())

        self.assertIn("por volta de **11:36**", texto)
        self.assertIn("espera típica", texto)
        self.assertIn("12 minutos", texto)
        self.assertNotIn("não publicou uma previsão ao vivo", texto)
        self.assertNotIn("GTFS", texto)
        self.assertLessEqual(
            len(re.findall(r"[.!?](?:\s|$)", texto.replace("Cid.", "Cid"))),
            3,
        )

    def test_fim_da_faixa_nao_compara_espera_tipica_com_janela_restante(self):
        faixa = FaixaPassagemProgramada(
            referencia="13:16",
            referencia_instante="2026-08-14T13:16:00-03:00",
            inicio="2026-08-14T12:18:00-03:00",
            fim="2026-08-14T13:17:00-03:00",
            inicio_texto="13:15",
            fim_texto="13:17",
            intervalo_min=10,
            espera_tipica_min=5,
            espera_maxima_min=2,
            ativa_agora=True,
        )
        resultado = ResultadoChegada(
            linha="8084-10",
            parada="Biênio",
            sentidos=(PassagensPorSentido(
                linha="8084-10",
                parada="Biênio",
                sentido="Cid. Universitária",
                faixas_programadas=(faixa,),
            ),),
            api_consultada=False,
        )

        texto = renderizar_chegada(resultado)

        self.assertIn("por volta de **13:16**", texto)
        self.assertIn("espera típica", texto)
        self.assertIn("intervalo programado de **10 minutos**", texto)
        self.assertNotIn("chegar a **2 minutos**", texto)

    def test_api_consultada_sem_eta_informa_status_e_veiculos(self):
        texto = renderizar_chegada(chegada_8084(
            api_consultada=True,
            veiculos=2,
        ))

        self.assertIn("mostra 2 ônibus", texto)
        self.assertIn("não publicou uma previsão ao vivo", texto)
        self.assertIn("por volta de **11:36**", texto)
        self.assertLessEqual(
            len(re.findall(r"[.!?](?:\s|$)", texto.replace("Cid.", "Cid"))),
            3,
        )

    def test_eta_ao_vivo_tem_prioridade_sobre_programacao(self):
        resultado = chegada_8084(api_consultada=True, eta=True)
        texto = renderizar_chegada(resultado)
        vista = resultado.public_view(
            "Quando chega o próximo 8084 no Biênio?"
        )

        self.assertIn("11:34, 11:47", texto)
        self.assertNotIn("11:36", texto)
        self.assertEqual(vista["status_api"], "eta_disponivel")
        self.assertEqual(
            vista["sentidos"][0]["base_previsao"], "eta_ao_vivo"
        )

    def test_public_view_programada_e_publica_e_formatada(self):
        vista = chegada_8084().public_view(
            "Quando vai passar o 8084 no Biênio?"
        )

        self.assertEqual(vista["tipo"], "chegada_onibus")
        self.assertEqual(vista["status_api"], "nao_consultada")
        self.assertTrue(vista["facetas"]["tempo_real"])
        sentido = vista["sentidos"][0]
        self.assertEqual(sentido["base_previsao"], "frequencia_programada")
        self.assertEqual(sentido["horario_referencia"], "11:36")
        self.assertEqual(sentido["espera_tipica_min"], 6)
        self.assertEqual(sentido["intervalo_programado_min"], 12)
        self.assertNotIn("referencia_instante", str(vista))

    def test_sentidos_multiplos_ficam_inequivocos_e_concisos(self):
        resultado = ResultadoChegada(
            linha="177H-10",
            parada="Terminal USP",
            sentidos=(
                PassagensPorSentido(
                    "177H-10", "Terminal USP", "Cid. Universitária",
                    horarios_programados=("11:40",),
                    instantes_programados=("2026-08-14T11:40:00-03:00",),
                ),
                PassagensPorSentido(
                    "177H-10", "Terminal USP", "Metrô Santana",
                    horarios_programados=("11:45",),
                    instantes_programados=("2026-08-14T11:45:00-03:00",),
                ),
            ),
            api_consultada=False,
        )

        texto = renderizar_chegada(resultado)

        self.assertIn("sentido Cid. Universitária", texto)
        self.assertIn("sentido Metrô Santana", texto)
        self.assertIn("11:40", texto)
        self.assertIn("11:45", texto)
        self.assertLessEqual(
            len(re.findall(r"[.!?](?:\s|$)", texto.replace("Cid.", "Cid"))),
            3,
        )


if __name__ == "__main__":
    unittest.main()
