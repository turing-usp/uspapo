"use client";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm'; 
import { memo, useEffect, useRef, useState } from 'react';
import type { Root, Element, Text, ElementContent } from 'hast';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';

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
const remarkPlugins = [remarkGfm];
function ChatResponse({ text, streaming = false }: { text: string; streaming?: boolean }) {
    const { visivel, sobra, revelando } = useRevelacao(text, streaming);

    return (
        <div className="flex flex-col text-foreground text-lg leading-relaxed">
            <ReactMarkdown
                rehypePlugins={
                    /* rehypeRaw revive o HTML cru; rehypeSanitize corta o que não for
                    seguro logo em seguida (o conteúdo vem do modelo). A revelação
                    vem por último: ela injeta spans com style que o sanitize
                    removeria se rodasse depois. */
                    revelando
                        ? [rehypeRaw, rehypeSanitize, [palavrasReveladas, sobra]]
                        : [rehypeRaw, rehypeSanitize]
                }
                remarkPlugins={remarkPlugins}
                components={{
                    h1: ({ children }) => (
                        <h1 className="text-3xl font-roboto font-bold text-foreground mt-6 mb-3 text-balance">{children}</h1>
                    ),
                    h2: ({ children }) => (
                        <h2 className="text-2xl font-roboto font-semibold text-foreground mt-5 mb-2 text-balance">{children}</h2>
                    ),
                    h3: ({ children }) => (
                        <h3 className="text-xl font-roboto font-semibold text-foreground mt-4 mb-2 text-balance">{children}</h3>
                    ),
                    p: ({ children }) => <p className="mb-3 text-foreground text-lg leading-relaxed font-roboto">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold text-lg font-roboto text-foreground">{children}</strong>,
                    em: ({ children }) => <em className="italic text-muted-foreground font-roboto">{children}</em>,
                    ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>,
                    li: ({ children }) => <li className="ml-2 break-words">{children}</li>,
                    code: ({ children }) => (
                        <code className="bg-tint/10 px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>
                    ),
                    pre: ({ children }) => (
                        <pre className="bg-tint/10 p-3 rounded-lg overflow-x-auto mb-3 text-sm font-roboto">{children}</pre>
                    ),
                    a: ({ children, href }) => (
                        <a href={href} className="text-brand underline hover:text-brand/80" target="_blank" rel="noopener noreferrer">
                            {children}
                        </a>
                    ),
                    blockquote: ({ children }) => (
                        <blockquote className="border-l-2 border-brand pl-3 italic text-muted-foreground mb-3">
                            {children}
                        </blockquote>
                    ),
                    hr: () => <hr className="border-line/10 my-4" />,
                    table: ({ children }) => (
                        <div
                            role="region"
                            aria-label="Tabela"
                            tabIndex={0}
                            className="mb-4 overflow-x-auto rounded-xl border border-line/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                        >
                            {/* border-separate porque border-collapse mata o raio do wrapper.
                                A última linha perde o traço para não duplicar com a borda. */}
                            <table className="w-full border-separate border-spacing-0 font-roboto text-base tabular-nums [&_tbody_tr:last-child_td]:border-b-0">
                                {children}
                            </table>
                        </div>
                    ),
                    thead: ({ children }) => <thead className="bg-tint/[0.07]">{children}</thead>,
                    tr: ({ children }) => (
                        <tr className="transition-colors hover:bg-tint/[0.04]">{children}</tr>
                    ),
                    th: ({ children }) => (
                        <th className="whitespace-nowrap border-b border-line/20 px-3 py-2.5 text-left font-semibold text-foreground">
                            {children}
                        </th>
                    ),
                    td: ({ children }) => (
                        <td className="border-b border-line/10 px-3 py-2.5 align-top text-muted-foreground">
                            {children}
                        </td>
                    ),
                    br: () => <br className="my-2" />,
                }}
            >
                {visivel}
            </ReactMarkdown>
        </div>
    );
}

/* Só a última mensagem muda durante o stream. */
export default memo(ChatResponse);