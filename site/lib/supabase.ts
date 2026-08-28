import { createBrowserClient } from '@supabase/ssr';

/* Domínio do cookie de sessão.
   NEXT_PUBLIC_COOKIE_DOMAIN, quando DEFINIDA — inclusive string vazia — manda
   na frente; o check é `!== undefined` de propósito, nunca `||`, porque o
   vazio é valor legítimo e significa "sem domínio". O vazio é mapeado para
   `undefined` no cookieOptions, que é como o @supabase/ssr representa cookie
   host-only (sem domínio): o app embutido roda na origem local
   (`localhost`) e nenhum domínio de subdomínio se aplica.
   INDEFINIDA → o comportamento de sempre: produção no domínio raiz
   `.turingusp.com` (o cookie vale em qualquer subdomínio), dev sem domínio. */
export const dominioCookie = (() => {
  const variavel = process.env.NEXT_PUBLIC_COOKIE_DOMAIN;
  if (variavel !== undefined) {
    return variavel === '' ? undefined : variavel;
  }
  return process.env.NODE_ENV === 'production' ? '.turingusp.com' : undefined;
})();

/* URL e anon key do projeto, o único lugar do site que nomeia essas duas
   variáveis: o cliente de navegador vem aqui (a portaria de sessão é o guard
   do AppShell e o callback de login — ambos no client).

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

/* Token da sessão no navegador, para mandar como `Authorization: Bearer <token>`
   nos fetches same-origin que batem nas rotas de API que pararam de ler cookies
   (export estático: a cookie store as forçava dinâmicas).
   Sem sessão devolve null — o consumidor manda o pedido como antes e o 401
   mantém o comportamento de "sessão expirada". */
export async function tokenDaSessao(): Promise<string | null> {
  const { data: { session } } = await criarCliente().auth.getSession();
  return session?.access_token ?? null;
}
