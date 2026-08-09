'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Users,
  Zap,
  Clock,
  AlertTriangle,
  RefreshCw,
  TrendingUp,
  Server,
  ShieldCheck,
  BarChart3,
  Calendar,
  Activity
} from 'lucide-react';
import {
  ResponsiveContainer,
  ComposedChart,
  AreaChart,
  Area,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
} from 'recharts';

interface AnalyticsData {
  dau: number;
  mau: number;
  tokens: {
    hoje: {
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
    };
    acumulado_30d: {
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
    };
    por_provedor: Record<string, { chamadas: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }>;
    por_modelo: Record<string, { chamadas: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }>;
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
    perguntas: number;
    total_tokens: number;
    prompt_tokens: number;
    completion_tokens: number;
    usuarios_unicos: number;
    latencia_media_ms: number;
  }>;
  top_usuarios: Array<{
    user_id: string;
    perguntas: number;
    total_tokens: number;
    ultima_atividade: string;
  }>;
}

const COLORS_PROVEDORES = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ec4899', '#6366f1'];

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
    } catch (err: any) {
      setError(err?.message || 'Erro inesperado ao buscar dados.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  const formatNumber = (num: number = 0) => {
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(1) + 'k';
    return num.toLocaleString();
  };

  const formatUserId = (id: string) => {
    if (!id || id === 'anonymo' || id === 'anonimo') return 'Usuário Anônimo';
    if (id.length > 12) return `${id.substring(0, 6)}...${id.substring(id.length - 4)}`;
    return id;
  };

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

  const MODEL_PRIORITY: Record<string, number> = {
    'GPT-OSS 120B': 1,
    'Llama 3.3 70B': 2,
    'GPT-OSS 20B': 3,
    'Qwen 3.6 27B': 4,
    'Llama 3.1 8B': 5,
    'Llama 3.1 70B': 6,
  };

  const pieData = data?.tokens?.por_modelo && Object.keys(data.tokens.por_modelo).length > 0
    ? (() => {
        const mapa = new Map<string, number>();
        for (const [nome, info] of Object.entries(data.tokens.por_modelo)) {
          const formatado = formatModelName(nome);
          mapa.set(formatado, (mapa.get(formatado) || 0) + (info.chamadas || 0));
        }
        return Array.from(mapa.entries())
          .map(([name, value]) => ({ name, value }))
          .sort((a, b) => b.value - a.value);
      })()
    : (data?.tokens?.por_provedor
      ? (() => {
          const mapa = new Map<string, number>();
          for (const [nome, info] of Object.entries(data.tokens.por_provedor)) {
            const formatado = formatModelName(nome);
            mapa.set(formatado, (mapa.get(formatado) || 0) + (info.chamadas || 0));
          }
          return Array.from(mapa.entries())
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value);
        })()
      : []);

  return (
    <div className="app-scroll">
      <div className="app-container py-6 space-y-8">
        {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-stone-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white">
              Painel de Analytics & Telemetria
            </h1>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Ao Vivo
            </span>
          </div>
          <p className="text-sm text-stone-400 mt-1">
            Métricas executivas de uso, tokens consumidos e desempenho do USPapo.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-stone-400 hidden sm:inline">
              Atualizado às {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchAnalytics}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-stone-900 hover:bg-stone-800 border border-stone-700 text-stone-200 rounded-lg transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Atualizar
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/50 text-rose-300 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
          <div className="text-sm">{error}</div>
        </div>
      )}

      {/* Grid de KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Usuários Ativos */}
        <div className="p-5 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-2">
          <div className="flex items-center justify-between text-stone-400 text-xs font-medium">
            <span>Usuários Ativos (DAU / MAU)</span>
            <Users className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-white">
              {loading ? '-' : ((data as any)?.usuarios?.dau ?? data?.dau ?? 0)}
            </span>
            <span className="text-xs text-stone-400">hoje</span>
            <span className="text-stone-600">/</span>
            <span className="text-lg font-semibold text-emerald-400">
              {loading ? '-' : ((data as any)?.usuarios?.mau ?? data?.mau ?? 0)}
            </span>
            <span className="text-xs text-stone-400">30d</span>
          </div>
          <p className="text-[11px] text-stone-400">
            Usuários únicos ativos nas últimas 24h e 30 dias.
          </p>
        </div>

        {/* Tokens Consumidos */}
        <div className="p-5 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-2">
          <div className="flex items-center justify-between text-stone-400 text-xs font-medium">
            <span>Consumo de Tokens</span>
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-white">
              {loading ? '-' : formatNumber(data?.tokens?.hoje?.total_tokens ?? (data?.tokens as any)?.total_tokens ?? 0)}
            </span>
            <span className="text-xs text-stone-400">hoje</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-stone-400">
            <span>Acumulado 30d:</span>
            <span className="font-semibold text-amber-400">
              {loading ? '-' : formatNumber(data?.tokens?.acumulado_30d?.total_tokens ?? (data?.tokens as any)?.total_tokens ?? 0)}
            </span>
          </div>
        </div>

        {/* Latência Média */}
        <div className="p-5 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-2">
          <div className="flex items-center justify-between text-stone-400 text-xs font-medium">
            <span>Latência Média de Resposta</span>
            <Clock className="w-4 h-4 text-cyan-400" />
          </div>
          {(() => {
            const hojeData = data?.serie_temporal && data.serie_temporal.length > 0
              ? data.serie_temporal[data.serie_temporal.length - 1]
              : null;
            const avgLat = hojeData?.latencia_media_ms || 0;
            const temMedicao = avgLat > 0;
            return (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-extrabold text-white">
                    {loading ? '-' : (temMedicao ? Math.round(avgLat) : '—')}
                  </span>
                  {temMedicao && <span className="text-xs text-stone-400">ms</span>}
                </div>
                <p className="text-[11px] text-stone-400">
                  Tempo médio de processamento dos LLMs.
                </p>
              </>
            );
          })()}
        </div>

        {/* Status da API */}
        <div className="p-5 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-2">
          <div className="flex items-center justify-between text-stone-400 text-xs font-medium">
            <span>Status da API Backend</span>
            <Server className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-xl font-bold ${error ? 'text-rose-400' : 'text-emerald-400'}`}>
              {loading ? 'Verificando...' : (error ? 'Fora do Ar' : 'Operacional')}
            </span>
          </div>
          <p className="text-[11px] text-stone-400">
            {error ? 'A conexão com o servidor falhou.' : 'Conexão com o banco de dados e LLMs estável.'}
          </p>
        </div>
      </div>

      {/* Gráficos Principais */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Gráfico Temporal (Linhas / Área) */}
        <div className="lg:col-span-2 p-6 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                Atividade e Volume de Perguntas (30 Dias)
              </h2>
              <p className="text-xs text-stone-400">
                Evolução diária das mensagens enviadas pelos usuários.
              </p>
            </div>
          </div>

          <div className="h-64 w-full pt-4">
            {data?.serie_temporal && data.serie_temporal.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.serie_temporal}>
                  <defs>
                    <linearGradient id="colorPerguntas" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="data" stroke="#71717a" fontSize={11} />
                  <YAxis yAxisId="left" stroke="#71717a" fontSize={11} allowDecimals={false} />
                  <YAxis yAxisId="right" orientation="right" stroke="#06b6d4" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#18181b',
                      borderColor: '#27272a',
                      borderRadius: '0.75rem',
                      color: '#fff',
                      fontSize: '12px',
                    }}
                  />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="perguntas"
                    name="Perguntas"
                    stroke="#10b981"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorPerguntas)"
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="latencia_media_ms"
                    name="Latência (ms)"
                    stroke="#06b6d4"
                    strokeWidth={2}
                    dot={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-stone-400 text-xs">
                {loading ? 'Carregando gráfico...' : 'Nenhum dado temporal registrado ainda.'}
              </div>
            )}
          </div>
        </div>

        {/* Gráfico Rosca - Modelos */}
        <div className="p-6 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-4">
          <div>
            <h2 className="text-base font-semibold text-white flex items-center gap-2">
              <Server className="w-4 h-4 text-blue-400" />
              Modelos de LLM (Groq)
            </h2>
            <p className="text-xs text-stone-400">
              Distribuição de chamadas por submodelo de IA.
            </p>
          </div>

          <div className="h-52 w-full flex items-center justify-center">
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={80}
                    paddingAngle={4}
                    dataKey="value"
                  >
                    {pieData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={COLORS_PROVEDORES[index % COLORS_PROVEDORES.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#18181b',
                      borderColor: '#27272a',
                      borderRadius: '0.75rem',
                      color: '#fff',
                      fontSize: '12px',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-stone-400 text-xs">
                {loading ? 'Carregando...' : 'Sem dados de modelos.'}
              </div>
            )}
          </div>

          {/* Legenda do Pie */}
          <div className="space-y-1.5 pt-2">
            {pieData.map((item, i) => (
              <div key={`${item.name}-${i}`} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: COLORS_PROVEDORES[i % COLORS_PROVEDORES.length] }}
                  />
                  <span className="text-stone-300 font-medium">{item.name}</span>
                </div>
                <span className="text-stone-400 font-mono">{item.value} chamadas</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Tabelas de Detalhamento */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Desempenho dos Provedores */}
        <div className="p-6 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-4">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-emerald-400" />
            Desempenho dos Modelos & Provedores
          </h2>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-stone-800 text-stone-400">
                  <th className="pb-3 font-medium">Modelo / Provedor</th>
                  <th className="pb-3 font-medium">Chamadas</th>
                  <th className="pb-3 font-medium">Latência Média</th>
                  <th className="pb-3 font-medium">Taxa de Erro</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-800/60">
                {data?.tokens?.por_modelo && Object.keys(data.tokens.por_modelo).length > 0 ? (
                  Object.entries(data.tokens.por_modelo)
                    .sort(([provA], [provB]) => {
                      const pA = MODEL_PRIORITY[formatModelName(provA)] ?? 99;
                      const pB = MODEL_PRIORITY[formatModelName(provB)] ?? 99;
                      return pA - pB;
                    })
                    .map(([prov, info]) => {
                    const modelPerf = data?.desempenho_provedores?.[prov];
                    const avgLat = modelPerf?.latencia_media_ms;
                    const taxaErro = modelPerf ? (modelPerf.taxa_erro * 100).toFixed(1) : '0.0';
                    return (
                      <tr key={prov} className="hover:bg-stone-800/30 transition-colors">
                        <td className="py-3 font-medium text-stone-200">{formatModelName(prov)}</td>
                        <td className="py-3 text-stone-400">{info.chamadas}</td>
                        <td className="py-3 text-stone-300 font-mono">
                          {avgLat != null && avgLat > 0 ? `${Math.round(avgLat)} ms` : '—'}
                        </td>
                        <td className="py-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            Number(taxaErro) > 0
                              ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                              : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          }`}>
                            {taxaErro}%
                          </span>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-stone-400">
                      Nenhum dado registrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Usuários Mais Ativos (Anônimo) */}
        <div className="p-6 rounded-2xl bg-stone-900/60 border border-stone-800/80 backdrop-blur-sm space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-white flex items-center gap-2">
              <Users className="w-4 h-4 text-purple-400" />
              Usuários Mais Ativos (Ranking Anônimo)
            </h2>
            <span className="text-[10px] text-stone-400 bg-stone-800 px-2 py-0.5 rounded border border-stone-700">
              Privacidade Garantida
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-stone-800 text-stone-400">
                  <th className="pb-3 font-medium">ID Usuário</th>
                  <th className="pb-3 font-medium">Perguntas</th>
                  <th className="pb-3 font-medium">Tokens</th>
                  <th className="pb-3 font-medium">Última Atividade</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-800/60">
                {data?.top_usuarios && data.top_usuarios.length > 0 ? (
                  data.top_usuarios.map((usr, i) => (
                    <tr key={i} className="hover:bg-stone-800/30 transition-colors">
                      <td className="py-3 font-mono text-purple-300">
                        {formatUserId(usr.user_id)}
                      </td>
                      <td className="py-3 text-stone-200 font-semibold">{usr.perguntas}</td>
                      <td className="py-3 text-stone-400 font-mono">
                        {formatNumber(usr.total_tokens)}
                      </td>
                      <td className="py-3 text-stone-400">
                        {usr.ultima_atividade
                          ? new Date(usr.ultima_atividade).toLocaleDateString()
                          : '-'}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-stone-400">
                      Nenhum usuário registrado ainda.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
);
}
