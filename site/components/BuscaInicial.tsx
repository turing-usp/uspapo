"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import PromptInput from "./propmptInput";
import { novoId } from "@/lib/conversas";
import { guardarPendente } from "@/lib/pendente";
import { sortear, QUANTAS_EXIBIR, type PerguntaFrequente } from "@/lib/perguntas";

export default function BuscaInicial({ perguntasFrequentes }: { perguntasFrequentes: PerguntaFrequente[] }) {
  const router = useRouter();
  const [pergunta, setPergunta] = useState("");
  /* Só para travar a interface. Quem decide de verdade é o ref logo abaixo. */
  const [enviando, setEnviando] = useState(false);
  const enviandoRef = useRef(false);

  /* O sorteio não pode acontecer no render: este componente também roda no
     servidor, e um Math.random() ali daria markup diferente do da hidratação.
     Então o primeiro render mostra as primeiras da lista, determinístico dos
     dois lados, e o sorteio entra depois de montado. Como a quantidade de
     botões não muda, a troca não desloca nada. */
  const [visiveis, setVisiveis] = useState(() =>
    perguntasFrequentes.slice(0, QUANTAS_EXIBIR)
  );

  useEffect(() => {
    /* O sorteio vive aqui de propósito: fora do render a hidratação quebra
       (ver o comentário acima do estado), então o set direto no efeito é o
       lugar certo. */
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVisiveis(sortear(perguntasFrequentes, QUANTAS_EXIBIR));
  }, [perguntasFrequentes]);

  /* O id da conversa é cunhado aqui, no primeiro render, e não no envio.
     Desde o export estático da Estratégia A a rota /chat é estática e o id
     mora na query string (?id=<uuid>): o export não conhece o id, mas a
     página dá para aquecer (prefetch) enquanto a pessoa digita, e aí o push
     acontece no mesmo quadro. */
  const idRef = useRef<string | null>(null);
  if (idRef.current === null) idRef.current = novoId();

  useEffect(() => {
    router.prefetch(`/chat?id=${idRef.current}`);
  }, [router]);

  /* Sem await, sem banco: guarda a pergunta na memória e navega. Quem grava é
     o próprio /chat, no efeito que ele já tinha, em segundo plano. */
  const enviarPergunta = (texto: string) => {
    /* O ref, e não o estado: dois Enter no mesmo tick leem o mesmo `enviando`
       antigo, porque setState não é síncrono. Antes não havia trava nenhuma e o
       campo nunca era limpo, então cada Enter chamava novoId() de novo e criava
       uma conversa inteira nova. */
    if (!texto.trim() || enviandoRef.current) return;
    enviandoRef.current = true;
    setEnviando(true);

    guardarPendente(idRef.current!, texto);
    router.push(`/chat?id=${idRef.current}`);
  };

  const lidarComEnvio = (e: React.SyntheticEvent) => {
    e.preventDefault();
    enviarPergunta(pergunta);
  };

  return (
    <>
      <div className="app-container mt-8 md:mt-10 curto:mt-4 curtinho:mt-2">
        <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} disabled={enviando} />
      </div>
      <div className="app-container flex flex-col items-center mt-10 md:mt-12 curto:mt-5 curtinho:mt-2">
        <p className="font-geom text-base text-foreground">Perguntas Frequentes</p>
        <div className="flex flex-col md:flex-row md:flex-wrap justify-center items-stretch gap-4 md:gap-6 curto:gap-2 mt-6 curto:mt-3 w-full">
          {visiveis.map((frequente) => (
            <button
              key={frequente.trecho}
              /* Mesmo buraco do campo: clicar dois cards em sequência rápida
                 criava duas conversas. A trava do enviarPergunta cobre os dois
                 caminhos; o disabled é o retorno visual. */
              disabled={enviando}
              className="glass flex flex-col justify-center items-center text-center w-full h-14 curto:h-12 md:w-auto md:flex-1 md:basis-0 md:min-w-[11rem] max-w-[18rem] mx-auto min-h-[3rem] px-4 py-2 rounded-[2rem] text-foreground transition-colors hover:text-brand hover:cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:pointer-events-none disabled:opacity-60"
              onClick={() => enviarPergunta(frequente.prompt)}
            >
              <span className="text-balance">{frequente.trecho}</span>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
