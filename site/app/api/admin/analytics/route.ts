import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { credenciaisSupabase } from '@/lib/supabase';

/* `revalidate = false` é o valor DEFAULT documentado (sem efeito no modo SSR:
   a rota segue dinâmica por causa do request.headers e do fetch no-store),
   mas no modo export (NEXT_EXPORT=1) o Next 16 exige que uma rota com handler
   GET declare explicitamente como se renderiza — e esse literal satisfaz a
   checagem. Aí o handler devolve o 404 fixo acima sem tocar no request
   (totalmente estático), então o prerender vira um arquivo fixo sem surpresa.
   `dynamic = 'force-static'` não pode: congela a rota também no SSR. */
export const revalidate = false;

function administradorPermitido(email: string | undefined) {
  const permitidos = (process.env.ADMIN_EMAILS || '')
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return permitidos.length === 0 || permitidos.includes((email || '').toLowerCase());
}

export async function GET(request: Request) {
  // Export estático do app (Capacitor): NEXT_EXPORT=1 é lida no build e esta
  // rota vira arquivo estático — qualquer leitura do `request` a tornaria
  // dinâmica e derrubaria o export. No app o analytics admin nem existe
  // (sem backend por perto), então 404 direto, ANTES de tocar no request;
  // as telas admin já tratam a resposta com erro como indisponível.
  // No modo SSR (Vercel) a flag é indefinida e o handler segue intacto.
  if (process.env.NEXT_EXPORT === '1') {
    return NextResponse.json(
      { ok: false, erro: 'Analytics indisponivel no app.' },
      { status: 404 },
    );
  }
  try {
    // A autenticação parou de ler cookies: era o que impedia esta rota de
    // entrar no export estático do app (a cookie store a forçava dinâmica).
    // O navegador já tem a sessão, então as páginas admin enviam o token no
    // header `Authorization: Bearer <token>`.
    const autenticacao = request.headers.get('authorization') || '';
    const [esquema, token] = autenticacao.split(' ');

    if (esquema?.toLowerCase() !== 'bearer' || !token) {
      return NextResponse.json(
        { ok: false, erro: 'Acesso negado. Login de administrador necessario.' },
        { status: 401 },
      );
    }

    // `persistSession: false` porque isto roda no servidor: o cliente é só a
    // via de validação do JWT contra o Supabase, não há sessão a persistir.
    const [url, chave] = credenciaisSupabase();
    const supabase = createClient(url, chave, { auth: { persistSession: false } });
    const { data: { user }, error } = await supabase.auth.getUser(token);

    if (error || !user) {
      return NextResponse.json(
        { ok: false, erro: 'Acesso negado. Login de administrador necessario.' },
        { status: 401 },
      );
    }
    if (!administradorPermitido(user.email)) {
      return NextResponse.json(
        { ok: false, erro: 'Acesso negado. Seu usuario nao e administrador.' },
        { status: 403 },
      );
    }

    const backendUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
    const adminKey = process.env.ADMIN_API_KEY;
    if (!backendUrl || !adminKey) {
      return NextResponse.json(
        { ok: false, erro: 'Analytics indisponivel: backend ou chave administrativa nao configurados.' },
        { status: 503 },
      );
    }

    const resposta = await fetch(`${backendUrl}/api/analytics/resumo`, {
      headers: { 'X-Admin-Key': adminKey },
      cache: 'no-store',
    });
    const corpo = await resposta.json().catch(() => null);
    if (!resposta.ok || !corpo?.ok) {
      return NextResponse.json(
        { ok: false, erro: corpo?.erro || 'O backend de analytics nao respondeu corretamente.' },
        { status: 502 },
      );
    }

    // Existe uma única fonte de cálculo: o backend com a service key.
    // Não há fallback local que possa divergir ou mostrar dados parciais.
    return NextResponse.json({ ok: true, data: corpo.data }, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch (erro: unknown) {
    const mensagem = erro instanceof Error ? erro.message : 'Erro interno no analytics.';
    return NextResponse.json({ ok: false, erro: mensagem }, { status: 500 });
  }
}
