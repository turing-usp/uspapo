'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  MessageSquareQuote,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import RevisaoFeedback, { type FeedbackAnalytics } from '@/components/analytics/RevisaoFeedback';
import { CardGrafico } from '@/components/analytics/primitivos';
import { tokenDaSessao } from '@/lib/supabase';

const PERCENTUAL = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  maximumFractionDigits: 1,
});

export default function AdminFeedbackPage() {
  const [data, setData] = useState<{ feedback?: FeedbackAnalytics } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchFeedbackData = async () => {
    setLoading(true);
    setError(null);
    try {
      // A rota parou de ler cookies (export estático): autentica por Bearer.
      // Sem sessão o pedido vai como antes e o 401 mantém o fluxo de
      // "sessão expirada" de hoje.
      const token = await tokenDaSessao();
      const res = await fetch('/api/admin/analytics', {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) {
        if (res.status === 403) {
          throw new Error('Acesso negado: apenas administradores podem visualizar os feedbacks.');
        }
        throw new Error('Erro ao carregar dados de feedback do servidor.');
      }
      const json = await res.json();
      if (!json.ok) {
        throw new Error(json.erro || 'Falha ao buscar feedbacks.');
      }
      setData(json.data);
      setLastUpdated(new Date());
    } catch (err: any) {
      setError(err.message || 'Erro inesperado');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFeedbackData();
  }, []);

  const feedback = data?.feedback;
  const temFeedback = !!(feedback && (feedback.likes > 0 || feedback.dislikes > 0));
  const motivos = Object.entries(feedback?.por_motivo ?? {}).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <>
      <div className="app-scroll">
        <div className="app-container py-6 space-y-8">
          {/* Cabeçalho */}
          <div className="flex flex-col gap-4 border-b border-line/15 pb-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <Link
                  href="/admin/analytics"
                  className="glass flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-scrim/20 hover:text-foreground"
                  title="Voltar para Analytics"
                >
                  <ArrowLeft className="h-4 w-4" />
                </Link>
                <h1 className="font-geom text-2xl tracking-tight text-foreground sm:text-3xl">
                  Revisão de Feedbacks
                </h1>
                <span className="glass inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-roboto text-xs text-brand">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
                  Ao Vivo
                </span>
              </div>
              <p className="mt-1 font-roboto text-sm text-muted-foreground">
                Central dedicada para revisão detalhada das avaliações dos usuários.
              </p>
            </div>

            <div className="flex items-center gap-3">
              {lastUpdated && (
                <span className="hidden font-roboto text-xs text-faint-foreground sm:inline">
                  Atualizado às {lastUpdated.toLocaleTimeString('pt-BR')}
                </span>
              )}
              <button
                onClick={fetchFeedbackData}
                disabled={loading}
                className="glass flex items-center gap-2 rounded-lg px-3 py-2 font-roboto text-xs text-foreground transition-colors hover:bg-scrim/20 disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
                Atualizar
              </button>
            </div>
          </div>

          {error && (
            <div className="glass flex items-center gap-3 rounded-xl p-4 text-danger">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <div className="font-roboto text-sm">{error}</div>
            </div>
          )}

          {/* Cards Resumo de Satisfação */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {/* Taxa de Aprovação */}
            <div className="glass rounded-2xl p-5 space-y-2">
              <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
                <span>Taxa Geral de Aprovação</span>
                <CheckCircle2 className="h-4 w-4 text-brand" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-foreground">
                  {loading ? '-' : temFeedback ? PERCENTUAL.format(feedback?.taxa_satisfacao ?? 0) : '—'}
                </span>
                <span className="font-roboto text-xs text-muted-foreground">de satisfação</span>
              </div>
              <p className="font-roboto text-[11px] text-faint-foreground">
                <span className="font-mono text-muted-foreground">{feedback?.total ?? 0}</span> avaliações acumuladas.
              </p>
            </div>

            {/* Positivos vs Negativos */}
            <div className="glass rounded-2xl p-5 space-y-2">
              <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
                <span>Avaliações Úteis / Não Úteis</span>
                <div className="flex items-center gap-1 text-muted-foreground">
                  <ThumbsUp className="h-3.5 w-3.5 text-brand" />
                  <ThumbsDown className="h-3.5 w-3.5 text-danger" />
                </div>
              </div>
              <div className="flex items-baseline gap-4 pt-1">
                <div className="flex items-center gap-1.5 font-roboto text-sm font-semibold text-brand">
                  <ThumbsUp className="h-4 w-4" />
                  <span className="text-2xl font-extrabold text-foreground">{loading ? '-' : (feedback?.likes ?? 0)}</span>
                </div>
                <div className="flex items-center gap-1.5 font-roboto text-sm font-semibold text-danger">
                  <ThumbsDown className="h-4 w-4" />
                  <span className="text-2xl font-extrabold text-foreground">{loading ? '-' : (feedback?.dislikes ?? 0)}</span>
                </div>
              </div>
              <p className="font-roboto text-[11px] text-faint-foreground">
                Cobertura de {loading ? '-' : PERCENTUAL.format(feedback?.cobertura ?? 0)} das respostas enviadas.
              </p>
            </div>

            {/* Motivos de Rejeição */}
            <div className="glass rounded-2xl p-5 space-y-2">
              <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
                <span>Principais Motivos de Rejeição</span>
                <MessageSquareQuote className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="space-y-1 pt-1">
                {motivos.length > 0 ? (
                  motivos.slice(0, 3).map(([motivo, quantos]) => (
                    <div key={motivo} className="flex items-center justify-between font-roboto text-xs">
                      <span className="min-w-0 truncate text-foreground">{motivo}</span>
                      <span className="ml-2 shrink-0 font-mono text-muted-foreground">{quantos}</span>
                    </div>
                  ))
                ) : (
                  <p className="font-roboto text-xs text-muted-foreground">Nenhuma rejeição registrada.</p>
                )}
              </div>
            </div>
          </div>

          {/* Tabela de Revisão Completa */}
          <CardGrafico
            titulo="Central de Revisão de Respostas"
            descricao="Lista completa dos feedbacks com a pergunta feita pelo aluno e a resposta gerada."
            icone={<MessageSquareQuote className="h-4 w-4 text-brand" />}
          >
            <RevisaoFeedback feedback={feedback} carregando={loading} />
          </CardGrafico>
        </div>
      </div>
      <div aria-hidden className="page-fade-t" />
    </>
  );
}
