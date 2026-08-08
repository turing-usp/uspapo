"""O ledger: o espelho local do que existe no Pinecone.

O ledger é o que permite ao pipeline gastar quase nada quando quase nada mudou:
em vez de reenviar o site inteiro toda semana, ele compara hash de parágrafo com
hash de parágrafo e só mexe no que virou outra coisa.

Duas mudanças em relação ao formato antigo.

**Enxugamento (v1 -> v2).** O v1 guardava o `texto` completo de cada chunk E o
texto completo de cada parágrafo dentro dele: uma cópia integral de
`data/processed/`, commitada no git a cada execução do cron. São 23,1 MB que
viram 2,73 MB (-88%) só guardando os hashes, que é tudo que o rechunking
ancorado realmente lê. A migração não altera nenhum `chunk_id`, então custa zero
requisição no Pinecone.

**Contagem de referência (`canonicos`).** Sem ela, deduplicar chunk idêntico e
deletar página que sumiu são duas features que se destroem: a página A e a
página B compartilham um chunk, A some, o chunk é apagado, e B fica com um
buraco silencioso — a busca simplesmente deixa de achar aquele trecho, sem erro
nenhum no log. Aqui cada texto de chunk é dono de um `chunk_id` só, e esse id só
morre quando a última página que o citava solta a referência.

Como o `chunk_id` carrega no nome o arquivo e a URL de quem o criou, a primeira
referência é também a que dá a URL gravada no metadado. Se justamente ela for
embora e ainda restar outra, o chunk não morre: ele é *realocado*, e o chamador
reenvia o metadado apontando para a página que sobrou. Sem isso a busca passaria
a citar uma URL que não existe mais.
"""

import json
import os

from embeddings import config_vetor as cfg

VERSAO_LEDGER = 2


# ─────────────────────────────────────────────
# Estrutura
# ─────────────────────────────────────────────
def novo_ledger() -> dict:
    return {"_meta": {"versao": VERSAO_LEDGER}, "canonicos": {}, "arquivos": {}}


def _chave(arquivo: str, url: str) -> list:
    # Lista, e não tupla, porque isto vai e volta do JSON.
    return [arquivo, url]


def enxugar_chunk(chunk: dict) -> dict:
    """Reduz um chunk ao que o rechunking ancorado precisa ler."""
    hashes = chunk.get("hashes_p")
    if hashes is None:
        hashes = [p["hash_p"] for p in chunk.get("paragrafos", [])]
    enxuto = {"hash_chunk": chunk["hash_chunk"], "hashes_p": hashes}
    if "chunk_id" in chunk:
        enxuto["chunk_id"] = chunk["chunk_id"]
    return enxuto


def migrar_v1_para_v2(v1: dict) -> dict:
    """Converte o formato antigo preservando todos os `chunk_id`.

    O v1 tinha os arquivos na raiz do dicionário; o v2 os move para dentro de
    `arquivos` para liberar a raiz para `_meta` e `canonicos`. Os `canonicos`
    são reconstruídos varrendo o que já existe, então a deduplicação passa a
    valer para o acervo antigo sem reindexar nada.
    """
    v2 = novo_ledger()
    for nome_arquivo, dados in v1.items():
        if nome_arquivo.startswith("_") or nome_arquivo in {"canonicos", "arquivos"}:
            continue
        paginas_v2 = {}
        for url, pag in dados.get("paginas", {}).items():
            chunks = []
            for chunk in pag.get("chunks", []):
                if "hash_chunk" not in chunk:
                    continue
                enxuto = enxugar_chunk(chunk)
                chunks.append(enxuto)
                if "chunk_id" in enxuto:
                    _registrar_bruto(
                        v2, enxuto["hash_chunk"], enxuto["chunk_id"], nome_arquivo, url
                    )
            paginas_v2[url] = {"titulo": pag.get("titulo", ""), "chunks": chunks}
        v2["arquivos"][nome_arquivo] = {"paginas": paginas_v2}
    return v2


def _registrar_bruto(ledger: dict, hash_chunk: str, chunk_id: str, arquivo: str, url: str):
    entrada = ledger["canonicos"].setdefault(
        hash_chunk, {"chunk_id": chunk_id, "refs": []}
    )
    entrada["refs"].append(_chave(arquivo, url))


# ─────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────
def carregar_ledger(caminho: str | None = None) -> dict:
    caminho = caminho or cfg.ARQUIVO_LEDGER
    if not os.path.exists(caminho):
        return novo_ledger()

    with open(caminho, "r", encoding="utf-8") as f:
        bruto = json.load(f)

    if bruto.get("_meta", {}).get("versao") == VERSAO_LEDGER:
        bruto.setdefault("canonicos", {})
        bruto.setdefault("arquivos", {})
        return bruto

    print("   [ledger] Formato v1 detectado. Migrando para v2 (nenhum vetor é tocado)...")
    v2 = migrar_v1_para_v2(bruto)
    print(
        f"   [ledger] Migrado: {len(v2['arquivos'])} arquivos, "
        f"{len(v2['canonicos'])} chunks canônicos."
    )
    return v2


def salvar_ledger(ledger: dict, caminho: str | None = None) -> None:
    """Escrita atômica: um `kill -9` no meio nunca deixa um JSON pela metade."""
    caminho = caminho or cfg.ARQUIVO_LEDGER
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporario, caminho)


def paginas_do_arquivo(ledger: dict, nome_arquivo: str) -> dict:
    return ledger["arquivos"].setdefault(nome_arquivo, {"paginas": {}})["paginas"]


# ─────────────────────────────────────────────
# Contagem de referência
# ─────────────────────────────────────────────
def adquirir(
    ledger: dict, hash_chunk: str, arquivo: str, url: str, fabricar_id
) -> tuple[str, bool]:
    """Registra que (arquivo, url) usa este texto de chunk.

    Devolve `(chunk_id, nascido)`. `nascido=False` significa que o texto já
    existe na nuvem sob outro id — é aqui que a duplicata deixa de virar um
    segundo vetor disputando as mesmas vagas do `top_k`.
    """
    entrada = ledger["canonicos"].get(hash_chunk)
    if entrada is not None:
        entrada["refs"].append(_chave(arquivo, url))
        return entrada["chunk_id"], False

    chunk_id = fabricar_id()
    ledger["canonicos"][hash_chunk] = {"chunk_id": chunk_id, "refs": [_chave(arquivo, url)]}
    return chunk_id, True


def liberar(ledger: dict, hash_chunk: str, arquivo: str, url: str) -> dict | None:
    """Solta UMA referência deste (arquivo, url) ao texto.

    Devolve:
      - `None` — ainda há quem use e o dono principal não mudou;
      - `{"acao": "morto", "chunk_id": ...}` — foi a última, pode deletar;
      - `{"acao": "realocado", "chunk_id": ..., "arquivo": ..., "url": ...}` —
        quem saiu era o dono do metadado; o chunk continua vivo, mas precisa ser
        reenviado apontando para a página que restou.
    """
    entrada = ledger["canonicos"].get(hash_chunk)
    if entrada is None:
        return None

    alvo = _chave(arquivo, url)
    era_principal = bool(entrada["refs"]) and entrada["refs"][0] == alvo
    try:
        entrada["refs"].remove(alvo)
    except ValueError:
        return None

    if not entrada["refs"]:
        del ledger["canonicos"][hash_chunk]
        return {"acao": "morto", "chunk_id": entrada["chunk_id"]}

    if era_principal:
        novo_arquivo, nova_url = entrada["refs"][0]
        # A mesma página pode citar o mesmo texto duas vezes. Nesse caso o dono
        # continua sendo ela, o metadado não muda e reenviar seria desperdício.
        if [novo_arquivo, nova_url] == alvo:
            return None
        return {
            "acao": "realocado",
            "chunk_id": entrada["chunk_id"],
            "arquivo": novo_arquivo,
            "url": nova_url,
        }
    return None


def total_de_chunks(ledger: dict) -> int:
    """Quantos vetores o ledger acredita existirem na nuvem."""
    return len(ledger["canonicos"])


# ─────────────────────────────────────────────
# Pendências de deleção
# ─────────────────────────────────────────────
def carregar_pendencias() -> list[str]:
    if not os.path.exists(cfg.ARQUIVO_PENDENCIAS):
        return []
    try:
        with open(cfg.ARQUIVO_PENDENCIAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def salvar_pendencias(ids: list[str]) -> None:
    os.makedirs(os.path.dirname(cfg.ARQUIVO_PENDENCIAS), exist_ok=True)
    temporario = cfg.ARQUIVO_PENDENCIAS + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(ids, f)
    os.replace(temporario, cfg.ARQUIVO_PENDENCIAS)


def limpar_pendencias() -> None:
    if os.path.exists(cfg.ARQUIVO_PENDENCIAS):
        os.remove(cfg.ARQUIVO_PENDENCIAS)
