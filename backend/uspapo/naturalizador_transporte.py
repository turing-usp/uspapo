"""Naturaliza respostas factuais de transporte sem entregar o planejamento ao LLM.

O planejador continua sendo a autoridade sobre linha, sentido, pontos e tempos.
Este módulo recebe somente uma visão pública desses fatos e um texto de fallback
já seguro. O modelo atua como revisor de estilo; sua saída é bufferizada e só é
usada se passar por validações determinísticas. Qualquer falha devolve o fallback.

A chamada é deliberadamente separada do laço de ferramentas de ``conversa.py``:
não há streaming nem ``tools``. Isso permite rejeitar uma resposta inteira antes
que qualquer trecho potencialmente incorreto chegue ao aluno.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


MODELOS_ESTRITOS = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
)
MAX_PALAVRAS_PADRAO = 90
MAX_TOKENS_SAIDA = 400
TIMEOUT_TOTAL_RENDERIZACAO_S = 8.0
TIMEOUT_POR_TENTATIVA_S = 4.0

_ESQUEMA_RESPOSTA = {
    "type": "json_schema",
    "json_schema": {
        "name": "resposta_transporte_natural",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"resposta": {"type": "string"}},
            "required": ["resposta"],
            "additionalProperties": False,
        },
    },
}

_PROMPT_SISTEMA = """Você é somente o revisor de texto da resposta de transporte do USPapo.
O backend já calculou todos os fatos. Você NÃO planeja a rota e NÃO corrige, completa ou infere dados.

Devolva um objeto JSON com apenas o campo `resposta`.

Regras obrigatórias:
- Responda em português do Brasil, como um chatbot natural, em no máximo {max_palavras} palavras.
- Responda diretamente ao que o aluno perguntou, em 2 a 4 frases curtas quando possível.
- Use somente fatos presentes em FATOS_PÚBLICOS ou na RESPOSTA_FACTUAL_SEGURA.
- Preserve números em algarismos e preserve exatamente linhas, horários, sentidos e nomes de locais.
- Não atribua, aumente, diminua ou interprete níveis de confiança/origem das chegadas; eles são fatos calculados pelo backend.
- Não acrescente números, linhas, horários, locais, pontos, sentidos ou estimativas.
- Se citar o tempo total e o tempo dentro do ônibus, deixe claro que o total também inclui espera e caminhada.
- Não mencione GTFS, stop_id, exact_times, payload, algoritmo, ranking ou recorte de dados.
- Não liste alternativas, detalhes técnicos ou fontes, salvo se a pergunta pedir isso explicitamente.
- As fontes são exibidas separadamente pela interface; não escreva links.
- Se não conseguir cumprir todas as regras, copie a RESPOSTA_FACTUAL_SEGURA sem alterações.
"""

# Números de linhas (inclusive 177H-10 e N842-11) e relógios são validados como
# unidades completas antes da checagem escalar. Assim, trocar só o sufixo de uma
# linha ou um minuto de um horário também invalida a resposta.
_PADRAO_LINHA = re.compile(
    r"(?<![\w])(?:[A-Za-z]?\d{3,4}[A-Za-z]?)-\d{2}(?![\w])"
)
_PADRAO_RELOGIO = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)")
_PADRAO_NUMERO = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?%?(?![\w])")
_PADRAO_PALAVRA = re.compile(r"[\wÀ-ÖØ-öø-ÿ]+(?:[-'][\wÀ-ÖØ-öø-ÿ]+)*", re.UNICODE)
_PADRAO_CAPITALIZADA = re.compile(
    r"(?<![\wÀ-ÖØ-öø-ÿ])([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][\wÀ-ÖØ-öø-ÿ-]*)",
    re.UNICODE,
)

_NUMEROS_POR_EXTENSO = {
    "zero": "0",
    "dois": "2",
    "duas": "2",
    "tres": "3",
    "quatro": "4",
    "cinco": "5",
    "seis": "6",
    "sete": "7",
    "oito": "8",
    "nove": "9",
    "dez": "10",
    "onze": "11",
    "doze": "12",
    "treze": "13",
    "catorze": "14",
    "quatorze": "14",
    "quinze": "15",
    "dezesseis": "16",
    "dezessete": "17",
    "dezoito": "18",
    "dezenove": "19",
    "vinte": "20",
    "trinta": "30",
    "quarenta": "40",
    "cinquenta": "50",
    "sessenta": "60",
}

# Palavras que podem aparecer com maiúscula por começarem uma frase. Qualquer
# outra palavra capitalizada precisa existir nos fatos/fallback, o que pesca
# invenções como "Terminal Pinheiros" sem exigir uma lista manual de lugares.
_CAPITALIZADAS_DE_ESTILO = {
    "a", "agora", "ainda", "ao", "aproximadamente", "as", "assim", "ate",
    "boa", "caminhe", "caso", "cerca", "como", "conte", "da", "de", "do",
    "e", "embarque", "em", "enquanto", "essa", "esse", "esta", "este",
    "fica", "ha", "ir", "ja", "leva", "mais", "melhor", "na", "nao",
    "neste", "no", "o", "os", "para", "pegue", "pelo", "por", "proximo",
    "quando", "saindo", "se", "sem", "so", "sao", "tem", "total", "uma",
    "uns", "va", "voce",
}

_TERMOS_TECNICOS_PROIBIDOS = (
    "gtfs",
    "stop_id",
    "exact_times",
    "payload",
    "algoritmo de ranking",
    "recorte gtfs",
    "recorte de dados",
)


@dataclass(frozen=True)
class ResultadoNaturalizacaoTransporte:
    """Resultado pronto para integrar ao stream e à telemetria da conversa."""

    texto: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provedor: str = "backend-deterministico"
    modelo: str = "naturalizador-fallback"
    usou_llm: bool = False
    motivo_fallback: str | None = None
    tentativas: tuple[dict[str, Any], ...] = ()

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _normalizar(texto: Any) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto).strip().lower())
    return "".join(c for c in bruto if not unicodedata.combining(c))


def _fallback_de(public_view: Mapping[str, Any], fallback: str | None) -> str:
    if fallback and fallback.strip():
        return fallback.strip()
    for chave in ("resposta_factual", "fallback"):
        valor = public_view.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return "Desculpe, não consegui apresentar essa rota agora. Tente novamente em breve."


def _serializar_public_view(public_view: Mapping[str, Any]) -> str:
    """Serializa só a visão que o chamador declarou pública, com limite defensivo."""
    bruto = json.dumps(public_view, ensure_ascii=False, sort_keys=True, default=str)
    # Uma resposta de transporte normal é muito menor. O teto impede que um bug
    # entregue ao renderer um catálogo/itinerário inteiro e consuma contexto à toa.
    return bruto[:12_000]


def _fontes_allowlist(public_view: Mapping[str, Any], fallback: str) -> str:
    return _serializar_public_view(public_view) + "\n" + fallback


def _canon_numero(valor: str) -> str:
    valor = valor.rstrip("%").replace(",", ".")
    try:
        numero = float(valor)
    except ValueError:
        return valor
    if numero.is_integer():
        return str(int(numero))
    return (f"{numero:.8f}").rstrip("0").rstrip(".")


def _tokens_numericos(texto: str) -> set[str]:
    return {_canon_numero(item) for item in _PADRAO_NUMERO.findall(texto)}


def _validar_numeros(texto: str, fonte: str) -> str | None:
    linhas_permitidas = {_normalizar(x) for x in _PADRAO_LINHA.findall(fonte)}
    for linha in _PADRAO_LINHA.findall(texto):
        if _normalizar(linha) not in linhas_permitidas:
            return f"linha não permitida: {linha}"

    horarios_permitidos = set(_PADRAO_RELOGIO.findall(fonte))
    for horario in _PADRAO_RELOGIO.findall(texto):
        if horario not in horarios_permitidos:
            return f"horário não permitido: {horario}"

    numeros_permitidos = _tokens_numericos(fonte)
    for numero in _tokens_numericos(texto):
        if numero not in numeros_permitidos:
            return f"número não permitido: {numero}"

    # O prompt pede algarismos. Ainda assim, aceitar "dois" quando 2 é um fato
    # é seguro; escrever qualquer quantidade nova por extenso não é.
    for palavra in _PADRAO_PALAVRA.findall(_normalizar(texto)):
        numero = _NUMEROS_POR_EXTENSO.get(palavra)
        if numero is not None and numero not in numeros_permitidos:
            return f"número por extenso não permitido: {palavra}"
    return None


def _validar_entidades(texto: str, fonte: str) -> str | None:
    palavras_permitidas = set(_PADRAO_PALAVRA.findall(_normalizar(fonte)))
    for palavra in _PADRAO_CAPITALIZADA.findall(texto):
        normalizada = _normalizar(palavra)
        if (
            len(normalizada) <= 1
            or normalizada in _CAPITALIZADAS_DE_ESTILO
            or normalizada in palavras_permitidas
        ):
            continue
        return f"nome/local não permitido: {palavra}"
    return None


def _validar_fatos_obrigatorios(
    texto: str, public_view: Mapping[str, Any]
) -> str | None:
    """Impede uma paráfrase correta, porém inútil, de omitir a resposta."""
    normalizado = _normalizar(texto)
    for fato in public_view.get("fatos_obrigatorios", ()) or ():
        esperado = _normalizar(fato)
        if esperado and esperado not in normalizado:
            return f"fato obrigatório ausente: {fato}"

    numeros = _tokens_numericos(texto)
    for numero in public_view.get("numeros_obrigatorios", ()) or ():
        esperado = _canon_numero(str(numero))
        if esperado not in numeros:
            return f"número obrigatório ausente: {numero}"

    horarios = set(_PADRAO_RELOGIO.findall(texto))
    for horario in public_view.get("horarios_obrigatorios", ()) or ():
        esperado = str(horario)
        if esperado not in horarios:
            return f"horário obrigatório ausente: {horario}"

    for frase in public_view.get("frases_obrigatorias", ()) or ():
        esperado = _normalizar(frase)
        if esperado and esperado not in normalizado:
            return f"estado operacional ausente: {frase}"
    return None


def validar_resposta_transporte(
    texto: str,
    public_view: Mapping[str, Any],
    fallback: str,
    *,
    max_palavras: int = MAX_PALAVRAS_PADRAO,
) -> tuple[bool, str | None]:
    """Confere limites de produto e se todos os fatos vieram da allowlist."""
    resposta = str(texto or "").strip()
    if not resposta:
        return False, "resposta vazia"
    if len(_PADRAO_PALAVRA.findall(resposta)) > max_palavras:
        return False, "resposta longa demais"
    if "http://" in resposta.lower() or "https://" in resposta.lower():
        return False, "link não permitido"

    normalizada = _normalizar(resposta)
    horario_indisponivel = (
        public_view.get("status_operacao") == "horario_indisponivel"
        or public_view.get("status_programacao") == "horario_indisponivel"
    )
    if horario_indisponivel and (
        _PADRAO_RELOGIO.search(resposta)
        or re.search(r"\b(minuto|minutos|hora|horas)\b", normalizada)
    ):
        return False, "estimativa presente apesar de horário indisponível"
    for termo in _TERMOS_TECNICOS_PROIBIDOS:
        if _normalizar(termo) in normalizada:
            return False, f"termo técnico não permitido: {termo}"
    if re.search(
        r"\b(?:alta|media|baixa)\s+confianca\b|\b(?:high|medium|low|scheduled)\b",
        normalizada,
    ):
        return False, "classificação de confiança não é escolhida pelo naturalizador"

    fonte = _fontes_allowlist(public_view, fallback)
    motivo = _validar_numeros(resposta, fonte)
    if motivo:
        return False, motivo
    motivo = _validar_entidades(resposta, fonte)
    if motivo:
        return False, motivo
    motivo = _validar_fatos_obrigatorios(resposta, public_view)
    if motivo:
        return False, motivo
    return True, None


def _provedores_renderer(provedores: Sequence[Any]) -> list[Any]:
    """Preserva todas as credenciais, priorizando todos os 120B e depois 20B.

    Duas entradas podem apontar para o mesmo modelo com chaves diferentes. Elas
    são instâncias de fallback distintas e não podem ser colapsadas pelo nome ou
    pelo ``model``.
    """
    return [
        provedor
        for modelo in MODELOS_ESTRITOS
        for provedor in provedores
        if str(getattr(provedor, "cfg", {}).get("model", "")) == modelo
    ]


def _conteudo_resposta(completion: Any) -> str:
    escolhas = getattr(completion, "choices", None) or []
    if not escolhas:
        raise ValueError("renderer não devolveu choices")
    mensagem = getattr(escolhas[0], "message", None)
    conteudo = getattr(mensagem, "content", None)
    if not isinstance(conteudo, str) or not conteudo.strip():
        raise ValueError("renderer não devolveu conteúdo")
    objeto = json.loads(conteudo)
    if not isinstance(objeto, dict) or set(objeto) != {"resposta"}:
        raise ValueError("renderer devolveu objeto fora do schema")
    resposta = objeto.get("resposta")
    if not isinstance(resposta, str):
        raise ValueError("campo resposta não é texto")
    return resposta.strip()


def _uso(completion: Any) -> tuple[int, int]:
    uso = getattr(completion, "usage", None)
    return (
        int(getattr(uso, "prompt_tokens", 0) or 0),
        int(getattr(uso, "completion_tokens", 0) or 0),
    )


def naturalizar_resposta_transporte(
    provedores: Sequence[Any],
    pergunta: str,
    public_view: Mapping[str, Any] | None,
    fallback: str | None = None,
    *,
    max_palavras: int = MAX_PALAVRAS_PADRAO,
) -> ResultadoNaturalizacaoTransporte:
    """Naturaliza uma resposta e volta silenciosamente ao fallback se necessário.

    ``public_view`` deve conter somente fatos que podem aparecer para o aluno.
    Pode incluir ``resposta_factual`` ou ``fallback``; o argumento ``fallback``
    explícito tem precedência. Provedores que não sejam GPT-OSS 120B/20B são
    ignorados porque não oferecem o modo estrito usado por este contrato.
    """
    fatos = dict(public_view or {})
    texto_fallback = _fallback_de(fatos, fallback)
    elegiveis = _provedores_renderer(provedores)
    if not elegiveis:
        return ResultadoNaturalizacaoTransporte(
            texto=texto_fallback,
            motivo_fallback="sem provedor com saída estruturada estrita",
        )

    prompt_tokens = 0
    completion_tokens = 0
    ultimo_provedor = "backend-deterministico"
    ultimo_modelo = "naturalizador-fallback"
    ultimo_motivo = "renderer indisponível"
    tentativas: list[dict[str, Any]] = []

    entrada = {
        "pergunta_do_aluno": str(pergunta or "").strip(),
        "fatos_publicos": fatos,
        "resposta_factual_segura": texto_fallback,
    }
    mensagem_usuario = json.dumps(entrada, ensure_ascii=False, default=str)
    sistema = _PROMPT_SISTEMA.format(max_palavras=max_palavras)
    inicio = time.monotonic()

    for provedor in elegiveis:
        restante_s = TIMEOUT_TOTAL_RENDERIZACAO_S - (time.monotonic() - inicio)
        if restante_s <= 0:
            ultimo_motivo = "tempo total do renderer excedido"
            break
        cfg = getattr(provedor, "cfg", {})
        ultimo_provedor = str(getattr(provedor, "nome", "groq"))
        ultimo_modelo = str(cfg.get("model", ""))
        prompt_usados = 0
        completion_usados = 0
        try:
            completion = provedor.cliente.chat.completions.create(
                model=ultimo_modelo,
                messages=[
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": mensagem_usuario},
                ],
                temperature=float(cfg.get("temperature_renderer", 0.1)),
                max_completion_tokens=MAX_TOKENS_SAIDA,
                reasoning_effort="low",
                response_format=_ESQUEMA_RESPOSTA,
                stream=False,
                timeout=min(TIMEOUT_POR_TENTATIVA_S, restante_s),
            )
            prompt_usados, completion_usados = _uso(completion)
            prompt_tokens += prompt_usados
            completion_tokens += completion_usados
            resposta = _conteudo_resposta(completion)
            valida, motivo = validar_resposta_transporte(
                resposta,
                fatos,
                texto_fallback,
                max_palavras=max_palavras,
            )
            if not valida:
                ultimo_motivo = motivo or "resposta não passou na validação"
                tentativas.append({
                    "provedor": ultimo_provedor,
                    "modelo": ultimo_modelo,
                    "prompt_tokens": prompt_usados,
                    "completion_tokens": completion_usados,
                    "resultado": "rejeitada",
                    "motivo": ultimo_motivo,
                })
                continue
            tentativas.append({
                "provedor": ultimo_provedor,
                "modelo": ultimo_modelo,
                "prompt_tokens": prompt_usados,
                "completion_tokens": completion_usados,
                "resultado": "aceita",
            })
            return ResultadoNaturalizacaoTransporte(
                texto=resposta,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                provedor=ultimo_provedor,
                modelo=ultimo_modelo,
                usou_llm=True,
                tentativas=tuple(tentativas),
            )
        except Exception as erro:
            # Não inclua a mensagem da exceção: erros de SDK/proxy não devem
            # correr o risco de carregar cabeçalhos ou configuração sensível.
            ultimo_motivo = type(erro).__name__
            tentativas.append({
                "provedor": ultimo_provedor,
                "modelo": ultimo_modelo,
                "prompt_tokens": prompt_usados,
                "completion_tokens": completion_usados,
                "resultado": "erro",
                "motivo": ultimo_motivo,
            })

    return ResultadoNaturalizacaoTransporte(
        texto=texto_fallback,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        provedor=ultimo_provedor,
        modelo=ultimo_modelo,
        usou_llm=False,
        motivo_fallback=ultimo_motivo,
        tentativas=tuple(tentativas),
    )


__all__ = [
    "ResultadoNaturalizacaoTransporte",
    "naturalizar_resposta_transporte",
    "validar_resposta_transporte",
]
