#!/usr/bin/env node
// ─────────────────────────────────────────────
// Guard de env do build do app (Capacitor/Android) — fail-fast antes do
// `next build` do app (chamado pelo `npm run build:app`).
//
// Confere as três NEXT_PUBLIC_* que o app congela no bundle, com a mesma
// precedência do Next: shell > site/.env.local > site/.env (o .env pode não
// existir). Sai 1, listando TODAS as vars com problema, se qualquer uma
// estiver ausente, vazia ou placeholder (vvv, xxx, changeme, todo,
// placeholder) — e nas duas URLs exige https:// e proíbe localhost,
// 127.0.0.1 e 10.0.2.2. A key vale JWT (eyJ…) ou publishable
// (sb_publishable_…); a produção usa a publishable.
//
// Não checa NEXT_PUBLIC_COOKIE_DOMAIN de propósito: vazia é o valor certo do
// app, e o `build:app` já sai com ela vazia na linha de comando.
//
// Uso: node scripts/valida-env-app.mjs — Node >= 22, sem dependências.
// As funções de validação são puras e exportadas (teste com node -e).
// ─────────────────────────────────────────────
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** Variáveis conferidas pelo guard e o tipo de validação de cada uma. */
export const VARS_APP = [
  { name: 'NEXT_PUBLIC_SUPABASE_URL', kind: 'url' },
  { name: 'NEXT_PUBLIC_SUPABASE_ANON_KEY', kind: 'key' },
  { name: 'NEXT_PUBLIC_API_URL', kind: 'url' },
];

/** Hosts que só existem em dev — no aparelho são inalcançáveis. */
const HOSTS_PROIBIDOS = ['localhost', '127.0.0.1', '10.0.2.2'];

/**
 * Valor efetivo de `name` com a precedência do Next: shell > .env.local >
 * .env. A primeira fonte que DEFINE a chave ganha — inclusive com valor
 * vazio (vazio no shell quebra o build, igual no Next).
 *
 * @param {string} name nome da variável
 * @param {{ shell?: object, envLocal?: object, env?: object }} fontes
 * @returns {{ value: string, origem: 'shell'|'.env.local'|'.env'|'nenhuma' }}
 */
export function resolveVar(name, { shell = {}, envLocal = {}, env = {} } = {}) {
  const fontes = [
    ['shell', shell],
    ['.env.local', envLocal],
    ['.env', env],
  ];
  for (const [origem, fonte] of fontes) {
    if (Object.prototype.hasOwnProperty.call(fonte, name)) {
      const bruto = fonte[name];
      return { value: bruto == null ? '' : String(bruto).trim(), origem };
    }
  }
  return { value: '', origem: 'nenhuma' };
}

/**
 * Parser simples de arquivo .env: `KEY=VALUE`, aceita `export KEY=VALUE`,
 * valores entre aspas (simples ou duplas), comentários `#` e linhas em
 * branco.
 *
 * @param {string} content conteúdo do arquivo
 * @returns {Record<string, string>} mapa de chave → valor
 */
export function parseEnvFile(content) {
  const out = {};
  for (const line of String(content).split(/\r?\n/)) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let value = m[2].trim();
    if (
      (value.startsWith('"') && value.endsWith('"') && value.length >= 2) ||
      (value.startsWith("'") && value.endsWith("'") && value.length >= 2)
    ) {
      value = value.slice(1, -1);
    }
    out[m[1]] = value;
  }
  return out;
}

/** True se o valor é um placeholder de template, não um valor real. */
export function isPlaceholder(value) {
  const v = String(value).trim().toLowerCase().replace(/\.+$/, '');
  return (
    v === 'vvv' ||
    /^x{2,}$/.test(v) ||
    v === 'changeme' ||
    v === 'todo' ||
    v === 'placeholder'
  );
}

/**
 * Problemas de uma URL (lista vazia = ok): exige https://, proíbe os hosts
 * de dev (localhost, 127.0.0.1, 10.0.2.2).
 *
 * @returns {string[]}
 */
export function validateUrl(value) {
  const problemas = [];
  const s = String(value);
  if (!s.startsWith('https://')) problemas.push('não usa https://');
  let host = null;
  try {
    host = new URL(s).hostname;
  } catch {
    problemas.push('URL malformada');
    return problemas;
  }
  if (HOSTS_PROIBIDOS.includes(host)) {
    problemas.push(`aponta para host proibido: ${host}`);
  }
  return problemas;
}

/**
 * Problemas da key (lista vazia = ok): aceita JWT (eyJ…) ou publishable
 * (sb_publishable_…).
 *
 * @returns {string[]}
 */
export function validateKey(value) {
  const v = String(value);
  if (v.startsWith('eyJ') || v.startsWith('sb_publishable_')) return [];
  return ['key inválida: deve começar com eyJ (JWT) ou sb_publishable_ (publishable)'];
}

/**
 * Confere as três vars do app.
 *
 * @param {{ shell?: object, envLocal?: object, env?: object }} fontes
 * @returns {{ ok: boolean, resultados: Array<{ name: string, value: string, origem: string, problemas: string[] }> }}
 */
export function validateAppEnv({ shell = {}, envLocal = {}, env = {} } = {}) {
  const resultados = VARS_APP.map(({ name, kind }) => {
    const { value, origem } = resolveVar(name, { shell, envLocal, env });
    let problemas = [];
    if (origem === 'nenhuma') {
      problemas = ['ausente (shell, .env.local e .env)'];
    } else if (value === '') {
      problemas = [`vazia (definida vazia no ${origem})`];
    } else if (isPlaceholder(value)) {
      problemas = [`valor placeholder: ${value}`];
    } else if (kind === 'url') {
      problemas = validateUrl(value);
    } else {
      problemas = validateKey(value);
    }
    return { name, value, origem, problemas };
  });
  return { ok: resultados.every((r) => r.problemas.length === 0), resultados };
}

/** Mostra só começo e fim da key — o valor cheio não precisa ir para o log. */
export function maskKey(value) {
  const v = String(value);
  if (v.length <= 12) return '***';
  return `${v.slice(0, 10)}…${v.slice(-4)}`;
}

/** Lê um arquivo .env do site (inexistente → {}). */
function loadEnvFile(caminho) {
  if (!existsSync(caminho)) return {};
  return parseEnvFile(readFileSync(caminho, 'utf8'));
}

/** CLI: valida contra o shell real e os arquivos do site, sai 0 ou 1. */
function main() {
  const dirSite = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const { ok, resultados } = validateAppEnv({
    shell: process.env,
    envLocal: loadEnvFile(path.join(dirSite, '.env.local')),
    env: loadEnvFile(path.join(dirSite, '.env')),
  });

  if (ok) {
    console.log('✅ Env do app OK (valores efetivos, com origem):');
    for (const r of resultados) {
      const mostrado = r.name.endsWith('_ANON_KEY') ? maskKey(r.value) : r.value;
      console.log(`  ${r.name} = ${mostrado}  (origem: ${r.origem})`);
    }
    return 0;
  }

  console.error('❌ Env do app inválida — build do app bloqueado antes do next build.');
  for (const r of resultados) {
    if (r.problemas.length === 0) continue;
    const valor = r.origem === 'nenhuma' ? '(ausente)' : JSON.stringify(r.value);
    console.error(`\n  • ${r.name} = ${valor}  (origem: ${r.origem})`);
    for (const p of r.problemas) console.error(`      - ${p}`);
  }
  console.error(
    [
      '',
      'Correção: exporte as variáveis de produção no shell antes do build — os',
      'valores vigentes estão em site/.env.example, seção "Build do app',
      '(Capacitor/Android)":',
      '',
      '  export NEXT_PUBLIC_SUPABASE_URL=…',
      '  export NEXT_PUBLIC_SUPABASE_ANON_KEY=…',
      '  export NEXT_PUBLIC_API_URL=…',
      '',
      'O shell manda na frente do site/.env.local: com as três exportadas, o',
      'guard passa e o build segue.',
    ].join('\n'),
  );
  return 1;
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  process.exitCode = main();
}
