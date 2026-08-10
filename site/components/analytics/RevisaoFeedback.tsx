'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, MessageSquareQuote, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react';
import ChatResponse from '@/components/chatResponse';
import Fontes from '@/components/Fontes';
import { COR_NEGATIVO, COR_POSITIVO, Vazio, formatUserId } from './primitivos';

export type ItemFeedback = {
  id: string;
  tipo: 'like' | 'dislike';
  motivo: string | null;
  comentario: string | null;
  created_at: string | null;
  conversa_id: string;
  mensagem_ordem: number;
  user_id: string | null;
  titulo_conversa: string | null;
  /* Nulos quando a conversa já foi apagada: o feedback guarda só um ponteiro
     (conversa + ordem do turno) e não há cascade que o leve junto. */
  pergunta: string | null;
  resposta: string | null;
  fontes: string[] | null;
};

export type FeedbackAnalytics = {
  total: number;
  likes: number;
  dislikes: number;
  respostas_avaliaveis: number;
  taxa_satisfacao: number;
  cobertura: number;
  por_motivo: Record<string, number>;
  serie: Array<{ data: string; likes: number; dislikes: number }>;
  itens: ItemFeedback[];
};

type Filtro = 'todos' | 'like' | 'dislike' | 'comentario';

const FILTROS: Array<{ chave: Filtro; rotulo: string }> = [
  { chave: 'todos', rotulo: 'Todos' },
  { chave: 'like', rotulo: 'Úteis' },
  { chave: 'dislike', rotulo: 'Não úteis' },
  { chave: 'comentario', rotulo: 'Com comentário' },
];

function combina(item: ItemFeedback, filtro: Filtro) {
  if (filtro === 'todos') return true;
  if (filtro === 'comentario') return Boolean(item.comentario);
  return item.tipo === filtro;
}

const dataCurta = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) : '—';

const dataLonga = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'sem data';

/**
 * A lista onde a pergunta, a resposta e o feedback ficam no mesmo lugar.
 *
 * É o motivo de a seção existir: as métricas acima dizem *quanto* de feedback
 * negativo houve, e só aqui dá para responder *em quê* — que é o que permite
 * mexer no prompt ou no índice.
 */
export default function RevisaoFeedback({
  feedback,
  carregando,
}: {
  feedback?: FeedbackAnalytics;
  carregando: boolean;
}) {
  const [filtro, setFiltro] = useState<Filtro>('todos');
  /* Um aberto por vez: com a resposta inteira renderizada dentro, dois abertos
     já colocam o segundo fora da tela. */
  const [aberto, setAberto] = useState<string | null>(null);

  const itens = useMemo(() => feedback?.itens ?? [], [feedback]);
  const visiveis = useMemo(() => itens.filter((item) => combina(item, filtro)), [itens, filtro]);

  if (!itens.length) {
    return (
      <div className="h-32">
        <Vazio carregando={carregando} mensagem="Nenhum feedback registrado ainda." />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {FILTROS.map(({ chave, rotulo }) => {
          const selecionado = filtro === chave;
          const quantos = itens.filter((item) => combina(item, chave)).length;
          return (
            <button
              key={chave}
              type="button"
              onClick={() => setFiltro(chave)}
              className={`rounded-full border px-2.5 py-1 font-roboto text-xs transition-colors ${
                selecionado
                  ? 'border-brand bg-brand/10 font-medium text-brand'
                  : 'border-line/20 text-muted-foreground hover:border-line/40 hover:text-foreground'
              }`}
            >
              {rotulo} <span className="font-mono">{quantos}</span>
            </button>
          );
        })}
      </div>

      {visiveis.length === 0 ? (
        <div className="h-24">
          <Vazio carregando={false} mensagem="Nenhum feedback neste filtro." />
        </div>
      ) : (
        <ul className="space-y-2">
          {visiveis.map((item) => {
            const positivo = item.tipo === 'like';
            const Polegar = positivo ? ThumbsUp : ThumbsDown;
            const cor = positivo ? COR_POSITIVO : COR_NEGATIVO;
            const expandido = aberto === item.id;
            const orfao = item.pergunta === null && item.resposta === null;

            return (
              <li key={item.id} className="glass overflow-hidden rounded-xl">
                <button
                  type="button"
                  onClick={() => setAberto(expandido ? null : item.id)}
                  aria-expanded={expandido}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-tint/5"
                >
                  <Polegar aria-hidden className="h-4 w-4 shrink-0" style={{ color: cor }} />
                  <span className="sr-only">{positivo ? 'Resposta útil' : 'Resposta não útil'}</span>

                  <span
                    className={`min-w-0 flex-1 truncate font-roboto text-sm ${
                      orfao ? 'italic text-muted-foreground' : 'text-foreground'
                    }`}
                  >
                    {orfao ? 'Turno removido' : item.pergunta}
                  </span>

                  {item.comentario && (
                    <MessageSquareQuote
                      aria-label="Tem comentário"
                      className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                    />
                  )}
                  {item.motivo && (
                    <span className="hidden shrink-0 rounded-full border border-line/20 px-2 py-0.5 font-roboto text-[10px] text-muted-foreground sm:inline">
                      {item.motivo}
                    </span>
                  )}
                  <span className="shrink-0 font-mono text-xs text-faint-foreground">
                    {dataCurta(item.created_at)}
                  </span>
                  <ChevronDown
                    aria-hidden
                    className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
                      expandido ? 'rotate-180' : ''
                    }`}
                  />
                </button>

                {expandido && (
                  <div className="space-y-4 border-t border-line/10 px-4 py-4">
                    {orfao ? (
                      <p className="flex items-center gap-2 font-roboto text-sm italic text-muted-foreground">
                        <Trash2 aria-hidden className="h-4 w-4 shrink-0" />
                        A conversa foi apagada; a pergunta e a resposta avaliadas não existem mais.
                      </p>
                    ) : (
                      <>
                        <div>
                          <p className="mb-1.5 font-roboto text-[11px] uppercase tracking-wider text-muted-foreground/70">
                            Pergunta
                          </p>
                          <p className="glass glass-panel rounded-xl p-3 font-roboto text-sm text-foreground">
                            {item.pergunta}
                          </p>
                        </div>

                        <div>
                          <p className="mb-1.5 font-roboto text-[11px] uppercase tracking-wider text-muted-foreground/70">
                            Resposta
                          </p>
                          {/* O mesmo renderizador do chat: é a única forma de o
                              admin ver markdown, tabela e fórmula exatamente
                              como o aluno viu antes de reprovar. Com
                              `streaming` falso ele já nasce revelado, sem
                              animação. O texto dele é text-lg, grande demais
                              numa lista; a altura é limitada para uma resposta
                              longa não empurrar os itens de baixo. */}
                          <div className="max-h-96 overflow-y-auto pr-1 [&>div]:text-base [&_p]:!text-base [&_strong]:!text-base">
                            <ChatResponse text={item.resposta ?? ''} />
                          </div>
                          {item.fontes && item.fontes.length > 0 && <Fontes urls={item.fontes} />}
                        </div>
                      </>
                    )}

                    {item.comentario && (
                      <div>
                        <p className="mb-1.5 font-roboto text-[11px] uppercase tracking-wider text-muted-foreground/70">
                          Comentário do aluno
                        </p>
                        <blockquote
                          className="whitespace-pre-wrap border-l-2 pl-3 font-roboto text-sm italic text-foreground"
                          style={{ borderColor: cor }}
                        >
                          {item.comentario}
                        </blockquote>
                      </div>
                    )}

                    {/* Rastro para achar a conversa no banco sem depender da tela. */}
                    <p className="flex flex-wrap gap-x-3 gap-y-1 font-roboto text-[11px] text-faint-foreground">
                      <span>{dataLonga(item.created_at)}</span>
                      <span>{formatUserId(item.user_id ?? '')}</span>
                      {item.motivo && <span>Motivo: {item.motivo}</span>}
                      <span className="font-mono">
                        {item.conversa_id} · turno {item.mensagem_ordem}
                      </span>
                    </p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
