import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { CHAVE_SUPABASE, dominioCookie } from './supabase';

export async function criarClienteServidor() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    CHAVE_SUPABASE!,
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