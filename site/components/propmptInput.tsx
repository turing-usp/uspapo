import Image from "next/image";

export default function PromptInput({ value, onChange, onSubmit }: { value: string; onChange: (value: string) => void; onSubmit: (e: React.SyntheticEvent) => void; }) {
  return (
    <form onSubmit={onSubmit} className="relative flex justify-center items-center w-full">
      <div className="relative w-full rounded-[2rem]">
        <div aria-hidden className="pointer-events-none absolute inset-0 z-0 rounded-[2rem] glass-radial-blur" />
        <button type="button" className="absolute left-3 md:left-4 top-1/2 -translate-y-1/2 z-10 text-[#f1863d] text-3xl md:text-4xl leading-none hover:cursor-pointer">
          ＋
        </button>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="relative z-10 bg-[#FFFFFF]/20 text-[#AEB8CF] text-base md:text-lg pl-13 pr-12 md:pl-16 md:pr-14 w-full h-14 rounded-[2rem] border border-[#f1863d] border-[0.15rem] placeholder:text-[#AEB8CF] focus:outline-none"
          placeholder="Pesquise sobre a USP"
        />
        <button type="button" className="absolute right-4 top-1/2 -translate-y-1/2 z-10 shrink-0 hover:cursor-pointer">
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