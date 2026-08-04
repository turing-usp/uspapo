import Image from "next/image";
import Link from "next/link";
import Leftmenu from "./leftmenu";
import MenuUsuario from "./Menuusuario";

export default function Navbar() {
  return (
    /* Filho direto do app-shell: não rola, então não precisa de sticky.
       O z-30 cria o stacking context que segura o fade abaixo do conteúdo
       da barra e acima do que rola no app-scroll. */
    <nav className="relative z-30 flex flex-none flex-row justify-between items-center w-full">
      <div className="flex w-full px-3 md:px-6 py-3 justify-between items-center gap-3">
        <div className="flex items-center gap-3">
          {/* O gatilho do menu agora é um item em fluxo daqui, e não uma
              camada fixa flutuando por cima. Ver o comentário em leftmenu. */}
          <Leftmenu />
          <Link href="/" className="flex items-center gap-2">
            <Image
              src="/logo.svg"
              alt="USPapo Logo"
              width={45}
              height={45}
            />
          </Link>
        </div>
        {/* O estilo vai no próprio Link: <button> dentro de <a> herdava a cor
            de botão do navegador em alguns temas e é aninhamento interativo.

            O Cadastrar não leva `border`, e sim glass-brand: o fio já é
            desenhado pelo ::after do vidro, e uma borda por cima duplicaria o
            traço */}
        <div className="flex gap-3 md:gap-2">
          <MenuUsuario />
        </div>
      </div>
    </nav>
  );
}
