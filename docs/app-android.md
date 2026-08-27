# App Android no USPapo

## Estratégia: WebView apontando para o site remoto

O app é um wrapper fino do Capacitor 8 (`site/android/`): a WebView **não
embutiu o site** — ela carrega o site remoto através do `server.url` de
`site/capacitor.config.ts`. Essa é a **Estratégia B**: atualizar o app é
redeployar o site. Não há rebuild do wrapper, nem novo APK, nem fila de
revisão da Play Store para mudar a interface.

### Por que a Estratégia A foi rejeitada (`output: 'export'`)

A alternativa era exportar o site para estáticos e empacotá-los na WebView
(Estratégia A). Este fork do Next **falha o build com export**:

- **E87** em `/chat/[id]`: rota dinâmica sem `generateStaticParams`;
- **E558** nos route handlers `/auth/callback` e `/api/admin/analytics`: usam
  `cookies()`, que não existe num export estático.

Refatorar isso (parametrizar a rota de chat e tirar o callback de auth dos
route handlers) é refatorar o **site**, não o app — fora do escopo do
wrapper, e por isso a Estratégia A segue rejeitada.

## Domínio

A produção do app é `https://uspapo.turingusp.com` (verificado ao vivo).
Três travas sustentam essa escolha:

- o CORS do backend (`ORIGENS_CORS` em `backend/uspapo/config.py:115-116`)
  aceita exatamente esse subdomínio (e a variante `www`);
- o apex `turingusp.com` é o site público do grupo Turing — **não usar**
  para o app;
- o cookie de auth tem escopo `.turingusp.com`, o que cobre o subdomínio: a
  WebView enxerga o mesmo cookie de sessão que o site serve.

O script `app:sync:prod` grava essa URL no build
(`CAPACITOR_URL=https://uspapo.turingusp.com`); o dev aponta para o servidor
local (abaixo). A `androidScheme` é derivada no próprio `capacitor.config.ts`
(`https` só quando a URL começa com `https`).

## Pré-requisitos

- **Node ≥ 22** — a toolchain do Capacitor (`npx cap`) e o `next dev`.
- **JDK 21** — a toolchain é AGP 8.13/Gradle 8.14.3, e JDK mais novo que
  21 pode quebrar o `./gradlew` (o JDK 25 deste ambiente já foi visto
  quebrando o build).
- **Android SDK** — via `ANDROID_HOME`/`ANDROID_SDK_ROOT` ou `sdk.dir` em
  `site/android/local.properties` (arquivo gitignored, da máquina de cada um).
- Emulador (ou aparelho físico) com API ≥ 24 — `minSdkVersion 24`,
  `targetSdkVersion 36` em `site/android/variables.gradle`.

## Desenvolvimento

Tudo roda a partir de `site/`:

```bash
npm run dev          # next dev, porta 3000
npm run app:sync:dev # CAPACITOR_URL=http://10.0.2.2:3000 + cap sync android
npx cap run android  # compila, instala e abre; --live-reload recarrega o app
```

- **Emulador:** usa `10.0.2.2` — esse IP é o loopback do host visto do
  emulador, então o `next dev` da porta 3000 responde em `10.0.2.2:3000`.
  É o default do `capacitor.config.ts` e o que `app:sync:dev` fixa.
- **Aparelho físico:** o `10.0.2.2` não existe lá — usar o IP local da rede
  (mesmo Wi-Fi do host):
  `CAPACITOR_URL=http://<ip-do-host>:3000 npx cap sync android`.
- O `webDir` (`public`) é placeholder: com `server.url` definido, a WebView
  carrega da URL e ignora o conteúdo local.

## Release

### Keystore (uma vez só)

Gere **uma única vez** e guarde o arquivo — o app nunca mais pode assinar
com outro keystore, e o `.gitignore` já cobre `*.keystore`/`*.jks`
(seção "Capacitor / Android"). **Nunca commitar** o keystore nem as senhas:

```bash
keytool -genkey -v -keystore keystore/uspapo-release.keystore \
  -alias uspapo -keyalg RSA -keysize 4096 -validity 10000
```

### Configuração

Configurar o `android.buildOptions` em `site/capacitor.config.ts`:

```ts
android: {
  buildOptions: {
    keystorePath: 'keystore/uspapo-release.keystore',
    keystorePassword: '<senha-do-keystore>',
    keystoreAlias: 'uspapo',
    keystoreAliasPassword: '<senha-do-alias>',
    releaseType: 'aab',      // 'apk' para side-load
    signingType: 'apksigner',
  },
},
```

### Build

A partir de `site/android/`:

```bash
./gradlew assembleRelease  # APK assinado (side-load)
./gradlew bundleRelease    # AAB assinado (Play Store)
```

Antes de cada release:

1. `npm run app:sync:prod` — grava a URL de produção no build;
2. **bump do `versionCode`** (e do `versionName`, se fizer sentido) em
   `site/android/app/build.gradle` — começa em `1`/`"1.0.0"`; a Play Store
   exige um `versionCode` maior que o da versão anterior.

## Limitações

- **O app exige rede para o servidor.** É um wrapper, não um app offline:
  se o site cair, a WebView cai junto (tela vazia, sem conteúdo local de
  fallback).
- A doc oficial do Capacitor sinaliza `server.url` como **não recomendado
  para produção** — o padrão recomendado é conteúdo local + refresh
  versionado. Trade-off aceito para o scaffold: com conteúdo remoto, a
  atualização deixa de ser um release de app e vira um redeploy do site.
- Migrar para export estático no futuro (Estratégia A) exige primeiro
  refatorar `/chat/[id]` (`generateStaticParams`) e os route handlers
  `/auth/callback` e `/api/admin/analytics` (sem `cookies()`); até lá o app
  segue na Estratégia B.
- **A sessão Supabase do app é isolada da do browser:** a WebView tem
  storage próprio, então o login feito no app não propaga para o browser
  (nem o contrário), mesmo no mesmo aparelho.
