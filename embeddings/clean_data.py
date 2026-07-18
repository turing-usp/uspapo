import json
import os
import re
import glob

def limpeza_universal(texto: str) -> str:
    """Aplica formatação básica sem destruir os parágrafos do Scrapy."""
    if not texto:
        return ""
    
    # Remove tags residuais que o Scrapy possa ter deixado
    texto = re.sub(r'<script.*?>.*?</script>', '', texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r'<style.*?>.*?</style>', '', texto, flags=re.IGNORECASE | re.DOTALL)
    
    # Reduz 3 ou mais quebras de linha para apenas 2 (mantém a lógica de fatiamento intacta)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    
    # Remove espaços duplos horizontais, preservando as quebras de linha
    texto = re.sub(r'[ \t]+', ' ', texto)
    
    return texto.strip()

def limpeza_especifica_poli(texto: str) -> str:
    """As suas regras blindadas contra o lixo do domínio poli.usp.br."""
    padroes_ruido = [
        r"Localização\s*Avenida Prof\. Luciano Gualberto.*?Formando Engenheiros e Líderes\s*© \d{4} Escola Politécnica da USP\s*Menu Acesso Rápido",
        r"CEP – 05508-010 – São Paulo – SP",
        r"Contato\s*Entre em contato conosco pelo e-mail comunicacao\.poli@usp\.br",
        r"MENU AVISOS\s*Para divulgar, escreva para:\s*comunicacao\.poli@usp\.br",
        r"Para divulgar, escreva para:\s*comunicacao\.poli@usp\.br",
        r"Equipe de imprensa da Poli-USP.*?Dúvidas e sugestões, entre em contato\.",
        r"Acesse a página com os vídeos produzidos na Poli-USP:\s*Clique aqui\.",
        r"A Escola Politécnica é composta por mais de 8 mil pessoas.*?Acesse a página com os vídeos produzidos na Poli-USP: Clique aqui\.",
        r"Acompanhe a Poli nas redes sociais!",
        r"Acesse abaixo as redes sociais da Escola Politécnica da USP.*?Banco de imagens e fotos:.*?(?=\n|$)",
        r"Retornar à página principal\.",
        r"Clique para acessar\.",
        r"Acesse no link\s*\.",
        r"VEJA TAMBÉM",
        r"\bMENU\b",
        r"Acesso Rápido",
        r"Última atualização em \d{2}/\d{2}/\d{4}"
    ]
    
    texto_limpo = texto
    for padrao in padroes_ruido:
        texto_limpo = re.sub(padrao, "", texto_limpo, flags=re.IGNORECASE | re.DOTALL)
        
    return texto_limpo

def executar():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    pasta_raw = os.path.join(diretorio_atual, "..", "data", "raw")
    pasta_processed = os.path.join(diretorio_atual, "..", "data", "processed")
    
    # Garante que a pasta processed exista antes de checarmos os arquivos nela
    os.makedirs(pasta_processed, exist_ok=True)
    
    # Pega todos os arquivos .json na pasta raw
    arquivos_raw = glob.glob(os.path.join(pasta_raw, "**", "*.json"), recursive=True)
    
    if not arquivos_raw:
        print(f"[AVISO] Nenhum arquivo JSON encontrado em {pasta_raw}.")
        return

    print(f"-> Analisando {len(arquivos_raw)} arquivos raw para limpeza...")

    for caminho_raw in arquivos_raw:
        nome_arquivo = os.path.basename(caminho_raw)
        nome_base = os.path.splitext(nome_arquivo)[0] 
        nome_saida = f"{nome_base}_limpo.json"
        
        # 2. A MÁGICA DO ESPELHAMENTO DE PASTAS
        # Descobre o caminho relativo (Ex: "Poli\poliscrap.json")
        caminho_relativo = os.path.relpath(caminho_raw, pasta_raw)
        # Pega só o nome da pasta (Ex: "Poli")
        pasta_relativa = os.path.dirname(caminho_relativo)
        
        # Cria o caminho de destino exato (Ex: "../data/processed/Poli")
        pasta_destino = os.path.join(pasta_processed, pasta_relativa)
        os.makedirs(pasta_destino, exist_ok=True) # Garante que a pasta exista!
        
        # Monta o caminho final do arquivo
        caminho_saida = os.path.join(pasta_destino, nome_saida)
        
        # Lógica inteligente de Update:
        # 1. Se o arquivo limpo não existe OR
        # 2. Se o arquivo raw foi modificado DEPOIS do arquivo limpo
        precisa_limpar = False
        if not os.path.exists(caminho_saida):
            precisa_limpar = True
        elif os.path.getmtime(caminho_raw) > os.path.getmtime(caminho_saida):
            precisa_limpar = True
            
        if not precisa_limpar:
            print(f"   [PULADO] '{nome_arquivo}' já está limpo e atualizado.")
            continue
            
        # Se chegou aqui, precisa processar!
        print(f"   [LIMPANDO] Processando '{nome_arquivo}' -> '{nome_saida}'...")
        
        try:
            with open(caminho_raw, 'r', encoding='utf-8') as f:
                dados_brutos = json.load(f)
                
            dados_limpos = []
            paginas_descartadas = 0
            
            for doc in dados_brutos:
                url_documento = doc.get("url", "")
                texto_original = doc.get("texto_limpo", "")
                
                texto_tratado = limpeza_universal(texto_original)
                
                if "poli.usp.br" in url_documento:
                    texto_tratado = limpeza_especifica_poli(texto_tratado)
                    
                texto_tratado = limpeza_universal(texto_tratado)
                
                if len(texto_tratado) > 50:
                    dados_limpos.append({
                        "url": url_documento,
                        "titulo": doc.get("titulo", "").strip(),
                        "texto_limpo": texto_tratado
                    })
                else:
                    paginas_descartadas += 1
                    
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                json.dump(dados_limpos, f, ensure_ascii=False, indent=4)
                
            print(f"      Sucesso: {len(dados_limpos)} pág. limpas | {paginas_descartadas} pág. descartadas.")
            
        except Exception as e:
            print(f"      [ERRO] Falha ao processar '{nome_arquivo}': {e}")

if __name__ == "__main__":
    executar()