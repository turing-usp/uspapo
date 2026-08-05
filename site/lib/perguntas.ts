// lib/perguntas.ts
//
// As perguntas frequentes da tela inicial. Para acrescentar uma, basta uma
// entrada nova aqui.
//
// São dois campos porque o card e o modelo querem coisas diferentes: o card
// precisa de um texto curto, que caiba na pílula e se leia de relance; o modelo
// responde muito melhor a uma pergunta inteira, com o contexto que o aluno
// daria. O prompt é o que vai para o backend e é o que aparece no balão do
// chat: o trecho não sai da home.
export type PerguntaFrequente = { trecho: string; prompt: string };

/* Quantas aparecem por visita. A lista pode crescer à vontade: o que sobra
   entra no sorteio das próximas visitas em vez de lotar a tela. */
export const QUANTAS_EXIBIR = 3;

export const PERGUNTAS_FREQUENTES: PerguntaFrequente[] = [
  {
    trecho: "Cardápio de hoje?",
    prompt: "Qual é o cardápio de hoje nos bandejões do Butantã, no almoço e no jantar?",
  },
  {
    trecho: "Tem choque de horário?",
    prompt:
      "Quais são as turmas de MAC0110 e MAT2454 neste semestre, e existe choque de horário entre elas?",
  },
  {
    trecho: "O que se estuda em Engenharia de Computação?",
    prompt:
      "Quais são as disciplinas obrigatórias do primeiro semestre de Engenharia de Computação na Poli?",
  },
  {
    trecho: "Como funciona uma disciplina?",
    prompt:
      "Qual é a ementa de MAC2166, quantos créditos ela vale e quais são os requisitos para cursá-la?",
  },
  {
    trecho: "O que é o Jupiterweb?",
    prompt: "O que é o JupiterWeb e para que um aluno da USP usa esse sistema?",
  },
  {
    trecho: "Quanto dura o curso de Direito?",
    prompt:
      "Quantos semestres dura o curso de Direito na USP e quais disciplinas se cursa em cada um?",
  },
];

/** Sorteia `n` perguntas sem repetir (Fisher-Yates parcial, sobre uma cópia). */
export function sortear(lista: PerguntaFrequente[], n: number): PerguntaFrequente[] {
  const copia = [...lista];
  const total = Math.min(n, copia.length);

  for (let i = 0; i < total; i++) {
    const j = i + Math.floor(Math.random() * (copia.length - i));
    [copia[i], copia[j]] = [copia[j], copia[i]];
  }

  return copia.slice(0, total);
}
