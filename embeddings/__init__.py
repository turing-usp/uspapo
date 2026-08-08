"""Ingestão: limpeza, chunking e sincronização com o banco vetorial.

Os módulos daqui são importados como pacote (`from embeddings import ledger`),
inclusive pelos scripts executáveis, para que os testes em `tests/` consigam
importar as mesmas funções que o pipeline usa. Os entrypoints
(`clean_data.py`, `build_vector.py`, `reconciliar.py`) rodam via
`python -m embeddings.<modulo>` a partir da raiz do projeto.
"""
