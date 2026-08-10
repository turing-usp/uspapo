'use client';

import React from 'react';

/* Peças compartilhadas do painel de analytics. Moraram dentro do page.tsx até
   a seção de feedback chegar; com ela o arquivo passaria de mil linhas, e o
   RevisaoFeedback precisa das mesmas cores, do mesmo tooltip e do mesmo card
   que os gráficos ao lado, se cada um trouxesse os seus, a tela deixaria de
   ser uma coisa só. */

/** Ordem fixa. Um sétimo modelo vira "Outros", não uma cor gerada. */
export const CORES_SERIE = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
];
export const MAX_FATIAS = CORES_SERIE.length;

/* Polaridade, e não identidade: aqui a cor não diz *quem* é a série, diz se o
   que ela conta é bom ou ruim. Por isso sai da paleta de slots, o laranja da
   marca, que o FeedbackBot usa no joinha, é o mesmo --chart-1 das perguntas no
   gráfico vizinho, e um "útil" pintado dele leria como mais uma entidade. O
   --danger para o lado negativo já é como o painel marca taxa de erro. */
export const COR_POSITIVO = 'var(--chart-3)';
export const COR_NEGATIVO = 'var(--danger)';

export const EIXO = {
  stroke: 'var(--muted-foreground)',
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

/**
 * Número curto para eixo e card.
 *
 * Em pt-BR o ponto é separador de milhar, então o "12.3k" que estava aqui antes
 * se lia como doze mil e trezentos bem ao lado de um tooltip escrevendo
 * "12.345", dois números diferentes para o mesmo valor. A notação compacta do
 * Intl resolve na própria língua: "12,3 mil", "1,2 mi".
 */
const COMPACTO = new Intl.NumberFormat('pt-BR', {
  notation: 'compact',
  maximumFractionDigits: 1,
});
export const formatNumber = (num: number = 0) =>
  num >= 1000 ? COMPACTO.format(num) : num.toLocaleString('pt-BR');

/** Rótulo curto no eixo: "2026-08-09" ocuparia a largura de três dias. */
export const rotuloDia = (iso: string) => {
  const partes = String(iso).split('-');
  return partes.length === 3 ? `${partes[2]}/${partes[1]}` : iso;
};

/** O painel nunca mostra o id inteiro: para ler a tela, o prefixo basta. */
export const formatUserId = (id: string) => {
  if (!id || id === 'anonymo' || id === 'anonimo') return 'Usuário Anônimo';
  if (id.length > 12) return `${id.substring(0, 6)}...${id.substring(id.length - 4)}`;
  return id;
};

export type ItemTooltip = {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
};

/**
 * Tooltip de vidro.
 *
 * O `contentStyle` do recharts é style inline e não alcança pseudo-elemento,
 * então não há como fazer a lâmina por ali: o jeito de o tooltip ser vidro de
 * verdade é substituir o conteúdo inteiro.
 *
 * O texto usa tinta de texto, nunca a cor da série — quem carrega a identidade
 * é o ponto ao lado do rótulo.
 */
export function TooltipGlass({
  active,
  payload,
  label,
  sufixo = '',
}: {
  active?: boolean;
  payload?: ItemTooltip[];
  label?: string | number;
  sufixo?: string;
}) {
  if (!active || !payload?.length) return null;

  return (
    <div className="glass rounded-xl px-3 py-2 font-roboto text-xs">
      <p className="text-muted-foreground mb-1.5">{rotuloDia(String(label))}</p>
      <div className="space-y-1">
        {payload.map((item, i) => (
          <div key={`${item.dataKey ?? i}`} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: item.color }}
              />
              {item.name}
            </span>
            <span className="font-mono text-foreground">
              {typeof item.value === 'number' ? item.value.toLocaleString('pt-BR') : item.value}
              {sufixo}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function LegendaGlass({ payload }: { payload?: ItemTooltip[] }) {
  if (!payload?.length) return null;
  return (
    <div className="flex flex-wrap items-center justify-center gap-4 pt-2 font-roboto text-xs">
      {payload.map((item, i) => (
        <span key={`${item.dataKey ?? i}`} className="flex items-center gap-1.5 text-muted-foreground">
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: item.color }}
          />
          {item.value}
        </span>
      ))}
    </div>
  );
}

export function CardGrafico({
  titulo,
  descricao,
  icone,
  className = '',
  children,
}: {
  titulo: string;
  descricao?: string;
  icone: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`glass rounded-2xl p-6 space-y-4 ${className}`}>
      <div>
        <h2 className="flex items-center gap-2 font-roboto text-base font-semibold text-foreground">
          {icone}
          {titulo}
        </h2>
        {descricao && <p className="font-roboto text-xs text-muted-foreground">{descricao}</p>}
      </div>
      {children}
    </div>
  );
}

export function Vazio({ carregando, mensagem }: { carregando: boolean; mensagem: string }) {
  return (
    <div className="flex h-full items-center justify-center font-roboto text-xs text-muted-foreground">
      {carregando ? 'Carregando...' : mensagem}
    </div>
  );
}
