import json
import os
import subprocess
import time
from datetime import datetime, timedelta

def calcular_vencimento(data_str, freq_str):
    """Calcula se a data atual ultrapassou o last_update + frequency."""
    if not data_str:
        return True # Se nunca foi raspado, está vencido
    
    try:
        ultima_att = datetime.strptime(data_str, "%Y-%m-%d")
        dias = int(freq_str.replace('d', ''))
        proxima_att = ultima_att + timedelta(days=dias)
        return datetime.now() >= proxima_att
    except Exception as e:
        print(f"[AVISO] Erro ao calcular data para {data_str}: {e}. Forçando atualização.")
        return True

def rodar_pipeline():
    # Isso pega a pasta atual (scrapers/spiders)
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    
    # Isso sobe duas pastas para voltar para a raiz (uspapo)
    raiz_projeto = os.path.abspath(os.path.join(diretorio_atual, "..", ".."))
    
    # Agora sim, apontamos para a raiz/scrapers_config.json
    config_path = os.path.join(raiz_projeto, "scrapers_config.json")
    
    # E apontamos para a raiz/clean_data.py
    clean_script_path = os.path.join(raiz_projeto, "clean_data.py")
    
    if not os.path.exists(config_path):
        print(f"[ERRO] Arquivo de configuração não encontrado: {config_path}")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        configs = json.load(f)

    print("\n" + "="*50)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INICIANDO RONDA DO USPAPO")
    print("="*50)

    houve_atualizacao = False
    hoje_str = datetime.now().strftime("%Y-%m-%d")

    # FASE 1: VERIFICAÇÃO E EXTRAÇÃO
    for config in configs:
        id_site = config["id_site"]
        last_update = config.get("last_update", "")
        frequency = config.get("frequency", "7d")

        if calcular_vencimento(last_update, frequency):
            print(f">>> Site [{id_site.upper()}] vencido. Iniciando extração...")
            
            # Garante que a pasta data/raw existe
            pasta_raw = os.path.join(raiz_projeto, "data", "raw")
            os.makedirs(pasta_raw, exist_ok=True)
            
            # Define o nome do arquivo de saída (ex: poli_raw.json)
            arquivo_saida = os.path.join(pasta_raw, f"{id_site}_raw.json")
            
            comando_scrapy = [
                "scrapy", "crawl", "spider_generico", 
                "-a", f"config_id={id_site}",
                "-O", arquivo_saida  # <-- O Pulo do Gato: manda salvar no arquivo!
            ]
            
            try:
                subprocess.run(comando_scrapy, check=True)
                # Atualiza a data apenas se o Scrapy rodar sem erros graves
                config["last_update"] = hoje_str
                houve_atualizacao = True
                print(f"[SUCESSO] Extração de {id_site} concluída.\n")
            except subprocess.CalledProcessError as e:
                print(f"[ERRO] Falha ao raspar {id_site}. O robô parou com erro: {e}\n")
            
            time.sleep(2) # Respiro para o SO
        else:
            print(f"--- Site [{id_site.upper()}] está em dia. Próxima extração em breve.")

    # FASE 2: HIGIENIZAÇÃO (Clean Data)
    if houve_atualizacao:
        # Salva as novas datas no JSON
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
        print("\n[OK] scrapers_config.json atualizado com as novas datas.")

        print("\n" + "="*50)
        print(" INICIANDO HIGIENIZAÇÃO (Clean Data)")
        print("="*50)
        if os.path.exists(clean_script_path):
            try:
                subprocess.run(["python", clean_script_path], check=True)
                print("\n[SUCESSO] Dados brutos higienizados!")
            except subprocess.CalledProcessError as e:
                print(f"[ERRO] O script clean_data.py falhou: {e}")

        # FASE 3: VETORIZAÇÃO (Build Vector)
        build_vector_script = os.path.join(diretorio_atual, "embeddings", "build_vector.py")
        if os.path.exists(build_vector_script):
            print("\n" + "="*50)
            print(" INICIANDO VETORIZAÇÃO (Build Vector)")
            print("="*50)
            try:
                subprocess.run(["python", build_vector_script], check=True)
                print("\n[SUCESSO TOTAL] Banco de vetores atualizado!")
            except subprocess.CalledProcessError as e:
                print(f"[ERRO] O script build_vector.py falhou: {e}")
        else:
            print(f"[AVISO] Script {build_vector_script} não encontrado.")
    else:
        print("\n[INFO] Nenhuma atualização necessária hoje. Sistema ocioso.")

if __name__ == "__main__":
    rodar_pipeline()