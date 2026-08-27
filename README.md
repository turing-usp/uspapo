# uspapo 🕷️💬

O **uspapo** é um chatbot que responde perguntas sobre a USP a partir de páginas
públicas da própria universidade. O projeto começou como um web scraper e hoje é
o caminho inteiro: raspa os sites, higieniza o texto, indexa num banco vetorial e
serve isso a um modelo de linguagem por trás de um site.

---

## As quatro peças

```
scrapers/     sites da USP  ->  data/raw/*.json           (Scrapy)
embeddings/   data/raw/     ->  data/processed/ -> Pinecone
backend/      pergunta      ->  busca + LLM -> resposta   (Flask, SSE)
site/         a interface                                 (Next.js)
```

Cada pasta roda sozinha. Dá para mexer no site sem nunca subir um crawler, e dá
para rodar o pipeline de dados sem o backend de pé.

> **Onde está a documentação de verdade:** no docstring de cada módulo. Este
> README orienta; quem quiser saber *por que* uma função é do jeito que é abre o
> arquivo. Os docstrings guardam os números medidos e os incidentes que
> motivaram cada trava — é lá que o detalhe fica atualizado.

---

## 📦 Setup

### 1. Python (scrapers, embeddings e backend)

**Python 3.11 ou mais novo.** A CI roda 3.11; 3.12, 3.13 e 3.14 funcionam.

```bash
git clone <url-do-repositorio> && cd uspapo
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Instale sempre pelo `requirements.txt`.** O pino `Twisted>=24.7,<26` tem um
motivo em cada ponta, e as duas quebram o `import scrapy` inteiro: o Twisted
antigo importa o módulo `cgi`, que saiu do Python 3.13
(`ModuleNotFoundError: No module named 'cgi'`), e o Twisted 26 removeu uma API
privada que o scrapy 2.13 usa.

### 2. Variáveis de ambiente

```bash
cp .env.example .env               # raiz: backend + pipeline
cp site/.env.example site/.env.local
```

Só a `PINECONE_API_KEY` e a `LLM_PROVIDERS` são obrigatórias, e nem elas se você
usar o backend simulado. Todo o resto tem default no código: o `.env.example`
lista as manoplas com o motivo de cada uma existir.

### 3. Site (Next.js)

```bash
cd site && npm install && npm run dev      # http://localhost:3000
```

### 4. Rodando sem chave nenhuma

```bash
python backend/app_stub.py                 # busca falsa, nada de Pinecone
python -m embeddings.build_vector --dry-run # calcula o plano, não escreve
```

---

## 🛠️ Ferramentas

### Pipeline de dados (`scrapers/` + `embeddings/`)

| Comando | O que faz |
| --- | --- |
| `python scrapers/spiders/rodar_scrapers.py` | a ronda completa: raspa o que venceu, higieniza, indexa |
| `python -m scrapers.validar_site --id <id>` | **portão de entrada** de site novo. Não toca no Pinecone |
| `python -m embeddings.clean_data` | `data/raw/` → `data/processed/` |
| `python -m embeddings.build_vector --dry-run` | mostra o plano de escrita antes de gastar cota |
| `python -m embeddings.reconciliar` | compara o ledger com o que existe de fato no índice |
| `python -m embeddings.criar_indice` | cria o índice do Pinecone (idempotente, roda uma vez) |

Flags que importam: `--somente <id...>` (em quase todos) processa um site só;
`--forcar` ignora o vencimento por frequência; `--paralelos N` diz quantos
**sites** raspar ao mesmo tempo (cada servidor continua vendo um crawler só); e
`--forcar-migracao` desliga o disjuntor de orçamento — existe para o rebuild,
nunca para o cron.

Os módulos, por assunto:

| Módulo | Do que cuida |
| --- | --- |
| `scrapers/spiders/spider_generico.py` | o único spider: descoberta, freios e teto de páginas |
| `scrapers/descoberta.py` | achar URLs por sitemap, seletor CSS ou link do domínio |
| `scrapers/filtros.py` | recusa de URL e o detector de domínio invadido |
| `scrapers/extracao.py` | HTML e PDF viram parágrafos (blocos-folha, sem duplicar) |
| `embeddings/clean_data.py` | regras de ruído por domínio + boilerplate estatístico |
| `embeddings/regex_seguro.py` | valida, cronometra e limita o dano de cada regra |
| `embeddings/chunking.py` | parágrafos viram chunks, com corte em fronteira de frase |
| `embeddings/ledger.py` | o espelho local do índice, com contagem de referência |
| `embeddings/build_vector.py` | o plano de upsert/delete e o disjuntor de orçamento |

### Backend (`backend/`)

```bash
python backend/app_stub.py     # busca falsa, NÃO precisa de Pinecone
python backend/app.py          # busca de verdade
gunicorn --chdir backend app:app   # produção (Render)
```

Os dois entrypoints têm ~30 linhas e a única diferença entre eles é **qual
conjunto de ferramentas** o modelo enxerga. Todo o resto vive em
`backend/uspapo/`:

| Módulo | Do que cuida |
| --- | --- |
| `config.py` | lê o `.env` uma vez e guarda as constantes |
| `provedores.py` | a cadeia `LLM_PROVIDERS`, com queda para o próximo |
| `conversa.py` | o motor: laço de ferramentas e fallback entre provedores |
| `contexto.py` | orçamento de tokens e poda do histórico |
| `conteudo.py` | separa `<think>`/`<tool_call>` do texto, token a token |
| `toolcalls.py` | parsers de tool call inline e o coletor de cada rodada |
| `contas.py` / `acesso.py` | quem é (token do Supabase) e quem pode (`uspapo_role` **ou** whitelist de emails) |
| `limites.py` | rate limit por conta |
| `saida.py` | os eventos viram SSE ou o JSON legado |
| `web.py` | `criar_app()`: CORS, `/chat` e `/health` |
| `ferramentas/` | o registro, a busca no Pinecone, consultas ao vivo (RU, JupiterWeb, Wikipedia etc.) e as simuladas |

**Para adicionar uma ferramenta**, escreva uma função decorada em
`ferramentas/busca.py` (ou num módulo novo) — o schema fica junto da
implementação e mais nada precisa mudar:

```python
@registro.ferramenta(nome="...", descricao="...", parametros={...})
def minha_ferramenta(...) -> tuple[str, list[str]]:
    """Devolve (texto para o modelo ler, lista de URLs consultadas)."""
```

### Frontend (`site/`)

Next.js 16 (App Router) + React 19 + Tailwind 4 + Supabase para login.

| Comando | O que faz |
| --- | --- |
| `npm run dev` | servidor de desenvolvimento |
| `npm run build` | build de produção |
| `npm run lint` | ESLint |
| `npm run app:sync:dev` | sincroniza o app Android apontando para o `next dev` (`10.0.2.2:3000`) |
| `npm run app:sync:prod` | sincroniza o app Android apontando para o domínio de produção |

O wrapper do app Android (Capacitor) vive em `site/android/`; desenvolvimento,
domínio e release estão em `docs/app-android.md`.

| Pasta | Do que cuida |
| --- | --- |
| `app/(app)/` | chat, histórico e a home logada |
| `app/(auth)/` | login e cadastro |
| `components/` | a interface: bolhas, menus, streaming, fontes |
| `lib/stream.ts` | consome o SSE do backend |
| `lib/conversas.ts` | persistência das conversas no Supabase |
| `lib/limites.ts` | os tetos do lado do cliente, por perfil de usuário |
| `lib/perguntas.ts` | as perguntas frequentes da tela inicial |

---

## 🔄 Fluxo de trabalho

### O pipeline diário

Roda sozinho às 5h (`.github/workflows/pipeline_rag.yml`) e faz, em ordem:

1. **raspa** os sites vencidos pela `frequency` de cada um, no máximo 12 por
   ronda e os mais atrasados primeiro: o excedente vence de novo amanhã, e é
   isso que impede um dia de vencimentos coincidentes de estourar o timeout;
2. **avalia o resultado** antes de aceitá-lo: 0 páginas, queda de mais de 50%
   ou texto curto demais reprovam a rodada, e aí o arquivo bom anterior fica
   onde está;
3. **higieniza** e **sincroniza** com o Pinecone.

O passo 3 passa por um **disjuntor de orçamento**: mexer em mais de 25% do banco
de uma vez aborta a execução sem escrever nada. Isso não é paranoia — foi um
site que trouxe 400 mil páginas de spam que derrubou o índice anterior.

### Adicionar um site novo

Site novo **nunca** entra direto no índice. O caminho é:

```bash
# 1. adicione a entrada em scrapers_config.json com "estado": "quarentena"
# 2. valide (raspa para data/raw/_quarentena/, não fala com o Pinecone)
python -m scrapers.validar_site --id meu_site
# 3. leia o relatório em data/reports/onboarding_meu_site.json
# 4. aprovado? mude "estado" para "ativo" numa PR
```

A validação mede páginas, mediana de caracteres, proporção de spam, parágrafos
gigantes, títulos vazios e duplicação, e **reprova sozinha**. Os estados
possíveis são `ativo`, `quarentena`, `suspeito` (3 falhas seguidas, pulado
automaticamente) e `desativado` (com `motivo` escrito, para ninguém
redescobrir o mesmo site morto daqui a três meses).

### Rebuild completo do índice

Raro, e de propósito trabalhoso — só quando a forma do chunk muda:

```bash
python -m embeddings.criar_indice                  # idempotente; só age se não existir
python -m embeddings.build_vector --dry-run        # confira a contagem primeiro
# apagar o namespace no Pinecone + remover data/index/ledger_avancado.json
python scrapers/spiders/rodar_scrapers.py --forcar
python -m embeddings.build_vector --forcar-migracao
```

O ledger tem que sair junto: ele é o espelho do índice, e um espelho que afirma
existir o que foi apagado faz o `build_vector` não reenviar nada.

---

## 🌱 Git

Trabalhe sempre numa branch com o seu nome, nunca na `main`:

```bash
git checkout main && git pull origin main
git checkout -b seu-nome
# ... suas mudanças ...
git add . && git commit -m "Crawler do site: xxxxx"
git push origin seu-nome
```

**Boas práticas:** commits pequenos e frequentes, mensagens claras
(`Crawler do site do IQ`), e teste antes de enviar. Respeite o trabalho dos
colegas, evite sobrescrever código de outra pessoa.

O que **não** entra no git: `.env`, `data/reports/`, `data/raw/_tmp/`,
`data/raw/_quarentena/` e `data/raw/_stats/`. Tudo que é relatório ou rascunho
de execução. O corpus em si (`data/raw/`, `data/processed/`) e o
`data/index/ledger_avancado.json` **são** versionados, porque é deles que o
pipeline calcula o que mudou desde ontem.
