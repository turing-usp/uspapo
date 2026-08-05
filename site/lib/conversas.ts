// lib/conversas.ts
import { criarCliente } from "./supabase";

export type Mensagem = { user: string; bot: string; fontes?: string[] };

export type Conversa = {
  id: string;
  titulo: string;
  criadoEm: number;
  favorita?: boolean;
  mensagens: Mensagem[];
  /* Total de turnos. No banco vem por agregação, sem carregar o conteúdo;
     no local é só o tamanho do array. */
  total?: number;
};

const CHAVE = "uspapo:conversas";
export const LIMITE = 20;
export const LIMITE_LOCAL = 5;
export const LIMITE_FAVORITAS = 5;

/* Sem sessão, tudo cai no localStorage. Uma chamada por operação é
   barato: o cliente lê o cookie, não vai à rede. */
async function uid(): Promise<string | null> {
  const { data } = await criarCliente().auth.getUser();
  return data.user?.id ?? null;
}

function ler(): Conversa[] {
  if (typeof window === "undefined") return [];
  try {
    const bruto = localStorage.getItem(CHAVE);
    return bruto ? (JSON.parse(bruto) as Conversa[]) : [];
  } catch { return []; }
}

function escrever(cs: Conversa[]) {
  if (typeof window === "undefined") return;
  try { localStorage.setItem(CHAVE, JSON.stringify(cs)); } catch {}
}

type LinhaConversa = {
  id: string; titulo: string; favorita: boolean; criada_em: string;
};
type LinhaMensagem = {
  ordem: number; pergunta: string; resposta: string | null; fontes: string[] | null;
};

/* resposta nula = o stream não terminou; a página trata como PENDENTE. */
function paraMensagens(linhas: LinhaMensagem[]): Mensagem[] {
  return linhas.map((l) => ({
    user: l.pergunta,
    bot: l.resposta ?? "...",
    ...(l.fontes?.length ? { fontes: l.fontes } : {}),
  }));
}

export async function obterConversa(id: string): Promise<Conversa | null> {
  if (!(await uid())) return ler().find((c) => c.id === id) ?? null;

  const supabase = criarCliente();
  const { data: conversa } = await supabase
    .from("conversas").select("id, titulo, favorita, criada_em")
    .eq("id", id).maybeSingle<LinhaConversa>();
  if (!conversa) return null;

  const { data: linhas } = await supabase
    .from("mensagens").select("ordem, pergunta, resposta, fontes")
    .eq("conversa_id", id).order("ordem");

  return {
    id: conversa.id,
    titulo: conversa.titulo,
    criadoEm: new Date(conversa.criada_em).getTime(),
    favorita: conversa.favorita,
    mensagens: paraMensagens((linhas ?? []) as LinhaMensagem[]),
  };
}

export async function salvarConversa(conversa: Conversa): Promise<void> {
  const usuario = await uid();

  if (!usuario) {
    const outras = ler().filter((c) => c.id !== conversa.id);
    const todas = [conversa, ...outras];
    const favoritas = todas.filter((c) => c.favorita);
    const resto = todas.filter((c) => !c.favorita);
    escrever([...favoritas, ...resto.slice(0, LIMITE_LOCAL)]);
    return;
  }

  const supabase = criarCliente();
  await supabase.from("conversas").upsert({
    id: conversa.id,
    user_id: usuario,
    titulo: conversa.titulo,
    favorita: conversa.favorita ?? false,
  });

  /* Grava turno a turno: insere o que é novo, completa o que estava
     sem resposta. Reescrever tudo a cada stream seria caro. */
  const { data: existentes } = await supabase
    .from("mensagens").select("ordem, resposta")
    .eq("conversa_id", conversa.id).order("ordem");

  const salvos = new Map((existentes ?? []).map((l) => [l.ordem, l.resposta]));

  for (const [i, m] of conversa.mensagens.entries()) {
    const resposta = m.bot === "..." ? null : m.bot;

    if (!salvos.has(i)) {
      await supabase.from("mensagens").insert({
        conversa_id: conversa.id, ordem: i,
        pergunta: m.user, resposta, fontes: m.fontes ?? null,
      });
    } else if (salvos.get(i) === null && resposta !== null) {
      await supabase.from("mensagens").update({ resposta, fontes: m.fontes ?? null })
        .eq("conversa_id", conversa.id).eq("ordem", i);
    }
  }
}

export function gerarTitulo(primeiraPergunta: string): string {
  const limpo = primeiraPergunta.trim();
  return limpo.length > 50 ? limpo.slice(0, 50) + "..." : limpo;
}

export function novoId(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  if (c?.getRandomValues) {
    const b = c.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const hex = [...b].map((n) => n.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

export async function listarConversas(): Promise<Conversa[]> {
  if (!(await uid())) {
    return ler()
      .sort((a, b) => b.criadoEm - a.criadoEm)
      .map((c) => ({ ...c, total: c.mensagens.length }));
  }

  const { data } = await criarCliente()
    .from("conversas")
    .select("id, titulo, favorita, criada_em, mensagens(count)")
    .order("atualizada_em", { ascending: false });

  return (data ?? []).map((c) => ({
    id: c.id,
    titulo: c.titulo,
    criadoEm: new Date(c.criada_em).getTime(),
    favorita: c.favorita,
    mensagens: [],
    total: c.mensagens?.[0]?.count ?? 0,
  }));
}

export async function apagarConversa(id: string): Promise<void> {
  if (!(await uid())) return escrever(ler().filter((c) => c.id !== id));
  /* As mensagens vão junto pelo cascade. */
  await criarCliente().from("conversas").delete().eq("id", id);
}

export async function alternarFavorita(id: string): Promise<boolean> {
  if (!(await uid())) {
    const conversas = ler();
    const alvo = conversas.find((c) => c.id === id);
    if (!alvo) return false;
    if (!alvo.favorita && conversas.filter((c) => c.favorita).length >= LIMITE_FAVORITAS) {
      return false;
    }
    alvo.favorita = !alvo.favorita;
    escrever(conversas);
    return true;
  }

  const supabase = criarCliente();
  const { data: atual } = await supabase
    .from("conversas").select("favorita").eq("id", id).maybeSingle();
  if (!atual) return false;

  /* O trigger limitar_favoritas rejeita o 6º: o erro é a resposta. */
  const { error } = await supabase
    .from("conversas").update({ favorita: !atual.favorita }).eq("id", id);
  return !error;
}

export async function contarNaoFavoritas(): Promise<number> {
  if (!(await uid())) return ler().filter((c) => !c.favorita).length;

  const { count } = await criarCliente()
    .from("conversas").select("*", { count: "exact", head: true })
    .eq("favorita", false);
  return count ?? 0;
}

export async function renomearConversa(id: string, novoTitulo: string): Promise<void> {
  const titulo = novoTitulo.trim();
  if (!titulo) return;

  if (!(await uid())) {
    const conversas = ler();
    const alvo = conversas.find((c) => c.id === id);
    if (!alvo) return;
    alvo.titulo = titulo;
    return escrever(conversas);
  }
  await criarCliente().from("conversas").update({ titulo }).eq("id", id);
}

/* Busca no conteúdo. Local filtra em memória; no banco o ilike roda no
   Postgres, já que a listagem não traz os textos. */
export async function buscarConversas(termo: string): Promise<Conversa[]> {
  const t = termo.trim();
  if (!t) return listarConversas();

  if (!(await uid())) {
    const alvo = t.toLowerCase();
    return (await listarConversas()).filter(
      (c) =>
        c.titulo.toLowerCase().includes(alvo) ||
        c.mensagens.some(
          (m) => m.user.toLowerCase().includes(alvo) || m.bot.toLowerCase().includes(alvo)
        )
    );
  }

  const supabase = criarCliente();
  const { data: achadas } = await supabase
    .from("mensagens")
    .select("conversa_id")
    .or(`pergunta.ilike.%${t}%,resposta.ilike.%${t}%`);

  const ids = new Set((achadas ?? []).map((m) => m.conversa_id));
  return (await listarConversas()).filter(
    (c) => ids.has(c.id) || c.titulo.toLowerCase().includes(t.toLowerCase())
  );
}

export const PENDENTE = "...";