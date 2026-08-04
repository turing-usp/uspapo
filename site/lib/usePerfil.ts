'use client';
import { useEffect, useState } from 'react';
import { criarCliente } from './supabase';

type Perfil = { nome: string | null; avatar_url: string | null; tipo_usuario: number };

export function usePerfil(id: string | undefined) {
  const [perfil, setPerfil] = useState<Perfil | null>(null);

  useEffect(() => {
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