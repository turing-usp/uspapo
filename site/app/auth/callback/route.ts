// app/auth/callback/route.ts
import { NextResponse } from 'next/server';
import { criarClienteServidor } from '@/lib/supabase-servidor';

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get('code');

  if (code) {
    const supabase = await criarClienteServidor();  // versão server do client
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(`${origin}/`);
  }

  return NextResponse.redirect(`${origin}/login?erro=callback`);
}