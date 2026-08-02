import json
import os
import subprocess
import sys
from datetime import datetime

# Ajuste de caminhos (Como o script está em scripts/, a raiz é um nível acima)
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIRETORIO_RAIZ = os.path.abspath(os.path.join(DIRETORIO_ATUAL, ".."))

ARQUIVO_CONFIG = os.path.join(DIRETORIO_RAIZ, "scrapers_config.json")

# Caminhos absolutos para os scripts que serão chamados
SCRIPT_SCRAPER = os.path.join(DIRETORIO_RAIZ, "scrapers", "spiders", "rodar_scrapers.py")
SCRIPT_CLEAN = os.path.join(DIRETORIO_RAIZ, "embeddings", "clean_data.py")
SCRIPT_VECTOR = os.path.join(DIRETORIO_RAIZ, "embeddings", "build_vector.py")


def precisa_atualizar(last_update_str, frequencia_dias=7):
    """Verifica se já passou o tempo necessário desde a última raspagem."""
    if not last_update_str:
        return True
    
    try:
        data_ultima = datetime.strptime(last_update_str, "%Y-%m-%d")
        dias_decorridos = (datetime.now() - data_ultima).days
        return dias_decorridos >= frequencia_dias
    except ValueError:
        print(f"[AVISO] Formato de data inválido: {last_update_str}. Forçando atualização.")
        return True


def rodar_comando(comando, descricao):
    """Roda um script Python simulando o terminal, garantindo o diretório correto."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Iniciando: {descricao}")
    
    # O cwd (Current Working Directory) é setado para a raiz para que os scripts 
    # encontrem as pastas data/ e o arquivo scrapers_config.json naturalmente.
    resultado = subprocess.run([sys.executable, comando], cwd=DIRETORIO_RAIZ)
    
    if resultado.returncode != 0:
        print(f"[ERRO] Falha ao executar {descricao}. Abortando o pipeline.")
        sys.exit(1)


def iniciar_rotina():
    print(f"=== INICIANDO ROTINA DIÁRIA USPAPO ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    
    if not os.path.exists(ARQUIVO_CONFIG):
        print(f"[ERRO] Arquivo de configuração não encontrado em: {ARQUIVO_CONFIG}")
        sys.exit(1)

    with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    houve_atualizacao = False

    # --- CORREÇÃO: Lida tanto com lista [] quanto com dicionário {} ---
    lista_institutos = []
    if isinstance(config, dict):
        lista_institutos = config.items()
    elif isinstance(config, list):
        for i, item in enumerate(config):
            # Tenta pegar o nome do instituto nas chaves mais comuns
            nome = item.get("instituto") or item.get("nome") or item.get("id") or f"Instituto_{i}"
            lista_institutos.append((nome, item))

    # Agora itera de forma segura
    for instituto, detalhes in lista_institutos:
        if detalhes.get("ativo", True):
            if precisa_atualizar(detalhes.get("last_update"), detalhes.get("frequencia_dias", 7)):
                houve_atualizacao = True
                print(f" -> {instituto.upper()} agendado para atualização.")

    if not houve_atualizacao:
        print("\n-> Nenhum instituto atingiu a frequência de dias para atualização. Finalizando.")
        return

    # Executa a esteira sequencialmente
    rodar_comando(SCRIPT_SCRAPER, "1/3 - Raspagem de Dados (Scrapy)")
    rodar_comando(SCRIPT_CLEAN, "2/3 - Higienização de Textos (Clean Data)")
    rodar_comando(SCRIPT_VECTOR, "3/3 - Atualização do Banco Vetorial (Pinecone)")

    print(f"\n=== ROTINA FINALIZADA COM SUCESSO ({datetime.now().strftime('%H:%M:%S')}) ===")


if __name__ == "__main__":
    iniciar_rotina()