// lib/conversas.ts
export type Mensagem = { user: string; bot: string };

export type Conversa = {
  id: string;
  titulo: string;
  criadoEm: number;
  mensagens: Mensagem[];
};

const CHAVE = "uspapo:conversas";
const LIMITE = 20;

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
  const conversas = ler().filter((c) => c.id !== conversa.id);
  conversas.unshift(conversa);
  escrever(conversas.slice(0, LIMITE));
}

export function apagarConversa(id: string): void {
  escrever(ler().filter((c) => c.id !== id));
}

export function gerarTitulo(primeiraPergunta: string): string {
  const limpo = primeiraPergunta.trim();
  return limpo.length > 50 ? limpo.slice(0, 50) + "..." : limpo;
}