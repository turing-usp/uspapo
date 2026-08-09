import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { credenciaisSupabase, dominioCookie } from './supabase';

export async function criarClienteServidor() {
  const cookieStore = await cookies();
  const [url, chave] = credenciaisSupabase();

  return createServerClient(
    url,
    chave,
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