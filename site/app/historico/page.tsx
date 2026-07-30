
"use client";
import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { listarConversas, apagarConversa, type Conversa } from "@/lib/conversas";

type Grupo = { rotulo: string; conversas: Conversa[] };

function agrupar(conversas: Conversa[]): Grupo[] {
  const agora = new Date();
  const inicioHoje = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate()).getTime();
  const DIA = 86_400_000;

  const baldes: Record<string, Conversa[]> = {
    "Hoje": [], "Ontem": [], "Últimos 7 dias": [], "Últimos 30 dias": [], "Há mais tempo": [],
  };

  for (const c of conversas) {
    if (c.criadoEm >= inicioHoje) baldes["Hoje"].push(c);
    else if (c.criadoEm >= inicioHoje - DIA) baldes["Ontem"].push(c);
    else if (c.criadoEm >= inicioHoje - 7 * DIA) baldes["Últimos 7 dias"].push(c);
    else if (c.criadoEm >= inicioHoje - 30 * DIA) baldes["Últimos 30 dias"].push(c);
    else baldes["Há mais tempo"].push(c);
  }

  return Object.entries(baldes)
    .filter(([, lista]) => lista.length > 0)
    .map(([rotulo, lista]) => ({ rotulo, conversas: lista }));
}

function formatarData(timestamp: number) {
  const data = new Date(timestamp);
  const hoje = new Date();
  const ehHoje = data.toDateString() === hoje.toDateString();

  return ehHoje
    ? `Hoje, ${data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`
    : data.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Historico() {
  const router = useRouter();
  const [conversas, setConversas] = useState<Conversa[]>([]);
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [agrupadas, setAgrupadas] = useState<Grupo[]>([]);

  useEffect(() => {
    const conversas = listarConversas();
    setConversas(conversas);
    setAgrupadas(agrupar(conversas));
    setCarregando(false);
  }, []);

  const filtradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    if (!termo) return conversas;
    return conversas.filter((c) =>
      c.titulo.toLowerCase().includes(termo) ||
      c.mensagens.some(
        (m) => m.user.toLowerCase().includes(termo) || m.bot.toLowerCase().includes(termo)
      )
    );
  }, [conversas, busca]);

  const filtradasAgrupadas = useMemo(() => agrupar(filtradas), [filtradas]);

  const remover = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    apagarConversa(id);
    setConversas(listarConversas());
  };

  return (
    <div className="app-container-chat flex flex-1 flex-col pt-8 pb-[max(4rem,env(safe-area-inset-bottom))]">
      <div className="flex items-center mb-2">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-7 h-7 text-[#ffffff]">
            <circle cx="12" cy="12" r="10" strokeWidth="2" fill="none" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
        </svg>
        <p className="font-geom text-2xl sm:text-3xl ml-3">Histórico de conversas</p>
      </div>
      <p className="text-[#AEB8CF] ml-3 mb-4">Retome suas perguntas anteriores e continue de onde parou</p>
      <div className="glass w-full rounded-[2rem] mb-8">
        <input
          type="text"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="Buscar nas conversas"
          className="relative w-full h-14 px-5 rounded-[2rem] bg-transparent text-white text-base placeholder:text-[#AEB8CF] border-[0.15rem] border-white/25 focus:border-[#f1863d] focus:outline-none transition-colors"
        />
      </div>

      {carregando ? null : filtradas.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-[#AEB8CF] mb-4">
            {busca ? "Nenhuma conversa encontrada." : "Você ainda não tem conversas salvas."}
          </p>
          {!busca && (
            <Link
              href="/"
              className="inline-block px-6 py-2.5 rounded-2xl border border-[#f1863d] text-[#f1863d] hover:bg-[#f1863d]/10 transition-colors"
            >
              Começar uma conversa
            </Link>
          )}
        </div>
      ) : (
        <div>
          {filtradasAgrupadas.map((grupo) => (
            <div key={grupo.rotulo} className="mb-6">
              <p className="text-[#AEB8CF] text-sm font-medium mb-3">{grupo.rotulo}</p>
              <ul className="flex flex-col gap-3">
                {grupo.conversas.map((conversa) => {
                  return (
                    <li key={conversa.id}>
                      <Link
                        href={`/chat/${conversa.id}`}
                        className="group flex items-start justify-between gap-4 p-4 pl-5 rounded-2xl overflow-hidden glass hover:bg-[#F5F5F5]/40 transition-colors">
                      {/* Acento como elemento opaco recortado pelo overflow-hidden do Link,
                          NÃO como border-l-4: um border de 4px num raio de 16px afina até
                          virar um fio nos cantos, e o antialiasing desse taper lê como blur. */}
                      <span
                        aria-hidden
                        className="absolute inset-y-0 left-0 w-1 bg-transparent group-hover:bg-[#f1863d] transition-colors"
                      />
                      <div className="min-w-0">
                        <p className="text-white text-base sm:text-lg truncate">{conversa.titulo}</p>
                        <p className="text-[#AEB8CF] text-sm mt-1">
                          {formatarData(conversa.criadoEm)} · {conversa.mensagens.length}{" "}
                          {conversa.mensagens.length === 1 ? "pergunta" : "perguntas"}
                        </p>
                      </div>

                      <button
                        onClick={(e) => remover(e, conversa.id)}
                        aria-label="Apagar conversa"
                        title="Apagar conversa"
                        className="shrink-0 p-2 rounded-lg text-[#AEB8CF] hover:text-red-400 hover:bg-white/5 transition-colors cursor-pointer"
                      >
                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673A2.25 2.25 0 0 1 15.916 21H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
                          />
                        </svg>
                      </button>
                    </Link>
                  </li>
                )})}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}