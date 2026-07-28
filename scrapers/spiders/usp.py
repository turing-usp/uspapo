import scrapy
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor

class LinkItem(scrapy.Item):
    url = scrapy.Field()

class uspSpider(CrawlSpider):
    name = "usp"
    
    allowed_domains = ["www5.usp.br"]
    
    # 2. O ponto de partida do mapeamento
    start_urls = ["https://www5.usp.br/"]

    # 3. As regras de navegação do robô
    rules = (
        Rule(
            LinkExtractor(
                restrict_css='main-navigation',
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