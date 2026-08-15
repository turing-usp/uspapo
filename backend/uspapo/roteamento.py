"""Pré-roteamento de intenções inequívocas para fontes oficiais.

O modelo continua escolhendo ferramentas em perguntas ambíguas. Aqui entram só
casos em que deixar essa escolha ao acaso reduz precisão e gasta uma chamada de
LLM: uma linha de ônibus explícita ou um nome que casa exatamente com o título
de uma página oficial presente no corpus.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from uspapo.ferramentas import normalizar, palavras
from uspapo.locais_usp import _mencoes_com_posicao

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PASTA_PROCESSADOS = os.path.join(RAIZ, "data", "processed")
PALAVRAS_PERGUNTA = frozenset(
    "que quem quando onde como qual quais seria significa explique sobre diga fale".split()
)
TIPOS_DE_ENTIDADE = frozenset(
    "projeto programa iniciativa servico sistema plataforma portal site".split()
)
PADRAO_LINHA = re.compile(r"(?<!\w)(\d{4}|\d{3}[A-Za-z])(?:\s*-\s*\d{2})?(?!\w)")
TERMOS_ONIBUS = frozenset(
    "onibus circular circulares linha linhas ponto pontos parada paradas chega "
    "chegada horario horarios previsao previsoes busp".split()
)
TERMOS_TRAJETO = frozenset(
    "caminho chegar demora demorar distancia ir leva levar melhor onibus rota "
    "trajeto tempo transporte vou circular circulares".split()
)
PADROES_PONTO = (
    re.compile(r"\b(?:no|na|ao|a)\s+(?:ponto\s+(?:do|da|de)\s+)?(.+?)(?:\?|$)", re.I),
    re.compile(r"\b(?:ponto|parada)\s+(?:do|da|de)?\s*(.+?)(?:\?|$)", re.I),
)


def _pediu_detalhes_transporte(pergunta: str) -> bool:
    texto = normalizar(pergunta)
    return any(
        trecho in texto
        for trecho in (
            "por que",
            "porque",
            "calcul",
            "de onde vem",
            "qual a fonte",
            "quais dados",
            "explique o tempo",
            "explique esse horario",
            "mais detalhes",
        )
    )


def _termo_principal(pergunta: str) -> str:
    termos = [p for p in palavras(pergunta) if p not in PALAVRAS_PERGUNTA]
    return " ".join(termos)


@lru_cache(maxsize=1)
def catalogo_titulos() -> dict[str, list[dict[str, str]]]:
    """Índice lexical leve: não mantém os 23 MB do corpus na memória."""
    catalogo: dict[str, list[dict[str, str]]] = {}
    if not os.path.isdir(PASTA_PROCESSADOS):
        return catalogo
    for nome in sorted(os.listdir(PASTA_PROCESSADOS)):
        if not nome.endswith(".json"):
            continue
        try:
            with open(os.path.join(PASTA_PROCESSADOS, nome), encoding="utf-8") as arquivo:
                paginas = json.load(arquivo)
        except (OSError, json.JSONDecodeError):
            continue
        for pagina in paginas if isinstance(paginas, list) else []:
            titulo = str(pagina.get("titulo") or "").strip()
            url = str(pagina.get("url") or "").strip()
            chave = normalizar(titulo)
            if titulo and pagina.get("texto_limpo") and url and len(chave) >= 4:
                catalogo.setdefault(chave, []).append(
                    {"titulo": titulo, "url": url, "arquivo": nome}
                )
    return catalogo


def pagina_por_titulo(pergunta: str) -> dict[str, str] | None:
    termo = _termo_principal(pergunta)
    if not termo:
        return None
    catalogo = catalogo_titulos()
    candidatos = catalogo.get(normalizar(termo), [])
    if not candidatos:
        sem_tipo = " ".join(p for p in palavras(termo) if p not in TIPOS_DE_ENTIDADE)
        candidatos = catalogo.get(normalizar(sem_tipo), [])
    if len(candidatos) != 1:
        return None
    candidato = candidatos[0]
    try:
        with open(
            os.path.join(PASTA_PROCESSADOS, candidato["arquivo"]), encoding="utf-8"
        ) as arquivo:
            paginas = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        return None
    for pagina in paginas if isinstance(paginas, list) else []:
        if pagina.get("url") == candidato["url"]:
            return {
                "titulo": candidato["titulo"],
                "url": candidato["url"],
                "texto": str(pagina.get("texto_limpo") or "").strip(),
            }
    return None


def pedido_trajeto(pergunta: str) -> dict[str, str] | None:
    """Extrai dois locais conhecidos e seus papéis de origem/destino."""
    texto = normalizar(pergunta)
    mencoes = _mencoes_com_posicao(texto)
    tem_intencao = bool(set(palavras(texto)) & TERMOS_TRAJETO)
    if len(mencoes) >= 2 and not tem_intencao:
        entre_locais = texto[mencoes[0][1]:mencoes[1][0]]
        tem_intencao = bool(re.search(r"\b(?:ate|para|pra)\b", entre_locais))
    if not tem_intencao:
        return None
    unicas: list[tuple[int, int, str]] = []
    chaves_vistas: set[str] = set()
    for mencao in mencoes:
        if mencao[2] not in chaves_vistas:
            chaves_vistas.add(mencao[2])
            unicas.append(mencao)
    if len(unicas) < 2:
        return None

    # "como chegar lá do metrô": o local depois de "chegar lá" é a origem;
    # o prédio mencionado antes é o destino.
    chegar_la = re.search(r"\bchegar\s+la\b", texto)
    if chegar_la:
        origens = [m for m in unicas if m[0] > chegar_la.end()]
        destinos = [m for m in unicas if m[0] < chegar_la.start()]
        if origens and destinos:
            return {"origem": origens[0][2], "destino_ou_ponto": destinos[-1][2]}

    destino = None
    marcador_destino = re.compile(
        r"(?:\bate(?:\s+[ao])?|\b(?:para|pra)(?:\s+[ao])?|"
        r"\b(?:chegar|chego|ir|vou)\s+(?:ate\s+|para\s+|pra\s+)?"
        r"(?:ao|a|no|na))\s*$"
    )
    for mencao in unicas:
        antes = texto[max(0, mencao[0] - 45):mencao[0]]
        if marcador_destino.search(antes):
            destino = mencao
    destino = destino or unicas[-1]
    origem = next((m for m in unicas if m[2] != destino[2]), None)
    if not origem:
        return None
    return {"origem": origem[2], "destino_ou_ponto": destino[2]}


def pedido_circular(pergunta: str) -> dict[str, str] | None:
    match = PADRAO_LINHA.search(pergunta)
    termos = set(palavras(pergunta))
    if not (termos & TERMOS_ONIBUS or "chega" in termos):
        return None
    ponto = ""
    for padrao in PADROES_PONTO:
        achado = padrao.search(pergunta)
        if achado:
            ponto = achado.group(1).strip(" .?!")
            break
    if not match and not ponto:
        return None
    return {
        "linha": match.group(1) if match else "",
        "destino_ou_ponto": ponto,
    }


def preconsultar(
    registro, pergunta: str
) -> tuple[str, list[str], str, dict | None] | None:
    trajeto = pedido_trajeto(pergunta)
    if trajeto and "consultar_circulares" in registro.nomes:
        try:
            resposta = registro.executar_direto(
                "consultar_circulares",
                linha="",
                detalhes=_pediu_detalhes_transporte(pergunta),
                _pergunta=pergunta,
                **trajeto,
            )
            texto, fontes = resposta
        except Exception as erro:
            print(f"[roteamento] pré-consulta de trajeto falhou: {type(erro).__name__}: {erro}")
            return None
        print(
            f"[roteamento] trajeto: origem={trajeto['origem']!r}, "
            f"destino={trajeto['destino_ou_ponto']!r}"
        )
        return (
            texto,
            fontes,
            "consultar_circulares",
            getattr(resposta, "dados_publicos", None),
        )

    circular = pedido_circular(pergunta)
    if circular and "consultar_circulares" in registro.nomes:
        try:
            resposta = registro.executar_direto(
                "consultar_circulares",
                detalhes=_pediu_detalhes_transporte(pergunta),
                _pergunta=pergunta,
                **circular,
            )
            texto, fontes = resposta
        except Exception as erro:
            print(f"[roteamento] pré-consulta de circular falhou: {type(erro).__name__}: {erro}")
            return None
        print(f"[roteamento] consultar_circulares: linha={circular['linha']}, ponto={circular['destino_ou_ponto']!r}")
        return (
            texto,
            fontes,
            "consultar_circulares",
            getattr(resposta, "dados_publicos", None),
        )

    pagina = pagina_por_titulo(pergunta)
    if pagina:
        # A introdução costuma definir a entidade; limitar aqui evita entregar ao
        # modelo páginas enormes só porque o título casou exatamente.
        texto = (
            f"Fonte oficial encontrada por correspondência exata de título:\n\n"
            f"### {pagina['titulo']}\n{pagina['texto'][:4500]}"
        )
        print(f"[roteamento] título oficial exato: {pagina['titulo']!r}")
        return texto, [pagina["url"]], "buscar_documentos", None
    return None
