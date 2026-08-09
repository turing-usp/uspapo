"""Os endpoints: a ponte com o Next.js.

    POST /chat  {"pergunta": "..."}                  -> {"resposta", "fontes"}
    POST /chat  {"pergunta": "...", "stream": true}  -> text/event-stream
    GET  /health

O corpo do /chat aceita ainda "historico": [{"pergunta", "resposta"}, ...] com
os turnos anteriores da conversa.

O /chat exige login: `Authorization: Bearer <access token do Supabase>`. A
portaria roda antes de qualquer trabalho e responde 401 (sem token ou token
inválido), 403 (conta fora da whitelist), 429 (rate limit) ou 503 (não deu para
falar com o JWKS do Supabase).
"""

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from uspapo import acesso, config, contas, saude
from uspapo.contexto import Orcamento, normalizar_historico
from uspapo.conversa import executar_conversa
from uspapo.limites import verificar_limite
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
    print("-> Contas:", aviso or "reconhecidas pelo JWKS do Supabase")
    print("-> Acesso:", acesso.aviso_de_configuracao())
    sobras = config.aviso_de_variaveis_mortas()
    if sobras:
        print("-> Atenção:", sobras)

    @app.route("/chat", methods=["POST"])
    def chat():
        # A portaria inteira antes de ler o corpo do pedido: quem não passa daqui
        # não custa uma chamada de LLM nem uma busca no Pinecone.
        try:
            conta = contas.conta_do_pedido()
        except contas.FalhaDeVerificacao as erro:
            # Não é culpa de quem perguntou, então não mandamos fazer login: a
            # sessão dele provavelmente está boa e o que faltou foi o JWKS.
            print(f"Não deu para verificar o token: {erro}")
            return jsonify({
                "erro": "Não consegui confirmar seu login agora. "
                        "Tente de novo em instantes."
            }), 503

        if conta is None:
            return jsonify({
                "erro": "Entre com sua conta para conversar com o USPapo."
            }), 401

        if not acesso.liberado(conta.email):
            return jsonify({
                "erro": "O USPapo ainda está em teste fechado e esta conta não "
                        "está na lista de acesso."
            }), 403

        excedeu = verificar_limite(f"conta:{conta.id}")
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
        # O id da conversa permite relacionar o turno persistido ao log medido.
        session_id = dados.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            session_id = None
        eventos = executar_conversa(
            provedores, registro, orcamento, pergunta, historico,
            user_id=conta.id,
            session_id=session_id,
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
            # Só o estado da portaria, nunca os emails da lista.
            "whitelist": acesso.panorama(),
            "indice": rotulo_indice,
            # Com dois conjuntos de ferramentas possíveis, é a forma mais rápida
            # de saber qual backend está no ar.
            "ferramentas": sorted(registro.nomes),
        })

    @app.route("/api/analytics/resumo", methods=["GET"])
    def analytics_resumo():
        chave_admin = request.headers.get("X-Admin-Key", "")
        if chave_admin != config.ADMIN_API_KEY:
            return jsonify({"ok": False, "erro": "Acesso não autorizado ao painel de analytics."}), 403

        try:
            from uspapo.analytics import obter_resumo_executivo
            resumo = obter_resumo_executivo()
            return jsonify({"ok": True, "data": resumo}), 200
        except Exception as e:
            return jsonify({"ok": False, "erro": str(e)}), 500

    return app


def rodar(app: Flask) -> None:
    """Sobe o servidor de desenvolvimento (o Render injeta a porta em PORT)."""
    app.run(host="0.0.0.0", port=config.PORTA)
