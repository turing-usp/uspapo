"use client";
import React, { useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import Image from "next/image";

/* Estável de propósito: o useSyncExternalStore abaixo não observa nada. */
const assinarNada = () => () => {};

export default function LeftMenu() {
  const [isOpen, setIsOpen] = useState(false);
  /* O portal precisa do document, que não existe no render do servidor.
     useSyncExternalStore dá "já hidratou?" sem setState dentro de efeito
     e sem divergência de hidratação: false no servidor, true no cliente. */
  const montado = useSyncExternalStore(assinarNada, () => true, () => false);

  // Espelha o breakpoint md do Tailwind (48rem) em vez de repetir 768px em px.
  const fecharSeMobile = () => {
    if (!window.matchMedia("(min-width: 48rem)").matches) setIsOpen(false);
  };

  return (
    <>
      {/* Some enquanto o painel está aberto: o painel é translúcido, então o
          botão apareceria borrado por baixo dele.

          A opacidade vai nos pseudos do vidro (glass-fade) e no invólucro do
          ícone, nunca no botão: opacidade no hospedeiro faria dele um backdrop
          root e o backdrop-filter do vidro perderia a página no meio da
          transição. O transition-colors também é de propósito: com o
          `transition` cru, o delay-300 daqui embaixo atrasava o hover junto,
          e a cor saía 300ms depois da escala do ícone. */}
      <button
        onClick={() => setIsOpen(true)}
        className={`shrink-0 touch-manipulation glass glass-fade rounded-xl p-2.5 text-muted-foreground hover:text-brand transition-colors duration-200 cursor-pointer flex items-center justify-center group ${
          isOpen
            ? "[--glass-fade:0] [--glass-fade-dur:150ms] [--glass-fade-delay:0ms] pointer-events-none"
            : "[--glass-fade:1] [--glass-fade-dur:200ms] [--glass-fade-delay:300ms]"
        }`}
        aria-label="Abrir menu lateral"
        aria-expanded={isOpen}
        title="Abrir menu"
      >
        <span
          className="flex opacity-[var(--glass-fade)] transition-opacity ease-in-out duration-[var(--glass-fade-dur)] delay-[var(--glass-fade-delay)]"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
            className="w-6 h-6 transition-transform group-hover:scale-110"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"
            />
          </svg>
        </span>
      </button>

      {montado && createPortal(
        <>
      {/* Fundo escuro para fechar no celular ao clicar fora. Pelo mesmo motivo
          do botão, some junto com o painel em vez de sumir de uma vez.

          Aberto, ele anda os mesmos 16rem do painel (translate-x-64 = w-64) e
          começa exatamente onde o painel termina: o painel é translúcido e fica
          por cima (z-50), então o backdrop-filter dele amostraria este scrim e o
          menu sairia de uma cor no celular e de outra no desktop, onde o scrim é
          md:hidden. O que o scrim precisa cobrir para fechar ao clicar fora é
          justamente a área que o painel não ocupa, então nada se perde. O que
          sobra dele para fora da direita da tela não é visto.

          O deslocamento é transform, e não left, pelo mesmo motivo do painel:
          anima no compositor, sem recalcular layout a cada quadro. Como os dois
          usam a mesma distância, duração e curva, a borda do scrim gruda na
          borda do painel durante a transição inteira. */}
      <div
        onClick={() => setIsOpen(false)}
        aria-hidden
        className={`fixed inset-0 bg-scrim/10 dark:bg-scrim/25 backdrop-blur-sm z-40 md:hidden transition duration-300 ease-in-out ${
          isOpen ? "translate-x-64 opacity-100" : "translate-x-0 opacity-0 pointer-events-none"
        }`}
      />

      {/* Painel da Barra Lateral */}
      <aside
        aria-hidden={!isOpen}
        className={`fixed top-0 left-0 h-dvh w-64 md:w-72 glass glass-panel z-50 flex flex-col p-4 transition-transform duration-300 ease-in-out ${
          isOpen ? "translate-x-0" : "-translate-x-full pointer-events-none"
        }`}
      >
        {/* Cabeçalho do Menu com o Logo da USPapo ao lado do nome e o Botão 'X' para fechar */}
        <div className="flex items-center justify-between pb-4 border-b border-line/10">
          <div className="flex items-center gap-2.5">
            <Image
              src="/logo.svg"
              alt="USPapo Logo"
              width={32}
              height={32}
            />
            <span className="font-geom text-xl text-brand font-bold">
              USPapo
            </span>
          </div>
          <button
            onClick={() => setIsOpen(false)}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-brand hover:bg-tint/5 transition-colors cursor-pointer"
            aria-label="Fechar menu lateral"
            title="Fechar menu"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="w-6 h-6"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18 18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Lista de Navegação com Ícones e Nomes */}
        <nav className="flex flex-col gap-2 mt-4">
          <Link
            href="/"
            onClick={fecharSeMobile}
            className="flex items-center gap-3 px-3.5 py-3 rounded-xl text-muted-foreground hover:text-foreground hover:bg-brand/15 border border-transparent hover:border-brand/30 transition-all cursor-pointer group"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="w-5 h-5 text-brand group-hover:scale-110 transition-transform"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v6m3-3H9m12 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
              />
            </svg>
            <span className="font-geom text-sm font-medium">Novo Chat</span>
          </Link>

          <Link
            href="/historico"
            onClick={fecharSeMobile}
            className="flex items-center gap-3 px-3.5 py-3 rounded-xl text-muted-foreground hover:text-foreground hover:bg-brand/15 border border-transparent hover:border-brand/30 transition-all cursor-pointer group text-left w-full"
          >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={2}
                stroke="currentColor"
                className="w-5 h-5 text-brand group-hover:scale-110 transition-transform"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.602 10.602Z"
                />
              </svg>
              <span className="font-geom text-sm font-medium">
                Pesquisar histórico
              </span>
          </Link>

          <button
            onClick={fecharSeMobile}
            className="flex items-center gap-3 px-3.5 py-3 rounded-xl text-muted-foreground hover:text-foreground hover:bg-brand/15 border border-transparent hover:border-brand/30 transition-all cursor-pointer group text-left w-full"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="w-5 h-5 text-brand group-hover:rotate-90 transition-transform duration-500"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.43l-1.003.77a1.119 1.119 0 0 0-.362 1.18c.004.074.006.147.006.222a1.14 1.14 0 0 0 .006.222 1.119 1.119 0 0 0 .362 1.18l1.003.77a1.125 1.125 0 0 1 .26 1.43l-1.296 2.247a1.125 1.125 0 0 1-1.37.49l-1.216-.456a1.125 1.125 0 0 0-1.076.124a6.57 6.57 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281a1.125 1.125 0 0 0-.645-.87a6.528 6.528 0 0 1-.22-.127a1.125 1.125 0 0 0-1.075-.124l-1.217.456a1.125 1.125 0 0 1-1.37-.49l-1.296-2.247a1.125 1.125 0 0 1 .26-1.43l1.003-.77a1.119 1.119 0 0 0 .362-1.18a6.6 6.6 0 0 1-.006-.222c0-.074-.002-.148-.006-.222a1.119 1.119 0 0 0-.362-1.18l-1.003-.77a1.125 1.125 0 0 1-.26-1.43l1.296-2.247a1.125 1.125 0 0 1 1.37-.49l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128c.332-.183.582-.495.644-.869l.213-1.28Z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
              />
            </svg>
            <span className="font-geom text-sm font-medium">Configurações</span>
          </button>
        </nav>
      </aside>
        </>,
        document.body,
      )}
    </>
  );
}