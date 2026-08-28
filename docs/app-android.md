# App Android no USPapo

## Estratégia: WebView apontando para o site remoto

O app é um wrapper fino do Capacitor 8 (`site/android/`): a WebView **não
embutiu o site** — ela carrega o site remoto através do `server.url` de
`site/capacitor.config.ts`. Essa é a **Estratégia B**: atualizar o app é
redeployar o site. Não há rebuild do wrapper, nem novo APK, nem fila de
revisão da Play Store para mudar a interface.

### Por que a Estratégia A foi rejeitada (`output: 'export'`)

A alternativa era exportar o site para estáticos e empacotá-los na WebView
(Estratégia A). O build com `output: 'export'` falhava com dois erros; os
dois estão **RESOLVIDOS** no site:

- **E87 em `/chat/[id]` — RESOLVIDO:** a conversa agora mora na query
  string (`/chat?id=<uuid>`). A rota é **estática** (`/chat`, não
  parametrizada) e o `id` é lido no client com `useSearchParams` dentro de
  uma fronteira de `<Suspense>` — exigência do build para `useSearchParams`
  numa página estática.
- **E558 nos route handlers — RESOLVIDO:** `cookies()` não existe num
  export estático, e nenhum dos dois a usa mais:
  - **`/auth/callback` é página client:** o `exchangeCodeForSession` roda
    no browser client (o route handler server e o client de servidor foram
    removidos). A sessão é gravada em cookie do próprio browser no origin
    do site (domínio `.turingusp.com` via `dominioCookie`, ver seção
    "Domínio").
  - **`/api/admin/analytics` autentica por header**
    `Authorization: Bearer <token>` validado server-side com
    `supabase.auth.getUser(token)`; as duas páginas admin mandam o token
    via `tokenDaSessao()`; a `ADMIN_API_KEY` segue restrita ao server-side.

O site não tem mais nenhum uso de `cookies()`/`next/headers` (o
`proxy.ts` lê os cookies do `Request` da requisição).

**`generateStaticParams` é inviável para a rota de chat:** o uuid é
cunhado no client (`novoId()`, `crypto.randomUUID()`), os dados são por
usuário (atrás de RLS do Supabase) e não há fonte enumerável em build para
listar os caminhos. No Next 16, um `generateStaticParams` retornando `[]` é
erro de build (`empty-generate-static-params`), e a doc oficial de static
exports orienta remover `output: 'export'` quando os caminhos não são
conhecíveis em build — por isso o padrão adotado é rota estática + query
string.

A Estratégia A **segue rejeitada**: restam estes bloqueios para habilitar
`output: 'export'`:

- **`proxy.ts`:** Proxy é feature **não suportada** em export (lista
  oficial de unsupported features do Next); a proteção de rotas migraria
  para o client.
- **`/api/admin/analytics`:** ainda é dinâmico — route handler que depende
  do `Request`; em export, só GET sem acesso ao request é prerenderável.
- **`next/image` com loader padrão:** o avatar remoto do Supabase
  (`remotePatterns` em `next.config.ts`) exigirá loader custom.

Resolver esses bloqueios é refatorar o **site**, não o app — fora do escopo
do wrapper.

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
- Migrar para export estático no futuro (Estratégia A): os dois erros
  originais de build estão **RESOLVIDOS** no site — **E87** com a rota
  estática `/chat?id=<uuid>` (lida no client com `useSearchParams` em
  fronteira de Suspense) e **E558** com `/auth/callback` como página client
  (`exchangeCodeForSession` do browser client, sessão em cookie do browser)
  e `/api/admin/analytics` sem `cookies()` (Bearer validado server-side).
  Restam `proxy.ts`, o handler dinâmico de analytics e `next/image` (loader
  padrão) — detalhes na seção "Por que a Estratégia A foi rejeitada". Até a
  resolução deles, o app segue na Estratégia B.
- **A sessão Supabase do app é isolada da do browser:** a WebView tem
  storage próprio, então o login feito no app não propaga para o browser
  (nem o contrário), mesmo no mesmo aparelho.
