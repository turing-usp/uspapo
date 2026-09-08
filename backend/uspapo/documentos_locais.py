"""Catálogo de títulos e leitura das páginas do corpus local."""

from __future__ import annotations

import json
import os
from functools import lru_cache

from uspapo.ferramentas import normalizar, palavras

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PASTA_PROCESSADOS = os.path.join(RAIZ, "data", "processed")
PALAVRAS_PERGUNTA = frozenset(
    "que quem quando onde como qual quais seria significa explique sobre diga fale".split()
)
TIPOS_DE_ENTIDADE = frozenset(
    "projeto programa iniciativa servico sistema plataforma portal site".split()
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
