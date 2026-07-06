import scrapy
import json
from pathlib import Path

class ChatbotContentItem(scrapy.Item):
    url = scrapy.Field()
    titulo = scrapy.Field()
    texto_limpo = scrapy.Field()

class IqContentSpider(scrapy.Spider):
    name = "iq_content"
    
    # 1. Definimos o domínio permitido para o Scrapy operar de forma segura
    allowed_domains = ["iq.usp.br", "www.iq.usp.br", "labiq.iq.usp.br", "lem.iq.usp.br", "memoria.iq.usp.br", "ca.iq.usp.br"]

    def start_requests(self):
        # Resolve o arquivo de links a partir do módulo do spider, não do cwd.
        json_path = Path(__file__).resolve().parents[1] / "data" / "links_novosiq.json"
        
        if not json_path.exists():
            self.logger.error(f"Arquivo de links não encontrado em: {json_path.absolute()}")
            return

        with open(json_path, "r", encoding="utf-8") as f:
            dados = json.load(f)
            
        self.logger.info(f"Carregando {len(dados)} links do arquivo JSON para processamento via Cache.")
        
        # Iteramos pelos links coletados e geramos as requisições
        for item in dados:
            url_alvo = item.get('url')
            if url_alvo:
                # Cada URL vai para o método 'parse_conteudo'
                yield scrapy.Request(url=url_alvo, callback=self.parse_conteudo)

    def parse_conteudo(self, response):
        item = ChatbotContentItem()
        item['url'] = response.url
        
        # Extrai o título principal h1 (comum em páginas internas) ou o title da aba se não houver h1
        titulo = response.css('h1::text').get()
        if not titulo:
            titulo = response.css('title::text').get(default='Sem Título')
        item['titulo'] = titulo.strip()
        
        # Criamos um seletor focado no corpo da página para aplicar a limpeza por exclusão (.drop())
        corpo = response.css('body')
        
        # Lista de elementos comuns de ruído que costumam poluir a base de conhecimento do chatbot
        elementos_para_remover = [
            'nav', 'footer', 'header', 'button', 'script', 'style', 'form',
            '.menu', '.sidebar', '#header', '#footer', '.breadcrumb', 
            '.redes-sociais', '.compartilhar', '.tags'
        ]
        
        # Varre o HTML limpando fisicamente as tags inúteis
        for seletor in elementos_para_remover:
            for elemento in corpo.css(seletor):
                elemento.drop()
        
        # Agora coletamos os textos estruturados que sobraram (parágrafos, listas e subtítulos)
        tags_de_texto = 'p::text, p *::text, li::text, li *::text, h2::text, h3::text, h4::text'
        textos_brutos = corpo.css(tags_de_texto).getall()
        
        # Limpamos espaços extras em branco e ignoramos linhas que ficaram vazias
        linhas_limpas = [texto.strip() for texto in textos_brutos if texto.strip()]
        
        # Une todas as linhas em um único parágrafo contínuo ideal para LLMs/Embeddings
        item['texto_limpo'] = " ".join(linhas_limpas)
        
        yield item