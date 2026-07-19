import Image from "next/image";
import Navbar from "../components/navbar";
import Leftmenu from "../components/leftmenu";

export default function Home() {
  return (
    <>
      <Navbar>
      </Navbar>
      <Leftmenu>
      </Leftmenu>
      <div className="flex flex-col items-center h-[20%] mt-[3%] mx-[5%]">
        <div className="flex flex-row justify-center items-center">
          <Image
            src="/uspapo.png"
            alt=""
            width={60}
            height={60}
          />
          <p className="font-geom text-[3rem] text-[#f1863d] ml-[2%]">USPapo</p>
        </div>
        <p className="font-geom text-[1.25rem] text-[#FFFFFF] mt-[2%]">Seu <span className="font-geom text-[1.25rem] text-[#f1863d]">assistente inteligente</span> para navegar pela USP</p>
      </div>
      <form className="relative flex justify-center items-center mt-[3%] mx-[5%]">
        <div className="relative w-[60%]">
          <button type="button" className="absolute left-4 top-1/2 -translate-y-1/2 text-[#f1863d] text-[2.5rem] hover:cursor-pointer">
            ＋
          </button>
          <input 
            className="bg-[#FFFFFF]/20 text-[#AEB8CF] text-[1.25rem] px-[5rem] w-full h-[3.5rem] rounded-[2rem] border border-[#f1863d] border-[0.15rem] placeholder:text-[#AEB8CF] focus:outline-none" 
            placeholder="Pesquise sobre a USP" 
          />
          <button type="button" className="absolute right-4 top-1/2 -translate-y-1/2 hover:cursor-pointer">
            <Image
              src="/mic.png"
              alt=""
              width={20}
              height={20}
            />
          </button>
        </div>
      </form>
      <div className="flex flex-col items-center mt-[3%] mx-[5%]">
        <p className="font-geom text-[1rem] text-[#ffffff]">Perguntas Frequentes</p>
        <div className="flex flex-row justify-center items-center gap-[2rem] mt-[2%]">
          <button className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer">
            O que é o USPapo?
          </button>
          <button className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer">
            O que é o Jupiterweb?
          </button>
          <button className="flex flex-col justify-center items-center bg-[#FFFFFF]/20 w-[15rem] h-[3rem] rounded-[2rem] border border-[#ffffff] border-[0.05rem] hover:cursor-pointer">
           Cardápio de hoje?
          </button>
        </div>
      </div>
      <div className="flex flex-row justify-center items-center mt-[4%] mx-[5%]">
          <p className="font-geom text-[1rem] text-[#f1863d]">Desenvolvido por</p>
          <div className="flex flex-row justify-center items-center ml-[0.5%]">
          <Image
            src="/logo.svg"
            alt=""
            width={30}
            height={30}
          />
          <p className="font-orbitron text-[1rem] text-[#f1863d]">turing.usp</p>
          </div>
      </div>
    </>
  );
}
