'use client';

import { useEffect, useState } from 'react';
import { criarCliente } from './supabase';
import type { User } from '@supabase/supabase-js';

export function useSessao() {
  const [usuario, setUsuario] = useState<User | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    const supabase = criarCliente();

    supabase.auth.getUser().then(({ data }) => {
      setUsuario(data.user);
      setCarregando(false);
    });

    // Mantém a UI em sincronia com login, logout e refresh de token,
    // inclusive quando acontecem em outra aba.
    const { data: sub } = supabase.auth.onAuthStateChange((_evento, sessao) => {
      setUsuario(sessao?.user ?? null);
    });

    return () => sub.subscription.unsubscribe();
  }, []);

  return { usuario, carregando };
}