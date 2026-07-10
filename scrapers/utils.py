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
        """Remove ruídos (nav, footer, etc.) e extrai texto limpo de um HTML."""
        resultado = {"titulo": "", "texto_limpo": ""}
        
        # 1. Extrai Título
        titulo = response.css('h1::text').get()
        if not titulo:
            titulo = response.css('title::text').get(default='Sem Título')
        resultado["titulo"] = titulo.strip()
        
        # 2. Limpeza do Corpo
        corpo = response.css('body')
        elementos_para_remover = [
            'nav', 'footer', 'header', 'button', 'script', 'style', 'form',
            '.menu', '.sidebar', '#header', '#footer', '.breadcrumb', 
            '.redes-sociais', '.compartilhar', '.tags', '.subfooter-area', '#subfooter-inside'
        ]
        
        # Cria uma cópia seletora para não corromper o response original global
        for seletor in elementos_para_remover:
            for elemento in corpo.css(seletor):
                elemento.drop()
        
        # 3. Coleta de Texto
        # Primeiro, tenta pegar o bloco de conteúdo principal para evitar pegar as divs do layout inteiro
        conteudo_principal = corpo.css('.field-items')

        if conteudo_principal:
            # Se existir a div do conteúdo principal, pega TODO texto que estiver lá dentro
            textos_brutos = conteudo_principal.css('::text').getall()
        else:
            # Caso seja uma página com estrutura diferente, usa o fallback das tags comuns
            tags_de_texto = 'p::text, p *::text, li::text, li *::text, h2::text, h3::text, h4::text, big::text, big *::text'
            textos_brutos = corpo.css(tags_de_texto).getall()

        # Limpeza rigorosa: remove espaços, quebras de linha (\n), abas (\t) e o caractere invisível \xa0 (&nbsp;)
        linhas_limpas = []
        for texto in textos_brutos:
            texto_limpo = texto.replace('\xa0', ' ').strip()
            if texto_limpo: # Só adiciona se não for vazio
                linhas_limpas.append(texto_limpo)

        resultado["texto_limpo"] = " ".join(linhas_limpas)
        return resultado