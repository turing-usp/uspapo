"""Ferramentas falsas para testar a UI sem gastar Pinecone.

A `buscar_documentos` daqui fala o mesmo protocolo da de verdade
(ferramentas/busca.py), mas devolve sempre documentos canned. A LLM continua
sendo real — vem da mesma cadeia LLM_PROVIDERS do .env — para dar para testar o
streaming, os blocos de "Pensando..." e o de "Usando ferramenta..." com tokens
de verdade.

O conteúdo é genérico de propósito: serve para o modelo ter o que citar, não
para ser exato.
"""

import itertools
import os
import time

from uspapo import config
from uspapo.ferramentas import Registro

# Latência simulada da busca, para o estado "Usando ferramenta..." ficar visível.
DELAY = float(os.getenv("STUB_DELAY", "1.2"))

PARAGRAFO = (
    "A Universidade de São Paulo é organizada em unidades de ensino e pesquisa "
    "distribuídas por diversos campi no estado. Este parágrafo existe apenas para "
    "dar volume ao trecho recuperado, de modo que a resposta gerada fique longa o "
    "bastante para exercitar a rolagem da página de chat, o fade sob a navbar e o "
    "gradiente do rodapé com o campo de digitação."
)

DOCUMENTOS_FALSOS = [
    {
        "titulo": "Sistema Júpiter — matrícula em disciplinas",
        "url": "https://uspdigital.usp.br/jupiterweb/",
        "texto": (
            "O Júpiter Web é o sistema acadêmico da graduação da USP. Por ele o aluno "
            "consulta a grade curricular do curso, faz a matrícula em disciplinas nos "
            "períodos definidos pelo calendário escolar, acompanha notas e frequência e "
            "emite atestados de matrícula. O acesso usa o número USP e a senha única. "
            + PARAGRAFO
        ),
    },
    {
        "titulo": "Serviços ao aluno de graduação",
        "url": "https://www.usp.br/servicos/",
        "texto": (
            "A página de serviços reúne os canais de atendimento ao aluno: emissão de "
            "documentos, carteirinha, acesso à rede sem fio, biblioteca e suporte de TI. "
            "Cada unidade mantém também uma secretaria de graduação própria, responsável "
            "pelos trâmites que não são resolvidos pelos sistemas centrais. " + PARAGRAFO
        ),
    },
    {
        "titulo": "Pró-Reitoria de Graduação",
        "url": "https://prg.usp.br/",
        "texto": (
            "A Pró-Reitoria de Graduação coordena as políticas de ensino de graduação, "
            "os programas de bolsas e monitoria, e a transferência interna entre cursos. "
            "Editais e prazos são publicados no site da própria pró-reitoria. " + PARAGRAFO
        ),
    },
    {
        "titulo": "RUCard — restaurantes universitários",
        "url": "https://uspdigital.usp.br/rucard/",
        "texto": (
            "O RUCard é o sistema de créditos dos restaurantes universitários. O aluno "
            "adiciona créditos pelo próprio sistema e utiliza o número USP na catraca do "
            "restaurante. Os cardápios da semana e os horários de funcionamento de cada "
            "unidade também ficam disponíveis no sistema. " + PARAGRAFO
        ),
    },
    {
        "titulo": "Superintendência de Assistência Social",
        "url": "https://sas.usp.br/",
        "texto": (
            "A SAS cuida dos programas de apoio à permanência estudantil: moradia, "
            "alimentação, auxílio livro e apoio à saúde. As inscrições acontecem por "
            "edital, normalmente no início do ano letivo, e são avaliadas por análise "
            "socioeconômica. " + PARAGRAFO
        ),
    },
    {
        "titulo": "Portal da USP — estrutura e campi",
        "url": "https://www5.usp.br/",
        "texto": (
            "A USP possui campi em São Paulo, Bauru, Lorena, Piracicaba, Pirassununga, "
            "Ribeirão Preto, São Carlos e São Sebastião, além de museus e institutos "
            "especializados. Cada campus concentra unidades de ensino e pesquisa com "
            "administração própria. " + PARAGRAFO
        ),
    },
]

# Alterna a janela de documentos a cada busca, para o conjunto de fontes variar
# entre as perguntas e exercitar o bloco de fontes do frontend.
_ciclo = itertools.count()

registro = Registro()


@registro.ferramenta(
    nome="buscar_documentos",
    descricao=(
        "Busca trechos de documentos oficiais da USP (graduação, matrícula, "
        "unidades, cursos, serviços ao aluno) numa base vetorial. Use SEMPRE "
        "que a pergunta exigir uma informação factual sobre a USP."
    ),
    parametros={
        "type": "object",
        "properties": {
            "consulta": {
                "type": "string",
                "description": (
                    "A busca, em português, reformulada com os termos que "
                    "provavelmente aparecem no documento oficial."
                ),
            },
            "limite": {
                "type": "integer",
                "description": f"Quantos trechos retornar (1 a {config.TOP_K_MAX}).",
                "default": config.TOP_K_PADRAO,
            },
        },
        "required": ["consulta"],
    },
)
def buscar_documentos(
    consulta: str, limite: int = config.TOP_K_PADRAO
) -> tuple[str, list[str]]:
    """Devolve documentos falsos no mesmo formato da busca real."""
    consulta = str(consulta).strip()
    if not consulta:
        return "O campo 'consulta' é obrigatório.", []

    try:
        limite = int(limite)
    except (TypeError, ValueError):
        limite = config.TOP_K_PADRAO
    limite = max(1, min(limite, config.TOP_K_MAX))

    time.sleep(DELAY)

    inicio = next(_ciclo) % len(DOCUMENTOS_FALSOS)
    escolhidos = [
        DOCUMENTOS_FALSOS[(inicio + n) % len(DOCUMENTOS_FALSOS)] for n in range(limite)
    ]

    blocos: list[str] = []
    urls: list[str] = []

    for posicao, doc in enumerate(escolhidos, 1):
        blocos.append(f"[{posicao}] {doc['titulo']} — {doc['url']}\n{doc['texto']}")
        urls.append(doc["url"])

    return "\n\n---\n\n".join(blocos), urls


OPERACOES = {
    1: ("soma", lambda a, b: a + b),
    2: ("subtração", lambda a, b: a - b),
    3: ("multiplicação", lambda a, b: a * b),
    4: ("divisão", lambda a, b: a / b),
}


@registro.ferramenta(
    nome="calculadora",
    descricao=(
        "Calculadora básica com as quatro operações fundamentais da matemática "
        "(soma, subtração, multiplicação e divisão). "
        "Use SEMPRE que for calcular alguma coisa."
    ),
    parametros={
        "type": "object",
        "properties": {
            "operador_1": {
                "type": "integer",
                "description": "O primeiro operador da operação (esquerda)",
            },
            "operador_2": {
                "type": "integer",
                "description": "O segundo operador da operação (direita)",
            },
            "operacao": {
                "type": "integer",
                "description": (
                    "Tipo da operacao, transformada em um número inteiro "
                    "(1: soma | 2: subtração | 3: multiplicação | 4: divisão)."
                ),
            },
        },
        "required": ["operador_1", "operador_2", "operacao"],
    },
)
def calculadora(operador_1: int, operador_2: int, operacao: int) -> tuple[str, list[str]]:
    """Faz a operação da calculadora. Segunda ferramenta do stub, para testar o
    caso de o modelo escolher entre duas."""
    escolhida = OPERACOES.get(operacao)
    if escolhida is None:
        return (
            f"Operação {operacao} não existe. Use 1 (soma), 2 (subtração), "
            "3 (multiplicação) ou 4 (divisão).",
            [],
        )

    nome, calcular = escolhida
    if operacao == 4 and operador_2 == 0:
        return "Não dá para dividir por zero. Avise o aluno.", []

    time.sleep(DELAY)

    return f"Resultado da {nome}: {calcular(operador_1, operador_2)}", []
