"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown, Check, X } from "lucide-react";
import { salvarFeedback, removerFeedback, type FeedbackItem } from "@/lib/feedback";

const MOTIVOS_SUGERIDOS = [
  "Informação incorreta",
  "Resposta incompleta",
  "Resposta confusa",
  "Outro",
];

interface FeedbackBotProps {
  conversaId: string;
  mensagemOrdem: number;
  feedbackInicial?: FeedbackItem | null;
  disabled?: boolean;
}

export default function FeedbackBot({
  conversaId,
  mensagemOrdem,
  feedbackInicial,
  disabled = false,
}: FeedbackBotProps) {
  const [likeState, setLikeState] = useState<"none" | "like" | "dislike">(
    feedbackInicial?.tipo ?? "none"
  );
  const [mostrarForm, setMostrarForm] = useState(false);
  const [motivoSelecionado, setMotivoSelecionado] = useState<string>(
    feedbackInicial?.motivo ?? ""
  );
  const [comentario, setComentario] = useState<string>(
    feedbackInicial?.comentario ?? ""
  );
  const [salvando, setSalvando] = useState(false);
  const [enviado, setEnviado] = useState(false);

  const lidarComLike = async () => {
    if (disabled || salvando) return;
    const novoTipo = likeState === "like" ? "none" : "like";
    setLikeState(novoTipo);
    setMostrarForm(false);
    setEnviado(false);

    setSalvando(true);
    if (novoTipo === "like") {
      await salvarFeedback({
        conversaId,
        mensagemOrdem,
        tipo: "like",
      });
    } else {
      await removerFeedback({
        conversaId,
        mensagemOrdem,
      });
    }
    setSalvando(false);
  };

  const lidarComDislike = async () => {
    if (disabled || salvando) return;
    const novoTipo = likeState === "dislike" ? "none" : "dislike";
    setLikeState(novoTipo);
    setEnviado(false);

    setSalvando(true);
    if (novoTipo === "dislike") {
      setMostrarForm(true);
      // Registra o dislike no banco imediatamente
      await salvarFeedback({
        conversaId,
        mensagemOrdem,
        tipo: "dislike",
        motivo: motivoSelecionado || undefined,
        comentario: comentario || undefined,
      });
    } else {
      setMostrarForm(false);
      await removerFeedback({
        conversaId,
        mensagemOrdem,
      });
    }
    setSalvando(false);
  };

  const enviarComentario = async (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled || salvando) return;

    setSalvando(true);
    const sucesso = await salvarFeedback({
      conversaId,
      mensagemOrdem,
      tipo: "dislike",
      motivo: motivoSelecionado || undefined,
      comentario: comentario.trim() || undefined,
    });
    setSalvando(false);

    if (sucesso) {
      setEnviado(true);
      setTimeout(() => {
        setMostrarForm(false);
      }, 2000);
    }
  };

  return (
    <div className="mt-2.5 flex flex-col items-start font-roboto text-sm">
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <span className="text-xs text-muted-foreground/70">A resposta foi útil?</span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={lidarComLike}
            disabled={disabled}
            title="Resposta útil (Like)"
            className={`p-1.5 rounded-lg transition-colors flex items-center justify-center ${likeState === "like"
              ? "bg-brand/15 text-brand"
              : "hover:bg-tint/10 text-muted-foreground hover:text-foreground"
              }`}
          >
            <ThumbsUp className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={lidarComDislike}
            disabled={disabled}
            title="Resposta ruim (Dislike)"
            className={`p-1.5 rounded-lg transition-colors flex items-center justify-center ${likeState === "dislike"
              ? "bg-danger/15 text-danger"
              : "hover:bg-tint/10 text-muted-foreground hover:text-foreground"
              }`}
          >
            <ThumbsDown className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* A superfície é a lâmina de vidro do resto do site, e não uma borda com
          véu montada na mão. As classes animate-in/slide-in-from-top-2 que
          moravam aqui eram no-op: tailwindcss-animate não é dependência do
          projeto. */}
      {mostrarForm && (
        <div className="glass mt-3 w-full max-w-lg p-4 rounded-2xl">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium text-foreground">
              Como podemos melhorar esta resposta?
            </p>
            <button
              type="button"
              onClick={() => setMostrarForm(false)}
              className="text-muted-foreground hover:text-foreground p-1 rounded-md"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {enviado ? (
            <div className="flex items-center gap-2 py-2 text-brand text-sm font-medium">
              <Check className="w-4 h-4" />
              <span>Obrigado pelo seu feedback! Ele nos ajuda a melhorar.</span>
            </div>
          ) : (
            <form onSubmit={enviarComentario} className="flex flex-col gap-3 mt-2">
              <div className="flex flex-wrap gap-1.5">
                {MOTIVOS_SUGERIDOS.map((motivo) => {
                  const selecionado = motivoSelecionado === motivo;
                  return (
                    <button
                      key={motivo}
                      type="button"
                      onClick={() =>
                        setMotivoSelecionado(selecionado ? "" : motivo)
                      }
                      className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${selecionado
                        ? "border-brand bg-brand/10 text-brand font-medium"
                        : "border-line/20 text-muted-foreground hover:border-line/40 hover:text-foreground"
                        }`}
                    >
                      {motivo}
                    </button>
                  );
                })}
              </div>

              {/* Campo de vidro, como a busca do histórico: o fio neutro que
                  acende na marca ao focar vem do glass-field. O bg-background
                  que estava aqui não é token deste projeto (os válidos são
                  canvas/surface/surface-raised) e não resolvia para nada. */}
              <div className="glass glass-field w-full rounded-xl">
                <textarea
                  value={comentario}
                  onChange={(e) => setComentario(e.target.value)}
                  placeholder="Conte detalhadamente o que esteve errado (opcional)..."
                  rows={3}
                  className="w-full p-2.5 bg-transparent border-0 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none resize-none"
                />
              </div>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setMostrarForm(false)}
                  className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground rounded-lg transition-colors"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={salvando}
                  className="px-4 py-1.5 text-xs bg-brand text-brand-foreground hover:bg-brand/90 font-medium rounded-lg transition-colors disabled:opacity-50"
                >
                  {salvando ? "Enviando..." : "Enviar feedback"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
