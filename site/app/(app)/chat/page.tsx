"use client";
import ChatResponse from "@/components/chatResponse";
import Fontes from "@/components/Fontes";
import PromptInput from "@/components/propmptInput";
import StatusBlock from "@/components/StatusBlock";
import TypingIndicator from "@/components/TypingIndicator";
import { obterConversa, salvarConversa, gerarTitulo, PENDENTE, type Mensagem } from "@/lib/conversas";
import { lerPendente, descartarPendente } from "@/lib/pendente";
import { obterFeedbacksDaConversa, type FeedbackItem } from "@/lib/feedback";
import FeedbackBot from "@/components/FeedbackBot";
import {
    perguntar,
    reduzirStatus,
    statusVisivel,
    STATUS_INICIAL,
    type StatusStream,
} from "@/lib/stream";
import { UserBubble } from "@/components/UserBubble";
import { useAlturaPublicada } from "@/lib/janela";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

function Chat() {

    const router = useRouter();
    const searchParams = useSearchParams();
    /* O id migrou do segmento de rota (/chat/[id]) para a query string
       (?id=<uuid>) por causa do export estático da Estratégia A: uma rota
       dinâmica não sai no export, e a estática lê o id só no cliente. */
    const id = searchParams.get("id");
    const [pergunta, setPergunta] = useState("");
    /* A pergunta que veio da home, lida uma única vez, no primeiro render.
       Guardada em estado e não em ref porque três useState abaixo dependem
       dela: é ela que faz a bolha, o "digitando" e o estado de "respondendo"
       existirem no mesmo quadro da navegação, antes de qualquer ida ao banco.

       Sem risco de divergência de hidratação: a fronteira de Suspense abaixo
       só renderiza este componente no cliente, e num acesso direto à URL o
       Map do lib/pendente está vazio. */
    const [daHome] = useState(() => (id ? lerPendente(id) : null));
    const [historico, setHistorico] = useState<Mensagem[]>(() =>
        daHome ? [{ user: daHome, bot: PENDENTE }] : []
    );
    const [respondendo, setRespondendo] = useState(!!daHome);
    const [streaming, setStreaming] = useState(false);
    /* O que o modelo está fazendo agora */
    const [status, setStatus] = useState<StatusStream>(STATUS_INICIAL);
    /* A conversa da URL não veio do banco. Ver o efeito de carga logo abaixo. */
    const [naoCarregou, setNaoCarregou] = useState(false);
    const [feedbacks, setFeedbacks] = useState<Record<number, FeedbackItem>>({});
    const jaProcessouInicial = useRef(false);
    const fimDasMensagensRef = useRef<HTMLDivElement>(null);
    const composerRef = useRef<HTMLDivElement>(null);

    /* O fade atrás do composer precisa saber onde ele começa. */
    useAlturaPublicada(composerRef, "--composer-h");

    /* O prólogo mora fora do completarResposta porque o caminho da home não
       precisa dele: quando a pergunta veio de lá, os três já nascem assim nos
       useState acima. Chamá-los do efeito de montagem só cascatearia um render
       para chegar num estado que já era o atual. */
    const iniciarResposta = () => {
        setRespondendo(true);
        setStreaming(false);
        setStatus(STATUS_INICIAL);
    };

    const completarResposta = async (texto: string, anteriores: Mensagem[]) => {
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
            /* id só é null num /chat sem ?id=, e o efeito de montagem já
               mandou o aluno para a home: nenhum caminho aqui chega a
               perguntar sem conversa. */
            await perguntar(texto, anteriores, (evento) => {
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
            }, id ?? undefined);
        } catch (erro) {
            console.error(erro);
            /* O back-end explica o 429 do rate limit na própria mensagem. */
            acc.erro = erro instanceof Error && erro.message
                ? erro.message
                : "Desculpe, ocorreu um erro ao conectar com o servidor do USPapo.";
        }

        if (!acc.corpo) {
            acc.corpo = acc.erro || "Desculpe, ocorreu um erro ao conectar com o servidor do USPapo.";
        } else if (acc.erro) {
            acc.corpo += `\n\n_${acc.erro}_`;
        }

        aplicar(true);
        setStatus(STATUS_INICIAL);
        setRespondendo(false);
    };

    const enviarPergunta = async (texto: string) => {
        if (!texto.trim() || respondendo) return;
        const anteriores = historico;
        setHistorico((prev) => [...prev, { user: texto, bot: PENDENTE }]);
        setPergunta("");
        iniciarResposta();
        await completarResposta(texto, anteriores);
    };

    const lidarComEnvio = (e: React.SyntheticEvent) => {
        e.preventDefault();
        enviarPergunta(pergunta);
    };

    // 0. /chat sem ?id=: não existe conversa para abrir. O redirecionamento é
    //    no cliente porque o HTML da rota estática não conhece a query — só o
    //    navegador sabe que ?id= está ausente.
    useEffect(() => {
        if (!id) router.replace("/");
    }, [id, router]);

    // 1. carrega a conversa salva e, se houver resposta pendente, completa
    useEffect(() => {
        if (jaProcessouInicial.current) return;
        jaProcessouInicial.current = true;

        /* /chat sem ?id=: nem conversa há que buscar nem pendência; o efeito
           acima já devolveu o aluno para a home. */
        if (!id) return;

        /* Conversa recém-nascida na home: a pergunta veio em memória e já está
           na tela, com o estado de resposta montado desde o primeiro render.
           Não há o que buscar, nem conversa, nem feedback, e as três idas ao
           banco abaixo só atrasariam o primeiro token. Quem grava é o efeito 2,
           sozinho, com o stream já correndo. */
        if (daHome) {
            descartarPendente(id);
            /* O set-state-in-effect segue para dentro do completarResposta e
               acha os setState de lá, mas nenhum deles é síncrono: todos rodam
               nos callbacks do stream, depois da rede. A regra aceita o mesmo
               completarResposta duas telas abaixo só porque lá existe um await
               antes dele, e pôr um await aqui, justamente no caminho que existe
               para NÃO esperar nada, seria enganar a regra em vez de atender. */
            // eslint-disable-next-line react-hooks/set-state-in-effect
            completarResposta(daHome, []);
            return;
        }

        (async () => {
            const conversa = await obterConversa(id);
            /* Sair calado aqui deixava a tela em branco: nem mensagem, nem erro,
               nem pista. Acontece quando a gravação falhou logo antes (banco sem
               o esquema, RLS barrando) e também quando a URL é de uma conversa
               que não existe mais. O motivo exato vai para o console pelo
               lib/conversas.ts; aqui o que importa é não deixar o aluno olhando
               para o nada. */
            if (!conversa) {
                setNaoCarregou(true);
                return;
            }

            setHistorico(conversa.mensagens);
            const mapaFeedbacks = await obterFeedbacksDaConversa(id);
            setFeedbacks(mapaFeedbacks);

            const ultima = conversa.mensagens[conversa.mensagens.length - 1];
            if (ultima && ultima.bot === PENDENTE) {
                /* A última é justamente a que está sem resposta: ela é a pergunta
                de agora, não um turno anterior. */
                iniciarResposta();
                completarResposta(ultima.user, conversa.mensagens.slice(0, -1));
            }
        })();
    }, [id]);
    const turnos = historico.length;
    // 2. salva a pergunta assim que entra e a resposta quando o stream acaba.
    //    Depender do array inteiro dispararia uma escrita a cada 50ms do stream.
    useEffect(() => {
        /* Sem ?id= não há conversa que salvar: o efeito de montagem devolveu
           o aluno para a home. Com id, sem conversa carrega turnos é 0. */
        if (!id || turnos === 0) return;

        (async () => {
            const existente = await obterConversa(id);
            await salvarConversa({
                id,
                titulo: existente?.titulo ?? gerarTitulo(historico[0].user),
                criadoEm: existente?.criadoEm ?? Date.now(),
                favorita: existente?.favorita,
                mensagens: historico,
            });
        })();
        // historico é lido, não observado: turnos e respondendo é que marcam
        // os dois instantes em que vale salvar.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [turnos, respondendo, id]);

    // 3. rola até o fim
    useEffect(() => {
        fimDasMensagensRef.current?.scrollIntoView({
            behavior: respondendo ? "auto" : "smooth",
        });
    }, [historico, respondendo]);

    const ferramentasAtivas = Object.values(status.ferramentas);

    return (
        <>
            {/* Só as mensagens rolam. Navbar e composer são irmãos fixos do shell,
            então nada se desloca quando o teclado abre. */}
            <div className="app-scroll">
                {historico.map((item, index) => {
                    const streamando = respondendo && streaming && index === historico.length - 1;
                    const semTexto = item.bot === PENDENTE;
                    const mostrarStatus = streamando && statusVisivel(status, semTexto);
                    /* O último turno fica de fora do content-visibility: é ele que
                       cresce a cada quadro do stream e que o scrollIntoView persegue. */
                    const assentado = index < historico.length - 1;

                    return (
                        <div key={index} className={assentado ? "turno-assentado" : undefined}>
                            <div className="app-container-chat flex justify-end mt-6">
                                <UserBubble text={item.user} />
                            </div>
                            <div className="app-container-chat mt-4 pb-6">
                                {semTexto && !mostrarStatus && <TypingIndicator />}
                                {!semTexto && <ChatResponse text={item.bot} streaming={streamando} />}
                                {item.fontes && <Fontes urls={item.fontes} />}
                                {mostrarStatus && <StatusBlock ferramentas={ferramentasAtivas} />}
                                {/* Sem ?id= não há conversa: nem bolha, nem botão de feedback. */}
                                {!semTexto && !streamando && id && (
                                    <FeedbackBot
                                        conversaId={id}
                                        mensagemOrdem={index}
                                        feedbackInicial={feedbacks[index]}
                                        disabled={respondendo}
                                    />
                                )}
                            </div>
                        </div>
                    );
                })}
                {naoCarregou && turnos === 0 && (
                    <div className="app-container-chat mt-10 text-center">
                        <p className="text-muted-foreground">
                            Não consegui carregar esta conversa.
                        </p>
                        <p className="mt-2 text-sm text-faint-foreground text-balance">
                            Ela pode ter sido apagada, ou a pergunta não chegou a ser salva.
                            Você pode começar outra pelo campo abaixo.
                        </p>
                    </div>
                )}
                <div ref={fimDasMensagensRef} />
            </div>
            {/* Dissolve as mensagens que chegam no composer. Fica fora do wrapper
            abaixo para compartilhar a caixa da casca; a altura vem do
            --composer-h publicado pelo useAlturaPublicada. */}
            <div aria-hidden className="page-fade-t" />
            <div
                ref={composerRef}
                className="relative z-30 flex-none pt-8 pb-4"
            >
                <div className="app-container-chat">
                    {/* O guard do enviarPergunta já barrava a segunda pergunta,
                    mas em silêncio: o campo aceitava o Enter e não acontecia
                    nada. O disabled é o mesmo estado, visível. */}
                    <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} disabled={respondendo} />
                    <p className="mt-2 text-center text-sm text-muted-foreground text-balance">
                        O USPapo é uma IA e pode cometer erros. Sempre confirme as informações com fontes oficiais.
                    </p>
                </div>
            </div>
        </>
    );
}

export default function ChatPage() {
    /* A página /chat é estática (export da Estratégia A) e lê ?id= com
       useSearchParams no cliente: sem esta fronteira de Suspense o build de
       produção falha ("Missing Suspense boundary with useSearchParams") — o
       mesmo padrão que /login usa. No HTML inicial o fallback é só a casca da
       tela; a hidratação o troca por <Chat /> quando a query é lida. */
    return (
        <Suspense fallback={<div className="app-scroll" />}>
            <Chat />
        </Suspense>
    );
}
