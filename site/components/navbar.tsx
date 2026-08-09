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
          <Link href="/" className="flex items-center justify-center shrink-0">
            <Image
              src="/logo.svg"
              alt="USPapo Logo"
              width={45}
              height={45}
              className="shrink-0 self-center translate-y-0.5"
            />
          </Link>
        </div>
        {/* Este é o container do gap: o MenuUsuario devolve os dois botões num
            fragmento, sem flex próprio. O estilo deles mora lá. */}
        <div className="flex items-center gap-3 md:gap-2">
          <MenuUsuario />
        </div>
      </div>
    </nav>
  );
}
