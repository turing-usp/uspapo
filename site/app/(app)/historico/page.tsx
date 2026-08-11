
"use client";
import { useState, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { listarConversas, apagarConversa, alternarFavorita, renomearConversa, gerarTitulo, buscarConversas, type Conversa } from "@/lib/conversas";
import { LIMITES } from "@/lib/limites";
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
  const [conversas, setConversas] = useState<Conversa[]>([]);
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);

  const [editandoId, setEditandoId] = useState<string | null>(null);
  const [novoTitulo, setNovoTitulo] = useState("");

  const iniciarEdicao = (conversa: Conversa) => {
    setEditandoId(conversa.id);
    setNovoTitulo(conversa.titulo);
  };

  const confirmarEdicao = async () => {
  if (editandoId && novoTitulo.trim()) {
    await renomearConversa(editandoId, novoTitulo);
    setConversas(await listarConversas());
  }
  setEditandoId(null);
};

  useEffect(() => {
    (async () => {
      const lista = await listarConversas();
      setConversas(lista);
      setCarregando(false);
    })();
  }, []);

  const [pendente, setPendente] = useState<Conversa | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const [filtradas, setFiltradas] = useState<Conversa[]>([]);

  useEffect(() => {
    /* Espera o usuário parar de digitar: sem isso, cada tecla vira uma
      consulta ao Postgres. */
    const t = setTimeout(async () => {
      const achadas = await buscarConversas(busca);
      setFiltradas(achadas.filter((c) => c.id !== pendente?.id));
    }, 250);
    return () => clearTimeout(t);
  }, [busca, conversas, pendente]);

  const filtradasAgrupadas = useMemo(() => agrupar(filtradas), [filtradas]);

    const apagarComDesfazer = (conversa: Conversa) => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        apagarConversa(pendente!.id);   // fire-and-forget: a UI já removeu
      }

      setPendente(conversa);
      timerRef.current = setTimeout(async () => {
        await apagarConversa(conversa.id);
        setConversas(await listarConversas());
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

  const buscaRef = useRef<HTMLInputElement>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        buscaRef.current?.focus();
      }
    };
    document.addEventListener("keydown", aoTeclar);
    return () => document.removeEventListener("keydown", aoTeclar);
  }, []);

  const mostrarAviso = (texto: string) => {
    setAviso(texto);
    setTimeout(() => setAviso(null), 4000);
  };
  

  const naoFavoritas = conversas.filter((c) => !c.favorita).length;

  return (
    <>
    <div className="app-scroll">
    <div className="app-container-chat flex min-h-full flex-col pt-8 pb-24">
      <div className="flex items-center mb-2">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-7 h-7 text-foreground">
            <circle cx="12" cy="12" r="10" strokeWidth="2" fill="none" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
        </svg>
        <p className="font-geom text-2xl sm:text-3xl ml-3">Histórico de conversas</p>
      </div>
      <p className="text-muted-foreground mb-4">Retome suas perguntas anteriores e continue de onde parou</p>
      <p className="text-faint-foreground text-xs mt-2 mb-5">
        Suas conversas ficam salvas na sua conta e sincronizam entre dispositivos.
      </p>

      {naoFavoritas >= LIMITES.conversas * 0.9 && (
        <div className="flex items-start gap-3 p-3 mb-5 rounded-xl glass">
          <span className="text-brand shrink-0">⚠</span>
          <p className="text-muted-foreground text-sm">
            Você tem {naoFavoritas} de {LIMITES.conversas} conversas salvas. As mais antigas serão
            removidas automaticamente. Favorite as que quiser manter.
          </p>
        </div>
      )}

      <div className="glass glass-field w-full rounded-[1.75rem] mb-2">
        <input
          type="text"
          ref={buscaRef}
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="Buscar nas conversas (Ctrl+K)"
          className="w-full h-14 px-5 rounded-[1.75rem] border-0 bg-transparent text-foreground text-[1rem] caret-brand placeholder:text-muted-foreground focus:outline-none"
        />
      </div>

      {busca.trim() && (
        <p className="text-muted-foreground text-sm mt-3 mb-2">
          {filtradas.length} {filtradas.length === 1 ? "conversa encontrada" : "conversas encontradas"}
        </p>
      )}

      {carregando ? null : filtradas.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-muted-foreground mb-4">
            {busca ? "Nenhuma conversa encontrada." : "Você ainda não tem conversas salvas."}
          </p>
          {!busca && (
            <Link
              href="/"
              className="inline-block px-6 py-2.5 rounded-2xl border border-brand text-brand hover:bg-brand/10 transition-colors"
            >
              Começar uma conversa
            </Link>
          )}
        </div>
      ) : (
        <div>
          {filtradasAgrupadas.map((grupo) => (
            <div key={grupo.rotulo} className="mb-6">
              <p className="text-muted-foreground text-sm font-medium my-3">
                {grupo.rotulo}
                {grupo.rotulo === "Favoritas" && (
                  <span className="text-faint-foreground text-xs ml-2">
                    {grupo.conversas.length}/{LIMITES.favoritas}
                  </span>
                )}
              </p>
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
                          className="flex-1 min-w-0 bg-transparent text-foreground text-base sm:text-lg border-b border-brand focus:outline-none"
                        />
                      </div>
                    ) : (
                      <>
                        <Link
                            href={`/chat/${conversa.id}`}
                            className="group flex items-start gap-4 p-4 pl-5 pr-14 rounded-2xl overflow-hidden glass hover:bg-scrim/20 transition-colors"
                        >
                            <span
                            aria-hidden
                            className={`absolute inset-y-0 left-0 w-1 transition-colors ${
                                conversa.favorita
                                ? "bg-brand"
                                : "bg-transparent"
                            }`}
                            />
                            <div className="min-w-0">
                            <p className="text-foreground text-base sm:text-lg truncate">{conversa.titulo}</p>
                            <p className="text-muted-foreground text-sm mt-1">
                                {formatarData(conversa.criadoEm)} · {conversa.total ?? 0}{" "}
                                {conversa.total === 1 ? "pergunta" : "perguntas"}
                            </p>
                            </div>
                        </Link>

                        <div className="absolute right-3 top-1/2 -translate-y-1/2 z-30">
                            <MenuConversa
                              favorita={!!conversa.favorita}
                              onFavoritar={async () => {
                                const ok = await alternarFavorita(conversa.id);
                                if (!ok) {
                                  mostrarAviso(`Limite de ${LIMITES.favoritas} favoritas atingido. Remova uma para adicionar outra.`);
                                  return;
                                }
                                setConversas(await listarConversas());
                              }}
                              onRenomear={() => iniciarEdicao(conversa)}
                              onApagar={() => apagarComDesfazer(conversa)}
                            />
                        </div>

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
    </div>
    {/* Mesmo dissolvido do chat: a lista some no fundo em vez de ser cortada
        na borda da área de scroll. Sem composer, é só o rabo de 2.5rem. */}
    <div aria-hidden className="page-fade-t" />

    {/* Os avisos moram aqui, e não na lista, por dois motivos. Dentro do
        .map() nascia um por conversa, e todos caíam no mesmo ponto da tela
        somando blur, véu e fio de borda. E dentro do .app-scroll, que é um
        contexto de empilhamento (z-10), o `fixed` ficava preso nele e o
        page-fade-t (z-20) pintava por cima; irmão dele, o z-50 vence. */}
    {pendente && (
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-2xl glass glass-solid overflow-hidden">
        <div
          key={pendente.id}
          className="h-1 w-full bg-brand origin-left animate-[encolher_6s_linear_forwards]"
        />
        <div className="flex items-center gap-4 px-5 py-3">
          <span className="text-foreground text-sm">Conversa apagada</span>
          <button onClick={desfazer} className="text-brand text-sm font-medium hover:underline cursor-pointer">
            Desfazer
          </button>
        </div>
      </div>
    )}

    {aviso && !pendente && (
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-2xl glass glass-solid">
        <span className="text-foreground text-sm">{aviso}</span>
      </div>
    )}
    </>
  );
}
