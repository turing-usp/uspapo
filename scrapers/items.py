# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy

class ChatbotContentItem(scrapy.Item):
    url = scrapy.Field()
    titulo = scrapy.Field()
    texto_limpo = scrapy.Field()