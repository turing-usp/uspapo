import AppShell from "../../components/AppShell";
import Leftmenu from "../../components/leftmenu";

export default function AuthLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AppShell>
      {/* Sem navbar aqui, então o gatilho ganha sua própria linha — mas segue
          em fluxo, nunca como camada fixa (ver o comentário em leftmenu). */}
      <div className="relative z-30 flex flex-none px-3 py-3">
        <Leftmenu />
      </div>
      <div className="app-scroll">{children}</div>
    </AppShell>
  );
}
