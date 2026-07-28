import json
import os
import hashlib
import glob
import time
from dotenv import load_dotenv
from tqdm import tqdm
from pinecone import Pinecone

# 1. Carrega as chaves do arquivo .env
load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

if not PINECONE_API_KEY:
    raise RuntimeError("PINECONE_API_KEY não encontrada no arquivo .env!")

PINECONE_INDEX_NAME = "uspapo-embeddings"

# Caminhos absolutos para garantir que rode de qualquer lugar
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_PROCESSED = os.path.join(DIRETORIO_ATUAL, "..", "data", "processed")
PASTA_INDEX = os.path.join(DIRETORIO_ATUAL, "..", "data", "index")
ARQUIVO_LEDGER = os.path.join(PASTA_INDEX, "ledger.json")

def gerar_hash_texto(texto: str) -> str:
    """Gera um identificador único universal (MD5) baseado no texto."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()

def carregar_ledger() -> dict:
    """
    O ledger agora guarda o hash de CADA CHUNK.
    Ex: { "poli.json": { "hash_chunk1": "id_pinecone_1", "hash_chunk2": "id_pinecone_2" } }
    """
    if os.path.exists(ARQUIVO_LEDGER):
        with open(ARQUIVO_LEDGER, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def salvar_ledger(ledger: dict):
    os.makedirs(PASTA_INDEX, exist_ok=True)
    with open(ARQUIVO_LEDGER, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=4)

def agrupar_por_paragrafos(texto_limpo: str, target_size=800, max_size=1100) -> list:
    """
    O Coração da Otimização: Substitui o LangChain.
    Impede o Efeito Cascata agrupando blocos de texto sem sobreposição.
    """
    paragrafos = [p.strip() for p in texto_limpo.split("\n\n") if p.strip()]
    chunks = []
    chunk_atual = ""

    for p in paragrafos:
        # REGRA DO GIGANTE: Blocos indivisíveis (>1100) viram chunks exclusivos
        if len(p) > max_size:
            if chunk_atual:
                chunks.append(chunk_atual)
                chunk_atual = ""
            chunks.append(p)
            continue

        tamanho_projetado = len(chunk_atual) + len(p) + 2 # +2 pelo \n\n

        if tamanho_projetado <= target_size:
            chunk_atual = chunk_atual + "\n\n" + p if chunk_atual else p
        elif tamanho_projetado <= max_size:
            chunk_atual = chunk_atual + "\n\n" + p if chunk_atual else p
            chunks.append(chunk_atual)
            chunk_atual = ""
        else:
            if chunk_atual:
                chunks.append(chunk_atual)
            chunk_atual = p

    # Adiciona a raspa final
    if chunk_atual:
        chunks.append(chunk_atual)

    return chunks

def construir_banco():
    arquivos_json = glob.glob(os.path.join(PASTA_PROCESSED, "**", "*.json"), recursive=True)

    if not arquivos_json:
        print(f"[AVISO] Nenhum arquivo JSON encontrado em {PASTA_PROCESSED}.")
        return

    ledger_arquivos = carregar_ledger()
    
    print("-> Conectando ao Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    ids_para_deletar = []
    registros_para_upsert = []
    arquivos_processados = 0

    print(f"-> Analisando {len(arquivos_json)} arquivos para encontrar as Zonas de Impacto...")

    # ---------------------------------------------------------
    # FASE 1: A LIXEIRA (Deletar arquivos inteiros que sumiram)
    # ---------------------------------------------------------
    nomes_arquivos_locais = {os.path.basename(caminho) for caminho in arquivos_json}
    arquivos_no_ledger = set(ledger_arquivos.keys())
    arquivos_deletados = arquivos_no_ledger - nomes_arquivos_locais

    if arquivos_deletados:
        for arq_removido in arquivos_deletados:
            print(f"   [Lixeira] O arquivo {arq_removido} sumiu. Marcando seus blocos para exclusão.")
            # Coleta os IDs de todos os chunks daquele arquivo
            ids_para_deletar.extend(list(ledger_arquivos[arq_removido].values()))
            del ledger_arquivos[arq_removido]

    # ---------------------------------------------------------
    # FASE 2: DIFFING DE CHUNKS CIRÚRGICO
    # ---------------------------------------------------------
    for caminho_arquivo in arquivos_json:
        nome_arquivo = os.path.basename(caminho_arquivo)
        
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.loads(f.read())
        except Exception as e:
            print(f"   [ERRO] Falha ao ler {nome_arquivo}: {e}")
            continue

        chunks_antigos = ledger_arquivos.get(nome_arquivo, {}) 
        chunks_novos = {}
        
        # Reconstrói as fronteiras determinísticas da página
        for pagina in dados:
            textos_agrupados = agrupar_por_paragrafos(pagina["texto_limpo"])
            
            for texto_chunk in textos_agrupados:
                chunk_hash = gerar_hash_texto(texto_chunk)
                pinecone_id = f"{nome_arquivo}_{chunk_hash}"
                
                chunks_novos[chunk_hash] = {
                    "id": pinecone_id,
                    "text": f"passage: {texto_chunk}", 
                    "url": pagina.get("url", ""),
                    "titulo": pagina.get("titulo", ""),
                    "arquivo_origem": nome_arquivo
                }

        # Cruzamento de Hashes
        set_antigos = set(chunks_antigos.keys())
        set_novos = set(chunks_novos.keys())

        hashes_removidos = set_antigos - set_novos
        hashes_adicionados = set_novos - set_antigos
        hashes_intactos = set_antigos & set_novos

        if hashes_removidos or hashes_adicionados:
            arquivos_processados += 1
            print(f"   [{nome_arquivo}] Atualizando: {len(hashes_adicionados)} novos | {len(hashes_removidos)} removidos | {len(hashes_intactos)} intactos.")

        # 1. Enfileira o que sumiu para deleção
        for h in hashes_removidos:
            ids_para_deletar.append(chunks_antigos[h])

        # 2. Constrói o estado novo em memória (Mantém os intactos, adiciona os novos)
        novo_ledger_do_arquivo = {}
        for h in hashes_intactos:
            novo_ledger_do_arquivo[h] = chunks_antigos[h]
            
        for h in hashes_adicionados:
            dados_chunk = chunks_novos[h]
            registros_para_upsert.append({
                "_id": dados_chunk["id"],
                "text": dados_chunk["text"],
                "url": dados_chunk["url"],
                "titulo": dados_chunk["titulo"],
                "arquivo_origem": dados_chunk["arquivo_origem"]
            })
            novo_ledger_do_arquivo[h] = dados_chunk["id"] 

        ledger_arquivos[nome_arquivo] = novo_ledger_do_arquivo

    # ---------------------------------------------------------
    # FASE 3: A EXECUÇÃO NA NUVEM
    # ---------------------------------------------------------
    if not ids_para_deletar and not registros_para_upsert:
        print("\n-> Sincronização limpa. O banco já está atualizado! Zero WUs gastos.")
        # Salva o ledger por garantia, caso a lixeira tenha removido algo inteiro
        salvar_ledger(ledger_arquivos)
        return

    if ids_para_deletar:
        print(f"\n-> Deletando {len(ids_para_deletar)} blocos modificados/obsoletos do Pinecone...")
        for i in range(0, len(ids_para_deletar), 1000):
            lote_ids = ids_para_deletar[i:i+1000]
            index.delete(ids=lote_ids, namespace="uspapo")

    if registros_para_upsert:
        print(f"\n-> Sincronizando {len(registros_para_upsert)} blocos com o Pinecone...")
        tamanho_lote = 90 
        for i in tqdm(range(0, len(registros_para_upsert), tamanho_lote), desc="Enviando lotes ao Pinecone"):
            lote = registros_para_upsert[i : i + tamanho_lote]
            sucesso = False
            while not sucesso:
                try:
                    index.upsert_records(namespace="uspapo", records=lote)
                    sucesso = True
                    time.sleep(1.5) 
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        print("\n[!] Limite de tokens atingido. Pausando por 60 segundos (não feche o terminal)...")
                        time.sleep(60)
                    else:
                        raise e

    # Só consolida a memória no disco se a nuvem responder 200 OK
    salvar_ledger(ledger_arquivos)
    
    status = index.describe_index_stats()
    print("\n[SUCESSO] Engenharia de sincronização finalizada!")
    print(f"O Pinecone possui agora {status.total_vector_count} blocos na nuvem.")

if __name__ == "__main__":
    construir_banco()