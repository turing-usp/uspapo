"use client";
import ReactMarkdown from 'react-markdown';
import { memo, useEffect, useRef, useState } from 'react';
import type { Root, Element, Text, ElementContent } from 'hast';

/* Largura do rastro de gradiente atrás da frente de revelação, em caracteres. */
const RASTRO = 120;

/* Atraso que a revelação persegue em relação ao stream, em segundos. */
const ATRASO_ALVO = 0.25;
const VELOCIDADE_MINIMA = 30;      // caracteres por segundo
const DRENO = RASTRO / 0.4;        // velocidade para apagar o rastro no fim
const INTERVALO_RENDER = 33;       // ms entre re-renders (o markdown é reparseado)

function useRevelacao(texto: string, streaming: boolean) {
    const [contador, setContador] = useState(() => (streaming ? 0 : texto.length + RASTRO));
    const posicao = useRef(contador);
    const alvo = useRef(texto);
    const ativo = useRef(streaming);

    useEffect(() => {
        alvo.current = texto;
        ativo.current = streaming;

        const destino = () => alvo.current.length + RASTRO;

        /* Mensagem que já nasce pronta (veio do localStorage) não tem o que
           revelar: animar seria repetir uma resposta que o aluno já leu. */
        if (!streaming && posicao.current >= destino()) return;

        let quadro = 0;
        let ultimoInstante = performance.now();
        let ultimoRender = 0;

        const passo = (agora: number) => {
            const decorrido = (agora - ultimoInstante) / 1000;
            ultimoInstante = agora;

            const restante = alvo.current.length - posicao.current;
            const atraso = ativo.current ? ATRASO_ALVO : ATRASO_ALVO / 3;
            const velocidade = restante > 0
                ? Math.max(VELOCIDADE_MINIMA, restante / atraso)
                : DRENO;

            posicao.current = Math.min(destino(), posicao.current + velocidade * decorrido);

            if (agora - ultimoRender >= INTERVALO_RENDER) {
                ultimoRender = agora;
                setContador(posicao.current);
            }

            if (ativo.current || posicao.current < destino()) {
                quadro = requestAnimationFrame(passo);
            } else {
                setContador(destino());
            }
        };

        quadro = requestAnimationFrame(passo);
        return () => cancelAnimationFrame(quadro);
    }, [texto, streaming]);

    const revelado = Math.min(Math.floor(contador), texto.length);

    return {
        visivel: texto.slice(0, revelado),
        sobra: Math.max(0, contador - texto.length),
        /* Enquanto houver gradiente na tela, os spans precisam existir. */
        revelando: streaming || contador < texto.length + RASTRO,
    };
}

function palavrasReveladas(sobra: number) {
    return (arvore: Root) => {
        let total = 0;
        const contar = (nos: ElementContent[]) => {
            for (const no of nos) {
                if (no.type === 'text') total += no.value.length;
                else if (no.type === 'element') contar(no.children);
            }
        };
        contar(arvore.children as ElementContent[]);

        const frente = total + sobra;
        let percorrido = 0;

        const marcar = (pai: Root | Element) => {
            const saida: ElementContent[] = [];

            for (const no of pai.children as ElementContent[]) {
                if (no.type === 'element') {
                    marcar(no);
                    saida.push(no);
                    continue;
                }
                if (no.type !== 'text') {
                    saida.push(no);
                    continue;
                }

                for (const pedaco of no.value.split(/(\s+)/)) {
                    if (!pedaco) continue;

                    percorrido += pedaco.length;
                    const parte = (frente - percorrido) / RASTRO;

                    if (parte >= 1 || /^\s+$/.test(pedaco)) {
                        saida.push({ type: 'text', value: pedaco } as Text);
                        continue;
                    }

                    const t = Math.max(parte, 0);
                    const suave = t * t * (3 - 2 * t);   // borda macia dos dois lados
                    const desloc = ((1 - suave) * 100).toFixed(1);

                    saida.push({
                        type: 'element',
                        tagName: 'span',
                        properties: {
                            className: ['palavra'],
                            style: `opacity:${suave.toFixed(3)};`
                                + `-webkit-mask-position:${desloc}% 0;`
                                + `mask-position:${desloc}% 0`,
                        },
                        children: [{ type: 'text', value: pedaco } as Text],
                    });
                }
            }

            pai.children = saida as typeof pai.children;
        };

        marcar(arvore);
    };
}

function ChatResponse({ text, streaming = false }: { text: string; streaming?: boolean }) {
    const { visivel, sobra, revelando } = useRevelacao(text, streaming);

    return (
        <div className="flex flex-col text-[#FFFFFF] text-lg leading-relaxed">
            <ReactMarkdown
                rehypePlugins={revelando ? [[palavrasReveladas, sobra]] : []}
                components={{
                    h1: ({ children }) => (
                        <h1 className="text-3xl font-roboto font-bold text-white mt-6 mb-3 text-balance">{children}</h1>
                    ),
                    h2: ({ children }) => (
                        <h2 className="text-2xl font-roboto font-semibold text-white mt-5 mb-2 text-balance">{children}</h2>
                    ),
                    h3: ({ children }) => (
                        <h3 className="text-xl font-roboto font-semibold text-white mt-4 mb-2 text-balance">{children}</h3>
                    ),
                    p: ({ children }) => <p className="mb-3 text-[#FFFFFF] text-lg leading-relaxed font-roboto">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold text-lg font-roboto text-white">{children}</strong>,
                    em: ({ children }) => <em className="italic text-[#AEB8CF] font-roboto">{children}</em>,
                    ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>,
                    li: ({ children }) => <li className="ml-2 break-words">{children}</li>,
                    code: ({ children }) => (
                        <code className="bg-white/10 px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>
                    ),
                    pre: ({ children }) => (
                        <pre className="bg-black/30 p-3 rounded-lg overflow-x-auto mb-3 text-sm font-roboto">{children}</pre>
                    ),
                    a: ({ children, href }) => (
                        <a href={href} className="text-[#f1863d] underline hover:text-[#f1863d]/80" target="_blank" rel="noopener noreferrer">
                            {children}
                        </a>
                    ),
                    blockquote: ({ children }) => (
                        <blockquote className="border-l-2 border-[#f1863d] pl-3 italic text-[#AEB8CF] mb-3">
                            {children}
                        </blockquote>
                    ),
                    hr: () => <hr className="border-white/10 my-4" />,
                    table: ({ children }) => (
                        <div className="overflow-x-auto mb-3">
                            <table className="min-w-full border-collapse border border-white/10">{children}</table>
                        </div>
                    ),
                    th: ({ children }) => (
                        <th className="border border-white/10 px-3 py-2 text-left bg-white/5">{children}</th>
                    ),
                    td: ({ children }) => (
                        <td className="border border-white/10 px-3 py-2">{children}</td>
                    ),
                }}
            >
                {visivel}
            </ReactMarkdown>
        </div>
    );
}

/* Só a última mensagem muda durante o stream. */
export default memo(ChatResponse);