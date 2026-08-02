import json
import os
import re
import glob

def carregar_regras():
    """Carrega o dicionário de regras de lixo do arquivo externo."""
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_regras = os.path.join(diretorio_atual, "regras_ruido.json")
    
    try:
        with open(caminho_regras, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("[ALERTA] Arquivo 'regras_ruido.json' não encontrado. Usando apenas limpeza básica.")
        return {}

def limpeza_universal(texto: str) -> str:
    """Aplica formatação básica de HTML e espaçamento."""
    if not texto:
        return ""
    
    texto = re.sub(r'<script.*?>.*?</script>', '', texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r'<style.*?>.*?</style>', '', texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    
    return texto.strip()

def aplicar_regras_regex(texto: str, url: str, regras: dict) -> str:
    """Aplica as regras do JSON dependendo do domínio da página."""
    texto_limpo = texto
    padroes_aplicar = regras.get("universal", []).copy()
    
    for dominio, padroes_dominio in regras.items():
        if dominio != "universal" and dominio in url:
            padroes_aplicar.extend(padroes_dominio)
            break
            
    for padrao in padroes_aplicar:
        texto_limpo = re.sub(padrao, "", texto_limpo, flags=re.IGNORECASE | re.DOTALL)
        
    return texto_limpo

def executar():
    # Caminho absoluto da raiz do projeto (uspapo)
    diretorio_script = os.path.dirname(os.path.abspath(__file__))
    raiz_projeto = os.path.abspath(os.path.join(diretorio_script, ".."))
    
    pasta_raw = os.path.join(raiz_projeto, "data", "raw")
    pasta_processed = os.path.join(raiz_projeto, "data", "processed")
    
    os.makedirs(pasta_processed, exist_ok=True)
    arquivos_raw = glob.glob(os.path.join(pasta_raw, "**", "*.json"), recursive=True)
    
    if not arquivos_raw:
        print(f"[AVISO] Nenhum arquivo JSON encontrado em {pasta_raw}.")
        return

    regras_ruido = carregar_regras()
    print(f"-> Analisando {len(arquivos_raw)} arquivo(s) raw para limpeza...")

    for caminho_raw in arquivos_raw:
        nome_arquivo = os.path.basename(caminho_raw)
        
        # Converte poli_raw.json ou poli.json em poli_limpo.json
        nome_base = os.path.splitext(nome_arquivo)[0].replace("_raw", "").replace("_data", "")
        nome_saida = f"{nome_base}_limpo.json"
        
        caminho_relativo = os.path.relpath(caminho_raw, pasta_raw)
        pasta_relativa = os.path.dirname(caminho_relativo)
        
        pasta_destino = os.path.join(pasta_processed, pasta_relativa)
        os.makedirs(pasta_destino, exist_ok=True) 
        
        caminho_saida = os.path.join(pasta_destino, nome_saida)
        
        print(f"   [LIMPANDO] Processando '{nome_arquivo}' -> '{nome_saida}'...")
        
        try:
            with open(caminho_raw, 'r', encoding='utf-8') as f:
                dados_brutos = json.load(f)
                
            dados_limpos = []
            paginas_descartadas = 0
            
            for doc in dados_brutos:
                url_documento = doc.get("url", "")
                texto_original = doc.get("texto_limpo", doc.get("clean_text", ""))
                
                texto_tratado = limpeza_universal(texto_original)
                texto_tratado = aplicar_regras_regex(texto_tratado, url_documento, regras_ruido)
                texto_tratado = limpeza_universal(texto_tratado)
                
                if len(texto_tratado) > 50:
                    dados_limpos.append({
                        "url": url_documento,
                        "titulo": doc.get("titulo", doc.get("title", "")).strip(),
                        "texto_limpo": texto_tratado
                    })
                else:
                    paginas_descartadas += 1
                    
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                json.dump(dados_limpos, f, ensure_ascii=False, indent=4)
                
            print(f"      Sucesso: {len(dados_limpos)} pág. limpas | {paginas_descartadas} pág. descartadas.")
            
        except Exception as e:
            print(f"      [ERRO] Falha ao processar '{nome_arquivo}': {e}")

# Execução obrigatória ao ser disparado via terminal ou subprocess
if __name__ == "__main__":
    executar()