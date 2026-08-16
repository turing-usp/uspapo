// lib/pendente.ts

/* A primeira pergunta, entregue da home para o chat sem passar pelo banco.
 *
 * A home antes fazia `await salvarConversa(...)` e só então `router.push`. São
 * seis idas seriais ao Supabase (getUser, upsert, select, insert, e a poda das
 * conversas velhas, que é faxina e não tem nada a ver com mostrar a tela) antes
 * de a navegação sequer começar, numa rota dinâmica que ninguém prefetchou. A
 * tela ficava parada e viva o tempo todo, então dava para apertar Enter de novo
 * e criar outra conversa.
 *
 * Agora a home só guarda a pergunta aqui e navega. O chat lê no primeiro
 * render, já desenha a bolha e já dispara o stream; a gravação acontece sozinha,
 * em segundo plano, pelo efeito que o chat já tinha.
 *
 * O par é um Map de módulo, que é a mesma instância dos dois lados porque
 * router.push não recarrega o JS, mais um espelho no sessionStorage para a
 * pergunta sobreviver a um F5 dado antes de ela ter chegado no banco. */

const CHAVE = "uspapo:pendente:";

/* O Map só existe no navegador. No servidor o módulo é UM, compartilhado entre
   todas as requisições, e guardar pergunta ali vazaria a de um aluno para a
   tela de outro. */
const emMemoria = new Map<string, string>();

const noNavegador = () => typeof window !== "undefined";

export function guardarPendente(id: string, texto: string): void {
  if (!noNavegador()) return;
  emMemoria.set(id, texto);
  try {
    sessionStorage.setItem(CHAVE + id, texto);
  } catch {
    /* Aba anônima com storage bloqueado, cota estourada. O Map já basta para o
       caminho normal; o espelho só cobre o recarregamento. */
  }
}

/* Lê SEM apagar, e isso não é detalhe: quem chama é o inicializador do useState
   do chat, e o StrictMode (ligado por padrão no Next 16) invoca inicializador
   duas vezes em desenvolvimento. Se a leitura consumisse, a segunda invocação
   voltaria vazia e a pergunta sumiria da tela. Quem apaga é o descartarPendente,
   chamado do efeito, que já é protegido por ref. */
export function lerPendente(id: string): string | null {
  if (!noNavegador()) return null;
  const daMemoria = emMemoria.get(id);
  if (daMemoria !== undefined) return daMemoria;
  try {
    return sessionStorage.getItem(CHAVE + id);
  } catch {
    return null;
  }
}

export function descartarPendente(id: string): void {
  if (!noNavegador()) return;
  emMemoria.delete(id);
  try {
    sessionStorage.removeItem(CHAVE + id);
  } catch {
    /* Não conseguir limpar não quebra nada: quem já leu já tem a pergunta na
       tela, e a chave morre junto com a aba. */
  }
}
