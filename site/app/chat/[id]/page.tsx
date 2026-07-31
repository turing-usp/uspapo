"use client";
import ChatResponse from "@/components/chatResponse";
import PromptInput from "@/components/propmptInput";
import TypingIndicator from "@/components/TypingIndicator";
import { obterConversa, salvarConversa, gerarTitulo } from "@/lib/conversas";
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

    // substitui a última mensagem (que está com bot: "...") pela resposta real
    const completarResposta = async (texto: string) => {
        const respostaFormatada = await enviarParaAPI(texto);
        setHistorico((prev) => {
            const copia = [...prev];
            copia[copia.length - 1] = { user: texto, bot: respostaFormatada };
            return copia;
        });
    };

    const enviarPergunta = async (texto: string) => {
        if (!texto.trim()) return;
        setHistorico((prev) => [...prev, { user: texto, bot: "..." }]);
        setPergunta("");
        await completarResposta(texto);
    };

    const lidarComEnvio = (e: React.SyntheticEvent) => {
        e.preventDefault();
        enviarPergunta(pergunta);
    };

    // 1. carrega a conversa salva e, se houver resposta pendente, completa
    useEffect(() => {
        if (jaProcessouInicial.current) return;
        jaProcessouInicial.current = true;

        const conversa = obterConversa(id as string);
        if (!conversa) return;

        setHistorico(conversa.mensagens);

        const ultima = conversa.mensagens[conversa.mensagens.length - 1];
        if (ultima && ultima.bot === "...") {
            completarResposta(ultima.user);
        }
    }, [id]);

    // 2. salva sempre que o histórico muda
    useEffect(() => {
        if (historico.length === 0) return;

        const existente = obterConversa(id as string);
        salvarConversa({
            id: id as string,
            titulo: existente?.titulo ?? gerarTitulo(historico[0].user),
            criadoEm: existente?.criadoEm ?? Date.now(),
            favorita: existente?.favorita,
            mensagens: historico,
        });
    }, [historico, id]);

    // 3. rola até o fim
    useEffect(() => {
        fimDasMensagensRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [historico]);

  return (
    <>
        <div className="flex flex-1 flex-col">
        <div className="flex-1">
            {historico.map((item, index) => (
            <div key={index}>
                <div className="app-container-chat flex justify-end mt-6">
                    <UserBubble text={item.user} />
                </div>
                <div className="app-container-chat mt-4 pb-6">
                    {item.bot === "..." ? <TypingIndicator /> : <ChatResponse text={item.bot} />}
                </div>
            </div>
            ))}
            <div ref={fimDasMensagensRef} />
        </div>
        <div className="sticky bottom-0 z-20 pt-8 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0 -z-10 page-fade-t"
            />
            <div className="app-container-chat">
                <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
                <p className="mt-2 text-center text-sm text-[#AEB8CF] text-balance">
                    O uspapo é uma IA e pode cometer erros. Sempre confirme as informações com fontes oficiais.
                </p>
            </div>
        </div>
        </div>
    </>
  );
}