import AppShell from "../../components/AppShell";

/* Sem menu lateral aqui de propósito. Ele levava a "Novo Chat" e "Pesquisar
   histórico", e desde que o login virou obrigatório essas duas rotas devolvem
   quem está deslogado para cá mesmo. Era um controle que prometia uma saída
   que não existe. Quem não tem conta só precisa de duas portas, login e
   cadastro, e as duas páginas já se linkam uma para a outra.

   Sem a linha do gatilho, o app-scroll ocupa a casca inteira e o formulário
   (min-h-full + justify-center) passa a centralizar de verdade na vertical. */
export default function AuthLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AppShell>
      <div className="app-scroll">{children}</div>
    </AppShell>
  );
}
