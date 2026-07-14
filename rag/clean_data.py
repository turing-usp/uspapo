import json
import re

def limpar_texto_poli(texto: str) -> str:
    if not texto:
        return ""

    # 1. Os Padrões de Ruído (Regex)
    # Aqui mapeamos exatamente os textos inúteis que se repetem no seu JSON
    padroes_ruido = [
        # 1. Rodapé Institucional e Endereço Padrão
        r"Localização\s*Avenida Prof\. Luciano Gualberto.*?Formando Engenheiros e Líderes\s*© \d{4} Escola Politécnica da USP\s*Menu Acesso Rápido",
        r"CEP – 05508-010 – São Paulo – SP",
        
        # 2. Contatos Genéricos e Repetitivos (Comunicação/Imprensa)
        r"Contato\s*Entre em contato conosco pelo e-mail comunicacao\.poli@usp\.br",
        r"MENU AVISOS\s*Para divulgar, escreva para:\s*comunicacao\.poli@usp\.br",
        r"Para divulgar, escreva para:\s*comunicacao\.poli@usp\.br",
        r"Equipe de imprensa da Poli-USP\. Dúvidas e sugestões, entre em contato\.",
        r"Acesse a página com os vídeos produzidos na Poli-USP:\s*Clique aqui\.",
        r"A Escola Politécnica é composta por mais de 8 mil pessoas.*?Acesse a página com os vídeos produzidos na Poli-USP: Clique aqui\.",
        
        # 3. Redes Sociais
        r"Acompanhe a Poli nas redes sociais!",
        r"Acesse abaixo as redes sociais da Escola Politécnica da USP.*?Banco de imagens e fotos:.*?(?=\n|$)",
        
        # 4. Navegação Morta (Sobras de Botões e Menus)
        r"Retornar à página principal\.",
        r"Clique para acessar\.",
        r"Acesse no link\s*\.",
        r"VEJA TAMBÉM",
        r"\bMENU\b", # Apenas a palavra MENU isolada
        r"Acesso Rápido",
        
        # 5. Metadados inúteis para o Chatbot
        r"Última atualização em \d{2}/\d{2}/\d{4}"
    ]
    
    texto_limpo = texto
    
    # Aplica a remoção de todos os padrões
    for padrao in padroes_ruido:
        # re.IGNORECASE ignora maiúsculas/minúsculas
        # re.DOTALL faz o regex entender quebras de linha no meio da sujeira
        texto_limpo = re.sub(padrao, "", texto_limpo, flags=re.IGNORECASE | re.DOTALL)

    # 2. Limpeza de Espaços e Quebras de Linha
    # O scraper às vezes junta palavras ou deixa espaços gigantes. Vamos arrumar.
    
    # Transforma 3 ou mais quebras de linha em apenas 2 (para separar parágrafos)
    texto_limpo = re.sub(r'\n{3,}', '\n\n', texto_limpo)
    
    # Transforma múltiplos espaços em branco ou tabs em um único espaço
    texto_limpo = re.sub(r'[ \t]+', ' ', texto_limpo)

    # 3. Aparar as arestas
    # Remove espaços vazios no começo e no final do texto
    texto_limpo = texto_limpo.strip()

    return texto_limpo

def executar():
    # Ajuste o caminho se o seu arquivo estiver em outro lugar
    caminho_entrada = "../data/raw/poliscrap.json"
    caminho_saida = "../data/processed/poliscrap_limpo.json"
    
    try:
        with open(caminho_entrada, 'r', encoding='utf-8') as f:
            dados_brutos = json.load(f)
            
        print(f"-> Lidos {len(dados_brutos)} documentos. Iniciando a faxina...")
        
        dados_limpos = []
        paginas_descartadas = 0
        
        for doc in dados_brutos:
            texto_original = doc.get("texto_limpo", "")
            texto_tratado = limpar_texto_poli(texto_original)
            
            # Controle de Qualidade: 
            # Se a página limpada ficou com menos de 50 caracteres, ela provavelmente 
            # era só um menu ou uma página vazia. Nós a descartamos.
            if len(texto_tratado) > 50:
                dados_limpos.append({
                    "url": doc.get("url", ""),
                    "titulo": doc.get("titulo", ""),
                    "texto_limpo": texto_tratado
                })
            else:
                paginas_descartadas += 1
                
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            json.dump(dados_limpos, f, ensure_ascii=False, indent=4)
            
        print(f"-> Sucesso! {len(dados_limpos)} documentos limpos e prontos para vetorização.")
        if paginas_descartadas > 0:
            print(f"-> {paginas_descartadas} páginas foram descartadas por não terem conteúdo útil.")
            
    except FileNotFoundError:
        print(f"Erro: O arquivo '{caminho_entrada}' não foi encontrado. Verifique o caminho.")

if __name__ == "__main__":
    executar()