'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useSessao } from '@/lib/useSessao';
import { sair } from '@/lib/auth';
import Image from 'next/image';
import { usePerfil } from '@/lib/usePerfil';

export default function MenuUsuario() {
  const { usuario, carregando } = useSessao();
  const perfil = usePerfil(usuario?.id);
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Fecha ao clicar fora ou apertar Esc.
  useEffect(() => {
    if (!aberto) return;
    const clique = (e: MouseEvent) => {
      if (!caixa.current?.contains(e.target as Node)) setAberto(false);
    };
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && setAberto(false);
    document.addEventListener('mousedown', clique);
    document.addEventListener('keydown', tecla);
    return () => {
      document.removeEventListener('mousedown', clique);
      document.removeEventListener('keydown', tecla);
    };
  }, [aberto]);

  // Nada durante a checagem: piscar "Entrar" para quem está logado é pior
  // que um instante vazio.
  if (carregando) return <div className="h-9 w-9" />;

  if (!usuario) {
    return (
      <>
        <Link
          href="/login"
          className="glass inline-flex items-center text-sm md:text-base text-brand px-4 md:px-8 py-1.5 rounded-[2rem] whitespace-nowrap hover:scale-103 transition-transform duration-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          Entrar
        </Link>
        <Link
          href="/cadastro"
          className="glass glass-brand inline-flex items-center text-sm md:text-base text-brand px-4 md:px-8 py-1.5 rounded-[2rem] whitespace-nowrap hover:scale-103 transition-transform duration-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          Cadastrar
        </Link>
      </>
    );
  }

  const nome = perfil?.nome ?? (usuario.user_metadata?.nome as string) ?? usuario.email ?? '';
  const inicial = nome.trim().charAt(0).toUpperCase() || '?';

  return (
    <div ref={caixa} className="relative">
      <button
        onClick={() => setAberto(!aberto)}
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-label="Menu do usuário"
        className="h-9 w-9 overflow-hidden rounded-full bg-brand text-brand-foreground font-medium grid place-items-center cursor-pointer transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
        {perfil?.avatar_url ? (
            <Image
            src={perfil.avatar_url}
            alt=""
            width={36}
            height={36}
            className="h-full w-full object-cover"
            />
        ) : (
            inicial
        )}
        </button>

      {aberto && (
        <div
          role="menu"
          className="glass absolute right-0 top-11 z-50 w-56 rounded-2xl p-1 text-sm"
        >
          <div className="px-3 py-2">
            <p className="truncate text-foreground">{nome}</p>
            <p className="truncate text-xs text-faint-foreground">{usuario.email}</p>
          </div>

          <div className="my-1 border-t border-line/10" />

          <button
            role="menuitem"
            onClick={async () => {
              await sair();
              setAberto(false);
              router.push('/');
              router.refresh();
            }}
            className="w-full rounded-xl px-3 py-2 text-left text-danger hover:bg-tint/5 transition-colors cursor-pointer"
          >
            Sair
          </button>
        </div>
      )}
    </div>
  );
}