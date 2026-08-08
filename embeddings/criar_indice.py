"""Cria o índice do Pinecone, se ele ainda não existir.

Existe porque o `build_vector.py` deliberadamente **não** cria índice nenhum:
uma ferramenta que roda todo dia às 5h e tem permissão de criar recurso na nuvem
é uma ferramenta que, no dia em que a variável `PINECONE_INDEX` vier com um typo,
cria um índice vazio e reindexa o acervo inteiro dentro dele sem ninguém notar.
Separado, o passo é explícito e acontece uma vez.

O índice precisa ser de **inferência integrada**: o `build_vector` envia texto
com `upsert_records`, não vetores, e é o Pinecone que roda o
`multilingual-e5-large`. Um índice comum criado com `create_index` aceitaria a
conexão e recusaria todo upsert.

O `field_map` aponta para o campo `text` dos registros — o mesmo nome que o
`_registro()` do build_vector monta e que o backend lê de volta em
`ferramentas/busca.py`. Os três precisam concordar.

Roda como `python -m embeddings.criar_indice` a partir da raiz do projeto.
"""

import argparse

from embeddings import config_vetor as cfg

MODELO = "multilingual-e5-large"
NUVEM = "aws"
REGIAO = "us-east-1"


def criar_indice(nome: str | None = None) -> dict:
    """Idempotente: se o índice já existe, só descreve e sai."""
    from pinecone import Pinecone

    nome = nome or cfg.PINECONE_INDEX
    pc = Pinecone(api_key=cfg.exigir_api_key())

    existentes = [i["name"] for i in pc.list_indexes()]
    if nome in existentes:
        print(f"O índice '{nome}' já existe. Nada a fazer.")
        return pc.describe_index(nome).to_dict()

    print(f"-> Criando '{nome}' com inferência integrada ({MODELO})...")
    pc.create_index_for_model(
        name=nome,
        cloud=NUVEM,
        region=REGIAO,
        embed={"model": MODELO, "field_map": {"text": "text"}},
    )

    descricao = pc.describe_index(nome).to_dict()
    print(f"   pronto: dimensão {descricao.get('dimension')}, host {descricao.get('host')}")
    return descricao


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria o índice do Pinecone (idempotente).")
    parser.add_argument("--nome", default=None, help="Sobrepõe a PINECONE_INDEX do .env.")
    argumentos = parser.parse_args()
    criar_indice(argumentos.nome)


if __name__ == "__main__":
    main()
