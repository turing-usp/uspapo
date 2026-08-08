from datetime import datetime, timedelta, timezone
from collections import defaultdict
from .logger import _obter_supabase

def _buscar_logs(dias: int = 30) -> list[dict]:
    """Busca os logs do Supabase dos últimos N dias."""
    client = _obter_supabase()
    if not client:
        return []
    try:
        data_corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        res = client.table("analytics_logs") \
            .select("*") \
            .gte("created_at", data_corte) \
            .execute()
        return res.data or []
    except Exception as e:
        print(f"[ERRO ANALYTICS METRICAS] Falha ao buscar logs: {e}")
        return []

def obter_dau_mau() -> dict:
    """Calcula DAU (últimas 24h) e MAU (últimos 30 dias)."""
    logs = _buscar_logs(dias=30)
    agora = datetime.now(timezone.utc)
    corte_24h = agora - timedelta(days=1)

    usuarios_mau = set()
    usuarios_dau = set()

    for log in logs:
        uid = log.get("user_id") or log.get("session_id")
        if not uid:
            continue
        
        usuarios_mau.add(uid)

        dt_str = log.get("created_at")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt >= corte_24h:
                    usuarios_dau.add(uid)
            except Exception:
                pass

    return {
        "dau": len(usuarios_dau),
        "mau": len(usuarios_mau),
        "razao_dau_mau": round(len(usuarios_dau) / max(len(usuarios_mau), 1), 3)
    }

def obter_consumo_tokens(dias: int = 30) -> dict:
    """Calcula o consumo de tokens acumulado e detalhado por provedor/modelo."""
    logs = _buscar_logs(dias=dias)
    agora = datetime.now(timezone.utc)
    corte_hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    prompt_total, completion_total, total_geral = 0, 0, 0
    prompt_hoje, completion_hoje, total_hoje = 0, 0, 0

    por_provedor = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "chamadas": 0})
    por_modelo = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "chamadas": 0})

    for log in logs:
        p_tok = log.get("prompt_tokens") or 0
        c_tok = log.get("completion_tokens") or 0
        t_tok = log.get("total_tokens") or (p_tok + c_tok)
        prov = log.get("provedor") or "Outro"
        mod = log.get("modelo") or "Desconhecido"

        prompt_total += p_tok
        completion_total += c_tok
        total_geral += t_tok

        por_provedor[prov]["prompt_tokens"] += p_tok
        por_provedor[prov]["completion_tokens"] += c_tok
        por_provedor[prov]["total_tokens"] += t_tok
        por_provedor[prov]["chamadas"] += 1

        por_modelo[mod]["prompt_tokens"] += p_tok
        por_modelo[mod]["completion_tokens"] += c_tok
        por_modelo[mod]["total_tokens"] += t_tok
        por_modelo[mod]["chamadas"] += 1

        dt_str = log.get("created_at")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt >= corte_hoje:
                    prompt_hoje += p_tok
                    completion_hoje += c_tok
                    total_hoje += t_tok
            except Exception:
                pass

    return {
        "hoje": {
            "prompt_tokens": prompt_hoje,
            "completion_tokens": completion_hoje,
            "total_tokens": total_hoje
        },
        "acumulado_30d": {
            "prompt_tokens": prompt_total,
            "completion_tokens": completion_total,
            "total_tokens": total_geral
        },
        "por_provedor": dict(por_provedor),
        "por_modelo": dict(por_modelo)
    }

def obter_consumo_por_usuario(top_k: int = 20) -> list[dict]:
    """Retorna o ranking dos usuários que mais consumiram tokens nos últimos 30 dias."""
    logs = _buscar_logs(dias=30)
    usuarios = defaultdict(lambda: {"total_tokens": 0, "perguntas": 0, "ultima_atividade": None})

    for log in logs:
        uid = log.get("user_id") or log.get("session_id")
        if not uid:
            continue
        t_tok = log.get("total_tokens") or 0
        usuarios[uid]["total_tokens"] += t_tok
        usuarios[uid]["perguntas"] += 1
        
        dt_str = log.get("created_at")
        if dt_str and (not usuarios[uid]["ultima_atividade"] or dt_str > usuarios[uid]["ultima_atividade"]):
            usuarios[uid]["ultima_atividade"] = dt_str

    ranking = [
        {
            "user_id": uid,
            "total_tokens": dados["total_tokens"],
            "perguntas": dados["perguntas"],
            "ultima_atividade": dados["ultima_atividade"]
        }
        for uid, dados in usuarios.items()
    ]
    ranking.sort(key=lambda x: x["total_tokens"], reverse=True)
    return ranking[:top_k]

def obter_desempenho_provedores() -> dict:
    """Retorna estatísticas de latência média e taxa de erro por provedor."""
    logs = _buscar_logs(dias=30)
    estats = defaultdict(lambda: {"latencias": [], "erros": 0, "total_chamadas": 0})

    for log in logs:
        prov = log.get("provedor") or "Outro"
        lat = log.get("latencia_ms") or 0
        evento = log.get("evento") or ""

        estats[prov]["total_chamadas"] += 1
        if lat > 0:
            estats[prov]["latencias"].append(lat)
        if "erro" in evento or "sys_" in evento:
            estats[prov]["erros"] += 1

    resultado = {}
    for prov, dados in estats.items():
        lats = dados["latencias"]
        mediana_lat = sum(lats) / len(lats) if lats else 0
        total_c = max(dados["total_chamadas"], 1)
        resultado[prov] = {
            "total_chamadas": dados["total_chamadas"],
            "latencia_media_ms": round(mediana_lat, 1),
            "erros": dados["erros"],
            "taxa_erro": round((dados["erros"] / total_c) * 100, 2)
        }
    return resultado

def obter_serie_temporal_diaria(dias: int = 30) -> list[dict]:
    """Gera dados de série temporal por dia (YYYY-MM-DD) prontos para gráficos do frontend."""
    logs = _buscar_logs(dias=dias)
    dias_map = defaultdict(lambda: {
        "usuarios": set(),
        "perguntas": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latencias": []
    })

    for log in logs:
        dt_str = log.get("created_at")
        if not dt_str:
            continue
        try:
            dia_key = dt_str[:10]  # YYYY-MM-DD
        except Exception:
            continue

        uid = log.get("user_id") or log.get("session_id")
        if uid:
            dias_map[dia_key]["usuarios"].add(uid)

        p_tok = log.get("prompt_tokens") or 0
        c_tok = log.get("completion_tokens") or 0
        t_tok = log.get("total_tokens") or (p_tok + c_tok)
        lat = log.get("latencia_ms") or 0

        dias_map[dia_key]["perguntas"] += 1
        dias_map[dia_key]["prompt_tokens"] += p_tok
        dias_map[dia_key]["completion_tokens"] += c_tok
        dias_map[dia_key]["total_tokens"] += t_tok
        if lat > 0:
            dias_map[dia_key]["latencias"].append(lat)

    serie = []
    for dia_key in sorted(dias_map.keys()):
        d = dias_map[dia_key]
        lats = d["latencias"]
        lat_media = round(sum(lats) / len(lats), 1) if lats else 0
        serie.append({
            "data": dia_key,
            "usuarios_unicos": len(d["usuarios"]),
            "perguntas": d["perguntas"],
            "prompt_tokens": d["prompt_tokens"],
            "completion_tokens": d["completion_tokens"],
            "total_tokens": d["total_tokens"],
            "latencia_media_ms": lat_media
        })
    return serie

def obter_resumo_executivo() -> dict:
    """Gera um resumo consolidado de telemetria pronto para exibição no dashboard."""
    dau_mau = obter_dau_mau()
    tokens = obter_consumo_tokens(dias=30)
    desempenho = obter_desempenho_provedores()
    top_usuarios = obter_consumo_por_usuario(top_k=5)
    serie_temporal = obter_serie_temporal_diaria(dias=30)

    return {
        "usuarios": dau_mau,
        "tokens": tokens,
        "desempenho_provedores": desempenho,
        "top_usuarios": top_usuarios,
        "serie_temporal": serie_temporal
    }
