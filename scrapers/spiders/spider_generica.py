import scrapy
from scrapers.utils import ExtratorConteudo
from scrapers.items import ChatbotContentItem  

class UspSpiderGenerica(scrapy.Spider):
    name = "usp_spider"
    
    def __init__(self, start_url='', allowed_domain='', seletores_alvo='', *args, **kwargs):
        super(UspSpiderGenerica, self).__init__(*args, **kwargs)
        
        self.start_urls = [start_url]
        self.allowed_domains = [allowed_domain]
        # Transforma a string unida "seletor1|||seletor2" de volta em uma lista iterável
        self.seletores = seletores_alvo.split('|||')

    def parse(self, response):
        todos_links_encontrados = []
        
        # 1. Varre todos os pontos de interesse que você mapeou para este site
        for seletor in self.seletores:
            links_neste_seletor = response.css(seletor).getall()
            todos_links_encontrados.extend(links_neste_seletor)
        
        # 2. Limpeza bruta e Deduplicação Instantânea
        links_limpos = [link for link in todos_links_encontrados if link and not link.startswith('#')]
        links_unicos = list(set(links_limpos)) # O set() mata qualquer duplicata
        
        self.logger.info(f"Mapeamento concluído! {len(links_unicos)} links únicos encontrados nos alvos.")
        
        # 3. Segue cada link único mapeado
        for link in links_unicos:
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