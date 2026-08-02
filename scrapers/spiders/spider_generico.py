import scrapy
import json
import os
from scrapers.utils import ExtratorConteudo
from scrapers.items import ChatbotContentItem  

class UspSpiderGenerica(scrapy.Spider):
    # ATENÇÃO: O nome aqui precisa bater com o que você chama no subprocess do rodar_scrapers.py
    name = "spider_generico" 
    
    def __init__(self, config_id='', *args, **kwargs):
        super(UspSpiderGenerica, self).__init__(*args, **kwargs)
        
        # 1. Bússola absoluta: sobe duas pastas para chegar na raiz do projeto (uspapo)
        diretorio_atual = os.path.dirname(os.path.abspath(__file__))
        raiz_projeto = os.path.abspath(os.path.join(diretorio_atual, "..", ".."))
        caminho_json = os.path.join(raiz_projeto, 'scrapers_config.json')

        if not os.path.exists(caminho_json):
            raise FileNotFoundError(f"Arquivo de configuração não encontrado em: {caminho_json}")

        with open(caminho_json, 'r', encoding='utf-8') as f:
            configs = json.load(f)
            
        # 2. Busca a configuração do site específico que o orquestrador pediu
        config = next((c for c in configs if c.get('id_site') == config_id), None)

        # 3. Configura o Spider dinamicamente
        self.start_urls = [config.get('start_url')]
        self.allowed_domains = [config.get('allowed_domain')]
        self.sources = config.get('sources', [])
        
        self.logger.info(f"Spider inicializado para '{config_id}' com {len(self.sources)} fontes de extração mapeadas.")

    def parse(self, response):
        todos_links_encontrados = []
        
        # 1. Varre todos os pontos de interesse (sources) que você mapeou no JSON
        for source in self.sources:
            tipo = source.get("type", "desconhecido")
            seletor = source.get("selector", "")
            
            if seletor:
                links_neste_seletor = response.css(seletor).getall()
                todos_links_encontrados.extend(links_neste_seletor)
                self.logger.info(f"Fonte [{tipo.upper()}] extraiu {len(links_neste_seletor)} links base.")
                
            # Futuro: Aqui poderemos colocar um `elif tipo == "wordpress_api"` para acessar REST APIs
        
        # 2. Limpeza bruta e Deduplicação Instantânea
        links_limpos = [link for link in todos_links_encontrados if link and not link.startswith('#')]
        links_unicos = list(set(links_limpos)) # O set() mata qualquer duplicata
        
        self.logger.info(f"Mapeamento concluído! {len(links_unicos)} links ÚNICOS serão raspados.")
        
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