/**
 * Configuração do Capacitor (wrapper Android do app web).
 *
 * DOMÍNIO DE PRODUÇÃO do app: https://uspapo.turingusp.com (verificado ao vivo).
 * O apex turingusp.com é o site principal do grupo Turing — NÃO usar para o app.
 */
import type { CapacitorConfig } from '@capacitor/cli';

// Dev: emulador Android → `next dev` rodando no host
// (10.0.2.2 = loopback do host a partir do emulador).
const defaultUrl = 'http://10.0.2.2:3000';
const url: string = process.env.CAPACITOR_URL ?? defaultUrl;

const config: CapacitorConfig = {
  appId: 'com.turingusp.uspapo',
  appName: 'USPapo',
  // webDir é placeholder — o conteúdo real vem do server.url
  // (com server.url definido, o WebView carrega da URL, não do webDir).
  webDir: 'public',
  server: {
    url,
    // https quando a URL começar com https, http caso contrário.
    androidScheme: url.startsWith('https') ? 'https' : 'http',
  },
};

export default config;
