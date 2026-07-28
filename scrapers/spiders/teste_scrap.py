import scrapy
from scrapers.utils import ExtratorConteudo
from scrapers.items import ChatbotContentItem  

class IqNavbarSpider(scrapy.Spider):
    name = "teste"
    
    # Domínios permitidos para o robô não sair da USP se houver links externos no menu
    allowed_domains = ["iq.usp.br", "www.iq.usp.br", "labiq.iq.usp.br", "lem.iq.usp.br", "memoria.iq.usp.br", "ca.iq.usp.br"]
    

    start_urls = ["https://www.iq.usp.br/portaliqusp/"]

    def parse(self, response):
        # 1. Mapeia todos os links contidos na navbar que você inspecionou
        links_menu = response.css('ul#superfish-1 a::attr(href)').getall()
        
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

        # 3. Varre o corpo do texto buscando links para PDFs anexados
        # Pega todos os links dentro do conteúdo principal
        links_da_pagina = response.css('.field-items a::attr(href)').getall()
        
        for link in links_da_pagina:
            if link and link.lower().endswith('.pdf'):
                # Transforma links relativos em absolutos e envia para processar o PDF
                url_absoluta = response.urljoin(link)
                self.logger.info(f"PDF encontrado no corpo da página: {url_absoluta}")
                yield scrapy.Request(url_absoluta, callback=self.parse_conteudo)