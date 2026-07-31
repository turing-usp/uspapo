// lib/stream.ts

export type EventoChat =
  | { tipo: "modo"; streaming: boolean }
  | { tipo: "provedor"; nome: string; indice: number }
  | { tipo: "pensando"; delta: string }
  | { tipo: "ferramenta"; estado: "inicio"; indice: number; nome: string }
  | {
      tipo: "ferramenta";
      estado: "fim";
      indice: number;
      nome: string;
      args: Record<string, unknown>;
      resultados: number;
    }
  | { tipo: "texto"; delta: string }
  | { tipo: "fontes"; urls: string[] }
  | { tipo: "erro"; mensagem: string }
  | { tipo: "fim" };

// ─────────────────────────────────────────────
// Estado do indicador de atividade
// ─────────────────────────────────────────────
export type StatusStream = {
  /** O modelo está produzindo a resposta final AGORA. */
  escrevendo: boolean;
  /** Ferramentas em execução, por índice da tool call. */
  ferramentas: Record<number, string>;
};

export const STATUS_INICIAL: StatusStream = { escrevendo: false, ferramentas: {} };

/** Atualiza o estado de atividade a partir de um evento do stream. */
export function reduzirStatus(estado: StatusStream, evento: EventoChat): StatusStream {
  switch (evento.tipo) {
    case "pensando":
      return { ...estado, escrevendo: false };

    case "texto":
      return { ...estado, escrevendo: true };

    case "ferramenta": {
      const ferramentas = { ...estado.ferramentas };
      if (evento.estado === "inicio") ferramentas[evento.indice] = evento.nome;
      else delete ferramentas[evento.indice];

      return { escrevendo: false, ferramentas };
    }

    default:
      return estado;
  }
}

/**
 * O bloco de status fica no ar durante todo o stream, EXCETO enquanto o texto da resposta está saindo, aí o próprio texto crescendo já é o feedback.
 */
export function statusVisivel(estado: StatusStream, semTexto: boolean): boolean {
  return semTexto || !estado.escrevendo;
}

/**
 * Envia a pergunta e chama `aoEvento` para cada evento recebido.
 *
 * Se o back-end responder JSON em vez de SSE (deploy antigo, sem suporte a
 * stream), a resposta inteira é convertida em um único evento de texto. A página não precisa saber a diferença.
 */
export async function perguntar(
  pergunta: string,
  aoEvento: (evento: EventoChat) => void
): Promise<void> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pergunta, stream: true }),
  });

  if (!res.ok) throw new Error("Erro na comunicação com o back-end");

  const tipoConteudo = res.headers.get("content-type") ?? "";
  const ehStream = tipoConteudo.includes("text/event-stream") && res.body !== null;

  aoEvento({ tipo: "modo", streaming: ehStream });

  if (!ehStream || !res.body) {
    const dados = await res.json();
    if (dados.resposta) aoEvento({ tipo: "texto", delta: dados.resposta });
    aoEvento({ tipo: "fontes", urls: dados.fontes ?? [] });
    aoEvento({ tipo: "fim" });
    return;
  }

  const leitor = res.body.getReader();
  const decodificador = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await leitor.read();
    if (done) break;

    buffer += decodificador.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    /* Eventos SSE são separados por uma linha em branco. O último pedaço pode estar incompleto, então volta para o buffer. */
    const blocos = buffer.split("\n\n");
    buffer = blocos.pop() ?? "";

    for (const bloco of blocos) {
      for (const linha of bloco.split("\n")) {
        if (!linha.startsWith("data:")) continue;
        try {
          aoEvento(JSON.parse(linha.slice(5).trim()) as EventoChat);
        } catch {
          /* Evento malformado: melhor perder um do que derrubar o stream. */
        }
      }
    }
  }
}
