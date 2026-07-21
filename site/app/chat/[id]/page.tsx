"use client";
import Image from "next/image";
import Navbar from "@/components/navbar";
import Leftmenu from "@/components/leftmenu";
import ChatResponse from "@/components/chatResponse";
import PromptInput from "@/components/propmptInput";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";

export default function Home() {

    const { id } = useParams();
    const [pergunta, setPergunta] = useState("");
    const [historico, setHistorico] = useState<{ user: string; bot: string }[]>([]);
    const jaProcessouInicial = useRef(false);

    useEffect(() => {
        if (!jaProcessouInicial.current) {
            jaProcessouInicial.current = true;
            const perguntaInicial = sessionStorage.getItem(`pergunta-inicial-${id}`);
            if (perguntaInicial) {
            setHistorico([{ user: perguntaInicial, bot: "resposta mock..." }]);
            sessionStorage.removeItem(`pergunta-inicial-${id}`); // limpa depois de usar
            }
        }
    }, [id]);

    const enviarPergunta = (texto: string) => {
        if (!texto.trim()) return;
        setHistorico((prev) => [...prev, { user: texto, bot: "resposta mock..." }]);
        setPergunta("");
    };

    const lidarComEnvio = (e: React.SyntheticEvent) => {
        e.preventDefault();
        enviarPergunta(pergunta);
    };

  return (
    <>
        <Navbar>
        </Navbar>
        <Leftmenu>
        </Leftmenu>
        <div>
        {historico.map((item, index) => (
        <div key={index}>
            <div className="flex flex-col h-[20%] mt-[1%] mr-[20%] ml-[55%]">
                <input 
                type="text" 
                value={item.user}
                readOnly
                className="bg-[#F5F5F5]/20 text-[#AEB8CF] text-[1.2rem] text-[#FFFFFF] px-[5%] w-[100%] h-[3.5rem] rounded-[2rem]  placeholder:text-[#AEB8CF] focus:outline-none" 
                disabled
                style={{
                boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.4), inset 0 -1px 1px rgba(255,255,255,0.05)'
                }}
                />
            </div>
            <div className="flex flex-col pb-[12%]">
            <ChatResponse text={item.bot} />
            </div>
        </div>
        ))}
        <div className="fixed bottom-0 left-0 right-0 z-20 bg-gradient-to-t from-[#03042c] via-[#03042c]/95 to-transparent pt-8 pb-4">
            <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
            <p className="mt-[1%] text-center text-[0.875rem] text-[#AEB8CF]">
                O uspapo é uma IA e pode cometer erros. Sempre confirme as informações com fontes oficiais.
            </p>
        </div>
        </div>
    </>
  );
}
