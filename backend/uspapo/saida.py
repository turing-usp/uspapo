"""Os dois adaptadores de saída do fluxo de eventos.

O motor (conversa.py) só produz dicts; quem decide se isso vira um
text/event-stream ou o JSON legado de uma resposta só é este módulo.
"""

import json
from typing import Iterator


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
