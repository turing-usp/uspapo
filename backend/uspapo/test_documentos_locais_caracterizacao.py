"""T5 documental: comportamento atual de roteamento com corpus temporário.

Nenhum cliente externo é criado. Cada teste instala um cache novo em torno da
função original, sem limpar ou preencher o cache de títulos já existente.
Executar pelo runner offline, que restringe as escritas à sua própria pasta.
"""

import builtins
from contextlib import ExitStack
from functools import lru_cache
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from uspapo import roteamento


class TestCaminhoDocumental(unittest.TestCase):
    def test_raiz_e_corpus_sao_resolvidos_a_partir_do_modulo(self):
        raiz = Path(roteamento.__file__).resolve().parents[2]
        self.assertEqual(Path(roteamento.RAIZ), raiz)
        self.assertEqual(Path(roteamento.PASTA_PROCESSADOS), raiz / "data" / "processed")


class TestDocumentosLocais(unittest.TestCase):
    def setUp(self):
        self.temporaria = TemporaryDirectory()
        self.addCleanup(self.temporaria.cleanup)
        self.pasta = Path(self.temporaria.name)
        self.cache_original = roteamento.catalogo_titulos
        self.estado_original = self.cache_original.cache_info()
        self.addCleanup(self._confirmar_cache_original_preservado)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.catalogo = lru_cache(maxsize=1)(self.cache_original.__wrapped__)
        self.patches.enter_context(patch.object(roteamento, "PASTA_PROCESSADOS", str(self.pasta)))
        self.patches.enter_context(patch.object(roteamento, "catalogo_titulos", self.catalogo))

    def _confirmar_cache_original_preservado(self):
        self.assertIs(roteamento.catalogo_titulos, self.cache_original)
        self.assertEqual(self.cache_original.cache_info(), self.estado_original)

    def gravar(self, nome, paginas):
        caminho = self.pasta / nome
        caminho.write_text(json.dumps(paginas, ensure_ascii=False), encoding="utf-8")
        return caminho

    def pagina(self, titulo="Aurora", url="https://corpus.invalid/aurora", texto="Corpo inicial."):
        return {"titulo": titulo, "url": url, "texto_limpo": texto}

    def test_catalogo_normaliza_titulos_mas_guarda_so_metadados(self):
        self.gravar("unidade.json", [
            self.pagina("  IMEmórias  ", "https://corpus.invalid/imemorias", "Texto extenso."),
            self.pagina("IME", "https://corpus.invalid/curto"),
            self.pagina("", "https://corpus.invalid/sem-titulo"),
            self.pagina("Sem URL", ""),
            self.pagina("Sem texto", texto=""),
            self.pagina("Texto nulo", texto=None),
            self.pagina("Nóvo", "https://corpus.invalid/novo"),
        ])
        self.assertEqual(self.catalogo(), {
            "imemorias": [{
                "titulo": "IMEmórias", "url": "https://corpus.invalid/imemorias",
                "arquivo": "unidade.json",
            }],
            "novo": [{
                "titulo": "Nóvo", "url": "https://corpus.invalid/novo",
                "arquivo": "unidade.json",
            }],
        })

    def test_catalogo_preserva_ordem_dos_arquivos_e_das_paginas(self):
        self.gravar("z.json", [self.pagina(url="https://corpus.invalid/z")])
        self.gravar("a.json", [
            self.pagina(url="https://corpus.invalid/a1"),
            self.pagina(url="https://corpus.invalid/a2"),
        ])
        self.assertEqual(
            [pagina["url"] for pagina in self.catalogo()["aurora"]],
            ["https://corpus.invalid/a1", "https://corpus.invalid/a2", "https://corpus.invalid/z"],
        )

    def test_catalogo_ignora_json_invalido_raiz_nao_lista_e_arquivos_nao_json(self):
        self.gravar("valido.json", [self.pagina()])
        (self.pasta / "invalido.json").write_text("{ inválido", encoding="utf-8")
        self.gravar("objeto.json", {"titulo": "Não é lista"})
        self.gravar("ignorado.txt", [self.pagina("Ignorado")])
        self.gravar("maiusculo.JSON", [self.pagina("Maiúsculo")])
        (self.pasta / "diretorio.json").mkdir()
        subpasta = self.pasta / "subpasta"
        subpasta.mkdir()
        (subpasta / "interno.json").write_text(
            json.dumps([self.pagina("Interno")]), encoding="utf-8"
        )
        self.assertEqual(set(self.catalogo()), {"aurora"})

    def test_falha_de_leitura_de_um_arquivo_nao_elimina_os_outros(self):
        self.gravar("bloqueado.json", [self.pagina("Bloqueado")])
        self.gravar("valido.json", [self.pagina()])

        def abrir(caminho, *args, **kwargs):
            if os.path.basename(caminho) == "bloqueado.json":
                raise PermissionError("falha de leitura simulada")
            return builtins.open(caminho, *args, **kwargs)

        with patch.object(roteamento, "open", side_effect=abrir, create=True):
            self.assertEqual(set(self.catalogo()), {"aurora"})

    def test_corpus_ausente_retorna_vazio_e_cacheia_o_resultado(self):
        ausente = self.pasta / "ainda-ausente"
        with patch.object(roteamento, "PASTA_PROCESSADOS", str(ausente)):
            vazio = self.catalogo()
            self.assertEqual(vazio, {})
            ausente.mkdir()
            (ausente / "novo.json").write_text(
                json.dumps([self.pagina()]), encoding="utf-8"
            )
            self.assertIs(self.catalogo(), vazio)
            self.assertEqual(self.catalogo(), {})
            self.catalogo.cache_clear()  # Apenas o wrapper criado por este teste.
            self.assertEqual(set(self.catalogo()), {"aurora"})

    def test_correspondencia_real_remove_pergunta_acentos_e_caixa(self):
        self.gravar("ime.json", [self.pagina(
            "IMEmórias", "https://corpus.invalid/imemorias", "  Introdução.\n\nOutro parágrafo.  "
        )])
        esperado = {
            "titulo": "IMEmórias", "url": "https://corpus.invalid/imemorias",
            "texto": "Introdução.\n\nOutro parágrafo.",
        }
        for pergunta in ("O que é o imemórias?", "EXPLIQUE IMEMÓRIAS!", "Sobre IMEmórias"):
            with self.subTest(pergunta=pergunta):
                self.assertEqual(roteamento.pagina_por_titulo(pergunta), esperado)

    def test_tipo_de_entidade_so_e_removido_quando_nao_ha_candidato_exato(self):
        self.gravar("projetos.json", [
            self.pagina("Projeto Aurora", "https://corpus.invalid/projeto"),
            self.pagina("Aurora", "https://corpus.invalid/aurora"),
        ])
        self.assertEqual(
            roteamento.pagina_por_titulo("Explique o projeto Aurora")["url"],
            "https://corpus.invalid/projeto",
        )
        self.assertEqual(
            roteamento.pagina_por_titulo("Explique a iniciativa Aurora")["url"],
            "https://corpus.invalid/aurora",
        )

    def test_titulo_exato_ambiguo_nao_cai_para_entidade_mais_generica(self):
        self.gravar("ambiguos.json", [
            self.pagina("Projeto Aurora", "https://corpus.invalid/primeiro"),
            self.pagina("PROJETO AURORA", "https://corpus.invalid/segundo"),
            self.pagina("Aurora"),
        ])
        self.assertIsNone(roteamento.pagina_por_titulo("Explique o projeto Aurora"))

    def test_duas_ocorrencias_da_mesma_url_tambem_sao_ambiguas(self):
        self.gravar("a.json", [self.pagina()])
        self.gravar("b.json", [self.pagina()])
        self.assertEqual(len(self.catalogo()["aurora"]), 2)
        self.assertIsNone(roteamento.pagina_por_titulo("Aurora"))

    def test_pergunta_vazia_titulo_ausente_e_correspondencia_parcial_retornam_none(self):
        self.gravar("titulos.json", [self.pagina()])
        for pergunta in ("", "O que é?", "Ausente", "Aur", "Aurora detalhes"):
            with self.subTest(pergunta=pergunta):
                self.assertIsNone(roteamento.pagina_por_titulo(pergunta))

    def test_chave_do_titulo_preserva_ligacoes_pontuacao_e_espaco_interno(self):
        self.gravar("titulos.json", [
            self.pagina("Memória USP", "https://corpus.invalid/normal"),
            self.pagina("Projeto de Memória", "https://corpus.invalid/ligacao"),
            self.pagina("Memória-USP", "https://corpus.invalid/hifen"),
            self.pagina("Memória  USP", "https://corpus.invalid/espacos"),
        ])
        self.assertEqual(set(self.catalogo()), {
            "memoria usp", "projeto de memoria", "memoria-usp", "memoria  usp",
        })
        # A pergunta é tokenizada, mas a chave do catálogo só perde acentos e
        # caixa. Esta assimetria é comportamento atual, não matching aproximado.
        self.assertEqual(
            roteamento.pagina_por_titulo("Memória-USP")["url"],
            "https://corpus.invalid/normal",
        )
        self.assertIsNone(roteamento.pagina_por_titulo("Projeto de Memória"))

    def test_indice_cacheado_preserva_titulo_mas_corpo_e_relido(self):
        self.gravar("pagina.json", [self.pagina()])
        catalogo = self.catalogo()
        self.assertEqual(roteamento.pagina_por_titulo("Aurora")["texto"], "Corpo inicial.")
        self.gravar("pagina.json", [self.pagina("Novo Título", texto="Corpo atualizado.")])
        self.assertIs(self.catalogo(), catalogo)
        self.assertEqual(roteamento.pagina_por_titulo("Aurora"), {
            "titulo": "Aurora", "url": "https://corpus.invalid/aurora",
            "texto": "Corpo atualizado.",
        })
        self.assertIsNone(roteamento.pagina_por_titulo("Novo Título"))
        self.assertEqual(self.catalogo.cache_info().maxsize, 1)
        self.assertEqual(self.catalogo.cache_info().currsize, 1)
        self.catalogo.cache_clear()
        self.assertIsNone(roteamento.pagina_por_titulo("Aurora"))
        self.assertEqual(roteamento.pagina_por_titulo("Novo Título")["texto"], "Corpo atualizado.")

    def test_arquivo_removido_depois_do_catalogo_retorna_none(self):
        caminho = self.gravar("pagina.json", [self.pagina()])
        self.catalogo()
        caminho.unlink()
        self.assertIsNone(roteamento.pagina_por_titulo("Aurora"))

    def test_arquivo_corrompido_ou_raiz_nao_lista_depois_do_catalogo_retorna_none(self):
        caminho = self.gravar("pagina.json", [self.pagina()])
        self.catalogo()
        for conteudo in ("{ inválido", "{}", "null"):
            with self.subTest(conteudo=conteudo):
                caminho.write_text(conteudo, encoding="utf-8")
                self.assertIsNone(roteamento.pagina_por_titulo("Aurora"))

    def test_url_removida_do_arquivo_nao_e_substituida_por_outro_documento(self):
        self.gravar("pagina.json", [self.pagina()])
        self.catalogo()
        self.gravar("pagina.json", [self.pagina(url="https://corpus.invalid/outra")])
        self.assertIsNone(roteamento.pagina_por_titulo("Aurora"))

    def test_url_e_aparada_no_catalogo_mas_comparacao_do_documento_e_literal(self):
        self.gravar("pagina.json", [self.pagina(url=" https://corpus.invalid/aurora ")])
        self.assertEqual(self.catalogo()["aurora"][0]["url"], "https://corpus.invalid/aurora")
        self.assertIsNone(roteamento.pagina_por_titulo("Aurora"))

    def test_texto_so_com_espacos_entra_no_catalogo_e_retorna_corpo_vazio(self):
        self.gravar("pagina.json", [self.pagina(texto=" \n\t ")])
        self.assertEqual(set(self.catalogo()), {"aurora"})
        self.assertEqual(roteamento.pagina_por_titulo("Aurora")["texto"], "")

    def test_elemento_nao_objeto_na_lista_nao_e_silenciado(self):
        self.gravar("pagina.json", [None])
        with self.assertRaises(AttributeError):
            self.catalogo()


if __name__ == "__main__":
    unittest.main()
