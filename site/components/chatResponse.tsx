"use client";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import { memo, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { Components } from 'react-markdown';
import type { Root, Element, Text, ElementContent } from 'hast';
import type { PluggableList } from 'unified';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import rehypeKatex from 'rehype-katex';

/* Largura do rastro de gradiente atrás da frente de revelação, em caracteres. */
const RASTRO = 120;

/* Atraso que a revelação persegue em relação ao stream, em segundos. */
const ATRASO_ALVO = 0.25;
const VELOCIDADE_MINIMA = 30;      // caracteres por segundo
const DRENO = RASTRO / 0.4;        // velocidade para apagar o rastro no fim
const INTERVALO_RENDER = 33;       // ms entre re-renders (o markdown é reparseado)

/* Estável de propósito: o perfil do vidro é decidido pelo script do layout.tsx
   antes do primeiro quadro e não muda mais na vida da página, então não há o
   que assinar. Pesado no servidor, que é o padrão do CSS. */
const assinarNada = () => () => {};
const lerVidroLeve = () => document.documentElement.dataset.vidro === "leve";
const sempreCarregado = () => false;

function useVidroLeve() {
    return useSyncExternalStore(assinarNada, lerVidroLeve, sempreCarregado);
}

function useRevelacao(texto: string, streaming: boolean, leve: boolean) {
    const [contador, setContador] = useState(() => (streaming ? 0 : texto.length + RASTRO));
    const posicao = useRef(contador);
    const alvo = useRef(texto);
    const ativo = useRef(streaming);

    useEffect(() => {
        alvo.current = texto;
        ativo.current = streaming;

        const destino = () => alvo.current.length + RASTRO;

        /* No perfil leve a revelação inteira sai de cena: ela envolve cada
           palavra da frente num <span> com máscara, e é isso, não o gradiente
           em si, que reconstrói a árvore a cada quadro. O texto passa a
           aparecer por bloco, que é o mesmo tratamento que o
           prefers-reduced-motion já dá à máscara no globals.css. */
        if (leve) {
            posicao.current = destino();
            setContador(destino());
            return;
        }

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
    }, [texto, streaming, leve]);

    const revelado = Math.min(Math.floor(contador), texto.length);

    return {
        visivel: texto.slice(0, revelado),
        sobra: Math.max(0, contador - texto.length),
        /* Enquanto houver gradiente na tela, os spans precisam existir. */
        revelando: !leve && (streaming || contador < texto.length + RASTRO),
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
/* ─────────────────────────────────────────────
   Matemática
   ───────────────────────────────────────────── */

/* Um trecho de código: cerca de três crases (aberta em pedaço ainda não
   fechado, durante o stream) ou crase simples. Vira grupo de captura para o
   `split` devolver o código junto e a conversão passar longe dele. */
const CODIGO = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g;
const DISPLAY = /\\\[([\s\S]+?)\\\]/g;
const INLINE = /\\\(([\s\S]+?)\\\)/g;

/**
 * Converte os delimitadores `\(…\)` e `\[…\]` do modelo para os `$$` que o
 * remark-math entende.
 *
 * Tem que ser na string, e não num plugin: o CommonMark trata `\(` como escape
 * de `(` e come a barra antes de qualquer plugin ver a árvore. Quando o remark
 * roda, o delimitador já não existe mais.
 *
 * O cifrão sozinho fica DESLIGADO (`singleDollarTextMath: false`) porque em
 * português ele é dinheiro: "custa R$ 2 e o outro R$ 3" viraria fórmula com o
 * padrão do remark-math. Por isso a conversão sempre gera `$$`, que não colide.
 *
 * Fórmula pela metade no meio do stream não casa e segue como texto até o
 * fechamento chegar, que é exatamente o que se quer.
 */
function normalizarMatematica(texto: string): string {
    if (!texto.includes('\\(') && !texto.includes('\\[')) return texto;

    return texto
        .split(CODIGO)
        .map((trecho, indice) =>
            indice % 2 === 1        // ímpar é o próprio código, intocado
                ? trecho
                : trecho
                    .replace(DISPLAY, (_, corpo: string) => `\n\n$$\n${corpo.trim()}\n$$\n\n`)
                    .replace(INLINE, (_, corpo: string) => `$$${corpo.trim()}$$`)
        )
        .join('');
}

/* ─────────────────────────────────────────────
   Corte entre o que já assentou e o que ainda está sendo escrito
   ───────────────────────────────────────────── */

/* Quanto de fonte fica do lado vivo do corte. Dois rastros: o gradiente da
   revelação tem que caber inteiro na cauda, e a fonte é sempre maior que o
   texto renderizado (a sintaxe do markdown some), então o dobro dá folga. */
const MINIMO_CAUDA = RASTRO * 2;

/* Uma linha que NÃO pode abrir a cauda, porque cortar antes dela mudaria o
   significado do markdown em vez de só reparti-lo:

   indentação/tab   continuação de item ou bloco de código indentado
   > |              citação e linha de tabela continuam o bloco anterior
   ``` ~~~ $$       abre ou fecha cerca; o par é conferido à parte
   <                HTML cru, que o rehypeRaw pode precisar ver inteiro
   - * + 1.         item de lista: cortar aqui parte a lista em duas, e numa
                    lista ordenada a segunda metade recomeça do 1
   --- ===          régua e sublinhado de título setext

   Sobra o caso seguro e o mais comum: parágrafo ou título depois de linha em
   branco. Como um bloco desses fecha qualquer lista aberta antes dele, cortar
   ali é garantido não deixar lista pela metade. */
const LINHA_INSEGURA =
    /^(?:[ ]{4}|\t|>|\||```|~~~|\$\$|<|(?:[-*+]|\d{1,9}[.)])\s|(?:[-*_][ \t]*){3,}$|(?:=+|-+)[ \t]*$)/;

function parElementos(trecho: string, marca: string): boolean {
    return trecho.split(marca).length % 2 === 1;
}

/**
 * Parte a resposta em `[assentado, cauda]`.
 *
 * O `assentado` é markdown que não muda mais: fica num bloco memoizado e sai
 * do caminho caro. Só a `cauda` é reparseada a cada quadro do stream, então o
 * custo por quadro para de crescer junto com o tamanho da resposta, que era o
 * que fazia uma resposta longa engasgar no fim, justamente quando há mais
 * texto na tela e mais vidro para recompor.
 *
 * Na dúvida devolve `["", fonte]`, que é o comportamento de sempre: uma
 * resposta que é uma lista só, sem parágrafo entre os itens, simplesmente não
 * acha corte e segue inteira no caminho vivo.
 */
export function cortarAssentado(fonte: string): [string, string] {
    if (fonte.length < MINIMO_CAUDA * 2) return ["", fonte];

    let limite = fonte.length - MINIMO_CAUDA;

    while (limite > 0) {
        const quebra = fonte.lastIndexOf("\n\n", limite);
        if (quebra <= 0) break;

        /* O corte cai no primeiro caractere depois da corrida de \n. */
        let inicio = quebra;
        while (fonte[inicio] === "\n") inicio++;

        const antes = fonte.slice(0, inicio);
        const fimDaLinha = fonte.indexOf("\n", inicio);
        const proxima = fonte.slice(inicio, fimDaLinha === -1 ? undefined : fimDaLinha);

        if (
            proxima.trim() !== "" &&
            !LINHA_INSEGURA.test(proxima) &&
            parElementos(antes, "```") &&
            parElementos(antes, "$$")
        ) {
            return [antes, fonte.slice(inicio)];
        }

        limite = quebra - 1;
    }

    return ["", fonte];
}

const remarkPlugins: PluggableList = [remarkGfm, [remarkMath, { singleDollarTextMath: false }]];

/* O KaTeX vem por último de propósito, depois do sanitize e da revelação.
   Depois do sanitize porque o que ele produz é span com style e MathML, que o
   esquema padrão apagaria, e não precisa passar por lá: a fonte da fórmula já
   veio higienizada. Depois da revelação porque `palavrasReveladas` reescreve
   TODO nó de texto da árvore, e picotar os spans internos do KaTeX destrói o
   layout da fórmula. Rodando por último, ele descarta os spans de revelação que
   caíram dentro da fórmula: ela aparece inteira, e não letra a letra.

   `errorColor` neutro porque a cada 33 ms o stream reparseia uma fórmula ainda
   pela metade; no vermelho padrão (#cc0000) a resposta pisca em erro enquanto o
   modelo digita. */
const OPCOES_KATEX = { errorColor: 'currentColor' };
const REHYPE_PRONTO: PluggableList = [rehypeRaw, rehypeSanitize, [rehypeKatex, OPCOES_KATEX]];

/* Fora do componente de propósito: montado dentro do render, este objeto
   nasceria de novo a cada 33 ms do stream e levaria junto a identidade de cada
   elemento que ele descreve. */
const COMPONENTES: Components = {
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
};

/* Um pedaço já pronto da resposta. Memoizado pela própria string: enquanto o
   corte não anda, o React nem chama isto de novo, e o parse do markdown some
   da conta do quadro. */
const BlocoPronto = memo(function BlocoPronto({ fonte }: { fonte: string }) {
    return (
        <ReactMarkdown
            remarkPlugins={remarkPlugins}
            rehypePlugins={REHYPE_PRONTO}
            components={COMPONENTES}
        >
            {fonte}
        </ReactMarkdown>
    );
});

function ChatResponse({ text, streaming = false }: { text: string; streaming?: boolean }) {
    const leve = useVidroLeve();
    const { visivel, sobra, revelando } = useRevelacao(text, streaming, leve);

    /* A conversão de \(…\) para $$ vem antes do corte para o corte poder
       contar os $$ e nunca partir uma fórmula ao meio. */
    const [assentado, cauda] = cortarAssentado(normalizarMatematica(visivel));

    /* rehypeRaw revive o HTML cru; rehypeSanitize corta o que não for seguro
       logo em seguida (o conteúdo vem do modelo). A revelação vem depois: ela
       injeta spans com style que o sanitize removeria se rodasse antes. Por que
       o KaTeX fecha a fila: ver a nota em REHYPE_PRONTO.

       O `sobra` é distância até o fim, e `palavrasReveladas` mede o texto da
       árvore que recebe — que aqui é só a cauda. Por isso a revelação continua
       caindo no lugar certo depois do corte, sem saber que houve corte. */
    const rehypeVivo: PluggableList = [
        rehypeRaw,
        rehypeSanitize,
        [palavrasReveladas, sobra],
        [rehypeKatex, OPCOES_KATEX],
    ];

    return (
        <div className="flex flex-col text-foreground text-lg leading-relaxed [&>p:last-child]:mb-1">
            {assentado && <BlocoPronto fonte={assentado} />}
            {revelando ? (
                <ReactMarkdown
                    remarkPlugins={remarkPlugins}
                    rehypePlugins={rehypeVivo}
                    components={COMPONENTES}
                >
                    {cauda}
                </ReactMarkdown>
            ) : (
                <BlocoPronto fonte={cauda} />
            )}
        </div>
    );
}

/* Só a última mensagem muda durante o stream. */
export default memo(ChatResponse);