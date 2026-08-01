"use client";
import { useJanelaVisual } from "@/lib/janela";

/* Casca de altura fixa: o documento não rola, o scroll acontece dentro do
   .app-scroll de cada página.

   O fundo mora aqui, e não no <body>, para dividir a mesma caixa com as
   camadas dissolvidas (page-fade-b / page-fade-t) que as páginas renderizam
   como irmãs — é o que garante o alinhamento em qualquer navegador. */
export default function AppShell({ children }: { children: React.ReactNode }) {
  useJanelaVisual();

  return (
    <div className="app-shell">
      <div aria-hidden className="page-backdrop" />
      {children}
    </div>
  );
}
