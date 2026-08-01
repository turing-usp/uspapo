import AppShell from "../../components/AppShell";
import Navbar from "../../components/navbar";

export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
      <AppShell>
        <Navbar />
        <div aria-hidden className="page-fade-b" />
        {children}
      </AppShell>
  )
}
