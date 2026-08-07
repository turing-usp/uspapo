"""Fachada da extração, mantida pelo nome que os spiders já usam.

A lógica toda mora em `scrapers/extracao.py`, que não depende de scrapy e por
isso é testável sem subir um crawler. Aqui fica só o nome antigo, para os
spiders continuarem chamando `ExtratorConteudo.extrair_html(response)`.
"""

import scrapy

from scrapers import extracao


class ExtratorConteudo:
    @staticmethod
    def extrair_pdf(response: scrapy.http.Response) -> dict:
        """Texto e título de um PDF, já em parágrafos."""
        return extracao.extrair_pdf(response)

    @staticmethod
    def extrair_html(response: scrapy.http.Response) -> dict:
        """Texto e título de uma página, um parágrafo por bloco semântico."""
        return extracao.extrair_html(response)

    @staticmethod
    def eh_pdf(response: scrapy.http.Response) -> bool:
        return extracao.eh_pdf(response)
