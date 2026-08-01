# uspapo 🕷️💬

O **uspapo** é um projeto focado no web scraping de páginas e sites da Universidade de São Paulo (USP). Nosso objetivo é coletar e estruturar dados públicos para análises e integrações futuras.

---

## 🚀 Pré-requisitos & Tecnologias

Para manter todo mundo na mesma página, padronizamos as seguintes ferramentas:

*   **Linguagem:** Python `3.13.9`
*   **Framework Principal:** Scrapy (para a extração de dados)
*   **Controle de Versão:** Git
*   **Recomendação de framwork para controlar a versão:** Anaconda

---

## 📦 Configuração do Ambiente Local

Siga o passo a passo abaixo para rodar o projeto na sua máquina:

## Como começar

### 1. Clone o repositório

```bash
git clone <url-do-repositorio>
cd <nome-do-repositorio>
```

---

### 2. Crie sua branch

Use um padrão com seu nome:

```bash
git checkout -b sua-branch
```

Exemplo:

```bash
git checkout -b joao-silva
```

---

### 3. Faça a sua parte ✍️

Siga o exemplo da documentação do scrapy, e crie um arquivo diferente para cada site que for utilizar. CUIDADO para não mexer no do amiguinho e dar problema no nosso scraper geral. 

---

### 4. Adicione e salve suas mudanças

```bash
git add .
git commit -m "Crawler do site: xxxxxxxx"
```

💡 **Dica:** Use mensagens de commit claras, como:
- `Crawler do site do IQ`
- `Crawler do site da POLI`

---

### 5. Envie sua branch

```bash
git push origin sua-branch
```

---

## 🚀 Dicas importantes de Git

### 🔄 Atualizar seu repositório

Antes de começar, sempre atualize:

```bash
git checkout main
git pull origin main
```

---

### 🔀 Trocar de branch

```bash
git checkout nome-da-branch
```

---

### 📊 Ver status

```bash
git status
```

---

### 🧾 Ver histórico de commits

```bash
git log --oneline
```

---

## ⚠️ Boas práticas

- JAMAIS trabalhe diretamente na `main`
- Faça commits pequenos e frequentes
- Use nomes claros para suas branches (simplesmente se identifique)
- Sempre teste seu código antes de enviar

---

## 🤝 Colaboração

Respeite o trabalho dos colegas e evite sobrescrever código de outras pessoas.

---

## 🧠 Backend (API do chat)

O backend vive em `backend/` e responde ao site em `site/`. Antes de rodar, copie
o `.env.example` da raiz para `.env` e preencha as chaves.

```bash
python backend/app_stub.py   # busca falsa, NÃO precisa de Pinecone
python backend/app.py        # busca de verdade, precisa de PINECONE_API_KEY
```

Em produção (Render), o comando é:

```bash
gunicorn --chdir backend app:app
```

### Como o código está organizado

Os dois arquivos acima são só entrypoints de ~30 linhas: a única coisa que muda
entre eles é **qual conjunto de ferramentas** o modelo enxerga. Todo o resto está
no pacote `backend/uspapo/` e é compartilhado.

| Módulo | Do que cuida |
| --- | --- |
| `config.py` | lê o `.env` (uma vez só) e guarda as constantes de todo mundo |
| `provedores.py` | a cadeia `LLM_PROVIDERS`, com queda para o próximo provedor |
| `prompt.py` | o prompt de sistema, com a data de hoje |
| `limites.py` | rate limit por aparelho (header `X-Device-Id`) |
| `contexto.py` | orçamento de tokens e poda do histórico da conversa |
| `conteudo.py` | separa `<think>`/`<tool_call>` do texto, token a token |
| `toolcalls.py` | parsers de tool call inline e o coletor de cada rodada |
| `conversa.py` | o motor: laço de ferramentas e fallback entre provedores |
| `saida.py` | os eventos viram SSE ou o JSON legado |
| `web.py` | `criar_app()`: CORS, `/chat` e `/health` |
| `ferramentas/` | o registro, a busca no Pinecone e as ferramentas simuladas |

**Para adicionar uma ferramenta nova**, escreva uma função decorada em
`ferramentas/busca.py` (ou num módulo novo) e pronto — o schema fica junto da
implementação e mais nada precisa mudar:

```python
@registro.ferramenta(nome="...", descricao="...", parametros={...})
def minha_ferramenta(...) -> tuple[str, list[str]]:
    """Devolve (texto para o modelo ler, lista de URLs consultadas)."""
```

---
