'use client';
import { useEffect, useState } from 'react';
import { criarCliente } from './supabase';

type Perfil = { nome: string | null; avatar_url: string | null; tipo_usuario: number };

export function usePerfil(id: string | undefined) {
  const [perfil, setPerfil] = useState<Perfil | null>(null);

  useEffect(() => {
    /* Sem id não há perfil para buscar: zerar o estado aqui é a
       sincronização intencional com a ausência de usuário. */
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!id) return setPerfil(null);
    criarCliente()
      .from('Perfis')
      .select('nome, avatar_url, tipo_usuario')
      .eq('id', id)
      .single()
      .then(({ data }) => setPerfil(data));
  }, [id]);

  return perfil;
}