import Image from "next/image";
import Link from "next/link";

export default function Navbar() {
  return (
    <nav className="flex flex-row justify-between items-center bg-transparent sticky top-0 left-0 w-full z-40">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[150%] -z-10 page-fade-b"
      />
      <div className="flex w-full px-4 md:px-6 py-3 justify-between items-center">
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
        <div className="flex gap-3 md:gap-2">
          <a href="/entrar">
            <button className="text-sm md:text-base text-[#f1863d] px-4 md:px-8 py-1.5 rounded-[2rem] whitespace-nowrap hover:scale-103 transition-transform duration-500 cursor-pointer">
              Entrar
            </button>
          </a>
          <a href="/cadastro">
            <button className="text-sm md:text-base text-[#f1863d] border border-[#f1863d] px-4 md:px-8 py-1.5 rounded-[2rem] whitespace-nowrap hover:scale-103 transition-transform duration-300 cursor-pointer">
              Cadastrar
            </button>
          </a>
        </div>
      </div>
    </nav>
  );
}