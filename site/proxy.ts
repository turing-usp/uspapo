/* Portaria do site: sem sessão, ninguém chega no chat.
 *
 * Desde o Next 16 este arquivo se chama `proxy.ts`, é o antigo `middleware.ts`,
 * mesmo comportamento e nome novo. Ele roda antes da rota renderizar, que é o
 * ponto: um guard em `useEffect` deixaria o aluno deslogado ver a tela do chat
 * montar inteira para só então ser chutado para o login.
 *
 * Aqui é uma checagem OTIMISTA, como a própria doc do Next recomenda: quem
 * decide de verdade quem pode perguntar é o backend, que confere a assinatura do
 * token no /chat (uspapo/contas.py) e a whitelist (uspapo/acesso.py). Isto aqui
 * só evita mandar o aluno para uma tela que não vai funcionar.
 *
 * O `getUser()` também renova a sessão e devolve os cookies atualizados. Por
 * isso os cookies são copiados para a resposta em vez de a gente sair criando
 * NextResponse novo no fim.
 */
import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

import { credenciaisSupabase, dominioCookie } from './lib/supabase';

/* Rotas que existem justamente para quem não tem sessão.
 *
 * `/esqueci-senha` está aqui embora a página ainda não exista: a tela de login
 * já linka para ela, e é a única rota do site cuja ausência daqui vira armadilha
 * de verdade. Quem esqueceu a senha não consegue entrar, então exigir sessão
 * para chegar na recuperação de senha tranca a pessoa para fora de vez. É mais
 * barato deixar a porta destrancada agora do que descobrir isso depois. */
const PUBLICAS = ['/login', '/cadastro', '/esqueci-senha', '/auth'];

export async function proxy(request: NextRequest) {
  let resposta = NextResponse.next({ request });
  const [url, chave] = credenciaisSupabase();

  const supabase = createServerClient(
    url,
    chave,
    {
      cookieOptions: { domain: dominioCookie },
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (lista) => {
          lista.forEach(({ name, value }) => request.cookies.set(name, value));
          resposta = NextResponse.next({ request });
          lista.forEach(({ name, value, options }) =>
            resposta.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  /* getUser() e não getSession(): o getSession lê o cookie sem conferir nada,
     e um cookie é coisa que o navegador pode ter guardado vencido. */
  const { data } = await supabase.auth.getUser();

  const caminho = request.nextUrl.pathname;
  const publica = PUBLICAS.some(
    (rota) => caminho === rota || caminho.startsWith(`${rota}/`)
  );

  if (!data.user && !publica) {
    const login = request.nextUrl.clone();
    login.pathname = '/login';
    /* Para onde ele queria ir, para o login devolver depois de entrar. */
    login.searchParams.set('destino', caminho);
    return NextResponse.redirect(login);
  }

  /* Já logado não tem o que fazer na tela de login. */
  if (data.user && (caminho === '/login' || caminho === '/cadastro')) {
    const inicio = request.nextUrl.clone();
    inicio.pathname = '/';
    inicio.search = '';
    return NextResponse.redirect(inicio);
  }

  return resposta;
}

export const config = {
  /* Sem matcher o proxy rodaria em CSS, imagem e favicon também, e aí o
     redirecionamento de quem não está logado quebraria o carregamento da própria
     tela de login. */
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
};
