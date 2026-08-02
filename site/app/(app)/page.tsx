"use client";
import Image from "next/image";
import PromptInput from "../../components/propmptInput";
import { salvarConversa, gerarTitulo, novoId } from "@/lib/conversas";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const[pergunta, setPergunta] = useState("");

  const enviarPergunta = (texto: string) => {
    if (!texto.trim()) return;
    const id = novoId();
    salvarConversa({
      id: id,
      titulo: gerarTitulo(texto),
      criadoEm: Date.now(),
      mensagens: [{ user: texto, bot: "..." }],
    });
    router.push(`/chat/${id}`);
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
    <div className="app-scroll">
      <div className="flex min-h-full flex-col">
        <div className="flex flex-1 flex-col justify-center py-8 curto:py-3 curtinho:py-1">
          <div className="app-container flex flex-col items-center">
            <div className="flex flex-col md:flex-row mb-3 curto:mb-1 justify-center items-center gap-2">
              <Image
                src="/uspapo.svg"
                alt=""
                width={40}
                height={40}
              />
              <p className="font-geom text-4xl md:text-5xl curtinho:text-3xl text-brand ml-1">USPapo</p>
            </div>
            <p className="font-geom text-base md:text-xl text-foreground mt-3 mb-6 curto:mt-1 curto:mb-2 curtinho:mb-0 text-center text-balance">Seu <span className="text-brand">assistente inteligente</span> para navegar pela USP</p>
          </div>
          <div className="app-container mt-8 md:mt-10 curto:mt-4 curtinho:mt-2">
            <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
          </div>
          <div className="app-container flex flex-col items-center mt-10 md:mt-12 curto:mt-5 curtinho:mt-2">
            <p className="font-geom text-base text-foreground">Perguntas Frequentes</p>
            <div className="flex flex-col md:flex-row md:flex-wrap justify-center items-stretch gap-4 md:gap-6 curto:gap-2 mt-6 curto:mt-3 w-full">
              {perguntasFrequentes.map((pergunta, index) => (
                <button
                  key={index}
                  className="glass flex flex-col justify-center items-center text-center w-full h-14 curto:h-12 md:w-auto md:flex-1 md:basis-0 md:min-w-[11rem] max-w-[18rem] mx-auto min-h-[3rem] px-4 py-2 rounded-[2rem] text-foreground transition-colors hover:text-brand hover:cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                  onClick={() => enviarPergunta(pergunta)}
                >
                  <span className="text-balance">{pergunta}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="app-container flex flex-row flex-wrap justify-center items-center gap-x-2 py-6 curto:py-3">
            <p className="font-geom text-base text-brand">Desenvolvido por</p>
            <div className="flex flex-row justify-center items-center gap-1">
              <Image
                src="/logo.svg"
                alt=""
                width={30}
                height={30}
              />
              <p className="font-orbitron text-base text-brand">turing.usp</p>
            </div>
        </div>
      </div>
    </div>
  );
}
