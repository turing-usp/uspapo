/**
 * Configuração do Capacitor (wrapper Android do app web).
 *
 * DOMÍNIO DE PRODUÇÃO do app: https://uspapo.turingusp.com (verificado ao vivo).
 * O apex turingusp.com é o site principal do grupo Turing — NÃO usar para o app.
 *
 * Estratégia A — site embutido: o release distribui o export estático
 * (`out/`, gerado com `npm run build:app`) dentro do app, sem depender de
 * servidor. `server.url`/`androidScheme` abaixo servem apenas para dev
 * live-reload (`next dev`); o Capacitor 8 documenta `server.url` como
 * não-indicada para produção.
 */
import type { CapacitorConfig } from '@capacitor/cli';

// Dev: emulador Android → `next dev` rodando no host
// (10.0.2.2 = loopback do host a partir do emulador). O valor só entra quando
// `CAPACITOR_URL` é definido (`app:sync:dev` define; `app:sync:prod` NÃO).
// Com `server.url` ausente o Capacitor usa o `webDir` embutido (Estratégia A).
// Nunca deixe um fallback de dev aqui: com `server.url` presente a WebView
// carrega a URL EM VEZ do webDir, e `10.0.2.2` não existe fora do emulador.
const url: string | undefined = process.env.CAPACITOR_URL;

// Assinatura do release: o keystore é artefato local, gitignored
// (`*.keystore` no .gitignore da raiz) e NUNCA vai ao git. As senhas são
// geradas com `openssl rand -base64 24` e ficam no config por design da doc
// do projeto (o `cap build android` e o Capacitor Cloud as lê daqui).
const keystorePassword = 'mlDkwrCOf13fYmnPtrWx3NrjWJlR4RrA';
// PKCS12 unifica storepass/keypass (restrição do formato; o keytool avisa e
// ignora `-keypass` distinto): a senha do alias é a do store.
const keystoreAliasPassword = keystorePassword;

const config: CapacitorConfig = {
  appId: 'com.turingusp.uspapo',
  appName: 'USPapo',
  // Estratégia A — site embutido: o export estático vai dentro do app.
  webDir: 'out',
  server: {
    // Só preenchido com `CAPACITOR_URL` (dev live-reload). No sync de produção
    // a chave fica ausente: com `server.url` definido a WebView ignora o
    // `webDir` embutido e tenta carregar a URL (que falharia em aparelho
    // físico).
    ...(url
      ? {
          url,
          // https quando a URL começar com https, http caso contrário.
          // (Só relevante em dev live-reload; release usa o webDir embutido.)
          androidScheme: url.startsWith('https') ? 'https' : 'http',
        }
      : {}),
  },
  android: {
    buildOptions: {
      releaseType: 'AAB',
      signingType: 'apksigner',
      // O CLI resolve `keystorePath` relativo a `android/` (cwd do apksigner
      // local), então `../keystore/...` aponta para `site/keystore/`.
      keystorePath: '../keystore/uspapo-release.keystore',
      keystoreAlias: 'uspapo',
      keystorePassword,
      keystoreAliasPassword,
    },
  },
};

export default config;
