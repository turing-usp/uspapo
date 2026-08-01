"""Os endpoints: a ponte com o Next.js.

    POST /chat  {"pergunta": "..."}                  -> {"resposta", "fontes"}
    POST /chat  {"pergunta": "...", "stream": true}  -> text/event-stream
    GET  /health

O corpo do /chat aceita ainda "historico": [{"pergunta", "resposta"}, ...] com
os turnos anteriores da conversa (o frontend guarda tudo no localStorage).
"""

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from uspapo import config
from uspapo.contexto import Orcamento, normalizar_historico
from uspapo.conversa import executar_conversa
from uspapo.limites import identificar_cliente, verificar_limite
from uspapo.provedores import carregar_provedores
from uspapo.saida import agregar, gerar_sse


def criar_app(registro, *, rotulo_indice: str) -> Flask:
    """Monta o Flask com CORS, /chat e /health sobre o registro dado.

    É o registro de ferramentas que separa o backend de verdade do backend
    falso; todo o resto — cadeia de provedores, orçamento, rate limit, stream —
    é o mesmo nos dois.
    """
    app = Flask(__name__)

    CORS(app, resources={
        r"/*": {
            "origins": config.ORIGENS_CORS,
            "allow_headers": config.HEADERS_CORS,
        }
    })

    provedores = carregar_provedores()
    orcamento = Orcamento(registro)

    print("-> Cadeia de LLMs:", " -> ".join(p.nome for p in provedores))
    print("-> Ferramentas:", ", ".join(sorted(registro.nomes)))

    @app.route("/chat", methods=["POST"])
    def chat():
        # Antes de qualquer trabalho: quem estourou o limite não custa nada.
        excedeu = verificar_limite(identificar_cliente())
        if excedeu:
            janela, espera = excedeu
            resposta = jsonify({
                "erro": f"Você fez muitas perguntas em pouco tempo (limite por {janela}). "
                        "Espere um pouquinho e tente de novo.",
                "limite": janela,
                "retry_after": espera,
            })
            # O Retry-After vai também no corpo: sem expose_headers no CORS, o
            # navegador não consegue ler headers customizados da resposta.
            resposta.headers["Retry-After"] = str(espera)
            return resposta, 429

        dados = request.get_json(silent=True)

        if not dados or "pergunta" not in dados:
            return jsonify({"erro": "Campo 'pergunta' é obrigatório"}), 400

        pergunta = str(dados["pergunta"]).strip()

        if not pergunta:
            return jsonify({"erro": "Pergunta vazia"}), 400

        historico = normalizar_historico(dados.get("historico"))
        eventos = executar_conversa(
            provedores, registro, orcamento, pergunta, historico
        )

        if dados.get("stream"):
            resposta = Response(
                stream_with_context(gerar_sse(eventos)),
                mimetype="text/event-stream",
            )
            resposta.headers["Cache-Control"] = "no-cache"
            resposta.headers["Connection"] = "keep-alive"
            # Sem isto o proxy do Render bufferiza o corpo e o streaming não aparece.
            resposta.headers["X-Accel-Buffering"] = "no"
            return resposta

        try:
            corpo, status = agregar(eventos)
        except Exception as erro:
            print(f"Erro ao processar pergunta: {erro}")
            return jsonify({"erro": "Erro interno ao processar a pergunta no servidor."}), 500

        return jsonify(corpo), status

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "ok": True,
            "provedores": [p.nome for p in provedores],
            "indice": rotulo_indice,
            # Com dois conjuntos de ferramentas possíveis, é a forma mais rápida
            # de saber qual backend está no ar.
            "ferramentas": sorted(registro.nomes),
        })

    return app


def rodar(app: Flask) -> None:
    """Sobe o servidor de desenvolvimento (o Render injeta a porta em PORT)."""
    app.run(host="0.0.0.0", port=config.PORTA)
