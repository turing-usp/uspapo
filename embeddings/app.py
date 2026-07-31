"""Backend do USPapo — RAG sobre documentos oficiais da USP.

Fala com qualquer API compatível com o protocolo OpenAI (Groq, OpenRouter,
DeepSeek, OpenAI, Together, Ollama local...) através de uma cadeia de
provedores lida de LLM_PROVIDERS no .env: se o primário falhar, cai
automaticamente para o próximo. Veja o .env.example na raiz.

A busca vetorial no Pinecone é uma toolcall que o modelo aciona
quando a pergunta exige um fato sobre a USP.

    POST /chat  {"pergunta": "..."}                  -> {"resposta", "fontes"}
    POST /chat  {"pergunta": "...", "stream": true}  -> text/event-stream
    GET  /health

O corpo do /chat aceita ainda "historico": [{"pergunta", "resposta"}, ...] com os
turnos anteriores da conversa (o frontend guarda tudo no localStorage). O que não
couber no orçamento de tokens é descartado, do turno mais antigo para o mais novo.

Cada cliente identifica seu aparelho no header X-Device-Id e tem um limite de
perguntas por janela de tempo; estourar devolve 429.

No modo stream, cada evento é uma linha `data: {json}` com um campo "tipo":
provedor, pensando, ferramenta, texto, fontes, erro, fim.
"""

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from openai import OpenAI
from pinecone import Pinecone

# ─────────────────────────────────────────────
# 1. Configurações e chaves
# ─────────────────────────────────────────────
load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "uspapo-embeddings")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "uspapo")

EMBED_MODEL = "multilingual-e5-large"
TOP_K_PADRAO = 2
TOP_K_MAX = 3

# Quantas vezes o modelo pode usar ferramentas
MAX_RODADAS_FERRAMENTA = 2

TEMPERATURA_PADRAO = 0.1
TIMEOUT_PADRAO = 60

# Quantas perguntas cada aparelho pode fazer por janela de tempo.
LIMITES_TAXA = [
    ("minuto",     60,    int(os.getenv("RATE_LIMIT_MINUTO", "8"))),
    ("10 minutos", 600,   int(os.getenv("RATE_LIMIT_10MIN",  "30"))),
    ("hora",       3600,  int(os.getenv("RATE_LIMIT_HORA",   "100"))),
    ("dia",        86400, int(os.getenv("RATE_LIMIT_DIA",    "400"))),
]

# Teto do que vai para o modelo, não importa o tamanho da conversa no frontend.
MAX_TOKENS_CONTEXTO = int(os.getenv("MAX_TOKENS_CONTEXTO", "16000"))
# Espaço guardado para o que as ferramentas ainda vão devolver nesta pergunta.
RESERVA_FERRAMENTAS = int(os.getenv("RESERVA_FERRAMENTAS", "4000"))
# Corte grosso antes de qualquer contagem, para não estimar tokens à toa.
MAX_MENSAGENS_HISTORICO = 40
CHARS_POR_TOKEN = 3.5


def carregar_provedores() -> list[tuple[dict, OpenAI]]:
    """Lê LLM_PROVIDERS (JSON) e instancia um cliente OpenAI por provedor.

    A ordem da lista é a ordem de prioridade: o primeiro é o primário, o segundo é secundário...
    """
    bruto = (os.getenv("LLM_PROVIDERS") or "").strip()
    if not bruto:
        raise RuntimeError(
            "LLM_PROVIDERS não foi definida no .env! Copie o .env.example da raiz."
        )

    try:
        entradas = json.loads(bruto)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            f"LLM_PROVIDERS não é um JSON válido ({erro}). "
            "Ele precisa ser uma lista JSON em UMA linha só! Veja o .env.example."
        ) from erro

    if not isinstance(entradas, list) or not entradas:
        raise RuntimeError("LLM_PROVIDERS precisa ser uma lista JSON não vazia.")

    provedores: list[tuple[dict, OpenAI]] = []

    for posicao, cfg in enumerate(entradas):
        if not isinstance(cfg, dict):
            raise RuntimeError(f"LLM_PROVIDERS[{posicao}] não é um objeto JSON.")

        nome = cfg.get("nome") or f"provedor-{posicao + 1}"

        faltando = [campo for campo in ("base_url", "model") if not cfg.get(campo)]
        if faltando:
            raise RuntimeError(
                f"LLM_PROVIDERS[{posicao}] ('{nome}'): faltam os campos {faltando}."
            )

        chave = cfg.get("api_key") or os.getenv(cfg.get("api_key_env") or "", "")
        if not chave:
            print(f"   [!] provedor '{nome}' ignorado: sem chave de API configurada.")
            continue

        cliente = OpenAI(
            api_key=chave,
            base_url=cfg["base_url"],
            timeout=float(cfg.get("timeout", TIMEOUT_PADRAO)),
            max_retries=0,
        )
        provedores.append(({**cfg, "nome": nome}, cliente))

    if not provedores:
        raise RuntimeError(
            "Nenhum provedor de LLM utilizável em LLM_PROVIDERS! Todos estão sem chave."
        )

    return provedores


if not PINECONE_API_KEY:
    raise RuntimeError("A chave PINECONE_API_KEY não foi encontrada no arquivo .env!")

app = Flask(__name__)

# Liberamos o acesso tanto para o domínio oficial do Turing quanto para os seus testes locais!
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://turingusp.com",       # Para o site público do seu amigo
            "https://www.turingusp.com",   # Garantia caso alguém digite www
            "http://localhost:3000", # Para você continuar testando na sua máquina
            "https://uspapo.turingusp.com",
            "https://www.uspapo.turingusp.com"
        ],
        "allow_headers": ["Content-Type", "X-Device-Id"]
    }
})

# ─────────────────────────────────────────────
# Inicialização ÚNICA (conecta à nuvem ao subir o servidor)
# ─────────────────────────────────────────────
print("-> Iniciando motor Cloud-Native...")

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX)

PROVEDORES = carregar_provedores()
print("-> Cadeia de LLMs:", " -> ".join(cfg["nome"] for cfg, _ in PROVEDORES))
print("-> Servidor USPapo ativado e super leve! 🚀")


# ─────────────────────────────────────────────
# 2. Registro de ferramentas
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class Ferramenta:
    """Uma ferramenta que o modelo pode chamar.

    `executar` recebe os argumentos do modelo por nome e devolve
    (texto_para_o_modelo, fontes). Ferramenta que não tem fonte: um cálculo,
    por exemplo, devolve lista vazia.
    """

    nome: str
    descricao: str
    parametros: dict  # JSON Schema dos argumentos
    executar: Callable[..., tuple[str, list[str]]]


REGISTRO: dict[str, Ferramenta] = {}


def ferramenta(nome: str, descricao: str, parametros: dict):
    """Registra a função decorada como ferramenta disponível ao modelo.

    O schema fica junto da implementação: adicionar uma ferramenta nova é
    escrever uma função decorada, sem tocar em mais nada neste arquivo. Cada
    ferramenta valida os próprios argumentos e devolve texto, mas nunca levanta.
    """

    def registrar(fn):
        if nome in REGISTRO:
            raise RuntimeError(f"Ferramenta '{nome}' foi registrada duas vezes.")
        REGISTRO[nome] = Ferramenta(nome, descricao, parametros, fn)
        return fn

    return registrar


# ─────────────────────────────────────────────
# 3. As ferramentas
# ─────────────────────────────────────────────
@ferramenta(
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
                "description": f"Quantos trechos retornar (1 a {TOP_K_MAX}).",
                "default": TOP_K_PADRAO,
            },
        },
        "required": ["consulta"],
    },
)
def buscar_documentos(consulta: str, limite: int = TOP_K_PADRAO) -> tuple[str, list[str]]:
    """Vetoriza a consulta via API e busca no Pinecone.

    Devolve o texto já formatado para o modelo ler e as URLs consultadas.
    """
    consulta = str(consulta).strip()
    if not consulta:
        return "O campo 'consulta' é obrigatório.", []

    try:
        limite = int(limite)
    except (TypeError, ValueError):
        limite = TOP_K_PADRAO
    limite = max(1, min(limite, TOP_K_MAX))

    embed_result = pc.inference.embed(
        model=EMBED_MODEL,
        inputs=[f"query: {consulta}"],
        parameters={"input_type": "query"},
    )

    resultados = index.query(
        namespace=PINECONE_NAMESPACE,
        vector=embed_result[0].values,
        top_k=limite,
        include_metadata=True,
    )

    blocos: list[str] = []
    urls: list[str] = []

    for posicao, match in enumerate(resultados.matches, 1):
        meta = match.metadata or {}
        # A ingestão grava "passage: {chunk}" (convenção do e5), mas talvez não precise do remove prefix
        texto = (meta.get("text") or "").removeprefix("passage: ").strip()
        if not texto:
            continue

        titulo = meta.get("titulo") or "Sem título"
        url = meta.get("url") or "URL desconhecida"
        blocos.append(f"[{posicao}] {titulo} — {url}\n{texto}")
        urls.append(url)

    if not blocos:
        return "Nenhum documento encontrado para esta consulta.", []

    return "\n\n---\n\n".join(blocos), urls


# ─────────────────────────────────────────────
# 4. Despacho genérico das tool calls
# ─────────────────────────────────────────────
# Derivados do registro: nada aqui precisa saber quais ferramentas existem.
FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": f.nome,
            "description": f.descricao,
            "parameters": f.parametros,
        },
    }
    for f in REGISTRO.values()
]

NOMES_FERRAMENTAS = set(REGISTRO)


def rodar_ferramenta(chamada: dict, memo: dict) -> tuple[str, list[str], dict]:
    """Executa uma tool call. Nunca levanta: falha vira texto para o modelo ler."""
    try:
        args = json.loads(chamada["args"] or "{}")
    except json.JSONDecodeError:
        return "Os argumentos não são um JSON válido. Chame a ferramenta de novo.", [], {}

    if not isinstance(args, dict):
        return "Os argumentos precisam ser um objeto JSON.", [], {}

    ferr = REGISTRO.get(chamada["nome"])
    if ferr is None:
        return f"Ferramenta desconhecida: {chamada['nome']}.", [], args

    # O nome entra na chave do cache: sem ele, duas ferramentas que aceitem um
    # argumento de mesmo nome leriam o resultado cacheado uma da outra.
    chave = (ferr.nome, json.dumps(args, sort_keys=True, ensure_ascii=False))

    if chave not in memo:
        try:
            memo[chave] = ferr.executar(**args)
        except TypeError as erro:
            # Argumento a mais ou faltando: devolve para o modelo se corrigir.
            return f"Argumentos inválidos para '{ferr.nome}': {erro}", [], args
        except Exception as erro:
            print(f"[ferramenta] '{ferr.nome}' falhou: {type(erro).__name__}: {erro}")
            return "A ferramenta falhou por um erro temporário. Avise o aluno.", [], args

    resultado, fontes = memo[chave]
    return resultado, fontes, args


# ─────────────────────────────────────────────
# 5. O prompt
# ─────────────────────────────────────────────
try:
    FUSO_BR = ZoneInfo("America/Sao_Paulo")
except Exception:
    FUSO_BR = timezone(timedelta(hours=-3))

DIAS_SEMANA = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)
MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

MODELO_PROMPT_SISTEMA = """Você é o USPapo, assistente virtual desenvolvido pelo grupo Turing USP que ajuda em assuntos sobre a Universidade de São Paulo.
Responde a alunos e candidatos em português do Brasil, em Markdown, de forma direta, amigável e em linguagem descontraída.

COMO TRABALHAR:
- Hoje é {data}. Use essa data para entender perguntas relativas ("este ano", "semana que vem", "ainda dá tempo?"), mas nunca deduza prazos ou datas que as ferramentas não devolveram.
- Antes de afirmar QUALQUER fato sobre a USP, use as ferramentas disponíveis. Você não sabe nada sobre a USP por conta própria: tudo o que afirmar precisa vir do que elas devolverem.
- Se o resultado não responder à pergunta, pode chamar a ferramenta de novo com outros argumentos, antes de desistir.
- NÃO chame ferramenta para saudações, agradecimentos, despedidas ou perguntas sobre você mesmo. Nesses casos responda direto.

COMO RESPONDER:
- Baseie-se ESTRITAMENTE no que as ferramentas devolveram. Nunca complete lacunas com conhecimento próprio nem com suposições.
- Se isso não cobrir a pergunta, responda exatamente: "Desculpe, não encontrei essa informação nos meus registros." e, se fizer sentido, sugira procurar a secretaria da unidade.
- Nunca invente URLs, datas, prazos, nomes de setores ou valores. As fontes consultadas são anexadas automaticamente ao fim da resposta. Não monte você mesmo uma lista de links.
"""


def montar_prompt_sistema() -> str:
    """Preenche o prompt com a data de hoje.

    Feito por pergunta, e não no import: o servidor fica dias no ar, e uma data
    congelada na hora do deploy é pior do que data nenhuma.
    """
    agora = datetime.now(FUSO_BR)
    data = (
        f"{DIAS_SEMANA[agora.weekday()]}, {agora.day} de "
        f"{MESES[agora.month - 1]} de {agora.year}"
    )
    return MODELO_PROMPT_SISTEMA.format(data=data)


# ─────────────────────────────────────────────
# 6. Portaria: limite de uso e orçamento de contexto
# ─────────────────────────────────────────────
# Duas defesas para o mesmo problema, o custo por pergunta: o rate limit cuida
# de quantas perguntas cada um faz, o orçamento cuida do tamanho de cada uma.

_batidas: dict[str, deque[float]] = {}
_tranca = threading.Lock()

JANELA_MAXIMA = max(segundos for _, segundos, _ in LIMITES_TAXA)
FORMATO_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def identificar_cliente() -> str:
    """Chave do rate limit: o aparelho, não o IP.

    A rede da USP é toda NAT, então um laboratório inteiro sai pelo mesmo
    endereço; limitar por IP puniria a turma por causa de um usuário. O ID vem
    do navegador e é falsificável, mas o alvo aqui é uso acidental e abuso
    casual, não um atacante dedicado. Sem o header a chave cai para o IP, senão
    bastava omiti-lo para escapar do limite.
    """
    dispositivo = (request.headers.get("X-Device-Id") or "").strip()
    if FORMATO_ID.match(dispositivo):
        return f"disp:{dispositivo}"

    # O proxy do Render termina o TLS, então remote_addr é o proxy, não o aluno.
    encaminhado = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return f"ip:{encaminhado or request.remote_addr or 'desconhecido'}"


def verificar_limite(chave: str) -> tuple[str, int] | None:
    """Registra a pergunta, ou devolve (janela estourada, segundos de espera)."""
    agora = time.monotonic()

    with _tranca:
        # Sem esta limpeza o dicionário cresce para sempre, um registro por
        # aparelho que passou pelo site.
        for antiga in [
            outra for outra, marcas in _batidas.items()
            if not marcas or agora - marcas[-1] > JANELA_MAXIMA
        ]:
            del _batidas[antiga]

        marcas = _batidas.setdefault(chave, deque())
        while marcas and agora - marcas[0] > JANELA_MAXIMA:
            marcas.popleft()

        for nome, segundos, maximo in LIMITES_TAXA:
            if maximo <= 0:
                continue  # janela desligada

            dentro = [marca for marca in marcas if agora - marca <= segundos]
            if len(dentro) >= maximo:
                # A vaga abre quando a batida mais antiga da janela sair dela.
                return nome, max(int(segundos - (agora - dentro[0])) + 1, 1)

        marcas.append(agora)

    return None


def estimar_tokens(texto: str) -> int:
    """Estimativa por caracteres.

    Não há tokenizer instalado e a cadeia de provedores é heterogênea (Qwen,
    gpt-oss, DeepSeek), então nenhuma contagem exata valeria para todos. A razão
    é conservadora de propósito: sobrar contexto é bem melhor do que a API
    recusar a requisição inteira.
    """
    return int(len(texto) / CHARS_POR_TOKEN) + 1


def custo_mensagem(mensagem: dict) -> int:
    """Tokens de uma mensagem, contando o enquadramento de role e formato."""
    custo = 4 + estimar_tokens(str(mensagem.get("content") or ""))

    for chamada in mensagem.get("tool_calls") or []:
        funcao = chamada.get("function", {})
        custo += estimar_tokens(funcao.get("name", "") + funcao.get("arguments", ""))

    return custo


CUSTO_FERRAMENTAS = estimar_tokens(json.dumps(FERRAMENTAS, ensure_ascii=False))


def normalizar_historico(bruto: object) -> list[dict]:
    """Filtra os turnos anteriores que vieram do frontend.

    Item torto é descartado calado: localStorage estragado não pode impedir o
    aluno de fazer a pergunta de agora.
    """
    if not isinstance(bruto, list):
        return []

    limpo = []
    for item in bruto[-MAX_MENSAGENS_HISTORICO:]:
        if not isinstance(item, dict):
            continue

        pergunta = str(item.get("pergunta") or "").strip()
        resposta = str(item.get("resposta") or "").strip()
        if pergunta and resposta:
            limpo.append({"pergunta": pergunta, "resposta": resposta})

    return limpo


def montar_mensagens(pergunta: str, historico: list[dict]) -> tuple[list[dict], int]:
    """Monta as messages cabendo em MAX_TOKENS_CONTEXTO.

    Devolve também o índice onde o turno de agora começa: dali para a frente as
    mensagens são intocáveis (a pergunta e o par assistant/tool das ferramentas),
    e só o prefixo de histórico pode ser podado mais tarde.
    """
    sistema = {"role": "system", "content": montar_prompt_sistema()}
    atual = {"role": "user", "content": pergunta}

    disponivel = (
        MAX_TOKENS_CONTEXTO
        - custo_mensagem(sistema)
        - CUSTO_FERRAMENTAS
        - RESERVA_FERRAMENTAS
    )

    # A pergunta de agora entra sempre. Se ela sozinha estourar o orçamento, é
    # ela que encolhe: sem pergunta não há o que responder.
    if custo_mensagem(atual) > disponivel:
        atual["content"] = pergunta[:max(int(disponivel * CHARS_POR_TOKEN), 500)]

    sobra = disponivel - custo_mensagem(atual)
    anteriores: list[dict] = []

    # Do turno mais recente para o mais antigo: o fim da conversa é o que
    # importa para entender a pergunta atual.
    for turno in reversed(historico):
        par = [
            {"role": "user", "content": turno["pergunta"]},
            {"role": "assistant", "content": turno["resposta"]},
        ]
        custo = sum(custo_mensagem(mensagem) for mensagem in par)

        # Para no primeiro que não cabe em vez de continuar procurando um menor:
        # buraco no meio da conversa confunde mais do que ajuda.
        if custo > sobra:
            break

        sobra -= custo
        anteriores[:0] = par

    mensagens = [sistema] + anteriores + [atual]
    return mensagens, len(mensagens) - 1


def podar_mensagens(mensagens: list[dict], inicio_turno: int) -> int:
    """Descarta turnos antigos até o total caber de novo no orçamento.

    Roda entre as rodadas de ferramenta, quando os resultados já entraram na
    lista. Mexe só no prefixo de histórico: tirar uma mensagem 'tool' ou o
    'assistant' que a chamou deixa um tool_call_id órfão, e aí o provedor recusa
    a requisição inteira.
    """
    total = CUSTO_FERRAMENTAS + sum(custo_mensagem(mensagem) for mensagem in mensagens)

    # O índice 0 é o prompt de sistema; o histórico vai dali até inicio_turno.
    while total > MAX_TOKENS_CONTEXTO and inicio_turno > 1:
        # Os pares saem juntos, para a conversa nunca começar por uma resposta
        # sem a pergunta que a gerou.
        removidas = mensagens[1:3]
        del mensagens[1:3]
        inicio_turno -= len(removidas)
        total -= sum(custo_mensagem(mensagem) for mensagem in removidas)

    return inicio_turno


# ─────────────────────────────────────────────
# 7. Limpeza do content: raciocínio e tool calls inline
# ─────────────────────────────────────────────
# Não existe campo padronizado: a DeepSeek manda "reasoning_content", a Groq e
# a OpenRouter mandam "reasoning", e vários modelos abertos simplesmente
# cospem <think>...</think> no meio do content.
CAMPOS_RACIOCINIO = ("reasoning_content", "reasoning", "reasoning_text")

# Tags que alguns modelos cospem DENTRO do content em vez de usar os campos
# estruturados da API. Cada entrada é (abre, fecha, transmitir_ao_vivo).
# O `ao vivo` diz se o miolo pode ser repassado token a token (raciocínio) ou
# se precisa ser bufferizado até fechar para virar uma coisa só (JSON de tool
# call). Suportar um formato novo é acrescentar uma linha aqui.
TAGS_CONTEUDO = {
    "pensando": ("<think>", "</think>", True),
    "ferramenta_inline": ("<tool_call>", "</tool_call>", False),
    "ferramenta_xml": ("<function=", "</function>", False),
}

# Rótulos que viram tool call em vez de texto no chat.
ROTULOS_FERRAMENTA = {"ferramenta_inline": "", "ferramenta_xml": "<function="}


def extrair_raciocinio(delta) -> str:
    """Pesca o token de raciocínio do delta, seja lá como o provedor o chame."""
    extra = getattr(delta, "model_extra", None) or {}
    for campo in CAMPOS_RACIOCINIO:
        valor = getattr(delta, campo, None) or extra.get(campo)
        if isinstance(valor, str) and valor:
            return valor
    return ""


FUNCAO_XML = re.compile(r"<function=([^>\s]+)\s*>(.*?)(?:</function>|\Z)", re.S)
PARAMETRO_XML = re.compile(r"<parameter=([^>\s]+)\s*>(.*?)(?:</parameter>|\Z)", re.S)


def converter_por_schema(nome: str, args: dict[str, str]) -> dict:
    """Tipa os argumentos do formato XML, onde tudo chega como string.

    O JSON Schema da ferramenta diz o tipo esperado de cada campo; o que não
    converter continua string e a ferramenta decide o que fazer com ele.
    """
    ferr = REGISTRO.get(nome)
    propriedades = (ferr.parametros.get("properties") if ferr else None) or {}
    convertidos: dict[str, object] = {}

    for chave, valor in args.items():
        tipo = (propriedades.get(chave) or {}).get("type")
        try:
            if tipo == "integer":
                convertidos[chave] = int(valor)
            elif tipo == "number":
                convertidos[chave] = float(valor)
            elif tipo == "boolean":
                convertidos[chave] = valor.lower() in ("true", "1", "sim", "yes")
            elif tipo in ("object", "array"):
                convertidos[chave] = json.loads(valor)
            else:
                convertidos[chave] = valor
        except (TypeError, ValueError, json.JSONDecodeError):
            convertidos[chave] = valor

    return convertidos


def ler_tool_calls(bruto: str) -> list[tuple[str, str]]:
    """Lê um bloco de tool call inline nos formatos que os modelos usam.

    Devolve pares (nome, argumentos como string JSON), lista vazia se o bloco
    não for reconhecível. Nunca levanta: formato estranho é caso esperado aqui.
    """
    texto = bruto.strip()
    if not texto:
        return []

    # Formato Hermes (Qwen, Mistral): um objeto JSON solto, ou uma lista deles
    # quando o modelo pede duas coisas de uma vez. "name"/"arguments" é o mais
    # comum; "parameters" aparece em alguns Llama. Os argumentos podem vir como
    # objeto ou já como string JSON.
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        dados = None

    chamadas = []
    for item in dados if isinstance(dados, list) else [dados]:
        if not isinstance(item, dict):
            continue

        nome = str(item.get("name") or item.get("nome") or "")
        if not nome:
            continue

        args = item.get("arguments", item.get("parameters", {}))
        chamadas.append(
            (nome, args if isinstance(args, str) else json.dumps(args, ensure_ascii=False))
        )

    if chamadas:
        return chamadas

    # Formato XML. Pode trazer mais de uma função no mesmo bloco.
    for achado in FUNCAO_XML.finditer(texto):
        nome = achado.group(1).strip()
        crus = {
            chave.strip(): valor.strip()
            for chave, valor in PARAMETRO_XML.findall(achado.group(2))
        }
        args = converter_por_schema(nome, crus)
        chamadas.append((nome, json.dumps(args, ensure_ascii=False)))

    if not chamadas:
        print(f"[ferramenta] tool call inline em formato desconhecido, ignorada: {texto[:200]}")

    return chamadas


def recuperar_tool_call(bruto: str, pendentes: dict, anunciadas: set) -> list[dict]:
    """Converte tool calls que vieram no texto em chamadas estruturadas.

    Runtimes sem parser de tool call são endereçados aqui.
    """
    eventos = []

    for nome, args_str in ler_tool_calls(bruto):
        if not nome:
            continue

        indice = (max(pendentes) + 1) if pendentes else 0
        pendentes[indice] = {"id": "", "nome": nome, "args": args_str}

        if indice in anunciadas:
            continue
        anunciadas.add(indice)
        eventos.append(
            {"tipo": "ferramenta", "estado": "inicio", "indice": indice, "nome": nome}
        )

    return eventos


class SeparadorConteudo:
    """Separa do content as tags que o modelo emitiu inline.

    As tags chegam partidas entre chunks ("<too" + "l_call>"), então seguramos
    no buffer o pedaço do fim que ainda pode ser o começo de uma tag.
    """

    def __init__(self):
        self._buffer = ""
        self._rotulo = "texto"   # bloco em que estamos agora
        self._acumulado = ""     # miolo dos blocos que não vão ao vivo

    def _fecha_atual(self) -> str:
        return TAGS_CONTEUDO[self._rotulo][1]

    def _tamanho_tail(self) -> int:
        """Quantos chars do fim do buffer ainda podem virar uma tag."""
        if self._rotulo == "texto":
            alvos = [abre for abre, _, _ in TAGS_CONTEUDO.values()]
        else:
            alvos = [self._fecha_atual()]

        maior = 0
        for alvo in alvos:
            for tamanho in range(min(len(alvo) - 1, len(self._buffer)), 0, -1):
                if alvo.startswith(self._buffer[-tamanho:]):
                    maior = max(maior, tamanho)
                    break
        return maior

    def _emitir(self, saida: list, trecho: str, fechou: bool) -> None:
        """Entrega o miolo do bloco atual conforme a política da tag."""
        if TAGS_CONTEUDO[self._rotulo][2]:      # ao vivo
            if trecho:
                saida.append((self._rotulo, trecho))
            return

        self._acumulado += trecho
        if fechou:
            saida.append((self._rotulo, self._acumulado))
            self._acumulado = ""

    def processar(self, pedaco: str) -> list[tuple[str, str]]:
        self._buffer += pedaco
        saida: list[tuple[str, str]] = []

        while True:
            if self._rotulo == "texto":
                # abre no ponto mais próximo, qualquer que seja a tag
                achado = None
                for rotulo, (abre, _, _) in TAGS_CONTEUDO.items():
                    posicao = self._buffer.find(abre)
                    if posicao != -1 and (achado is None or posicao < achado[0]):
                        achado = (posicao, rotulo, abre)
                if achado is None:
                    break

                posicao, rotulo, abre = achado
                if posicao:
                    saida.append(("texto", self._buffer[:posicao]))
                self._buffer = self._buffer[posicao + len(abre):]
                self._rotulo = rotulo
                self._acumulado = ""
            else:
                fecha = self._fecha_atual()
                posicao = self._buffer.find(fecha)
                if posicao == -1:
                    break

                self._emitir(saida, self._buffer[:posicao], fechou=True)
                self._buffer = self._buffer[posicao + len(fecha):]
                self._rotulo = "texto"

        seguro = len(self._buffer) - self._tamanho_tail()
        if seguro > 0:
            trecho, self._buffer = self._buffer[:seguro], self._buffer[seguro:]
            if self._rotulo == "texto":
                saida.append(("texto", trecho))
            else:
                self._emitir(saida, trecho, fechou=False)

        return saida

    def finalizar(self) -> list[tuple[str, str]]:
        resto, self._buffer = self._buffer, ""

        if self._rotulo == "texto":
            return [("texto", resto)] if resto else []

        if TAGS_CONTEUDO[self._rotulo][2]:
            return [(self._rotulo, resto)] if resto else []

        # Bloco bufferizado que nunca fechou: entregamos assim mesmo, porque
        # uma tool call cortada no fim ainda costuma ter nome e argumentos
        # legíveis. Quem recebe é o parser, nunca o chat.
        incompleto, self._acumulado = self._acumulado + resto, ""
        if not incompleto.strip():
            return []

        print(f"[conteudo] bloco '{self._rotulo}' não fechou: {incompleto[:120]}")
        return [(self._rotulo, incompleto)]


# ─────────────────────────────────────────────
# 8. O núcleo: um gerador de eventos
# ─────────────────────────────────────────────
def conversar_com_provedor(
    cfg: dict,
    cliente: OpenAI,
    pergunta: str,
    historico: list[dict],
    urls_turno: set[str],
    memo: dict,
) -> Iterator[dict]:
    """Roda o laço de ferramentas num provedor. Levanta se a API falhar."""
    mensagens, inicio_turno = montar_mensagens(pergunta, historico)

    for rodada in range(MAX_RODADAS_FERRAMENTA + 1):
        # Na última rodada tiramos as ferramentas da mesa: o modelo é obrigado
        # a fechar a resposta com o que já recuperou.
        ultima = rodada == MAX_RODADAS_FERRAMENTA

        # Os resultados das ferramentas entraram na lista desde a última volta e
        # podem ter estourado o orçamento; quem paga são os turnos mais velhos.
        inicio_turno = podar_mensagens(mensagens, inicio_turno)

        parametros = {
            "model": cfg["model"],
            "messages": mensagens,
            "temperature": float(cfg.get("temperature", TEMPERATURA_PADRAO)),
            "stream": True,
        }
        if not ultima:
            parametros["tools"] = FERRAMENTAS
        if cfg.get("max_tokens"):
            parametros["max_tokens"] = int(cfg["max_tokens"])
        if cfg.get("extra_body"):
            parametros["extra_body"] = cfg["extra_body"]

        separador = SeparadorConteudo()
        pendentes: dict[int, dict] = {}
        anunciadas: set[int] = set()
        texto_final = ""

        def despachar(blocos: list[tuple[str, str]]) -> Iterator[dict]:
            """Traduz os blocos que saem do separador em eventos do stream."""
            nonlocal texto_final

            for rotulo, trecho in blocos:
                # Tool call que veio como texto vira chamada de verdade em vez
                # de aparecer crua no chat.
                if rotulo in ROTULOS_FERRAMENTA:
                    inteiro = ROTULOS_FERRAMENTA[rotulo] + trecho
                    yield from recuperar_tool_call(inteiro, pendentes, anunciadas)
                    continue

                if rotulo == "texto":
                    texto_final += trecho
                yield {"tipo": rotulo, "delta": trecho}

        for chunk in cliente.chat.completions.create(**parametros):
            if not chunk.choices:
                continue  # chunk só de usage, no fim do stream

            delta = chunk.choices[0].delta
            if delta is None:
                continue

            raciocinio = extrair_raciocinio(delta)
            if raciocinio:
                yield {"tipo": "pensando", "delta": raciocinio}

            if delta.content:
                yield from despachar(separador.processar(delta.content))

            for tc in (delta.tool_calls or []):
                slot = pendentes.setdefault(tc.index, {"id": "", "nome": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["nome"] += tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments

                # O nome chega picotado ("buscar_" + "documentos"), então
                # anunciamos assim que o acumulado casa com uma ferramenta
                # conhecida: ainda é cedo (os argumentos nem fecharam) e a UI
                # já recebe o rótulo certo para "Pesquisando nos documentos...".
                if tc.index not in anunciadas and slot["nome"] in NOMES_FERRAMENTAS:
                    anunciadas.add(tc.index)
                    yield {
                        "tipo": "ferramenta",
                        "estado": "inicio",
                        "indice": tc.index,
                        "nome": slot["nome"],
                    }

        yield from despachar(separador.finalizar())

        # Sem texto e sem ferramenta não há resposta nenhuma: costuma ser tool
        # call em formato que nenhum parser reconheceu, ou o provedor cortando
        # a geração. Levantar aqui joga para o próximo da cadeia, em vez de
        # devolver uma bolha vazia ao aluno.
        if not pendentes and not texto_final.strip():
            raise RuntimeError("o provedor terminou o stream sem texto nem tool call")

        if ultima or not pendentes:
            return

        chamadas = []
        for posicao, indice in enumerate(sorted(pendentes)):
            chamada = pendentes[indice]
            chamada["indice"] = indice  # casa com o evento "inicio"
            # Alguns provedores não mandam id; precisamos de um para casar a
            # resposta da ferramenta com a chamada.
            chamada["id"] = chamada["id"] or f"call_{rodada}_{posicao}"
            chamadas.append(chamada)

        mensagens.append({
            "role": "assistant",
            "content": texto_final,
            "tool_calls": [
                {
                    "id": chamada["id"],
                    "type": "function",
                    "function": {"name": chamada["nome"], "arguments": chamada["args"] or "{}"},
                }
                for chamada in chamadas
            ],
        })

        for chamada in chamadas:
            resultado, urls, args = rodar_ferramenta(chamada, memo)
            urls_turno.update(urls)

            yield {
                "tipo": "ferramenta",
                "estado": "fim",
                "indice": chamada["indice"],
                "nome": chamada["nome"],
                "args": args,
                "resultados": len(urls),
            }

            mensagens.append({
                "role": "tool",
                "tool_call_id": chamada["id"],
                "content": resultado,
            })


def executar_conversa(pergunta: str, historico: list[dict]) -> Iterator[dict]:
    """Percorre a cadeia de provedores até um deles responder."""
    memo: dict = {}  # buscas já feitas neste turno, para não repagar embed+query
    emitiu_texto = False
    ultimo_erro = None

    for indice, (cfg, cliente) in enumerate(PROVEDORES):
        yield {"tipo": "provedor", "nome": cfg["nome"], "indice": indice}

        # Cada tentativa tem suas próprias fontes: as do provedor que falhou
        # não correspondem à resposta que o aluno vai ler.
        urls_turno: set[str] = set()

        try:
            eventos = conversar_com_provedor(
                cfg, cliente, pergunta, historico, urls_turno, memo
            )
            for evento in eventos:
                if evento["tipo"] == "texto":
                    emitiu_texto = True
                yield evento
        except Exception as erro:
            ultimo_erro = erro
            print(f"[llm] provedor '{cfg['nome']}' falhou: {type(erro).__name__}: {erro}")

            # Depois que o cliente já começou a receber a resposta não dá para
            # reescrever o que ele viu: aí a falha é terminal.
            if emitiu_texto:
                yield {"tipo": "erro", "mensagem": "A conexão com o modelo caiu no meio da resposta."}
                yield {"tipo": "fim"}
                return
            continue

        yield {"tipo": "fontes", "urls": sorted(urls_turno)}
        yield {"tipo": "fim"}
        return

    print(f"[llm] todos os provedores falharam. Último erro: {ultimo_erro}")
    yield {"tipo": "erro", "mensagem": "Nenhum provedor de LLM está disponível no momento."}
    yield {"tipo": "fim"}


# ─────────────────────────────────────────────
# 9. Os dois adaptadores de saída
# ─────────────────────────────────────────────
def gerar_sse(eventos: Iterator[dict]) -> Iterator[str]:
    """Serializa os eventos como Server-Sent Events."""
    yield ": ok\n\n"  # abre a conexão na hora, sem esperar o primeiro token
    try:
        for evento in eventos:
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
    except Exception as erro:
        # O status HTTP 200 já foi enviado; erro aqui só pode virar evento.
        print(f"[stream] erro inesperado: {type(erro).__name__}: {erro}")
        yield f"data: {json.dumps({'tipo': 'erro', 'mensagem': 'Erro interno no servidor.'})}\n\n"
        yield f"data: {json.dumps({'tipo': 'fim'})}\n\n"


def agregar(eventos: Iterator[dict]) -> tuple[dict, int]:
    """Junta os eventos no JSON legado {"resposta", "fontes"}."""
    partes: list[str] = []
    fontes: list[str] = []
    erro = None

    for evento in eventos:
        if evento["tipo"] == "texto":
            partes.append(evento["delta"])
        elif evento["tipo"] == "fontes":
            fontes = evento["urls"]
        elif evento["tipo"] == "erro":
            erro = evento["mensagem"]

    resposta = "".join(partes).strip()
    if erro and not resposta:
        return {"erro": erro}, 500

    return {"resposta": resposta, "fontes": fontes}, 200


# ─────────────────────────────────────────────
# 10. Endpoints (a ponte com o Next.js)
# ─────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    # Antes de qualquer trabalho: quem estourou o limite não custa nada.
    excedeu = verificar_limite(identificar_cliente())
    if excedeu:
        janela, espera = excedeu
        resposta = jsonify({
            "erro": f"Você fez muitas perguntas em pouco tempo (limite por {janela}). "
                    "Espere um pouquinho e tente de novo.",
            "limite": janela,
            "retry_after": espera,
        })
        # O Retry-After vai também no corpo: sem expose_headers no CORS, o
        # navegador não consegue ler headers customizados da resposta.
        resposta.headers["Retry-After"] = str(espera)
        return resposta, 429

    dados = request.get_json(silent=True)

    if not dados or "pergunta" not in dados:
        return jsonify({"erro": "Campo 'pergunta' é obrigatório"}), 400

    pergunta = str(dados["pergunta"]).strip()

    if not pergunta:
        return jsonify({"erro": "Pergunta vazia"}), 400

    historico = normalizar_historico(dados.get("historico"))

    if dados.get("stream"):
        resposta = Response(
            stream_with_context(gerar_sse(executar_conversa(pergunta, historico))),
            mimetype="text/event-stream",
        )
        resposta.headers["Cache-Control"] = "no-cache"
        resposta.headers["Connection"] = "keep-alive"
        # Sem isto o proxy do Render bufferiza o corpo e o streaming não aparece.
        resposta.headers["X-Accel-Buffering"] = "no"
        return resposta

    try:
        corpo, status = agregar(executar_conversa(pergunta, historico))
    except Exception as erro:
        print(f"Erro ao processar pergunta: {erro}")
        return jsonify({"erro": "Erro interno ao processar a pergunta no servidor."}), 500

    return jsonify(corpo), status


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "provedores": [cfg["nome"] for cfg, _ in PROVEDORES],
        "indice": PINECONE_INDEX,
    })


if __name__ == "__main__":
    # Render atribui a porta via variável de ambiente 'PORT'
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
