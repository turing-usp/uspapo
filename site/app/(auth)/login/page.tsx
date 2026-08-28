'use client';

import React, { useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import TuringLogo from '../../turing-logo.svg';
import { entrar, entrarComGoogle } from '@/lib/auth';
import { useRouter, useSearchParams } from 'next/navigation';
import {Suspense} from "react";
import { useSessao } from '@/lib/useSessao';

function LoginForm() {
  // Estado para visibilidade da senha
  const [showPassword, setShowPassword] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const router = useRouter();
  const params = useSearchParams();
  const erroCallback = params.get('erro') === 'callback';

  /* Para onde o aluno estava indo quando a portaria do AppShell o mandou para
     cá (o antigo proxy.ts, removido p/ viabilizar o export estático).
     Só caminho interno: um "//site.com" ou "https://site.com" aqui viraria um
     redirecionamento aberto, com o nosso domínio dando credibilidade ao destino. */
  const pedido = params.get('destino') ?? '';
  const destino = pedido.startsWith('/') && !pedido.startsWith('//') ? pedido : '/';

  /* Já logado não tem o que fazer na tela de login: a segunda regra do antigo
     proxy.ts (que mandava /login e /cadastro de volta para /), agora no client.
     O ref existe para o login do próprio formulário: o onAuthStateChange
     devolve o usuário assim que ele entra, e sem a marca o replace('/')
     disputaria com o push para o ?destino= e o deep-link /chat?id=... morria. */
  const acabouDeEntrar = useRef(false);
  const { usuario } = useSessao();

  useEffect(() => {
    if (usuario && !acabouDeEntrar.current) router.replace('/');
  }, [usuario, router]);

  // Estado simplificado para credenciais de login
  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const { name, value } = e.target;
      setFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErro(null);
    setCarregando(true);

    const { error } = await entrar(formData.email, formData.password);
    setCarregando(false);

    if (error) {
      /* Conta criada mas email não confirmado é o erro mais comum aqui, e
         chamar isso de "senha incorreta" manda a pessoa para a recuperação de
         senha quando a resposta estava na caixa de entrada dela. */
      setErro(
        error.code === 'email_not_confirmed'
          ? 'Falta confirmar seu email. Abra o link que enviamos para ativar a conta.'
          : 'Email ou senha incorretos.'
      );
      return;
    }

    /* Marca antes do push: o usuário já chegou via onAuthStateChange e o
       efeito de "já logado" não pode rebater para cima do destino pedido. */
    acabouDeEntrar.current = true;
    router.push(destino);
    router.refresh();
  };

  const handleGoogleLogin = async () => {
    setErro(null);
    setCarregando(true);
    const { error } = await entrarComGoogle();
    if (error) {
      setErro('Erro ao conectar com o Google.');
      setCarregando(false);
    }
  };

  return (
    <main className="flex min-h-full w-full items-center justify-center px-4 py-8 text-foreground">
      {/* Container principal do formulário */}
      <div className="w-full max-w-md flex flex-col items-center">
        <div className="mb-6 flex items-center justify-center">
          <Image src={TuringLogo} alt="Turing Logo" />
        </div>

        {/* Título da Página */}
        <h1 className="text-xl md:text-2xl font-geom text-foreground mb-8 tracking-wide text-center">
          Entre com sua conta
        </h1>

        {/* Form */}
        <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
          
          {/* INPUT 1: Email */}
          <div className="glass glass-field relative w-full rounded-full">
            {/* Ícone Envelope */}
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-muted-foreground">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <input
              type="email"
              name="email"
              placeholder="Email"
              required
              value={formData.email}
              onChange={handleChange}
              className="w-full pl-12 pr-4 py-3 rounded-full border-0 bg-transparent text-[1rem] text-foreground caret-brand placeholder:text-muted-foreground focus:outline-none"
            />
          </div>

          {/* INPUT 2: Senha */}
          <div className="glass glass-field rounded-full relative w-full">
            {/* Ícone Cadeado */}
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-muted-foreground">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <input
              type={showPassword ? 'text' : 'password'}
              name="password"
              placeholder="Senha"
              required
              value={formData.password}
              onChange={handleChange}
              className="w-full pl-12 pr-12 py-3 rounded-full border-0 bg-transparent text-[1rem] text-foreground caret-brand placeholder:text-muted-foreground focus:outline-none"
            />
            {/* Botão para alternar visibilidade */}
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="cursor-pointer absolute inset-y-0 right-0 pr-4 flex items-center text-muted-foreground hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand focus:outline-none"
            >
              {showPassword ? (
                /* Ícone Olho Fechado */
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858-5.908A8.962 8.962 0 0112 5c4.478 0 8.268 2.943 9.542 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21M3 3l18 18" />
                </svg>
              ) : (
                /* Ícone Olho Aberto */
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>

          {erroCallback && !erro && (
            <p className="px-2 text-xs text-faint-foreground">
              Não foi possível confirmar o link. Tente entrar com seu email e senha.
            </p>
          )}

          {erro && <p className="px-2 text-xs text-danger" role="alert">{erro}</p>}

          {/* BOTÃO PRINCIPAL: Entrar */}
          <button
            type="submit"
            disabled={carregando}
            className="cursor-pointer w-full py-3.5 mt-2 bg-brand hover:bg-brand-strong text-brand-foreground font-medium rounded-full text-base transition-colors duration-200 shadow-md hover:shadow-lg active:scale-[0.99]"
          >
            {carregando ? 'Entrando…' : 'Entrar'}
          </button>
        </form>

        {/* LINK: Esqueceu a senha */}
        <a
          href="/esqueci-a-senha"
          className="mt-4 text-sm text-brand font-medium hover:underline transition-colors cursor-pointer"
        >
          Esqueceu a senha?
        </a>

        {/* DIVISOR OU */}
        <div className="w-full flex items-center my-6">
          <div className="flex-1 border-t border-line/15" />
          <span className="px-4 text-sm font-geom tracking-wider">OU</span>
          <div className="flex-1 border-t border-line/15" />
        </div>

        {/* BOTÃO GOOGLE */}
        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={carregando}
          className="cursor-pointer w-full py-3 px-4 bg-surface-raised hover:bg-surface text-foreground font-medium rounded-full text-sm flex items-center justify-center relative transition-colors duration-200 border border-line/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          <div className="absolute left-4 flex items-center justify-center">
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
          </div>
          <span>Continuar com o Google</span>
        </button>

        {/* LINK FOOTER: Cadastre-se */}
        <p className="mt-8 text-sm text-muted-foreground">
          Não tem uma conta?{' '}
          <a
            href="/cadastro"
            className="cursor-pointer text-brand font-medium hover:underline transition-colors"
          >
            Cadastre-se
          </a>
        </p>

      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}