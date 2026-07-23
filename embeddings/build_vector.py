import json
import os
import hashlib
import glob
import time
from dotenv import load_dotenv
from tqdm import tqdm
from pinecone import Pinecone
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 1. Carrega as chaves do arquivo .env
load_dotenv()

ARQUIVO_LEDGER = "ledger_arquivos.json"
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Proteção: Impede o código de rodar se a chave não for encontrada
if not PINECONE_API_KEY:
    raise RuntimeError("PINECONE_API_KEY não encontrada no arquivo .env!")

PINECONE_INDEX_NAME = "uspapo-embeddings"

def gerar_hash_texto(texto: str) -> str:
    """Gera um identificador único universal (MD5) baseado no texto."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()

def carregar_ledger() -> dict:
    if os.path.exists(ARQUIVO_LEDGER):
        with open(ARQUIVO_LEDGER, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def salvar_ledger(ledger: dict):
    with open(ARQUIVO_LEDGER, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=4)

def construir_banco():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    pasta_processed = os.path.join(diretorio_atual, "..", "data", "processed")

    arquivos_json = glob.glob(os.path.join(pasta_processed, "**", "*.json"), recursive=True)

    if not arquivos_json:
        print(f"[AVISO] Nenhum arquivo JSON encontrado em {pasta_processed}.")
        return

    ledger_arquivos = carregar_ledger()
    arquivos_processados_nesta_rodada = 0

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    print("-> Conectando ao Pinecone...")
    # Olha como ficou limpo! Nada de carregar SentenceTransformer pesado.
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    print(f"-> Encontrados {len(arquivos_json)} arquivos na pasta local.")

    # ---------------------------------------------------------
    # A LIXEIRA (Deleta do Pinecone arquivos removidos do seu PC)
    # ---------------------------------------------------------
    nomes_arquivos_locais = {os.path.basename(caminho) for caminho in arquivos_json}
    arquivos_no_ledger = set(ledger_arquivos.keys())
    arquivos_deletados = arquivos_no_ledger - nomes_arquivos_locais

    if arquivos_deletados:
        print(f"\n[!] Encontrados {len(arquivos_deletados)} arquivos deletados localmente. Limpando do Pinecone...")
        for arq_removido in arquivos_deletados:
            print(f"   Excluindo registros de: {arq_removido}")
            index.delete(filter={"arquivo_origem": {"$eq": arq_removido}})
            del ledger_arquivos[arq_removido]
        salvar_ledger(ledger_arquivos)

    # ---------------------------------------------------------

    registros_pinecone = []
    hashes_vistos_no_lote = set()

    print("\n-> Verificando atualizações e novos arquivos...")
    for caminho_arquivo in arquivos_json:
        nome_arquivo = os.path.basename(caminho_arquivo)
        
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                conteudo_texto_puro = f.read()
                dados = json.loads(conteudo_texto_puro)
        except Exception as e:
            print(f"   [ERRO] Falha ao ler {nome_arquivo}: {e}")
            continue

        hash_arquivo_atual = gerar_hash_texto(conteudo_texto_puro)
        hash_antigo = ledger_arquivos.get(nome_arquivo)
        
        # Pula se o arquivo for idêntico ao já salvo
        if hash_arquivo_atual == hash_antigo:
            continue
            
        print(f"   Processando novo/modificado: {nome_arquivo}")
        arquivos_processados_nesta_rodada += 1
        
        # Se mudou, deletamos os antigos antes de enviar os novos
        if hash_antigo is not None:
            print(f"   [!] Alteração detectada em {nome_arquivo}. Limpando blocos antigos do Pinecone...")
            index.delete(filter={"arquivo_origem": {"$eq": nome_arquivo}})

        ledger_arquivos[nome_arquivo] = hash_arquivo_atual

        for pagina in dados:
            chunks = text_splitter.split_text(pagina["texto_limpo"])
            
            for chunk in chunks:
                chunk_hash = gerar_hash_texto(chunk)
                
                if chunk_hash in hashes_vistos_no_lote:
                    continue
                    
                hashes_vistos_no_lote.add(chunk_hash)
                
                # O FORMATO INTEGRATED EMBEDDINGS (JSON PLANO)
                registros_pinecone.append({
                    "_id": chunk_hash,
                    # O "passage:" ainda é obrigatório para o E5-Large entender que é uma fonte de dados
                    "text": f"passage: {chunk}", 
                    "url": pagina["url"],
                    "titulo": pagina["titulo"],
                    "arquivo_origem": nome_arquivo
                })

    print(f"-> Arquivos que exigiram processamento: {arquivos_processados_nesta_rodada}")

    # 3. Envio super leve direto para a API
    if registros_pinecone:
        print(f"\n-> Sincronizando {len(registros_pinecone)} blocos com o Pinecone (Integrated Embedding)...")
        
        tamanho_lote = 90 
        for i in tqdm(range(0, len(registros_pinecone), tamanho_lote), desc="Enviando lotes ao Pinecone"):
            lote = registros_pinecone[i : i + tamanho_lote]
            
            sucesso = False
            while not sucesso:
                try:
                    index.upsert_records(namespace="uspapo", records=lote)
                    sucesso = True
                    # Uma micro-pausa saudável entre lotes normais
                    time.sleep(1.5) 
                except Exception as e:
                    # Se batermos no limite de requisições, o código respira e tenta de novo
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        print("\n[!] Limite de tokens atingido. Pausando por 60 segundos (não feche o terminal)...")
                        time.sleep(60)
                    else:
                        raise e # Se for outro erro, ele para o código
            
        salvar_ledger(ledger_arquivos)
    else:
        print("\n-> Nenhum dado novo para sincronizar. O banco já está atualizado!")

    status = index.describe_index_stats()
    print("\n[SUCESSO NA ARQUITETURA]")
    print(f"O Pinecone possui agora um total de {status.total_vector_count} blocos armazenados na nuvem.")

if __name__ == "__main__":
    construir_banco()