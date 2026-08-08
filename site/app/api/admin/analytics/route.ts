import { NextResponse } from 'next/server';
import { criarClienteServidor } from '@/lib/supabase-servidor';

export async function GET() {
  try {
    const supabase = await criarClienteServidor();
    const { data: { user }, error } = await supabase.auth.getUser();

    // Se o Supabase estiver configurado e o usuário não estiver logado
    if (error || !user) {
      const emailsPermitidos = (process.env.ADMIN_EMAILS || '').split(',').map((e) => e.trim().toLowerCase());
      
      // Se ADMIN_EMAILS for explicitamente definido e houver restrição
      if (emailsPermitidos.length > 0 && emailsPermitidos[0] !== '') {
        return NextResponse.json(
          { ok: false, erro: 'Acesso negado. Login de administrador necessário.' },
          { status: 401 }
        );
      }
    } else if (user) {
      const emailsPermitidos = (process.env.ADMIN_EMAILS || '').split(',').map((e) => e.trim().toLowerCase());
      if (emailsPermitidos.length > 0 && emailsPermitidos[0] !== '') {
        const emailUsuario = (user.email || '').toLowerCase();
        if (!emailsPermitidos.includes(emailUsuario)) {
          return NextResponse.json(
            { ok: false, erro: 'Acesso negado. Seu usuário não é administrador.' },
            { status: 403 }
          );
        }
      }
    }

    const backendUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:5000';
    const adminKey = process.env.ADMIN_API_KEY || 'uspapo-admin-secret-key-dev';

    const resp = await fetch(`${backendUrl}/api/analytics/resumo`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': adminKey,
      },
      cache: 'no-store',
    });

    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      return NextResponse.json(
        { ok: false, erro: errBody.erro || 'Erro na comunicação com o backend de analytics.' },
        { status: resp.status }
      );
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, erro: err?.message || 'Erro interno no servidor de analytics.' },
      { status: 500 }
    );
  }
}
