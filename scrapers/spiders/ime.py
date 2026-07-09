import scrapy
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor

class ImeContentItem(scrapy.Item):
    url = scrapy.Field()
    title = scrapy.Field()
    clean_text = scrapy.Field()

class ImeSpider(CrawlSpider):
    name = "ime"
    
    allowed_domains = ["ime.usp.br", "www.ime.usp.br"]
    
    start_urls = ["https://www.ime.usp.br/"]

    # Configurações específicas para este spider para mitigar bloqueios
    custom_settings = {
        'DOWNLOAD_DELAY': 3,  # Delay base de 3 segundos entre as requisições
        'RANDOMIZE_DOWNLOAD_DELAY': True,  # Adiciona uma aleatoriedade no delay (entre 1.5s e 4.5s)
        'AUTOTHROTTLE_ENABLED': True,  # Ativa o ajuste automático de velocidade
        'AUTOTHROTTLE_START_DELAY': 5,
        'AUTOTHROTTLE_MAX_DELAY': 60,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2, # Limita o número de requisições simultâneas
    }

    rules = (
        Rule(
            LinkExtractor(allow=(), unique=True), 
            callback="parse_page_content", 
            follow=True
        ),
    )

    def parse_page_content(self, response):
        """Processes each discovered page, extracting its main textual content."""
        item = ImeContentItem()
        item['url'] = response.url
        
        # Extract the main h1 title or the tab title if no h1 exists
        title = response.css('h1::text').get()
        if not title:
            title = response.css('title::text').get(default='No Title')
        item['title'] = title.strip()
        
        # Focus on the page body to apply exclusion cleanup
        body = response.css('body')
        
        # List of common noise elements to remove
        elements_to_remove = [
            'nav', 'footer', 'header', 'button', 'script', 'style', 'form',
            '.menu', '.sidebar', '#header', '#footer', '.breadcrumb', 
            '.redes-sociais', '.compartilhar', '.tags'
        ]
        
        # Physically drop useless tags
        for selector in elements_to_remove:
            for element in body.css(selector):
                element.drop()
        
        # Collect remaining structured texts (paragraphs, lists, and subtitles)
        text_tags = 'p::text, p *::text, li::text, li *::text, h2::text, h3::text, h4::text'
        raw_texts = body.css(text_tags).getall()
        
        # Clean extra whitespaces and ignore empty lines
        clean_lines = [text.strip() for text in raw_texts if text.strip()]
        
        # Join all lines into a single continuous paragraph
        item['clean_text'] = " ".join(clean_lines)
        
        yield item
