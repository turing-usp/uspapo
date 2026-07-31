
"use client";
import { useState, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { listarConversas, apagarConversa, alternarFavorita, renomearConversa, type Conversa } from "@/lib/conversas";
import { MenuConversa } from "@/components/MenuConversa";

type Grupo = { rotulo: string; conversas: Conversa[] };

function agrupar(conversas: Conversa[]): Grupo[] {
  const agora = new Date();
  const inicioHoje = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate()).getTime();
  const DIA = 86_400_000;

  const favoritas = conversas.filter((c) => c.favorita);
  const resto = conversas.filter((c) => !c.favorita);

  const baldes: Record<string, Conversa[]> = {
    "Hoje": [], "Ontem": [], "Últimos 7 dias": [], "Últimos 30 dias": [], "Há mais tempo": [],
  };

  for (const c of resto) {                              // ← resto, não conversas
    if (c.criadoEm >= inicioHoje) baldes["Hoje"].push(c);
    else if (c.criadoEm >= inicioHoje - DIA) baldes["Ontem"].push(c);
    else if (c.criadoEm >= inicioHoje - 7 * DIA) baldes["Últimos 7 dias"].push(c);
    else if (c.criadoEm >= inicioHoje - 30 * DIA) baldes["Últimos 30 dias"].push(c);
    else baldes["Há mais tempo"].push(c);
  }

  const grupos = Object.entries(baldes)
    .filter(([, lista]) => lista.length > 0)
    .map(([rotulo, lista]) => ({ rotulo, conversas: lista }));

  return favoritas.length > 0
    ? [{ rotulo: "Favoritas", conversas: favoritas }, ...grupos]   // ← favoritas primeiro
    : grupos;
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

  const [editandoId, setEditandoId] = useState<string | null>(null);
  const [novoTitulo, setNovoTitulo] = useState("");

  const iniciarEdicao = (conversa: Conversa) => {
    setEditandoId(conversa.id);
    setNovoTitulo(conversa.titulo);
  };

  const confirmarEdicao = () => {
    if (editandoId && novoTitulo.trim()) {
      renomearConversa(editandoId, novoTitulo);
      setConversas(listarConversas());
    }
    setEditandoId(null);
  };

  useEffect(() => {
    const conversas = listarConversas();
    setConversas(conversas);
    setAgrupadas(agrupar(conversas));
    setCarregando(false);
  }, []);

  const [pendente, setPendente] = useState<Conversa | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const filtradas = useMemo(() => {
    const semPendente = conversas.filter((c) => c.id !== pendente?.id);

    const termo = busca.trim().toLowerCase();
    if (!termo) return semPendente;

    return semPendente.filter((c) =>
      c.titulo.toLowerCase().includes(termo) ||
      c.mensagens.some(
        (m) => m.user.toLowerCase().includes(termo) || m.bot.toLowerCase().includes(termo)
      )
    );
  }, [conversas, busca, pendente]);

  const filtradasAgrupadas = useMemo(() => agrupar(filtradas), [filtradas]);

  const apagarComDesfazer = (conversa: Conversa) => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      apagarConversa(pendente!.id);   // confirma a exclusão anterior antes de começar outra
    }

    setPendente(conversa);
    timerRef.current = setTimeout(() => {
      apagarConversa(conversa.id);
      setConversas(listarConversas());
      setPendente(null);
      timerRef.current = null;
    }, 6000);
  };

  const desfazer = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    setPendente(null);
  };

  useEffect(() => {
    return () => {
      if (timerRef.current && pendente) {
        clearTimeout(timerRef.current);
        apagarConversa(pendente.id);
      }
    };
  }, [pendente]);

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
                    <li key={conversa.id} className="relative has-[[aria-expanded=true]]:z-50">
                    {editandoId === conversa.id ? (
                       <div className="flex items-center p-4 pl-5 rounded-2xl glass">
                        <input
                          autoFocus
                          value={novoTitulo}
                          onChange={(e) => setNovoTitulo(e.target.value)}
                          onBlur={confirmarEdicao}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") confirmarEdicao();
                            if (e.key === "Escape") setEditandoId(null);
                          }}
                          className="flex-1 min-w-0 bg-transparent text-white text-base sm:text-lg border-b border-[#f1863d] focus:outline-none"
                        />
                      </div>
                    ) : (
                      <>
                        <Link
                            href={`/chat/${conversa.id}`}
                            className="group flex items-start gap-4 p-4 pl-5 pr-14 rounded-2xl overflow-hidden glass hover:bg-[#000000]/20 transition-colors"
                        >
                            <span
                            aria-hidden
                            className={`absolute inset-y-0 left-0 w-1 transition-colors ${
                                conversa.favorita
                                ? "bg-[#f1863d]"
                                : "bg-transparent"
                            }`}
                            />
                            <div className="min-w-0">
                            <p className="text-white text-base sm:text-lg truncate">{conversa.titulo}</p>
                            <p className="text-[#AEB8CF] text-sm mt-1">
                                {formatarData(conversa.criadoEm)} · {conversa.mensagens.length}{" "}
                                {conversa.mensagens.length === 1 ? "pergunta" : "perguntas"}
                            </p>
                            </div>
                        </Link>

                        <div className="absolute right-3 top-1/2 -translate-y-1/2 z-30">
                            <MenuConversa
                              favorita={!!conversa.favorita}
                              onFavoritar={() => { alternarFavorita(conversa.id); setConversas(listarConversas()); }}
                              onRenomear={() => iniciarEdicao(conversa)}
                              onApagar={() => { apagarComDesfazer(conversa); }}
                            />
                        </div>

                        {pendente && (
                            <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-2xl glass overflow-hidden">
                              <div
                                key={pendente.id}
                                className="h-1 w-full bg-[#f1863d] origin-left animate-[encolher_6s_linear_forwards]"
                              />
                              <div className="flex items-center gap-4 px-5 py-3">
                                <span className="text-white text-sm">Conversa apagada</span>
                                <button onClick={desfazer} className="text-[#f1863d] text-sm font-medium hover:underline cursor-pointer">
                                  Desfazer
                                </button>
                              </div>
                            </div>
                          )}
                      </>
                    )}
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