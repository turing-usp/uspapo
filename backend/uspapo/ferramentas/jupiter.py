"""Acesso ao JupiterWeb: o encanamento que disciplinas.py e curriculo.py usam.

Este módulo não registra ferramenta nenhuma. Ele só resolve os três problemas
que as duas páginas do JupiterWeb têm em comum:

1. **Charset.** Tudo lá é ISO-8859-1 e o servidor às vezes não deixa isso claro
   o bastante para o `requests` acertar sozinho. Palpite errado transforma
   "Cálculo" em "CÃ¡lculo" na cara do aluno, então o encoding é fixado à mão.

2. **HTML de 1999.** As páginas são sopa de `<table>` com `<font>` dentro. Não
   existe classe nem id para agarrar: o jeito de ler é achatar tudo em texto (ou
   em lista de células, na ordem) e fatiar pelos rótulos.

3. **DWR.** A grade curricular não vem em HTML nenhum: a jupCarreira.jsp chega
   com os `<select>` vazios e quem preenche é o JavaScript, por Direct Web
   Remoting. É o mesmo protocolo que o bandejao.py fala com o RUCard, só que
   aqui os alvos são vários, então vale um cliente genérico.

O parser do DWR (`registros`) merece uma nota. A resposta é JavaScript, não
JSON: as chaves vêm sem aspas. Mas os valores são SEMPRE string JSON ou `null`,
e é isso que salva: varrendo o texto em ordem com uma regex que casa o par
inteiro, o motor sempre retoma DEPOIS da aspa de fechamento, e o miolo das
strings nunca é lido como se fosse estrutura. Sem isso o `objcur` do
pubObterInfoCurso, que é HTML cheio de `:` e `,`, quebraria tudo.
"""

import html
import json
import re
import time

import requests

BASE = "https://uspdigital.usp.br/jupiterweb/"
URL_DWR = BASE + "dwr/call/plaincall/ControlePublicoDWR.{metodo}.dwr"

TIMEOUT = 12

# O JupiterWeb é lento e os dados são estáveis. Meia hora para o que muda dentro
# do semestre (turma, vaga), seis horas para o que muda de ano em ano (catálogo
# de cursos, grade curricular).
TTL_CURTO = 1800
TTL_LONGO = 21600

# Numa página de erro do JupiterWeb o aviso vem sozinho nesta div. É o único
# lugar da página com id próprio, então é por ele que se distingue erro de dado.
# Atenção ao ler o que sai daqui: essas mensagens vêm com "?" no lugar dos
# acentos ("Disciplina n?o tem requisitos"), porque o servidor as escreve num
# charset e serve a página noutro. Quem casa contra elas tem que casar sem
# acento, e quem repassa o texto ao modelo devia reescrevê-lo antes.
_MENSAGEM = re.compile(r'<div id="web_mensagem">(.*?)</div>', re.S | re.I)

_INGLES = re.compile(r"<i\b.*?</i>", re.S | re.I)
_INVISIVEL = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_CELULA = re.compile(r"<t[dh]\b[^>]*>(.*?)(?=</t[dh]>|<t[dh]\b|</tr>|$)", re.S | re.I)
_LINHA = re.compile(r"<tr\b[^>]*>(.*?)(?=<tr\b|</table>|$)", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")

# Um par `chave:valor` da resposta do DWR. Ver a nota no topo do módulo.
_PAR = re.compile(r'(\w+):(null|"(?:[^"\\]|\\.)*")')

_CACHE: dict[tuple, tuple[float, object]] = {}


# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────
def cache(chave: tuple, ttl: int, produzir):
    """Memo por TTL, compartilhado entre as ferramentas do JupiterWeb.

    Sem lock, pelo mesmo motivo do bandejão: atribuição em dict é atômica e dois
    workers produzindo o mesmo valor ao mesmo tempo é desperdício, não erro.
    """
    guardado = _CACHE.get(chave)
    if guardado and (time.monotonic() - guardado[0]) < ttl:
        return guardado[1]

    valor = produzir()
    _CACHE[chave] = (time.monotonic(), valor)
    return valor


# ─────────────────────────────────────────────
# Páginas HTML
# ─────────────────────────────────────────────
def pagina(caminho: str, **params) -> str:
    """GET numa página do JupiterWeb, já decodificada como ISO-8859-1."""
    resposta = requests.get(BASE + caminho, params=params, timeout=TIMEOUT)
    resposta.raise_for_status()
    # Fixado à mão de propósito: o palpite do requests aqui sai caro.
    resposta.encoding = "iso-8859-1"
    return resposta.text


def url(caminho: str, **params) -> str:
    """A URL que o aluno consegue abrir, para devolver como fonte."""
    query = "&".join(f"{chave}={valor}" for chave, valor in params.items())
    return f"{BASE}{caminho}?{query}" if query else BASE + caminho


def mensagem(bruto: str) -> str | None:
    """O aviso da página de erro do JupiterWeb, ou None se a página é de dado.

    O JupiterWeb responde 200 para tudo: disciplina inexistente, sigla curta,
    sem oferecimento. A diferença está só neste bloco.
    """
    achado = _MENSAGEM.search(bruto)
    return achatar(achado.group(1)) or None if achado else None


def sem_ingles(bruto: str) -> str:
    """Tira a tradução em inglês da ficha da disciplina.

    Cada ementa, objetivo e programa aparece duas vezes na página: em português
    e, logo abaixo, em inglês dentro de <i>. O aluno pergunta em português e o
    inglês custaria o dobro de token pela mesma informação.
    """
    return _INGLES.sub("", bruto)


def achatar(bruto: str) -> str:
    """Tira tags e entidades e normaliza o espaço em branco."""
    return " ".join(html.unescape(_TAG.sub(" ", _INVISIVEL.sub("", bruto))).split())


def celulas(bruto: str) -> list[str]:
    """O texto de cada <td>/<th>, na ordem em que aparecem.

    É assim que se lê essa sopa de tabela: o rótulo cai numa célula e o valor na
    seguinte, sem nenhuma classe ou id para agarrar.
    """
    limpo = _INVISIVEL.sub("", bruto)
    return [achatar(conteudo) for conteudo in _CELULA.findall(limpo)]


def linhas(bruto: str) -> list[list[str]]:
    """As células de cada <tr>, agrupadas por linha.

    Onde a tabela tem forma — vagas, horários — a linha é o que distingue um
    registro do outro, e quantas células ela tem é o que distingue um total de
    um detalhe. Achatar isso num fluxo único de células perderia justamente essa
    informação.
    """
    limpo = _INVISIVEL.sub("", bruto)
    return [celulas(conteudo) for conteudo in _LINHA.findall(limpo)]


# ─────────────────────────────────────────────
# DWR
# ─────────────────────────────────────────────
def registros(js: str) -> list[dict]:
    """Lê a lista (ou o objeto) que o DWR devolveu dentro do handleCallback.

    Um par `chave:valor` cuja chave já apareceu abre um registro novo — é o que
    marca a fronteira entre os itens, já que aqui não dá para confiar em `},{`.
    """
    inicio = js.find("handleCallback")
    if inicio < 0:
        return []

    saida: list[dict] = []
    atual: dict = {}

    for chave, literal in _PAR.findall(js[inicio:]):
        if chave in atual:
            saida.append(atual)
            atual = {}
        try:
            atual[chave] = None if literal == "null" else json.loads(literal)
        except json.JSONDecodeError:
            atual[chave] = None

    if atual:
        saida.append(atual)
    return saida


def dwr(metodo: str, alvo: str, argumentos: dict) -> list[dict]:
    """Chama ControlePublicoDWR.listar/obter e devolve os registros lidos.

    O `alvo` é o nome da consulta do lado do servidor (pubGradeCurricular,
    pubListarColegiado...) e os `argumentos` viram o objeto que ela recebe. Sem
    o instanceId o DWR responde exceção e nada mais, igual ao do RUCard.
    """
    linhas = [
        "callCount=1",
        "windowName=",
        "c0-id=0",
        "c0-scriptName=ControlePublicoDWR",
        f"c0-methodName={metodo}",
        f"c0-param0=string:{alvo}",
    ]
    referencias = []
    for posicao, (chave, valor) in enumerate(argumentos.items(), 1):
        linhas.append(f"c0-e{posicao}=string:{valor}")
        referencias.append(f"{chave}:reference:c0-e{posicao}")

    linhas += [
        "c0-param1=Object_Object:{" + ", ".join(referencias) + "}",
        "batchId=0",
        "instanceId=0",
        "page=%2Fjupiterweb%2FjupCarreira.jsp",
        "scriptSessionId=",
        "",
    ]

    resposta = requests.post(
        URL_DWR.format(metodo=metodo),
        data="\n".join(linhas).encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return registros(resposta.text)
