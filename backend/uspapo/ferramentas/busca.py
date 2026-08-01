"""Busca vetorial no Pinecone: a ferramenta do backend de verdade.

Importar este módulo já conecta ao Pinecone e exige a PINECONE_API_KEY — por
isso ele fica fora do núcleo, para o backend falso (ferramentas/simuladas.py)
nunca precisar da chave.
"""

import os

from pinecone import Pinecone

from uspapo import config
from uspapo.ferramentas import Registro

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "uspapo-embeddings")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "uspapo")

EMBED_MODEL = "multilingual-e5-large"

if not PINECONE_API_KEY:
    raise RuntimeError("A chave PINECONE_API_KEY não foi encontrada no arquivo .env!")

# Conexão ÚNICA, feita ao subir o servidor.
print("-> Iniciando motor Cloud-Native...")
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX)

registro = Registro()


@registro.ferramenta(
    nome="buscar_documentos",
    descricao=(
        "Busca trechos de documentos oficiais da USP (graduação, matrícula, "
        "unidades, cursos, serviços ao aluno) numa base vetorial. Use SEMPRE "
        "que a pergunta exigir uma informação factual sobre a USP."
    ),
    parametros={
        "type": "object",
        "properties": {
            "consulta": {
                "type": "string",
                "description": (
                    "A busca, em português, reformulada com os termos que "
                    "provavelmente aparecem no documento oficial."
                ),
            },
            "limite": {
                "type": "integer",
                "description": f"Quantos trechos retornar (1 a {config.TOP_K_MAX}).",
                "default": config.TOP_K_PADRAO,
            },
        },
        "required": ["consulta"],
    },
)
def buscar_documentos(
    consulta: str, limite: int = config.TOP_K_PADRAO
) -> tuple[str, list[str]]:
    """Vetoriza a consulta via API e busca no Pinecone.

    Devolve o texto já formatado para o modelo ler e as URLs consultadas.
    """
    consulta = str(consulta).strip()
    if not consulta:
        return "O campo 'consulta' é obrigatório.", []

    try:
        limite = int(limite)
    except (TypeError, ValueError):
        limite = config.TOP_K_PADRAO
    limite = max(1, min(limite, config.TOP_K_MAX))

    embed_result = pc.inference.embed(
        model=EMBED_MODEL,
        inputs=[f"query: {consulta}"],
        parameters={"input_type": "query"},
    )

    resultados = index.query(
        namespace=PINECONE_NAMESPACE,
        vector=embed_result[0].values,
        top_k=limite,
        include_metadata=True,
    )

    blocos: list[str] = []
    urls: list[str] = []

    for posicao, match in enumerate(resultados.matches, 1):
        meta = match.metadata or {}
        # A ingestão grava "passage: {chunk}" (convenção do e5), mas talvez não
        # precise do remove prefix
        texto = (meta.get("text") or "").removeprefix("passage: ").strip()
        if not texto:
            continue

        titulo = meta.get("titulo") or "Sem título"
        url = meta.get("url") or "URL desconhecida"
        blocos.append(f"[{posicao}] {titulo} — {url}\n{texto}")
        urls.append(url)

    if not blocos:
        return "Nenhum documento encontrado para esta consulta.", []

    return "\n\n---\n\n".join(blocos), urls
