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
  /* <meta name="color-scheme">, que acerta scrollbar, campo de texto e o resto
     dos controles nativos em todo navegador que se comporta.

     Não é ele que resolve o Samsung Internet, e já foi tentado aqui: o force
     dark de lá não pergunta se o site sabe fazer escuro. Ele IGNORA o ramo
     prefers-color-scheme: dark, renderiza o ramo claro e recolore o resultado
     com algoritmo próprio, sem opt-out nenhum do lado de cá. Quem tinha que
     mudar era o CSS, que forçava a paleta escura em todo navegador sem
     light-dark(), o Samsung Internet <= 24 inteiro, e entregava ao algoritmo
     uma página já escura para ele inverter de novo. Ver o comentário do
     dicionário de cores no globals.css. */
  colorScheme: "light dark",

  /* Espelha --base do globals.css nos dois esquemas. */
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#dde4f6" },
    { media: "(prefers-color-scheme: dark)", color: "#03042c" },
  ],
};

/* Promove ao vidro pesado o aparelho que aguenta, antes do primeiro quadro.

   A direção importa: quem sai do servidor é o LEVE (o data-vidro no <html>
   abaixo), e este script só promove. Era o contrário, e o contrário errava
   para o lado caro, script que não roda, navegador com JS desligado ou uma
   exceção engolida pelo catch deixavam a lente ligada justamente em quem menos
   aguenta. Agora a falha cai no barato, que é como tem que ser.

   Tem que ser script inline no <head> de qualquer jeito: decisão tomada depois
   da hidratação apareceria como um piscar de blur na tela.

   A regra virou conjunção. O pesado precisa de TODOS os sinais, em vez de o
   leve precisar de um. E o sinal que manda é o primeiro:

   (hover: hover) and (pointer: fine) quer dizer mouse, e mouse quer dizer
   computador. O que os quatro sinais antigos não viam é que o gargalo do
   backdrop-filter não é RAM nem núcleo, é a GPU relendo o framebuffer a cada
   quadro, coisa que celular de linha média sofre e reporta 8 GB e 8 núcleos
   assim mesmo, porque o deviceMemory é limitado em 8 e arredondado. Celular,
   tablet e Chromebook de toque ficam leves; o resto é conferido pelas specs.

   deviceMemory e connection não existem fora do Chromium e caem no padrão
   generoso de propósito: fora do Chromium (iOS, Firefox) quem decide é o
   pointer, e lá o backdrop-filter não é o gargalo que é no Android.

   Três fontes mandam mais que a regra, nesta ordem: ?vidro=leve|pesado (que
   grava), a escolha gravada, e o veredito da sonda. */
const ESCOLHER_VIDRO = `
(function () {
try {
  var raiz = document.documentElement;

  var pedido = new URLSearchParams(location.search).get("vidro");
  if (pedido === "leve" || pedido === "pesado") localStorage.setItem("vidro", pedido);

  var escolhido = localStorage.getItem("vidro");
  var pesado = escolhido
    ? escolhido === "pesado"
    : localStorage.getItem("vidro-medido") !== "leve" && (
        matchMedia("(hover: hover) and (pointer: fine)").matches &&
        (navigator.deviceMemory || 8) >= 8 &&
        (navigator.hardwareConcurrency || 8) >= 8 &&
        !matchMedia("(update: slow)").matches &&
        !matchMedia("(prefers-reduced-transparency: reduce)").matches &&
        !(navigator.connection && navigator.connection.saveData)
      );

  if (!pesado) return;
  raiz.dataset.vidro = "pesado";

  /* A sonda de quadros: pega o aparelho que passou na regra e engasga mesmo
     assim. Só faz sentido aqui dentro (medir o leve não decide nada) e só sem
     escolha explícita gravada, quem digitou ?vidro=pesado quer o pesado.

     O capture não é enfeite: a conversa rola dentro do .app-scroll, não no
     documento, e evento de scroll não borbulha. Sem a fase de captura a sonda
     nunca dispararia na única tela onde o custo aparece. */
  if (escolhido) return;
  addEventListener("scroll", function () {
    var restantes = 90, lentos = 0, anterior = performance.now();
    requestAnimationFrame(function passo(agora) {
      if (agora - anterior > 22) lentos++;   // abaixo de ~45 fps
      anterior = agora;
      if (--restantes > 0) return requestAnimationFrame(passo);
      /* Um terço dos quadros perdidos em ~1,5 s de rolagem. Grava em chave
         própria, e não em "vidro": misturar medição com escolha do usuário
         tiraria o jeito de reavaliar quando a regra mudar. */
      if (lentos > 30) {
        localStorage.setItem("vidro-medido", "leve");
        raiz.dataset.vidro = "leve";
      }
    });
  }, { once: true, passive: true, capture: true });
} catch (e) {}
})();
`;

/* Diagnóstico temporário da WebView — remover depois da triagem.

   O app instalado nunca mostra a tela de erro de timeout: sintoma coerente
   com o JavaScript dos chunks nunca executar na WebView (o HTML estático e o
   CSS funcionam sem JS). Este script roda MESMO se o bundle falhar, porque
   é inline e não depende dele. Só atua em hostname === "localhost" (o
   deploy web é no-op); após 8 s, se detectar qualquer problema — flight
   data ausente, fetch de um chunk de controle com falha, erro de
   load/promise capturado, ou recurso _next sem bytes — injeta na base da
   tela uma faixa fixa com o veredito: versão do Chrome, flight, chunk,
   erros e contagem de recursos. Tudo ok: não injeta nada.

   O código de dentro é var/clássico e SEM template strings (nenhum ${),
   por ser texto crú dentro deste template literal — os backslashes da
   regex e do \n estão duplicados justamente por isso. */
const DIAGNOSTICO_WEBVIEW = `
(function () {
  if (location.hostname !== "localhost") return;
  try {
    var erros = [];
    function h(e) {
      erros.push((e && e.target && e.target.src ? "script " + e.target.src.split("/").pop() : "js") + ": " + (e.message || "falha de load"));
      if (erros.length > 10) window.removeEventListener("error", h, true);
    }
    window.addEventListener("error", h, true);
    function hRej(e) {
      var motivo = e.reason;
      erros.push("promise: " + ((motivo && motivo.message) || (motivo ? String(motivo) : "rejeição sem motivo")));
      if (erros.length > 10) window.removeEventListener("unhandledrejection", hRej);
    }
    window.addEventListener("unhandledrejection", hRej);
    setTimeout(function () {
      try {
        var flight = !!window.__next_f;
        var recs = performance.getEntriesByType("resource").filter(function (r) {
          return r.name.indexOf("_next/") !== -1;
        });
        var comBytes = recs.filter(function (r) {
          return (r.transferSize || 0) > 0;
        }).length;
        var el = document.querySelector("script[src*='_next/static/chunks']");
        var chunkInfo = "chunk: elemento não encontrado";
        var chunkFalhou = true;
        function concluir() {
          if (flight && !chunkFalhou && comBytes >= recs.length && erros.length === 0) return;
          var corpo = document.body;
          if (!corpo) {
            corpo = document.createElement("body");
            document.documentElement.appendChild(corpo);
          }
          var faixa = document.createElement("div");
          faixa.style.cssText = "position:fixed;left:8px;right:8px;bottom:8px;z-index:2147483647;background:#111;color:#fff;font:11px/1.5 monospace;padding:8px;border-radius:8px;white-space:pre-wrap";
          var m = navigator.userAgent.match(/Chrome\\/(\\d+)/);
          var linhas = ["USPapo diag: chrome " + (m ? m[1] : navigator.userAgent.slice(0, 60))];
          linhas.push("USPapo diag: flight: " + (flight ? "ok" : "faltando"));
          linhas.push("USPapo diag: " + chunkInfo);
          if (erros.length > 0) {
            var n = Math.min(2, erros.length);
            for (var i = 0; i < n; i++) linhas.push("USPapo diag: " + erros[i].slice(0, 80));
          } else {
            linhas.push("USPapo diag: erros: nenhum");
          }
          linhas.push("USPapo diag: recursos _next com bytes: " + comBytes + "/" + recs.length);
          faixa.textContent = linhas.join("\\n");
          corpo.appendChild(faixa);
        }
        if (el) {
          fetch(el.src)
            .then(function (resp) {
              if (!resp.ok) { chunkInfo = "chunk: " + resp.status; return; }
              return resp.text().then(function (texto) {
                var bytes = parseInt(resp.headers.get("content-length"), 10) || texto.length;
                chunkInfo = "chunk: " + resp.status + " (" + Math.round(bytes / 1024) + " kB)";
                chunkFalhou = false;
              });
            })
            .catch(function (e) {
              chunkInfo = "chunk: erro " + (e && e.message ? e.message : String(e));
            })
            .then(concluir);
        } else {
          concluir();
        }
      } catch (e) {}
    }, 8000);
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    /* O data-vidro="leve" é o perfil que o servidor manda, e o que fica de pé
       quando o script do <head> não roda: sem JS, com JS quebrado ou com o
       catch engolindo, o aparelho fica leve. O script troca o valor para
       "pesado" quando mede que dá. */
    <html
      lang="pt-BR"
      data-vidro="leve"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${orbitron.variable} ${geom.variable} ${roboto.variable} h-full antialiased`}
    >
    <head>
      {/* O data-vidro acima é reescrito aqui, antes do React montar. O <html>
          já tem suppressHydrationWarning, então o valor trocado não diverge. */}
      <script dangerouslySetInnerHTML={{ __html: ESCOLHER_VIDRO }} />
      {/* Diagnóstico temporário da WebView — remover depois da triagem.
          Inerte no site web (gated por hostname === "localhost"); no app,
          só aparece se o JS do bundle não rodar como esperado. */}
      <script dangerouslySetInnerHTML={{ __html: DIAGNOSTICO_WEBVIEW }} />
    </head>
    <body className="h-full">
      {children}
    </body>
    </html>
  );
}
