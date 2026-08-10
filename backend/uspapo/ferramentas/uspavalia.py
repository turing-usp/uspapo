"""Avaliações de professor no USP Avalia (uspavalia.com).

Esta é a primeira ferramenta do USPapo cuja fonte NÃO é a USP. O USP Avalia é um
site independente, feito por alunos, onde se dá nota de 0 a 10 a um professor em
cinco quesitos e se deixa comentário anônimo. É opinião, não registro oficial,
por isso o texto devolvido termina sempre com a ressalva, e a `descricao` do
schema repete o recado: o modelo tem instrução de tratar resultado de ferramenta
como fato, e aqui isso seria errado.

Sobre raspar o site: `uspavalia.com/robots.txt` não existe (o servidor devolve a
própria página de 404), então não há diretiva a respeitar, diferente do
`fea.usp.br`, que proíbe crawler e está em quarentena no scrapers_config.json.
Ainda assim mandamos User-Agent identificando o USPapo, e o memo de seis horas é
o que evita uma ida à rede por aluno.

Três rotas, e a primeira é um presente:

1. **`POST /typeahead`** devolve **JSON limpo** — `[{"id":175,"name":"Norton
   Trevisan Roman","type":0}]`, com `type` 0 para professor e 1 para disciplina.
   É o autocomplete da barra de busca do site. Ignora acento do lado do servidor
   ("Joao" acha "João"), responde a partir de três caracteres e corta em dez
   resultados. Nenhum HTML precisa ser lido para descobrir o id de um professor.

2. **`GET /professor/<id>`** tem o nome, a unidade e a tabela de disciplinas com
   a nota geral de cada uma. Cuidado ao depurar: o `<tbody>` tem uns 42 KB de
   markup de *modal* de avaliação intercalado entre as linhas, uma janela
   inteira por disciplina. A extração de `<tr>`/`<td>` funciona porque os modais
   não têm `<td>`, mas o tamanho da página engana.

3. **`GET /ver/<id>`** é a ficha de um par professor+disciplina: os cinco
   quesitos e os comentários. Os números confiáveis são os atributos `avg` e
   `std` do `<p class="graph">`, que já vêm numéricos, o `<h3>` ao lado traz o
   mesmo valor formatado com três casas. Página sem nota nenhuma não traz
   quesito algum: no lugar dos cinco blocos vem um painel de "Nenhuma avaliação
   ainda", o que deixa a regex dos quesitos segura (casa cinco ou zero, nunca
   um nome trocado).

O volume de comentário é pequeno de verdade: numa amostra de doze fichas, de
zero a quatro comentários cada, no máximo ~650 caracteres de texto somados. O
custo em token desta ferramenta está no NÚMERO DE FICHAS buscadas, não no
comentário, daí o `MAX_FICHAS`.

Ao contrário da `buscar_documentos`, esta ferramenta é a MESMA nos dois
backends: não existe versão simulada do USP Avalia. Por isso este módulo não cria
um `Registro` próprio. Ele expõe uma `registrar(registro)` que os dois entrypoints
chamam com o registro deles.
"""

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from uspapo.ferramentas import Registro, cache, casa, normalizar, palavras

BASE = "https://uspavalia.com"
URL_TYPEAHEAD = f"{BASE}/typeahead"
URL_PROFESSOR = BASE + "/professor/{id}"
URL_FICHA = BASE + "/ver/{id}"

TIMEOUT = 12

# Média de avaliação se move em semanas, não em minutos. Seis horas, o mesmo
# TTL_LONGO do JupiterWeb, é o que impede o site levar uma consulta por aluno.
TTL = 21600

# O backend não manda User-Agent em lugar nenhum, mas ali os alvos são sistemas
# da própria USP. Este é um site de terceiro, mantido por voluntários: quem
# estiver lendo o log de acesso merece saber quem bateu na porta.
CABECALHOS = {"User-Agent": "USPapo/1.0 (chatbot de alunos da USP)"}

# O autocomplete do site não responde a menos que isto (o próprio JS dele exige
# quatro); abaixo disso nem vale a ida à rede.
MIN_BUSCA = 3

# Tetos de token. A ferramenta inteira, no pior caso, gira em torno de mil
# tokens, contra a reserva de ~4000 do config.RESERVA_FERRAMENTAS.
MAX_CANDIDATOS = 8      # nomes devolvidos quando a busca fica ambígua
MAX_DISCIPLINAS = 12    # professor antigo tem dezenas de linhas na tabela
MAX_SEM_NOTA = 6        # as sem avaliação viram uma frase, não linhas de tabela
MAX_FICHAS = 2          # páginas /ver por chamada: é isto que segura o custo
MAX_COMENTARIOS = 4     # acima do pior caso medido (4 numa amostra de 12 fichas)
MAX_COMENTARIO = 280    # corta o comentário quilométrico avulso

_TAG = re.compile(r"<[^>]+>")
_INVISIVEL = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)

_NOME = re.compile(r"<h2>(.*?)</h2>", re.S)
_UNIDADE = re.compile(r'<p class="text-muted">(.*?)</p>', re.S)
_TBODY = re.compile(r"<tbody>(.*?)</tbody>", re.S | re.I)
_LINHA = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELULA = re.compile(r"<td>(.*?)</td>", re.S)
_VER = re.compile(r'href="/ver/(\d+)"')

# Um quesito da ficha. O `<h3>` entre o título e o gráfico é obrigatório na
# regex de propósito: é ele que impede o `.*?` atravessar um quesito sem nota e
# casar o nome de um com o número do seguinte.
_QUESITO = re.compile(
    r"<h4>([^<]+)</h4>\s*"
    r'<h3 style="text-align:center">[\d.]+</h3>\s*'
    r'<p class="graph" avg="([-\d.]+)" std="([-\d.]+)"></p>\s*'
    r"<p><small>Quesito avaliado (\d+) vezes",
    re.S,
)
_DISCIPLINA_FICHA = re.compile(r'itemprop="affiliation">(.*?)</span>', re.S)
_COMENTARIO = re.compile(r'<li class="media">(.*?)</li>', re.S)
_DATA = re.compile(r'class="media-heading">([^<]*)<')
_TEXTO = re.compile(r'style="text-align:justify">(.*?)</div>', re.S)
_VOTO = re.compile(r'class="badge">(\d+)<')

# Nesta ordem, que é a que o site usa e a que faz sentido ler.
QUESITOS = ("Avaliação Geral", "Didática", "Empenho/Dedicação", "Relação com os alunos", "Dificuldade")

RESSALVA = (
    "O USP Avalia é um site independente feito por alunos e NÃO é fonte oficial "
    "da USP. As notas são média de poucos votos e os comentários são opinião "
    "individual e anônima: repasse como opinião de aluno, com essa ressalva, e "
    "nunca como fato sobre o professor. Se a pergunta for sobre a disciplina em "
    "si (ementa, créditos, turmas), use a ferramenta do JupiterWeb."
)


# ─────────────────────────────────────────────
# Rede
# ─────────────────────────────────────────────
def _achatar(bruto: str) -> str:
    """Tira tags e entidades e normaliza o espaço em branco."""
    return " ".join(html.unescape(_TAG.sub(" ", _INVISIVEL.sub("", bruto))).split())


def _pagina(url: str) -> str:
    """GET numa página do site. O 404 vira exceção e o chamador decide."""
    resposta = requests.get(url, headers=CABECALHOS, timeout=TIMEOUT)
    resposta.raise_for_status()
    return resposta.text


def _buscar(termo: str) -> list[dict]:
    """Uma consulta ao autocomplete, memoizada.

    Só `type == 0`: o mesmo endpoint responde disciplina, e disciplina aqui não
    interessa — quem procura ementa tem ferramenta do JupiterWeb.
    """
    def buscar():
        resposta = requests.post(
            URL_TYPEAHEAD,
            data={"query": termo},
            headers=CABECALHOS,
            timeout=TIMEOUT,
        )
        resposta.raise_for_status()
        return resposta.json()

    achados = cache(("uspavalia", "busca", normalizar(termo)), TTL, buscar)
    if not isinstance(achados, list):
        return []
    return [item for item in achados if isinstance(item, dict) and item.get("type") == 0]


def _candidatos(termo: str) -> tuple[list[dict], bool]:
    """Professores que casam com o termo, e se a busca teve que ser alargada.

    O autocomplete do site é substring literal, não busca por palavra: "norton
    roman" não acha "Norton Trevisan Roman", porque o nome do meio fica no
    caminho. E é assim que o aluno fala, pelo primeiro nome e pelo sobrenome.

    Então, quando o termo inteiro não acha nada, a segunda tentativa manda só a
    palavra mais longa (a mais seletiva) e a filtragem por palavra fica com o
    `casa`, do nosso lado. O segundo elemento do retorno diz que a lista veio
    por esse caminho: ali os nomes são de gente que só compartilha UMA palavra
    com o pedido, então não servem como palpite quando o `casa` não fecha.
    """
    diretos = _buscar(termo)
    if diretos:
        return diretos, False

    partes = sorted(palavras(termo), key=len, reverse=True)
    if len(partes) < 2 or len(partes[0]) < MIN_BUSCA:
        return [], False

    return _buscar(partes[0]), True


# ─────────────────────────────────────────────
# Páginas
# ─────────────────────────────────────────────
def _ficha_professor(id_professor: int) -> dict:
    """Nome, unidade e a tabela de disciplinas de um professor."""
    def buscar():
        bruto = _pagina(URL_PROFESSOR.format(id=id_professor))

        nome = _NOME.search(bruto)
        unidade = _UNIDADE.search(bruto)
        corpo = _TBODY.search(bruto)

        disciplinas = []
        for linha in _LINHA.findall(corpo.group(1) if corpo else ""):
            celulas = _CELULA.findall(linha)
            ver = _VER.search(linha)
            if len(celulas) < 2 or not ver:
                continue

            nota = _achatar(celulas[1])
            disciplinas.append({
                "nome": _achatar(celulas[0]),
                # "Sem avaliações" na coluna da nota é o jeito do site dizer
                # que ninguém votou nessa oferta ainda.
                "nota": _numero(nota),
                "id": int(ver.group(1)),
            })

        return {
            "nome": _achatar(nome.group(1)) if nome else "",
            "unidade": _achatar(unidade.group(1)) if unidade else "",
            "disciplinas": disciplinas,
        }

    return cache(("uspavalia", "professor", id_professor), TTL, buscar)


def _avaliacao(id_ficha: int) -> dict:
    """Os cinco quesitos e os comentários de um par professor+disciplina."""
    def buscar():
        bruto = _pagina(URL_FICHA.format(id=id_ficha))

        disciplina = _DISCIPLINA_FICHA.search(bruto)
        quesitos = [
            {
                "nome": _achatar(nome),
                "media": _numero(media),
                "desvio": _numero(desvio),
                "votos": int(votos),
            }
            for nome, media, desvio, votos in _QUESITO.findall(bruto)
        ]

        comentarios = []
        for bloco in _COMENTARIO.findall(bruto):
            texto = _TEXTO.search(bloco)
            if not texto:
                continue
            corpo = _achatar(texto.group(1))
            if not corpo:
                continue

            data = _DATA.search(bloco)
            votos = _VOTO.findall(bloco)
            comentarios.append({
                # A data vem "04/11/2020 - 11:47:34"; a hora não diz nada.
                "data": (data.group(1).strip().split(" - ")[0] if data else ""),
                "texto": corpo,
                "positivo": int(votos[0]) if votos else 0,
                "negativo": int(votos[1]) if len(votos) > 1 else 0,
            })

        return {
            "disciplina": _achatar(disciplina.group(1)) if disciplina else "",
            "quesitos": quesitos,
            "comentarios": comentarios,
        }

    return cache(("uspavalia", "ficha", id_ficha), TTL, buscar)


def _tentar(id_ficha: int) -> dict | None:
    """Busca uma ficha; uma que falhe não derruba a resposta inteira."""
    try:
        return _avaliacao(id_ficha)
    except Exception as erro:
        print(f"[uspavalia] ver/{id_ficha} falhou: {type(erro).__name__}: {erro}")
        return None


def _numero(texto: str) -> float | None:
    """O número de um campo do site, ou None quando não há nota ali."""
    try:
        return float(str(texto).replace(",", "."))
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────
def _formatar_quesitos(quesitos: list[dict]) -> list[str]:
    """Os cinco quesitos numa linha, mais a leitura da Dificuldade."""
    ordem = {nome: indice for indice, nome in enumerate(QUESITOS)}
    ordenados = sorted(quesitos, key=lambda q: ordem.get(q["nome"], len(QUESITOS)))

    partes = []
    for quesito in ordenados:
        media = quesito["media"]
        if media is None:
            continue
        desvio = quesito["desvio"]
        # O desvio só entra quando existe: "±0.0" em toda linha é ruído.
        sufixo = f" (±{desvio:.1f})" if desvio else ""
        partes.append(f"{quesito['nome']} {media:.1f}{sufixo}")

    if not partes:
        return []

    votos = max((q["votos"] for q in ordenados), default=0)
    quantos = "1 aluno" if votos == 1 else f"{votos} alunos"
    return [
        " · ".join(partes),
        f"Notas de 0 a 10, média de {quantos}. Em Dificuldade a nota mede o "
        "quanto a matéria é puxada: alta ali não é defeito do professor.",
    ]


def _formatar_comentarios(comentarios: list[dict]) -> list[str]:
    """Os comentários mais úteis, do mais bem votado para o menos."""
    if not comentarios:
        return []

    # Ordenado pelo saldo de votos: é a triagem que os próprios alunos fizeram,
    # e o site já esconde o que leva muita qualificação negativa.
    melhores = sorted(
        comentarios,
        key=lambda c: (c["positivo"] - c["negativo"], c["data"]),
        reverse=True,
    )
    cortados = max(0, len(melhores) - MAX_COMENTARIOS)

    linhas = []
    for comentario in melhores[:MAX_COMENTARIOS]:
        texto = comentario["texto"]
        if len(texto) > MAX_COMENTARIO:
            texto = texto[:MAX_COMENTARIO].rstrip() + "..."
        selo = f"{comentario['positivo']} positivo, {comentario['negativo']} negativo"
        data = comentario["data"] or "sem data"
        linhas.append(f'- {data} ({selo}): "{texto}"')

    if cortados:
        plural = "comentário" if cortados == 1 else "comentários"
        linhas.append(f"- (mais {cortados} {plural} no site, menos votados)")

    return ["**Comentários de alunos:**"] + linhas


def _formatar_ficha(ficha: dict, nome_tabela: str) -> str:
    """Uma disciplina detalhada: cabeçalho, quesitos e comentários."""
    # O título da ficha traz "Disciplina - SIGLA"; a tabela do professor só tem
    # o nome, então é daqui que sai a sigla.
    titulo = ficha["disciplina"] or nome_tabela
    partes = [f"### {titulo}"]
    partes.extend(_formatar_quesitos(ficha["quesitos"]))
    partes.extend(_formatar_comentarios(ficha["comentarios"]))
    return "\n".join(partes)


# ─────────────────────────────────────────────
# A ferramenta
# ─────────────────────────────────────────────
def consultar_avaliacoes_professor(professor=None, disciplina=None) -> tuple[str, list[str]]:
    """Consulta as avaliações de um professor no USP Avalia.

    Devolve (texto formatado para o modelo, URLs consultadas).
    """
    termo = str(professor or "").strip()
    if len(normalizar(termo)) < MIN_BUSCA:
        return (
            "Preciso do nome do professor, com pelo menos "
            f"{MIN_BUSCA} letras, para buscar no USP Avalia.",
            [],
        )

    try:
        candidatos, amplo = _candidatos(termo)
    except Exception as erro:
        print(f"[uspavalia] busca '{termo}' falhou: {type(erro).__name__}: {erro}")
        return (
            "Não consegui consultar o USP Avalia agora: o site não respondeu. "
            "Avise o aluno e sugira tentar de novo daqui a pouco. NÃO conclua "
            "que o professor não tem avaliação.",
            [],
        )

    if not candidatos:
        return (
            f"O USP Avalia não tem nenhum professor chamado '{termo}'. O site "
            "cobre parte dos docentes, então ausência ali não quer dizer que a "
            "pessoa não dê aula na USP. Vale conferir a grafia do nome.",
            [],
        )

    # `casa` é a mesma correspondência por prefixo de palavra das outras
    # ferramentas: 'norton roman' casa com 'Norton Trevisan Roman', e a ordem
    # das palavras não importa. O typeahead já ignora acento do lado dele.
    exatos = [c for c in candidatos if normalizar(c["name"]) == normalizar(termo)]
    casados = [c for c in candidatos if casa(termo, c["name"])]

    # Sem `casa` nenhum, a lista crua só serve quando o site casou o termo
    # inteiro. Numa busca alargada ela é gente que divide UMA palavra com o
    # pedido: "Silva" para quem procurou "Ana Silva". Chutar ali seria trocar o
    # professor, que é bem pior do que dizer que não achou.
    escolhidos = exatos or casados or ([] if amplo else candidatos)

    if not escolhidos:
        nomes = ", ".join(c["name"] for c in candidatos[:MAX_CANDIDATOS])
        return (
            f"Não achei '{termo}' no USP Avalia. A busca do site casa o nome por "
            "trecho literal e devolve no máximo dez resultados, então nome do "
            f"meio faltando ou sobrenome muito comum atrapalha. Ela trouxe: "
            f"{nomes}. Se o professor for um desses, chame de novo com o nome "
            "como está escrito aí; senão, confirme a grafia com o aluno.",
            [],
        )

    if len(escolhidos) > 1:
        nomes = "\n".join(f"- {c['name']}" for c in escolhidos[:MAX_CANDIDATOS])
        sobra = max(0, len(escolhidos) - MAX_CANDIDATOS)
        rabicho = f"\n- (e mais {sobra})" if sobra else ""
        return (
            f"Há mais de um professor no USP Avalia que casa com '{termo}':\n"
            f"{nomes}{rabicho}\n\n"
            "Chame a ferramenta de novo com o nome completo de um deles. Se o "
            "aluno não disse qual, pergunte a ele antes.",
            [],
        )

    alvo = escolhidos[0]
    fontes = [URL_PROFESSOR.format(id=alvo["id"])]

    try:
        perfil = _ficha_professor(alvo["id"])
    except Exception as erro:
        print(f"[uspavalia] professor/{alvo['id']} falhou: {type(erro).__name__}: {erro}")
        return (
            f"Achei {alvo['name']} no USP Avalia, mas a página dele não abriu "
            "agora. Avise o aluno e sugira tentar de novo daqui a pouco.",
            fontes,
        )

    cabecalho = perfil["nome"] or alvo["name"]
    if perfil["unidade"]:
        cabecalho += f" — {perfil['unidade']}"

    avaliadas = [d for d in perfil["disciplinas"] if d["nota"] is not None]
    sem_nota = [d for d in perfil["disciplinas"] if d["nota"] is None]

    if not perfil["disciplinas"]:
        return (
            f"## {cabecalho}\n\nO USP Avalia tem a página deste professor, mas "
            f"nenhuma disciplina cadastrada nela.\n\n{RESSALVA}",
            fontes,
        )

    if not avaliadas:
        nomes = ", ".join(d["nome"] for d in sem_nota[:MAX_DISCIPLINAS])
        return (
            f"## {cabecalho}\n\nNenhuma das disciplinas deste professor foi "
            f"avaliada ainda no USP Avalia. As cadastradas são: {nomes}.\n\n"
            "Isso NÃO é uma avaliação ruim: é ausência de voto.\n\n"
            f"{RESSALVA}",
            fontes,
        )

    avaliadas.sort(key=lambda d: d["nota"], reverse=True)

    # Uma disciplina pedida pelo nome manda na escolha; a sigla não dá para
    # casar aqui, porque a tabela do professor só traz o nome.
    pedida = str(disciplina or "").strip()
    if pedida:
        filtradas = [d for d in avaliadas if casa(pedida, d["nome"])]
        if not filtradas:
            nomes = ", ".join(d["nome"] for d in avaliadas[:MAX_DISCIPLINAS])
            return (
                f"## {cabecalho}\n\nNão achei '{pedida}' entre as disciplinas "
                f"avaliadas deste professor. As avaliadas são: {nomes}.\n\n"
                "Chame de novo com um desses nomes (o nome, não a sigla), ou "
                "sem disciplina nenhuma para ver o panorama.\n\n"
                f"{RESSALVA}",
                fontes,
            )
        detalhar = filtradas[:MAX_FICHAS]
    else:
        detalhar = avaliadas[:MAX_FICHAS]

    mostradas = avaliadas[:MAX_DISCIPLINAS]
    tabela = ["| Disciplina | Nota geral (0-10) |", "| --- | --- |"]
    tabela += [f"| {d['nome']} | {d['nota']:.2f} |" for d in mostradas]

    partes = [f"## {cabecalho}", "\n".join(tabela)]

    if len(avaliadas) > MAX_DISCIPLINAS:
        partes.append(
            f"Outras {len(avaliadas) - MAX_DISCIPLINAS} disciplinas avaliadas "
            "ficaram de fora da tabela por espaço."
        )

    if sem_nota:
        nomes = ", ".join(d["nome"] for d in sem_nota[:MAX_SEM_NOTA])
        sobra = len(sem_nota) - MAX_SEM_NOTA
        partes.append(
            f"Sem nenhuma avaliação ainda: {nomes}"
            + (f" e mais {sobra}" if sobra > 0 else "")
            + ". Falta de voto não é nota baixa."
        )

    # Em paralelo: sequencial, duas fichas passariam de um segundo com o
    # frontend parado no "Buscando avaliações".
    with ThreadPoolExecutor(max_workers=max(1, len(detalhar))) as executor:
        fichas = list(executor.map(lambda d: _tentar(d["id"]), detalhar))

    for pedido, ficha in zip(detalhar, fichas):
        fontes.append(URL_FICHA.format(id=pedido["id"]))
        if ficha is None:
            partes.append(
                f"### {pedido['nome']}\nA ficha desta disciplina não abriu agora."
            )
            continue
        partes.append(_formatar_ficha(ficha, pedido["nome"]))

    restantes = len(avaliadas) - len(detalhar)
    if not pedida and restantes > 0:
        partes.append(
            f"Detalhei as {len(detalhar)} disciplinas mais bem avaliadas das "
            f"{len(avaliadas)} que têm nota. As outras {restantes} estão na "
            "tabela acima, só sem o detalhe. Para uma delas em específico, chame "
            "a ferramenta de novo passando o nome da disciplina."
        )

    partes.append(RESSALVA)
    return "\n\n".join(partes), fontes


def registrar(registro: Registro) -> None:
    """Registra a ferramenta no registro dado.

    Ao contrário da `buscar_documentos`, esta ferramenta é a mesma nos dois
    backends, por isso quem escolhe o registro é o entrypoint, e não este
    módulo.
    """
    registro.ferramenta(
        nome="consultar_avaliacoes_professor",
        descricao=(
            "Notas e comentários de alunos sobre um professor da USP, do site "
            "USP Avalia: avaliação geral, didática, empenho, relação com os "
            "alunos e dificuldade, por disciplina. Use quando perguntarem se um "
            "professor é bom, como ele dá aula ou o que os alunos acham dele. "
            "ATENÇÃO: é site independente de alunos, não é fonte oficial da USP. "
            "O resultado é opinião e tem que ser repassado como tal. Para "
            "ementa, créditos, turmas ou horário da disciplina, use a ferramenta "
            "do JupiterWeb."
        ),
        parametros={
            "type": "object",
            "properties": {
                "professor": {
                    "type": "string",
                    "description": (
                        "Nome do professor como o aluno falou. Não precisa ser "
                        "completo nem acentuado."
                    ),
                },
                "disciplina": {
                    "type": "string",
                    "description": (
                        "O NOME da disciplina, quando a pergunta for sobre uma "
                        "específica ('ele é bom em Cálculo I?'). Não use a "
                        "sigla. Omita para o panorama do professor."
                    ),
                },
            },
            "required": ["professor"],
        },
    )(consultar_avaliacoes_professor)
