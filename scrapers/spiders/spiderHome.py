import scrapy
from scrapy.spiders import SitemapSpider
from bs4 import BeautifulSoup


class CompleteScraper(SitemapSpider):

    name = "complete_scraper"

    allowed_domains = [
        "www5.usp.br"
    ]

    # Coloque aqui o sitemap principal do site
    sitemap_urls = [
        "https://www5.usp.br/sitemap.xml"
    ]

    # Faz o parse de qualquer URL encontrada no sitemap
    sitemap_rules = [
        (r'.*', 'parse_page'),
    ]

    # Conjunto utilizado para não visitar a mesma URL duas vezes
    visited_urls = set()


    def parse_page(self, response):

        # Evita visitar URLs repetidas
        if response.url in self.visited_urls:
            return

        self.visited_urls.add(response.url)

        # --------------------------
        # EXTRAÇÃO DO CONTEÚDO
        # --------------------------

        # Remove scripts e estilos
        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # Pega todo o texto da página
        text = soup.get_text(separator="\n", strip=True)

        yield {
            "url": response.url,
            "content": text
        }

        # --------------------------
        # ENCONTRA TODOS OS LINKS
        # --------------------------

        links = response.css("a::attr(href)").getall()

        for link in links:

            # Converte links relativos em absolutos
            absolute_link = response.urljoin(link)

    # Verifica se o link pertence ao domínio do site
    # e se ainda não foi visitado
            if (
                self.allowed_domains[0] in absolute_link
                and absolute_link not in self.visited_urls
            ):

                yield response.follow(
                    absolute_link,
                    callback=self.parse_page
                )