"""Metricas baseadas exclusivamente nos registros reais do Supabase."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .logger import _obter_supabase

EVENTO_RESPOSTA_CONCLUIDA = "chat_query_completed"
TAMANHO_PAGINA = 1000


def _data_utc(valor) -> datetime | None:
    """Converte timestamp ISO para UTC; dados invalidos nunca viram atividade."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def _numero(valor) -> int:
    """Normaliza numeros trazidos pelo PostgREST sem criar estimativas."""
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _tokens(log: dict) -> tuple[int, int, int]:
    prompt = _numero(log.get("prompt_tokens"))
    completion = _numero(log.get("completion_tokens"))
    total = _numero(log.get("total_tokens"))
    # Campo do schema legado; continua sendo uma medicao, nao uma estimativa.
    if not total:
        total = _numero(log.get("tokens_gastos"))
    if not total:
        total = prompt + completion
    return prompt, completion, total


def _balde_tokens() -> dict:
    """Fabrica, nao literal.

    Um dict literal compartilhado com o ``defaultdict`` seria capturado por
    referencia e so avaliado no primeiro acesso ao balde: como o acumulado
    global e mutado antes, cada modelo novo nascia ja com o total corrente
    somado dentro dele.
    """
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _e_resposta_concluida(log: dict) -> bool:
    return str(log.get("evento") or "") == EVENTO_RESPOSTA_CONCLUIDA


def _e_erro(log: dict) -> bool:
    evento = str(log.get("evento") or "").lower()
    return "erro" in evento or "error" in evento


def _buscar_tabela(client, tabela: str) -> list[dict]:
    """Le todas as paginas; select() simples pode truncar em 1.000 linhas."""
    linhas: list[dict] = []
    inicio = 0
    while True:
        resposta = client.table(tabela).select("*").range(
            inicio, inicio + TAMANHO_PAGINA - 1
        ).execute()
        pagina = resposta.data or []
        linhas.extend(pagina)
        if len(pagina) < TAMANHO_PAGINA:
            return linhas
        inicio += TAMANHO_PAGINA


def _buscar_dados_reais_supabase():
    """Le conversas, mensagens e telemetria sem truncamento silencioso."""
    client = _obter_supabase()
    if not client:
        return [], [], []

    dados = []
    for tabela in ("conversas", "mensagens", "analytics_logs"):
        try:
            dados.append(_buscar_tabela(client, tabela))
        except Exception as erro:
            print(f"[ANALYTICS] Aviso ao buscar {tabela}: {erro}")
            dados.append([])
    return tuple(dados)


def _mapa_conversa_usuario(conversas: list[dict]) -> dict:
    return {
        conversa["id"]: conversa.get("user_id")
        for conversa in conversas
        if conversa.get("id") and conversa.get("user_id")
    }


def _adicionar_atividade(usuarios: set, uid, data, corte_24h, corte_30d):
    if not uid or not data:
        return
    if data >= corte_30d:
        usuarios["mau"].add(uid)
    if data >= corte_24h:
        usuarios["dau"].add(uid)


def _atividade_por_dia(conversas: list[dict], mensagens: list[dict], logs: list[dict]) -> dict:
    """Mapa ``dia UTC (ISO) -> {user_id}`` com quem deu sinal de vida no dia.

    Le as mesmas tres fontes que ``obter_dau_mau``, de proposito: se o card
    escalar e a serie do grafico contassem "ativo" de jeitos diferentes, os
    dois numeros discordariam na tela sem que ninguem soubesse qual esta certo.
    """
    mapa = defaultdict(set)
    conversa_usuario = _mapa_conversa_usuario(conversas)

    def marcar(uid, data):
        if uid and data:
            mapa[data.date().isoformat()].add(uid)

    for conversa in conversas:
        marcar(
            conversa.get("user_id"),
            _data_utc(conversa.get("atualizada_em") or conversa.get("criada_em")),
        )
    for mensagem in mensagens:
        marcar(
            conversa_usuario.get(mensagem.get("conversa_id")),
            _data_utc(mensagem.get("criada_em") or mensagem.get("created_at")),
        )
    for log in logs:
        marcar(log.get("user_id"), _data_utc(log.get("created_at")))
    return mapa


def obter_dau_mau(dados=None) -> dict:
    """DAU/MAU por atividade real: turnos persistidos e respostas medidas."""
    conversas, mensagens, logs = dados or _buscar_dados_reais_supabase()
    agora = datetime.now(timezone.utc)
    corte_24h = agora - timedelta(days=1)
    corte_30d = agora - timedelta(days=30)
    usuarios = {"dau": set(), "mau": set()}
    conversa_usuario = _mapa_conversa_usuario(conversas)

    for conversa in conversas:
        _adicionar_atividade(
            usuarios,
            conversa.get("user_id"),
            _data_utc(conversa.get("atualizada_em") or conversa.get("criada_em")),
            corte_24h,
            corte_30d,
        )
    for mensagem in mensagens:
        _adicionar_atividade(
            usuarios,
            conversa_usuario.get(mensagem.get("conversa_id")),
            _data_utc(mensagem.get("criada_em") or mensagem.get("created_at")),
            corte_24h,
            corte_30d,
        )
    for log in logs:
        _adicionar_atividade(
            usuarios, log.get("user_id"), _data_utc(log.get("created_at")), corte_24h, corte_30d
        )

    return {
        "dau": len(usuarios["dau"]),
        "mau": len(usuarios["mau"]),
        "razao_dau_mau": round(len(usuarios["dau"]) / max(len(usuarios["mau"]), 1), 3),
    }


def obter_consumo_tokens(dias: int = 30, dados=None) -> dict:
    """Tokens realmente reportados pelo provedor em respostas concluídas."""
    _, _, logs = dados or _buscar_dados_reais_supabase()
    agora = datetime.now(timezone.utc)
    corte_periodo = agora - timedelta(days=dias)
    inicio_hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    periodo = [
        log for log in logs
        if _e_resposta_concluida(log)
        and (data := _data_utc(log.get("created_at"))) is not None
        and data >= corte_periodo
    ]

    acumulado = _balde_tokens()
    hoje = _balde_tokens()
    por_provedor = defaultdict(lambda: {**_balde_tokens(), "chamadas": 0})
    por_modelo = defaultdict(lambda: {**_balde_tokens(), "chamadas": 0})

    for log in periodo:
        prompt, completion, total = _tokens(log)
        data = _data_utc(log.get("created_at"))
        for chave, valor in (("prompt_tokens", prompt), ("completion_tokens", completion), ("total_tokens", total)):
            acumulado[chave] += valor
            if data >= inicio_hoje:
                hoje[chave] += valor

        provedor = log.get("provedor") or "Nao informado"
        modelo = log.get("modelo") or provedor
        for agrupamento, nome in ((por_provedor, provedor), (por_modelo, modelo)):
            agrupamento[nome]["prompt_tokens"] += prompt
            agrupamento[nome]["completion_tokens"] += completion
            agrupamento[nome]["total_tokens"] += total
            agrupamento[nome]["chamadas"] += 1

    return {
        "hoje": hoje,
        "acumulado_30d": acumulado,
        "por_provedor": dict(por_provedor),
        "por_modelo": dict(por_modelo),
    }


def obter_consumo_por_usuario(top_k: int = 20, dados=None) -> list[dict]:
    """Ranking com perguntas persistidas e tokens medidos, sem estimativas."""
    conversas, mensagens, logs = dados or _buscar_dados_reais_supabase()
    conversa_usuario = _mapa_conversa_usuario(conversas)
    usuarios = defaultdict(lambda: {"total_tokens": 0, "perguntas": 0, "ultima_atividade": None})

    def atividade(uid, data):
        if not uid or not data:
            return
        atual = usuarios[uid]["ultima_atividade"]
        if not atual or data > atual:
            usuarios[uid]["ultima_atividade"] = data

    for mensagem in mensagens:
        uid = conversa_usuario.get(mensagem.get("conversa_id"))
        data = _data_utc(mensagem.get("criada_em") or mensagem.get("created_at"))
        if uid:
            usuarios[uid]["perguntas"] += 1
            atividade(uid, data)
    for log in logs:
        if not _e_resposta_concluida(log) or not log.get("user_id"):
            continue
        uid = log["user_id"]
        usuarios[uid]["total_tokens"] += _tokens(log)[2]
        atividade(uid, _data_utc(log.get("created_at")))

    ranking = [
        {**info, "user_id": uid, "ultima_atividade": info["ultima_atividade"].isoformat() if info["ultima_atividade"] else None}
        for uid, info in usuarios.items()
    ]
    ranking.sort(key=lambda item: (item["total_tokens"], item["perguntas"]), reverse=True)
    return ranking[:top_k]


def obter_desempenho_provedores(dias: int = 30, dados=None) -> dict:
    """Chamadas, falhas e latência das telemetrias dos últimos ``dias``."""
    _, _, logs = dados or _buscar_dados_reais_supabase()
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    grupos = defaultdict(lambda: {"total_chamadas": 0, "erros": 0, "latencias": []})

    for log in logs:
        data = _data_utc(log.get("created_at"))
        if not data or data < corte or not (_e_resposta_concluida(log) or _e_erro(log)):
            continue
        nome = log.get("modelo") or log.get("provedor") or "Nao informado"
        grupo = grupos[nome]
        grupo["total_chamadas"] += 1
        if _e_erro(log):
            grupo["erros"] += 1
        elif _numero(log.get("latencia_ms")) > 0:
            grupo["latencias"].append(_numero(log.get("latencia_ms")))

    return {
        nome: {
            "total_chamadas": info["total_chamadas"],
            "erros": info["erros"],
            "latencia_media_ms": round(sum(info["latencias"]) / len(info["latencias"]), 2) if info["latencias"] else 0.0,
            "taxa_erro": round(info["erros"] / info["total_chamadas"], 4),
        }
        for nome, info in grupos.items()
    }


def obter_resumo_conversas(dados=None) -> dict:
    conversas, mensagens, _ = dados or _buscar_dados_reais_supabase()
    total_conversas = len(conversas)
    total_mensagens = len(mensagens)
    return {
        "total_conversas": total_conversas,
        "total_mensagens": total_mensagens,
        "media_mensagens_por_conversa": round(total_mensagens / max(total_conversas, 1), 2),
    }


def obter_serie_temporal_diaria(dias: int = 30, janela_mau: int = 30, dados=None) -> list[dict]:
    """Serie diária: perguntas, DAU/MAU, tokens e latência medidos.

    ``usuarios_unicos`` é o DAU do dia e ``mau`` é a janela móvel de
    ``janela_mau`` dias terminando nele. Como o MAU olha para trás, o mapa de
    atividade precisa cobrir ``dias + janela_mau - 1`` dias mesmo que só os
    ``dias`` finais sejam devolvidos.
    """
    conversas, mensagens, logs = dados or _buscar_dados_reais_supabase()
    hoje = datetime.now(timezone.utc).date()
    chaves = [(hoje - timedelta(days=indice)).isoformat() for indice in range(dias - 1, -1, -1)]
    serie = {
        chave: {
            "conversas_iniciadas": 0, "perguntas": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "latencias": [],
        }
        for chave in chaves
    }
    atividade = _atividade_por_dia(conversas, mensagens, logs)

    for conversa in conversas:
        data = _data_utc(conversa.get("criada_em"))
        if data and data.date().isoformat() in serie:
            serie[data.date().isoformat()]["conversas_iniciadas"] += 1
    # A contagem de perguntas sai da telemetria, e nao de ``mensagens``: a
    # tabela de mensagens nao tem coluna de data, entao filtrar por dia ali
    # descartava todas as linhas e a serie vivia zerada.
    for log in logs:
        if not _e_resposta_concluida(log):
            continue
        data = _data_utc(log.get("created_at"))
        if not data or data.date().isoformat() not in serie:
            continue
        item = serie[data.date().isoformat()]
        item["perguntas"] += 1
        prompt, completion, total = _tokens(log)
        item["prompt_tokens"] += prompt
        item["completion_tokens"] += completion
        item["total_tokens"] += total
        latencia = _numero(log.get("latencia_ms"))
        if latencia > 0:
            item["latencias"].append(latencia)

    def mau_em(chave: str) -> int:
        fim = date.fromisoformat(chave)
        janela = set()
        for recuo in range(janela_mau):
            janela |= atividade.get((fim - timedelta(days=recuo)).isoformat(), set())
        return len(janela)

    return [
        {
            "data": chave,
            "usuarios_unicos": len(atividade.get(chave, set())),
            "mau": mau_em(chave),
            "conversas_iniciadas": item["conversas_iniciadas"],
            "perguntas": item["perguntas"],
            "prompt_tokens": item["prompt_tokens"],
            "completion_tokens": item["completion_tokens"],
            "total_tokens": item["total_tokens"],
            "latencia_media_ms": round(sum(item["latencias"]) / len(item["latencias"]), 1) if item["latencias"] else 0.0,
        }
        for chave, item in serie.items()
    ]


def obter_resumo_executivo() -> dict:
    # Todos os cards vêm da mesma leitura paginada, evitando que uma mensagem
    # criada entre consultas deixe o painel internamente inconsistente.
    dados = _buscar_dados_reais_supabase()
    usuarios = obter_dau_mau(dados)
    return {
        "dau": usuarios["dau"],
        "mau": usuarios["mau"],
        "usuarios": usuarios,
        "resumo_conversas": obter_resumo_conversas(dados),
        "tokens": obter_consumo_tokens(dias=30, dados=dados),
        "desempenho_provedores": obter_desempenho_provedores(dias=30, dados=dados),
        "top_usuarios": obter_consumo_por_usuario(top_k=5, dados=dados),
        "serie_temporal": obter_serie_temporal_diaria(dias=30, dados=dados),
    }
