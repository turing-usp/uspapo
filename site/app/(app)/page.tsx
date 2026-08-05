import Image from "next/image";
import BuscaInicial from "../../components/BuscaInicial";
import { PERGUNTAS_FREQUENTES } from "@/lib/perguntas";

export default function Home() {
  return (
    <div className="app-scroll">
      <div className="flex min-h-full flex-col">
        <div className="flex flex-1 flex-col justify-center py-8 curto:py-3 curtinho:py-1">
          <div className="app-container flex flex-col items-center">
            <div className="flex flex-col md:flex-row mb-3 curto:mb-1 justify-center items-center gap-2">
              <Image
                src="/uspapo.svg"
                alt=""
                width={40}
                height={40}
              />
              <p className="font-geom text-4xl md:text-5xl curtinho:text-3xl text-brand ml-1">USPapo</p>
            </div>
            <p className="font-geom text-base md:text-xl text-foreground mt-3 mb-6 curto:mt-1 curto:mb-2 curtinho:mb-0 text-center text-balance">Seu <span className="text-brand">assistente inteligente</span> para navegar pela USP</p>
          </div>
          <BuscaInicial perguntasFrequentes={PERGUNTAS_FREQUENTES} />
        </div>
        <div className="app-container flex flex-row flex-wrap justify-center items-center gap-x-2 py-6 curto:py-3">
            <p className="font-geom text-base text-brand">Desenvolvido por</p>
            <div className="flex flex-row justify-center items-center gap-1">
              <Image
                src="/logo.svg"
                alt=""
                width={30}
                height={30}
              />
              <p className="font-orbitron text-base text-brand">turing.usp</p>
            </div>
        </div>
      </div>
    </div>
  );
}
