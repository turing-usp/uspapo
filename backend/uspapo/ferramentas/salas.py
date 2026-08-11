"""Sala e prédio das aulas, do USPolis (uspolis.com.br).

O USPolis é o sistema de alocação de salas da Escola Politécnica, feito e mantido
por alunos da Poli (PCS). É ele que a secretaria usa para dizer qual turma ocupa
qual sala em qual horário, e é o único lugar onde esse dado existe publicado.

Ele preenche exatamente o buraco do JupiterWeb: a `consultar_turmas` devolve dia,
horário, professor e vagas de qualquer unidade da USP, e NÃO devolve sala, porque
o JupiterWeb não publica sala. Aqui é o contrário: sala e prédio, só da Poli.

ESCOPO, que é a coisa mais importante deste módulo: o USPolis conhece 10 prédios
(Elétrica, Biênio, Civil, Mecânica, Química, Produção, Minas e Petróleo,
Metalúrgica e Materiais, Administração e FAU), 137 salas e ~720 disciplinas, TODAS
da Poli. Perguntar por MAC0110 ou por qualquer coisa do IME, da FEA ou do IF não
devolve nada, e "não devolve nada" aqui não quer dizer "não tem aula". Por isso
todo caminho de erro deste módulo devolve prosa proibindo o modelo de concluir
ausência, e a `descricao` do schema traz o escopo em caixa alta.

Sobre a API: `www.uspolis.com.br/api` é o backend FastAPI do próprio site, com o
schema aberto em `/api/openapi.json`. As rotas marcadas `Public` respondem sem
autenticação nenhuma (só `/health` exige `x-api-key`), e o `robots.txt` do domínio
é `Disallow:` vazio, ou seja, libera tudo. Não há nada a raspar: é JSON.

Duas rotas, e nessa ordem:

1. **`GET /subjects`** — o catálogo inteiro, ~720 disciplinas, 250 KB, ~1,5 s. Dá
   o `id` numérico a partir da sigla ou do nome. Vem para o memo de seis horas
   reduzido a uma tupla de registros: guardar os 250 KB de JSON por seis horas
   para usar três campos seria desperdício de memória do worker.

2. **`GET /classes/subject/{id}`** — as turmas da disciplina, ~2 KB, ~60 ms. Cada
   turma traz `schedules[]`, e é lá que estão `classroom` e `building`, junto de
   `week_day` (**0 = segunda**, confirmado contra a data real das turmas) e do
   horário. A rota já filtra pelo semestre corrente sozinha.

Existe uma terceira, `GET /classes/subjects?subject_ids=`, que buscaria várias
disciplinas de uma vez. Ela responde **401**: apesar do nome, não é pública. Por
isso a ferramenta atende uma disciplina por chamada.

Horário sem sala é caso comum, não borda: no semestre medido, 64 dos 707 horários
estavam com `allocated: false` (`classroom` e `building` nulos). A alocação sai
perto do início das aulas e muda durante o semestre — daí o TTL curto e a
ressalva pedindo que o aluno confira no dia.

Ao contrário da `buscar_documentos`, esta ferramenta é a MESMA nos dois backends:
não existe versão simulada do USPolis. Por isso este módulo não cria um `Registro`
próprio. Ele expõe uma `registrar(registro)` que os dois entrypoints chamam com o
registro deles.
"""

import requests

from uspapo.ferramentas import Registro, cache, casa, normalizar

BASE = "https://www.uspolis.com.br/api"
URL_CATALOGO = f"{BASE}/subjects"
URL_TURMAS = BASE + "/classes/subject/{id}"

# A página pública equivalente, para o aluno abrir e conferir. Vai SÓ na lista de
# fontes: o frontend já as renderiza embaixo da resposta.
URL_PUBLICA = "https://uspolis.com.br/public/find-classes"

TIMEOUT = 12

# O catálogo muda de semestre em semestre; a alocação muda dentro do semestre e,
# perto do começo das aulas, dentro da semana. Os mesmos dois patamares do
# JupiterWeb (jupiter.TTL_LONGO / TTL_CURTO).
TTL_CATALOGO = 21600
TTL_TURMAS = 1800

# Mesmo motivo do uspavalia.py: o alvo aqui não é sistema da USP, é um serviço
# mantido por alunos. Quem ler o log de acesso merece saber quem bateu na porta.
CABECALHOS = {"User-Agent": "USPapo/1.0 (chatbot de alunos da USP)"}

# `week_day` do USPolis. Zero é segunda, e não domingo: confirmado contra as datas
# reais das turmas e contra o mapa do próprio front-end deles.
DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

# Tetos de token. Uma disciplina normal tem 1 ou 2 turmas com 2 horários cada, o
# que dá umas 150 palavras; os tetos existem para o caso patológico (disciplina do
# ciclo básico com dez turmas) não comer a reserva inteira.
MAX_TURMAS = 8        # turmas detalhadas por chamada
MAX_HORARIOS = 8      # horários por turma (uma turma semanal tem 2 ou 3)
MAX_CANDIDATOS = 8    # nomes devolvidos quando a busca por nome fica ambígua

# Distingue "a consulta falhou" de "não achei nada". Confundir os dois faz o
# modelo afirmar ao aluno que a aula não tem sala quando o que houve foi timeout.
_FALHA = object()

RESSALVA = (
    "O USPolis é o sistema de alocação de salas da Escola Politécnica, mantido "
    "por alunos, e cobre APENAS a Poli: as disciplinas dela e os prédios dela. "
    "A alocação muda durante o semestre e sala pode ser trocada em cima da hora, "
    "então vale conferir no dia. Para ementa, créditos, vagas ou professor, e "
    "para disciplinas de qualquer outra unidade, use a ferramenta do JupiterWeb."
)


# ─────────────────────────────────────────────
# Rede
# ─────────────────────────────────────────────
def _json(url: str):
    """GET numa rota da API. Erro de HTTP vira exceção e o chamador decide."""
    resposta = requests.get(url, headers=CABECALHOS, timeout=TIMEOUT)
    resposta.raise_for_status()
    return resposta.json()


def _catalogo() -> tuple[tuple[int, str, str, str], ...]:
    """O catálogo inteiro, memoizado, reduzido ao que a busca usa.

    Cada registro é `(id, sigla, nome, sigla_normalizada)`. A sigla normalizada
    vem pré-computada porque a alternativa é rodar `normalizar` setecentas vezes
    a cada pergunta só para achar uma igualdade.
    """

    def produzir():
        return tuple(
            (d["id"], d["code"], d["name"], normalizar(d["code"]))
            for d in _json(URL_CATALOGO)
            if d.get("id") and d.get("code")
        )

    return cache(("uspolis", "catalogo"), TTL_CATALOGO, produzir)


def _turmas(subject_id: int) -> list[dict]:
    """As turmas do semestre corrente de uma disciplina, memoizadas."""
    return cache(
        ("uspolis", "turmas", subject_id),
        TTL_TURMAS,
        lambda: _json(URL_TURMAS.format(id=subject_id)),
    )


def _tentar(o_que: str, produzir):
    """Roda `produzir` e devolve `_FALHA` se a rede ou o JSON derem errado."""
    try:
        return produzir()
    except Exception as erro:
        print(f"[uspolis] {o_que} falhou: {type(erro).__name__}: {erro}")
        return _FALHA


# ─────────────────────────────────────────────
# Busca da disciplina
# ─────────────────────────────────────────────
def _procurar(registros, pedido: str) -> list[tuple[int, str, str, str]]:
    """Acha a disciplina pela sigla exata e, se não achar, pelo nome.

    A sigla vem primeiro e sozinha: quem escreveu 'PCS3216' quer aquela, e deixar
    a busca por nome opinar sobre isso só teria como piorar. O casamento por nome
    é o `casa` compartilhado, que já resolve acento, ordem e ligação.
    """
    alvo = normalizar(pedido)
    por_sigla = [r for r in registros if r[3] == alvo]
    if por_sigla:
        return por_sigla

    return [r for r in registros if casa(pedido, r[2])]


# ─────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────
def _hora(bruto) -> str:
    """'09:20:00' vira '09:20'. Já vem assim da API, mas nunca custa."""
    return str(bruto or "")[:5]


def _dia(bruto) -> str:
    """`week_day` para nome do dia, tolerando ausente, nulo e fora da faixa.

    O `is not None` não é zelo: `week_day` nulo comparado com `0 <=` levanta
    TypeError, e a zero é justamente a segunda-feira, o valor mais comum.
    """
    return DIAS[bruto] if isinstance(bruto, int) and 0 <= bruto < len(DIAS) else "dia não informado"


def _horario(agenda: dict) -> str:
    """Uma linha de horário: quando, onde, e o aviso quando não há onde."""
    dia = _dia(agenda.get("week_day"))
    faixa = f"{_hora(agenda.get('start_time'))}–{_hora(agenda.get('end_time'))}".strip("–")
    quando = f"{dia}, {faixa}" if faixa else dia

    sala, predio = agenda.get("classroom"), agenda.get("building")
    if not agenda.get("allocated") or not sala:
        # Nunca omitir o horário sem sala: some da resposta e o aluno conclui que
        # naquele dia não tem aula.
        return f"- {quando} — **sala ainda não alocada** no USPolis"

    onde = f"sala {sala}" + (f", prédio {predio}" if predio else "")
    return f"- {quando} — {onde}"


def _turma(turma: dict) -> str:
    """Um bloco de turma: o código, quem dá, e onde cai cada aula."""
    linhas = [f"**Turma {turma.get('code') or '(sem código)'}**"]

    professores = [p for p in (turma.get("professors") or []) if p]
    if professores:
        linhas.append(f"Professor(es): {', '.join(professores)}")

    agenda = sorted(
        turma.get("schedules") or [],
        key=lambda a: (a.get("week_day") if a.get("week_day") is not None else 9, a.get("start_time") or ""),
    )
    if not agenda:
        linhas.append("- Sem horário publicado no USPolis.")
        return "\n".join(linhas)

    linhas.extend(_horario(a) for a in agenda[:MAX_HORARIOS])
    if len(agenda) > MAX_HORARIOS:
        linhas.append(f"- (mais {len(agenda) - MAX_HORARIOS} horários não listados)")

    return "\n".join(linhas)


# ─────────────────────────────────────────────
# A ferramenta
# ─────────────────────────────────────────────
def _fora_do_escopo(pedido: str) -> str:
    return (
        f"O USPolis não conhece nenhuma disciplina que case com \"{pedido}\". Ele "
        "cobre APENAS a Escola Politécnica. NÃO conclua que a disciplina não "
        "existe, nem que ela não tem sala: se ela for de outra unidade da USP "
        "(IME, FEA, IF, Poli não), a sala simplesmente não é publicada em lugar "
        "nenhum que o USPapo alcance. Diga isso ao aluno e sugira que ele "
        "confirme com a secretaria da unidade ou no dia, no mural. Se for "
        "disciplina da Poli e mesmo assim não apareceu, peça a sigla exata."
    )


def consultar_sala(disciplina=None) -> tuple[str, list[str]]:
    """Em que sala e prédio cai cada aula de uma disciplina da Poli."""
    pedido = str(disciplina or "").strip()
    if not pedido:
        return ("Informe a sigla ou o nome da disciplina (ex.: PCS3216).", [])

    registros = _tentar("o catálogo", _catalogo)
    if registros is _FALHA:
        return (
            "O USPolis não respondeu a tempo. NÃO conclua que a disciplina não "
            "tem sala: não se sabe. Diga que a consulta falhou e que vale tentar "
            "de novo.",
            [],
        )

    achadas = _procurar(registros, pedido)
    if not achadas:
        return (_fora_do_escopo(pedido), [])

    if len(achadas) > 1:
        lista = "\n".join(f"- {sigla} — {nome}" for _, sigla, nome, _ in achadas[:MAX_CANDIDATOS])
        sobra = len(achadas) - MAX_CANDIDATOS
        extra = f"\n\n(e mais {sobra} que não couberam)" if sobra > 0 else ""
        return (
            f"\"{pedido}\" casa com mais de uma disciplina no USPolis. Pergunte "
            f"ao aluno qual delas, ou chame de novo com a sigla:\n\n{lista}{extra}"
            f"\n\n{RESSALVA}",
            [],
        )

    subject_id, sigla, nome, _ = achadas[0]

    turmas = _tentar(f"as turmas de {sigla}", lambda: _turmas(subject_id))
    if turmas is _FALHA:
        return (
            f"Encontrei {sigla} ({nome}) no USPolis, mas a consulta das turmas "
            "falhou. NÃO conclua que a disciplina não tem sala: não se sabe. "
            f"Vale tentar de novo.\n\n{RESSALVA}",
            [],
        )

    if not turmas:
        return (
            f"{sigla} ({nome}) está no USPolis, mas não tem nenhuma turma no "
            "semestre corrente. Isso quer dizer que ela não está sendo oferecida "
            "agora, não que ela tenha deixado de existir, e não que esteja "
            f"lotada.\n\n{RESSALVA}",
            [URL_PUBLICA],
        )

    partes = [f"## Salas de {sigla} — {nome}"]
    partes.extend(_turma(t) for t in turmas[:MAX_TURMAS])

    if len(turmas) > MAX_TURMAS:
        partes.append(
            f"São {len(turmas)} turmas no total; detalhei as {MAX_TURMAS} "
            "primeiras. Para uma turma específica, peça o código dela ao aluno."
        )

    partes.append(RESSALVA)
    return ("\n\n".join(partes), [URL_PUBLICA])


def registrar(registro: Registro) -> None:
    """Registra a ferramenta no registro dado.

    Ao contrário da `buscar_documentos`, esta ferramenta é a mesma nos dois
    backends, por isso quem escolhe o registro é o entrypoint, e não este
    módulo.
    """
    registro.ferramenta(
        nome="consultar_sala",
        descricao=(
            "Em que SALA e em que PRÉDIO cai cada aula de uma disciplina, por dia "
            "da semana e horário, do USPolis. Use quando perguntarem onde é a "
            "aula, em que sala, em que prédio ou onde fica a turma. ATENÇÃO: o "
            "USPolis cobre APENAS a Escola Politécnica (Poli). Não tem nada do "
            "IME, FEA, IF ou qualquer outra unidade. Se a ferramenta não achar a "
            "disciplina, isso NÃO significa que ela não existe nem que não tem "
            "sala. Para ementa, créditos, vagas, professor ou horário de "
            "qualquer unidade, use a ferramenta de turmas do JupiterWeb, que "
            "cobre a USP inteira mas não publica sala."
        ),
        parametros={
            "type": "object",
            "properties": {
                "disciplina": {
                    "type": "string",
                    "description": (
                        "A sigla (ex.: PCS3216) ou o nome da disciplina. Não "
                        "precisa ser acentuado. A sigla é mais confiável."
                    ),
                },
            },
            "required": ["disciplina"],
        },
    )(consultar_sala)
