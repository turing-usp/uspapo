"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import Image from "next/image";

export default function LeftMenu() {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    // Abrir por padrão em telas desktop (>= 768px) e manter fechado no celular
    if (window.innerWidth >= 768) {
      setIsOpen(true);
    }
  }, []);

  return (
    <>
      {/* Botão para abrir o menu (exibido no canto superior esquerdo quando a barra lateral está fechada) */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed top-3 left-3 md:top-3.5 md:left-4 z-50 p-2.5 rounded-xl bg-[#0a0d3c]/80 text-[#AEB8CF] hover:text-[#f1863d] border border-white/10 hover:border-[#f1863d]/50 backdrop-blur-md transition-all shadow-lg cursor-pointer flex items-center justify-center group"
          aria-label="Abrir menu lateral"
          title="Abrir menu"
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
        </button>
      )}

      {/* Fundo escuro para fechar no celular ao clicar fora */}
      {isOpen && (
        <div
          onClick={() => setIsOpen(false)}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden transition-opacity"
        />
      )}

      {/* Painel da Barra Lateral */}
      <aside
        className={`fixed top-0 left-0 h-full w-64 md:w-72 bg-[#050738]/95 backdrop-blur-xl border-r border-white/10 z-50 flex flex-col p-4 shadow-2xl transition-transform duration-300 ease-in-out ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Cabeçalho do Menu com o Logo da USPapo ao lado do nome e o Botão 'X' para fechar */}
        <div className="flex items-center justify-between pb-4 border-b border-white/10">
          <div className="flex items-center gap-2.5">
            <Image
              src="/logo.svg"
              alt="USPapo Logo"
              width={32}
              height={32}
            />
            <span className="font-geom text-xl text-[#f1863d] font-bold">
              USPapo
            </span>
          </div>
          <button
            onClick={() => setIsOpen(false)}
            className="p-1.5 rounded-lg text-[#AEB8CF] hover:text-[#f1863d] hover:bg-white/5 transition-colors cursor-pointer"
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
            onClick={() => {
              if (window.innerWidth < 768) setIsOpen(false);
            }}
            className="flex items-center gap-3 px-3.5 py-3 rounded-xl text-[#AEB8CF] hover:text-white hover:bg-[#f1863d]/15 border border-transparent hover:border-[#f1863d]/30 transition-all cursor-pointer group"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="w-5 h-5 text-[#f1863d] group-hover:scale-110 transition-transform"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v6m3-3H9m12 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
              />
            </svg>
            <span className="font-geom text-sm font-medium">Novo Chat</span>
          </Link>

          <button
            onClick={() => {
              if (window.innerWidth < 768) setIsOpen(false);
            }}
            className="flex items-center gap-3 px-3.5 py-3 rounded-xl text-[#AEB8CF] hover:text-white hover:bg-[#f1863d]/15 border border-transparent hover:border-[#f1863d]/30 transition-all cursor-pointer group text-left w-full"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="w-5 h-5 text-[#f1863d] group-hover:scale-110 transition-transform"
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
          </button>

          <button
            onClick={() => {
              if (window.innerWidth < 768) setIsOpen(false);
            }}
            className="flex items-center gap-3 px-3.5 py-3 rounded-xl text-[#AEB8CF] hover:text-white hover:bg-[#f1863d]/15 border border-transparent hover:border-[#f1863d]/30 transition-all cursor-pointer group text-left w-full"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className="w-5 h-5 text-[#f1863d] group-hover:rotate-90 transition-transform duration-500"
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
    </>
  );
}