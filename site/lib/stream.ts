// lib/stream.ts
import type { Mensagem } from "@/lib/conversas";
import { LIMITES } from "./limites";
import { criarCliente } from "./supabase";

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

/* O access token da sessão. Sem ele não há pergunta: o backend exige login no
   /chat e responde 401. Existia aqui um X-Device-Id, id que o próprio navegador
   gerava, que servia de chave do rate limit de quem perguntava sem conta. Saiu
   junto com o modo anônimo, porque um id que qualquer um troca não identifica
   ninguém. */
async function tokenDaSessao(): Promise<string> {
  try {
    const { data } = await criarCliente().auth.getSession();
    return data.session?.access_token ?? "";
  } catch {
    return "";
  }
}

/**
 * Envia a pergunta e chama `aoEvento` para cada evento recebido.
 */
export async function perguntar(
  pergunta: string,
  anteriores: Mensagem[],
  aoEvento: (evento: EventoChat) => void
): Promise<void> {
  const token = await tokenDaSessao();
  /* Falhar aqui em vez de bater no backend para levar 401: a mensagem fica
     honesta ("sua sessão venceu") e a pergunta não vira uma ida perdida. */
  if (!token) {
    throw new Error("Sua sessão expirou. Entre de novo para continuar perguntando.");
  }

  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      pergunta,
      stream: true,
      /* Só os últimos turnos: o backend ainda corta pelo orçamento de token,
         mas mandar a conversa inteira pela rede a cada pergunta é desperdício
         que cresce sem parar numa conversa longa. */
      historico: anteriores
        .slice(-LIMITES.historico)
        .map((m) => ({ pergunta: m.user, resposta: m.bot })),
    }),
  });

  if (!res.ok) {
    /* O 429 do rate limit traz uma explicação pronta para o aluno ler; sem
       isto ela viraria "erro ao conectar com o servidor". */
    const corpo = await res.json().catch(() => null);
    throw new Error(corpo?.erro ?? "Não consegui falar com o USPapo agora. Tente de novo em instantes.");
  }

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
