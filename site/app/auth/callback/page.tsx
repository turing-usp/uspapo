'use client';

/* Callback do login com Google (e do "confirmar email") no Supabase.
   Página cliente no lugar do route handler SSR de antes: o handler lia a
   cookie store no servidor, o que forçava a rota a ser dinâmica e barrava
   o export estático. Aqui o supabase-js troca o `code` da URL pela sessão
   direto no navegador (o PKCE/`code_verifier` fica no `localStorage` e o
   cliente do browser cuida sozinho) e grava a sessão em cookie do próprio
   navegador no origin do site (domínio `.turingusp.com` via `dominioCookie`).
   O `redirectTo`/`emailRedirectTo` do fluxo (lib/auth.ts) já aponta para
   esta URL — nada muda do lado do provider. */

import { Suspense, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { criarCliente } from '@/lib/supabase';

function Callback() {
  const router = useRouter();
  const params = useSearchParams();
  const code = params.get('code');

  useEffect(() => {
    /* Sem `code` a troca é impossível (o provider devolveu um erro ou a
       pessoa abriu a URL no ar): mesma saída do handler antigo. */
    if (!code) {
      router.replace('/login?erro=callback');
      return;
    }

    let cancelado = false;
    (async () => {
      const { error } = await criarCliente().auth.exchangeCodeForSession(code);
      if (cancelado) return;

      if (error) {
        router.replace('/login?erro=callback');
        return;
      }

      /* Sessão já gravada em cookie do navegador; o refresh faz o proxy
         revalidar contra o cookie novo — mesmo padrão da página de login. */
      router.replace('/');
      router.refresh();
    })();

    return () => {
      /* Navegação cancelada no meio da troca: não redirecionamos por cima. */
      cancelado = true;
    };
  }, [code, router]);

  return (
    <main className="flex min-h-full w-full items-center justify-center text-foreground">
      <p className="text-sm text-muted-foreground">Confirmando seu acesso…</p>
    </main>
  );
}

/* `useSearchParams` numa página estática exige fronteira de `<Suspense>`
   (o build falha sem ela) — mesma exigência da página de login. */
export default function AuthCallbackPage() {
  return (
    <Suspense>
      <Callback />
    </Suspense>
  );
}
