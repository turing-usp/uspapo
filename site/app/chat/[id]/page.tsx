"use client";
import ChatResponse from "@/components/chatResponse";
import PromptInput from "@/components/propmptInput";
import TypingIndicator from "@/components/TypingIndicator";
import { UserBubble } from "@/components/UserBubble";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";


export default function ChatPage() {

    const { id } = useParams();
    const [pergunta, setPergunta] = useState("");
    const [historico, setHistorico] = useState<{ user: string; bot: string }[]>([]);
    const jaProcessouInicial = useRef(false);
    const fimDasMensagensRef = useRef<HTMLDivElement>(null);

    const enviarParaAPI = async (texto: string) => {
    try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pergunta: texto }),
        });

        if (!res.ok) throw new Error("Erro na comunicação com o back-end");

        const dados = await res.json();

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

    const enviarPergunta = async (texto: string) => {
        if (!texto.trim()) return;

        setHistorico((prev) => [...prev, { user: texto, bot: "..." }]);
        setPergunta("");

        const respostaFormatada = await enviarParaAPI(texto);

        setHistorico((prev) => {
            const copia = [...prev];
            copia[copia.length - 1] = { user: texto, bot: respostaFormatada };
            return copia;
        });
    };

    useEffect(() => {
    if (!jaProcessouInicial.current) {
        jaProcessouInicial.current = true;
        const perguntaInicial = sessionStorage.getItem(`pergunta-inicial-${id}`);
        if (perguntaInicial) {
            sessionStorage.removeItem(`pergunta-inicial-${id}`);
            enviarPergunta(perguntaInicial);   
        }
    }
    }, [id]);

    const lidarComEnvio = (e: React.SyntheticEvent) => {
        e.preventDefault();
        enviarPergunta(pergunta);
    };

    // UseEffect para rolar para o fim das mensagens quando a página é carregada ou quando o histórico muda
    useEffect(() => {
        if (fimDasMensagensRef.current) {
            fimDasMensagensRef.current.scrollIntoView({ behavior: "smooth" });
        }
    }, [historico]);

  return (
    <>
        <div className="pb-32">
        {historico.map((item, index) => (
        <div key={index}>
            <div className="relative flex flex-col h-[20%] mt-[1%] mr-[20%] ml-[55%] rounded-[2rem]">
                <UserBubble text={item.user} />
            </div>
            <div className="flex flex-col pb-[3%]">
                {item.bot === "..." ? <TypingIndicator /> : <ChatResponse text={item.bot} />}
            </div>
        </div>
        ))}
        <div ref={fimDasMensagensRef} />
        <div className="fixed bottom-0 left-0 right-0 z-20 pt-8 pb-4">
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0 -z-10 page-fade-t"
            />
            <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
            <p className="mt-[1%] text-center text-[0.875rem] text-[#AEB8CF]">
                O uspapo é uma IA e pode cometer erros. Sempre confirme as informações com fontes oficiais.
            </p>
        </div>
        </div>
    </>
  );
}