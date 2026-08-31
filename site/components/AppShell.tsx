"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";

import { useJanelaVisual } from "@/lib/janela";
import { useSessao } from "@/lib/useSessao";

/* Casca de altura fixa: o documento não rola, o scroll acontece dentro do
   .app-scroll de cada página.

   O fundo mora aqui, e não no <body>, para dividir a mesma caixa com as
   camadas dissolvidas (page-fade-b / page-fade-t) que as páginas renderizam
   como irmãs — é o que garante o alinhamento em qualquer navegador. */
export default function AppShell({ children }: { children: React.ReactNode }) {
  useJanelaVisual();

  return (
    <div className="app-shell">
      <div aria-hidden className="page-backdrop" />
      {/* useSearchParams em rota estática exige a fronteira de Suspense
          (o build falha sem ela) — mesmo padrão das páginas de login e do
          callback de auth. */}
      <Suspense fallback={<EsqueletoSessao />}>
        <PortariaSessao>{children}</PortariaSessao>
      </Suspense>
    </div>
  );
}

/* Portaria de sessão: a casca do app só abre com o usuário decidido.

   É o guard que ocupava o antigo proxy.ts (o middleware), removido porque o
   Proxy não existe no export estático, que é como o site é servido. A checagem
   continua OTIMISTA, como era: quem decide de verdade quem pode perguntar é o
   backend, que confere a assinatura do token no /chat (uspapo/contas.py) e a
   whitelist (uspapo/acesso.py). Isto aqui só evita montar uma tela que não
   vai funcionar.

   Enquanto a sessão não decide, ou quando ela diz "não", a casca entrega o
   esqueleto em vez da página: um guard que só redirecionaria depois do
   useEffect deixaria o aluno deslogado ver a interface do chat montar
   inteira. O deep-link ?id=... segue vivo no ?destino= para o login devolver. */
function PortariaSessao({ children }: { children: React.ReactNode }) {
  const { usuario, carregando, falha, tentarNovamente } = useSessao();
  const router = useRouter();
  const caminho = usePathname();
  const busca = useSearchParams().toString();

  useEffect(() => {
    /* Com `falha` o esqueleto vira diagnóstico (mensagem + retry): o
       redirect para /login apagaria a tela de erro antes de ela ser lida,
       e o retry nunca seria alcançável. Sem falha, o deslogado segue para
       o login como antes. */
    if (carregando || usuario || falha) return;

    /* destino = caminho + query, codificado: com o id da conversa na query
       (?id=<uuid>, Estratégia A), colar a string crua faria o ? virar o
       delimitador da query do próprio /login e o deep-link morreria no
       round-trip — o proxy antigo usava searchParams.set, que codifica. */
    const destino = busca ? `${caminho}?${busca}` : caminho;
    router.replace(`/login?destino=${encodeURIComponent(destino)}`);
  }, [carregando, usuario, falha, caminho, busca, router]);

  if (carregando || !usuario)
    return <EsqueletoSessao falha={falha} aoTentarNovamente={tentarNovamente} />;

  return <>{children}</>;
}

/* O que a casca entrega até a sessão decidir: um pulso neutro no centro, no
   lugar de montar a página de verdade.

   Com `falha`, o pulso vira diagnóstico: a mensagem curta do erro (ex.:
   "Failed to fetch" ou o timeout de 15s) e um retry — antes a falha do
   getUser() era invisível e a bola pulsava para sempre no app. O fallback do
   Suspense usa o componente sem props (roda fora do hook): skeleton simples. */
function EsqueletoSessao({ falha, aoTentarNovamente }: { falha?: string | null; aoTentarNovamente?: () => void }) {
  /* Marca temporária de triagem da WebView — remover depois: o efeito só
     roda se o JavaScript do bundle executou, então o texto abaixo da bola
     é a prova direta de que o JS está vivo no app. */
  const [jsAtivo, setJsAtivo] = useState(false);
  useEffect(() => {
    setJsAtivo(true);
  }, []);

  return (
    <div aria-hidden={!falha} className="flex h-full w-full items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-9 w-9 animate-pulse rounded-full bg-line/30" />
        {jsAtivo && (
          <p aria-hidden className="text-[10px] uppercase tracking-wide text-muted-foreground/60">js ativo</p>
        )}
        {falha && (
          <>
            <p role="alert" className="max-w-xs text-center text-xs text-muted-foreground">
              {falha}
            </p>
            {/* Mesma gramática do botão secundário do login (surface-raised +
                borda line/15), em tamanho small. */}
            <button
              type="button"
              onClick={aoTentarNovamente}
              className="cursor-pointer rounded-full border border-line/15 bg-surface-raised px-4 py-1.5 text-xs font-medium text-foreground transition-colors duration-200 hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
            >
              Tentar novamente
            </button>
          </>
        )}
      </div>
    </div>
  );
}
