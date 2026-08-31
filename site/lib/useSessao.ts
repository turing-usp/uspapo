'use client';

import { useCallback, useEffect, useState } from 'react';
import { criarCliente } from './supabase';
import type { User } from '@supabase/supabase-js';

export function useSessao() {
  const [usuario, setUsuario] = useState<User | null>(null);
  const [carregando, setCarregando] = useState(true);

  // Falha curta em pt-BR para o esqueleto do AppShell expor: antes o erro
  // era engolido no catch e a bola pulsava para sempre, sem dizer por quê.
  const [falha, setFalha] = useState<string | null>(null);

  // Contador de tentativa: o retry só reinicia o efeito abaixo (getUser +
  // timeout) sem recriar o cliente do zero.
  const [tentativa, setTentativa] = useState(0);

  useEffect(() => {
    const supabase = criarCliente();

    // `ativo` impede setState após o unmount e faz o timeout ceder para o
    // resultado real da chamada, se ele ainda chegar.
    let ativo = true;

    // O fetch do getUser() não tem timeout próprio: rede que conecta mas não
    // responde deixaria a promessa pendurada e o esqueleto do AppShell eterno.
    // O timeout agora também expõe a falha, em vez de só soltar o carregando.
    const timer = window.setTimeout(() => {
      if (ativo) {
        setUsuario(null);
        setFalha('A conexão demorou demais para responder.');
        setCarregando(false);
      }
    }, 15000);

    // Sem .catch, uma rejeição de rede (AuthRetryableFetchError, lançado pelo
    // supabase-js) mantinha `carregando` true para sempre (esqueleto eterno).
    // O `message` do erro (ex.: "Failed to fetch") vai para a tela e o
    // console.error fica no logcat, se um PC estiver conectado.
    supabase.auth.getUser()
      .then(({ data }) => {
        if (ativo) {
          setUsuario(data.user);
          setFalha(null);
        }
      })
      .catch((erro) => {
        if (!ativo) return;
        const m = erro instanceof Error && erro.message ? erro.message : 'Falha ao carregar a sessão.';
        setUsuario(null);
        setFalha(m);
        console.error('USPapo: falha ao carregar a sessão', erro);
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
  }, [tentativa]);

  // Retry: limpa a falha, volta para o estado de carregando e reinicia o
  // efeito acima — o increment do contador é o que re-dispara o getUser.
  const tentarNovamente = useCallback(() => {
    setFalha(null);
    setUsuario(null);
    setCarregando(true);
    setTentativa((t) => t + 1);
  }, []);

  return { usuario, carregando, falha, tentarNovamente };
}