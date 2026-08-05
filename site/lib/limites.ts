/* Os tetos do lado do cliente, num lugar só.
 *
 * São dois perfis, e a diferença entre eles não é comercial: é onde as
 * conversas moram. Sem conta tudo vive no localStorage deste navegador, que é
 * pequeno, é compartilhado com o resto do site e some quando o aluno limpa o
 * histórico: guardar muita coisa ali é prometer o que não dá para cumprir.
 * Com conta as conversas vão para o banco, então o teto pode ser bem maior.
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

export const LIMITES: Record<"anonimo" | "conta", Perfil> = {
  anonimo: { conversas: 5, favoritas: 3, historico: 10 },
  conta: { conversas: 20, favoritas: 5, historico: 30 },
};

export function perfil(logado: boolean): Perfil {
  return logado ? LIMITES.conta : LIMITES.anonimo;
}
