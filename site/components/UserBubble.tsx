"use client";
import { useLayoutEffect, useRef, useState } from "react";

// Literal: o Tailwind não gera classes montadas em runtime.
const CLAMP_COLAPSADO = "line-clamp-3";

export function UserBubble({ text }: { text: string }) {
  const [expandido, setExpandido] = useState(false);
  const [temOverflow, setTemOverflow] = useState(false);
  const textoRef = useRef<HTMLParagraphElement>(null);

  useLayoutEffect(() => {
    const el = textoRef.current;
    if (!el || expandido) return;

    const medir = () => {
      if (el.scrollHeight > el.clientHeight + 1) setTemOverflow(true);
    };

    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(el);
    return () => observador.disconnect();
  }, [text, expandido]);

  return (
    <div className="glass max-w-[85%] sm:max-w-[75%] text-foreground text-lg px-5 py-3 rounded-[2rem] break-words">
      <p
        ref={textoRef}
        className={`whitespace-pre-wrap ${expandido ? "" : CLAMP_COLAPSADO}`}
      >
        {text}
      </p>
      {temOverflow && (
        <button
          onClick={() => setExpandido((v) => !v)}
          className="text-brand text-sm mt-1 hover:underline hover:cursor-pointer"
        >
          {expandido ? "ver menos" : "ver mais"}
        </button>
      )}
    </div>
  );
}
