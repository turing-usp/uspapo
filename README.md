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
