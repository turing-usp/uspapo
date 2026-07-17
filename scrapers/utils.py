import io
import scrapy
from pypdf import PdfReader  

class ExtratorConteudo:
    
    @staticmethod
    def extrair_pdf(response: scrapy.http.Response) -> dict:
        """Extrai texto bruto e título de um arquivo PDF."""
        resultado = {"titulo": "", "texto_limpo": ""}
        try:
            pdf_reader = PdfReader(io.BytesIO(response.body))
            texto_pdf = []
            for pagina in pdf_reader.pages:
                texto_pdf.append(pagina.extract_text())
            
            resultado["texto_limpo"] = "\n".join(texto_pdf).strip()
            resultado["titulo"] = (
                pdf_reader.metadata.title 
                if pdf_reader.metadata and pdf_reader.metadata.title 
                else response.url.split('/')[-1]
            )
        except Exception as e:
            resultado["texto_limpo"] = ""
            resultado["titulo"] = response.url.split('/')[-1]
        return resultado

    @staticmethod
    def extrair_html(response: scrapy.http.Response) -> dict:
        """Remove ruídos e extrai texto limpo de um HTML respeitando parágrafos."""
        resultado = {"titulo": "", "texto_limpo": ""}
        
        # 1. Extrai Título
        titulo = response.css('h1::text').get()
        if not titulo:
            titulo = response.css('title::text').get(default='Sem Título')
        resultado["titulo"] = titulo.strip()
        
        # 2. Limpeza do Corpo (Removemos o lixo estrutural)
        corpo = response.css('body')
        elementos_para_remover = [
            'nav', 'footer', 'header', 'button', 'script', 'style', 'form',
            '.menu', '.sidebar', '#header', '#footer', '.breadcrumb', 
            '.redes-sociais', '.compartilhar', '.tags', '.subfooter-area', '#subfooter-inside'
        ]
        
        for seletor in elementos_para_remover:
            for elemento in corpo.css(seletor):
                elemento.drop()
        
        # 3. Coleta de Texto Inteligente (Por Blocos)
        # Em vez de pegar '::text' soltos, focamos nas tags que formam blocos reais
        tags_de_bloco = corpo.css('p, li, h1, h2, h3, h4, h5, h6, .field-items div')
        
        linhas_limpas = []
        for tag in tags_de_bloco:
            # Pega todo o texto DENTRO deste parágrafo específico (incluindo links e negritos)
            # e junta com um espaço simples para não quebrar frases
            textos_internos = tag.css('*::text, ::text').getall()
            texto_do_paragrafo = "".join(textos_internos).replace('\xa0', ' ')
            
            # Limpa espaços duplos dentro do parágrafo
            import re
            texto_do_paragrafo = re.sub(r'\s+', ' ', texto_do_paragrafo).strip()
            
            # Só adiciona se sobrou algum texto útil no bloco
            if texto_do_paragrafo:
                linhas_limpas.append(texto_do_paragrafo)

        # Agora sim, separamos os parágrafos completos e perfeitos com \n\n
        resultado["texto_limpo"] = "\n\n".join(linhas_limpas)
        return resultado