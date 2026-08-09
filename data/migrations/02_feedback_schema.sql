-- Migration: Tabela de Feedback de Mensagens do USPapo
-- Execute este script no SQL Editor do Supabase para criar/atualizar a tabela mensagem_feedbacks.

CREATE TABLE IF NOT EXISTS public.mensagem_feedbacks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    conversa_id TEXT NOT NULL,
    mensagem_ordem INTEGER NOT NULL,
    user_id TEXT,
    tipo TEXT NOT NULL CHECK (tipo IN ('like', 'dislike')),
    motivo TEXT,
    comentario TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unq_feedback_conversa_ordem_user UNIQUE (conversa_id, mensagem_ordem, user_id)
);

-- Índices otimizados para busca por conversa e métricas de feedback
CREATE INDEX IF NOT EXISTS idx_feedbacks_conversa_id ON public.mensagem_feedbacks(conversa_id);
CREATE INDEX IF NOT EXISTS idx_feedbacks_created_at ON public.mensagem_feedbacks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedbacks_tipo ON public.mensagem_feedbacks(tipo);

-- Habilita RLS (Row Level Security) e libera inserção/atualização/leitura
ALTER TABLE public.mensagem_feedbacks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Permite insercao e update de feedback" 
ON public.mensagem_feedbacks FOR ALL 
USING (true)
WITH CHECK (true);
