/* Os tetos do lado do cliente, num lugar só.
 *
 * Um perfil só: o login é obrigatório (a portaria está em proxy.ts, e o backend
 * confere de novo no /chat), então toda conversa mora no banco. Existiam dois
 * perfis enquanto dava para perguntar sem conta, aí tudo vivia no localStorage
 * deste navegador, que é pequeno, é compartilhado com o resto do site e some
 * quando o aluno limpa o histórico, e prometer 20 conversas ali seria mentira.
 *
 * O rate limit (quantas PERGUNTAS por minuto) é outra coisa e mora no backend,
 * em uspapo/limites.py: ele protege a cota dos provedores de LLM, e o cliente
 * não teria como aplicá-lo de forma confiável.
 */

export type Perfil = {
  /** Conversas não favoritas guardadas; as mais antigas somem depois disso. */
  conversas: number;
  /** Conversas que o aluno pode fixar para não serem apagadas. */
  favoritas: number;
  /** Turnos anteriores enviados ao backend junto com a pergunta. */
  historico: number;
};

export const LIMITES: Perfil = { conversas: 20, favoritas: 5, historico: 30 };
