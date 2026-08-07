"""Higienização: `data/raw/*.json` -> `data/processed/*_limpo.json`.

Três consertos em relação à versão anterior.

**Escolha de regra por host, não por substring.** Antes era
`if dominio in url: ...; break`. Como `"fflch.usp.br"` é substring de
`"geografia.fflch.usp.br"` e vinha antes no JSON, toda página do geografia
recebia as regras do fflch e o `break` impedia as suas próprias de rodarem —
elas nunca rodaram, uma vez sequer. Agora o casamento é pelo hostname da URL, e
**todas** as regras que casam são aplicadas, da mais geral para a mais
específica.

**Regex sob custódia.** Ver `regex_seguro.py`: validação no carregamento,
watchdog de tempo e trava de proporção. É o que impede uma regra de travar o
processo ou de comer metade de uma página legítima.

**Boilerplate por estatística.** Ver `boilerplate.py`: o menu e o rodapé que
aparecem em toda página do site saem sozinhos, sem ninguém escrever regex.

Roda como `python -m embeddings.clean_data` a partir da raiz do projeto.
"""

import argparse
import glob
import json
import os
from collections import Counter
from datetime import date
from urllib.parse import urlparse

from embeddings import boilerplate, config_vetor as cfg
from embeddings.regex_seguro import PadraoInseguro, RegraCompilada, aplicar_com_limite, compilar
from embeddings.texto import normalizar

CAMINHO_REGRAS = os.path.join(cfg.DIRETORIO_ATUAL, "regras_ruido.json")

# Página com menos que isto depois da limpeza não é conteúdo, é casca.
MIN_CHARS_PAGINA = 120


# ─────────────────────────────────────────────
# Regras
# ─────────────────────────────────────────────
def carregar_regras(caminho: str = CAMINHO_REGRAS) -> tuple[list[RegraCompilada], dict]:
    """Compila e valida tudo de uma vez. Aceita o formato v1 e o v2."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except FileNotFoundError:
        print("[ALERTA] 'regras_ruido.json' não encontrado. Só a limpeza básica será aplicada.")
        return [], {}

    universais = bruto.get("universal", [])
    dominios = bruto.get("dominios")
    if dominios is None:  # formato v1: domínios na raiz
        dominios = {k: v for k, v in bruto.items() if k not in {"universal", "_meta"}}

    regras: list[RegraCompilada] = []
    recusadas: dict[str, str] = {}

    for dominio, lista in [("universal", universais), *dominios.items()]:
        for especificacao in lista:
            padrao = especificacao if isinstance(especificacao, str) else especificacao["padrao"]
            try:
                regras.append(compilar(dominio, especificacao))
            except PadraoInseguro as erro:
                recusadas[f"{dominio}: {padrao[:70]}"] = str(erro)

    if recusadas:
        print(f"\n[REGRAS RECUSADAS] {len(recusadas)} padrão(ões) não passaram na validação:")
        for chave, motivo in recusadas.items():
            print(f"   - {chave}\n     {motivo}")
        print()

    return regras, recusadas


def host_de(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def escolher_regras(url: str, regras: list[RegraCompilada]) -> list[RegraCompilada]:
    """Universais + todas as de domínio que casam, da mais geral para a mais específica."""
    host = host_de(url)
    escolhidas = [r for r in regras if r.dominio == "universal"]

    especificas = [
        r
        for r in regras
        if r.dominio != "universal" and (host == r.dominio or host.endswith("." + r.dominio))
    ]
    # Menos rótulos = mais geral. Aplicar nessa ordem evita que uma regra
    # específica perca o alvo porque a geral já mexeu no texto em volta.
    especificas.sort(key=lambda r: r.dominio.count("."))
    return escolhidas + especificas


def limpar_texto(texto: str, url: str, regras: list[RegraCompilada]) -> str:
    texto = normalizar(texto)
    for regra in escolher_regras(url, regras):
        texto = aplicar_com_limite(regra, texto)
    return normalizar(texto)


# ─────────────────────────────────────────────
# Execução
# ─────────────────────────────────────────────
def limpar_arquivo(caminho_raw: str, regras: list[RegraCompilada]) -> tuple[list[dict], dict]:
    with open(caminho_raw, "r", encoding="utf-8") as f:
        brutos = json.load(f)

    paginas = []
    descartadas = 0
    for documento in brutos:
        url = documento.get("url", "")
        original = documento.get("texto_limpo", documento.get("clean_text", ""))
        tratado = limpar_texto(original, url, regras)

        if len(tratado) < MIN_CHARS_PAGINA:
            descartadas += 1
            continue

        paginas.append(
            {
                "url": url,
                "titulo": (documento.get("titulo") or documento.get("title") or "").strip(),
                "texto_limpo": tratado,
            }
        )

    antes = sum(len(p["texto_limpo"]) for p in paginas)
    paginas, resumo_boilerplate = boilerplate.limpar_site(paginas)

    # A remoção de boilerplate pode esvaziar uma página que só tinha rodapé.
    paginas = [p for p in paginas if len(p["texto_limpo"]) >= MIN_CHARS_PAGINA]

    return paginas, {
        "paginas_entrada": len(brutos),
        "paginas_saida": len(paginas),
        "paginas_descartadas": descartadas + (len(brutos) - descartadas - len(paginas)),
        "chars": sum(len(p["texto_limpo"]) for p in paginas),
        "chars_antes_boilerplate": antes,
        "boilerplate": resumo_boilerplate,
    }


def executar(somente: list[str] | None = None) -> dict:
    pasta_raw = os.path.join(cfg.RAIZ_PROJETO, "data", "raw")
    os.makedirs(cfg.PASTA_PROCESSED, exist_ok=True)

    arquivos = sorted(glob.glob(os.path.join(pasta_raw, "*.json")))
    if somente:
        alvos = {os.path.basename(a) for a in somente}
        arquivos = [a for a in arquivos if os.path.basename(a) in alvos]

    if not arquivos:
        print(f"[AVISO] Nenhum JSON encontrado em {pasta_raw}.")
        return {}

    regras, recusadas = carregar_regras()
    print(f"-> {len(arquivos)} arquivo(s) para higienizar, {len(regras)} regra(s) válida(s).\n")

    relatorio = {"data": date.today().isoformat(), "recusadas": recusadas, "arquivos": {}}

    for caminho in arquivos:
        nome = os.path.basename(caminho)
        base = os.path.splitext(nome)[0].replace("_raw", "").replace("_data", "")
        saida = os.path.join(cfg.PASTA_PROCESSED, f"{base}_limpo.json")

        try:
            paginas, resumo = limpar_arquivo(caminho, regras)
        except Exception as erro:  # um arquivo corrompido não derruba os outros
            print(f"   [ERRO] {nome}: {erro}")
            relatorio["arquivos"][nome] = {"erro": str(erro)}
            continue

        with open(saida, "w", encoding="utf-8") as f:
            json.dump(paginas, f, ensure_ascii=False, indent=2)

        bp = resumo["boilerplate"]
        economia = (
            100 * bp["chars_removidos"] / resumo["chars_antes_boilerplate"]
            if resumo["chars_antes_boilerplate"]
            else 0
        )
        print(
            f"   [{base:12s}] {resumo['paginas_saida']:4d} páginas | "
            f"{resumo['chars']:8,d} chars | boilerplate: {bp['blocos']:3d} blocos, "
            f"-{economia:.1f}%"
        )
        relatorio["arquivos"][nome] = resumo

    _relatar_regras(regras, relatorio)
    return relatorio


def _relatar_regras(regras: list[RegraCompilada], relatorio: dict) -> None:
    """Grava e resume o desempenho de cada regra.

    A lista de regras mortas é o ponto todo: sem ela, uma regra que parou de
    casar por causa de uma reforma do site fica lá para sempre, dando a falsa
    impressão de que aquele rodapé está sendo tratado.
    """
    relatorio["regras"] = [r.para_relatorio() for r in regras]
    contagem = Counter(r.status for r in regras)

    os.makedirs(cfg.PASTA_RELATORIOS, exist_ok=True)
    destino = os.path.join(cfg.PASTA_RELATORIOS, "limpeza.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    print(f"\n-> Regras: {dict(contagem)}")
    mortas = [r for r in regras if r.status == "morta"]
    if mortas:
        print(f"   {len(mortas)} regra(s) não casaram nada (candidatas a poda):")
        for regra in mortas[:12]:
            print(f"      [{regra.dominio}] {regra.padrao[:74]}")
    print(f"-> Relatório em {os.path.relpath(destino, cfg.RAIZ_PROJETO)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Higieniza data/raw -> data/processed.")
    parser.add_argument(
        "--somente",
        nargs="*",
        default=None,
        help="Processa só estes arquivos de data/raw (ex.: iq_raw.json).",
    )
    argumentos = parser.parse_args()
    executar(somente=argumentos.somente)


if __name__ == "__main__":
    main()
