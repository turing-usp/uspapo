# App Android no USPapo

## Estratégia: site estático embutido (Estratégia A)

O app é um wrapper fino do Capacitor 8 (`site/android/`): a WebView **embutiu
o site** — ela carrega o export estático do próprio APK. `webDir: 'out'` em
`site/capacitor.config.ts` aponta para a pasta `out/`, gerada pelo
`npm run build:app`, que liga `NEXT_EXPORT=1` na `site/next.config.ts`
(`output: 'export'` + `images: { unoptimized: true }`; sem a flag, a config
SSR segue intacta). Essa é a **Estratégia A**, adotada: atualizar a
interface agora exige **novo APK** — rebuild estático, sync e build Android
assinado (seção "Release"). Redeploy do site **não** atualiza o app.

O desenvolvimento continua via `server.url` (live-reload, seção
"Desenvolvimento"). O trade-off documentado antes continua valendo: a doc
oficial do Capacitor sinaliza `server.url` como **não recomendada para
produção** — o dev aceita isso por causa do live-reload. Na produção o
conteúdo segue o padrão recomendado: o `out/` estático embutido no APK
(`webDir: 'out'`). O fallback que derivava `server.url` de
`http://10.0.2.2:3000` quando `CAPACITOR_URL` estava ausente foi
**removido** no commit `69168e6`:
`server.url` só entra no config quando `CAPACITOR_URL` está definido
(`app:sync:dev` define; `app:sync:prod` **não** define), e o sync de
produção grava `server: {}` (confirmado no `capacitor.config.json`
sincronizado em `site/android/app/src/main/assets/`). Com a chave ausente a
WebView carrega o `webDir` embutido — o conteúdo que o release distribui.

### Por que a Estratégia A foi rejeitada — e como os bloqueios foram resolvidos

A alternativa era exportar o site para estáticos e empacotá-los na WebView
(Estratégia A). O build com `output: 'export'` falhava; os dois erros
originais foram **RESOLVIDOS** no ciclo anterior, e os três bloqueios que
mantinham a rejeição caíram neste ciclo — a Estratégia A é a adotada
(seção "Estratégia"):

- **E87 em `/chat/[id]` — RESOLVIDO:** a conversa agora mora na query
  string (`/chat?id=<uuid>`). A rota é **estática** (`/chat`, não
  parametrizada) e o `id` é lido no client com `useSearchParams` dentro de
  uma fronteira de `<Suspense>` — exigência do build para `useSearchParams`
  numa página estática.
- **E558 nos route handlers — RESOLVIDO:** `cookies()` não existe num
  export estático, e nenhum handler a usa mais:
  - **`/auth/callback` é página client:** o `exchangeCodeForSession` roda
    no browser client (o route handler server e o client de servidor foram
    removidos). A sessão é gravada em cookie do próprio browser no origin
    do site (domínio por build, ver seção "Domínio").
  - **`/api/admin/analytics` autentica por header**
    `Authorization: Bearer <token>` validado server-side com
    `supabase.auth.getUser(token)`; as duas páginas admin mandam o token
    via `tokenDaSessao()`; a `ADMIN_API_KEY` segue restrita ao server-side.

O site não tem mais nenhum uso de `cookies()`/`next/headers` (o
`proxy.ts`, que os lia do `Request` da requisição, foi removido).

**`generateStaticParams` é inviável para a rota de chat:** o uuid é
cunhado no client (`novoId()`, `crypto.randomUUID()`), os dados são por
usuário (atrás de RLS do Supabase) e não há fonte enumerável em build para
listar os caminhos. No Next 16, um `generateStaticParams` retornando `[]` é
erro de build (`empty-generate-static-params`), e a doc oficial de static
exports orienta remover `output: 'export'` quando os caminhos não são
conhecíveis em build — por isso o padrão adotado é rota estática + query
string.

Os três bloqueios que mantinham a rejeição, **RESOLVIDOS** neste ciclo:

- **`proxy.ts` removido — guard no client:** Proxy (middleware) é feature
  **não suportada** em export (lista oficial de unsupported features do
  Next). A proteção de rotas migrou para o client: o `AppShell`
  (`site/components/AppShell.tsx`) tem a portaria de sessão — `useSessao`,
  e enquanto a sessão não decide (ou não há usuário) a casca entrega um
  esqueleto e manda para `/login?destino=<caminho+query>`; o `/login`
  (`site/app/(auth)/login/page.tsx`) tem o efeito "já logado → `/`". A
  checagem segue **OTIMISTA**: quem decide de verdade quem pode perguntar
  é o backend (assinatura do token no `/chat` e a whitelist). Consequência
  prática: o **deploy web precisa de redeploy para herdar o guard** (o
  `proxy.ts` saiu do código; o deploy atual ainda roda o antigo).
  Deep-links preservam `?id=` via o `?destino=` codificado — o mesmo
  round-trip do proxy antigo.
- **`/api/admin/analytics` estático no export:** a rota declara
  `revalidate = false` e, quando `NEXT_EXPORT === '1'`, devolve um **404
  estático antes de tocar no `Request`** (totalmente estático, sem
  surpresa no prerender). **Limitação: o analytics admin é indisponível no
  app** (as telas admin tratam a resposta como erro). Sem a flag, no modo
  SSR (deploy web), a rota segue dinâmica e inalterada.
- **`next/image` no export:** com a flag, a `site/next.config.ts` liga
  `images: { unoptimized: true }` — sem servidor não existe a Image
  Optimization API, o `<Image>` renderiza `<img>` direto e o
  `remotePatterns` fica dispensável (nenhum host remoto é consultado). Sem
  a flag, a config SSR (com `remotePatterns`) segue intacta.

## Domínio

Duas origens, e o cookie é decidido **por build** (`dominioCookie`, em
`site/lib/supabase.ts`):

- **Deploy web:** `https://uspapo.turingusp.com` (verificado ao vivo). O
  apex `turingusp.com` é o site público do grupo Turing — **não usar** para
  o app. Sem variável, em produção o cookie tem escopo `.turingusp.com`,
  cobrindo o subdomínio.
- **App embutido:** a WebView nasce em `https://localhost` (o Capacitor 8
  aponta o `androidScheme` para `https`; em modo debug/cleartext ela
  aparece em `http://localhost`). O CORS do backend (`ORIGENS_CORS`, em
  `backend/uspapo/config.py`) aceita o subdomínio do deploy (e a variante
  `www`) e, para a WebView embutida, também `https://localhost` e
  `http://localhost`. O `build:app` define `NEXT_PUBLIC_COOKIE_DOMAIN=`
  (string vazia): o check é `!== undefined`, então o vazio é valor legítimo
  e vira cookie **host-only em `localhost`** (nenhum domínio de subdomínio
  se aplica a uma origem local).

## Pré-requisitos

- **Node ≥ 22** — a toolchain do Capacitor (`npx cap`) e o `next dev`.
- **JDK 21** — a toolchain é AGP 8.13/Gradle 8.14.3, e JDK mais novo que
  21 quebra o `./gradlew` (o JDK 25 deste ambiente já foi visto quebrando
  o build). O Gradle roda com `JAVA_HOME` apontando para a JDK 21
  (seção "Release").
- **Android SDK** — via `ANDROID_HOME`/`ANDROID_SDK_ROOT` ou `sdk.dir` em
  `site/android/local.properties` (arquivo gitignored, da máquina de cada um).
- Emulador (ou aparelho físico) com API ≥ 24 — `minSdkVersion 24`,
  `targetSdkVersion 36` em `site/android/variables.gradle`.
- **Dashboard do Supabase (externo):** cadastrar
  `https://localhost/auth/callback` como redirect URL — o callback do OAuth
  do app embutido roda nessa origem. O redirect do deploy web continua
  válido; até o cadastro, o OAuth no app não volta ao callback.

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
- O `webDir` é `out` — o conteúdo de produção do app: em dev, com
  `server.url` definido, a WebView carrega da URL e ignora o conteúdo
  local; o `out/` embutido é o que a release distribui (seção "Release").

## Release

### Keystore (uma vez só)

O keystore mora em `site/keystore/uspapo-release.keystore`, é **gitignored**
(`*.keystore`/`*.jks` na seção "Capacitor / Android" do `.gitignore`) e o
app nunca mais pode assinar com outro — **nunca commitar** o arquivo. As
senhas ficam declaradas em **dois** lugares versionados, com o mesmo valor
por design da doc do projeto: o `android.buildOptions` de
`site/capacitor.config.ts` (lido pelo `cap build android`/Capacitor Cloud) e
o `signingConfigs.release` de `site/android/app/build.gradle` (lido pelo
Gradle, que assina o APK e o AAB na hora do build — o CLI do Capacitor 8
não assina AAB: ele invoca `apksigner`, que não suporta o formato de
bundle).

```bash
keytool -genkey -v -keystore keystore/uspapo-release.keystore \
  -alias uspapo -keyalg RSA -keysize 4096 -validity 10000
```

### Configuração

Já configurado no `android.buildOptions` de `site/capacitor.config.ts`
(keystore em `site/keystore/`, alias `uspapo`):

```ts
android: {
  buildOptions: {
    releaseType: 'AAB',       // 'apk' para side-load
    signingType: 'apksigner',
    keystorePath: '../keystore/uspapo-release.keystore', // relativo a android/
    keystoreAlias: 'uspapo',
    keystorePassword,         // por design da doc, no config
    keystoreAliasPassword,    // PKCS12: igual à do store
  },
},
```

### Build

O app embute as `NEXT_PUBLIC_*` no bundle em build — o release só fica
correto com as **vars de produção** exportadas no shell antes do
`app:sync:prod`:

```bash
export NEXT_PUBLIC_SUPABASE_URL=https://zgvbnmovongrigjoviyu.supabase.co
export NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_ZYlNqNjeRpqRV6pkKzta7A_6QjfYcl2
export NEXT_PUBLIC_API_URL=https://uspapo-53zh.onrender.com
```

A anon key `sb_publishable_…` é pública por design (RLS protege os dados)
— ok embuti-la no bundle. **Como obtê-las:** o deploy web
(`https://uspapo.turingusp.com`) embute as mesmas vars no bundle público —
abrir o site no navegador e procurar os três valores nos JS da página
(devtools → Fontes/Rede) entrega o ambiente de produção; os valores
correspondentes ficam documentados em `site/.env.example` (seção "Build do
app").

**Guard de env (fail-fast):** o `build:app` roda `node
scripts/valida-env-app.mjs` antes do `next build` e **falha** (exit 1, com
a variável, a origem do valor ruim e a correção) se qualquer uma das três
estiver ausente, vazia, placeholder (`vvv`, `xxx…`, `changeme`, `todo`,
`placeholder`) ou — nas duas URLs — não-`https://` ou apontando para
`localhost`/`127.0.0.1`/`10.0.2.2`. Sem exportar as vars de produção (ou
com as de dev no `.env`), o build do app não roda. A chave aceita JWT
(`eyJ…`) ou publishable (`sb_publishable_…`); `NEXT_PUBLIC_COOKIE_DOMAIN`
não é checada — vazia é o valor certo do app. Precedência dos valores:
shell > `site/.env.local` > `site/.env`.

Fluxo de release, a partir de `site/` (com as vars acima no shell):

```bash
npm run build:app      # node scripts/valida-env-app.mjs + NEXT_EXPORT=1 NEXT_PUBLIC_COOKIE_DOMAIN= next build → out/
npm run app:sync:prod  # roda o build:app e faz cap sync android (copia out/ p/ os assets)
cd android
JAVA_HOME=<...>/toolchain/jdk21 ./gradlew assembleRelease bundleRelease
# saem assinados: app-release.apk (apk/release/) e app-release.aab (bundle/release/)
# nomes canônicos para distribuição (o fluxo anterior usava app-release-signed.*):
mv app/build/outputs/apk/release/app-release.apk app/build/outputs/apk/release/app-release-signed.apk
mv app/build/outputs/bundle/release/app-release.aab app/build/outputs/bundle/release/app-release-signed.aab
```

- **JDK 21 é obrigatória** via `JAVA_HOME` — o JDK 25 quebra o `./gradlew`.
- **Assinatura:** o `signingConfigs.release` do `site/android/app/build.gradle`
  assina no Gradle (v1 no AAB; v1+v2+v3 no APK). Para o rollout de instalação
  rápida da Play, passar o APK final pelo `apksigner sign` (gera o `.idsig`
  v4) — `apksigner` do build-tools da SDK, `--ks-key-alias uspapo`.
- **AAB** para a Play Store, **APK** para side-load. (O `cap build android`
  não é usado: o APK dele espera a saída `-unsigned` do Gradle, que não
  existe com o `signingConfig` configurado, e o AAB dele falha porque o
  `apksigner` não assina bundle.)
- Versão: o versionName é 0.0.1 (placeholder) e o versionCode fica em 2 —
  o projeto não faz bump a cada release; o APK novo instala por cima do
  1.0.0/1.0.1 já no aparelho sem desinstalar. Se a 1.0.0 (versionCode 1,
  env de dev) for publicada na Play Store, o primeiro upload exigirá um
  versionCode maior que o dela.

## Limitações

- **Atualizar o app exige novo APK** (Estratégia A): a interface embutida só
  muda com o fluxo de release — redeploy do site não atualiza o app.
- **A 1.0.0 (versionCode 1) saiu com env de dev embutida — NÃO
  distribuir:** o build da 1.0.0 rodou sem as vars de produção, então o
  bundle embutido aponta para `127.0.0.1:54321` (Supabase dev) e
  `localhost:5000` (API dev) — inalcançáveis no aparelho: o app não
  carrega e não funciona. O build **0.0.1 (versionCode 2)** sai com env
  de produção embutida (seção "Release"); a distribuição é dele. A 1.0.0
  instalada em aparelho só é corrigida por esse novo build — redeploy web
  não atualiza o app.
- **Analytics admin indisponível no app:** no export a rota
  `/api/admin/analytics` devolve 404 estático e as telas admin tratam a
  resposta como indisponível; no deploy web a rota segue dinâmica.
- **O app não é offline:** a interface é embutida (se o deploy web cair, a
  UI carrega do APK), mas sessão, chat e dados passam por Supabase/backend —
  sem rede o app carrega e não funciona.
- **OAuth no app depende de cadastro externo:**
  `https://localhost/auth/callback` precisa estar como redirect URL no
  dashboard do Supabase (seção "Pré-requisitos"); até lá, o OAuth no app
  não volta ao callback. O redirect do deploy web continua válido.
- **O deploy web precisa de redeploy para herdar o guard de sessão no
  client** — o `proxy.ts` foi removido (detalhes na seção "Por que a
  Estratégia A foi rejeitada"); o backend segue sendo a autoridade real.
- **A sessão Supabase do app é isolada da do browser:** a WebView tem
  storage próprio, então o login feito no app não propaga para o browser
  (nem o contrário), mesmo no mesmo aparelho.
