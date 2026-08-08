"""O spider único, agora com freios.

O que ele era: `start_url` -> links casados por seletor CSS -> conteúdo. Dois
níveis, sem filtro de URL, sem teto de páginas, sem profundidade. Apontado para
um domínio invadido, ele seguiria obedientemente as 400 mil URLs de spam do
`iri.usp.br`.

O que ele é agora: a mesma ideia, mas com descoberta híbrida (sitemap ->
seletores -> links do domínio), teto rígido de páginas por site, filtro de URL
antes de cada requisição e um detector que aborta a rodada inteira se o domínio
parecer comprometido.

O contador de páginas é a peça que realmente protege. Filtro pode ter furo, o
detector precisa de amostra. O teto vale sempre.
"""

import json
import os

import scrapy
from scrapy.exceptions import CloseSpider

from scrapers import descoberta
from scrapers.filtros import DetectorAnomalia, parece_spam, url_permitida
from scrapers.items import ChatbotContentItem
from scrapers.utils import ExtratorConteudo

MAX_PAGINAS_PADRAO = 300
PROFUNDIDADE_PADRAO = 2
MIN_URLS_SITEMAP = 5

# Página com menos texto que isto não vira item. O número é o `CHUNK_MIN` do
# config_vetor: abaixo dele a página não consegue formar nem um chunk, e o
# `filtrar_chunks` a descartaria depois de qualquer forma — então guardá-la só
# gasta requisição, disco e teto de páginas.
#
# Sem esse corte o crawler contava como "página" a ficha de docente que só tem o
# nome (12 caracteres) e a tela de erro de um sistema de reserva de salas. No
# `fflch` isso era 137 das 205 páginas, e no `if`, 165 de 268 — a mediana do site
# caía para 27 e 95 caracteres, e a guarda de resultado do orquestrador
# (corretamente) recusava a extração inteira.
MIN_CHARS_PAGINA = 200


class UspSpiderGenerica(scrapy.Spider):
    name = "spider_generico"

    def __init__(self, config_id="", max_paginas=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        raiz = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        caminho = os.path.join(raiz, "scrapers_config.json")
        if not os.path.exists(caminho):
            raise FileNotFoundError(f"Configuração não encontrada em: {caminho}")

        with open(caminho, "r", encoding="utf-8") as f:
            configuracoes = json.load(f)

        config = next((c for c in configuracoes if c.get("id_site") == config_id), None)
        if config is None:
            # Antes isto era um AttributeError em `None.get('start_url')`, três
            # linhas adiante, sem dizer qual era o id nem quais existiam.
            disponiveis = ", ".join(sorted(c.get("id_site", "?") for c in configuracoes))
            raise ValueError(
                f"id_site '{config_id}' não existe em scrapers_config.json.\n"
                f"Disponíveis: {disponiveis}"
            )

        self.config = config
        self.id_site = config_id

        self.start_urls = config.get("start_urls") or [config["start_url"]]
        self.allowed_domains = config.get("allowed_domains") or [config["allowed_domain"]]
        self.fontes = config.get("sources", [])
        self.modo = config.get("descoberta", "seletores")
        self.max_paginas = int(max_paginas or config.get("max_paginas", MAX_PAGINAS_PADRAO))
        self.profundidade_max = int(config.get("profundidade_max", PROFUNDIDADE_PADRAO))

        self.detector = DetectorAnomalia()
        self.paginas_extraidas = 0
        self.paginas_magras = 0
        self.urls_enfileiradas: set[str] = set()
        self.sitemaps_vistos: set[str] = set()
        self.urls_de_sitemap: list[str] = []
        self.tentou_sitemap = False

        # Requisições de sitemap/robots ainda no ar. Enquanto houver alguma, as
        # URLs ficam represadas: enfileirar assim que o primeiro sub-sitemap
        # chega faz o teto de páginas ser gasto por ordem de resposta da rede,
        # e a ordenação por relevância só vale dentro de cada lote. Represando,
        # o `ordenar_por_relevancia` decide sobre o sitemap inteiro — que é a
        # única forma de `max_paginas=300` pegar as 300 páginas certas.
        self.sitemaps_pendentes = 0

        self.logger.info(
            f"[{config_id}] modo={self.modo} teto={self.max_paginas} "
            f"profundidade={self.profundidade_max}"
        )

    # ─────────────────────────────────────────
    # Descoberta
    # ─────────────────────────────────────────
    async def start(self):
        """O scrapy 2.13 substituiu `start_requests` por esta corrotina."""
        for requisicao in self._requisicoes_iniciais():
            yield requisicao

    def _requisicoes_iniciais(self):
        if self.modo in ("sitemap", "hibrido"):
            base = self.start_urls[0]
            for candidato in self.config.get("sitemap_urls") or descoberta.candidatos_de_sitemap(base):
                yield self._pedir_sitemap(candidato, self.parse_sitemap)
            yield self._pedir_sitemap(base.rstrip("/") + "/robots.txt", self.parse_robots)

        if self.modo != "sitemap":
            for url in self.start_urls:
                yield scrapy.Request(url, callback=self.parse, dont_filter=True)

    def _pedir_sitemap(self, url: str, callback):
        self.sitemaps_pendentes += 1
        return scrapy.Request(
            url, callback=callback, errback=self.falhou_sitemap,
            dont_filter=True, priority=10,
        )

    def falhou_sitemap(self, falha):
        self.logger.debug(f"Sitemap indisponível: {falha.request.url}")
        yield from self._quitar_sitemap()

    def _quitar_sitemap(self):
        """Baixa o contador e, ao zerar, enfileira tudo de uma vez."""
        self.sitemaps_pendentes -= 1
        if self.sitemaps_pendentes > 0:
            return

        if self.urls_de_sitemap:
            yield from self._enfileirar(descoberta.ordenar_por_relevancia(self.urls_de_sitemap))
        elif self.modo == "sitemap":
            # Sem sitemap utilizável e sem outra estratégia configurada, o site
            # devolveria zero página em silêncio. Cair para a start_url é mais
            # honesto do que um arquivo vazio que a guarda de resultado reprova.
            self.logger.warning(f"[{self.id_site}] nenhum sitemap utilizável; caindo para links.")
            self.modo = "hibrido"
            for url in self.start_urls:
                yield scrapy.Request(url, callback=self.parse, dont_filter=True)

    def parse_robots(self, response):
        for url in descoberta.sitemaps_do_robots(response.text, response.url):
            if url not in self.sitemaps_vistos:
                self.sitemaps_vistos.add(url)
                yield self._pedir_sitemap(url, self.parse_sitemap)
        yield from self._quitar_sitemap()

    def parse_sitemap(self, response):
        urls, subs = descoberta.urls_de_sitemap(response.body)
        if not urls and not subs:
            yield from self._quitar_sitemap()
            return

        self.tentou_sitemap = True

        # Um sub-sitemap sozinho com dezenas de milhares de URLs é a assinatura
        # de injeção de spam. Não se corta no teto: descarta-se o sitemap todo.
        if len(urls) > descoberta.TETO_POR_SITEMAP:
            self.logger.error(
                f"[{self.id_site}] {response.url} traz {len(urls)} URLs "
                f"(teto {descoberta.TETO_POR_SITEMAP}). Sinal de domínio comprometido — ignorado."
            )
            self.detector.registrar("sitemap_gigante", url=response.url)
            yield from self._quitar_sitemap()
            return

        # Orçamento de requisição, não sinal de invasão: cada sub-sitemap é um
        # GET a mais antes da primeira página. Corta-se o excedente e segue.
        if len(subs) > descoberta.TETO_SUB_SITEMAPS:
            self.logger.warning(
                f"[{self.id_site}] {len(subs)} sub-sitemaps; usando os primeiros "
                f"{descoberta.TETO_SUB_SITEMAPS}."
            )
            subs = subs[: descoberta.TETO_SUB_SITEMAPS]

        # A soma é que denuncia: dá para diluir 400 mil URLs de spam em arquivos
        # pequenos, e o teto por arquivo não veria nada.
        if len(self.urls_de_sitemap) + len(urls) > descoberta.TETO_URLS_TOTAL:
            self.logger.error(
                f"[{self.id_site}] o sitemap passa de {descoberta.TETO_URLS_TOTAL} URLs no total. "
                f"Sinal de domínio comprometido — descartado."
            )
            self.detector.registrar("sitemap_gigante", url=response.url)
            self.urls_de_sitemap.clear()
            yield from self._quitar_sitemap()
            return

        for sub in subs:
            if sub not in self.sitemaps_vistos:
                self.sitemaps_vistos.add(sub)
                yield self._pedir_sitemap(sub, self.parse_sitemap)

        self.urls_de_sitemap.extend(urls)
        yield from self._quitar_sitemap()

    def parse(self, response):
        profundidade = response.meta.get("depth", 0)
        achados = descoberta.links_por_seletores(response, self.fontes)

        # Sem seletor, ou seletor que não casou nada (o caso do `fea`): cai para
        # o link genérico do domínio em vez de devolver zero página.
        if self.modo in ("links", "hibrido") and len(achados) < MIN_URLS_SITEMAP:
            achados += descoberta.links_genericos(response, self.allowed_domains)

        if achados:
            self.logger.info(f"[{self.id_site}] {len(achados)} link(s) em {response.url[:70]}")

        yield from self._enfileirar(
            descoberta.ordenar_por_relevancia(achados), profundidade=profundidade
        )

    def _enfileirar(self, urls, profundidade: int = 0):
        if profundidade >= self.profundidade_max:
            return
        for url in urls:
            if self.paginas_extraidas + len(self.urls_enfileiradas) >= self.max_paginas:
                return
            if url in self.urls_enfileiradas:
                continue

            permitida, motivo = url_permitida(url, self.config)
            self.detector.registrar(motivo, url=url)
            if not permitida:
                continue

            abortar, explicacao = self.detector.deve_abortar()
            if abortar:
                raise CloseSpider(f"anomalia: {explicacao}")

            self.urls_enfileiradas.add(url)
            yield scrapy.Request(url, callback=self.parse_conteudo)

    # ─────────────────────────────────────────
    # Conteúdo
    # ─────────────────────────────────────────
    def parse_conteudo(self, response):
        if self.paginas_extraidas >= self.max_paginas:
            raise CloseSpider(f"teto de {self.max_paginas} páginas atingido")

        if ExtratorConteudo.eh_pdf(response):
            dados = ExtratorConteudo.extrair_pdf(response)
        else:
            if not isinstance(response, scrapy.http.TextResponse):
                return
            dados = ExtratorConteudo.extrair_html(response)

        suspeita, motivo = parece_spam(response.url, dados["titulo"], dados["texto_limpo"])
        self.detector.registrar(motivo if suspeita else "ok", url=response.url)
        if suspeita:
            self.logger.warning(f"[{self.id_site}] descartada ({motivo}): {response.url[:80]}")
            abortar, explicacao = self.detector.deve_abortar()
            if abortar:
                raise CloseSpider(f"anomalia: {explicacao}")
            return

        texto = dados["texto_limpo"].strip()
        if len(texto) < MIN_CHARS_PAGINA:
            self.paginas_magras += 1
            # Continua servindo de fonte de link: um índice de departamento tem
            # pouco texto próprio e leva às páginas que interessam.
            if self.modo in ("links", "hibrido"):
                profundidade = response.meta.get("depth", 0)
                if profundidade < self.profundidade_max and isinstance(response, scrapy.http.TextResponse):
                    yield from self._enfileirar(
                        descoberta.ordenar_por_relevancia(
                            descoberta.links_genericos(response, self.allowed_domains)
                        ),
                        profundidade=profundidade,
                    )
            return

        self.paginas_extraidas += 1
        item = ChatbotContentItem()
        item["url"] = response.url
        item["titulo"] = dados["titulo"]
        item["texto_limpo"] = dados["texto_limpo"]
        yield item

        # Em modo de link genérico, a página de conteúdo também é fonte de link.
        if self.modo in ("links", "hibrido"):
            profundidade = response.meta.get("depth", 0)
            if profundidade < self.profundidade_max and isinstance(response, scrapy.http.TextResponse):
                yield from self._enfileirar(
                    descoberta.ordenar_por_relevancia(
                        descoberta.links_genericos(response, self.allowed_domains)
                    ),
                    profundidade=profundidade,
                )

    def closed(self, reason):
        """Deixa a estatística em disco: é dela que sai a guarda de vazio."""
        resumo = {
            "id_site": self.id_site,
            "motivo_fim": reason,
            "paginas_extraidas": self.paginas_extraidas,
            "paginas_magras": self.paginas_magras,
            "urls_enfileiradas": len(self.urls_enfileiradas),
            "usou_sitemap": self.tentou_sitemap,
            **self.detector.resumo(),
        }
        raiz = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        pasta = os.path.join(raiz, "data", "raw", "_stats")
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, f"{self.id_site}.json"), "w", encoding="utf-8") as f:
            json.dump(resumo, f, ensure_ascii=False, indent=2)
        self.logger.info(f"[{self.id_site}] fim: {resumo}")
