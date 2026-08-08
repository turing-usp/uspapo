-- Migration: Tabela de Telemetria e Analytics do USPapo
-- Execute este script no SQL Editor do Supabase para criar/atualizar a tabela analytics_logs.

CREATE TABLE IF NOT EXISTS public.analytics_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    evento TEXT NOT NULL,
    session_id TEXT,
    user_id TEXT,
    provedor TEXT,
    modelo TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latencia_ms INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Índices otimizados para rápida consulta de DAU, MAU e consumo de tokens
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON public.analytics_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_user_id ON public.analytics_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_evento ON public.analytics_logs(evento);
CREATE INDEX IF NOT EXISTS idx_analytics_provedor ON public.analytics_logs(provedor);

-- Habilita RLS (Row Level Security) e libera inserção segura/leitura para a Service Key
ALTER TABLE public.analytics_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Permite insercao via service key e anon" 
ON public.analytics_logs FOR INSERT 
WITH CHECK (true);

CREATE POLICY "Permite leitura via service key" 
ON public.analytics_logs FOR SELECT 
USING (true);
