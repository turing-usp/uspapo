import unittest
from embeddings.qualidade import motivo_descarte, filtrar_chunks
from embeddings import config_vetor as cfg

class TestQualidade(unittest.TestCase):

    def test_chunk_vazio(self):
        self.assertEqual(motivo_descarte(""), "vazio")
        self.assertEqual(motivo_descarte("   "), "vazio")
        self.assertEqual(motivo_descarte(None), "vazio")

    def test_chunk_curto(self):
        # Texto com menos de 200 caracteres (CHUNK_MIN) e unico_da_pagina=False
        texto_curto = "Este é um texto curto com pouca quantidade de caracteres no total."
        self.assertLess(len(texto_curto), cfg.CHUNK_MIN)
        self.assertEqual(motivo_descarte(texto_curto, unico_da_pagina=False), "curto")

    def test_unico_da_pagina_afrouxa_limiar(self):
        # Texto de ~150 caracteres (entre 120 e 199) com mais de 25 palavras
        palavras = [
            "Aviso", "importante", "do", "CEPEUSP", "para", "todos", "os", "alunos", "inscritos",
            "no", "programa", "de", "atividades", "físicas", "do", "semestre", "atual:", "fiquem",
            "atentos", "ao", "prazo", "final", "de", "rematrícula", "online", "nesta", "semana."
        ]
        texto = " ".join(palavras)
        self.assertGreaterEqual(len(texto), 120)
        self.assertLess(len(texto), cfg.CHUNK_MIN)
        self.assertGreaterEqual(len(palavras), 25)
        # Quando único da página, afrouxa CHUNK_MIN de 200 para 120
        motivo = motivo_descarte(texto, unico_da_pagina=True)
        self.assertIsNone(motivo)

    def test_so_navegacao(self):
        # Linhas curtas <= 30 chars sem pontuação de frase (.!?), > 200 chars no total
        linhas_nav = "\n".join([
            "Cursos do Semestre CEPEUSP",
            "Inscrições para Natação",
            "Infraestrutura Esportiva",
            "Portarias I e II de Acesso",
            "Conjunto Aquático Coberto",
            "Campos de Futebol Areia",
            "Vestiários e Lanchonete",
            "Pista de Atletismo Reaberta",
            "Ginásio Poliesportivo Central"
        ])
        self.assertGreaterEqual(len(linhas_nav), cfg.CHUNK_MIN)
        self.assertEqual(motivo_descarte(linhas_nav), "so_navegacao")

    def test_poucas_palavras(self):
        # > 200 caracteres, mas poucas palavras no total (< 25 palavras)
        palavras_longas = ["desenvolvimento", "infraestrutura", "responsabilidade", "sustentabilidade"]
        texto = " ".join(palavras_longas * 4)  # 16 palavras, > 250 caracteres
        self.assertGreaterEqual(len(texto), cfg.CHUNK_MIN)
        self.assertEqual(motivo_descarte(texto), "poucas_palavras")

    def test_pouca_letra(self):
        # > 200 caracteres e 25+ palavras, mas pouca razão de letras (< 0.55)
        texto_simbolos = "Item 01: R$ 100,00 | Item 02: R$ 200,00 | Item 03: R$ 300,00 | Item 04: R$ 400,00 | Item 05: R$ 500,00 | Item 06: R$ 600,00 | Item 07: R$ 700,00 | Item 08: R$ 800,00 | Item 09: R$ 900,00 | 1234 5678 9012 3456"
        self.assertGreaterEqual(len(texto_simbolos), cfg.CHUNK_MIN)
        self.assertEqual(motivo_descarte(texto_simbolos), "pouca_letra")

    def test_chunk_aprovado(self):
        texto_bom = (
            "O Centro de Práticas Esportivas da Universidade de São Paulo (CEPEUSP) oferece diversas modalidades "
            "esportivas para toda a comunidade universitária e público externo. As inscrições ocorrem semestralmente "
            "através do sistema oficial, sendo necessário apresentar comprovante de vínculo ou documento com foto. "
            "Confira a grade horária completa das turmas de natação, musculação e tênis diretamente na secretaria do clube."
        )
        self.assertGreaterEqual(len(texto_bom), cfg.CHUNK_MIN)
        self.assertIsNone(motivo_descarte(texto_bom))

    def test_filtrar_chunks_com_reaproveitados(self):
        texto_valido = (
            "Aviso de manutenção na piscina olímpica do CEPEUSP durante o final de semana de vestibular da Fuvest. "
            "Todas as raias estarão temporariamente interditadas para limpeza e calibragem dos filtros de água. "
            "As demais instalações do clube funcionarão normalmente nos horários habituais."
        )
        chunks = [
            {"hash_chunk": "abc", "texto": None},  # Reaproveitado do ledger
            {"hash_chunk": "def", "texto": texto_valido},  # Bom (>= 200 chars)
            {"hash_chunk": "ghi", "texto": ""}  # Vazio
        ]
        aprovados, descartes = filtrar_chunks(chunks)
        self.assertEqual(len(aprovados), 2)  # O reaproveitado e o bom
        self.assertIn("vazio", descartes)
        self.assertEqual(descartes["vazio"], 1)

if __name__ == "__main__":
    unittest.main()
