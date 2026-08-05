"""Grade curricular de um curso de ingresso, da aba "Cursos de ingresso".

A página que o aluno abre é a jupCarreira.jsp, mas ela não traz grade nenhuma:
chega com os dois `<select>` vazios e quem preenche tudo: unidades, cursos,
informações e a grade. É o JavaScript, por DWR. É o mesmo protocolo que o
bandejao.py fala com o RUCard, e a fonte devolvida aqui continua sendo a .jsp,
que é a página que o aluno consegue abrir (a grade em si não tem URL própria).

O aluno diz "engenharia de computação", não "3123|3000", então a ferramenta
resolve o nome sozinha. Para isso precisa do catálogo inteiro: 1 chamada para
as unidades e mais 47 para os cursos de cada uma. São 196 cursos, leva ~1,6 s em
paralelo e vale por horas: só o primeiro aluno da janela paga.

O corte por tipo não é preciosismo de token, é necessidade. A grade do
Bacharelado em Ciência da Computação tem 221 disciplinas, das quais 184 são
optativas eletivas. Sozinha ela consumiria quase todo o orçamento reservado
para ferramentas numa pergunta. Por padrão vão só as obrigatórias, e o resto sai
por pedido explícito.

Como o bandejão, esta ferramenta é a mesma nos dois backends: não cria
`Registro` próprio, expõe uma `registrar(registro)` que os entrypoints chamam.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from uspapo.ferramentas import Registro, casa, normalizar
from uspapo.ferramentas import jupiter

# A página do aluno. A grade é toda AJAX, então não há URL mais específica.
URL_PAGINA = jupiter.url("jupCarreira.jsp", codmnu="8275")

# tipobg no DWR -> como o próprio jupCarreira.js rotula cada bloco.
BLOCOS = {
    "O": "Disciplinas Obrigatórias",
    "C": "Disciplinas Optativas Eletivas",
    "L": "Disciplinas Optativas Livres",
}

# Os valores de `tipo` que a ferramenta anuncia e que aparecem numa mensagem de
# erro. Ficam separados dos apelidos de propósito: com um `set(TIPOS) - {...}`
# escrito à mão, todo apelido novo vazava para o texto que o aluno lê.
TIPOS_PUBLICOS = ("obrigatorias", "eletivas", "livres", "todas")

# O que o modelo pode mandar em `tipo`, e o tipobg correspondente.
TIPOS = {
    "obrigatorias": "O",
    "obrigatoria": "O",
    "eletivas": "C",
    "eletiva": "C",
    "optativas eletivas": "C",
    # "optativa", sem qualificar, quase sempre quer dizer eletiva: é o bloco
    # que o aluno escolhe dentro do curso. As livres são o caso raro e quem
    # sabe que elas existem sabe o nome delas.
    "optativas": "C",
    "optativa": "C",
    "livres": "L",
    "livre": "L",
    "optativas livres": "L",
    "todas": None,
    "todos": None,
    "tudo": None,
    "todas as disciplinas": None,
    "grade completa": None,
    "completa": None,
}

# Apelidos de curso que o casamento por palavra não alcança: sigla e nome
# popular que não são prefixo de nada no nome oficial. O valor é por o que
# trocar antes de procurar.
CURSOS = {
    "bcc": "ciencia da computacao",
    "bsi": "sistemas de informacao",
    "agronomia": "engenharia agronomica",
    "agronomo": "engenharia agronomica",
    "biologia": "ciencias biologicas",
    "biologicas": "ciencias biologicas",
    "biomedicina": "ciencias biomedicas",
    "contabilidade": "ciencias contabeis",
    "contabeis": "ciencias contabeis",
    "atuaria": "ciencias atuariais",
    "vet": "medicina veterinaria",
    "veterinario": "medicina veterinaria",
    "ri": "relacoes internacionais",
    "adm": "administracao",
    "odonto": "odontologia",
    "psico": "psicologia",
    "nutri": "nutricao",
    "fono": "fonoaudiologia",
    "fisio": "fisioterapia",
    "moleculares": "ciencias moleculares",
    "cdm": "ciencias moleculares",
    "propaganda": "publicidade",
    "poli": "engenharia",
}

# Apelidos de unidade. A sigla oficial NÃO precisa entrar aqui: ela já vem
# dentro do nome que o JupiterWeb devolve ("... - ( IME )"). O que entra é o
# que o aluno chama de um jeito que não aparece no nome nenhum — a cidade do
# campus, o apelido histórico.
UNIDADES = {
    "largo sao francisco": "faculdade de direito",
    "sao francisco": "faculdade de direito",
    "usp leste": "each",
    "leste": "each",
    "piracicaba": "esalq",
    "pirassununga": "fzea",
    "poli": "politecnica",
}

# A sigla que o JupiterWeb põe entre parênteses no fim do nome da unidade.
_SIGLA_UNIDADE = re.compile(r"\(([^)]+)\)\s*$")

# Teto de disciplinas listadas, mesmo com tipo='todas'.
MAX_LINHAS = 120
# Teto de cursos listados quando o nome pedido casa com vários.
MAX_OPCOES = 25


# ─────────────────────────────────────────────
# Catálogo de cursos de ingresso
# ─────────────────────────────────────────────
class _Incompleto(Exception):
    """O catálogo veio furado: uma unidade falhou. Carrega o que deu para obter."""

    def __init__(self, parcial: list[dict]):
        self.parcial = parcial


def _cursos_da_unidade(unidade: dict) -> list[dict] | None:
    """Os cursos de ingresso de uma unidade, já com o nome dela junto."""
    try:
        cursos = jupiter.dwr(
            "listar", "pubListarCursoEntrada", {"codclg": unidade["codclg"]}
        )
    except Exception as erro:
        print(f"[curriculo] codclg={unidade['codclg']} falhou: "
              f"{type(erro).__name__}: {erro}")
        return None

    for curso in cursos:
        curso["unidade"] = unidade["nomclg"]
        curso["rotulo"] = _rotulo(curso)
    return cursos


def _rotulo(curso: dict) -> str:
    """Monta o nome pelo qual o aluno chama o curso.

    O JupiterWeb guarda o curso e a habilitação separados, e a relação entre os
    dois muda de unidade para unidade:

        nomcur "Bacharelado em Gestão Ambiental"  nomhab "… - Ciclo Básico"
        nomcur "Engenharia"                       nomhab "Habilitação: Engenharia Civil"
        nomcur "Bacharelado em Ciência da Computação"  nomhab igual ao nomcur

    O jupCarreira.js monta o rótulo cortando o nomcur de dentro do nomhab, o que
    no caso da Poli produz "Engenharia (Habilitação:  de Computação)" — nome que
    nenhum aluno digitaria e que estragaria a busca. Aqui a habilitação é
    preservada inteira quando já traz o nome do curso dentro dela.
    """
    nomcur, nomhab, periodo = curso["nomcur"], curso["nomhab"], curso["perhab"]

    habilitacao = nomhab.removeprefix(f"{nomcur} - ").removeprefix("Habilitação:").strip()

    if not habilitacao or habilitacao == nomcur:
        return f"{nomcur} - {periodo}"
    if nomcur in habilitacao:
        return f"{habilitacao} - {periodo}"
    return f"{nomcur} ({habilitacao}) - {periodo}"


def _catalogo() -> list[dict]:
    """Todos os cursos de ingresso da USP, de todas as unidades.

    As 47 consultas vão em paralelo: sequencial isso passaria de dez segundos
    com o aluno parado no "Usando ferramenta...".
    """
    def montar() -> list[dict]:
        unidades = jupiter.dwr(
            "listar", "pubListarColegiado", {"pfxdisval": "XXX", "codcg": "0"}
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            lotes = list(executor.map(_cursos_da_unidade, unidades))

        cursos = [c for lote in lotes if lote is not None for c in lote]
        if any(lote is None for lote in lotes):
            # Um catálogo furado NÃO pode ficar seis horas no cache: os cursos
            # da unidade que falhou virariam "não encontrei esse curso" para
            # todo mundo até o TTL vencer. A exceção sai de dentro do produzir,
            # então o jupiter.cache não guarda nada — e a próxima pergunta
            # tenta de novo.
            raise _Incompleto(cursos)
        return cursos

    try:
        return jupiter.cache(("catalogo",), jupiter.TTL_LONGO, montar)
    except _Incompleto as furado:
        return furado.parcial


def _sigla(unidade: str) -> str:
    """A sigla entre parênteses no fim do nome da unidade ('' se não tiver)."""
    achado = _SIGLA_UNIDADE.search(unidade)
    return normalizar(achado.group(1)) if achado else ""


def _filtrar_unidade(achados: list[dict], unidade: str) -> list[dict]:
    """Os cursos da unidade pedida, da interpretação mais precisa para a mais frouxa.

    A sigla exata vem primeiro porque o nome traz a sigla dentro dele, e uma
    sigla curta é substring de várias: procurar "IF" por substring pega o IFSC
    e a Interunidades junto com o Instituto de Física.
    """
    pedido = normalizar(UNIDADES.get(normalizar(unidade), unidade))

    exatos = [c for c in achados if _sigla(c["unidade"]) == pedido]
    if exatos:
        return exatos

    contidos = [c for c in achados if pedido in normalizar(c["unidade"])]
    if contidos:
        return contidos

    return [c for c in achados if casa(pedido, c["unidade"])]


def _procurar(catalogo: list[dict], curso: str, unidade: str) -> list[dict]:
    """Os cursos cujo nome (e unidade, se pedida) casam com o que foi buscado.

    Três passadas em ordem de precisão: o nome como veio, o apelido conhecido,
    e o casamento palavra a palavra — que é o que absorve "engenharia DA
    computação", "eng comp" e a ordem trocada.
    """
    achados = catalogo

    if unidade:
        achados = _filtrar_unidade(achados, unidade)

    alvo = normalizar(curso)
    exatos = [c for c in achados if alvo in normalizar(c["rotulo"])]
    if exatos:
        return exatos

    apelido = CURSOS.get(alvo)
    if apelido:
        por_apelido = [c for c in achados if apelido in normalizar(c["rotulo"])]
        if por_apelido:
            return por_apelido

    return [c for c in achados if casa(apelido or curso, c["rotulo"])]


# ─────────────────────────────────────────────
# Formatação da grade
# ─────────────────────────────────────────────
def _semestre_de(disciplina: dict) -> int:
    """O semestre ideal da disciplina. Tudo no DWR vem como string."""
    try:
        return int(disciplina.get("numsemidl") or 0)
    except (TypeError, ValueError):
        return 0


def _tabela(disciplinas: list[dict]) -> list[str]:
    """As disciplinas de um semestre ideal, em tabela Markdown."""
    linhas = [
        "| Código | Disciplina | Créd. aula | Créd. trab. | CH |",
        "| --- | --- | --- | --- | --- |",
    ]
    for disciplina in disciplinas:
        aula = int(disciplina.get("creaul") or 0)
        trabalho = int(disciplina.get("cretrb") or 0)
        # A fórmula é a do próprio jupCarreira.js.
        linhas.append(
            f"| {disciplina['coddis']} | {disciplina['nomdis']} | "
            f"{aula} | {trabalho} | {15 * aula + 30 * trabalho} h |"
        )
    return linhas


def _corpo(grade: list[dict], tipobg: str | None, semestre: int | None) -> tuple[list[str], int]:
    """Os blocos da grade, por tipo e por semestre ideal, e quantas entraram."""
    partes: list[str] = []
    restantes = MAX_LINHAS

    for sigla, titulo in BLOCOS.items():
        if tipobg and sigla != tipobg:
            continue

        do_bloco = [d for d in grade if d.get("tipobg") == sigla]
        semestres = sorted({_semestre_de(d) for d in do_bloco})
        cabecalho = f"### {titulo}"

        for numero in semestres:
            if semestre and numero != semestre:
                continue

            do_semestre = [d for d in do_bloco if _semestre_de(d) == numero][:restantes]
            if not do_semestre:
                break  # o teto de linhas acabou

            if cabecalho:
                partes.append(cabecalho)  # só quando há mesmo o que listar embaixo
                cabecalho = ""
            restantes -= len(do_semestre)
            partes.append(f"**{numero}º semestre ideal**\n" + "\n".join(_tabela(do_semestre)))

    return partes, MAX_LINHAS - restantes


def _rodape(
    grade: list[dict], tipobg: str | None, semestre: int | None, mostradas: int
) -> list[str]:
    """Avisa o que ficou de fora, para o modelo não concluir que não existe."""
    avisos = []

    omitidos = [
        f"{len([d for d in grade if d.get('tipobg') == sigla])} "
        f"{titulo.lower().removeprefix('disciplinas ')}"
        for sigla, titulo in BLOCOS.items()
        if tipobg and sigla != tipobg and any(d.get("tipobg") == sigla for d in grade)
    ]
    if omitidos:
        # "ao longo de todo o curso" não é enfeite: com filtro de semestre o
        # modelo lê a contagem como se fosse daquele semestre só.
        avisos.append(
            f"Ao longo de todo o curso há ainda {' e '.join(omitidos)}, que não "
            "estão listadas aqui. Chame de novo com o 'tipo' correspondente "
            "para vê-las."
        )

    # Com filtro de semestre o resto não foi cortado, foi o que se pediu.
    cabiveis = [
        d for d in grade
        if (tipobg is None or d.get("tipobg") == tipobg)
        and (semestre is None or _semestre_de(d) == semestre)
    ]
    if mostradas < len(cabiveis):
        avisos.append(
            f"Listadas {mostradas} de {len(cabiveis)} disciplinas; o resto foi "
            "cortado por tamanho. Use 'semestre' para pedir um semestre de cada vez."
        )

    return avisos


# ─────────────────────────────────────────────
# A ferramenta
# ─────────────────────────────────────────────
def consultar_grade_curricular(curso, unidade=None, tipo=None, semestre=None) -> tuple[str, list[str]]:
    """Consulta a grade curricular de um curso de ingresso da graduação."""
    curso = str(curso or "").strip()
    if not curso:
        return "Informe o nome do curso de ingresso (ex.: 'engenharia de computação').", []

    chave = normalizar(tipo or "obrigatorias")
    if chave not in TIPOS:
        return (
            f"Não conheço o tipo '{tipo}'. Os valores aceitos são: "
            f"{', '.join(TIPOS_PUBLICOS)}.",
            [],
        )
    tipobg = TIPOS[chave]

    try:
        semestre = int(semestre) if semestre not in (None, "") else None
    except (TypeError, ValueError):
        semestre = None

    unidade = str(unidade or "").strip()
    achados = _procurar(_catalogo(), curso, unidade)

    if not achados:
        onde = f" na unidade '{unidade}'" if unidade else ""
        return (
            f"Não encontrei nenhum curso de ingresso com '{curso}'{onde}. "
            "Tente o nome como aparece no JupiterWeb (ex.: 'engenharia de "
            "computação', 'ciências moleculares', 'matemática aplicada').",
            [URL_PAGINA],
        )

    if len(achados) > 1:
        opcoes = [f"- {c['rotulo']} — {c['unidade']}" for c in achados[:MAX_OPCOES]]
        sobra = (
            f" (listando os {MAX_OPCOES} primeiros)"
            if len(achados) > MAX_OPCOES else ""
        )
        topo = (
            f"'{curso}' casa com {len(achados)} cursos de ingresso{sobra}. Chame "
            "de novo com o nome exato de um deles; o argumento 'unidade' também "
            "ajuda a desempatar."
        )
        return f"{topo}\n\n" + "\n".join(opcoes), [URL_PAGINA]

    escolhido = achados[0]
    argumentos = {"codcur": escolhido["codcur"], "codhab": escolhido["codhab"]}

    # As duas consultas em paralelo: a grade é a lenta, a duração sai de graça.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_info = executor.submit(
            jupiter.cache, ("info", *argumentos.values()), jupiter.TTL_LONGO,
            lambda: jupiter.dwr("obter", "pubObterInfoCurso", argumentos),
        )
        grade = jupiter.cache(
            ("grade", *argumentos.values()), jupiter.TTL_LONGO,
            lambda: jupiter.dwr(
                "listar", "pubGradeCurricular", {**argumentos, "tipo": "N"}
            ),
        )
        info = futuro_info.result()

    if not grade:
        return (
            f"O JupiterWeb não publica a grade curricular de {escolhido['rotulo']} "
            f"({escolhido['unidade']}).",
            [URL_PAGINA],
        )

    cabecalho = [f"## {escolhido['rotulo']}", escolhido["unidade"]]
    if info and info[0].get("duridlhab"):
        duracao = info[0]
        cabecalho.append(
            f"Duração ideal: {duracao['duridlhab']} semestres "
            f"(mínimo {duracao.get('durminhab', '?')}, "
            f"máximo {duracao.get('durmaxhab', '?')})"
        )
    partes, mostradas = _corpo(grade, tipobg, semestre)
    if not partes:
        alvo = f"o {semestre}º semestre ideal" if semestre else "esse tipo de disciplina"
        return "\n".join(cabecalho) + f"\n\nA grade não tem {alvo}.", [URL_PAGINA]

    rodape = _rodape(grade, tipobg, semestre, mostradas)
    return "\n\n".join(["\n".join(cabecalho)] + partes + rodape), [URL_PAGINA]


def registrar(registro: Registro) -> None:
    """Registra a ferramenta no registro dado."""
    registro.ferramenta(
        nome="consultar_grade_curricular",
        descricao=(
            "Grade curricular de um curso de graduação: as disciplinas de cada "
            "semestre ideal, com créditos e carga horária. Use para o que se "
            "estuda num curso ou num semestre, e quanto ele dura."
        ),
        parametros={
            "type": "object",
            "properties": {
                "curso": {
                    "type": "string",
                    "description": (
                        "Nome do curso, como o aluno diria (ex.: 'engenharia "
                        "de computação', 'direito')."
                    ),
                },
                "unidade": {
                    "type": "string",
                    "description": (
                        "Unidade ou sigla (ex.: 'Poli', 'IME'), para desempatar "
                        "cursos de mesmo nome."
                    ),
                },
                "tipo": {
                    "type": "string",
                    "enum": ["obrigatorias", "eletivas", "livres", "todas"],
                    "description": "Omita para as obrigatórias.",
                },
                "semestre": {
                    "type": "integer",
                    "description": "Listar só um semestre ideal.",
                },
            },
            "required": ["curso"],
        },
    )(consultar_grade_curricular)
