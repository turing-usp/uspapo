'use client';

import React, { useState } from 'react';
import Image from 'next/image';
import TuringLogo from '../../turing-logo.svg';
import { useSearchParams } from 'next/navigation';
import {Suspense} from "react";
import { enviarLinkDeSenha } from '../../../lib/auth';

function EsqueciASenha() {
  const [carregando, setCarregando] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const params = useSearchParams();
  const erroCallback = params.get('erro') === 'callback';

  /* Para onde o aluno estava indo quando o proxy.ts o mandou para cá.
     Só caminho interno: um "//site.com" ou "https://site.com" aqui viraria um
     redirecionamento aberto, com o nosso domínio dando credibilidade ao destino. */
     
  // Estado simplificado para credenciais de login
  const [formData, setFormData] = useState({
    email: '',
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const { name, value } = e.target;
      setFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErro(null);
    setCarregando(true);

    const { error } = await enviarLinkDeSenha(formData.email);
    setCarregando(false);

    if (error) {
        setErro('Não foi possível enviar o link. Tente de novo em instantes.');
        return;
        }
      setEnviado(true);
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
          Esqueci minha senha
        </h1>

        {/* Form */}
        {enviado ? (
            <p className="px-2 text-sm text-muted-foreground" role="status">
                Se existe uma conta com {formData.email}, enviamos um link para redefinir a senha.
            </p>
        ) : (
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

          {erroCallback && !erro && (
            <p className="px-2 text-xs text-faint-foreground">
              Não foi possível confirmar o link. Tente entrar com seu email novamente.
            </p>
          )}

          {erro && <p className="px-2 text-xs text-danger" role="alert">{erro}</p>}

          {/* BOTÃO PRINCIPAL: Entrar */}
          <button
            type="submit"
            disabled={carregando}
            className="cursor-pointer w-full py-3.5 mt-2 bg-brand hover:bg-brand-strong text-brand-foreground font-medium rounded-full text-base transition-colors duration-200 shadow-md hover:shadow-lg active:scale-[0.99]"
          >
            {carregando ? 'Enviando…' : 'Enviar link de redefinição'}
          </button>
        </form>
        )}
      </div>
    </main>
  );
}

export default function EsqueciASenhaPage() {
  return (
    <Suspense>
      <EsqueciASenha />
    </Suspense>
  );
}