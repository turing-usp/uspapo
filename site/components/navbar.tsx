import Image from "next/image";
import Link from "next/link";

export default function Navbar() {
    return(
         <nav className={`flex flex-row justify-between items-center bg-transparent sticky top-0 left-0 w-full z-50
            `}>
            <div className='flex px-[5%] py-[1%] justify-between w-full items-center'>
                <div className='flex justify-center gap-4'>
                    <Link href='/' className='flex items-center'>
                        <Image
                            src="/logo.svg"
                            alt=''
                            width={50}
                            height={50}
                        />
                    </Link>
                </div>
                 <div className='hidden lg:flex gap-[1rem]'>
                        <a href="/entrar"><button className={`text-[1rem] text-[#f1863d] w-[9rem] h-[2rem] rounded rounded-[2rem] hover:scale-103 transition-transform duration-500 cursor-pointer`}>Entrar</button></a>
                        <a href="/cadastre-se"><button className={`text-[1rem] text-[#f1863d] border border-[#f1863d] w-[9rem] h-[2rem] rounded rounded-[2rem] hover:scale-103 transition-transform duration-300 cursor-pointer`}>Cadastrar</button></a>
                </div>
            </div>
        </nav>
    )
}