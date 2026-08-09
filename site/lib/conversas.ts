// lib/conversas.ts
import { criarCliente } from "./supabase";
import { LIMITES } from "./limites";

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

/* Tudo aqui pressupõe sessão: o proxy.ts não deixa chegar nesta parte do site
   sem login. Existia um caminho paralelo em localStorage, para quem usava sem
   conta, e ele saiu junto com essa possibilidade. Uma chamada por operação é
   barato: o cliente lê o cookie, não vai à rede. */
async function uid(): Promise<string | null> {
  const { data } = await criarCliente().auth.getUser();
  return data.user?.id ?? null;
}

/* Toda chamada aqui pode falhar por motivo que não é "não achei": tabela que
   não existe (esquema não aplicado no banco), RLS barrando, rede fora. Antes o
   `{ error }` do supabase-js era descartado em todas elas, e o resultado era o
   pior tipo de bug: a gravação falhava, a tela seguia como se tivesse dado
   certo, e o aluno acabava numa conversa vazia sem nenhuma pista do motivo.

   Não levanta de propósito. Quase todas as chamadas vêm de handler de UI sem
   try/catch, e derrubar a tela é pior do que seguir degradado. Quem precisa
   reagir olha o retorno; o console garante que a causa nunca fique invisível. */
function falhou(operacao: string, error: { message: string } | null): boolean {
  if (!error) return false;
  console.error(`[conversas] ${operacao} falhou: ${error.message}`);
  return true;
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
  const supabase = criarCliente();
  const { data: conversa, error } = await supabase
    .from("conversas").select("id, titulo, favorita, criada_em")
    .eq("id", id).maybeSingle<LinhaConversa>();
  if (falhou("obterConversa", error) || !conversa) return null;

  const { data: linhas, error: erroMensagens } = await supabase
    .from("mensagens").select("ordem, pergunta, resposta, fontes")
    .eq("conversa_id", id).order("ordem");
  falhou("obterConversa/mensagens", erroMensagens);

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
  /* Sessão vencida entre abrir a tela e mandar a pergunta: gravar sem user_id
     só levaria um erro do RLS. O proxy.ts manda para o login no próximo passo. */
  if (!usuario) return;

  const supabase = criarCliente();
  const { error } = await supabase.from("conversas").upsert({
    id: conversa.id,
    user_id: usuario,
    titulo: conversa.titulo,
    favorita: conversa.favorita ?? false,
  });
  /* Sem a conversa gravada, gravar as mensagens só produziria erro de chave
     estrangeira em cima do erro que já aconteceu. */
  if (falhou("salvarConversa", error)) return;

  /* Grava turno a turno: insere o que é novo, completa o que estava
     sem resposta. Reescrever tudo a cada stream seria caro. */
  const { data: existentes } = await supabase
    .from("mensagens").select("ordem, resposta")
    .eq("conversa_id", conversa.id).order("ordem");

  const salvos = new Map((existentes ?? []).map((l) => [l.ordem, l.resposta]));

  for (const [i, m] of conversa.mensagens.entries()) {
    const resposta = m.bot === "..." ? null : m.bot;

    if (!salvos.has(i)) {
      const { error: erroInsercao } = await supabase.from("mensagens").insert({
        conversa_id: conversa.id, ordem: i,
        pergunta: m.user, resposta, fontes: m.fontes ?? null,
      });
      falhou(`salvarConversa/insert turno ${i}`, erroInsercao);
    } else if (salvos.get(i) === null && resposta !== null) {
      const { error: erroUpdate } = await supabase
        .from("mensagens").update({ resposta, fontes: m.fontes ?? null })
        .eq("conversa_id", conversa.id).eq("ordem", i);
      falhou(`salvarConversa/update turno ${i}`, erroUpdate);
    }
  }

  await podarConversas(supabase);
}

/* As favoritas nunca entram na conta: é exatamente para isso que elas servem. */
async function podarConversas(supabase: ReturnType<typeof criarCliente>): Promise<void> {
  const { data } = await supabase
    .from("conversas").select("id")
    .eq("favorita", false)
    .order("atualizada_em", { ascending: false });

  const excedentes = (data ?? []).slice(LIMITES.conversas);
  if (!excedentes.length) return;

  /* As mensagens vão junto pelo cascade. */
  await supabase.from("conversas").delete().in("id", excedentes.map((c) => c.id));
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
  /* As mensagens vão junto pelo cascade. */
  await criarCliente().from("conversas").delete().eq("id", id);
}

export async function alternarFavorita(id: string): Promise<boolean> {
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
  const { count } = await criarCliente()
    .from("conversas").select("*", { count: "exact", head: true })
    .eq("favorita", false);
  return count ?? 0;
}

export async function renomearConversa(id: string, novoTitulo: string): Promise<void> {
  const titulo = novoTitulo.trim();
  if (!titulo) return;

  await criarCliente().from("conversas").update({ titulo }).eq("id", id);
}

/* Busca no conteúdo. O ilike roda no Postgres, já que a listagem não traz os
   textos das mensagens. */
export async function buscarConversas(termo: string): Promise<Conversa[]> {
  const t = termo.trim();
  if (!t) return listarConversas();

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