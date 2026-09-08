"""Executa unittest sem credenciais, rede ou escrita no estado do projeto.

Uso: python -B scripts/testar_offline.py [modulo_de_teste ...]
Sem argumentos, descobre os test_*.py de backend, embeddings e scripts.
Uma tentativa proibida interrompe a execução, mesmo dentro de um try/except
Exception do produto. Arquivos de teste só podem ser escritos no diretório
temporário exclusivo desta execução.
"""

import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import socket
import tempfile
import traceback
import unittest
from unittest.mock import patch


RAIZ = Path(__file__).resolve().parents[1]


class ViolacaoOffline(KeyboardInterrupt):
    """Interrompe unittest e não é absorvida pelos fallbacks da aplicação."""


def _caminho_descritor(descritor: int) -> str | None:
    """Resolve descritores POSIX sem autorizar destinos desconhecidos.

    O shutil usa dir_fd para limpar TemporaryDirectory no Linux. No Windows,
    onde esta resolução não está disponível, um descritor desconhecido é negado.
    """
    for base in ("/proc/self/fd", "/dev/fd"):
        try:
            destino = os.readlink(f"{base}/{descritor}")
        except OSError:
            continue
        if os.path.isabs(destino):
            return destino
    return None


def instalar_barreira(pasta_temporaria: Path) -> list[str]:
    """Instala proteção de testes controlados; não é sandbox de código hostil."""
    permitida = os.path.normcase(os.path.realpath(pasta_temporaria))
    violacoes: list[str] = []

    def negar(evento, motivo):
        # Registra ANTES de levantar: capturar BaseException não torna a
        # execução aprovada. Nenhum argumento potencialmente sensível é salvo.
        descricao = f"{evento}: {motivo}"
        violacoes.append(descricao)
        origem = " > ".join(
            f"{Path(quadro.filename).name}:{quadro.lineno}:{quadro.name}"
            for quadro in traceback.extract_stack(limit=12)[:-1]
        )
        raise ViolacaoOffline(f"{descricao}\n{origem}")

    def conferir_escrita(evento, caminho, dir_fd=None):
        if isinstance(caminho, int):
            caminho = _caminho_descritor(caminho)
            if caminho is None:
                negar(evento, "descritor sem destino verificável")
        elif dir_fd not in (None, -1) and not os.path.isabs(caminho):
            base = _caminho_descritor(dir_fd)
            if base is None:
                negar(evento, "dir_fd sem destino verificável")
            caminho = os.path.join(base, os.fsdecode(caminho))
        destino = os.path.normcase(os.path.realpath(os.fsdecode(caminho)))
        try:
            dentro = os.path.commonpath((permitida, destino)) == permitida
        except ValueError:
            dentro = False
        if not dentro:
            negar(evento, "escrita fora do diretório temporário isolado")
        return destino

    def auditar(evento, argumentos):
        if evento in {
            "socket.connect", "socket.connect_ex", "socket.getaddrinfo",
            "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
            "socket.sendmsg", "socket.getnameinfo",
            "socket.bind", "subprocess.Popen", "os.system", "os.posix_spawn",
            "os.spawn", "os.exec", "os.fork", "os.forkpty", "os.startfile",
            "os.startfile/2",
        }:
            negar(evento, "operação externa bloqueada")
        if evento in {
            "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue",
            "winreg.SetValue", "winreg.LoadKey", "winreg.SaveKey",
        }:
            negar(evento, "alteração de estado do sistema bloqueada")
        if evento == "open":
            caminho, modo, flags = argumentos
            if not isinstance(caminho, int):
                nome = os.path.basename(os.fsdecode(caminho)).casefold()
                if nome == ".env" or nome.startswith(".env."):
                    negar(evento, "leitura de arquivo de ambiente bloqueada")
            escrita = bool(modo and any(letra in modo for letra in "wax+"))
            escrita = escrita or bool(flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            ))
            if escrita:
                if isinstance(caminho, int) and caminho in (1, 2):
                    return  # Saída do runner, nunca truncamento ou chmod.
                # O evento open omite o dir_fd de os.open. Exigir caminho
                # absoluto evita validar contra o cwd e escrever via outro fd.
                if not isinstance(caminho, int) and not os.path.isabs(caminho):
                    negar(evento, "abertura para escrita exige caminho absoluto")
                conferir_escrita(evento, caminho)
        elif evento in {"os.remove", "os.rmdir"}:
            conferir_escrita(evento, argumentos[0], argumentos[1])
        elif evento in {"os.mkdir", "os.chmod"}:
            conferir_escrita(evento, argumentos[0], argumentos[2])
        elif evento in {"os.utime", "os.chown"}:
            conferir_escrita(evento, argumentos[0], argumentos[3])
        elif evento in {"os.truncate", "os.chflags"}:
            conferir_escrita(evento, argumentos[0])
        elif evento in {"os.rename", "os.link"}:
            conferir_escrita(evento, argumentos[0], argumentos[2])
            conferir_escrita(evento, argumentos[1], argumentos[3])
        elif evento == "os.symlink":
            destino = conferir_escrita(evento, argumentos[1], argumentos[2])
            origem = os.fsdecode(argumentos[0])
            if not os.path.isabs(origem):
                origem = os.path.join(os.path.dirname(destino), origem)
            conferir_escrita(evento, origem)
        elif evento == "sqlite3.connect" and argumentos[0] != ":memory:":
            # URIs podem apontar para arquivos; sem interpretar parâmetros e
            # sidecars, só bancos em memória são aceitos nesta suíte offline.
            negar(evento, "banco persistente bloqueado")

    sys.addaudithook(auditar)
    return violacoes


class ResultadoOffline(unittest.TextTestResult):
    """Guarda o progresso para não repetir testes concluídos após um STOP."""

    def __init__(self, *args, violacoes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.violacoes = [] if violacoes is None else violacoes
        self.concluidos: list[tuple[str, str]] = []
        self.em_execucao: str | None = None
        self._estado_subteste: str | None = None

    def startTest(self, test):
        self._conferir_violacoes()
        self.em_execucao = test.id()
        self._estado_subteste = None
        super().startTest(test)

    def stopTest(self, test):
        # Uma falha em subTest não passa por addFailure/addSuccess do pai.
        # Durante interrupção o teste continua pendente, mesmo que um subTest
        # anterior já tenha falhado.
        self._conferir_violacoes()
        if self.em_execucao and self._estado_subteste and sys.exc_info()[0] is None:
            self._registrar(test, self._estado_subteste)
        super().stopTest(test)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._estado_subteste = "falha" if issubclass(err[0], test.failureException) else "erro"

    def _registrar(self, test, estado):
        if self.violacoes:
            return  # A violação capturada mantém este teste pendente no STOP.
        self.concluidos.append((test.id(), estado))
        self.em_execucao = None

    def _conferir_violacoes(self):
        if self.violacoes:
            raise ViolacaoOffline("violação registrada; suíte interrompida na fronteira do teste")

    def addSuccess(self, test):
        super().addSuccess(test)
        self._registrar(test, "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._registrar(test, "falha")

    def addError(self, test, err):
        super().addError(test, err)
        self._registrar(test, "erro")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._registrar(test, "pulado")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._registrar(test, "falha_esperada")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._registrar(test, "sucesso_inesperado")


def codigo_de_saida(resultado, violacoes: list[str]) -> int:
    if violacoes:
        return 3
    return 0 if resultado.wasSuccessful() else 1


def preparar_ambiente() -> None:
    # Não herdar configuração de produto nem credentials do shell. Mantém só
    # o necessário para o interpretador e o sistema operacional local.
    preservar = {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
        "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "PROGRAMDATA", "SYSTEMDRIVE",
    }
    for nome in list(os.environ):
        if nome.upper() not in preservar:
            del os.environ[nome]
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["SPTRANS_TOKEN"] = ""


def main() -> int:
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(RAIZ), str(RAIZ / "backend")]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    preparar_ambiente()

    modulos = sys.argv[1:] or [
        ".".join(caminho.relative_to(RAIZ).with_suffix("").parts)
        for pasta in ("backend", "embeddings", "scripts")
        for caminho in sorted((RAIZ / pasta).rglob("test_*.py"))
    ]
    base_temporaria = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="uspapo-phase3a-", dir=base_temporaria) as nome:
        temporaria = Path(nome).resolve()
        if temporaria.parent != base_temporaria or temporaria == base_temporaria:
            raise RuntimeError("diretório temporário fora da raiz prevista")
        tempfile.tempdir = str(temporaria)
        for variavel in ("TEMP", "TMP", "TMPDIR"):
            os.environ[variavel] = str(temporaria)
        violacoes = instalar_barreira(temporaria)
        resultado = None

        def criar_resultado(*args, **kwargs):
            nonlocal resultado
            resultado = ResultadoOffline(*args, violacoes=violacoes, **kwargs)
            return resultado

        try:
            # urllib3 sonda IPv6 com bind local durante o import. Não é uma
            # integração do produto; neutraliza só essa sonda, mantendo a
            # barreira ativa e todos os clientes externos sob mocks dos testes.
            with patch.object(socket, "has_ipv6", False):
                import urllib3.util.connection  # noqa: F401
            suite = unittest.TestSuite()
            for modulo in modulos:
                print(f"Carregando {modulo}", flush=True)
                suite.addTests(unittest.defaultTestLoader.loadTestsFromName(modulo))
                if violacoes:
                    raise ViolacaoOffline("violação registrada durante importação; carga interrompida")
            unittest.TextTestRunner(verbosity=2, resultclass=criar_resultado).run(suite)
        except ViolacaoOffline as erro:
            print(f"\nSTOP OFFLINE: {erro}", file=sys.stderr)
            print("OFFLINE_VIOLACOES=" + json.dumps(violacoes), file=sys.stderr)
            if resultado is not None:
                print("OFFLINE_CONCLUIDOS=" + json.dumps(resultado.concluidos))
                print("OFFLINE_EM_EXECUCAO=" + str(resultado.em_execucao))
            return 3
        if violacoes:
            print(f"\nSTOP OFFLINE: {len(violacoes)} violação(ões) capturada(s).", file=sys.stderr)
            print("OFFLINE_VIOLACOES=" + json.dumps(violacoes), file=sys.stderr)
            print("OFFLINE_CONCLUIDOS=" + json.dumps(resultado.concluidos))
        return codigo_de_saida(resultado, violacoes)


if __name__ == "__main__":
    raise SystemExit(main())
