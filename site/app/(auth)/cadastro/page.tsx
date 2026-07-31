'use client';

import React, { useState } from 'react';
import Image from 'next/image';
import TuringLogo from '../../turing-logo.svg'

export default function RegisterPage() {
  // Estados para visibilidade das senhas
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // Estado do formulário
  const [formData, setFormData] = useState({
    fullName: '',
    birthDate: '',
    gender: '',
    username: '',
    password: '',
    confirmPassword: '',
    isUspStudent: false,
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    if (type === 'checkbox') {
      const checked = (e.target as HTMLInputElement).checked;
      setFormData((prev) => ({ ...prev, [name]: checked }));
    } else {
      setFormData((prev) => ({ ...prev, [name]: value }));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
  };

  return (
    <main className="bg relative min-h-screen w-full h-screen flex items-center justify-center overflow-hidden text-white px-4 py-8">
      {/* Background visual decorativo (luzes/gradientes radiais em camadas) */}
      <div className="absolute -top-40 -right-40 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-40 -left-40 w-96 h-96 bg-indigo-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Container principal do formulário */}
      <div className="w-full max-w-md z-10 flex flex-col items-center">
        <div className="mb-6 flex items-center justify-center">
          {
            <Image
              src={TuringLogo}
              alt="Turing Logo"
            />
          }
        </div>

        {/* Título da Página */}
        <h1 className="text-xl md:text-2 font-geom text-slate-100 mb-8 tracking-wide text-center">
          Crie a sua conta
        </h1>

        {/* Form */}
        <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
          
          {/* INPUT 1: Nome Completo */}
          <div className="glass relative w-full rounded-full">
            {/* PLACEHOLDER ÍCONE ESQUERDA: Usuário */}
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <input
              type="text"
              name="fullName"
              placeholder="Nome completo"
              value={formData.fullName}
              onChange={handleChange}
              className="w-full pl-12 pr-4 py-3 text-slate-100 placeholder-slate-400 rounded-full text-sm border border-transparent focus:outline-none focus:border-[#f58233] focus:ring-1 focus:ring-[#f58233] transition-all duration-200"
            />
          </div>

          {/* LINHA DUPLA: Data de Nascimento & Gênero */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            
            {/* INPUT 2: Data de Nascimento */}
            <div className="glass rounded-full relative w-full">
              {/* PLACEHOLDER ÍCONE ESQUERDA: Calendário */}
              <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              </div>
              <input
                type="text"
                name="birthDate"
                placeholder="DD/MM/AAAA"
                value={formData.birthDate}
                onChange={handleChange}
                className="w-full pl-12 pr-4 py-3 text-slate-100 placeholder-slate-400 rounded-full text-sm border border-transparent focus:outline-none focus:border-[#f58233] focus:ring-1 focus:ring-[#f58233] transition-all duration-200"
              />
            </div>

            {/* INPUT 3: Gênero */}
            <div className="glass rounded-full relative w-full">
              {/* PLACEHOLDER ÍCONE ESQUERDA: Gênero / Usuário */}
              <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>
              <input
                type="text"
                name="gender"
                placeholder="Gênero"
                value={formData.gender}
                onChange={handleChange}
                className="w-full pl-12 pr-4 py-3 text-slate-100 placeholder-slate-400 rounded-full text-sm border border-transparent focus:outline-none focus:border-[#f58233] focus:ring-1 focus:ring-[#f58233] transition-all duration-200"
              />
            </div>
          </div>

          {/* INPUT 4: Usuário / E-mail */}
          <div className="glass rounded-full relative w-full">
            {/* PLACEHOLDER ÍCONE ESQUERDA: Cadeado / Usuário */}
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <input
              type={showPassword ? 'text' : 'password'}
              name="username"
              placeholder="Senha"
              value={formData.username}
              onChange={handleChange}
              className="w-full pl-12 pr-4 py-3 text-slate-100 placeholder-slate-400 rounded-full text-sm border border-transparent focus:outline-none focus:border-[#f58233] focus:ring-1 focus:ring-[#f58233] transition-all duration-200"
            />
            {/* BOTÃO MASCARAR/EXIBIR */}
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="cursor-pointer absolute inset-y-0 right-0 pr-4 flex items-center text-slate-400 hover:text-slate-200 focus:outline-none"
            >
              {showPassword ? (
                /* Ícone Olho Fechado (riscado) */
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

          {/* INPUT 5: Confirmar Senha */}
          <div className="glass rounded-full relative w-full">
            {/* PLACEHOLDER ÍCONE ESQUERDA: Cadeado */}
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <input
              type={showConfirmPassword ? 'text' : 'password'}
              name="confirmPassword"
              placeholder="Confirmar senha"
              value={formData.confirmPassword}
              onChange={handleChange}
              className="w-full pl-12 pr-4 py-3 text-slate-100 placeholder-slate-400 rounded-full text-sm border border-transparent focus:outline-none focus:border-[#f58233] focus:ring-1 focus:ring-[#f58233] transition-all duration-200"
            />
            {/* BOTÃO MASCARAR/EXIBIR */}
            <button
              type="button"
              onClick={() => setShowConfirmPassword(!showConfirmPassword)}
              className="cursor-pointer absolute inset-y-0 right-0 pr-4 flex items-center text-slate-400 hover:text-slate-200 focus:outline-none"
            >
              {showConfirmPassword ? (
                /* Ícone Olho Fechado (riscado) */
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

          {/* RADIO / SELEÇÃO: Sou aluno da USP */}
          <div className="flex items-center gap-3 my-1 px-2">
            <label className="relative flex items-center cursor-pointer">
              <input
                type="checkbox"
                name="isUspStudent"
                checked={formData.isUspStudent}
                onChange={handleChange}
                className="sr-only peer"
              />
              <div className="w-5 h-5 rounded-full border-2 border-[#f58233] flex items-center justify-center transition-all peer-checked:bg-transparent">
                <div className={`w-2.5 h-2.5 rounded-full bg-[#f58233] transition-opacity duration-150 ${formData.isUspStudent ? 'opacity-100' : 'opacity-0'}`} />
              </div>
              <span className="ml-3 text-sm text-slate-200 select-none">
                Sou aluno da USP
              </span>
            </label>
          </div>

          {/* BOTÃO PRINCIPAL: Cadastrar */}
          <button
            type="submit"
            className="cursor-pointer w-full py-3.5 mt-2 bg-[#f58233] hover:bg-[#e07125] text-white font-medium rounded-full text-base transition-colors duration-200 shadow-md hover:shadow-lg active:scale-[0.99]"
          >
            Cadastrar
          </button>
        </form>

        {/* DIVISOR DA OPÇÃO DE LOGIN SOCIAL */}
        <div className="w-full flex items-center my-6">
          <div className="flex-1 border-t border-slate-600/60" />
          <span className="px-4 text-l font-geom tracking-wider">OU</span>
          <div className="flex-1 border-t border-slate-600/60" />
        </div>

        {/* ========================================================= */}
        {/* PLACEHOLDER 2: BOTÃO GOOGLE                               */}
        {/* ========================================================= */}
        <button
          type="button"
          className="cursor-pointer w-full py-3 px-4 bg-white hover:bg-slate-50 text-slate-800 font-medium rounded-full text-sm flex items-center justify-center relative transition-all duration-200 border border-transparent focus:outline-none focus:border-[#f58233] focus:ring-2 focus:ring-[#f58233]"
        >
          {/* Ícone Logo do Google */}
          <div className="absolute left-4 flex items-center justify-center">
            {/* 
              Substitua este SVG/div pela sua imagem de logo do Google:
              <Image src="/google-logo.svg" alt="Google" width={20} height={20} />
            */}
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

        {/* LINK FOOTER: Já possui conta */}
        <p className="mt-8 text-sm text-slate-300">
          Já possui uma conta?{' '}
          <a
            href="/login"
            className="cursor-pointer text-[#f58233] font-medium hover:underline transition-colors"
          >
            Entre
          </a>
        </p>

      </div>
    </main>
  );
}
