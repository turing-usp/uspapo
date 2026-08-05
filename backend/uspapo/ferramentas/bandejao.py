"""Cardápio dos bandejões do Butantã, direto do RUCard.

A página que o aluno abre é a cardapioSAS.jsp, mas ela NÃO traz o cardápio: o
HTML vem com as células vazias e quem preenche é o JavaScript da própria página,
por uma chamada DWR (Direct Web Remoting). Um GET ali não devolve comida
nenhuma, então quem buscamos aqui é o mesmo endpoint que o navegador buscaria.
As URLs que a ferramenta devolve como fonte continuam sendo as da .jsp, que é a
página que o aluno consegue abrir.

Ao contrário da `buscar_documentos`, esta ferramenta é a MESMA nos dois
backends: não existe versão simulada de cardápio. Por isso este módulo não cria
um `Registro` próprio. Ele expõe uma `registrar(registro)` que os dois entrypoints
chamam com o registro deles.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import requests

from uspapo.ferramentas import Registro, casa, em_lista, normalizar, palavras
from uspapo.prompt import DIAS_SEMANA, FUSO_BR

# A página do aluno, e o endpoint que ela consulta por baixo dos panos.
URL_PAGINA = "https://uspdigital.usp.br/rucard/Jsp/cardapioSAS.jsp?codrtn={codigo}"
URL_DWR = (
    "https://uspdigital.usp.br/rucard/dwr/call/plaincall/"
    "CardapioControleDWR.obterCardapioRestUSP.dwr"
)

# Sem o instanceId o DWR responde IllegalArgumentException e nada mais.
CORPO_DWR = (
    "callCount=1\n"
    "windowName=\n"
    "c0-id=0\n"
    "c0-scriptName=CardapioControleDWR\n"
    "c0-methodName=obterCardapioRestUSP\n"
    "c0-param0=number:{codigo}\n"
    "batchId=0\n"
    "instanceId=0\n"
    "page=%2Frucard%2FJsp%2FcardapioSAS.jsp\n"
    "scriptSessionId=\n"
)

TIMEOUT = 12
# O cardápio muda uma vez por semana; o memo do Registro só vale dentro de uma
# pergunta. Meia hora evita bater no RUCard uma vez por aluno.
TTL = 1800

# Apelido -> (codrtn, nome para exibir).
RESTAURANTES = {
    "central": (6, "Central"),
    "prefeitura": (7, "da Prefeitura (PUSP-CB)"),
    "fisica": (8, "da Física"),
    "quimica": (9, "da Química"),
}

# Palavras que dizem "isto é um restaurante" sem dizer QUAL. Somem antes de
# comparar, senão "ru da física" nunca casaria com "da Física".
GENERICAS = frozenset(
    "ru rus bandejao bandejoes bandeco bandex restaurante restaurantes "
    "refeitorio cardapio comida campus predio".split()
)

# O que o aluno escreve no lugar do apelido canônico e o casamento por palavra
# não resolve sozinho: sigla, nome oficial da unidade, referência geográfica.
# As chaves já estão normalizadas (sem acento e em minúscula).
SINONIMOS = {
    # Central
    "central butanta": "central",
    "ru central butanta": "central",
    "principal": "central",
    # Prefeitura
    "pusp": "prefeitura",
    "pusp-cb": "prefeitura",
    "puspcb": "prefeitura",
    "pusp cb": "prefeitura",
    "prefeitura do campus": "prefeitura",
    "prefeitura do campus butanta": "prefeitura",
    # Física
    "fisicas": "fisica",
    "if": "fisica",
    "ifusp": "fisica",
    "instituto de fisica": "fisica",
    # Química
    "quimicas": "quimica",
    "iq": "quimica",
    "iqusp": "quimica",
    "instituto de quimica": "quimica",
}

REFEICOES = {"A": "almoço", "J": "jantar"}

# ─────────────────────────────────────────────
# Vocabulário de dias
# ─────────────────────────────────────────────
# A raiz de três letras de cada dia, na ordem do weekday() do Python (0 =
# segunda). É o truque que o disciplinas.py já usa: uma raiz absorve "seg",
# "segunda", "segunda-feira" e "segunda feira" de uma vez.
RAIZES_DIA = tuple(normalizar(nome)[:3] for nome in DIAS_SEMANA)

# Palavras que acompanham o dia sem mudar QUAL dia é. "sexta no jantar" e
# "sexta" pedem o mesmo dia — a refeição já vem inteira na resposta.
#
# "que vem" e "próxima" ficam DE FORA de propósito: elas mudam o dia, e para
# outro que o RUCard nem publica. Tratá-las como enfeite faria "quinta que vem"
# devolver o cardápio da quinta desta semana — resposta errada com cara de
# certa, que é o pior resultado possível aqui.
RUIDO_DIA = frozenset(
    "feira dia almoco jantar janta noite tarde manha cedo dessa desta esse este essa".split()
)

# Pedidos que dá para entender mas ficam fora do que existe: o RUCard publica
# só a semana corrente. Dizer isso é diferente de "não entendi".
OUTRA_SEMANA = frozenset(
    [
        "semana que vem", "proxima semana", "semana proxima", "semana seguinte",
        "mes que vem", "proximo mes", "semana passada", "semana anterior",
    ]
)

# Frases inteiras, já reduzidas às palavras que importam.
SEMANA_TODA = frozenset(
    ["semana", "todos", "todos dias", "semana toda", "semana inteira", "tudo", "todas"]
)
FIM_DE_SEMANA = frozenset(["fim semana", "final semana", "fds", "sabado domingo"])
# Quantos dias somar a hoje.
RELATIVOS = {
    "hoje": 0,
    "hj": 0,
    "agora": 0,
    "amanha": 1,
    "depois amanha": 2,
    "ontem": -1,
    "anteontem": -2,
}

# Cardápio longo demais vira custo de token sem virar informação.
MAX_CELULA = 300
# Abaixo disso, apontar para a célula repetida custa mais do que repeti-la.
MIN_REPETICAO = 80

# Os campos vêm em ordem alfabética e o schema do DWR é fixo, então esta ordem
# vale para todo registro. Cada literal capturado é uma string JSON válida: o
# json.loads resolve os \uXXXX e as barras escapadas de graça.
_LITERAL = r'(null|"(?:[^"\\]|\\.)*")'
_REGISTRO = re.compile(
    rf"cdpdia:{_LITERAL}.*?"
    rf"dtarfi:{_LITERAL}.*?"
    rf"tiprfi:{_LITERAL}.*?"
    r"vlrclorfi:(-?\d+)",
    re.S,
)
_AVISO_SEMANA = re.compile(rf"obscdpsmn:{_LITERAL}")
# Recados que o RUCard repete em TODAS as células (copos descartáveis etc.).
_DESTAQUE = re.compile(r"\*\*(.+?)\*\*", re.S)

_CACHE: dict[int, tuple[float, dict]] = {}


# ─────────────────────────────────────────────
# Qual restaurante o aluno pediu
# ─────────────────────────────────────────────
def _apelido(pedido: str) -> str | None:
    """Traduz o que veio para um apelido de RESTAURANTES, ou None.

    Em quatro passadas, da mais precisa para a mais tolerante: apelido exato,
    sinônimo conhecido, e só então o casamento por palavra — depois de tirar as
    genéricas, que é o que faz "ru da física" e "bandejão da física" chegarem
    ao mesmo lugar que "física".
    """
    chave = normalizar(pedido)
    if chave in RESTAURANTES:
        return chave
    if chave in SINONIMOS:
        return SINONIMOS[chave]

    especificas = [p for p in palavras(pedido) if p not in GENERICAS]
    if not especificas:
        return None

    # Sem as genéricas o pedido pode ter virado um apelido ou sinônimo direto.
    reduzido = " ".join(especificas)
    if reduzido in RESTAURANTES:
        return reduzido
    if reduzido in SINONIMOS:
        return SINONIMOS[reduzido]

    # Casa contra o apelido e contra o nome de exibição ("da Física"). Só vale
    # se UM restaurante casar: entre dois, chutar responderia sobre o errado.
    achados = [
        apelido for apelido, (_, nome) in RESTAURANTES.items()
        if casa(reduzido, apelido) or casa(reduzido, nome)
    ]
    return achados[0] if len(achados) == 1 else None


# ─────────────────────────────────────────────
# Leitura da resposta do DWR
# ─────────────────────────────────────────────
def _decodificar(literal: str) -> str:
    """Converte um literal capturado ('null' ou uma string JSON) em texto."""
    if literal == "null":
        return ""
    try:
        return json.loads(literal) or ""
    except json.JSONDecodeError:
        return ""


# ─────────────────────────────────────────────
# Consulta ao RUCard
# ─────────────────────────────────────────────
def _buscar_semana(codigo: int) -> dict:
    """Busca a semana de um restaurante. Devolve {"itens": [...], "aviso": str}.

    Cacheado por TTL. Sem lock: atribuição em dict é atômica e dois workers
    recalculando ao mesmo tempo é inofensivo.
    """
    guardado = _CACHE.get(codigo)
    if guardado and (time.monotonic() - guardado[0]) < TTL:
        return guardado[1]

    resposta = requests.post(
        URL_DWR,
        data=CORPO_DWR.format(codigo=codigo).encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    bruto = resposta.text

    itens = []
    for cardapio, data_texto, refeicao, kcal in _REGISTRO.findall(bruto):
        dia = _decodificar(data_texto)
        try:
            dia = datetime.strptime(dia, "%d/%m/%Y").date()
        except ValueError:
            continue  # registro sem data não serve para montar tabela nenhuma
        itens.append({
            "data": dia,
            "refeicao": _decodificar(refeicao).upper(),
            "cardapio": _decodificar(cardapio),
            "kcal": int(kcal),
        })

    aviso = _AVISO_SEMANA.search(bruto)
    semana = {"itens": itens, "aviso": _decodificar(aviso.group(1)) if aviso else ""}

    _CACHE[codigo] = (time.monotonic(), semana)
    return semana


def _tentar(codigo: int) -> dict | None:
    """Busca uma semana; um restaurante fora do ar não derruba os outros três."""
    try:
        return _buscar_semana(codigo)
    except Exception as erro:
        print(f"[bandejao] codrtn={codigo} falhou: {type(erro).__name__}: {erro}")
        return None


# ─────────────────────────────────────────────
# Quais dias o aluno pediu
# ─────────────────────────────────────────────
def _resolver_dias(
    pedidos: list[str], disponiveis: list[date]
) -> tuple[list[date], list[str], list[str]]:
    """Traduz 'hoje', 'sexta', '29/07/2026'... para datas da semana publicada.

    Devolve as datas encontradas, os dias que existem mas não estão na semana
    publicada, e os pedidos que não deu para entender. Os dois últimos viram
    texto: o modelo é proibido de deduzir data, então omitir em silêncio faria
    ele responder sobre o dia errado.
    """
    hoje = datetime.now(FUSO_BR).date()

    escolhidas: list[date] = []
    fora: list[str] = []
    ininteligiveis: list[str] = []

    def anotar(alvo: date) -> None:
        if alvo not in escolhidas:
            escolhidas.append(alvo)

    for pedido in pedidos:
        chave = normalizar(pedido)
        # Sem o ruído sobra só o que identifica o dia: "sexta no jantar" e
        # "sexta-feira" viram os mesmos ['sexta'].
        uteis = [p for p in palavras(pedido) if p not in RUIDO_DIA]
        frase = " ".join(uteis)
        raiz = uteis[0][:3] if uteis else ""

        if frase in SEMANA_TODA:
            return list(disponiveis), [], []

        # "quinta que vem", "semana que vem": entendido, mas fora do que o
        # RUCard publica. Vai para `fora`, não para `ininteligiveis`.
        if frase in OUTRA_SEMANA or {"vem", "proxima", "proximo"} & set(uteis):
            fora.append(pedido)
            continue

        if frase in FIM_DE_SEMANA:
            # Sábado e domingo da semana publicada, os que existirem nela.
            achou = [d for d in disponiveis if d.weekday() >= 5]
            if achou:
                for dia in achou:
                    anotar(dia)
            else:
                fora.append("o fim de semana")
            continue

        alvo = None
        if frase in RELATIVOS:
            alvo = hoje + timedelta(days=RELATIVOS[frase])
        elif raiz in RAIZES_DIA and len(uteis) == 1:
            posicao = RAIZES_DIA.index(raiz)
            alvo = next((d for d in disponiveis if d.weekday() == posicao), None)
            if alvo is None:
                fora.append(DIAS_SEMANA[posicao])
                continue
        else:
            for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d/%m"):
                try:
                    lido = datetime.strptime(chave, formato).date()
                except ValueError:
                    continue
                # "29/07" não traz ano: assume o da semana publicada.
                alvo = lido.replace(year=disponiveis[0].year) if formato == "%d/%m" else lido
                break

        if alvo is None:
            ininteligiveis.append(pedido)
        elif alvo in disponiveis:
            anotar(alvo)
        else:
            # "amanhã" num domingo cai na semana que vem: dizer a data resolvida
            # evita a dúvida de qual dia o RUCard não tinha.
            data = alvo.strftime("%d/%m/%Y")
            fora.append(data if normalizar(pedido) == normalizar(data) else f"{pedido} ({data})")

    return sorted(escolhidas), fora, ininteligiveis


# ─────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────
def _limpar(cardapio: str, destaques: list[str]) -> str:
    """Achata o HTML de uma célula e recolhe os recados repetidos.

    O RUCard manda os itens separados por <br> e repete o mesmo recado entre
    ** ** nas 56 células da semana. Tirar isso daqui e imprimir uma vez no fim
    economiza mais de mil tokens numa consulta de semana inteira.
    """
    texto = re.sub(r"<br\s*/?>", "\n", cardapio, flags=re.I)
    texto = re.sub(r"<[^>]+>", "", texto)

    for recado in _DESTAQUE.findall(texto):
        recado = " ".join(recado.split())
        if recado and recado not in destaques:
            destaques.append(recado)
    texto = _DESTAQUE.sub("", texto)

    itens = [" ".join(linha.split()) for linha in texto.split("\n")]
    junto = " / ".join(item for item in itens if item)
    # A barra vertical fecharia a coluna da tabela no meio da frase.
    junto = junto.replace("|", "-")

    if len(junto) > MAX_CELULA:
        junto = junto[:MAX_CELULA].rstrip() + "…"
    return junto


def _rotulo(dia: date) -> str:
    return f"{DIAS_SEMANA[dia.weekday()]}, {dia.strftime('%d/%m')}"


def _tabela(semana: dict, dias: list[date], destaques: list[str]) -> list[str]:
    """Monta a tabela Markdown de um restaurante."""
    por_dia: dict[tuple[date, str], dict] = {
        (item["data"], item["refeicao"]): item for item in semana["itens"]
    }

    linhas = ["| Dia | Almoço | Jantar |", "| --- | --- | --- |"]
    ja_visto: dict[str, str] = {}

    for dia in dias:
        celulas = []
        for sigla in ("A", "J"):
            item = por_dia.get((dia, sigla))
            if item is None:
                celulas.append("—")
                continue

            texto = _limpar(item["cardapio"], destaques) or "—"

            # O aviso de reforma do Central se repete nos 14 registros: mostrar
            # uma vez e apontar para ela vale a mesma informação por 1/14 do
            # custo. Só vale a pena para texto longo. Apontar para um "FECHADO"
            # sai mais caro do que repetir o "FECHADO".
            anterior = ja_visto.get(texto) if len(texto) > MIN_REPETICAO else None
            if anterior:
                texto = f"(igual ao {anterior})"
            else:
                ja_visto.setdefault(texto, f"{REFEICOES[sigla]} de {_rotulo(dia)}")

            # A caloria entra depois da checagem: ela varia de um dia para o
            # outro mesmo quando o cardápio é o mesmo aviso repetido.
            if item["kcal"] > 0:
                texto = f"{texto} ({item['kcal']} kcal)"

            celulas.append(texto)

        linhas.append(f"| {_rotulo(dia)} | {celulas[0]} | {celulas[1]} |")

    return linhas


# ─────────────────────────────────────────────
# A ferramenta
# ─────────────────────────────────────────────
def consultar_bandejao(restaurantes=None, dias=None) -> tuple[str, list[str]]:
    """Consulta o cardápio dos bandejões e devolve (tabela, URLs consultadas)."""
    apelidos: list[str] = []
    desconhecidos: list[str] = []

    for pedido in em_lista(restaurantes, list(RESTAURANTES)):
        apelido = _apelido(pedido)
        if apelido is None:
            desconhecidos.append(pedido)
        elif apelido not in apelidos:
            apelidos.append(apelido)

    if not apelidos:
        return (
            f"Não conheço o restaurante {', '.join(desconhecidos)}. "
            f"Os bandejões do Butantã são: {', '.join(RESTAURANTES)}.",
            [],
        )

    pedidos_dias = em_lista(dias, ["hoje"])

    # As quatro consultas em paralelo: sequencial isso passaria de dois segundos
    # com o frontend parado no "Usando ferramenta...".
    with ThreadPoolExecutor(max_workers=len(apelidos)) as executor:
        semanas = list(executor.map(
            lambda apelido: _tentar(RESTAURANTES[apelido][0]), apelidos
        ))

    partes: list[str] = []
    fontes: list[str] = []
    destaques: list[str] = []
    avisos: list[str] = []
    fora_geral: list[str] = []
    ininteligiveis_geral: list[str] = []
    intervalo: list[date] = []

    for apelido, semana in zip(apelidos, semanas):
        codigo, nome = RESTAURANTES[apelido]
        url = URL_PAGINA.format(codigo=codigo)
        fontes.append(url)

        cabecalho = f"## Restaurante {nome}"

        if semana is None:
            partes.append(f"{cabecalho}\n\nNão consegui consultar este bandejão agora.")
            continue

        disponiveis = sorted({item["data"] for item in semana["itens"]})
        if not disponiveis:
            partes.append(f"{cabecalho}\n\nNão há cardápio publicado para esta semana.")
            continue

        intervalo.extend(disponiveis)
        # O aviso da semana vem com o mesmo HTML das células, e às vezes traz
        # embutido o recado das canecas que o _limpar manda para os destaques.
        aviso = _limpar(semana["aviso"], destaques)
        if aviso and aviso not in avisos:
            avisos.append(aviso)

        escolhidos, fora, ininteligiveis = _resolver_dias(pedidos_dias, disponiveis)
        for perdido in fora:
            if perdido not in fora_geral:
                fora_geral.append(perdido)
        for perdido in ininteligiveis:
            if perdido not in ininteligiveis_geral:
                ininteligiveis_geral.append(perdido)

        if not escolhidos:
            partes.append(
                f"{cabecalho}\n\nNenhum dos dias pedidos está na semana publicada "
                f"({disponiveis[0].strftime('%d/%m/%Y')} a "
                f"{disponiveis[-1].strftime('%d/%m/%Y')})."
            )
            continue

        partes.append(cabecalho + "\n\n" + "\n".join(_tabela(semana, escolhidos, destaques)))

    if not intervalo:
        return "\n\n".join(partes) or "Não consegui consultar os bandejões agora.", fontes

    inicio, fim = min(intervalo), max(intervalo)
    topo = [
        f"Cardápio publicado para a semana de {inicio.strftime('%d/%m/%Y')} a "
        f"{fim.strftime('%d/%m/%Y')}."
    ]
    if fora_geral:
        topo.append(
            f"Não há cardápio publicado para {', '.join(fora_geral)}: a página do "
            "RUCard só traz a semana atual."
        )
    if ininteligiveis_geral:
        topo.append(f"Não entendi que dia é {', '.join(ininteligiveis_geral)}.")

    rodape = avisos + destaques

    return "\n\n".join(topo + partes + rodape), fontes


def registrar(registro: Registro) -> None:
    """Registra a ferramenta no registro dado.

    Ao contrário da `buscar_documentos`, esta ferramenta é a mesma nos dois
    backends, por isso quem escolhe o registro é o entrypoint, e não este
    módulo.
    """
    registro.ferramenta(
        nome="consultar_bandejao",
        descricao=(
            "Cardápio da semana dos bandejões do Butantã, com almoço, jantar e "
            "calorias. Use para qualquer pergunta sobre cardápio, comida ou RU."
        ),
        parametros={
            "type": "object",
            "properties": {
                "restaurantes": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(RESTAURANTES)},
                    "description": "Omita para consultar os quatro.",
                },
                "dias": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "'hoje', 'amanha', 'depois de amanha', dia da semana "
                        "('sexta'), 'fim de semana', data 'dd/mm/aaaa' ou "
                        "'semana' para a semana toda. Omita para hoje. Repasse "
                        "o dia como o aluno disse, sem converter para data."
                    ),
                },
            },
            "required": [],
        },
    )(consultar_bandejao)
