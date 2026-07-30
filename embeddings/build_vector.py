import json
import os
import hashlib
import glob
import time
from dotenv import load_dotenv
from tqdm import tqdm
from pinecone import Pinecone

# 1. Carrega as chaves do ambiente
load_dotenv()

DRY_RUN = True  # <--- TRAVA DE SEGURANÇA ATIVADA

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
if not PINECONE_API_KEY and not DRY_RUN:
    raise RuntimeError("PINECONE_API_KEY não encontrada no arquivo .env!")

PINECONE_INDEX_NAME = "uspapo-embeddings"

# Caminhos absolutos do projeto
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_PROCESSED = os.path.join(DIRETORIO_ATUAL, "..", "data", "processed")
PASTA_INDEX = os.path.join(DIRETORIO_ATUAL, "..", "data", "index")
ARQUIVO_LEDGER = os.path.join(PASTA_INDEX, "ledger_avancado.json")


def gerar_hash(texto: str) -> str:
    """Gera um identificador único universal (MD5) para controle de blocos."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()


def carregar_ledger() -> dict:
    """Carrega o índice hierárquico local (A memória de estado do banco)."""
    if os.path.exists(ARQUIVO_LEDGER):
        with open(ARQUIVO_LEDGER, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def salvar_ledger(ledger: dict):
    """Grava o estado consolidado no disco local."""
    os.makedirs(PASTA_INDEX, exist_ok=True)
    with open(ARQUIVO_LEDGER, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=4, ensure_ascii=False)


def agrupar_lista_de_paragrafos(lista_textos_paragrafos: list, target_size=800, max_size=1100) -> list:
    """
    Função base de agrupamento determinístico por parágrafos.
    Garante limite duro de 1100 caracteres sem cortar frases/parágrafos ao meio.
    """
    chunks_formados = []
    chunk_atual_textos = []
    tamanho_atual = 0

    for p in lista_textos_paragrafos:
        tam_p = len(p)
        
        # REGRA DO GIGANTE: Bloco indivisível (>1100 chars)
        if tam_p > max_size:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_formados.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
                chunk_atual_textos = []
                tamanho_atual = 0
            
            chunks_formados.append({
                "texto": p,
                "hash_chunk": gerar_hash(p),
                "paragrafos": [{"texto": p, "hash_p": gerar_hash(p)}]
            })
            continue

        tamanho_projetado = tamanho_atual + tam_p + (2 if chunk_atual_textos else 0)

        if tamanho_projetado <= target_size:
            chunk_atual_textos.append(p)
            tamanho_atual = tamanho_projetado
        elif tamanho_projetado <= max_size:
            chunk_atual_textos.append(p)
            texto_junto = "\n\n".join(chunk_atual_textos)
            chunks_formados.append({
                "texto": texto_junto,
                "hash_chunk": gerar_hash(texto_junto),
                "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
            })
            chunk_atual_textos = []
            tamanho_atual = 0
        else:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_formados.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
            chunk_atual_textos = [p]
            tamanho_atual = tam_p

    if chunk_atual_textos:
        texto_junto = "\n\n".join(chunk_atual_textos)
        chunks_formados.append({
            "texto": texto_junto,
            "hash_chunk": gerar_hash(texto_junto),
            "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
        })

    return chunks_formados


def rechunking_ancorado(old_chunks, novos_paragrafos_puros, target_size=800, max_size=1100):
    """
    O Motor de Otimização Incremental (Ancoragem Dinâmica + Anchor Flush + Trava de Reivindicação).
    Garante que chunks com textos idênticos (ex: rodapés/menus) em páginas diferentes mantenham seus IDs únicos.
    """
    primeiro_p_map = {}
    for c in old_chunks:
        if not c.get("paragrafos"): 
            continue
        first_hash = c["paragrafos"][0]["hash_p"]
        assinatura = "".join([p["hash_p"] for p in c["paragrafos"]])
        
        if first_hash not in primeiro_p_map:
            primeiro_p_map[first_hash] = []
        primeiro_p_map[first_hash].append({
            "assinatura": assinatura, 
            "len": len(c["paragrafos"]), 
            "chunk": c
        })

    chunks_finais = []
    chunk_atual_textos = []
    tamanho_atual = 0
    used_chunk_ids = set()  # Trava para impedir que a mesma âncora seja reutilizada por páginas diferentes

    idx = 0
    total_p = len(novos_paragrafos_puros)
    novos_hashes = [gerar_hash(p) for p in novos_paragrafos_puros]

    while idx < total_p:
        p_texto = novos_paragrafos_puros[idx]
        p_hash = novos_hashes[idx]

        # TENTATIVA DE ANCORAGEM COM DESACOPLAMENTO
        ancorado = False
        if p_hash in primeiro_p_map:
            for candidato in primeiro_p_map[p_hash]:
                c_id = candidato["chunk"].get("chunk_id")
                
                # Se esse chunk_id já foi reivindicado por outra página nesta rodada, pula para o próximo!
                if c_id and c_id in used_chunk_ids:
                    continue

                tam_janela = candidato["len"]
                if idx + tam_janela <= total_p:
                    assinatura_teste = "".join(novos_hashes[idx : idx + tam_janela])
                    if assinatura_teste == candidato["assinatura"]:
                        # Despeja o texto acumulado na área modificada anterior
                        if chunk_atual_textos:
                            texto_junto = "\n\n".join(chunk_atual_textos)
                            chunks_finais.append({
                                "texto": texto_junto,
                                "hash_chunk": gerar_hash(texto_junto),
                                "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                            })
                            chunk_atual_textos = []
                            tamanho_atual = 0

                        # Acopla a âncora e registra a reivindicação
                        chunks_finais.append(candidato["chunk"])
                        if c_id:
                            used_chunk_ids.add(c_id)
                            
                        idx += tam_janela
                        ancorado = True
                        break
        
        if ancorado:
            continue

        # LÓGICA PADRÃO DE AGRUPAMENTO
        tam_p = len(p_texto)
        if tam_p > max_size:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_finais.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
                chunk_atual_textos = []
                tamanho_atual = 0

            chunks_finais.append({
                "texto": p_texto,
                "hash_chunk": p_hash,
                "paragrafos": [{"texto": p_texto, "hash_p": p_hash}]
            })
            idx += 1
            continue

        tamanho_projetado = tamanho_atual + tam_p + (2 if chunk_atual_textos else 0)

        if tamanho_projetado <= target_size:
            chunk_atual_textos.append(p_texto)
            tamanho_atual = tamanho_projetado
        elif tamanho_projetado <= max_size:
            chunk_atual_textos.append(p_texto)
            texto_junto = "\n\n".join(chunk_atual_textos)
            chunks_finais.append({
                "texto": texto_junto,
                "hash_chunk": gerar_hash(texto_junto),
                "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
            })
            chunk_atual_textos = []
            tamanho_atual = 0
        else:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_finais.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
            chunk_atual_textos = [p_texto]
            tamanho_atual = tam_p

        idx += 1

    if chunk_atual_textos:
        texto_junto = "\n\n".join(chunk_atual_textos)
        chunks_finais.append({
            "texto": texto_junto,
            "hash_chunk": gerar_hash(texto_junto),
            "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
        })

    # BALANÇO DE OPERAÇÕES
    ids_velhos = {c["chunk_id"]: c for c in old_chunks if "chunk_id" in c}
    ids_novos_preservados = set()
    chunks_nascidos = []

    for c_final in chunks_finais:
        if "chunk_id" in c_final:
            ids_novos_preservados.add(c_final["chunk_id"])
        else:
            chunks_nascidos.append(c_final)

    ids_mortos = list(set(ids_velhos.keys()) - ids_novos_preservados)

    return chunks_finais, ids_mortos, chunks_nascidos


def construir_banco():
    arquivos_json = glob.glob(os.path.join(PASTA_PROCESSED, "**", "*.json"), recursive=True)

    if not arquivos_json:
        print(f"[AVISO] Nenhum arquivo JSON encontrado em {PASTA_PROCESSED}.")
        return

    ledger_avancado = carregar_ledger()

    if DRY_RUN:
        print("-> [DRY RUN] Ignorando conexão com Pinecone (Modo Offline).")
    else:
        print("-> Conectando ao Pinecone...")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)

    lote_global_delete = []
    lote_global_upsert = []

    # FASE 1: Lixeira de Páginas Removidas
    nomes_arquivos_locais = {os.path.basename(caminho) for caminho in arquivos_json}
    arquivos_no_ledger = set(ledger_avancado.keys())
    arquivos_deletados = arquivos_no_ledger - nomes_arquivos_locais

    if arquivos_deletados:
        for arq_removido in arquivos_deletados:
            print(f"   [Lixeira] Arquivo {arq_removido} não existe mais localmente. Marcando blocos para deleção.")
            for chunk_data in ledger_avancado[arq_removido].get("chunks", []):
                if "chunk_id" in chunk_data:
                    lote_global_delete.append(chunk_data["chunk_id"])
            del ledger_avancado[arq_removido]

    # FASE 2: Processamento e Diff de Arquivos Processados
    for caminho_arquivo in arquivos_json:
        nome_arquivo = os.path.basename(caminho_arquivo)
        
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.loads(f.read())
        except Exception as e:
            print(f"   [ERRO] Falha ao ler {nome_arquivo}: {e}")
            continue

        url_site = dados[0].get("url", "") if dados else ""
        estado_antigo = ledger_avancado.get(nome_arquivo, {"chunks": []})
        old_chunks = estado_antigo.get("chunks", [])
        
        # Extrai os parágrafos novos do JSON
        paragrafos_novos_puros = []
        for pagina in dados:
            texto = pagina.get("texto_limpo", "")
            textos = [p.strip() for p in texto.split("\n\n") if p.strip()]
            paragrafos_novos_puros.extend(textos)

        if not paragrafos_novos_puros:
            continue

        # COLD START (Primeira execução do arquivo)
        if not old_chunks:
            novos_chunks = agrupar_lista_de_paragrafos(paragrafos_novos_puros)
            estado_novo = []
            
            for idx, chunk_dict in enumerate(novos_chunks):
                pinecone_id = f"{nome_arquivo}_ch{idx}_{chunk_dict['hash_chunk']}"
                chunk_dict["chunk_id"] = pinecone_id
                estado_novo.append(chunk_dict)
                
                lote_global_upsert.append({
                    "_id": pinecone_id,
                    "text": f"passage: {chunk_dict['texto']}",
                    "url": url_site,
                    "titulo": dados[0].get("titulo", ""),
                    "arquivo_origem": nome_arquivo
                })
            
            ledger_avancado[nome_arquivo] = {"url": url_site, "chunks": estado_novo}
            print(f"   [{nome_arquivo}] Cold Start: {len(estado_novo)} blocos novos preparados.")
            continue

        # RECHUNKING INCREMENTAL ANCORADO
        chunks_finais, ids_mortos, chunks_nascidos = rechunking_ancorado(old_chunks, paragrafos_novos_puros)
        
        if not ids_mortos and not chunks_nascidos:
            continue  # Zero alterações detectadas no site.

        print(f"   [{nome_arquivo}] Atualização Incremental: {len(chunks_nascidos)} novos | {len(ids_mortos)} removidos.")
        
        lote_global_delete.extend(ids_mortos)
        
        estado_novo = []
        for idx, chunk_dict in enumerate(chunks_finais):
            if "chunk_id" in chunk_dict:
                estado_novo.append(chunk_dict)
            else:
                pinecone_id = f"{nome_arquivo}_ch{idx}_{chunk_dict['hash_chunk']}"
                chunk_dict["chunk_id"] = pinecone_id
                estado_novo.append(chunk_dict)
                
                lote_global_upsert.append({
                    "_id": pinecone_id,
                    "text": f"passage: {chunk_dict['texto']}",
                    "url": url_site,
                    "titulo": dados[0].get("titulo", ""),
                    "arquivo_origem": nome_arquivo
                })
                
        ledger_avancado[nome_arquivo] = {"url": url_site, "chunks": estado_novo}

    # =======================================================
    # FASE 3: Sincronização em Lote com a Nuvem (Pinecone)
    # =======================================================

    if not lote_global_delete and not lote_global_upsert:
        print("\n-> Banco vetorial sincronizado! Zero WUs gastos na nuvem.")
        if not DRY_RUN:
            salvar_ledger(ledger_avancado)
        return

    print("\n" + "="*50)
    print("RESUMO DA OPERAÇÃO PARA O PINECONE:")
    print("="*50)
    print(f" -> Deletes agendados: {len(lote_global_delete)} vetores.")
    print(f" -> Upserts agendados: {len(lote_global_upsert)} vetores.")
    print("="*50)

    if DRY_RUN:
        print("\n[MODO DRY RUN ATIVADO] Nenhuma requisição foi enviada ao Pinecone.")
        print("Salvando o ledger_avancado.json localmente para simular o estado da nuvem...")
        salvar_ledger(ledger_avancado)
        return

    # --- Daqui para baixo, o código só roda se DRY_RUN for False ---
    if lote_global_delete:
        print(f"\n-> Removendo {len(lote_global_delete)} vetores obsoletos do Pinecone...")
        for i in range(0, len(lote_global_delete), 1000):
            lote_del = lote_global_delete[i:i+1000]
            index.delete(ids=lote_del, namespace="uspapo")

    if lote_global_upsert:
        print(f"\n-> Enviando {len(lote_global_upsert)} novos vetores ao Pinecone...")
        tamanho_lote = 90
        for i in tqdm(range(0, len(lote_global_upsert), tamanho_lote), desc="Sincronizando"):
            lote_up = lote_global_upsert[i : i + tamanho_lote]
            sucesso = False
            while not sucesso:
                try:
                    index.upsert_records(namespace="uspapo", records=lote_up)
                    sucesso = True
                    time.sleep(1.5)
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        print("\n[!] Limite atingido. Pausando por 60s...")
                        time.sleep(60)
                    else:
                        raise e

    salvar_ledger(ledger_avancado)
    status = index.describe_index_stats()
    print("\n[SUCESSO] Sincronização do banco de vetores finalizada!")
    if DRY_RUN:
        print("Total de blocos ativos no Pinecone: [Simulação Offline - Status Indisponível].")
    else:
        status = index.describe_index_stats()
        print(f"Total de blocos ativos no Pinecone: {status.total_vector_count}.")

if __name__ == "__main__":
    construir_banco()