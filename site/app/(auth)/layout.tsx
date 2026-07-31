import Leftmenu from "../../components/leftmenu";

export default function AuthLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <Leftmenu />
      {children}
    </>
  );
}
