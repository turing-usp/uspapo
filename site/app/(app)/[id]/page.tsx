"use client";
import ChatResponse from "@/components/chatResponse";
import Fontes from "@/components/Fontes";
import PromptInput from "@/components/propmptInput";
import StatusBlock from "@/components/StatusBlock";
import TypingIndicator from "@/components/TypingIndicator";
import { obterConversa, salvarConversa, gerarTitulo, type Mensagem } from "@/lib/conversas";
import {
    perguntar,
    reduzirStatus,
    statusVisivel,
    STATUS_INICIAL,
    type StatusStream,
} from "@/lib/stream";
import { UserBubble } from "@/components/UserBubble";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";

const PENDENTE = "...";

export default function ChatPage() {

    const { id } = useParams();
    const [pergunta, setPergunta] = useState("");
    const [historico, setHistorico] = useState<Mensagem[]>([]);
    const [respondendo, setRespondendo] = useState(false);
    const [streaming, setStreaming] = useState(false);
    /* O que o modelo está fazendo agora */
    const [status, setStatus] = useState<StatusStream>(STATUS_INICIAL);
    const jaProcessouInicial = useRef(false);
    const fimDasMensagensRef = useRef<HTMLDivElement>(null);

    const completarResposta = async (texto: string) => {
        setRespondendo(true);
        setStreaming(false);
        setStatus(STATUS_INICIAL);

        const acc = { corpo: "", fontes: [] as string[], erro: "" };

        /* Parser mais lento para não exigir muita performance do React */
        let ultimoRender = 0;

        const aplicar = (forcar = false) => {
            const agora = performance.now();
            if (!forcar && agora - ultimoRender < 50) return;
            ultimoRender = agora;

            setHistorico((prev) => {
                const copia = [...prev];
                copia[copia.length - 1] = {
                    user: texto,
                    bot: acc.corpo || PENDENTE,
                    ...(acc.fontes.length > 0 ? { fontes: acc.fontes } : {}),
                };
                return copia;
            });
        };

        try {
            await perguntar(texto, (evento) => {
                setStatus((atual) => reduzirStatus(atual, evento));

                switch (evento.tipo) {
                    case "modo":
                        setStreaming(evento.streaming);
                        break;
                    case "texto":
                        acc.corpo += evento.delta;
                        aplicar();
                        break;
                    case "fontes":
                        acc.fontes = evento.urls;
                        break;
                    case "erro":
                        acc.erro = evento.mensagem;
                        break;
                }
            });
        } catch (erro) {
            console.error(erro);
            acc.erro = "Desculpe, ocorreu um erro ao conectar com o servidor do USPapo.";
        }

        if (!acc.corpo) {
            acc.corpo = acc.erro || "Desculpe, ocorreu um erro ao conectar com o servidor do USPapo.";
        }

        aplicar(true);
        setStatus(STATUS_INICIAL);
        setRespondendo(false);
    };

    const enviarPergunta = async (texto: string) => {
        if (!texto.trim() || respondendo) return;
        setHistorico((prev) => [...prev, { user: texto, bot: PENDENTE }]);
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
        if (ultima && ultima.bot === PENDENTE) {
            completarResposta(ultima.user);
        }
    }, [id]);

    // 2. salva quando o histórico muda, depois do stream
    useEffect(() => {
        if (historico.length === 0 || respondendo) return;

        const existente = obterConversa(id as string);
        salvarConversa({
            id: id as string,
            titulo: existente?.titulo ?? gerarTitulo(historico[0].user),
            criadoEm: existente?.criadoEm ?? Date.now(),
            favorita: existente?.favorita,
            mensagens: historico,
        });
    }, [historico, id, respondendo]);

    // 3. rola até o fim
    useEffect(() => {
        fimDasMensagensRef.current?.scrollIntoView({
            behavior: respondendo ? "auto" : "smooth",
        });
    }, [historico, respondendo]);

    const ferramentasAtivas = Object.values(status.ferramentas);

  return (
    <>
        <div className="flex flex-1 flex-col">
        <div className="flex-1">
            {historico.map((item, index) => {
            const streamando = respondendo && streaming && index === historico.length - 1;
            const semTexto = item.bot === PENDENTE;
            const mostrarStatus = streamando && statusVisivel(status, semTexto);

            return (
            <div key={index}>
                <div className="app-container-chat flex justify-end mt-6">
                    <UserBubble text={item.user} />
                </div>
                <div className="app-container-chat mt-4 pb-6">
                    {semTexto && !mostrarStatus && <TypingIndicator />}
                    {!semTexto && <ChatResponse text={item.bot} />}
                    {item.fontes && <Fontes urls={item.fontes} />}
                    {mostrarStatus && <StatusBlock ferramentas={ferramentasAtivas} />}
                </div>
            </div>
            );
            })}
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
