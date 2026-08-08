import { createBrowserClient } from '@supabase/ssr';

export const dominioCookie =
  process.env.NODE_ENV === 'production' ? '.turingusp.com' : undefined;

/* A chave pública do projeto. O Supabase trocou o formato: a `anon key` (um JWT)
   virou a publishable key, `sb_publishable_…`, que não é JWT nenhum. O valor
   entra no mesmo lugar, então o fallback existe só para o deploy não cair no
   intervalo entre subir este código e trocar a variável no painel da Vercel.

   Pública mesmo: vai embutida no bundle e qualquer um lê. Quem protege as
   tabelas é o RLS. */
export const CHAVE_SUPABASE =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export function criarCliente() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    CHAVE_SUPABASE!,
    { cookieOptions: { domain: dominioCookie } }
  );
}
