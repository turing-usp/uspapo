"use client";
import { useLayoutEffect, useRef } from "react";

/* Cresce até aqui e depois rola por dentro. */
const ALTURA_MAXIMA = "40vh";

export default function PromptInput({ value, onChange, onSubmit, disabled = false }: { value: string; onChange: (value: string) => void; onSubmit: (e: React.SyntheticEvent) => void; disabled?: boolean; }) {
  const campoRef = useRef<HTMLTextAreaElement>(null);

  /* Auto-resize: zera a altura para o scrollHeight refletir só o conteúdo. */
  useLayoutEffect(() => {
    const el = campoRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  const aoTeclar = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    /* isComposing: não roubar o Enter de quem está montando um caractere no IME. */
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (disabled) return;
      onSubmit(e);
    }
  };

  /* Enquanto trava, o botão continua sendo o de enviar: trocar para o microfone
     no meio do envio pareceria que a pergunta se perdeu. */
  const temTexto = value.trim().length > 0;
  const podeEnviar = temTexto && !disabled;

  return (
    <form onSubmit={onSubmit} className="w-full">
      {/* items-end mantém os botões na base conforme o campo cresce. */}
      <div className="glass glass-brand flex items-end gap-1 w-full p-2 rounded-[1.75rem]">
        <button
          type="button"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand cursor-pointer"
          aria-label="Anexar arquivo"
        >
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14m-7-7h14" />
          </svg>
        </button>

        <textarea
          ref={campoRef}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={aoTeclar}
          disabled={disabled}
          /* text-[1rem] e não text-base: abaixo de 16px o iOS dá zoom ao focar. */
          className="min-w-0 flex-1 resize-none overflow-y-auto border-0 bg-transparent py-2.5 text-[1rem] md:text-lg leading-6 text-foreground caret-brand placeholder:text-muted-foreground focus:outline-none disabled:cursor-default"
          style={{ maxHeight: ALTURA_MAXIMA }}
          placeholder="Pesquise sobre a USP"
        />

        <button
          type={podeEnviar ? "submit" : "button"}
          disabled={disabled}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand cursor-pointer disabled:cursor-default disabled:opacity-60"
          aria-label={temTexto ? "Enviar pergunta" : "Falar"}
        >
          {/* As key são obrigatórias, e não decoração: sem elas os dois ramos
              são <span> na mesma posição, então o React reaproveita o nó e só
              troca a className. */}
          {temTexto ? (
            <span key="enviar" className="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-brand-foreground transition-colors hover:bg-brand-strong">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5m0 0l-6 6m6-6l6 6" />
              </svg>
            </span>
          ) : (
            <span key="falar" className="text-muted-foreground transition-colors hover:text-brand">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M18 11a6 6 0 0 1-12 0M12 17v4m-3 0h6" />
              </svg>
            </span>
          )}
        </button>
      </div>
    </form>
  );
}
