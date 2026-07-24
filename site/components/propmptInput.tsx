import Image from "next/image";

export default function PromptInput({ value, onChange, onSubmit }: { value: string; onChange: (value: string) => void; onSubmit: (e: React.SyntheticEvent) => void;}) {
    return (
        <form onSubmit={onSubmit} className="relative flex justify-center items-center my-[6%] md:my-[0%] md:mt-[3%] mx-[5%]">
                    <div className="relative md:w-[60%]">
                      <button type="button" className="absolute left-4 top-1/2 -translate-y-1/2 text-[#f1863d] text-[2.5rem] hover:cursor-pointer">
                        ＋
                      </button>
                      <input 
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
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
    );
}