import scrapy

class ChatbotContentItem(scrapy.Item):
    url = scrapy.Field()
    titulo = scrapy.Field()
    texto_limpo = scrapy.Field()