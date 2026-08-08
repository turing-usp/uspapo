import { createBrowserClient } from '@supabase/ssr';

export const dominioCookie =
  process.env.NODE_ENV === 'production' ? '.turingusp.com' : undefined;

export function criarCliente() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://placeholder.supabase.co';
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'placeholder-anon-key';
  return createBrowserClient(
    url,
    key,
    { cookieOptions: { domain: dominioCookie } }
  );
}