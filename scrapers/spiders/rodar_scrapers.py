"""Orquestrador: decide o que raspar, higieniza e sincroniza.

O conserto principal aqui é a **guarda de resultado vazio**.

Como era: o scrapy escrevia direto em `data/raw/{id}_raw.json` com `-O`
(sobrescreve), e qualquer saída sem exceção contava como sucesso. Um site cujos
seletores pararam de casar produzia `[]`, esse `[]` ia por cima do arquivo bom, e
o `last_update` avançava como se estivesse tudo certo. É o que aconteceu com o
`fea`: `data/raw/fea_raw.json` é literalmente `[\\n\\n]`, e ninguém percebeu.

Como é: o scrapy escreve em `data/raw/_tmp/`, e o arquivo só é promovido se
passar por `avaliar_extracao`. Reprovou, o arquivo antigo fica, `last_update` não
sobe, e a falha é contada: em três falhas seguidas o site vira `suspeito` e
para de ser tentado todo dia.

O segundo conserto é de escopo: `houve_atualizacao` era um booleano global, então
um único site atualizado mandava reprocessar os 18. Agora só o que foi promovido
segue para a limpeza e a indexação.

O terceiro é de tempo. Os sites eram raspados um depois do outro, e com
`DOWNLOAD_DELAY = 4` isso dá ~15 minutos por site. Com 40 e poucos sites
cadastrados, um dia de vencimentos coincidentes não cabia nos
`timeout-minutes: 45` do próprio workflow. Agora vários sites correm em paralelo.
Isso **não** deixa o crawler menos educado: cada site é um domínio e um processo
separados, e o intervalo entre requisições continua valendo dentro de cada um.
O paralelismo é entre servidores diferentes, nunca em cima do mesmo.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CONFIG = os.path.join(RAIZ, "scrapers_config.json")
PASTA_RAW = os.path.join(RAIZ, "data", "raw")
PASTA_TMP = os.path.join(PASTA_RAW, "_tmp")
PASTA_QUARENTENA = os.path.join(PASTA_RAW, "_quarentena")

QUEDA_MAXIMA = 0.5  # perder mais da metade das páginas reprova a extração
MIN_MEDIANA_CHARS = 200
MAX_FALHAS = 3

# Quantos sites ao mesmo tempo. Conservador de propósito: o teto útil aqui é a
# memória do runner (~95 MB por processo do scrapy), não a paciência dos
# servidores da USP, que só veem um crawler cada.
PARALELOS_PADRAO = 4

# Teto de sites por ronda, com os mais atrasados primeiro.
#
# Existe como rede contra o `timeout-minutes` do workflow: um dia em que muitos
# sites vencem juntos não pode matar a ronda no meio.
#
# O número acompanha a cadência. Enquanto a ronda era diária, 12 bastava e o
# excedente vencia de novo no dia seguinte. Agora a ronda é semanal — porque
# reindexar custa cota de embedding — e a próxima só vem em sete dias: um teto
# baixo não adiaria o excedente, ele o deixaria envelhecer uma semana inteira.
# A demanda de uma semana são ~31 sites (43 ativos: 22 a cada 7d, 9 a cada 14d,
# 12 a cada 21d), e com `--paralelos 8` isso fecha dentro dos 90 minutos.
MAX_SITES_POR_RONDA = 32

# Piso de frequência, em dias.
#
# Raspar é barato; reindexar não é. Cada página promovida volta para o
# `clean_data` e para o `build_vector`, e todo parágrafo cujo hash mudou vira um
# embedding pago. Sites da USP têm carrossel de notícias e de eventos que muda
# sozinho, então um site revisitado com frequência gera upsert mesmo sem nenhuma
# mudança de conteúdo que interesse ao aluno.
#
# Nenhum site pode, portanto, ser revisitado em menos de uma semana. O piso mora
# aqui, e não no `scrapers_config.json`, porque config é dado editável: um `1d`
# digitado sem querer numa entrada nova não pode reabrir a torneira.
MIN_FREQUENCIA_DIAS = 7


def dias_de_frequencia(freq_str: str) -> int:
    """Converte a frequência declarada, nunca abaixo do piso semanal."""
    try:
        dias = int(str(freq_str).replace("d", "").strip())
    except (ValueError, TypeError):
        print(f"[AVISO] Frequência inválida '{freq_str}'. Usando {MIN_FREQUENCIA_DIAS}d.")
        return MIN_FREQUENCIA_DIAS
    if dias < MIN_FREQUENCIA_DIAS:
        print(
            f"[AVISO] Frequência '{freq_str}' é menor que o piso de "
            f"{MIN_FREQUENCIA_DIAS}d; tratando como {MIN_FREQUENCIA_DIAS}d."
        )
        return MIN_FREQUENCIA_DIAS
    return dias


def calcular_vencimento(data_str: str, freq_str: str) -> bool:
    if not data_str:
        return True
    try:
        ultima = datetime.strptime(data_str, "%Y-%m-%d")
    except (ValueError, TypeError) as erro:
        print(f"[AVISO] Data inválida '{data_str}': {erro}. Forçando atualização.")
        return True
    return datetime.now() >= ultima + timedelta(days=dias_de_frequencia(freq_str))


def _carregar(caminho: str) -> list:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def avaliar_extracao(novo: str, anterior: str, config: dict) -> tuple[bool, str]:
    """Decide se a extração nova pode substituir a anterior."""
    paginas = _carregar(novo)
    if not paginas:
        return False, "extração vazia (0 páginas)"

    minimo = int(config.get("min_paginas", 1))
    if len(paginas) < minimo:
        return False, f"só {len(paginas)} páginas, mínimo é {minimo}"

    tamanhos = [len(p.get("texto_limpo", "")) for p in paginas]
    mediana = statistics.median(tamanhos) if tamanhos else 0
    if mediana < MIN_MEDIANA_CHARS:
        return False, f"mediana de {mediana:.0f} chars por página (mínimo {MIN_MEDIANA_CHARS})"

    antigas = _carregar(anterior)
    if antigas and len(paginas) < len(antigas) * (1 - QUEDA_MAXIMA):
        return False, f"caiu de {len(antigas)} para {len(paginas)} páginas"

    return True, f"{len(paginas)} páginas, mediana {mediana:.0f} chars"


def raspar(id_site: str, destino: str, timeout: int = 2400) -> bool:
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(destino):
        os.remove(destino)
    comando = [
        sys.executable, "-m", "scrapy", "crawl", "spider_generico",
        "-a", f"config_id={id_site}", "-O", destino, "-L", "INFO",
    ]
    try:
        subprocess.run(comando, check=True, cwd=RAIZ, timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        print(f"[ERRO] {id_site}: estourou o tempo de {timeout}s.")
    except subprocess.CalledProcessError as erro:
        print(f"[ERRO] {id_site}: o scrapy terminou com erro: {erro}")
    return False


def _processar_site(config: dict, hoje: str) -> str | None:
    """Raspa um site e decide se promove. Devolve o nome do arquivo promovido.

    Roda numa thread, então não imprime linha a linha: monta o relato inteiro e
    solta de uma vez, senão a saída de quatro sites vira uma sopa. Só mexe no
    `config` do próprio site e nos arquivos com o id dele no nome — é isso que
    torna o paralelismo seguro sem lock nenhum.
    """
    id_site = config["id_site"]
    estado = config.get("estado", "ativo")
    em_quarentena = estado == "quarentena"

    pasta = PASTA_QUARENTENA if em_quarentena else PASTA_TMP
    temporario = os.path.join(pasta, f"{id_site}_raw.json")
    definitivo = os.path.join(PASTA_RAW, f"{id_site}_raw.json")

    sucesso = raspar(id_site, temporario)
    config["ultima_tentativa"] = hoje

    if em_quarentena:
        # Quarentena nunca promove nem alimenta o índice: o material fica
        # em _quarentena/ para alguém olhar com o validar_site.py.
        print(f">>> [{id_site.upper():12s}] [QUARENTENA] resultado em "
              f"{os.path.relpath(temporario, RAIZ)}, não promovido.")
        return None

    aprovado, detalhe = (False, "o scrapy falhou")
    if sucesso:
        aprovado, detalhe = avaliar_extracao(temporario, definitivo, config)

    if not aprovado:
        config["falhas_consecutivas"] = int(config.get("falhas_consecutivas", 0)) + 1
        aviso = ""
        if config["falhas_consecutivas"] >= MAX_FALHAS:
            config["estado"] = "suspeito"
            aviso = (f"\n    [SUSPEITO] {config['falhas_consecutivas']} falhas seguidas. "
                     "Não será tentado de novo até revisão manual.")
        print(f">>> [{id_site.upper():12s}] [REPROVADO] {detalhe}. "
              f"O arquivo anterior foi mantido.{aviso}")
        return None

    shutil.move(temporario, definitivo)
    config["last_update"] = hoje
    config["falhas_consecutivas"] = 0
    print(f">>> [{id_site.upper():12s}] [OK] {detalhe}")
    return f"{id_site}_raw.json"


def rodar_pipeline(
    somente=None, forcar=False, somente_extracao=False, paralelos=PARALELOS_PADRAO
) -> None:
    if not os.path.exists(CONFIG):
        print(f"[ERRO] Configuração não encontrada: {CONFIG}")
        return

    with open(CONFIG, "r", encoding="utf-8") as f:
        configuracoes = json.load(f)

    print("\n" + "=" * 56)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] RONDA DO USPAPO")
    print("=" * 56)

    hoje = datetime.now().strftime("%Y-%m-%d")
    a_raspar: list[dict] = []

    for config in configuracoes:
        id_site = config["id_site"]
        estado = config.get("estado", "ativo")

        if somente and id_site not in somente:
            continue
        if estado in ("desativado", "suspeito"):
            motivo = config.get("motivo", "")
            print(f"--- [{id_site.upper():12s}] pulado (estado={estado}) {motivo}")
            continue
        if not forcar and not calcular_vencimento(config.get("last_update", ""), config.get("frequency", "7d")):
            print(f"--- [{id_site.upper():12s}] em dia.")
            continue
        a_raspar.append(config)

    # Mais atrasados primeiro: quem nunca foi raspado (`last_update` vazio) tem
    # prioridade, e ninguém fica indefinidamente no fim da fila.
    if not somente and len(a_raspar) > MAX_SITES_POR_RONDA:
        a_raspar.sort(key=lambda c: c.get("last_update") or "")
        adiados = [c["id_site"] for c in a_raspar[MAX_SITES_POR_RONDA:]]
        a_raspar = a_raspar[:MAX_SITES_POR_RONDA]
        print(
            f"\n[TETO] {len(adiados)} site(s) vencido(s) ficam para a próxima ronda "
            f"(teto de {MAX_SITES_POR_RONDA}): {', '.join(sorted(adiados))}"
        )

    promovidos: list[str] = []
    houve_mudanca_de_config = bool(a_raspar)

    if a_raspar:
        paralelos = max(1, min(paralelos, len(a_raspar)))
        print(f"\n>>> {len(a_raspar)} site(s) para raspar, {paralelos} em paralelo.\n")
        with ThreadPoolExecutor(max_workers=paralelos) as pool:
            for nome in pool.map(lambda c: _processar_site(c, hoje), a_raspar):
                if nome:
                    promovidos.append(nome)

    if houve_mudanca_de_config:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(configuracoes, f, indent=2, ensure_ascii=False)
        print("\n[OK] scrapers_config.json atualizado.")

    if not promovidos:
        print("\n[INFO] Nenhuma extração promovida. Limpeza e indexação não são necessárias.")
        return
    if somente_extracao:
        print(f"\n[INFO] --somente-extracao: parando após promover {len(promovidos)} arquivo(s).")
        return

    print("\n" + "=" * 56)
    print(f" HIGIENIZAÇÃO ({len(promovidos)} arquivo(s))")
    print("=" * 56)
    if not _rodar(["-m", "embeddings.clean_data", "--somente", *promovidos]):
        print("[ERRO] A limpeza falhou; a indexação não vai rodar sobre dado duvidoso.")
        return

    limpos = [nome.replace("_raw.json", "_limpo.json") for nome in promovidos]
    print("\n" + "=" * 56)
    print(" VETORIZAÇÃO")
    print("=" * 56)
    _rodar(["-m", "embeddings.build_vector", "--somente", *limpos])


# `build_vector` sai com 3 quando a cota mensal de embeddings acabou. Não é uma
# falha do scraping: as páginas foram raspadas e promovidas, só a vetorização
# não cabe mais neste mês. Confundir os dois faria alguém procurar um seletor
# quebrado que não existe.
SAIDA_COTA_MENSAL = 3


def _rodar(argumentos: list[str]) -> bool:
    try:
        subprocess.run([sys.executable, *argumentos], check=True, cwd=RAIZ)
        return True
    except subprocess.CalledProcessError as erro:
        if erro.returncode == SAIDA_COTA_MENSAL:
            print(
                "[COTA] A cota mensal de tokens de embedding acabou. O texto "
                "raspado está salvo e será indexado na virada do mês; nada "
                "aqui precisa ser reparado."
            )
        else:
            print(f"[ERRO] {' '.join(argumentos)} falhou: {erro}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Roda a ronda de scraping do USPapo.")
    parser.add_argument("--somente", nargs="*", default=None, help="Só estes id_site.")
    parser.add_argument("--forcar", action="store_true", help="Ignora o vencimento por frequência.")
    parser.add_argument("--somente-extracao", action="store_true", help="Não roda limpeza nem indexação.")
    parser.add_argument(
        "--paralelos", type=int, default=PARALELOS_PADRAO,
        help=f"Quantos sites raspar ao mesmo tempo (padrão {PARALELOS_PADRAO}).",
    )
    argumentos = parser.parse_args()
    rodar_pipeline(
        somente=argumentos.somente,
        forcar=argumentos.forcar,
        somente_extracao=argumentos.somente_extracao,
        paralelos=argumentos.paralelos,
    )


if __name__ == "__main__":
    main()
