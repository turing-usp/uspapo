import json
import subprocess
import os

ARQUIVO_CONFIG = "scrapers_config.json"
PASTA_RAW = "../data/raw"

def rodar_tudo():
    os.makedirs(PASTA_RAW, exist_ok=True)

    with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
        sites = json.load(f)

    # A Mágica da Organização: 
    # Ordena primeiro pela 'prioridade' (crescente: 1, 2, 3...) 
    # e em caso de empate, ordena alfabeticamente pelo 'id_site'
    sites.sort(key=lambda x: (x["prioridade"], x["id_site"]))

    print(f"Fila de execução organizada para {len(sites)} sites:")
    for s in sites:
        print(f" - [{s['prioridade']}] {s['id_site']} ({s['frequencia']})")

    for site in sites:
        id_site = site["id_site"]
        caminho_saida = os.path.join(PASTA_RAW, f"{id_site}.json")
        
        if os.path.exists(caminho_saida):
            os.remove(caminho_saida)

        print(f"\n---> Raspando: {site['start_url']} (Prioridade {site['prioridade']})")
        
        comando = [
            "scrapy", "runspider", "spider_generica.py",
            "-a", f"start_url={site['start_url']}",
            "-a", f"allowed_domain={site['allowed_domain']}",
            "-a", f"seletor_menu={site['seletor_menu']}",
            "-o", caminho_saida
        ]
        
        subprocess.run(comando)
        print(f"[OK] Dados de {id_site} salvos.")

if __name__ == "__main__":
    rodar_tudo()