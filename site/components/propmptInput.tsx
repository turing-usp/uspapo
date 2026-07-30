import Image from "next/image";

export default function PromptInput({ value, onChange, onSubmit }: { value: string; onChange: (value: string) => void; onSubmit: (e: React.SyntheticEvent) => void; }) {
  return (
    <form onSubmit={onSubmit} className="relative flex justify-center items-center w-full">
      <div className="glass w-full rounded-[2rem]">
        <button type="button" className="absolute left-3 md:left-4 top-1/2 -translate-y-1/2 z-10 text-[#f1863d] text-3xl md:text-4xl leading-none hover:cursor-pointer">
          ＋
        </button>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="relative bg-transparent text-white text-base md:text-lg pl-13 pr-12 md:pl-16 md:pr-14 w-full h-14 rounded-[2rem] border-[0.15rem] border-[#f1863d] placeholder:text-[#AEB8CF] focus:outline-none"
          placeholder="Pesquise sobre a USP"
        />
        <button
          type={value.trim() ? "submit" : "button"}
          className="absolute right-4 top-1/2 -translate-y-1/2 hover:cursor-pointer z-10"
          aria-label={value.trim() ? "Enviar pergunta" : "Falar"}
        >
          {value.trim() ? (
            <span className="flex items-center justify-center w-9 h-9 rounded-full bg-[#f1863d] hover:bg-[#f1863d]/85 transition-colors">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5m0 0l-6 6m6-6l6 6" />
              </svg>
            </span>
          ) : (
            <Image src="/mic.png" alt="" width={20} height={20} />
          )}
        </button>
      </div>
    </form>
  );
}