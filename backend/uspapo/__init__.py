"""Núcleo do backend do USPapo.

O que muda entre um backend e outro é só o registro de ferramentas; tudo o mais
mora aqui e é compartilhado.

    config       .env e as constantes de todo mundo
    provedores   cadeia LLM_PROVIDERS -> clientes OpenAI, com fallback
    prompt       prompt de sistema, com a data de hoje
    limites      rate limit por aparelho (X-Device-Id)
    contexto     orçamento de tokens e poda do histórico
    conteudo     separa <think>/<tool_call> do texto, token a token
    toolcalls    parsers de tool call inline e o coletor da rodada
    conversa     o motor: laço de ferramentas e queda para o próximo provedor
    saida        os eventos viram SSE ou o JSON legado
    web          criar_app(): CORS, /chat e /health
    ferramentas  o registro e as ferramentas de cada backend
"""
