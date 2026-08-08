import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { dominioCookie } from './supabase';

export async function criarClienteServidor() {
  const cookieStore = await cookies();

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://placeholder.supabase.co';
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'placeholder-anon-key';

  return createServerClient(
    url,
    key,
    {
      cookieOptions: { domain: dominioCookie },
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (lista) => {
          lista.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          );
        },
      },
    }
  );
}