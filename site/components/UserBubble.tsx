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
    <div className="relative max-w-[85%] sm:max-w-[75%]">
      {/* camada decorativa do glass, isolada, sempre atrás */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 rounded-[2rem] glass-radial-blur" />

      {/* conteúdo real, sempre na frente */}
      <div
        className="relative z-10 bg-[#F5F5F5]/20 text-[#FFFFFF] text-lg px-5 py-3 rounded-[2rem] break-words"
        style={{
          boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.4), inset 0 -1px 1px rgba(255,255,255,0.05)'
        }}
      >
        <p
          ref={textoRef}
          className={`whitespace-pre-wrap ${expandido ? "" : CLAMP_COLAPSADO}`}
        >
          {text}
        </p>
        {temOverflow && (
          <button
            onClick={() => setExpandido((v) => !v)}
            className="text-[#f1863d] text-sm mt-1 hover:underline hover:cursor-pointer"
          >
            {expandido ? "ver menos" : "ver mais"}
          </button>
        )}
      </div>
    </div>
  );
}
