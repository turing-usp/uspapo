"use client";
import Image from "next/image";
import PromptInput from "../components/propmptInput";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const[pergunta, setPergunta] = useState("");

  const enviarPergunta = (texto: string) => {
      if (!texto.trim()) return;
      const novoId = crypto.randomUUID();
      sessionStorage.setItem(`pergunta-inicial-${novoId}`, texto);
      router.push(`/chat/${novoId}`);
  };

  // 2. Função que simula o envio do formulário
  const lidarComEnvio = (e: React.SyntheticEvent) => {
  e.preventDefault();
  enviarPergunta(pergunta);
};

 // 3. Textos das perguntas frequentes
  const perguntasFrequentes = [
    "O que é o USPapo?",
    "O que é o Jupiterweb?",
    "Cardápio de hoje?"
  ];

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-1 flex-col justify-center py-8">
        <div className="app-container flex flex-col items-center">
          <div className="flex flex-col md:flex-row justify-center items-center gap-2">
            <Image
              src="/uspapo.png"
              alt=""
              width={60}
              height={60}
            />
            <p className="font-geom text-4xl md:text-5xl text-[#f1863d]">USPapo</p>
          </div>
          <p className="font-geom text-base md:text-xl text-[#FFFFFF] mt-3 text-center text-balance">Seu <span className="text-[#f1863d]">assistente inteligente</span> para navegar pela USP</p>
        </div>
        <div className="app-container mt-8 md:mt-10">
          <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
        </div>
        <div className="app-container flex flex-col items-center mt-10 md:mt-12">
          <p className="font-geom text-base text-[#ffffff]">Perguntas Frequentes</p>
          <div className="flex flex-col md:flex-row md:flex-wrap justify-center items-stretch gap-4 md:gap-6 mt-6 w-full">
            {perguntasFrequentes.map((pergunta, index) => (
              <button
                key={index}
                className="relative flex flex-col justify-center items-center text-center bg-[#FFFFFF]/20 w-full md:w-auto md:flex-1 md:basis-0 md:min-w-[11rem] max-w-[18rem] mx-auto min-h-[3rem] px-4 py-2 rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer"
                onClick={() => enviarPergunta(pergunta)}
              >
                <div aria-hidden className="pointer-events-none absolute inset-0 z-0 rounded-[2rem] glass-radial-blur" />
                <span className="relative z-10 text-balance">{pergunta}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="app-container flex flex-row flex-wrap justify-center items-center gap-x-2 py-6">
          <p className="font-geom text-base text-[#f1863d]">Desenvolvido por</p>
          <div className="flex flex-row justify-center items-center gap-1">
            <Image
              src="/logo.svg"
              alt=""
              width={30}
              height={30}
            />
            <p className="font-orbitron text-base text-[#f1863d]">turing.usp</p>
          </div>
      </div>
    </div>
  );
}
