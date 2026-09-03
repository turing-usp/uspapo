'use client';

import React, { useState } from 'react';
import Image from 'next/image';
import TuringLogo from '../../turing-logo.svg';
import { useRouter } from 'next/navigation';
import { criarCliente } from '@/lib/supabase';
import { checarSenha } from '@/lib/auth';
import { useEffect, useRef } from 'react';

export default function NovaSenha() {
  const router = useRouter();
  const [senha, setSenha] = useState('');
  const [confirmacao, setConfirmacao] = useState('');
  const [mostrar, setMostrar] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [pronto, setPronto] = useState(false);
  const jatrocou = useRef(false);

    useEffect(() => {
    if (jatrocou.current) return;
    jatrocou.current = true;
    const code = new URLSearchParams(window.location.search).get('code');
    /* Sem código na URL a página segue o fluxo normal de sessão: este set
       fecha o carregamento de propósito, e o ref acima já garante que o
       efeito roda uma vez só. */
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!code) return setPronto(true);   // já tem sessão, ou link inválido

    criarCliente()
        .auth.exchangeCodeForSession(code)
        .then(({ error }) => {
        if (error) setErro('O link expirou ou já foi usado. Peça um novo.');
        setPronto(true);
        });
    }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErro(null);

    if (senha !== confirmacao) return setErro('As senhas não coincidem.');
    if (Object.values(checarSenha(senha)).some((ok) => !ok))
      return setErro('A senha não atende aos requisitos.');

    setCarregando(true);
    /* O link do email já criou uma sessão de recuperação, então o
       updateUser funciona sem pedir a senha antiga. */
    const { error } = await criarCliente().auth.updateUser({ password: senha });
    setCarregando(false);

    if (error) {
      setErro('Não foi possível alterar a senha. O link pode ter expirado.');
      return;
    }
    router.push('/');
    router.refresh();
  };

  return (
    <main className="flex min-h-full w-full items-center justify-center px-4 py-8 text-foreground">
      <div className="w-full max-w-md flex flex-col items-center">
        <div className="mb-6 flex items-center justify-center">
          <Image src={TuringLogo} alt="Turing Logo" />
        </div>

        <h1 className="text-xl md:text-2xl font-geom mb-8 tracking-wide text-center">
          Escolha uma nova senha
        </h1>
      {!pronto ? (
        <p className="text-sm text-muted-foreground text-center">
          Verificando link de recuperação…
        </p>
      ):(
        <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
          <div className="glass glass-field rounded-full relative w-full">
            <input
              type={mostrar ? 'text' : 'password'}
              placeholder="Nova senha"
              required
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              className="w-full px-5 py-3 rounded-full border-0 bg-transparent text-[1rem] text-foreground caret-brand placeholder:text-muted-foreground focus:outline-none"
            />
          </div>

          <div className="glass glass-field rounded-full relative w-full">
            <input
              type={mostrar ? 'text' : 'password'}
              placeholder="Confirmar nova senha"
              required
              value={confirmacao}
              onChange={(e) => setConfirmacao(e.target.value)}
              className="w-full px-5 py-3 rounded-full border-0 bg-transparent text-[1rem] text-foreground caret-brand placeholder:text-muted-foreground focus:outline-none"
            />
          </div>

          <label className="px-2 text-xs text-muted-foreground flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={mostrar} onChange={() => setMostrar(!mostrar)} className="accent-brand" />
            Mostrar senhas
          </label>

          {senha && (
            <ul className="px-2 space-y-0.5 text-xs" aria-live="polite">
              {([
                ['tamanho', 'Pelo menos 8 caracteres'],
                ['maiuscula', 'Uma letra maiúscula'],
                ['minuscula', 'Uma letra minúscula'],
                ['numero', 'Um número'],
                ['especial', 'Um caractere especial'],
              ] as const).map(([chave, rotulo]) => {
                const ok = checarSenha(senha)[chave];
                return (
                  <li key={chave} className={ok ? 'text-emerald-500' : 'text-faint-foreground'}>
                    {ok ? '✓' : '○'} {rotulo}
                  </li>
                );
              })}
            </ul>
          )}

          {erro && <p className="px-2 text-xs text-danger" role="alert">{erro}</p>}

          <button
            type="submit"
            disabled={carregando}
            className="cursor-pointer w-full py-3.5 mt-2 bg-brand hover:bg-brand-strong text-brand-foreground font-medium rounded-full text-base transition-colors duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {carregando ? 'Salvando…' : 'Salvar nova senha'}
          </button>
        </form>
      )}
      </div>
    </main>
  );
}