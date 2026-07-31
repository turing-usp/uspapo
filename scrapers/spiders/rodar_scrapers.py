import json
import os
import subprocess
import time
import sys
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
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    raiz_projeto = os.path.abspath(os.path.join(diretorio_atual, "..", ".."))
    
    config_path = os.path.join(raiz_projeto, "scrapers_config.json")
    clean_script_path = os.path.join(raiz_projeto, "embeddings", "clean_data.py")
    build_vector_script = os.path.join(raiz_projeto, "embeddings", "build_vector.py")
    
    if not os.path.exists(config_path):
        print(f"[ERRO] Ficheiro de configuração não encontrado: {config_path}")
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
            print(f">>> Site [{id_site.upper()}] vencido. A iniciar extração...")
            
            pasta_raw = os.path.join(raiz_projeto, "data", "raw")
            os.makedirs(pasta_raw, exist_ok=True)
            
            arquivo_saida = os.path.join(pasta_raw, f"{id_site}_raw.json")
            
            comando_scrapy = [
                "scrapy", "crawl", "spider_generico", 
                "-a", f"config_id={id_site}",
                "-O", arquivo_saida,
                "-L", "INFO"
            ]
            
            try:
                subprocess.run(comando_scrapy, check=True)
                config["last_update"] = hoje_str
                houve_atualizacao = True
                print(f"[SUCESSO] Extração de {id_site} concluída.\n")
            except subprocess.CalledProcessError as e:
                print(f"[ERRO] Falha ao raspar {id_site}. O robô parou com erro: {e}\n")
            
            time.sleep(2)
        else:
            print(f"--- Site [{id_site.upper()}] está em dia. Próxima extração em breve.")

    # FASE 2: HIGIENIZAÇÃO E SALVAMENTO DO ESTADO
    if houve_atualizacao:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
        print("\n[OK] scrapers_config.json atualizado com as novas datas.")

        print("\n" + "="*50)
        print(" INICIANDO HIGIENIZAÇÃO (Clean Data)")
        print("="*50)
        if os.path.exists(clean_script_path):
            try:
                subprocess.run([sys.executable, clean_script_path], check=True)
                print("\n[SUCESSO] Dados brutos higienizados!")
            except subprocess.CalledProcessError as e:
                print(f"[ERRO] O script clean_data.py falhou: {e}")
        else:
            print(f"[AVISO] Script {clean_script_path} não encontrado.")

        # FASE 3: VETORIZAÇÃO (Build Vector)
        print("\n" + "="*50)
        print(" INICIANDO VETORIZAÇÃO (Build Vector)")
        print("="*50)
        if os.path.exists(build_vector_script):
            try:
                subprocess.run([sys.executable, build_vector_script], check=True)
                print("\n[SUCESSO TOTAL] Banco de vetores atualizado!")
            except subprocess.CalledProcessError as e:
                print(f"[ERRO] O script build_vector.py falhou: {e}")
        else:
            print(f"[AVISO] Script {build_vector_script} não encontrado.")
    else:
        print("\n[INFO] Nenhuma atualização necessária hoje. Sistema inativo.")

if __name__ == "__main__":
    rodar_pipeline()