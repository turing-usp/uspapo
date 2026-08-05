"""Disciplinas e turmas do JupiterWeb: ficha, requisitos, horários e professores.

O aluno chega na "Busca por Disciplinas" (jupDisciplinaBusca?tipo=D&codmnu=6755),
que é só um formulário: o botão manda o navegador para `obterDisciplina`, com
`sgldis` OU `nomdis`. As duas ferramentas daqui usam os mesmos endpoints que o
navegador usaria, e devolvem como fonte as URLs que o aluno consegue abrir.

    obterDisciplina?nomdis=…      lista de siglas que casam com o nome
    obterDisciplina?sgldis=XXX    a ficha (o `verdis` dos links é opcional)
    obterTurma?sgldis=XXX         as turmas do semestre corrente
    listarCursosRequisitos?…      os requisitos, repetidos curso a curso

Sobre o oferecimento, um limite do JupiterWeb que vale registrar porque parece
bug e não é: a `obterTurma` publica APENAS o semestre corrente. Verificado em 93
turmas de 47 disciplinas de cinco unidades diferentes: todas com exatamente o
mesmo período. Não há parâmetro de ano ou semestre (testados anosem, anoexe,
semexe, periodo, codtur: nenhum muda a resposta), nem página com seletor, e o
alvo DWR `pubObterTurma` existe mas devolve vazio para toda combinação de
argumento que dá para adivinhar de fora.

E turma lotada NÃO some: turmas com 28/28 e 64/64 matriculados aparecem
normalmente, com horário e vagas. Quando a ferramenta diz que não há turma, é
porque a disciplina não tem nenhuma no semestre publicado — quase sempre por ser
do outro semestre do curso. Dizer isso ao modelo é obrigação: senão ele conclui
que a disciplina acabou, ou que lotou.

Três armadilhas do JupiterWeb, todas tratadas aqui:

- **A sigla tem 7 caracteres, sempre.** Menos que isso e o site devolve uma
  página de erro; barrar antes economiza a viagem. Nem toda sigla é
  alfanumérica: 5950106 e 1400105 são válidas.
- **O nome vai sem acento e em caixa baixa**: é o que o JavaScript do
  formulário faz antes de montar a URL, e o backend conta com isso.
- **A ficha vem duplicada em inglês**, dentro de `<i>`. O `sem_ingles` corta.

Como o bandejão, esta ferramenta é a mesma nos dois backends: não cria `Registro`
próprio, expõe uma `registrar(registro)` que os entrypoints chamam.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from uspapo.ferramentas import Registro, em_lista, normalizar
from uspapo.ferramentas import jupiter

# O formulário só aceita sigla completa; qualquer outro tamanho é erro do site.
SIGLA = re.compile(r"^[A-Za-z0-9]{7}$")

# Cada turma vem embrulhada nesta div — é o que separa uma da outra.
_BLOCO_TURMA = re.compile(r'<div style="border: 2px solid #658CCF')

_DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")

# Consulta que falhou, para não ser confundida com "não há oferecimento".
_FALHA = object()

# Rótulos da ficha, na ordem da página. O valor de cada um é tudo o que vem
# entre ele e o próximo: regra que serve tanto para "Créditos Aula:" (uma
# célula) quanto para "Bibliografia" (um parágrafo) e para os docentes (vários).
_FICHA = {
    "creditos aula:": "Créditos aula",
    "creditos trabalho:": "Créditos trabalho",
    "carga horaria total:": "Carga horária",
    "tipo:": "Tipo",
    "ativacao:": "Em vigor desde",
    "desativacao:": "Desativada em",
    "ementa": "Ementa",
    "objetivos": "Objetivos",
    "conteudo programatico": "Conteúdo programático",
    "instrumentos e criterios de avaliacao": None,  # só cabeçalho, sem conteúdo
    "metodo de avaliacao": "Método de avaliação",
    "criterio de avaliacao": "Critério de avaliação",
    "norma de recuperacao": "Norma de recuperação",
    "bibliografia": "Bibliografia",
    "docente(s) responsavel(eis)": "Docentes responsáveis",
}
# Uma linha por rótulo; os longos ganham parágrafo próprio.
_CURTOS = ("Créditos aula", "Créditos trabalho", "Carga horária", "Tipo",
           "Em vigor desde", "Desativada em")

# Texto acima disso vira custo de token sem virar informação.
MAX_SECAO = 1200
MAX_RESULTADOS = 60
MAX_TURMAS = 20
# Uma grade de graduação raramente passa disso, e cada disciplina é um GET.
MAX_DISCIPLINAS = 8
# Teto de turmas somando todas as disciplinas do pedido. Cálculo II sozinha tem
# 13 turmas; oito disciplinas assim estourariam o orçamento da pergunta.
MAX_TURMAS_TOTAL = 40
# Duas disciplinas com muitas turmas rendem dezenas de combinações que batem;
# listar todas não ajuda a escolher.
MAX_CHOQUES = 6


# ─────────────────────────────────────────────
# Leitura das páginas
# ─────────────────────────────────────────────
def _ficha(bruto: str) -> tuple[str, dict[str, str]]:
    """Lê a ficha da disciplina: devolve o título e os campos rotulados."""
    inicio = bruto.find("Disciplina:")
    # O corpo termina no link dos requisitos; recuar até o "<" evita levar junto
    # meia tag aberta, que sobreviveria à limpeza e vazaria para o modelo.
    fim = bruto.rfind("<", inicio, bruto.find("listarCursosRequisitos", inicio))
    corpo = bruto[inicio:fim if fim > inicio else None]

    titulo = jupiter.achatar(corpo[: corpo.find("<")]).removeprefix("Disciplina:").strip()

    campos: dict[str, str] = {}
    rotulo = None
    partes: list[str] = []

    for celula in jupiter.celulas(jupiter.sem_ingles(corpo)):
        chave = normalizar(celula)
        if chave in _FICHA:
            if rotulo and partes:
                campos[rotulo] = " ".join(partes)
            rotulo, partes = _FICHA[chave], []
        elif rotulo and celula:
            partes.append(celula)

    if rotulo and partes:
        campos[rotulo] = " ".join(partes)

    return titulo, campos


def _requisitos(bruto: str) -> list[tuple[str, list[str]]]:
    """Lê os requisitos e agrupa os cursos que exigem exatamente o mesmo conjunto.

    O JupiterWeb repete o requisito curso a curso — MAT2454 rende 41 blocos
    idênticos, todos pedindo MAT2453. Guardar o conjunto uma vez e listar quem o
    exige é a mesma economia que o bandejão faz com o aviso repetido nas células.
    """
    inicio = bruto.find("Lista de Requisitos")
    if inicio < 0:
        return []

    por_conjunto: dict[tuple[str, ...], list[str]] = {}
    curso = None
    grupos: list[list[str]] = []
    alternativa = False

    def fechar():
        # O mesmo requisito aparece repetido dentro de um grupo em vários
        # cursos ("A ou A"), e cursos diferentes têm o mesmo nome de exibição
        # (codcur 3032 e 3033 são os dois "Ciclo Básico - Engenharia Elétrica").
        # Sem tirar as duas repetições, o agrupamento não agrupa nada.
        conjunto = tuple(" ou ".join(dict.fromkeys(grupo)) for grupo in grupos if grupo)
        if curso and conjunto:
            cursos = por_conjunto.setdefault(conjunto, [])
            if curso not in cursos:
                cursos.append(curso)

    for linha in jupiter.linhas(bruto[inicio:]):
        celulas = [c for c in linha if c]
        if not celulas:
            continue

        if celulas[0].startswith("Curso:"):
            fechar()
            # "Curso: 3011 Engenharia - Habilitação: Habilitação: Eng. Civil -
            # Período ideal: 2". O período ideal é assunto da grade curricular,
            # não do requisito, e só atrapalharia o agrupamento.
            curso = re.sub(r"^\d+\s*", "", celulas[0].removeprefix("Curso:").strip())
            curso = re.sub(r"\s*-\s*Período ideal:.*$", "", curso)
            curso = curso.replace("Habilitação: Habilitação:", "Habilitação:")
            grupos, alternativa = [], False

        elif celulas[0].lower() == "ou":
            alternativa = True

        elif curso and len(celulas) >= 2:
            requisito = f"{celulas[0]} ({celulas[1].lower()})"
            if alternativa and grupos:
                grupos[-1].append(requisito)
            else:
                grupos.append([requisito])
            alternativa = False

    fechar()
    return [(" · ".join(conjunto), cursos) for conjunto, cursos in por_conjunto.items()]


def _turma(bloco: str) -> dict:
    """Lê um bloco de turma: dados, horários e o total de vagas por categoria."""
    dados: dict[str, str] = {}
    horarios: list[str] = []
    vagas: list[str] = []
    matriculados = 0

    for celulas in jupiter.linhas(bloco):
        if len(celulas) == 2 and celulas[0].endswith(":"):
            dados[normalizar(celulas[0]).rstrip(":")] = celulas[1]

        elif len(celulas) == 4 and normalizar(celulas[0])[:3] in _DIAS:
            dia, comeco, fim, professor = celulas
            # Guardado em campos, e não já formatado: é comparando início e fim
            # que se acha choque de horário entre duas disciplinas.
            horarios.append({
                "dia": normalizar(dia)[:3],
                "inicio": comeco,
                "fim": fim or comeco,
                "professor": professor,
            })

        # A tabela de vagas traz o total da categoria numa linha de 5 células e
        # a quebra por curso em linhas de 6, com a primeira vazia por causa do
        # recuo. Só o total interessa: a quebra por curso é o grosso da página.
        elif len(celulas) == 5 and celulas[0] and celulas[1].isdigit():
            categoria, oferecidas, _, _, ocupadas = celulas
            vagas.append(f"{categoria} {oferecidas}")
            matriculados += int(ocupadas)

    return {
        "codigo": dados.get("codigo da turma", "?"),
        "inicio": dados.get("inicio", ""),
        "fim": dados.get("fim", ""),
        "tipo": dados.get("tipo da turma", ""),
        "observacoes": dados.get("observacoes", ""),
        "horarios": horarios,
        "vagas": vagas,
        "matriculados": matriculados,
    }


# ─────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────
def _cortar(texto: str) -> str:
    return texto if len(texto) <= MAX_SECAO else texto[:MAX_SECAO].rstrip() + "…"


def _formatar_ficha(sigla: str, titulo: str, campos: dict, requisitos: list) -> str:
    partes = [f"## {titulo}"]

    resumo = [f"{rotulo}: {campos[rotulo]}" for rotulo in _CURTOS if campos.get(rotulo)]
    if resumo:
        partes.append(" | ".join(resumo))

    for rotulo, valor in campos.items():
        if rotulo not in _CURTOS and valor:
            partes.append(f"**{rotulo}**\n{_cortar(valor)}")

    if requisitos:
        partes.append("**Requisitos**\n" + "\n".join(
            conjunto if len(requisitos) == 1
            else f"{conjunto} — para {', '.join(cursos[:6])}"
                 + (f" e mais {len(cursos) - 6} cursos" if len(cursos) > 6 else "")
            for conjunto, cursos in requisitos
        ))
    else:
        partes.append("**Requisitos**\nEsta disciplina não tem requisitos.")

    return "\n\n".join(partes)


def _quando(horario: dict) -> str:
    inicio, fim = horario["inicio"], horario["fim"]
    faixa = f"{inicio}–{fim}" if fim != inicio else inicio
    return f"{horario['dia']} {faixa}"


def _formatar_turmas(sigla: str, cabecalho: list[str], turmas: list[dict], cortadas: int) -> str:
    partes = ["\n".join(cabecalho)]

    for turma in turmas:
        tipo = f" ({turma['tipo']})" if turma["tipo"] else ""
        linhas = [f"**Turma {turma['codigo']}**{tipo}"]

        linhas += [
            f"- {_quando(h)}" + (f" — {h['professor']}" if h["professor"] else "")
            for h in turma["horarios"]
        ] or ["- Horário não publicado."]

        if turma["vagas"]:
            linhas.append(
                f"- Vagas: {', '.join(turma['vagas'])} — {turma['matriculados']} matriculados"
            )
        if turma["observacoes"]:
            linhas.append(f"- Observações: {turma['observacoes']}")

        partes.append("\n".join(linhas))

    if cortadas:
        partes.append(
            f"…e mais {cortadas} turmas de {sigla} não listadas (nem "
            "consideradas na checagem de choque abaixo)."
        )

    return "\n\n".join(partes)


# ─────────────────────────────────────────────
# Choque de horário
# ─────────────────────────────────────────────
def _sobrepoe(um: dict, outro: dict) -> bool:
    """Dois horários caem no mesmo dia e se cruzam no relógio.

    Comparar "08:00" < "09:40" como texto funciona porque HH:MM tem largura
    fixa; o zero à esquerda é o que garante a ordem.
    """
    return (
        um["dia"] == outro["dia"]
        and um["inicio"] < outro["fim"]
        and outro["inicio"] < um["fim"]
    )


def _choque_entre(uma: dict, outra: dict) -> dict | None:
    """O primeiro horário em que duas turmas se cruzam, se houver."""
    for horario in uma["horarios"]:
        for concorrente in outra["horarios"]:
            if _sobrepoe(horario, concorrente):
                return {"quando": _quando(horario), "outro": _quando(concorrente)}
    return None


def _choques(ofertadas: list[tuple[str, list[dict]]]) -> tuple[list[str], bool]:
    """Compara as disciplinas duas a duas e descreve os choques de horário.

    Turmas da MESMA disciplina não entram: o aluno escolhe uma delas, elas são
    alternativas, não conflito. O que impede uma grade é o choque entre turmas
    de disciplinas diferentes.

    Devolve também se sobrou alguma combinação livre — sem isso não dá para
    dizer ao modelo que o que não foi listado está liberado.
    """
    avisos: list[str] = []
    sobrou_combinacao = False

    for posicao, (sigla, turmas) in enumerate(ofertadas):
        for outra_sigla, outras_turmas in ofertadas[posicao + 1:]:
            pares = [
                (uma, outra, choque)
                for uma in turmas
                for outra in outras_turmas
                if (choque := _choque_entre(uma, outra))
            ]
            if not pares:
                sobrou_combinacao = True
                continue

            # Se toda combinação bate, dizer isso vale mais (e custa menos) do
            # que listar as 225 combinações de duas disciplinas com 15 turmas.
            if len(pares) == len(turmas) * len(outras_turmas):
                avisos.append(
                    f"- {sigla} e {outra_sigla} são incompatíveis: todas as "
                    f"combinações de turma se chocam."
                )
                continue

            sobrou_combinacao = True
            for uma, outra, choque in pares[:MAX_CHOQUES]:
                avisos.append(
                    f"- {sigla} turma {uma['codigo']} ({choque['quando']}) bate "
                    f"com {outra_sigla} turma {outra['codigo']} "
                    f"({choque['outro']})."
                )
            if len(pares) > MAX_CHOQUES:
                avisos.append(
                    f"- …e mais {len(pares) - MAX_CHOQUES} combinações de "
                    f"{sigla} com {outra_sigla} que se chocam."
                )

    return avisos, sobrou_combinacao


# ─────────────────────────────────────────────
# As ferramentas
# ─────────────────────────────────────────────
def _buscar_ficha(sigla: str) -> tuple[str, list[str]]:
    """A ficha da disciplina, com os requisitos buscados em paralelo.

    São duas páginas diferentes do JupiterWeb; buscá-las juntas custa o mesmo
    que buscar a mais lenta, como as quatro consultas do bandejão.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_requisitos = executor.submit(
            jupiter.cache, ("requisitos", sigla), jupiter.TTL_CURTO,
            lambda: jupiter.pagina("listarCursosRequisitos", coddis=sigla),
        )
        bruto = jupiter.cache(
            ("disciplina", sigla), jupiter.TTL_CURTO,
            lambda: jupiter.pagina("obterDisciplina", sgldis=sigla),
        )
        pagina_requisitos = futuro_requisitos.result()

    aviso = jupiter.mensagem(bruto)
    if aviso:
        return f"Não encontrei a disciplina {sigla} no JupiterWeb ({aviso})", []

    titulo, campos = _ficha(bruto)
    fonte = jupiter.url("obterDisciplina", sgldis=sigla)
    return (
        _formatar_ficha(sigla, titulo, campos, _requisitos(pagina_requisitos)),
        [fonte],
    )


def buscar_disciplina(nome=None, sigla=None) -> tuple[str, list[str]]:
    """Busca uma disciplina por sigla ou por nome, como o formulário do site."""
    sigla = str(sigla or "").strip().upper()
    nome = str(nome or "").strip()

    if not sigla and not nome:
        return "Informe a sigla da disciplina (ex.: MAT2453) ou parte do nome.", []

    if sigla:
        if not SIGLA.match(sigla):
            return (
                f"'{sigla}' não é uma sigla de disciplina válida: a sigla tem "
                "exatamente 7 caracteres (ex.: MAT2453, ACH2011, 5950106). "
                "Se você só sabe o nome, use o argumento 'nome'.",
                [],
            )
        return _buscar_ficha(sigla)

    # O JavaScript do formulário tira o acento e baixa a caixa antes de montar a
    # URL; o backend do JupiterWeb conta com isso para casar o nome.
    termo = normalizar(nome)
    bruto = jupiter.cache(
        ("busca", termo), jupiter.TTL_LONGO,
        lambda: jupiter.pagina("obterDisciplina", nomdis=termo, sgldis=""),
    )

    aviso = jupiter.mensagem(bruto)
    if aviso:
        return f"Nenhuma disciplina encontrada para '{nome}' no JupiterWeb.", []

    achados = re.findall(
        r"obterDisciplina\?sgldis=([A-Za-z0-9]+)[^>]*>(.*?)</a>", bruto, re.S | re.I
    )
    achados = [(s, jupiter.achatar(n)) for s, n in achados]

    if not achados:
        return f"Nenhuma disciplina encontrada para '{nome}' no JupiterWeb.", []

    # Um resultado só: já entrega a ficha e poupa uma rodada de ferramenta.
    if len(achados) == 1:
        return _buscar_ficha(achados[0][0])

    fonte = jupiter.url("jupDisciplinaBusca", tipo="D", codmnu="6755")
    linhas = [f"| {s} | {n} |" for s, n in achados[:MAX_RESULTADOS]]
    topo = (
        f"{len(achados)} disciplinas casam com '{nome}'. Chame esta ferramenta "
        "de novo com a 'sigla' da que interessar para ver a ficha completa."
    )
    if len(achados) > MAX_RESULTADOS:
        topo += f" Listando as {MAX_RESULTADOS} primeiras."

    return (
        f"{topo}\n\n| Sigla | Disciplina |\n| --- | --- |\n" + "\n".join(linhas),
        [fonte],
    )


def _turmas_de(sigla: str) -> tuple[list[str], list[dict]] | None:
    """Cabeçalho e turmas de uma disciplina, ou None se não há oferecimento."""
    bruto = jupiter.cache(
        ("turmas", sigla), jupiter.TTL_CURTO,
        lambda: jupiter.pagina("obterTurma", sgldis=sigla),
    )
    if jupiter.mensagem(bruto):
        return None

    blocos = _BLOCO_TURMA.split(bruto)
    turmas = [_turma(bloco) for bloco in blocos[1:]]
    if not turmas:
        return None

    # Antes do primeiro bloco vêm o banner do Júpiter, a unidade, o departamento
    # e o nome da disciplina, cada um na sua célula.
    celulas = [c for c in jupiter.celulas(blocos[0]) if c]
    posicao = next((n for n, c in enumerate(celulas) if c.startswith("Disciplina:")), -1)

    cabecalho = [f"### {sigla}"]
    if posicao >= 0:
        cabecalho = [f"### {celulas[posicao].removeprefix('Disciplina:').strip()}"]
    if posicao >= 2:
        cabecalho.append(f"{celulas[posicao - 2]} — {celulas[posicao - 1]}")

    return cabecalho, turmas


def _tentar_turmas(sigla: str):
    """Busca as turmas de uma disciplina; uma que falhe não derruba a grade.

    Devolve os dados, None quando o JupiterWeb diz que não há oferecimento, ou
    _FALHA quando a consulta em si deu errado. A diferença importa: tratar um
    timeout como "não tem turma" faz o modelo afirmar ao aluno que a disciplina
    não é oferecida, que é errado e soa exatamente igual ao caso verdadeiro.
    """
    try:
        return _turmas_de(sigla)
    except Exception as erro:
        print(f"[disciplinas] turmas de {sigla} falharam: {type(erro).__name__}: {erro}")
        return _FALHA


def _periodo(ofertadas: list[tuple[str, list[dict]]]) -> str:
    """O intervalo que o JupiterWeb está publicando, lido das próprias turmas.

    Dizer isso em toda resposta é o que deixa o modelo explicar por que uma
    disciplina "sumiu": ela não está no semestre publicado, e não há outro.
    """
    inicios = sorted({t["inicio"] for _, turmas in ofertadas for t in turmas if t["inicio"]})
    fins = sorted({t["fim"] for _, turmas in ofertadas for t in turmas if t["fim"]})
    if not inicios or not fins:
        return "O JupiterWeb publica apenas o oferecimento do semestre corrente."
    return (
        f"Oferecimento publicado pelo JupiterWeb: {inicios[0]} a {fins[-1]}. "
        "É o único semestre disponível — não há dado de semestres anteriores "
        "nem do próximo antes da matrícula."
    )


def consultar_turmas(siglas=None, sigla=None) -> tuple[str, list[str]]:
    """Turmas oferecidas no semestre corrente, para uma ou várias disciplinas."""
    pedidas = em_lista(siglas if siglas is not None else sigla, [])
    pedidas = list(dict.fromkeys(s.strip().upper() for s in pedidas))

    if not pedidas:
        return "Informe a sigla da disciplina (ex.: MAC0110).", []

    invalidas = [s for s in pedidas if not SIGLA.match(s)]
    aceitas = [s for s in pedidas if SIGLA.match(s)]
    validas, excedentes = aceitas[:MAX_DISCIPLINAS], aceitas[MAX_DISCIPLINAS:]
    if not validas:
        return (
            f"{', '.join(invalidas)} não é sigla de disciplina válida: a sigla "
            "tem exatamente 7 caracteres (ex.: MAT2453). Use buscar_disciplina "
            "pelo nome para descobrir a sigla.",
            [],
        )

    # Em paralelo: montar uma grade de seis disciplinas em série passaria de um
    # segundo por disciplina, com o aluno parado no "Usando ferramenta...".
    with ThreadPoolExecutor(max_workers=min(len(validas), 6)) as executor:
        resultados = list(executor.map(_tentar_turmas, validas))

    achadas = [(s, *r) for s, r in zip(validas, resultados) if isinstance(r, tuple)]
    sem_oferta = [s for s, r in zip(validas, resultados) if r is None]
    falharam = [s for s, r in zip(validas, resultados) if r is _FALHA]

    # O corte vem ANTES da análise de choque: apontar um conflito com uma turma
    # que não foi listada deixaria o aluno procurando o que não está ali.
    teto = MAX_TURMAS if len(achadas) <= 1 else max(3, MAX_TURMAS_TOTAL // len(achadas))
    achadas = [(s, cab, turmas[:teto], max(0, len(turmas) - teto)) for s, cab, turmas in achadas]
    ofertadas = [(s, turmas) for s, _, turmas, _ in achadas]

    partes: list[str] = []
    fontes: list[str] = []

    if achadas:
        partes.append(f"## Turmas de {', '.join(s for s, *_ in achadas)}\n{_periodo(ofertadas)}")
        for sigla_ok, cabecalho, turmas, cortadas in achadas:
            partes.append(_formatar_turmas(sigla_ok, cabecalho, turmas, cortadas))
            fontes.append(jupiter.url("obterTurma", sgldis=sigla_ok))

    if sem_oferta:
        # Sem esta frase o modelo conclui que a disciplina deixou de existir, ou
        # que está lotada. Nenhum dos dois: turma lotada aparece normalmente,
        # com horário e tudo.
        partes.append(
            f"**Sem turma no semestre publicado:** {', '.join(sem_oferta)}. "
            "Essas disciplinas não têm nenhuma turma no oferecimento atual do "
            "JupiterWeb, o que não quer dizer que estejam lotadas (turma lotada "
            "continua aparecendo, com horário e vagas). Em geral são disciplinas "
            "do outro semestre do curso."
        )

    if falharam:
        partes.append(
            f"**Não consegui consultar:** {', '.join(falharam)}. O JupiterWeb "
            "não respondeu a tempo. NÃO conclua que essas disciplinas não têm "
            "turma: não se sabe. Elas também ficaram de fora da checagem de "
            "choque. Vale tentar de novo."
        )

    if invalidas:
        partes.append(f"Siglas ignoradas por não terem 7 caracteres: {', '.join(invalidas)}.")

    if excedentes:
        partes.append(
            f"Só cabem {MAX_DISCIPLINAS} disciplinas por consulta; ficaram de "
            f"fora {', '.join(excedentes)}. Chame de novo com elas."
        )

    if len(ofertadas) > 1:
        avisos, sobrou_combinacao = _choques(ofertadas)
        if not avisos:
            # "todas" só vale se todas foram mesmo consultadas.
            alcance = "entre as que consegui consultar" if falharam else "entre todas"
            partes.append(
                f"### Choques de horário\nNenhum {alcance}: dá para cursá-las "
                "juntas, com qualquer combinação das turmas acima."
            )
        else:
            # Sem a última linha o modelo lê a lista como se tudo batesse.
            if sobrou_combinacao:
                avisos.append(
                    "- Qualquer combinação de turmas não citada acima NÃO se choca."
                )
            partes.append("### Choques de horário\n" + "\n".join(avisos))

    return "\n\n".join(partes), fontes


def registrar(registro: Registro) -> None:
    """Registra as duas ferramentas no registro dado."""
    registro.ferramenta(
        nome="buscar_disciplina",
        descricao=(
            "Ficha de uma disciplina: créditos, carga horária, ementa, "
            "programa, avaliação, bibliografia, docentes e requisitos. Use "
            "para qualquer pergunta sobre uma matéria específica."
        ),
        parametros={
            "type": "object",
            "properties": {
                "sigla": {
                    "type": "string",
                    "description": "Código de 7 caracteres (ex.: MAT2453, 5950106).",
                },
                "nome": {
                    "type": "string",
                    "description": (
                        "Parte do nome, quando não souber a sigla. Devolve as "
                        "siglas que casam."
                    ),
                },
            },
            "required": [],
        },
    )(buscar_disciplina)

    registro.ferramenta(
        nome="consultar_turmas",
        descricao=(
            "Turmas do semestre corrente: horário de cada aula, professor e "
            "vagas. Aponta também os choques de horário entre as disciplinas "
            "pedidas: é assim que se monta uma grade.\n"
            "OBRIGATÓRIO: uma ÚNICA chamada com TODAS as disciplinas de uma "
            "vez. Nunca chame uma vez por disciplina, só a chamada única "
            "compara os horários e devolve os choques.\n"
            "Só existe o semestre corrente."
        ),
        parametros={
            "type": "object",
            "properties": {
                "siglas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Códigos de 7 caracteres de TODAS as disciplinas da "
                        f"pergunta, até {MAX_DISCIPLINAS} — ex.: "
                        "['MAC0121','MAT2454']. Sempre uma lista, mesmo com "
                        "uma disciplina só."
                    ),
                },
            },
            "required": ["siglas"],
        },
    )(consultar_turmas)
