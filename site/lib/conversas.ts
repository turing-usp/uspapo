// lib/conversas.ts
export type Mensagem = { user: string; bot: string };

export type Conversa = {
  id: string;
  titulo: string;
  criadoEm: number;
  favorita?: boolean;
  mensagens: Mensagem[];
};

const CHAVE = "uspapo:conversas";
export const LIMITE = 20;
export const LIMITE_FAVORITAS = 5;

function ler(): Conversa[] {
  if (typeof window === "undefined") return [];
  try {
    const bruto = localStorage.getItem(CHAVE);
    return bruto ? (JSON.parse(bruto) as Conversa[]) : [];
  } catch {
    return [];
  }
}

function escrever(conversas: Conversa[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(CHAVE, JSON.stringify(conversas));
  } catch {
    // cota do localStorage cheia — ignora silenciosamente
  }
}

export function listarConversas(): Conversa[] {
  return ler().sort((a, b) => b.criadoEm - a.criadoEm);
}

export function obterConversa(id: string): Conversa | null {
  return ler().find((c) => c.id === id) ?? null;
}

export function salvarConversa(conversa: Conversa): void {
  const outras = ler().filter((c) => c.id !== conversa.id);
  const todas = [conversa, ...outras];

  const favoritas = todas.filter((c) => c.favorita);
  const naoFavoritas = todas.filter((c) => !c.favorita);

  escrever([...favoritas, ...naoFavoritas.slice(0, LIMITE)]);
}

export function apagarConversa(id: string): void {
  escrever(ler().filter((c) => c.id !== id));
}

export function gerarTitulo(primeiraPergunta: string): string {
  const limpo = primeiraPergunta.trim();
  return limpo.length > 50 ? limpo.slice(0, 50) + "..." : limpo;
}

export function alternarFavorita(id: string): boolean {
  const conversas = ler();
  const alvo = conversas.find((c) => c.id === id);
  if (!alvo) return false;

  if (!alvo.favorita) {
    const total = conversas.filter((c) => c.favorita).length;
    if (total >= LIMITE_FAVORITAS) return false;
  }

  alvo.favorita = !alvo.favorita;
  escrever(conversas);
  return true;
}

export function contarNaoFavoritas(): number {
  return ler().filter((c) => !c.favorita).length;
}

export function renomearConversa(id: string, novoTitulo: string): void {
  const titulo = novoTitulo.trim();
  if (!titulo) return;
  const conversas = ler();
  const alvo = conversas.find((c) => c.id === id);
  if (!alvo) return;
  alvo.titulo = titulo;
  escrever(conversas);
}