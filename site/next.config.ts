import type { NextConfig } from "next";
import path from "path";

/* Build estático p/ o app (Capacitor, `npm run build:app`): NEXT_EXPORT=1 é
   lida no próprio build e troca a saída para o modo export — pasta `out/`
   com HTML/CSS/JS puros, sem servidor. Sem servidor não existe a Image
   Optimization API, então o <Image> renderiza <img> direto (unoptimized) e o
   `remotePatterns` fica dispensável junto: sem loader, nenhum host remoto é
   consultado. SEM a flag nada muda: a config de SSR segue intacta. */
const exportEstatico = process.env.NEXT_EXPORT === '1';

const nextConfig: NextConfig = {
  turbopack: {
    root: path.join(__dirname),
  },
  /* Testar mobile com cloudflare em dev */
  allowedDevOrigins: ["*.trycloudflare.com", "*.cfargotunnel.com"],
  images: exportEstatico
    ? { unoptimized: true }
    : {
        remotePatterns: [
          { protocol: 'https', hostname: 'zgvbnmovongrigjoviyu.supabase.co' },
        ],
      },
  /* `as const` porque o spread perde o contexto de tipos do NextConfig e o
     TS rebaixaria 'export' a string. */
  ...(exportEstatico ? { output: 'export' as const } : {}),
};

export default nextConfig;
