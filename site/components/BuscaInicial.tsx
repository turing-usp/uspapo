"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import PromptInput from "./propmptInput";
import { salvarConversa, gerarTitulo, novoId,PENDENTE } from "@/lib/conversas";
import { sortear, QUANTAS_EXIBIR, type PerguntaFrequente } from "@/lib/perguntas";

export default function BuscaInicial({ perguntasFrequentes }: { perguntasFrequentes: PerguntaFrequente[] }) {
  const router = useRouter();
  const [pergunta, setPergunta] = useState("");

  /* O sorteio não pode acontecer no render: este componente também roda no
     servidor, e um Math.random() ali daria markup diferente do da hidratação.
     Então o primeiro render mostra as primeiras da lista, determinístico dos
     dois lados, e o sorteio entra depois de montado. Como a quantidade de
     botões não muda, a troca não desloca nada. */
  const [visiveis, setVisiveis] = useState(() =>
    perguntasFrequentes.slice(0, QUANTAS_EXIBIR)
  );

  useEffect(() => {
    setVisiveis(sortear(perguntasFrequentes, QUANTAS_EXIBIR));
  }, [perguntasFrequentes]);

    const enviarPergunta = async (texto: string) => {
    if (!texto.trim()) return;
    const id = novoId();
    await salvarConversa({
      id,
      titulo: gerarTitulo(texto),
      criadoEm: Date.now(),
      mensagens: [{ user: texto, bot: PENDENTE }],
    });
    router.push(`/chat/${id}`);
  };

  const lidarComEnvio = (e: React.SyntheticEvent) => {
    e.preventDefault();
    enviarPergunta(pergunta);
  };

  return (
    <>
      <div className="app-container mt-8 md:mt-10 curto:mt-4 curtinho:mt-2">
        <PromptInput value={pergunta} onChange={setPergunta} onSubmit={lidarComEnvio} />
      </div>
      <div className="app-container flex flex-col items-center mt-10 md:mt-12 curto:mt-5 curtinho:mt-2">
        <p className="font-geom text-base text-foreground">Perguntas Frequentes</p>
        <div className="flex flex-col md:flex-row md:flex-wrap justify-center items-stretch gap-4 md:gap-6 curto:gap-2 mt-6 curto:mt-3 w-full">
          {visiveis.map((frequente) => (
            <button
              key={frequente.trecho}
              className="glass flex flex-col justify-center items-center text-center w-full h-14 curto:h-12 md:w-auto md:flex-1 md:basis-0 md:min-w-[11rem] max-w-[18rem] mx-auto min-h-[3rem] px-4 py-2 rounded-[2rem] text-foreground transition-colors hover:text-brand hover:cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
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
