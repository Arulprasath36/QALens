import React from 'react';
import type { ComparisonMetrics } from '../../types';

// ─────────────────────────────────────────────────────────────
// Single metric card
// ─────────────────────────────────────────────────────────────

interface MetricCardProps {
  label:    string;
  valueA:   number | string;
  valueB:   number | string;
  labelA:   string;
  labelB:   string;
  format?:  'percent' | 'count';
  icon:     string;
  higher?:  'better' | 'worse'; // is a higher value better or worse?
}

function delta(a: number, b: number, higher: 'better' | 'worse'): 'better' | 'worse' | 'same' {
  if (a === b) return 'same';
  const aIsBetter = higher === 'worse' ? a < b : a > b;
  return aIsBetter ? 'better' : 'worse';
}

function fmt(val: number | string, format?: 'percent' | 'count'): string {
  if (typeof val !== 'number') return String(val);
  if (format === 'percent') return `${Math.round(val * 100)}%`;
  return String(val);
}

function ValueDisplay({
  value, format, side, higher,
  other,
}: {
  value:   number;
  format?: 'percent' | 'count';
  side:    'a' | 'b';
  higher:  'better' | 'worse';
  other:   number;
}) {
  const d = side === 'a' ? delta(value, other, higher) : delta(value, other, higher);

  const color =
    d === 'better' ? 'text-emerald-400' :
    d === 'worse'  ? 'text-red-400'     :
                     'text-zinc-300';

  const dot =
    d === 'better' ? '🟢' :
    d === 'worse'  ? '🔴' :
                     '⚪';

  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-2xl font-bold tabular-nums ${color}`}>
        {fmt(value, format)}
      </span>
      <span className="text-base">{dot}</span>
    </div>
  );
}

function MetricCard({ label, valueA, valueB, labelA, labelB, format, icon, higher = 'worse' }: MetricCardProps) {
  const numA = typeof valueA === 'number' ? valueA : 0;
  const numB = typeof valueB === 'number' ? valueB : 0;

  return (
    <div className="flex-1 min-w-[180px] bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3 hover:border-zinc-700 transition-colors duration-150">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-base">{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</span>
      </div>

      {/* A vs B */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-[10px] text-zinc-600 mb-1 truncate" title={labelA}>{labelA}</p>
          <ValueDisplay value={numA} format={format} side="a" higher={higher} other={numB} />
        </div>
        <div>
          <p className="text-[10px] text-zinc-600 mb-1 truncate" title={labelB}>{labelB}</p>
          <ValueDisplay value={numB} format={format} side="b" higher={higher} other={numA} />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Summary cards row
// ─────────────────────────────────────────────────────────────

interface ComparisonSummaryCardsProps {
  metricsA: ComparisonMetrics;
  metricsB: ComparisonMetrics;
}

export function ComparisonSummaryCards({ metricsA, metricsB }: ComparisonSummaryCardsProps) {
  const cards: MetricCardProps[] = [
    {
      label:   'Failure Rate',
      icon:    '📉',
      valueA:  metricsA.failureRate,
      valueB:  metricsB.failureRate,
      labelA:  metricsA.label,
      labelB:  metricsB.label,
      format:  'percent',
      higher:  'worse',
    },
    {
      label:   'Flaky Tests',
      icon:    '🌊',
      valueA:  metricsA.flakyCount,
      valueB:  metricsB.flakyCount,
      labelA:  metricsA.label,
      labelB:  metricsB.label,
      format:  'count',
      higher:  'worse',
    },
    {
      label:   'New Failures',
      icon:    '🔥',
      valueA:  metricsA.newFailures,
      valueB:  metricsB.newFailures,
      labelA:  metricsA.label,
      labelB:  metricsB.label,
      format:  'count',
      higher:  'worse',
    },
    {
      label:   'Fixed Tests',
      icon:    '✅',
      valueA:  metricsA.fixedTests,
      valueB:  metricsB.fixedTests,
      labelA:  metricsA.label,
      labelB:  metricsB.label,
      format:  'count',
      higher:  'better',
    },
    {
      label:   'Total Tests',
      icon:    '🧪',
      valueA:  metricsA.totalTests,
      valueB:  metricsB.totalTests,
      labelA:  metricsA.label,
      labelB:  metricsB.label,
      format:  'count',
      higher:  'better',
    },
  ];

  return (
    <div className="flex gap-3 flex-wrap">
      {cards.map(card => (
        <MetricCard key={card.label} {...card} />
      ))}
    </div>
  );
}
