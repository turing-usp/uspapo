import json
import os
import hashlib
import glob
import chromadb
from tqdm import tqdm
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

ARQUIVO_LEDGER = "ledger_arquivos.json"

def gerar_hash_texto(texto: str) -> str:
    """Gera um identificador único universal (MD5) baseado exclusivamente no texto."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()

def carregar_ledger() -> dict:
    """Carrega o histórico de arquivos já processados."""
    if os.path.exists(ARQUIVO_LEDGER):
        with open(ARQUIVO_LEDGER, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def salvar_ledger(ledger: dict):
    """Salva o estado atualizado dos arquivos processados."""
    with open(ARQUIVO_LEDGER, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=4)

def construir_banco():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    pasta_processed = os.path.join(diretorio_atual, "..", "data", "processed")
    caminho_db = os.path.join(diretorio_atual, "chroma_data")

    arquivos_json = glob.glob(os.path.join(pasta_processed, "**", "*.json"), recursive=True)

    if not arquivos_json:
        print(f"[ERRO] Nenhum arquivo JSON encontrado em {pasta_processed}.")
        return

    # 1. Carrega a "memória" do sistema (O Livro Caixa)
    ledger_arquivos = carregar_ledger()
    arquivos_processados_nesta_rodada = 0

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    documentos = []
    metadados = []
    ids = []
    hashes_vistos_no_lote = set()

    # 2. Conecta ao Banco ANTES do loop, pois precisaremos dele para deletar arquivos velhos
    print("-> Conectando ao banco de dados ChromaDB...")
    cliente = chromadb.PersistentClient(path=caminho_db)
    
    funcao_embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="intfloat/multilingual-e5-base"
    )

    colecao = cliente.get_or_create_collection(
        name="poli_chatbot",
        embedding_function=funcao_embedding
    )

    print(f"-> Encontrados {len(arquivos_json)} arquivos para verificação.")
    
    # 3. Loop de Varredura e Validação de Arquivos
    for caminho_arquivo in arquivos_json:
        nome_arquivo = os.path.basename(caminho_arquivo)
        
        try:
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                conteudo_texto_puro = f.read() # Lê como texto puro para gerar o hash do arquivo
                dados = json.loads(conteudo_texto_puro)
        except Exception as e:
            print(f"   [ERRO] Falha ao ler o arquivo {nome_arquivo}: {e}")
            continue

        # Calcula a assinatura digital do ARQUIVO INTEIRO
        hash_arquivo_atual = gerar_hash_texto(conteudo_texto_puro)
        
        # CAMADA 1: Verifica se o arquivo é inédito ou se sofreu alterações
        hash_antigo = ledger_arquivos.get(nome_arquivo)
        
        if hash_arquivo_atual == hash_antigo:
            # Arquivo não mudou. Pula instantaneamente.
            continue
            
        print(f"   Processando novo/modificado: {nome_arquivo}")
        arquivos_processados_nesta_rodada += 1
        
        # Se o arquivo já existia mas MUDOU, limpamos a sujeira velha do banco primeiro
        if hash_antigo is not None:
            print(f"   [!] Arquivo {nome_arquivo} foi alterado. Removendo blocos antigos do banco...")
            colecao.delete(where={"arquivo_origem": nome_arquivo})

        # Atualiza o ledger na memória
        ledger_arquivos[nome_arquivo] = hash_arquivo_atual

        # Extrai os textos do arquivo e fatia
        for pagina in dados:
            chunks = text_splitter.split_text(pagina["texto_limpo"])
            
            for chunk in chunks:
                chunk_hash = gerar_hash_texto(chunk)
                
                # CAMADA 2: Proteção de duplicatas no nível do bloco
                if chunk_hash in hashes_vistos_no_lote:
                    continue
                    
                hashes_vistos_no_lote.add(chunk_hash)
                
                # O segredo do modelo E5: O prefixo "passage: "
                documentos.append(f"passage: {chunk}")
                
                metadados.append({
                    "url": pagina["url"],
                    "titulo": pagina["titulo"],
                    "arquivo_origem": nome_arquivo 
                })
                ids.append(chunk_hash)

    print(f"-> Arquivos que exigiram processamento: {arquivos_processados_nesta_rodada} de {len(arquivos_json)}")

    # 4. Sincroniza com o banco apenas se houver algo novo
    if documentos:
        print(f"-> Total de blocos únicos novos gerados: {len(documentos)}")
        print("-> Sincronizando dados de forma incremental (Upserting)...")
        
        tamanho_lote = 256
        for i in tqdm(range(0, len(documentos), tamanho_lote), desc="Enviando lotes ao ChromaDB"):
            lote_docs = documentos[i : i + tamanho_lote]
            lote_metas = metadados[i : i + tamanho_lote]
            lote_ids = ids[i : i + tamanho_lote]
            
            colecao.upsert(
                documents=lote_docs,
                metadatas=lote_metas,
                ids=lote_ids
            )
            
        # Só salva o livro caixa no HD se o upload pro banco for um sucesso
        salvar_ledger(ledger_arquivos)
    else:
        print("-> Nenhum dado novo para sincronizar. O banco já está atualizado!")

    total_gavetas = colecao.count()
    print("\n[SUCESSO NA ARQUITETURA]")
    print(f"O banco vetorial possui agora um total de {total_gavetas} gavetas armazenadas.")

if __name__ == "__main__":
    construir_banco()