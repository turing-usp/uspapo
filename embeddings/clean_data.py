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
    
    # 1. Aplica as regras universais (que valem para todos os sites)
    padroes_aplicar = regras.get("universal", []).copy()
    
    # 2. Descobre de qual instituto é a URL e adiciona as regras específicas
    for dominio, padroes_dominio in regras.items():
        if dominio != "universal" and dominio in url:
            padroes_aplicar.extend(padroes_dominio)
            break # Achou o domínio, não precisa testar os outros
            
    # 3. Executa a faxina com as regras combinadas
    for padrao in padroes_aplicar:
        texto_limpo = re.sub(padrao, "", texto_limpo, flags=re.IGNORECASE | re.DOTALL)
        
    return texto_limpo

def executar():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    pasta_raw = os.path.join(diretorio_atual, "..", "data", "raw")
    pasta_processed = os.path.join(diretorio_atual, "..", "data", "processed")
    
    os.makedirs(pasta_processed, exist_ok=True)
    arquivos_raw = glob.glob(os.path.join(pasta_raw, "**", "*.json"), recursive=True)
    
    if not arquivos_raw:
        print(f"[AVISO] Nenhum arquivo JSON encontrado em {pasta_raw}.")
        return

    # Carrega as regras na memória uma única vez
    regras_ruido = carregar_regras()

    print(f"-> Analisando {len(arquivos_raw)} arquivos raw para limpeza...")

    for caminho_raw in arquivos_raw:
        nome_arquivo = os.path.basename(caminho_raw)
        nome_base = os.path.splitext(nome_arquivo)[0] 
        nome_saida = f"{nome_base}_limpo.json"
        
        caminho_relativo = os.path.relpath(caminho_raw, pasta_raw)
        pasta_relativa = os.path.dirname(caminho_relativo)
        
        pasta_destino = os.path.join(pasta_processed, pasta_relativa)
        os.makedirs(pasta_destino, exist_ok=True) 
        
        caminho_saida = os.path.join(pasta_destino, nome_saida)
        
        precisa_limpar = False
        if not os.path.exists(caminho_saida):
            precisa_limpar = True
        elif os.path.getmtime(caminho_raw) > os.path.getmtime(caminho_saida):
            precisa_limpar = True
            
        if not precisa_limpar:
            print(f"   [PULADO] '{nome_arquivo}' já está limpo e atualizado.")
            continue
            
        print(f"   [LIMPANDO] Processando '{nome_arquivo}' -> '{nome_saida}'...")
        
        try:
            with open(caminho_raw, 'r', encoding='utf-8') as f:
                dados_brutos = json.load(f)
                
            dados_limpos = []
            paginas_descartadas = 0
            
            for doc in dados_brutos:
                url_documento = doc.get("url", "")
                
                # A CORREÇÃO DO BUG: tenta "texto_limpo", se não achar tenta "clean_text"
                texto_original = doc.get("texto_limpo", doc.get("clean_text", ""))
                
                # Passa pela esteira de limpeza
                texto_tratado = limpeza_universal(texto_original)
                texto_tratado = aplicar_regras_regex(texto_tratado, url_documento, regras_ruido)
                texto_tratado = limpeza_universal(texto_tratado) # Passa de novo para tirar quebras de linha que sobraram
                
                if len(texto_tratado) > 50:
                    dados_limpos.append({
                        "url": url_documento,
                        # Também previne o bug com o título
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

if __name__ == "__main__":
    executar()