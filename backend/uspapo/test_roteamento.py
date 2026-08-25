import unittest
from unittest.mock import Mock

from uspapo import roteamento
from uspapo.locais_usp import (
    CATALOGO_LOCAIS,
    coordenada_local,
    mencoes_locais,
    resolver_local,
)


class TestRoteamento(unittest.TestCase):
    def test_catalogo_resolve_todos_os_nomes_e_aliases_explicitos(self):
        for chave, local in CATALOGO_LOCAIS.items():
            with self.subTest(chave=chave, nome=local["nome"]):
                self.assertEqual(resolver_local(chave), chave)
                self.assertEqual(resolver_local(local["nome"]), chave)
                self.assertEqual(
                    coordenada_local(chave),
                    (local["latitude"], local["longitude"]),
                )
            for alias in local["aliases"]:
                with self.subTest(chave=chave, alias=alias):
                    self.assertEqual(resolver_local(alias), chave)

    def test_coordenadas_ficam_na_regiao_da_cidade_universitaria(self):
        for chave in CATALOGO_LOCAIS:
            latitude, longitude = coordenada_local(chave)
            with self.subTest(chave=chave):
                self.assertGreater(latitude, -23.58)
                self.assertLess(latitude, -23.54)
                self.assertGreater(longitude, -46.75)
                self.assertLess(longitude, -46.70)

    def test_central_reitoria_e_administracao_sao_destinos_distintos(self):
        self.assertEqual(resolver_local("Central"), "restaurante_central")
        self.assertEqual(
            resolver_local("Administração Central"), "administracao_central"
        )
        self.assertEqual(resolver_local("Reitoria"), "reitoria")
        self.assertEqual(
            mencoes_locais(
                "Saio da Central, passo pela Administração Central e vou à Reitoria."
            ),
            ["restaurante_central", "administracao_central", "reitoria"],
        )

    def test_siglas_nao_casam_com_prefixos_de_palavras_diferentes(self):
        for termo in (
            "Academia de Polícia",
            "Rua Faustolo",
            "Avenida Ipiranga",
            "Rua Hugo Carotini",
        ):
            with self.subTest(termo=termo):
                self.assertIsNone(resolver_local(termo))

        self.assertEqual(resolver_local("Poli"), "poli")
        self.assertEqual(resolver_local("FAU"), "fau")
        self.assertEqual(resolver_local("IP"), "psicologia")
        self.assertEqual(resolver_local("HU"), "hu")

    def test_metro_generico_nao_substitui_outra_estacao_por_butanta(self):
        self.assertEqual(resolver_local("Metrô"), "metro_butanta")
        self.assertEqual(resolver_local("Metrô Butantã"), "metro_butanta")
        self.assertIsNone(resolver_local("Metrô Santana"))
        self.assertIsNone(resolver_local("Metrô Vila Madalena"))
        self.assertEqual(
            mencoes_locais("Do Metrô Santana até a Poli"),
            ["poli"],
        )

    def test_extrai_origem_e_destino_de_perguntas_de_trajeto(self):
        casos = {
            (
                "Eu venho do portão da entrada de pedestres da cidade universitária, "
                "perto do P1. Qual o melhor ônibus pra chegar ao Biênio?"
            ): {"origem": "p1", "destino_ou_ponto": "bienio"},
            "Qual o melhor ônibus pra ir do Biênio até a Química?": {
                "origem": "bienio", "destino_ou_ponto": "quimica"
            },
            (
                "Aonde fica o prédio da Engenharia Mecânica e como chegar lá "
                "do Metrô Butantã?"
            ): {"origem": "metro_butanta", "destino_ou_ponto": "mecanica"},
            "Qual o melhor ônibus da FEA até Letras?": {
                "origem": "fea", "destino_ou_ponto": "letras"
            },
            "Quanto tempo demora para ir da Central até o Biênio?": {
                "origem": "restaurante_central", "destino_ou_ponto": "bienio"
            },
            "Quanto tempo demora pra chegar do metrô até a Poli?": {
                "origem": "metro_butanta", "destino_ou_ponto": "poli"
            },
            "Qual é o trajeto do HU até a FAU?": {
                "origem": "hu", "destino_ou_ponto": "fau"
            },
            "Quanto tempo leva do IP ao IME?": {
                "origem": "psicologia", "destino_ou_ponto": "ime"
            },
            "Como vou da Administração Central para a Reitoria?": {
                "origem": "administracao_central", "destino_ou_ponto": "reitoria"
            },
            "Central até o Biênio": {
                "origem": "restaurante_central", "destino_ou_ponto": "bienio"
            },
        }

        for pergunta, esperado in casos.items():
            with self.subTest(pergunta=pergunta):
                self.assertEqual(roteamento.pedido_trajeto(pergunta), esperado)

    def test_pedido_trajeto_usa_aliases_do_catalogo_inteiro(self):
        itens = list(CATALOGO_LOCAIS.items())
        for indice, (origem, info_origem) in enumerate(itens):
            destino, info_destino = itens[(indice + 1) % len(itens)]
            pergunta = (
                f"Quanto tempo leva de {info_origem['aliases'][0]} "
                f"até {info_destino['aliases'][0]}?"
            )
            with self.subTest(origem=origem, destino=destino):
                self.assertEqual(
                    roteamento.pedido_trajeto(pergunta),
                    {"origem": origem, "destino_ou_ponto": destino},
                )

    def test_nome_oficial_exato_encontra_imemorias(self):
        pagina = roteamento.pagina_por_titulo("O que é o imemórias?")

        self.assertEqual(pagina["titulo"], "IMEmórias")
        self.assertEqual(pagina["url"], "https://www.ime.usp.br/imemorias/")
        self.assertIn("entrevistas em vídeo", pagina["texto"])

    def test_nome_generico_nao_chuta_pagina(self):
        self.assertIsNone(roteamento.pagina_por_titulo("O que é memória?"))

    def test_tipo_generico_nao_impede_titulo_exato(self):
        pagina = roteamento.pagina_por_titulo("Explique o projeto IMEmórias")

        self.assertEqual(pagina["titulo"], "IMEmórias")

    def test_extrai_linha_e_ponto_do_bienio(self):
        pedido = roteamento.pedido_circular(
            "Quando que chega o próximo 8084 no ponto do biênio?"
        )

        self.assertEqual(pedido, {"linha": "8084", "destino_ou_ponto": "bienio"})

    def test_extrai_ponto_mesmo_sem_numero_de_linha(self):
        pedido = roteamento.pedido_circular(
            "Quais linhas de ônibus passam pelo ponto do Biênio?"
        )

        self.assertEqual(pedido, {"linha": "", "destino_ou_ponto": "bienio"})

    def test_ponto_conhecido_nao_carrega_sufixo_temporal(self):
        pedido = roteamento.pedido_circular(
            "Quais ônibus estão passando no Biênio esse final de semana?"
        )

        self.assertEqual(pedido, {"linha": "", "destino_ou_ponto": "bienio"})

    def test_origem_conhecida_nao_sobrescreve_parada_explicita(self):
        pedido = roteamento.pedido_circular(
            "Quando chega o 8084 na Av. Afrânio Peixoto, saindo do Biênio?"
        )

        self.assertEqual(
            pedido,
            {"linha": "8084", "destino_ou_ponto": "Av. Afrânio Peixoto"},
        )

    def test_lista_em_dois_pontos_nao_vira_trajeto(self):
        pergunta = "Quais ônibus passam no Biênio e na Reitoria?"

        self.assertIsNone(roteamento.pedido_trajeto(pergunta))
        self.assertIsNone(roteamento.pedido_circular(pergunta))

    def test_destino_repetido_nao_inverte_trajeto(self):
        pedido = roteamento.pedido_trajeto(
            "Onde fica o IME e como ir do Metrô ao IME?"
        )

        self.assertEqual(
            pedido,
            {"origem": "metro_butanta", "destino_ou_ponto": "ime"},
        )

    def test_preconsulta_recupera_ponto_inequivoco_associado_a_linha(self):
        registro = Mock()
        registro.nomes = {"consultar_circulares"}
        registro.executar_direto.return_value = ("Sem serviço hoje.", ["sptrans"])
        historico = [
            {
                "pergunta": "Quais ônibus passam no ponto do Biênio?",
                "resposta": "Passam 8012-10 e 8084-10.",
            },
            {
                "pergunta": "Quanto tempo leva do metrô ao IME?",
                "resposta": "Cerca de 20 minutos.",
            },
        ]

        roteamento.preconsultar(
            registro,
            "Quando chega o próximo 8084 hoje?",
            historico,
        )

        registro.executar_direto.assert_called_once_with(
            "consultar_circulares",
            detalhes=False,
            _pergunta="Quando chega o próximo 8084 hoje?",
            _historico=historico,
            linha="8084",
            destino_ou_ponto="bienio",
        )

    def test_preconsulta_nao_chuta_entre_dois_locais_do_turno_associado(self):
        registro = Mock()
        registro.nomes = {"consultar_circulares"}
        registro.executar_direto.return_value = (
            "Em qual parada você quer consultar?",
            [],
        )
        historico = [
            {
                "pergunta": "O 8084 vai do Metrô Butantã ao Biênio?",
                "resposta": "Sim, nesse sentido.",
            }
        ]

        roteamento.preconsultar(
            registro,
            "Quando chega o próximo 8084 hoje?",
            historico,
        )

        registro.executar_direto.assert_called_once_with(
            "consultar_circulares",
            detalhes=False,
            _pergunta="Quando chega o próximo 8084 hoje?",
            _historico=historico,
            linha="8084",
            destino_ou_ponto="",
        )

    def test_ponto_explicito_atual_prevalece_sobre_historico(self):
        registro = Mock()
        registro.nomes = {"consultar_circulares"}
        registro.executar_direto.return_value = ("Chega às 21:04.", ["sptrans"])
        historico = [
            {
                "pergunta": "Quais ônibus passam no Biênio?",
                "resposta": "O 8084-10 passa lá.",
            }
        ]

        roteamento.preconsultar(
            registro,
            "Quando chega o 8084 na Reitoria?",
            historico,
        )

        self.assertEqual(
            registro.executar_direto.call_args.kwargs["destino_ou_ponto"],
            "reitoria",
        )

    def test_preconsulta_executa_ferramenta_sem_modelo(self):
        registro = Mock()
        registro.nomes = {"consultar_circulares"}
        registro.executar_direto.return_value = ("Chega às 21:04.", ["sptrans"])

        resultado = roteamento.preconsultar(
            registro, "Quando chega o 8084 no ponto do biênio?"
        )

        registro.executar_direto.assert_called_once_with(
            "consultar_circulares",
            detalhes=False,
            _pergunta="Quando chega o 8084 no ponto do biênio?",
            linha="8084",
            destino_ou_ponto="bienio",
        )
        self.assertEqual(
            resultado,
            ("Chega às 21:04.", ["sptrans"], "consultar_circulares", None),
        )


if __name__ == "__main__":
    unittest.main()
