"""Confere o que o ledger acredita contra o que o Pinecone realmente tem.

O ledger é um espelho, e espelho descola da realidade: uma execução interrompida
no meio, uma deleção que não completou, um índice mexido à mão. Duas formas de
divergência, com gravidades bem diferentes:

- **Órfão** (está no Pinecone, não está no ledger): custa armazenamento e pode
  devolver na busca um trecho de página que já saiu do ar. Ruim, mas visível.
- **Faltante** (está no ledger, não está no Pinecone): é o pior caso, porque é
  silencioso: o pipeline acha que já enviou aquele trecho e nunca mais tenta, e
  a busca simplesmente não encontra o que deveria.

Sem `--aplicar`, só relata. É o padrão de propósito: reconciliação que apaga
sozinha, num dia em que o ledger esteja errado, apaga o índice inteiro.

Roda como `python -m embeddings.reconciliar` a partir da raiz do projeto.
"""

import argparse
import json
import os
from datetime import datetime

from embeddings import config_vetor as cfg
from embeddings import ledger as L


def listar_ids_remotos(index) -> set[str]:
    """Todos os ids do namespace.

    O formato de id (`arquivo_hashurl_chN_hashchunk`) é prefixável de propósito,
    o que permitiria paginar por arquivo se um dia o índice ficar grande demais
    para uma varredura inteira.
    """
    remotos: set[str] = set()
    for pagina in index.list(namespace=cfg.PINECONE_NAMESPACE):
        # O `list()` do pinecone 9.x devolve um `ListResponse` por página, com
        # `.vectors` de `ListItem(id=...)`. Versões mais antigas devolviam a
        # lista de ids crua, e há quem devolva o id solto — os três casos abaixo.
        vetores = getattr(pagina, "vectors", None)
        if vetores is not None:
            remotos.update(getattr(v, "id", v) for v in vetores)
        elif isinstance(pagina, (list, tuple)):
            remotos.update(getattr(v, "id", v) for v in pagina)
        else:
            remotos.add(getattr(pagina, "id", pagina))
    return remotos


def ids_do_ledger(ledger: dict) -> set[str]:
    return {entrada["chunk_id"] for entrada in ledger["canonicos"].values()}


def reconciliar(aplicar: bool = False) -> dict:
    from pinecone import Pinecone

    pc = Pinecone(api_key=cfg.exigir_api_key())
    index = pc.Index(cfg.PINECONE_INDEX)

    ledger = L.carregar_ledger()
    locais = ids_do_ledger(ledger)
    remotos = listar_ids_remotos(index)

    orfaos = sorted(remotos - locais)
    faltantes = sorted(locais - remotos)

    print("=" * 56)
    print("RECONCILIAÇÃO")
    print("=" * 56)
    print(f" No ledger        : {len(locais)}")
    print(f" No Pinecone      : {len(remotos)}")
    print(f" Órfãos (só nuvem): {len(orfaos)}")
    print(f" Faltantes (só ledger): {len(faltantes)}")
    print("=" * 56)

    for titulo, lista in (("ÓRFÃOS", orfaos), ("FALTANTES", faltantes)):
        for chunk_id in lista[:5]:
            print(f"   [{titulo}] {chunk_id[:96]}")

    if faltantes:
        print(
            "\n[ATENÇÃO] Faltante é falha silenciosa de busca. Para reenviar, apague as "
            "entradas correspondentes do ledger e rode o build_vector — ele os recriará."
        )

    relatorio = {
        "data": datetime.now().isoformat(timespec="seconds"),
        "no_ledger": len(locais),
        "no_pinecone": len(remotos),
        "orfaos": len(orfaos),
        "faltantes": len(faltantes),
        "amostra_orfaos": orfaos[:50],
        "amostra_faltantes": faltantes[:50],
        "aplicado": False,
    }

    if orfaos and aplicar:
        print(f"\n-> Removendo {len(orfaos)} órfão(s)...")
        for i in range(0, len(orfaos), cfg.LOTE_DELETE):
            index.delete(ids=orfaos[i : i + cfg.LOTE_DELETE], namespace=cfg.PINECONE_NAMESPACE)
        relatorio["aplicado"] = True
        print("   feito.")
    elif orfaos:
        print("\n(rode com --aplicar para remover os órfãos)")

    os.makedirs(cfg.PASTA_RELATORIOS, exist_ok=True)
    destino = os.path.join(cfg.PASTA_RELATORIOS, "reconciliacao.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)
    print(f"\nRelatório: {os.path.relpath(destino, cfg.RAIZ_PROJETO)}")
    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara o ledger com o índice do Pinecone.")
    parser.add_argument("--aplicar", action="store_true", help="Apaga os órfãos de verdade.")
    argumentos = parser.parse_args()
    reconciliar(aplicar=argumentos.aplicar)


if __name__ == "__main__":
    main()
