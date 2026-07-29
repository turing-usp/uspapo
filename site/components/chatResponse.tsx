import ReactMarkdown from 'react-markdown';

export default function ChatResponse({ text }: { text: string }) {
    return (
        <div className="flex flex-col text-[#FFFFFF] text-lg leading-relaxed">
            <ReactMarkdown
                components={{
                    h1: ({ children }) => (
                        <h1 className="text-3xl font-roboto font-bold text-white mt-6 mb-3 text-balance">{children}</h1>
                    ),
                    h2: ({ children }) => (
                        <h2 className="text-2xl font-roboto font-semibold text-white mt-5 mb-2 text-balance">{children}</h2>
                    ),
                    h3: ({ children }) => (
                        <h3 className="text-xl font-roboto font-semibold text-white mt-4 mb-2 text-balance">{children}</h3>
                    ),
                    p: ({ children }) => <p className="mb-3 text-[#FFFFFF] text-lg leading-relaxed font-roboto">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold text-lg font-roboto text-white">{children}</strong>,
                    em: ({ children }) => <em className="italic text-[#AEB8CF] font-roboto">{children}</em>,
                    ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>,
                    li: ({ children }) => <li className="ml-2 break-words">{children}</li>,
                    code: ({ children }) => (
                        <code className="bg-white/10 px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>
                    ),
                    pre: ({ children }) => (
                        <pre className="bg-black/30 p-3 rounded-lg overflow-x-auto mb-3 text-sm font-roboto">{children}</pre>
                    ),
                    a: ({ children, href }) => (
                        <a href={href} className="text-[#f1863d] underline hover:text-[#f1863d]/80" target="_blank" rel="noopener noreferrer">
                            {children}
                        </a>
                    ),
                    blockquote: ({ children }) => (
                        <blockquote className="border-l-2 border-[#f1863d] pl-3 italic text-[#AEB8CF] mb-3">
                            {children}
                        </blockquote>
                    ),
                    hr: () => <hr className="border-white/10 my-4" />,
                    table: ({ children }) => (
                        <div className="overflow-x-auto mb-3">
                            <table className="min-w-full border-collapse border border-white/10">{children}</table>
                        </div>
                    ),
                    th: ({ children }) => (
                        <th className="border border-white/10 px-3 py-2 text-left bg-white/5">{children}</th>
                    ),
                    td: ({ children }) => (
                        <td className="border border-white/10 px-3 py-2">{children}</td>
                    ),
                }}
            >
                {text}
            </ReactMarkdown>
        </div>
    );
}