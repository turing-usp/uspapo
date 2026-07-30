import json
import os
import hashlib
import glob
import time
from dotenv import load_dotenv
from tqdm import tqdm
from pinecone import Pinecone

# 1. Trava de segurança para execução sem API Key
DRY_RUN = True

load_dotenv()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

if not PINECONE_API_KEY and not DRY_RUN:
    raise RuntimeError("PINECONE_API_KEY não encontrada no arquivo .env!")

PINECONE_INDEX_NAME = "uspapo-embeddings"

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_PROCESSED = os.path.join(DIRETORIO_ATUAL, "..", "data", "processed")
PASTA_INDEX = os.path.join(DIRETORIO_ATUAL, "..", "data", "index")
ARQUIVO_LEDGER = os.path.join(PASTA_INDEX, "ledger_avancado.json")


def gerar_hash(texto: str) -> str:
    return hashlib.md5(texto.encode('utf-8')).hexdigest()


def carregar_ledger() -> dict:
    if os.path.exists(ARQUIVO_LEDGER):
        with open(ARQUIVO_LEDGER, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def salvar_ledger(ledger: dict):
    os.makedirs(PASTA_INDEX, exist_ok=True)
    with open(ARQUIVO_LEDGER, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=4, ensure_ascii=False)


def agrupar_lista_de_paragrafos(lista_textos_paragrafos: list, target_size=800, max_size=1100) -> list:
    chunks_formados = []
    chunk_atual_textos = []
    tamanho_atual = 0

    for p in lista_textos_paragrafos:
        tam_p = len(p)
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
            chunk_atual_textos = [p_texto if 'p_texto' in locals() else p]
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
    used_chunk_ids = set()

    idx = 0
    total_p = len(novos_paragrafos_puros)
    novos_hashes = [gerar_hash(p) for p in novos_paragrafos_puros]

    while idx < total_p:
        p_texto = novos_paragrafos_puros[idx]
        p_hash = novos_hashes[idx]

        ancorado = False
        if p_hash in primeiro_p_map:
            for candidato in primeiro_p_map[p_hash]:
                c_id = candidato["chunk"].get("chunk_id")
                if c_id and c_id in used_chunk_ids:
                    continue

                tam_janela = candidato["len"]
                if idx + tam_janela <= total_p:
                    assinatura_teste = "".join(novos_hashes[idx : idx + tam_janela])
                    if assinatura_teste == candidato["assinatura"]:
                        if chunk_atual_textos:
                            texto_junto = "\n\n".join(chunk_atual_textos)
                            chunks_finais.append({
                                "texto": texto_junto,
                                "hash_chunk": gerar_hash(texto_junto),
                                "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                            })
                            chunk_atual_textos = []
                            tamanho_atual = 0

                        chunks_finais.append(candidato["chunk"])
                        if c_id:
                            used_chunk_ids.add(c_id)
                        idx += tam_janela
                        ancorado = True
                        break
        
        if ancorado:
            continue

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

    # FASE 1: Limpeza de arquivos removidos no disco
    nomes_arquivos_locais = {os.path.basename(caminho) for caminho in arquivos_json}
    arquivos_no_ledger = set(ledger_avancado.keys())
    arquivos_deletados = arquivos_no_ledger - nomes_arquivos_locais

    if arquivos_deletados:
        for arq_removido in arquivos_deletados:
            print(f"   [Lixeira] Arquivo {arq_removido} removido localmente. Deletando vetores no Pinecone...")
            for pag_data in ledger_avancado[arq_removido].get("paginas", {}).values():
                for chunk_data in pag_data.get("chunks", []):
                    if "chunk_id" in chunk_data:
                        lote_global_delete.append(chunk_data["chunk_id"])
            del ledger_avancado[arq_removido]

    # FASE 2: Processamento PÁGINA A PÁGINA dentro de cada arquivo
    for caminho_arquivo in arquivos_json:
        nome_arquivo = os.path.basename(caminho_arquivo)
        
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                paginas = json.loads(f.read())
        except Exception as e:
            print(f"   [ERRO] Falha ao ler {nome_arquivo}: {e}")
            continue

        if nome_arquivo not in ledger_avancado:
            ledger_avancado[nome_arquivo] = {"paginas": {}}

        estado_arquivo_ledger = ledger_avancado[nome_arquivo]["paginas"]
        novos_nascidos_no_arq = 0
        removidos_no_arq = 0

        for pag_idx, pagina in enumerate(paginas):
            url_pagina = pagina.get("url", f"sem_url_{pag_idx}")
            titulo_pagina = pagina.get("titulo", "")
            texto = pagina.get("texto_limpo", "")

            paragrafos_pagina = [p.strip() for p in texto.split("\n\n") if p.strip()]
            if not paragrafos_pagina:
                continue

            estado_antigo_pag = estado_arquivo_ledger.get(url_pagina, {"chunks": []})
            old_chunks = estado_antigo_pag.get("chunks", [])

            hash_url = gerar_hash(url_pagina)[:8]

            # COLD START DA PÁGINA
            if not old_chunks:
                novos_chunks = agrupar_lista_de_paragrafos(paragrafos_pagina)
                estado_novo_chunks = []

                for idx, chunk_dict in enumerate(novos_chunks):
                    pinecone_id = f"{nome_arquivo}_{hash_url}_ch{idx}_{chunk_dict['hash_chunk']}"
                    chunk_dict["chunk_id"] = pinecone_id
                    estado_novo_chunks.append(chunk_dict)

                    lote_global_upsert.append({
                        "_id": pinecone_id,
                        "text": f"passage: {chunk_dict['texto']}",
                        "url": url_pagina,             # URL EXATA DA PÁGINA!
                        "titulo": titulo_pagina,        # TÍTULO EXATO DA PÁGINA!
                        "arquivo_origem": nome_arquivo
                    })

                estado_arquivo_ledger[url_pagina] = {
                    "titulo": titulo_pagina,
                    "chunks": estado_novo_chunks
                }
                novos_nascidos_no_arq += len(estado_novo_chunks)
                continue

            # RECHUNKING INCREMENTAL ISOLADO DA PÁGINA
            chunks_finais, ids_mortos, chunks_nascidos = rechunking_ancorado(old_chunks, paragrafos_pagina)

            if not ids_mortos and not chunks_nascidos:
                continue

            lote_global_delete.extend(ids_mortos)
            removidos_no_arq += len(ids_mortos)
            novos_nascidos_no_arq += len(chunks_nascidos)

            estado_novo_chunks = []
            for idx, chunk_dict in enumerate(chunks_finais):
                if "chunk_id" in chunk_dict:
                    estado_novo_chunks.append(chunk_dict)
                else:
                    pinecone_id = f"{nome_arquivo}_{hash_url}_ch{idx}_{chunk_dict['hash_chunk']}"
                    chunk_dict["chunk_id"] = pinecone_id
                    estado_novo_chunks.append(chunk_dict)

                    lote_global_upsert.append({
                        "_id": pinecone_id,
                        "text": f"passage: {chunk_dict['texto']}",
                        "url": url_pagina,             # URL EXATA DA PÁGINA!
                        "titulo": titulo_pagina,        # TÍTULO EXATO DA PÁGINA!
                        "arquivo_origem": nome_arquivo
                    })

            estado_arquivo_ledger[url_pagina] = {
                "titulo": titulo_pagina,
                "chunks": estado_novo_chunks
            }

        if novos_nascidos_no_arq > 0 or removidos_no_arq > 0:
            print(f"   [{nome_arquivo}] Atualizado por Página: {novos_nascidos_no_arq} novos | {removidos_no_arq} removidos.")

    # FASE 3: Sincronização em Lote
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
    print(f"Total de blocos ativos no Pinecone: {status.total_vector_count}.")


if __name__ == "__main__":
    construir_banco()