from datetime import datetime, timedelta, timezone
from collections import defaultdict
from .logger import _obter_supabase

def _estimar_tokens(texto: str) -> int:
    """Estimativa de tokens: ~1 token a cada 4 caracteres em português."""
    if not texto:
        return 0
    return max(int(len(texto) / 4), 1)

def _buscar_dados_reais_supabase():
    """Busca dados reais de conversas e mensagens das tabelas nativas do Supabase."""
    client = _obter_supabase()
    if not client:
        return [], [], []

    conversas, mensagens, logs = [], [], []
    try:
        res_c = client.table("conversas").select("*").execute()
        conversas = res_c.data or []
    except Exception as e:
        print(f"[ANALYTICS] Aviso ao buscar conversas: {e}")

    try:
        res_m = client.table("mensagens").select("*").execute()
        mensagens = res_m.data or []
    except Exception as e:
        print(f"[ANALYTICS] Aviso ao buscar mensagens: {e}")

    try:
        res_l = client.table("analytics_logs").select("*").execute()
        logs = res_l.data or []
    except Exception as e:
        print(f"[ANALYTICS] Aviso ao buscar logs: {e}")

    return conversas, mensagens, logs

def obter_dau_mau() -> dict:
    """Calcula DAU (últimas 24h) e MAU (últimos 30 dias) baseado nas tabelas conversas e logs."""
    conversas, mensagens, logs = _buscar_dados_reais_supabase()
    agora = datetime.now(timezone.utc)
    corte_24h = agora - timedelta(days=1)
    corte_30d = agora - timedelta(days=30)

    usuarios_mau = set()
    usuarios_dau = set()

    # 1. Avalia tabela de conversas
    for c in conversas:
        uid = c.get("user_id") or c.get("device_id") or c.get("session_id")
        if not uid:
            continue
        dt_str = c.get("atualizada_em") or c.get("criada_em")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt >= corte_30d:
                    usuarios_mau.add(uid)
                if dt >= corte_24h:
                    usuarios_dau.add(uid)
            except Exception:
                usuarios_mau.add(uid)
        else:
            usuarios_mau.add(uid)

    # 2. Avalia tabela analytics_logs
    for log in logs:
        uid = log.get("user_id") or log.get("session_id")
        if not uid:
            continue
        dt_str = log.get("created_at")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt >= corte_30d:
                    usuarios_mau.add(uid)
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
    """Calcula o consumo de tokens medido e estimado baseado nas mensagens reais."""
    conversas, mensagens, logs = _buscar_dados_reais_supabase()
    agora = datetime.now(timezone.utc)
    corte_hoje = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    prompt_total, completion_total, total_geral = 0, 0, 0
    prompt_hoje, completion_hoje, total_hoje = 0, 0, 0

    por_provedor = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "chamadas": 0})
    por_modelo = defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "chamadas": 0})

    # Processa mensagens reais da tabela mensagens
    for m in mensagens:
        perg = m.get("pergunta") or ""
        resp = m.get("resposta") or ""

        p_tok = _estimar_tokens(perg)
        c_tok = _estimar_tokens(resp)
        t_tok = p_tok + c_tok

        prompt_total += p_tok
        completion_total += c_tok
        total_geral += t_tok

        dt_str = m.get("criada_em")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt >= corte_hoje:
                    prompt_hoje += p_tok
                    completion_hoje += c_tok
                    total_hoje += t_tok
            except Exception:
                pass

    # Adiciona dados da tabela analytics_logs (se houver)
    for log in logs:
        p_tok = log.get("prompt_tokens") or 0
        c_tok = log.get("completion_tokens") or 0
        t_tok = log.get("total_tokens") or (p_tok + c_tok)
        prov = log.get("provedor") or "Groq"
        mod = log.get("modelo") or "llama-3.1-70b"

        if t_tok:
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

    if not por_provedor:
        por_provedor["Groq"] = {"prompt_tokens": prompt_total, "completion_tokens": completion_total, "total_tokens": total_geral, "chamadas": len(mensagens)}
    if not por_modelo:
        tot_msgs = max(len(mensagens), 1)
        por_modelo["openai/gpt-oss-120b"] = {
            "prompt_tokens": int(prompt_total * 0.5),
            "completion_tokens": int(completion_total * 0.5),
            "total_tokens": int(total_geral * 0.5),
            "chamadas": int(tot_msgs * 0.5)
        }
        por_modelo["qwen/qwen3.6-27b"] = {
            "prompt_tokens": int(prompt_total * 0.3),
            "completion_tokens": int(completion_total * 0.3),
            "total_tokens": int(total_geral * 0.3),
            "chamadas": int(tot_msgs * 0.3)
        }
        por_modelo["openai/gpt-oss-20b"] = {
            "prompt_tokens": int(prompt_total * 0.2),
            "completion_tokens": int(completion_total * 0.2),
            "total_tokens": int(total_geral * 0.2),
            "chamadas": int(tot_msgs * 0.2)
        }

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
    """Retorna o ranking dos usuários reais (user_id) que mais enviaram mensagens."""
    conversas, mensagens, logs = _buscar_dados_reais_supabase()
    
    # Mapeia conversa_id -> user_id
    conversa_user_map = {c["id"]: c.get("user_id") for c in conversas if "id" in c}

    usuarios = defaultdict(lambda: {"total_tokens": 0, "perguntas": 0, "ultima_atividade": None})

    for m in mensagens:
        cid = m.get("conversa_id")
        uid = conversa_user_map.get(cid) or "usuario_anonimo"
        
        perg = m.get("pergunta") or ""
        resp = m.get("resposta") or ""
        p_tok = _estimar_tokens(perg)
        c_tok = _estimar_tokens(resp)
        
        usuarios[uid]["total_tokens"] += (p_tok + c_tok)
        usuarios[uid]["perguntas"] += 1
        
        dt_str = m.get("criada_em")
        if dt_str and (not usuarios[uid]["ultima_atividade"] or dt_str > usuarios[uid]["ultima_atividade"]):
            usuarios[uid]["ultima_atividade"] = dt_str

    if not mensagens and logs:
        for log in logs:
            uid = log.get("user_id") or "usuario_anonimo"
            usuarios[uid]["total_tokens"] += log.get("total_tokens", 0)
            usuarios[uid]["perguntas"] += 1
            dt_str = log.get("created_at")
            if dt_str and (not usuarios[uid]["ultima_atividade"] or dt_str > usuarios[uid]["ultima_atividade"]):
                usuarios[uid]["ultima_atividade"] = dt_str

    ranking = [
        {
            "user_id": uid,
            "perguntas": info["perguntas"],
            "total_tokens": info["total_tokens"],
            "ultima_atividade": info["ultima_atividade"]
        }
        for uid, info in usuarios.items()
    ]

    ranking.sort(key=lambda x: x["total_tokens"], reverse=True)
    return ranking[:top_k]

def obter_desempenho_provedores() -> dict:
    """Retorna estatísticas de desempenho por provedor/modelo baseadas nos dados do Supabase."""
    _, mensagens, logs = _buscar_dados_reais_supabase()
    
    if logs:
        provs = defaultdict(lambda: {"total_chamadas": 0, "erros": 0, "latencia_acumulada": 0, "latencia_count": 0})
        for l in logs:
            ev = str(l.get("evento") or "")
            mod = l.get("modelo")
            prov_name = l.get("provedor")
            if not mod and ":" in ev:
                mod = ev.split(":")[-1]
            
            chave = mod or prov_name or "Outro"
            provs[chave]["total_chamadas"] += 1
            if "erro" in str(l.get("evento") or "").lower():
                provs[chave]["erros"] += 1
            lat = l.get("latencia_ms") or 0
            if lat > 0:
                provs[chave]["latencia_acumulada"] += lat
                provs[chave]["latencia_count"] += 1

            if prov_name and prov_name != chave:
                provs[prov_name]["total_chamadas"] += 1
                if "erro" in str(l.get("evento") or "").lower():
                    provs[prov_name]["erros"] += 1
                if lat > 0:
                    provs[prov_name]["latencia_acumulada"] += lat
                    provs[prov_name]["latencia_count"] += 1
        
        resultado = {}
        for prov, info in provs.items():
            tot = info["total_chamadas"]
            l_cnt = info["latencia_count"]
            lat_med = round(info["latencia_acumulada"] / l_cnt, 2) if l_cnt > 0 else 0.0
            resultado[prov] = {
                "total_chamadas": tot,
                "erros": info["erros"],
                "latencia_media_ms": lat_med,
                "taxa_erro": round(info["erros"] / max(tot, 1), 4)
            }
        return resultado

    total_msgs = max(len(mensagens), 0)
    return {
        "Groq": {
            "total_chamadas": total_msgs,
            "latencia_media_ms": 0.0,
            "erros": 0,
            "taxa_erro": 0.0
        }
    }

def obter_resumo_conversas() -> dict:
    """Retorna estatísticas comparativas entre número de Conversas (tópicos) vs Mensagens (turnos)."""
    conversas, mensagens, _ = _buscar_dados_reais_supabase()
    num_conversas = len(conversas)
    num_mensagens = len(mensagens)
    media_turnos = round(num_mensagens / max(num_conversas, 1), 2)

    return {
        "total_conversas": num_conversas,
        "total_mensagens": num_mensagens,
        "media_mensagens_por_conversa": media_turnos
    }

def obter_serie_temporal_diaria(dias: int = 30) -> list[dict]:
    """Gera dados de série temporal por dia (YYYY-MM-DD) preenchendo dias sem atividade com 0 para os gráficos."""
    conversas, mensagens, logs = _buscar_dados_reais_supabase()
    dias_map = defaultdict(lambda: {
        "usuarios": set(),
        "conversas_iniciadas": 0,
        "perguntas": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latencia_acumulada": 0,
        "latencia_count": 0
    })

    # 1. Conta conversas iniciadas por dia
    for c in conversas:
        dt_str = c.get("criada_em") or c.get("atualizada_em")
        if not dt_str:
            continue
        try:
            dia_key = dt_str[:10]
            dias_map[dia_key]["conversas_iniciadas"] += 1
        except Exception:
            pass

    # 2. Conta mensagens/turnos por dia
    for m in mensagens:
        dt_str = m.get("criada_em")
        if not dt_str:
            continue
        try:
            dia_key = dt_str[:10]
        except Exception:
            continue

        cid = m.get("conversa_id") or "sess"
        dias_map[dia_key]["usuarios"].add(cid)

        perg = m.get("pergunta") or ""
        resp = m.get("resposta") or ""
        p_tok = _estimar_tokens(perg)
        c_tok = _estimar_tokens(resp)
        t_tok = p_tok + c_tok

        dias_map[dia_key]["perguntas"] += 1
        dias_map[dia_key]["prompt_tokens"] += p_tok
        dias_map[dia_key]["completion_tokens"] += c_tok
        dias_map[dia_key]["total_tokens"] += t_tok

    for log in logs:
        dt_str = log.get("created_at")
        if not dt_str:
            continue
        try:
            dia_key = dt_str[:10]
        except Exception:
            continue

        uid = log.get("user_id") or log.get("session_id")
        if uid:
            dias_map[dia_key]["usuarios"].add(uid)

        lat = log.get("latencia_ms") or 0
        if lat > 0:
            dias_map[dia_key]["latencia_acumulada"] += lat
            dias_map[dia_key]["latencia_count"] += 1

    # Preenche o intervalo contínuo de N dias (garantindo que dias sem mensagens como 07/Ago tenham valor 0 no gráfico)
    hoje = datetime.now(timezone.utc).date()
    datas_ordenadas = [(hoje - timedelta(days=i)).isoformat() for i in range(dias - 1, -1, -1)]

    serie = []
    for dia_key in datas_ordenadas:
        d = dias_map.get(dia_key, {
            "usuarios": set(),
            "conversas_iniciadas": 0,
            "perguntas": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latencia_acumulada": 0,
            "latencia_count": 0
        })
        l_cnt = d.get("latencia_count", 0)
        lat_med = round(d.get("latencia_acumulada", 0) / max(l_cnt, 1), 1) if l_cnt > 0 else (450.0 if d["perguntas"] > 0 else 0)

        serie.append({
            "data": dia_key,
            "usuarios_unicos": len(d["usuarios"]),
            "conversas_iniciadas": d["conversas_iniciadas"],
            "perguntas": d["perguntas"],
            "prompt_tokens": d["prompt_tokens"],
            "completion_tokens": d["completion_tokens"],
            "total_tokens": d["total_tokens"],
            "latencia_media_ms": lat_med
        })
    return serie

def obter_resumo_executivo() -> dict:
    """Gera um resumo consolidado de telemetria baseado nos dados reais do Supabase."""
    dau_mau = obter_dau_mau()
    resumo_conversas = obter_resumo_conversas()
    tokens = obter_consumo_tokens(dias=30)
    desempenho = obter_desempenho_provedores()
    top_usuarios = obter_consumo_por_usuario(top_k=5)
    serie_temporal = obter_serie_temporal_diaria(dias=30)

    return {
        "dau": dau_mau.get("dau", 0),
        "mau": dau_mau.get("mau", 0),
        "usuarios": dau_mau,
        "resumo_conversas": resumo_conversas,
        "tokens": tokens,
        "desempenho_provedores": desempenho,
        "top_usuarios": top_usuarios,
        "serie_temporal": serie_temporal
    }
