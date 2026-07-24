import Image from "next/image";
import Link from "next/link";

export default function Navbar() {
  return (
    <nav className="flex flex-row justify-between items-center bg-transparent sticky top-0 left-0 w-full z-40">
      <div className="flex px-[4%] py-[3%] md:py-[1%] justify-between w-full items-center">
        <div className="flex items-center gap-3 ml-12 md:ml-14 transition-all">
          <Link href="/" className="flex items-center gap-2">
            <Image
              src="/logo.svg"
              alt="USPapo Logo"
              width={45}
              height={45}
            />
          </Link>
        </div>
        <div className="flex gap-[0.75rem] md:gap-[1rem]">
          <a href="/entrar">
            <button className="text-[1rem] text-[#f1863d] w-[4rem] md:w-[9rem] h-[2rem] rounded-[2rem] hover:scale-103 transition-transform duration-500 cursor-pointer">
              Entrar
            </button>
          </a>
          <a href="/cadastre-se">
            <button className="text-[1rem] text-[#f1863d] md:border border-[#f1863d] w-[4rem] md:w-[9rem] h-[2rem] rounded-[2rem] hover:scale-103 transition-transform duration-300 cursor-pointer">
              Cadastrar
            </button>
          </a>
        </div>
      </div>
    </nav>
  );
}