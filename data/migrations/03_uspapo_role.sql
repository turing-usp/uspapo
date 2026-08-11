-- Migration: Coluna uspapo_role na tabela Perfis
-- Adiciona a coluna de permissao exclusiva do USPapo na tabela Perfis.
-- Valores validos: 'admin', 'early_access', ou NULL (sem acesso ao USPapo).
-- A coluna tipo_usuario (cargos do Turing) NAO e alterada.

ALTER TABLE public."Perfis"
ADD COLUMN IF NOT EXISTS uspapo_role TEXT DEFAULT NULL;

-- Indice para consulta rapida por role
CREATE INDEX IF NOT EXISTS idx_perfis_uspapo_role
ON public."Perfis"(uspapo_role)
WHERE uspapo_role IS NOT NULL;

COMMENT ON COLUMN public."Perfis".uspapo_role IS
  'Permissao exclusiva do USPapo: admin, early_access ou NULL (sem acesso).';
