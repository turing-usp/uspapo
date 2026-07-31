"use client";
import { useState, useRef, useEffect } from "react";

type Props = {
  favorita: boolean;
  onFavoritar: () => void;
  onRenomear: () => void;
  onApagar: () => void;
};

export function MenuConversa({ favorita, onFavoritar, onRenomear, onApagar }: Props) {
  const [aberto, setAberto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!aberto) return;

    const aoClicarFora = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setAberto(false);
    };
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAberto(false);
    };

    document.addEventListener("mousedown", aoClicarFora);
    document.addEventListener("keydown", aoTeclar);
    return () => {
      document.removeEventListener("mousedown", aoClicarFora);
      document.removeEventListener("keydown", aoTeclar);
    };
  }, [aberto]);

  const acao = (fn: () => void) => (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setAberto(false);
    fn();
  };

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setAberto((v) => !v); }}
        aria-label="Ações da conversa"
        aria-expanded={aberto}
        className="p-2 rounded-lg text-[#AEB8CF] hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
      >
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
          <circle cx="5" cy="12" r="1.8" />
          <circle cx="12" cy="12" r="1.8" />
          <circle cx="19" cy="12" r="1.8" />
        </svg>
      </button>

      {aberto && (
        <div className="absolute right-0 top-full mt-1 z-50 w-44 py-1 rounded-xl bg-[#0a0d3c] border border-white/15 shadow-2xl">
          <button onClick={acao(onFavoritar)} className="w-full text-left px-4 py-2.5 text-sm text-[#AEB8CF] hover:text-white hover:bg-white/5 transition-colors cursor-pointer">
            {favorita ? "Remover dos favoritos" : "Favoritar"}
          </button>
          <button onClick={acao(onRenomear)} className="w-full text-left px-4 py-2.5 text-sm text-[#AEB8CF] hover:text-white hover:bg-white/5 transition-colors cursor-pointer">
            Renomear
          </button>
          <button onClick={acao(onApagar)} className="w-full text-left px-4 py-2.5 text-sm text-[#AEB8CF] hover:text-red-400 hover:bg-white/5 transition-colors cursor-pointer">
            Apagar
          </button>
        </div>
      )}
    </div>
  );
}