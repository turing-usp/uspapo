"use client";
import Image from "next/image";
import Navbar from "@/components/navbar";
import Leftmenu from "@/components/leftmenu";
import ChatResponse from "@/components/chatResponse";
import PromptInput from "@/components/propmptInput";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";

export default function ChatPage() {

    const { id } = useParams();
    const [pergunta, setPergunta] = useState("");
    const [historico, setHistorico] = useState<{ user: string; bot: string }[]>([]);
    const jaProcessouInicial = useRef(false);

    // Função que faz a requisição real para o seu Flask (porta 5000)
    const enviarParaAPI = async (texto: string) => {
        try {
            const res = await fetch("http://localhost:5000/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ pergunta: texto }),
            });

            if (!res.ok) throw new Error("Erro na comunicação com o back-end");

            const dados = await res.json();
            
            // Junta a resposta do Groq com as fontes oficiais da USP
            let respostaCompleta = dados.resposta;
            if (dados.fontes && dados.fontes.length > 0) {
                respostaCompleta += "\n\nFontes consultadas:\n" + dados.fontes.map((url: string) => `- ${url}`).join("\n");
            }

            return respostaCompleta;
        } catch (erro) {
            console.error(erro);
            return "Desculpe, ocorreu um erro ao conectar com o servidor do USPapo.";
        }
    };

    useEffect(() => {
        if (!jaProcessouInicial.current) {
            jaProcessouInicial.current = true;
            const perguntaInicial = sessionStorage.getItem(`pergunta-inicial-${id}`);
            if (perguntaInicial) {
                sessionStorage.removeItem(`pergunta-inicial-${id}`); // limpa depois de usar
                
                // Exibe a pergunta inicial com status de carregamento
                setHistorico([{ user: perguntaInicial, bot: "Pensando..." }]);
                
                // Busca a resposta real na API
                enviarParaAPI(perguntaInicial).then((respostaReal) => {
                    setHistorico([{ user: perguntaInicial, bot: respostaReal }]);
                });
            }
        }
    }, [id]);

    const enviarPergunta = async (texto: string) => {
        if (!texto.trim()) return;
        
        // Adiciona a nova mensagem ao histórico mostrando "Pensando..."
        setHistorico((prev) => [...prev, { user: texto, bot: "Pensando..." }]);
        setPergunta("");

        // Pega a resposta real do Groq via API
        const respostaReal = await enviarParaAPI(texto);

        // Atualiza o último balão com a resposta processada
        setHistorico((prev) => {
            const novoHistorico = [...prev];
            novoHistorico[novoHistorico.length - 1].bot = respostaReal;
            return novoHistorico;
        });
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
        <div className="pb-32">
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