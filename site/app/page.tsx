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
    <>
      <div className="flex flex-col items-center h-[20%] mt-[3%] mx-[5%]">
        <div className="flex flex-col md:flex-row justify-center items-center">
          <Image
            src="/uspapo.png"
            alt=""
            width={60}
            height={60}
          />
          <p className="font-geom text-[2.5rem] md:text-[3rem] text-[#f1863d] ml-[2%]">USPapo</p>
        </div>
        <p className="font-geom text-[1rem] md:text-[1.25rem] text-[#FFFFFF] mt-[2%]">Seu <span className="font-geom text-[1rem] md:text-[1.25rem] text-[#f1863d]">assistente inteligente</span> para navegar pela USP</p>
      </div>
      <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
      <div className="flex flex-col items-center my-[6%] md:my-[0%] md:mt-[3%] mx-[5%]">
        <p className="font-geom text-[1rem] text-[#ffffff]">Perguntas Frequentes</p>
        <div className="flex flex-col md:flex-row justify-center items-center gap-[2rem] mt-[2%]">
          {perguntasFrequentes.map((pergunta, index) => (
            <button
              key={index}
              className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer"
              onClick={() => enviarPergunta(pergunta)}
            >
              {pergunta}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-row justify-center items-center mt-[4%] mx-[5%]">
          <p className="font-geom text-[1rem] text-[#f1863d]">Desenvolvido por</p>
          <div className="flex flex-row justify-center items-center ml-[0.5%]">
            <Image
              src="/logo.svg"
              alt=""
              width={30}
              height={30}
            />
            <p className="font-orbitron text-[1rem] text-[#f1863d]">turing.usp</p>
          </div>
      </div>
    </>
  );
}
