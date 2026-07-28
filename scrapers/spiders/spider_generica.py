import scrapy
from scrapers.utils import ExtratorConteudo
from scrapers.items import ChatbotContentItem  

class UspSpiderGenerica(scrapy.Spider):
    name = "usp_spider"
    
    # O __init__ recebe os parâmetros mágicos do nosso configurador
    def __init__(self, start_url='', allowed_domain='', seletor_menu='', *args, **kwargs):
        super(UspSpiderGenerica, self).__init__(*args, **kwargs)
        
        self.start_urls = [start_url]
        self.allowed_domains = [allowed_domain]
        self.seletor_menu = seletor_menu

    def parse(self, response):
        # Usa o seletor dinâmico injetado
        links_menu = response.css(self.seletor_menu).getall()
        
        links_validos = [link for link in links_menu if link and not link.startswith('#')]
        
        self.logger.info(f"Navbar mapeada! {len(links_validos)} links encontrados usando o seletor: {self.seletor_menu}")
        
        for link in links_validos:
            yield response.follow(link, callback=self.parse_conteudo)

    def parse_conteudo(self, response):
        if response.url.lower().endswith('.pdf'):
            dados = ExtratorConteudo.extrair_pdf(response)
        else:
            dados = ExtratorConteudo.extrair_html(response)
            
        item = ChatbotContentItem()
        item['url'] = response.url
        item['titulo'] = dados['titulo']
        item['texto_limpo'] = dados['texto_limpo']
        
        yield item