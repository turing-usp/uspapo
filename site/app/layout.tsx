import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Orbitron, Geom, Roboto} from "next/font/google";
import "./globals.css";
/* Estilo das fórmulas do chat. Aqui, e não dentro do chatResponse.tsx, para a
   ordem ser determinística: o KaTeX precisa cair DEPOIS do globals.css, senão o
   preflight do Tailwind ganha dele. As fontes .woff2 vêm do próprio pacote. */
import "katex/dist/katex.min.css";

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
  /* <meta name="color-scheme">. O globals.css já declara o mesmo em CSS, mas
     o Samsung Internet decide se vai recolorir a página com o algoritmo de
     modo escuro dele ANTES de aplicar folha de estilo, sem a meta tag, ele
     conclui que o site não sabe fazer escuro e reescreve as cores por cima,
     que é como um fundo #03042c chega lavado na tela. */
  colorScheme: "light dark",

  /* Espelha --base do globals.css nos dois esquemas. */
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#dde4f6" },
    { media: "(prefers-color-scheme: dark)", color: "#03042c" },
  ],
};

/* Escolhe o perfil do vidro antes do primeiro quadro.

   Tem que ser script inline no <head>: o vidro pesado é a aparência padrão do
   CSS, então qualquer decisão tomada depois da hidratação apareceria como um
   piscar de blur na tela de quem justamente não aguenta blur.

   Os sinais são baratos e todos síncronos. deviceMemory e connection não
   existem fora do Chromium, e é aceitável: fora do Chromium (iOS, Firefox) o
   backdrop-filter não é o gargalo que é no Android de entrada.

   ?vidro=leve e ?vidro=pesado forçam e gravam a escolha, para dar como
   comparar os dois no mesmo aparelho — é o que a /diagnostico.html usa. */
const ESCOLHER_VIDRO = `
try {
  var p = new URLSearchParams(location.search).get("vidro");
  if (p === "leve" || p === "pesado") localStorage.setItem("vidro", p);
  var g = localStorage.getItem("vidro");
  var leve = g === "leve" || (g !== "pesado" && (
    (navigator.deviceMemory || 8) <= 4 ||
    (navigator.hardwareConcurrency || 8) <= 4 ||
    matchMedia("(update: slow)").matches ||
    !!(navigator.connection && navigator.connection.saveData)
  ));
  if (leve) document.documentElement.dataset.vidro = "leve";
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="pt-BR"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${orbitron.variable} ${geom.variable} ${roboto.variable} h-full antialiased`}
    >
    <head>
      {/* O data-vidro é escrito aqui, antes do React montar. O <html> já tem
          suppressHydrationWarning, então o atributo a mais não diverge. */}
      <script dangerouslySetInnerHTML={{ __html: ESCOLHER_VIDRO }} />
    </head>
    <body className="h-full">
      {children}
    </body>
    </html>
  );
}
