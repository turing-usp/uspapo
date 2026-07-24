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
    <div
      className="bg-[#F5F5F5]/20 text-[#FFFFFF] text-[1.2rem] px-[1.5rem] py-3 rounded-[2rem] max-w-full break-words"
      style={{
        boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.4), inset 0 -1px 1px rgba(255,255,255,0.05)'
      }}
    >
      <p className="whitespace-pre-wrap">{textoExibido}</p>
      {textoLongo && (
        <button
          onClick={() => setExpandido((v) => !v)}
          className="text-[#f1863d] text-sm mt-1 hover:underline"
        >
          {expandido ? "ver menos" : "ver mais"}
        </button>
      )}
    </div>
  );
}