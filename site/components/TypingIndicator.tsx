export default function TypingIndicator() {
    return (
    <div className="flex mx-[15%] gap-1 items-center px-2 py-3">
      <span className="w-2 h-2 rounded-full bg-[#AEB8CF] animate-bounce [animation-delay:-0.3s]" />
      <span className="w-2 h-2 rounded-full bg-[#AEB8CF] animate-bounce [animation-delay:-0.15s]" />
      <span className="w-2 h-2 rounded-full bg-[#AEB8CF] animate-bounce" />
    </div>
  );
}