'use client';

import { useEffect, useState } from 'react';
import { criarCliente } from './supabase';
import type { User } from '@supabase/supabase-js';

export function useSessao() {
  const [usuario, setUsuario] = useState<User | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    const supabase = criarCliente();

    // `ativo` impede setState após o unmount e faz o timeout ceder para o
    // resultado real da chamada, se ele ainda chegar.
    let ativo = true;

    // O fetch do getUser() não tem timeout próprio: rede que conecta mas não
    // responde deixaria a promessa pendurada e o esqueleto do AppShell eterno.
    const timer = window.setTimeout(() => {
      if (ativo) {
        setUsuario(null);
        setCarregando(false);
      }
    }, 15000);

    // Sem .catch, uma rejeição de rede (AuthRetryableFetchError, lançado pelo
    // supabase-js) mantinha `carregando` true para sempre (esqueleto eterno).
    supabase.auth.getUser()
      .then(({ data }) => {
        if (ativo) setUsuario(data.user);
      })
      .catch(() => {
        if (ativo) setUsuario(null);
      })
      .finally(() => {
        clearTimeout(timer);
        if (ativo) setCarregando(false);
      });

    // Mantém a UI em sincronia com login, logout e refresh de token,
    // inclusive quando acontecem em outra aba.
    const { data: sub } = supabase.auth.onAuthStateChange((_evento, sessao) => {
      setUsuario(sessao?.user ?? null);
    });

    return () => {
      ativo = false;
      clearTimeout(timer);
      sub.subscription.unsubscribe();
    };
  }, []);

  return { usuario, carregando };
}