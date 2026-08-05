"""Os endpoints: a ponte com o Next.js.

    POST /chat  {"pergunta": "..."}                  -> {"resposta", "fontes"}
    POST /chat  {"pergunta": "...", "stream": true}  -> text/event-stream
    GET  /health

O corpo do /chat aceita ainda "historico": [{"pergunta", "resposta"}, ...] com
os turnos anteriores da conversa (o frontend guarda tudo no localStorage).
"""

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from uspapo import config, contas, saude
from uspapo.contexto import Orcamento, normalizar_historico
from uspapo.conversa import executar_conversa
from uspapo.limites import identificar_cliente, verificar_limite
from uspapo.provedores import carregar_provedores
from uspapo.saida import agregar, gerar_sse


def _espera_legivel(segundos: int) -> str:
    """'em 40 segundos', 'em 3 minutos': o que o aluno precisa saber.

    Dizer o tempo concreto é melhor do que nomear a janela estourada: "limite
    por 10 minutos" não responde a única pergunta de quem levou o bloqueio, que
    é quando pode perguntar de novo.
    """
    if segundos < 60:
        return f"em {segundos} segundo{'s' if segundos != 1 else ''}"

    minutos = round(segundos / 60)
    if minutos < 60:
        return f"em {minutos} minuto{'s' if minutos != 1 else ''}"

    horas = round(minutos / 60)
    return f"em {horas} hora{'s' if horas != 1 else ''}"


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
    aviso = contas.aviso_de_configuracao()
    print("-> Contas:", aviso or "reconhecidas pelo token do Supabase")

    @app.route("/chat", methods=["POST"])
    def chat():
        # Antes de qualquer trabalho: quem estourou o limite não custa nada.
        chave, escada = identificar_cliente()
        excedeu = verificar_limite(chave, escada)
        if excedeu:
            janela, espera = excedeu
            resposta = jsonify({
                "erro": f"Você perguntou bastante coisa em pouco tempo! "
                        f"Pode voltar a perguntar {_espera_legivel(espera)}.",
                "limite": janela,
                "retry_after": espera,
            })
            # O Retry-After vai também no corpo: sem expose_headers no CORS, o
            # navegador não consegue ler headers customizados da resposta.
            resposta.headers["Retry-After"] = str(espera)
            return resposta, 429

        dados = request.get_json(silent=True)

        if not dados or "pergunta" not in dados:
            return jsonify({"erro": "Não recebi nenhuma pergunta. Tente escrever de novo."}), 400

        pergunta = str(dados["pergunta"]).strip()

        if not pergunta:
            return jsonify({"erro": "Sua pergunta chegou vazia. Escreva o que você quer saber!"}), 400

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
            return jsonify({"erro": "Deu algo errado por aqui. Tente perguntar de novo!"}), 500

        return jsonify(corpo), status

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "ok": True,
            "provedores": [p.nome for p in provedores],
            # Quanto falta de castigo em cada provedor: é o que responde "por
            # que a cadeia está caindo para o segundo?" sem abrir o log.
            "castigos": saude.panorama([p.nome for p in provedores]),
            "contas": contas.disponivel(),
            "indice": rotulo_indice,
            # Com dois conjuntos de ferramentas possíveis, é a forma mais rápida
            # de saber qual backend está no ar.
            "ferramentas": sorted(registro.nomes),
        })

    return app


def rodar(app: Flask) -> None:
    """Sobe o servidor de desenvolvimento (o Render injeta a porta em PORT)."""
    app.run(host="0.0.0.0", port=config.PORTA)
