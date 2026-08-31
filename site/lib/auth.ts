// lib/auth.ts
import { criarCliente } from './supabase';

export function checarSenha(senha: string) {
  return {
    tamanho:   senha.length >= 8,
    maiuscula: /[A-Z]/.test(senha),
    minuscula: /[a-z]/.test(senha),
    numero:    /[0-9]/.test(senha),
    especial:  /[^A-Za-z0-9]/.test(senha),
  };
}

export function validarCadastro(senha: string, confirmacao: string) {
  if (senha !== confirmacao) return 'As senhas não coincidem.';
  if (Object.values(checarSenha(senha)).some((ok) => !ok))
    return 'A senha não atende aos requisitos.';
  return null;
}

/* O supabase-js LANÇA AuthRetryableFetchError quando a rede falha, em vez de
   resolver com { error }. Sem este catch a rejeição escaparia dos handlers de
   tela (que esperam o shape { data, error }); convertemos a falha para o mesmo
   shape, com code 'rede_indisponivel' para a UI avisar sobre a conexão. */
async function semRejeicaoDeRede<T>(chamada: () => Promise<T>): Promise<T> {
  try {
    return await chamada();
  } catch (erro) {
    return {
      data: null,
      error: {
        name: 'AuthError',
        message: erro instanceof Error ? erro.message : String(erro),
        status: 0,
        code: 'rede_indisponivel',
      },
    } as unknown as T;
  }
}

export async function cadastrar(nome: string, email: string, senha: string) {
  const supabase = criarCliente();
  return semRejeicaoDeRede(() =>
    supabase.auth.signUp({
      email: email.trim(),
      password: senha,
      options: {
        data: { nome: nome.trim() },
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    })
  );
}

export async function entrar(email: string, senha: string) {
  const supabase = criarCliente();
  return semRejeicaoDeRede(() =>
    supabase.auth.signInWithPassword({
      email: email.trim(),
      password: senha,
    })
  );
}

export async function sair() {
  const supabase = criarCliente();
  return supabase.auth.signOut();
}

export async function entrarComGoogle() {
  const supabase = criarCliente();
  return semRejeicaoDeRede(() =>
    supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    })
  );
}

export async function enviarLinkDeSenha(email: string) {
  const supabase = criarCliente();
  return semRejeicaoDeRede(() =>
    supabase.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: `${window.location.origin}/nova-senha`,
    })
  );
}