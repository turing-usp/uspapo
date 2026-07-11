import scrapy
from scrapers.utils import ExtratorConteudo
from scrapers.items import ChatbotContentItem  

class IqNavbarSpider(scrapy.Spider):
    name = "politudo"
    
    # Domínios permitidos para o robô não sair da USP se houver links externos no menu
    allowed_domains = ["poli.usp.br"]
    

    start_urls = ["https://www.poli.usp.br/en/"]

    def parse(self, response):
        # 1. Mapeia todos os links contidos na navbar que você inspecionou
        links_menu = response.css('ul#menu-1-7a1b5c55 a::attr(href)').getall()
        
        # Filtra links vazios ou âncoras comuns (#)
        links_validos = [link for link in links_menu if link and not link.startswith('#')]
        
        self.logger.info(f"Navbar mapeada com sucesso! {len(links_validos)} links encontrados.")
        
        # 2. Segue cada um dos links encontrados no menu e joga para o processador de conteúdo
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