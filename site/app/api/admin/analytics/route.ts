import { NextResponse } from 'next/server';
import { criarClienteServidor } from '@/lib/supabase-servidor';

function administradorPermitido(email: string | undefined) {
  const permitidos = (process.env.ADMIN_EMAILS || '')
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return permitidos.length === 0 || permitidos.includes((email || '').toLowerCase());
}

export async function GET() {
  try {
    const supabase = await criarClienteServidor();
    const { data: { user }, error } = await supabase.auth.getUser();

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
