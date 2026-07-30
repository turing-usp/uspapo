import json
import subprocess
import os

ARQUIVO_CONFIG = "scrapers_config.json"
PASTA_RAW = "../data/raw"

def rodar_tudo():
    os.makedirs(PASTA_RAW, exist_ok=True)

    with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
        sites = json.load(f)

    # Ordena primeiro pela 'prioridade' e em caso de empate, alfabeticamente pelo 'id_site'
    # Usa get("prioridade", 99) para jogar pro final da fila caso não haja prioridade definida
    sites.sort(key=lambda x: (x.get("prioridade", 99), x["id_site"]))

    print(f"Fila de execução organizada para {len(sites)} sites:")
    for s in sites:
        print(f" - [{s.get('prioridade', '-')}] {s['id_site']} ({s.get('frequencia', '-')})")

    for site in sites:
        id_site = site["id_site"]
        caminho_saida = os.path.join(PASTA_RAW, f"{id_site}.json")
        
        if os.path.exists(caminho_saida):
            os.remove(caminho_saida)

        print(f"\n---> Raspando: {site['start_url']}")
        
        # A Mágica de Empacotamento: Transforma a lista ["alvo1", "alvo2"] do JSON em "alvo1|||alvo2"
        seletores_unidos = "|||".join(site['seletores_alvo'])
        
        comando = [
            "scrapy", "runspider", "spider_generica.py",
            "-a", f"start_url={site['start_url']}",
            "-a", f"allowed_domain={site['allowed_domain']}",
            "-a", f"seletores_alvo={seletores_unidos}",
            "-o", caminho_saida
        ]
        
        subprocess.run(comando)
        print(f"[OK] Dados de {id_site} salvos.")

if __name__ == "__main__":
    rodar_tudo()