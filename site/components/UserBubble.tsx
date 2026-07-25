"use client";
import { useState } from "react";

const LIMITE_CARACTERES = 150;

export function UserBubble({ text }: { text: string }) {
  const [expandido, setExpandido] = useState(false);
  const textoLongo = text.length > LIMITE_CARACTERES;
  const textoExibido = expandido || !textoLongo
    ? text
    : text.slice(0, LIMITE_CARACTERES) + "...";

  return (
    <div className="relative">
      {/* camada decorativa do glass, isolada, sempre atrás */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 rounded-[2rem] glass-radial-blur" />

      {/* conteúdo real, sempre na frente */}
      <div
        className="relative z-10 bg-[#F5F5F5]/20 text-[#FFFFFF] text-[1.2rem] px-[1.5rem] py-3 rounded-[2rem] max-w-full break-words"
        style={{
          boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.4), inset 0 -1px 1px rgba(255,255,255,0.05)'
        }}
      >
        <p className="whitespace-pre-wrap">{textoExibido}</p>
        {textoLongo && (
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