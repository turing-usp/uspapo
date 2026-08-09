import { createBrowserClient } from '@supabase/ssr';

export const dominioCookie =
  process.env.NODE_ENV === 'production' ? '.turingusp.com' : undefined;

/* URL e anon key do projeto, o único lugar do site que nomeia essas duas
   variáveis: o cliente de navegador, o de servidor e o proxy todos vêm aqui.

   A chave é pública mesmo: vai embutida no bundle e qualquer um lê. Quem
   protege as tabelas é o RLS.

   Embutida literalmente, e é por isso que a conferência mora numa função e não
   num `!`: o Next troca `process.env.NEXT_PUBLIC_*` pelo valor durante o
   `next build` e congela ali. Faltar aqui não quer dizer "faltou na Vercel",
   quer dizer "faltava no ambiente que rodou o build". Preencher no painel só
   vale a partir do próximo deploy. O erro que o @supabase/ssr lança sozinho
   ("Your project's URL and Key are required") não diz nem qual das duas faltou
   nem que o problema é de build; este diz. */
export function credenciaisSupabase(): [url: string, chave: string] {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const chave = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !chave) {
    const faltando: string[] = [];
    if (!url) faltando.push('NEXT_PUBLIC_SUPABASE_URL');
    if (!chave) faltando.push('NEXT_PUBLIC_SUPABASE_ANON_KEY');
    throw new Error(
      `${faltando.join(' e ')} não estava(m) no ambiente do next build. ` +
        'Preencha e refaça o deploy: o valor é embutido no bundle, então ' +
        'mudar a variável no painel não conserta um build que já saiu.'
    );
  }

  return [url, chave];
}

export function criarCliente() {
  const [url, chave] = credenciaisSupabase();
  return createBrowserClient(url, chave, {
    cookieOptions: { domain: dominioCookie },
  });
}
