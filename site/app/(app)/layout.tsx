import Navbar from "../../components/navbar";
import Leftmenu from "../../components/leftmenu";

export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
        <Navbar />
        <Leftmenu />
        {children}
    </>
  )
}