import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Orbitron, Geom, Roboto} from "next/font/google";
import "./globals.css";
import Navbar from "../components/navbar";
import Leftmenu from "../components/leftmenu";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const orbitron  = Orbitron({
  variable: "--font-orbitron-src",
  subsets: ["latin"],
  weight: ["400","700"]
});

const geom = Geom({
  variable: "--font-geom-src",
  subsets: ["latin"]
});

const roboto = Roboto({
  variable: "--font-roboto-src",
  subsets: ["latin"],
  weight: ["400","700"]
});

export const metadata: Metadata = {
  title: "USPapo",
  description: "USPapo - Seu assistente inteligente para navegar pela USP",
};

export const viewport: Viewport = {
  themeColor: "#03042c",
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${orbitron.variable} ${geom.variable} ${roboto.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Navbar />
        <Leftmenu />
        {children}
      </body>
    </html>
  );
}
