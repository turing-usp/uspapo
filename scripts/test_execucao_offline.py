"""T0: verifica a barreira com eventos sintéticos, sem operações proibidas.

O callback é capturado no lugar de instalar outro audit hook. Os caminhos e
descritores abaixo são somente argumentos do callback; não são abertos,
truncados, removidos, conectados nem usados para iniciar processos.
"""

import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import testar_offline as offline


class TestBarreiraOffline(unittest.TestCase):
    def setUp(self):
        self.temporaria = Path(tempfile.gettempdir()) / "barreira-sintetica"
        self.dentro = self.temporaria / "arquivo.json"
        self.fora = offline.RAIZ / "data" / "index" / "ledger_avancado.json"
        with patch.object(offline.sys, "addaudithook") as instalar:
            self.violacoes = offline.instalar_barreira(self.temporaria)
        instalar.assert_called_once()
        self.auditar = instalar.call_args.args[0]

    def bloquear(self, evento, argumentos):
        anteriores = len(self.violacoes)
        with self.assertRaises(offline.ViolacaoOffline) as captura:
            self.auditar(evento, argumentos)
        self.assertEqual(len(self.violacoes), anteriores + 1)
        self.assertIn(evento, self.violacoes[-1])
        return str(captura.exception)

    def test_leitura_do_corpus_e_permitida(self):
        self.auditar("open", (str(self.fora), "r", os.O_RDONLY))
        self.assertEqual(self.violacoes, [])

    def test_escrita_absoluta_no_temporario_e_permitida(self):
        self.auditar("open", (str(self.dentro), "w", os.O_WRONLY | os.O_CREAT))
        self.auditar("open", (os.fsencode(self.dentro), "a", os.O_APPEND))
        self.assertEqual(self.violacoes, [])

    def test_modos_de_escrita_no_repositorio_sao_bloqueados(self):
        for modo in ("w", "a", "x", "r+", "w+b"):
            with self.subTest(modo=modo):
                self.bloquear("open", (str(self.fora), modo, 0))

    def test_flags_de_escrita_sem_modo_sao_bloqueadas(self):
        for flag in (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_TRUNC, os.O_APPEND):
            with self.subTest(flag=flag):
                self.bloquear("open", (str(self.fora), None, flag))

    def test_prefixo_irmao_e_travessia_nao_entram_no_temporario(self):
        caminhos = (
            self.temporaria.with_name(self.temporaria.name + "-irma") / "saida",
            self.temporaria / ".." / "fora.json",
        )
        for caminho in caminhos:
            with self.subTest(caminho=caminho.name):
                self.bloquear("open", (str(caminho), "w", os.O_WRONLY))

    def test_abertura_relativa_nao_pode_ocultar_dir_fd(self):
        self.bloquear("open", ("arquivo.json", "w", os.O_WRONLY))

    def test_nul_e_outros_destinos_relativos_continuam_bloqueados(self):
        for caminho in ("nul", "NUL", "./nul", "arquivo.json", "data/index/cota_embeddings.json"):
            with self.subTest(caminho=caminho):
                self.bloquear("open", (caminho, "w", os.O_WRONLY))

    def test_arquivos_de_ambiente_sao_bloqueados_na_leitura(self):
        for nome in (".env", ".env.local", ".env.example", ".ENV"):
            with self.subTest(nome=nome):
                self.bloquear("open", (str(self.temporaria / nome), "r", 0))

    def test_mutacoes_de_arquivo_operacional_sao_bloqueadas(self):
        eventos = (
            ("os.remove", (str(self.fora), -1)),
            ("os.rmdir", (str(self.fora.parent), -1)),
            ("os.mkdir", (str(self.fora.parent), 0o700, -1)),
            ("os.chmod", (str(self.fora), 0o600, -1)),
            ("os.utime", (str(self.fora), None, None, -1)),
            ("os.chown", (str(self.fora), 1, 1, -1)),
            ("os.truncate", (str(self.fora), 0)),
            ("os.chflags", (str(self.fora), 0)),
        )
        for evento, argumentos in eventos:
            with self.subTest(evento=evento):
                self.bloquear(evento, argumentos)

    def test_criacao_e_limpeza_do_temporario_sao_permitidas(self):
        self.auditar("os.mkdir", (str(self.temporaria), 0o700, -1))
        self.auditar("os.remove", (str(self.dentro), -1))
        self.auditar("os.rmdir", (str(self.temporaria), -1))
        self.assertEqual(self.violacoes, [])

    def test_rename_e_hardlink_conferem_as_duas_pontas(self):
        for evento in ("os.rename", "os.link"):
            for origem, destino in ((self.fora, self.dentro), (self.dentro, self.fora)):
                with self.subTest(evento=evento, origem_externa=origem == self.fora):
                    self.bloquear(evento, (str(origem), str(destino), -1, -1))
        self.auditar("os.rename", (str(self.dentro), str(self.dentro) + ".tmp", -1, -1))

    def test_symlink_nao_aponta_para_fora(self):
        self.bloquear("os.symlink", (str(self.fora), str(self.dentro), -1))
        self.bloquear("os.symlink", ("../fora.json", str(self.dentro), -1))
        self.auditar("os.symlink", ("outro.json", str(self.dentro), -1))

    def test_dir_fd_resolvido_dentro_permite_limpeza_relativa(self):
        with patch.object(offline, "_caminho_descritor", return_value=str(self.temporaria)):
            self.auditar("os.remove", ("arquivo.json", 999))
        self.assertEqual(self.violacoes, [])

    def test_dir_fd_externo_ou_desconhecido_e_bloqueado(self):
        for destino in (str(self.fora.parent), None):
            with self.subTest(verificavel=destino is not None):
                with patch.object(offline, "_caminho_descritor", return_value=destino):
                    self.bloquear("os.remove", ("arquivo.json", 999))

    def test_fd_de_escrita_precisa_ter_destino_temporario_verificado(self):
        with patch.object(offline, "_caminho_descritor", return_value=str(self.dentro)):
            self.auditar("open", (999, "w", os.O_WRONLY))
        for destino in (str(self.fora), None):
            with self.subTest(verificavel=destino is not None):
                with patch.object(offline, "_caminho_descritor", return_value=destino):
                    self.bloquear("open", (999, "w", os.O_WRONLY))

    def test_stdout_stderr_permitidos_so_como_saida(self):
        for descritor in (1, 2):
            self.auditar("open", (descritor, "w", os.O_WRONLY))
        with patch.object(offline, "_caminho_descritor", return_value=None):
            self.bloquear("os.truncate", (1, 0))

    def test_eventos_de_rede_sao_bloqueados_sem_chamar_socket(self):
        for evento in (
            "socket.connect", "socket.connect_ex", "socket.getaddrinfo",
            "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
            "socket.sendto", "socket.sendmsg", "socket.bind",
        ):
            with self.subTest(evento=evento):
                self.bloquear(evento, ("argumento-sintetico",))

    def test_processos_sao_bloqueados_sem_iniciar_comandos(self):
        for evento in (
            "subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn",
            "os.exec", "os.fork", "os.forkpty", "os.startfile", "os.startfile/2",
        ):
            with self.subTest(evento=evento):
                self.bloquear(evento, ("argumento-sintetico",))

    def test_banco_persistente_e_registro_sao_bloqueados(self):
        for banco in (str(self.fora), str(self.dentro), "file:estado.db?mode=rwc"):
            with self.subTest(banco=banco.rsplit("/", 1)[-1]):
                self.bloquear("sqlite3.connect", (banco,))
        self.auditar("sqlite3.connect", (":memory:",))
        for evento in (
            "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue",
            "winreg.SetValue", "winreg.LoadKey", "winreg.SaveKey",
        ):
            self.bloquear(evento, ("argumento-sintetico",))

    def test_argumentos_nao_aparecem_em_mensagem_ou_registro(self):
        marcador = "conteudo-sensivel-sintetico-123"
        mensagem = self.bloquear("subprocess.Popen", (marcador,))
        self.assertNotIn(marcador, mensagem)
        self.assertNotIn(marcador, " ".join(self.violacoes))

    def test_stack_registrada_preserva_origem_mais_antiga_que_doze_frames(self):
        def origem_antiga():
            intermediaria(24)

        def intermediaria(profundidade):
            if profundidade:
                intermediaria(profundidade - 1)
            else:
                self.auditar("os.truncate", (str(self.fora), 0))

        with self.assertRaises(offline.ViolacaoOffline) as captura:
            origem_antiga()
        self.assertEqual(len(self.violacoes), 1)
        diagnostico = self.violacoes[0]
        self.assertEqual(str(captura.exception), diagnostico)
        self.assertIn("in origem_antiga", diagnostico)
        self.assertGreaterEqual(diagnostico.count("in intermediaria"), 25)

    def test_stack_exibe_metadados_sem_codigo_fonte_ou_valores_locais(self):
        marcador = "dado-sensivel-sintetico-da-stack"
        quadros = [
            offline.traceback.FrameSummary(
                "origem_sintetica.py", 41, "origem_sintetica",
                lookup_line=False, line=f"token = '{marcador}'",
                locals={"token": marcador},
            ),
            offline.traceback.FrameSummary(
                "barreira_sintetica.py", 60, "negar", lookup_line=False,
            ),
        ]
        with patch.object(offline.traceback, "extract_stack", return_value=quadros) as extrair:
            mensagem = self.bloquear("subprocess.Popen", (marcador,))
        extrair.assert_called_once_with()
        self.assertIn('File "origem_sintetica.py", line 41, in origem_sintetica', mensagem)
        self.assertNotIn(marcador, mensagem)
        self.assertNotIn(marcador, self.violacoes[0])

    def test_stack_original_sobrevive_stoptest_com_violacao_capturada_ou_propagada(self):
        for capturar in (False, True):
            with self.subTest(capturar=capturar):
                with patch.object(offline.sys, "addaudithook") as instalar:
                    violacoes = offline.instalar_barreira(self.temporaria)
                auditar = instalar.call_args.args[0]
                executados = []

                def origem_do_bloqueio():
                    auditar("open", ("arquivo-sintetico.json", "w", os.O_WRONLY))

                class CasoSintetico(unittest.TestCase):
                    def test_a_bloqueado(self):
                        executados.append("primeiro")
                        if capturar:
                            with self.assertRaises(offline.ViolacaoOffline):
                                origem_do_bloqueio()
                        else:
                            origem_do_bloqueio()

                    def test_b_nao_deve_comecar(self):
                        executados.append("segundo")

                resultado = offline.ResultadoOffline(io.StringIO(), True, 0, violacoes=violacoes)
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(CasoSintetico)
                primeiro = next(iter(suite)).id()
                with self.assertRaises(offline.ViolacaoOffline):
                    suite.run(resultado)
                self.assertEqual(executados, ["primeiro"])
                self.assertEqual(resultado.concluidos, [])
                self.assertEqual(resultado.em_execucao, primeiro)
                self.assertEqual(len(violacoes), 1)
                self.assertIn("in origem_do_bloqueio", violacoes[0])
                self.assertIn("in test_a_bloqueado", violacoes[0])
                self.assertIn("open: abertura para escrita exige caminho absoluto", violacoes[0])
                self.assertEqual(offline.codigo_de_saida(resultado, violacoes), 3)

    def test_violacao_capturada_ainda_exige_saida_com_falha(self):
        self.bloquear("os.truncate", (str(self.fora), 0))
        resultado = Mock()
        resultado.wasSuccessful.return_value = True
        self.assertEqual(offline.codigo_de_saida(resultado, self.violacoes), 3)
        resultado.wasSuccessful.assert_not_called()

    def test_fallback_exception_nao_absorve_violacao(self):
        self.assertTrue(issubclass(offline.ViolacaoOffline, KeyboardInterrupt))
        self.assertFalse(issubclass(offline.ViolacaoOffline, Exception))


class TestExecucaoOffline(unittest.TestCase):
    def test_ambiente_nao_herda_secrets_nem_configuracao_do_produto(self):
        ambiente = {
            "PATH": "caminho-local", "TEMP": "temporario-local",
            "PINECONE_API_KEY": "valor-sintetico", "LLM_PROVIDERS": "[]",
            "SUPABASE_SERVICE_KEY": "valor-sintetico", "SPTRANS_TOKEN": "valor-sintetico",
            "CHUNK_ALVO": "9999", "HTTP_PROXY": "valor-sintetico",
        }
        with patch.object(offline.os, "environ", ambiente):
            offline.preparar_ambiente()
        self.assertEqual(set(ambiente), {
            "PATH", "TEMP", "PYTHON_DOTENV_DISABLED",
            "PYTHONDONTWRITEBYTECODE", "SPTRANS_TOKEN",
        })
        self.assertEqual(ambiente["PYTHON_DOTENV_DISABLED"], "1")
        self.assertEqual(ambiente["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(ambiente["SPTRANS_TOKEN"], "")

    def test_resultado_sem_violacao_distingue_sucesso_e_falha(self):
        resultado = Mock()
        resultado.wasSuccessful.return_value = True
        self.assertEqual(offline.codigo_de_saida(resultado, []), 0)
        resultado.wasSuccessful.return_value = False
        self.assertEqual(offline.codigo_de_saida(resultado, []), 1)

    def test_progresso_separa_concluido_de_interrompido(self):
        resultado = offline.ResultadoOffline(io.StringIO(), True, 0)
        concluido = unittest.FunctionTestCase(lambda: None, description="concluido")
        pendente = unittest.FunctionTestCase(lambda: None, description="pendente")
        resultado.startTest(concluido)
        resultado.addSuccess(concluido)
        resultado.stopTest(concluido)
        resultado.startTest(pendente)
        self.assertEqual(resultado.concluidos, [(concluido.id(), "ok")])
        self.assertEqual(resultado.em_execucao, pendente.id())

    def test_progresso_inclui_teste_com_subteste_reprovado(self):
        class CasoSintetico(unittest.TestCase):
            def runTest(self):
                with self.subTest(caso="sintetico"):
                    self.fail("falha prevista para verificar o registro")

        resultado = offline.ResultadoOffline(io.StringIO(), True, 0)
        caso = CasoSintetico()
        caso.run(resultado)
        self.assertEqual(resultado.concluidos, [(caso.id(), "falha")])
        self.assertIsNone(resultado.em_execucao)

    def test_violacao_capturada_interrompe_antes_do_proximo_teste(self):
        violacoes = []
        executados = []

        class CasoSintetico(unittest.TestCase):
            def test_a_captura(self):
                executados.append("primeiro")
                # Simula a lista que o callback preencheria ANTES de levantar.
                # Não instala hook nem tenta qualquer operação proibida.
                violacoes.append("evento sintético bloqueado")
                with self.assertRaises(offline.ViolacaoOffline):
                    raise offline.ViolacaoOffline("violação sintética")

            def test_b_nao_deve_comecar(self):
                executados.append("segundo")

        resultado = offline.ResultadoOffline(io.StringIO(), True, 0, violacoes=violacoes)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CasoSintetico)
        primeiro = next(iter(suite)).id()
        with self.assertRaises(offline.ViolacaoOffline):
            suite.run(resultado)
        self.assertEqual(executados, ["primeiro"])
        self.assertEqual(resultado.concluidos, [])
        self.assertEqual(resultado.em_execucao, primeiro)


if __name__ == "__main__":
    unittest.main()
