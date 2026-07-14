import scrapy
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor

class LinkItem(scrapy.Item):
    url = scrapy.Field()

class IqSpider(CrawlSpider):
    name = "iq"
    
    allowed_domains = ["iq.usp.br", "www.iq.usp.br", "labiq.iq.usp.br"]
    
    # 2. O ponto de partida do mapeamento
    start_urls = ["https://www.iq.usp.br/portaliqusp/?q=pt-br/graduacao/iniciacao-cientifica"]

    # 3. As regras de navegação do robô
    rules = (
        Rule(
            LinkExtractor(
                restrict_css='section.col-md-8',
                deny_extensions=[],  # Limpa o bloqueio padrão para capturar links de .pdf
                unique=True
            ),
            callback="parse_item",
            follow=False
        ),
    )

    def parse_item(self, response):
        """Este método é chamado para CADA página que o robô encontrar."""
        item = LinkItem()
        item['url'] = response.url
        yield item