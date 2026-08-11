'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import {
  Users,
  Zap,
  Clock,
  AlertTriangle,
  RefreshCw,
  TrendingUp,
  Server,
  BarChart3,
  Activity,
  ThumbsUp,
  MessageSquareQuote,
  ArrowRight,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
} from 'recharts';
import {
  CORES_SERIE,
  MAX_FATIAS,
  COR_NEGATIVO,
  COR_POSITIVO,
  EIXO,
  CardGrafico,
  LegendaGlass,
  TooltipGlass,
  Vazio,
  formatNumber,
  formatUserId,
  rotuloDia,
} from '@/components/analytics/primitivos';
import RevisaoFeedback, { type FeedbackAnalytics } from '@/components/analytics/RevisaoFeedback';

interface BaldeTokens {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

interface AnalyticsData {
  dau: number;
  mau: number;
  usuarios?: { dau: number; mau: number; razao_dau_mau: number };
  tokens: {
    hoje: BaldeTokens;
    acumulado_30d: BaldeTokens;
    por_provedor: Record<string, BaldeTokens & { chamadas: number }>;
    por_modelo: Record<string, BaldeTokens & { chamadas: number }>;
  };
  desempenho_provedores: Record<
    string,
    {
      total_chamadas: number;
      erros: number;
      latencia_media_ms: number;
      taxa_erro: number;
    }
  >;
  serie_temporal: Array<{
    data: string;
    /** DAU: usuários únicos ativos naquele dia. */
    usuarios_unicos: number;
    /** MAU: janela móvel de 30 dias terminando naquele dia. */
    mau: number;
    conversas_iniciadas: number;
    perguntas: number;
    total_tokens: number;
    prompt_tokens: number;
    completion_tokens: number;
    latencia_media_ms: number;
  }>;
  top_usuarios: Array<{
    user_id: string;
    perguntas: number;
    total_tokens: number;
    ultima_atividade: string;
  }>;
  /* Opcional: um backend ainda sem `obter_feedback_respostas` no ar não manda
     a chave, e a tela precisa degradar para "sem feedback" em vez de quebrar. */
  feedback?: FeedbackAnalytics;
}

const PERCENTUAL = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  maximumFractionDigits: 0,
});

export default function AdminAnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchAnalytics = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch('/api/admin/analytics');
      const json = await res.json();

      if (json.ok === false) {
        throw new Error(json.erro || 'Falha ao carregar dados de analytics.');
      }

      const payload = json.data || json;
      setData(payload);
      setLastUpdated(new Date());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro inesperado ao buscar dados.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  const formatModelName = (modelStr: string) => {
    if (!modelStr || modelStr === 'Nao informado') return 'Não informado';
    const str = modelStr.toLowerCase();
    if (str.includes('gpt-oss-120b') || str.includes('gptoss120')) return 'GPT-OSS 120B';
    if (str.includes('gpt-oss-20b') || str.includes('gptoss20')) return 'GPT-OSS 20B';
    if (str.includes('qwen3.6-27b') || str.includes('qwen27') || str.includes('qwen')) return 'Qwen 3.6 27B';
    if (str.includes('llama-3.3-70b') || str.includes('llama70')) return 'Llama 3.3 70B';
    if (str.includes('llama-3.1-70b')) return 'Llama 3.1 70B';
    if (str.includes('llama-3.1-8b') || str.includes('llama8')) return 'Llama 3.1 8B';
    if (str === 'outros / testes' || str === 'outro') return 'Outros / Testes';
    const parts = modelStr.split('/');
    return parts[parts.length - 1];
  };

  /** Ordem da tabela: a cadeia de fallback, não o volume. */
  const MODEL_PRIORITY: Record<string, number> = {
    'GPT-OSS 120B': 1,
    'Llama 3.3 70B': 2,
    'GPT-OSS 20B': 3,
    'Qwen 3.6 27B': 4,
    'Llama 3.1 8B': 5,
    'Llama 3.1 70B': 6,
  };

  const serie = data?.serie_temporal ?? [];
  const temSerie = serie.length > 0;

  // Agrupa pelo nome já formatado: dois ids crus podem cair no mesmo rótulo, e
  // sem juntar eles virariam duas fatias com a mesma legenda.
  const porRotulo = (registros: Record<string, { chamadas: number }>) => {
    const mapa = new Map<string, number>();
    for (const [nome, info] of Object.entries(registros)) {
      const rotulo = formatModelName(nome);
      mapa.set(rotulo, (mapa.get(rotulo) || 0) + (info.chamadas || 0));
    }
    return Array.from(mapa, ([name, value]) => ({ name, value })).sort(
      (a, b) => b.value - a.value,
    );
  };

  const ordenado =
    data?.tokens?.por_modelo && Object.keys(data.tokens.por_modelo).length > 0
      ? porRotulo(data.tokens.por_modelo)
      : porRotulo(data?.tokens?.por_provedor ?? {});

  // Além do sexto slot não há cor validada: o excedente vira uma fatia só.
  const pieData =
    ordenado.length > MAX_FATIAS
      ? [
          ...ordenado.slice(0, MAX_FATIAS - 1),
          {
            name: 'Outros modelos',
            value: ordenado.slice(MAX_FATIAS - 1).reduce((soma, item) => soma + item.value, 0),
          },
        ]
      : ordenado;

  const tokensHoje = data?.tokens?.hoje;
  const tokens30d = data?.tokens?.acumulado_30d;
  const ultimoDia = temSerie ? serie[serie.length - 1] : null;
  const latenciaHoje = ultimoDia?.latencia_media_ms ?? 0;

  const feedback = data?.feedback;
  const serieFeedback = feedback?.serie ?? [];
  const temFeedback = (feedback?.total ?? 0) > 0;
  // Ordena por volume: quem mais reprovou aparece primeiro, que é a leitura
  // útil aqui, a ordem fixa da paleta vale para identidade de modelo, não
  // para uma lista de motivos que não carrega cor.
  const motivos = Object.entries(feedback?.por_motivo ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <>
    <div className="app-scroll">
      <div className="app-container py-6 space-y-8">
        {/* Cabeçalho */}
        <div className="flex flex-col gap-4 border-b border-line/15 pb-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-geom text-2xl tracking-tight text-foreground sm:text-3xl">
                Painel de Analytics &amp; Telemetria
              </h1>
              <span className="glass inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-roboto text-xs text-brand">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
                Ao Vivo
              </span>
            </div>
            <p className="mt-1 font-roboto text-sm text-muted-foreground">
              Métricas executivas de uso, tokens medidos e desempenho do USPapo.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="hidden font-roboto text-xs text-faint-foreground sm:inline">
                Atualizado às {lastUpdated.toLocaleTimeString('pt-BR')}
              </span>
            )}
            <button
              onClick={fetchAnalytics}
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

        {/* KPIs */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {/* Usuários ativos */}
          <div className="glass rounded-2xl p-5 space-y-2">
            <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
              <span>Usuários Ativos (DAU / MAU)</span>
              <Users className="h-4 w-4 text-brand" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-foreground">
                {loading ? '-' : (data?.usuarios?.dau ?? data?.dau ?? 0)}
              </span>
              {/* "24h" e não "hoje": a métrica é janela móvel, não dia-calendário. */}
              <span className="font-roboto text-xs text-muted-foreground">24h</span>
              <span className="text-faint-foreground">/</span>
              <span className="text-lg font-semibold text-brand">
                {loading ? '-' : (data?.usuarios?.mau ?? data?.mau ?? 0)}
              </span>
              <span className="font-roboto text-xs text-muted-foreground">30d</span>
            </div>
            <p className="font-roboto text-[11px] text-faint-foreground">
              Usuários únicos ativos nas últimas 24h e 30 dias.
            </p>
          </div>

          {/* Tokens: processados e gerados, separados */}
          <div className="glass rounded-2xl p-5 space-y-2">
            <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
              <span>Consumo de Tokens</span>
              <Zap className="h-4 w-4 text-brand" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-foreground">
                {loading ? '-' : formatNumber(tokensHoje?.total_tokens ?? 0)}
              </span>
              <span className="font-roboto text-xs text-muted-foreground">hoje</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-roboto text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="h-2 w-2 rounded-full"
                  style={{ background: 'var(--chart-2)' }}
                />
                Processados{' '}
                <span className="font-mono text-foreground">
                  {loading ? '-' : formatNumber(tokensHoje?.prompt_tokens ?? 0)}
                </span>
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="h-2 w-2 rounded-full"
                  style={{ background: 'var(--chart-1)' }}
                />
                Gerados{' '}
                <span className="font-mono text-foreground">
                  {loading ? '-' : formatNumber(tokensHoje?.completion_tokens ?? 0)}
                </span>
              </span>
            </div>
            <p className="font-roboto text-[11px] text-faint-foreground">
              Acumulado 30d:{' '}
              <span className="font-mono text-muted-foreground">
                {loading ? '-' : formatNumber(tokens30d?.total_tokens ?? 0)}
              </span>{' '}
              ({loading ? '-' : formatNumber(tokens30d?.prompt_tokens ?? 0)} +{' '}
              {loading ? '-' : formatNumber(tokens30d?.completion_tokens ?? 0)})
            </p>
          </div>

          {/* Latência */}
          <div className="glass rounded-2xl p-5 space-y-2">
            <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
              <span>Latência Média de Resposta</span>
              <Clock className="h-4 w-4 text-brand" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-foreground">
                {loading ? '-' : latenciaHoje > 0 ? Math.round(latenciaHoje) : '—'}
              </span>
              {latenciaHoje > 0 && (
                <span className="font-roboto text-xs text-muted-foreground">ms</span>
              )}
            </div>
            <p className="font-roboto text-[11px] text-faint-foreground">
              Tempo médio de processamento dos LLMs.
            </p>
          </div>

          {/* Status */}
          <div className="glass rounded-2xl p-5 space-y-2">
            <div className="flex items-center justify-between font-roboto text-xs font-medium text-muted-foreground">
              <span>Status da API Backend</span>
              <Server className="h-4 w-4 text-brand" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className={`text-xl font-bold ${error ? 'text-danger' : 'text-brand'}`}>
                {loading ? 'Verificando...' : error ? 'Fora do Ar' : 'Operacional'}
              </span>
            </div>
            <p className="font-roboto text-[11px] text-faint-foreground">
              {error
                ? 'A conexão com o servidor falhou.'
                : 'Conexão com o banco de dados e LLMs estável.'}
            </p>
          </div>
        </div>

        {/* Volume de perguntas + modelos */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <CardGrafico
            className="lg:col-span-2"
            titulo="Volume de Perguntas (30 Dias)"
            descricao="Respostas concluídas por dia, medidas na telemetria."
            icone={<TrendingUp className="h-4 w-4 text-brand" />}
          >
            <div className="h-64 w-full pt-4">
              {temSerie ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={serie} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                    <defs>
                      <linearGradient id="fillPerguntas" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--chart-1)" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="var(--chart-1)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="data" tickFormatter={rotuloDia} minTickGap={24} {...EIXO} />
                    <YAxis allowDecimals={false} {...EIXO} />
                    <Tooltip
                      cursor={{ stroke: 'var(--chart-grid)' }}
                      content={<TooltipGlass />}
                    />
                    {/* Série única: o título já a nomeia, dispensa legenda. */}
                    <Area
                      type="monotone"
                      dataKey="perguntas"
                      name="Perguntas"
                      stroke="var(--chart-1)"
                      strokeWidth={2}
                      fill="url(#fillPerguntas)"
                      activeDot={{ r: 4, strokeWidth: 2 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <Vazio carregando={loading} mensagem="Nenhum dado temporal registrado ainda." />
              )}
            </div>
          </CardGrafico>

          <CardGrafico
            titulo="Modelos de LLM (Groq)"
            descricao="Distribuição de chamadas por submodelo de IA."
            icone={<Server className="h-4 w-4 text-brand" />}
          >
            <div className="flex h-52 w-full items-center justify-center">
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={2}
                      dataKey="value"
                      stroke="none"
                    >
                      {pieData.map((entry, index) => (
                        <Cell key={entry.name} fill={CORES_SERIE[index % CORES_SERIE.length]} />
                      ))}
                    </Pie>
                    <Tooltip content={<TooltipGlass />} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <Vazio carregando={loading} mensagem="Sem dados de modelos." />
              )}
            </div>

            {/* Legenda textual: é ela que dá o relevo exigido pelas cores de
                menor contraste no tema claro. */}
            <div className="space-y-1.5 pt-2">
              {pieData.map((item, i) => (
                <div
                  key={item.name}
                  className="flex items-center justify-between font-roboto text-xs"
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: CORES_SERIE[i % CORES_SERIE.length] }}
                    />
                    <span className="font-medium text-foreground">{item.name}</span>
                  </div>
                  <span className="font-mono text-muted-foreground">{item.value} chamadas</span>
                </div>
              ))}
            </div>
          </CardGrafico>
        </div>

        {/* DAU / MAU */}
        <CardGrafico
          titulo="Usuários Ativos — DAU e MAU (30 Dias)"
          descricao="DAU é o dia; MAU é a janela móvel de 30 dias que termina nele. Mesma unidade, mesmo eixo."
          icone={<Users className="h-4 w-4 text-brand" />}
        >
          <div className="h-72 w-full pt-4">
            {temSerie ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={serie} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="fillMau" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--chart-2)" stopOpacity={0.28} />
                      <stop offset="95%" stopColor="var(--chart-2)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="fillDau" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--chart-1)" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="var(--chart-1)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="data" tickFormatter={rotuloDia} minTickGap={24} {...EIXO} />
                  {/* Um eixo só: DAU e MAU são a mesma medida (usuários únicos),
                      e o MAU é sempre o envelope superior do DAU. */}
                  <YAxis allowDecimals={false} {...EIXO} />
                  <Tooltip cursor={{ stroke: 'var(--chart-grid)' }} content={<TooltipGlass />} />
                  <Legend content={<LegendaGlass />} />
                  <Area
                    type="monotone"
                    dataKey="mau"
                    name="MAU (30 dias)"
                    stroke="var(--chart-2)"
                    strokeWidth={2}
                    fill="url(#fillMau)"
                    activeDot={{ r: 4, strokeWidth: 2 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="usuarios_unicos"
                    name="DAU (diário)"
                    stroke="var(--chart-1)"
                    strokeWidth={2}
                    fill="url(#fillDau)"
                    activeDot={{ r: 4, strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <Vazio carregando={loading} mensagem="Nenhum dado de atividade registrado ainda." />
            )}
          </div>
        </CardGrafico>

        {/* Tokens + latência */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <CardGrafico
            titulo="Tokens Processados e Gerados (30 Dias)"
            descricao="Processados são o prompt enviado (eixo da esquerda); gerados, a resposta da Groq (eixo da direita). As escalas são diferentes: compare cada curva com o eixo da cor dela, nunca uma com a outra."
            icone={<BarChart3 className="h-4 w-4 text-brand" />}
          >
            <div className="h-64 w-full pt-4">
              {temSerie ? (
                <ResponsiveContainer width="100%" height="100%">
                  {/* `left: -4`, e não o `-12` dos gráficos irmãos: os rótulos
                      daqui são os mais largos do painel ("12,3 mil" contra o
                      "10" do volume de perguntas) e não sobra folga na largura
                      do eixo para puxá-los mais para fora. À direita a margem é
                      zero porque o segundo eixo ocupa o lugar dela. */}
                  <AreaChart data={serie} margin={{ top: 4, right: 0, left: -4, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="data" tickFormatter={rotuloDia} minTickGap={24} {...EIXO} />
                    {/* Um eixo para cada série, e não um só compartilhado: o
                        prompt carrega sistema + histórico + resultado de
                        ferramenta e cada rodada de ferramenta é uma chamada
                        cobrada, então "Processados" roda de 10x a 50x acima de
                        "Gerados". Num eixo comum a resposta do modelo vira uma
                        linha colada no zero.

                        O `stroke` vem DEPOIS do {...EIXO}, senão o
                        --muted-foreground de lá sobrescreve: é a cor do tick
                        que diz de quem é cada eixo. */}
                    <YAxis
                      yAxisId="processados"
                      tickFormatter={formatNumber}
                      allowDecimals={false}
                      {...EIXO}
                      stroke="var(--chart-2)"
                    />
                    <YAxis
                      yAxisId="gerados"
                      orientation="right"
                      tickFormatter={formatNumber}
                      allowDecimals={false}
                      {...EIXO}
                      stroke="var(--chart-1)"
                    />
                    <Tooltip cursor={{ stroke: 'var(--chart-grid)' }} content={<TooltipGlass />} />
                    <Legend content={<LegendaGlass />} />
                    {/* Sem stackId. Empilhado, a curva de cima era desenhada na
                        altura de prompt+completion enquanto o tooltip mostrava
                        o valor cru do dataKey: "Gerados" aparecia na casa dos
                        40 mil e o tooltip dizia 1.980. Desempilhado, a altura
                        da curva é o próprio número.

                        O stroke tem que ser a cor da série, e não a da
                        superfície: o recharts tira dele a cor do ponto da
                        legenda e do tooltip (getLegendItemColor só cai no fill
                        quando não há stroke), então pintá-lo de --canvas
                        apagava a identidade das duas nos dois lugares. */}
                    <Area
                      type="monotone"
                      yAxisId="processados"
                      dataKey="prompt_tokens"
                      name="Processados"
                      stroke="var(--chart-2)"
                      strokeWidth={2}
                      fill="var(--chart-2)"
                      fillOpacity={0.28}
                      activeDot={{ r: 4, strokeWidth: 2 }}
                    />
                    <Area
                      type="monotone"
                      yAxisId="gerados"
                      dataKey="completion_tokens"
                      name="Gerados"
                      stroke="var(--chart-1)"
                      strokeWidth={2}
                      fill="var(--chart-1)"
                      fillOpacity={0.28}
                      activeDot={{ r: 4, strokeWidth: 2 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <Vazio carregando={loading} mensagem="Nenhum token medido ainda." />
              )}
            </div>
          </CardGrafico>

          <CardGrafico
            titulo="Latência Média Diária"
            descricao="Tempo da cadeia de provedores até a resposta concluída."
            icone={<Clock className="h-4 w-4 text-brand" />}
          >
            <div className="h-64 w-full pt-4">
              {temSerie ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={serie} margin={{ top: 4, right: 8, left: -4, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="data" tickFormatter={rotuloDia} minTickGap={24} {...EIXO} />
                    <YAxis tickFormatter={formatNumber} {...EIXO} />
                    <Tooltip
                      cursor={{ stroke: 'var(--chart-grid)' }}
                      content={<TooltipGlass sufixo=" ms" />}
                    />
                    <Line
                      type="monotone"
                      dataKey="latencia_media_ms"
                      name="Latência"
                      stroke="var(--chart-3)"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4, strokeWidth: 2 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <Vazio carregando={loading} mensagem="Nenhuma latência medida ainda." />
              )}
            </div>
          </CardGrafico>
        </div>

        {/* Tabelas */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <CardGrafico
            titulo="Desempenho dos Modelos & Provedores"
            icone={<Activity className="h-4 w-4 text-brand" />}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left font-roboto text-xs">
                <thead>
                  <tr className="border-b border-line/15 text-muted-foreground">
                    <th className="pb-3 font-medium">Modelo / Provedor</th>
                    <th className="pb-3 font-medium">Chamadas</th>
                    <th className="pb-3 font-medium">Processados</th>
                    <th className="pb-3 font-medium">Gerados</th>
                    <th className="pb-3 font-medium">Latência</th>
                    <th className="pb-3 font-medium">Erro</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/10">
                  {data?.tokens?.por_modelo && Object.keys(data.tokens.por_modelo).length > 0 ? (
                    Object.entries(data.tokens.por_modelo)
                      // A tabela segue a prioridade da cadeia de fallback, e não
                      // o volume: é assim que dá para ver quem está atendendo o
                      // que deveria e quem só entra quando o anterior falha.
                      .sort(
                        ([a], [b]) =>
                          (MODEL_PRIORITY[formatModelName(a)] ?? 99) -
                          (MODEL_PRIORITY[formatModelName(b)] ?? 99),
                      )
                      .map(([prov, info]) => {
                      const modelPerf = data?.desempenho_provedores?.[prov];
                      const avgLat = modelPerf?.latencia_media_ms;
                      const taxaErro = modelPerf ? (modelPerf.taxa_erro * 100).toFixed(1) : '0.0';
                      return (
                        <tr key={prov} className="transition-colors hover:bg-tint/5">
                          <td className="py-3 font-medium text-foreground">
                            {formatModelName(prov)}
                          </td>
                          <td className="py-3 text-muted-foreground">{info.chamadas}</td>
                          <td className="py-3 font-mono text-muted-foreground">
                            {formatNumber(info.prompt_tokens)}
                          </td>
                          <td className="py-3 font-mono text-muted-foreground">
                            {formatNumber(info.completion_tokens)}
                          </td>
                          <td className="py-3 font-mono text-foreground">
                            {avgLat != null && avgLat > 0 ? `${Math.round(avgLat)} ms` : '—'}
                          </td>
                          <td className="py-3">
                            <span
                              className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
                                Number(taxaErro) > 0
                                  ? 'border border-danger/25 bg-danger/10 text-danger'
                                  : 'bg-tint/10 text-muted-foreground'
                              }`}
                            >
                              {taxaErro}%
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={6} className="py-4 text-center text-muted-foreground">
                        Nenhum dado registrado.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardGrafico>

          <CardGrafico
            titulo="Usuários Mais Ativos (Ranking Anônimo)"
            icone={<Users className="h-4 w-4 text-brand" />}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left font-roboto text-xs">
                <thead>
                  <tr className="border-b border-line/15 text-muted-foreground">
                    <th className="pb-3 font-medium">ID Usuário</th>
                    <th className="pb-3 font-medium">Perguntas</th>
                    <th className="pb-3 font-medium">Tokens</th>
                    <th className="pb-3 font-medium">Última Atividade</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/10">
                  {data?.top_usuarios && data.top_usuarios.length > 0 ? (
                    data.top_usuarios.map((usr) => (
                      <tr key={usr.user_id} className="transition-colors hover:bg-tint/5">
                        <td className="py-3 font-mono text-brand">{formatUserId(usr.user_id)}</td>
                        <td className="py-3 font-semibold text-foreground">{usr.perguntas}</td>
                        <td className="py-3 font-mono text-muted-foreground">
                          {formatNumber(usr.total_tokens)}
                        </td>
                        <td className="py-3 text-muted-foreground">
                          {usr.ultima_atividade
                            ? new Date(usr.ultima_atividade).toLocaleDateString('pt-BR')
                            : '-'}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4} className="py-4 text-center text-muted-foreground">
                        Nenhum usuário registrado ainda.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardGrafico>
        </div>

        {/* Qualidade das respostas. Fecha o painel de propósito: as seções
            acima medem quanto o USPapo foi usado e quanto custou; esta é a
            única que diz se o que ele respondeu prestou. */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <CardGrafico
            className="lg:col-span-2"
            titulo="Feedback das Respostas (30 Dias)"
            descricao="Joinhas dados pelos alunos, por dia. Mesma unidade nas duas séries, então um eixo só."
            icone={<ThumbsUp className="h-4 w-4 text-brand" />}
          >
            <div className="h-64 w-full pt-4">
              {temFeedback ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={serieFeedback} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                    <defs>
                      <linearGradient id="fillUtil" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COR_POSITIVO} stopOpacity={0.35} />
                        <stop offset="95%" stopColor={COR_POSITIVO} stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="fillNaoUtil" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COR_NEGATIVO} stopOpacity={0.35} />
                        <stop offset="95%" stopColor={COR_NEGATIVO} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="data" tickFormatter={rotuloDia} minTickGap={24} {...EIXO} />
                    <YAxis allowDecimals={false} {...EIXO} />
                    <Tooltip cursor={{ stroke: 'var(--chart-grid)' }} content={<TooltipGlass />} />
                    <Legend content={<LegendaGlass />} />
                    {/* As cores aqui são polaridade, não identidade: ver a nota
                        em COR_POSITIVO/COR_NEGATIVO nos primitivos. */}
                    <Area
                      type="monotone"
                      dataKey="likes"
                      name="Útil"
                      stroke={COR_POSITIVO}
                      strokeWidth={2}
                      fill="url(#fillUtil)"
                      activeDot={{ r: 4, strokeWidth: 2 }}
                    />
                    <Area
                      type="monotone"
                      dataKey="dislikes"
                      name="Não útil"
                      stroke={COR_NEGATIVO}
                      strokeWidth={2}
                      fill="url(#fillNaoUtil)"
                      activeDot={{ r: 4, strokeWidth: 2 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <Vazio carregando={loading} mensagem="Nenhum feedback registrado ainda." />
              )}
            </div>
          </CardGrafico>

          <CardGrafico
            titulo="Satisfação"
            descricao="Totais desde o início, e não da janela de 30 dias: feedback é raro, e um recorte curto viveria zerado."
            icone={<MessageSquareQuote className="h-4 w-4 text-brand" />}
          >
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-foreground">
                {loading ? '-' : temFeedback ? PERCENTUAL.format(feedback?.taxa_satisfacao ?? 0) : '—'}
              </span>
              <span className="font-roboto text-xs text-muted-foreground">de aprovação</span>
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-roboto text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: COR_POSITIVO }} />
                Útil <span className="font-mono text-foreground">{feedback?.likes ?? 0}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: COR_NEGATIVO }} />
                Não útil <span className="font-mono text-foreground">{feedback?.dislikes ?? 0}</span>
              </span>
            </div>

            <p className="font-roboto text-[11px] text-faint-foreground">
              {/* Cobertura em números absolutos, e não só em porcentagem: "2 de
                  40" avisa que a amostra é pequena, "5%" não. */}
              <span className="font-mono text-muted-foreground">{feedback?.total ?? 0}</span> de{' '}
              <span className="font-mono text-muted-foreground">
                {feedback?.respostas_avaliaveis ?? 0}
              </span>{' '}
              respostas avaliadas ({loading ? '-' : PERCENTUAL.format(feedback?.cobertura ?? 0)}).
            </p>

            <div className="space-y-1.5 border-t border-line/15 pt-3">
              <p className="font-roboto text-[11px] uppercase tracking-wider text-muted-foreground/70">
                Motivos de rejeição
              </p>
              {motivos.length > 0 ? (
                motivos.map(([motivo, quantos]) => (
                  <div key={motivo} className="flex items-center justify-between font-roboto text-xs">
                    <span className="min-w-0 truncate text-foreground">{motivo}</span>
                    <span className="ml-2 shrink-0 font-mono text-muted-foreground">{quantos}</span>
                  </div>
                ))
              ) : (
                <p className="font-roboto text-xs text-muted-foreground">Nenhuma resposta reprovada.</p>
              )}
            </div>

            <div className="pt-3 border-t border-line/15">
              <Link
                href="/admin/feedback"
                className="glass flex items-center justify-between rounded-xl p-3 font-roboto text-xs font-medium text-brand transition-colors hover:bg-brand/10"
              >
                <span className="flex items-center gap-2">
                  <MessageSquareQuote className="h-4 w-4" />
                  Abrir Central de Revisão de Respostas
                </span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </CardGrafico>
        </div>
      </div>
    </div>

    {/* Mesmo dissolvido do histórico: os cards somem no fundo em vez de serem
        cortados na borda da área de scroll. Sem composer, é só o rabo de
        2.5rem. Irmão do .app-scroll, e não filho: dentro dele o absolute
        ficaria preso no contexto de empilhamento z-10. */}
    <div aria-hidden className="page-fade-t" />
    </>
  );
}
