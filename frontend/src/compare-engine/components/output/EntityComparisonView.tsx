import { useState, useEffect } from 'react';
import { Dropdown } from '../../../components/Dropdown';
import { Tooltip } from '../../../components/Tooltip';
import type { ApiEntityCompareResult, ApiEntityCompareRow, ApiEntityMetrics } from '../../hooks/useCompareData';

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function pct(r: number) {
  return `${Math.round(r * 100)}%`;
}

function classifyRow(row: ApiEntityCompareRow): 'stable' | 'flaky' | 'failing' {
  const statuses = row.run_history.map(p => p.status).filter(s => s !== 'absent');
  if (statuses.length === 0) return 'stable';
  const hasFail = statuses.some(s => s === 'failed' || s === 'broken');
  const hasPass = statuses.some(s => s === 'passed');
  if (hasFail && hasPass) return 'flaky';
  if (hasFail) return 'failing';
  return 'stable';
}

function failCount(row: ApiEntityCompareRow) {
  return row.run_history.filter(p => p.status === 'failed' || p.status === 'broken').length;
}

// Window pass/fail rates — computed from run_history across all rows and all runs.
// More accurate than metrics.pass_rate / failure_rate which are latest-run only.
function windowRates(rows: ApiEntityCompareRow[]): { passRate: number; failRate: number } {
  let passed = 0;
  let failed = 0;
  let total  = 0;
  for (const row of rows) {
    for (const pt of row.run_history) {
      if (pt.status === 'absent') continue;
      total++;
      if (pt.status === 'passed') passed++;
      else if (pt.status === 'failed' || pt.status === 'broken') failed++;
    }
  }
  if (total === 0) return { passRate: 0, failRate: 0 };
  return { passRate: passed / total, failRate: failed / total };
}

// Trend: compare status_b (baseline) vs status_a (latest) per test in this entity's rows
function computeTrend(rows: ApiEntityCompareRow[]): { direction: 'up' | 'down' | 'flat'; improved: number; regressed: number } {
  let improved = 0;
  let regressed = 0;
  for (const r of rows) {
    const wasGood = r.status_b === 'passed';
    const isGood  = r.status_a === 'passed';
    if (!wasGood && isGood)  improved++;
    if (wasGood  && !isGood) regressed++;
  }
  const net = improved - regressed;
  return {
    direction: net > 0 ? 'up' : net < 0 ? 'down' : 'flat',
    improved,
    regressed,
  };
}

// Build a ranked list of entities sorted by composite health score
// Score = pass_rate (60%) - failure_rate (20%) - new_failures_norm (20%)
interface RankedEntity {
  label:        string;
  metrics:      ApiEntityMetrics;
  rows:         ApiEntityCompareRow[];
  rank:         number;   // 1 = best
  score:        number;
  winPassRate:  number;   // window pass rate (passes / non-absent across all runs)
  winFailRate:  number;   // window fail rate (consistent denominator)
}

function rankEntities(data: ApiEntityCompareResult): RankedEntity[] {
  const entities = [
    { label: data.label_a, metrics: data.metrics_a, rows: data.rows.filter(r => (r.owner ?? r.suite_name) === data.label_a) },
    { label: data.label_b, metrics: data.metrics_b, rows: data.rows.filter(r => (r.owner ?? r.suite_name) === data.label_b) },
    ...(data.metrics_c ? [{ label: data.label_c!, metrics: data.metrics_c, rows: data.rows.filter(r => (r.owner ?? r.suite_name) === data.label_c) }] : []),
  ];

  const maxTests = Math.max(...entities.map(e => e.metrics.total_tests), 1);

  return entities
    .map(e => {
      const { passRate: winPR, failRate: winFR } = windowRates(e.rows);
      return {
        ...e,
        winPassRate: winPR,
        winFailRate: winFR,
        // All four terms now use the same window-based denominator — no mixing of
        // latest-run and window metrics which caused wrong rankings.
        score: winPR * 0.6
             - winFR  * 0.2
             - (e.metrics.new_failures / maxTests) * 0.1
             - (e.metrics.flaky_count  / maxTests) * 0.1,
        rank: 0,
      };
    })
    .sort((a, b) => b.score - a.score)
    .map((e, i) => ({ ...e, rank: i + 1 }));
}

// ─────────────────────────────────────────────────────────────
// 1. Verdict + Narrative
// ─────────────────────────────────────────────────────────────

// Which category of evidence a reason bullet drills into
type DrillType = 'pass_rate' | 'flaky' | 'regressions' | 'failures';

// Per-entity classification based on window metrics
// Hierarchy: Regressing → Flaky → Stable
// "Flaky" requires meaningful instability — a high pass rate with 1–2 flaky tests is still Stable.
function classifyEntity(e: RankedEntity): { label: string; tone: string; bg: string; border: string } {
  const { winPassRate, winFailRate, metrics } = e;
  const trend = computeTrend(e.rows);

  // Regressing: net decline in test status AND below 75% pass rate
  const isRegressing = trend.regressed > trend.improved && winPassRate < 0.75;
  if (isRegressing)
    return { label: 'Regressing', tone: 'text-danger',  bg: 'bg-danger/8',  border: 'border-danger/20'  };

  // Flaky: significant failure rate OR heavy flakiness at sub-80% pass rate
  const isFlaky = winFailRate > 0.2 || (metrics.flaky_count > 2 && winPassRate < 0.80);
  if (isFlaky)
    return { label: 'Flaky',      tone: 'text-warning', bg: 'bg-warning/8', border: 'border-warning/20' };

  // Everything else is Stable (includes 80%+ with a handful of flaky tests)
  return { label: 'Stable', tone: 'text-success', bg: 'bg-success/8', border: 'border-success/20' };
}

// Build reasons why best outperforms others.
// Each reason includes a drillType so the bullet can open an evidence panel.
function buildReasons(best: RankedEntity, ranked: RankedEntity[]): { delta: string; description: string; tone: string; drillType: DrillType }[] {
  const others  = ranked.filter(e => e.label !== best.label);
  const worst   = ranked[ranked.length - 1];
  const reasons: { delta: string; description: string; tone: string; drillType: DrillType }[] = [];

  // 1. Pass rate — compare to worst (largest gap)
  if (best.winPassRate > worst.winPassRate) {
    const d = best.winPassRate - worst.winPassRate;
    if (d >= 0.03)
      reasons.push({ delta: `+${Math.round(d * 100)}%`, description: `higher pass rate (vs ${worst.label.split(' ')[0]})`, tone: 'text-success', drillType: 'pass_rate' });
  }

  // 2. Flaky count — list all peers that best beats
  const beatenFlaky = others.filter(o => best.metrics.flaky_count < o.metrics.flaky_count);
  if (beatenFlaky.length > 0) {
    const minDelta = Math.min(...beatenFlaky.map(o => o.metrics.flaky_count)) - best.metrics.flaky_count;
    const vsNames  = beatenFlaky.map(o => o.label.split(' ')[0]).join(' and ');
    if (best.metrics.flaky_count === 0) {
      reasons.push({ delta: 'zero', description: `flaky tests — completely stable (vs ${vsNames})`, tone: 'text-success', drillType: 'flaky' });
    } else {
      reasons.push({ delta: `${minDelta} fewer`, description: `flaky test${minDelta > 1 ? 's' : ''} (vs ${vsNames})`, tone: 'text-warning', drillType: 'flaky' });
    }
  }

  // 3. No regressions while others show decline
  if (reasons.length < 3) {
    const bestTrend       = computeTrend(best.rows);
    const regressingPeers = others.filter(o => { const t = computeTrend(o.rows); return t.regressed > t.improved && t.regressed > 0; });
    if (regressingPeers.length > 0 && bestTrend.regressed === 0) {
      reasons.push({ delta: 'no', description: 'recent regressions (others show decline)', tone: 'text-success', drillType: 'regressions' });
    }
  }

  // 4. New failures fallback
  if (best.metrics.new_failures < worst.metrics.new_failures && reasons.length < 2) {
    const d = worst.metrics.new_failures - best.metrics.new_failures;
    reasons.push({ delta: `${d} fewer`, description: `new failure${d > 1 ? 's' : ''} this window (vs ${worst.label.split(' ')[0]})`, tone: 'text-danger', drillType: 'failures' });
  }

  // 5. Failure rate fallback
  if (best.winFailRate < worst.winFailRate && reasons.length < 2) {
    const d = Math.round((worst.winFailRate - best.winFailRate) * 100);
    reasons.push({ delta: `${d}% lower`, description: `failure rate (vs ${worst.label.split(' ')[0]})`, tone: 'text-success', drillType: 'pass_rate' });
  }

  return reasons;
}

// One-line summary per entity for the group overview
function entitySummaryLine(e: RankedEntity, rank: number, total: number): string {
  const cls   = classifyEntity(e);
  const trend = computeTrend(e.rows);
  const parts: string[] = [`${pct(e.winPassRate)} pass rate`];
  if (e.metrics.flaky_count > 0) parts.push(`${e.metrics.flaky_count} flaky`);
  if (trend.regressed > 0)       parts.push(`${trend.regressed} regressed`);
  const prefix = rank === 1 ? 'Top' : rank === total ? 'Lowest' : 'Mid';
  return `${prefix} · ${cls.label} · ${parts.join(', ')}`;
}

// ─────────────────────────────────────────────────────────────
// Shared evidence primitives
// ─────────────────────────────────────────────────────────────

type InsightVariant = 'pass_rate' | 'flaky' | 'regressions' | 'failures';

const INSIGHT_THEME: Record<InsightVariant, {
  panel: string;
  headerSurface: string;
  rail: string;
  headerIcon: string;
  stripTrack: string;
  stripWinner: string;
  stripPeer: string;
  row: string;
  footerBorder: string;
  emphasis: string;
  titleClass: string;
  explanationClass: string;
}> = {
  pass_rate: {
    panel: 'border-[#EEF3FB] bg-white shadow-[0_16px_38px_rgba(15,23,42,0.045)]',
    headerSurface: 'bg-[linear-gradient(180deg,rgba(248,250,255,0.9),rgba(255,255,255,0.98))]',
    rail: 'bg-info/44',
    headerIcon: 'border-[#E7EEFF] bg-white text-info shadow-[0_4px_10px_rgba(79,70,229,0.05)]',
    stripTrack: 'bg-[#EDF2F8]',
    stripWinner: 'bg-white shadow-[0_10px_22px_rgba(15,23,42,0.05)] ring-1 ring-[#E4EBF8]',
    stripPeer: 'bg-[#FBFCFE]',
    row: 'border-b border-[#ECF1F7] last:border-b-0 hover:bg-[#FAFCFF]',
    footerBorder: 'border-[#F0F4F9]',
    emphasis: 'ring-1 ring-[#DDE7FB] bg-white shadow-[0_8px_20px_rgba(79,70,229,0.04)]',
    titleClass: 'text-primary',
    explanationClass: 'text-secondary',
  },
  flaky: {
    panel: 'border-[#F8E8CF] bg-white shadow-[0_14px_34px_rgba(180,83,9,0.045)]',
    headerSurface: 'bg-[linear-gradient(180deg,rgba(255,250,243,0.96),rgba(255,255,255,0.9))]',
    rail: 'bg-warning/60',
    headerIcon: 'border-[#F9E4C4] bg-white text-warning shadow-[0_4px_12px_rgba(245,158,11,0.06)]',
    stripTrack: 'bg-[#F7EFDF]',
    stripWinner: 'bg-white/96 ring-1 ring-[#F2E8D3]',
    stripPeer: 'bg-[#FFFDF9]',
    row: 'border-b border-[#F7ECDD] last:border-b-0 hover:bg-[#FFF9F1]',
    footerBorder: 'border-[#F8EEDF]',
    emphasis: 'ring-1 ring-[#F4E3C0] bg-white shadow-[0_8px_18px_rgba(245,158,11,0.035)]',
    titleClass: 'text-primary',
    explanationClass: 'text-secondary',
  },
  regressions: {
    panel: 'border-[#F8E1E1] bg-white shadow-[0_14px_34px_rgba(239,68,68,0.04)]',
    headerSurface: 'bg-[linear-gradient(180deg,rgba(255,247,247,0.96),rgba(255,255,255,0.92))]',
    rail: 'bg-danger/58',
    headerIcon: 'border-[#F8DDDD] bg-white text-danger shadow-[0_4px_12px_rgba(239,68,68,0.05)]',
    stripTrack: 'bg-[#F8E9E9]',
    stripWinner: 'bg-white/96 ring-1 ring-[#F1E4E4]',
    stripPeer: 'bg-[#FFFDFD]',
    row: 'border-b border-[#F6E9E9] last:border-b-0 hover:bg-[#FFF8F8]',
    footerBorder: 'border-[#F7EBEB]',
    emphasis: 'ring-1 ring-[#F3DEDE] bg-white shadow-[0_8px_18px_rgba(239,68,68,0.03)]',
    titleClass: 'text-primary',
    explanationClass: 'text-secondary',
  },
  failures: {
    panel: 'border-[#F8E6E6] bg-white shadow-[0_14px_32px_rgba(239,68,68,0.035)]',
    headerSurface: 'bg-[linear-gradient(180deg,rgba(255,248,248,0.96),rgba(255,255,255,0.92))]',
    rail: 'bg-danger/54',
    headerIcon: 'border-[#F7E1E1] bg-white text-danger shadow-[0_4px_12px_rgba(239,68,68,0.045)]',
    stripTrack: 'bg-[#F7EBEB]',
    stripWinner: 'bg-white/96 ring-1 ring-[#F2E8E8]',
    stripPeer: 'bg-[#FFFDFD]/92',
    row: 'bg-white/86 hover:bg-white ring-1 ring-[#F7ECEC] shadow-[0_2px_10px_rgba(239,68,68,0.02)]',
    footerBorder: 'border-[#F6EAEA]',
    emphasis: 'ring-1 ring-[#F4E4E4] bg-white shadow-[0_8px_18px_rgba(239,68,68,0.028)]',
    titleClass: 'text-primary',
    explanationClass: 'text-secondary',
  },
};

function variantFromDrill(type: DrillType): InsightVariant {
  switch (type) {
    case 'pass_rate':   return 'pass_rate';
    case 'flaky':       return 'flaky';
    case 'regressions': return 'regressions';
    default:            return 'failures';
  }
}

function InsightVariantIcon({ variant }: { variant: InsightVariant }) {
  if (variant === 'pass_rate') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M3 12h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
        <path d="M4.5 10 6.9 7.6 8.7 9.2 11.8 5.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  }

  if (variant === 'flaky') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M2.75 9.75c.9 0 1.15-2.85 2.2-2.85 1.05 0 1.25 2.95 2.15 2.95 1 0 1.2-5.15 2.25-5.15 1.05 0 1.2 6.7 2.2 6.7.7 0 1.1-1.1 1.5-1.75" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  }

  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 4.5h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
      <path d="M4.4 5.9 7.2 8.7 11.8 4.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M8 11.5V8.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    </svg>
  );
}

function AlertTriangleIcon({ className = '', size = 12 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" className={className}>
      <path d="M8 2.2 1.8 13h12.4L8 2.2Z" fill="currentColor" />
      <path d="M8 5.9v3.25M8 11.35v.45" stroke="white" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon({ className = '', size = 12 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" className={className}>
      <path d="M3.15 8.25 6.45 11.15 12.85 4.55" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MinusIcon({ className = '', size = 12 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" className={className}>
      <path d="M3.5 8h9" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
    </svg>
  );
}

function InfoCircleIcon({ className = '', size = 12 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" className={className}>
      <circle cx="8" cy="8" r="6" fill="currentColor" />
      <path d="M8 7v3M8 4.95v.45" stroke="white" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function triggerClasses(type: DrillType, isActive: boolean) {
  const variant = INSIGHT_THEME[variantFromDrill(type)];
  return isActive
    ? `${variant.emphasis} border-transparent`
    : 'bg-white/72 border border-transparent hover:bg-white/94 hover:border-border-subtle';
}

// Flip count: number of status transitions across run_history
function flipCount(row: ApiEntityCompareRow): number {
  const pts = row.run_history.filter(p => p.status !== 'absent');
  let flips = 0;
  for (let i = 1; i < pts.length; i++) {
    const prev = pts[i - 1].status === 'passed';
    const curr = pts[i].status   === 'passed';
    if (prev !== curr) flips++;
  }
  return flips;
}

// Shared expandable error block used by multiple panel types
function ErrorPreview({ msg }: { msg: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[9px] font-medium text-danger/60 hover:text-danger transition-colors duration-150"
      >
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none"
          className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`}>
          <path d="M2.5 4.25 6 7.75l3.5-3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        {open ? 'Hide error' : 'Show root cause'}
      </button>
      {open && (
        <div className="qalens-insight-reveal mt-1.5 rounded-xl bg-danger/[0.035] px-3 py-2.5 ring-1 ring-danger/10">
          <p className="text-[10px] font-mono text-danger/80 leading-relaxed break-all line-clamp-5">{msg}</p>
        </div>
      )}
    </div>
  );
}

// Shared panel shell — handles header, empty state, footer CTA
function EvidencePanelShell({
  title,
  explanation,
  variant,
  showIcon = true,
  viewAllLabel,
  onViewAll,
  viewAllCls,
  isEmpty,
  children,
}: {
  title:        string;
  explanation:  string;
  variant:      InsightVariant;
  showIcon?:    boolean;
  viewAllLabel: string;
  onViewAll:    (cls: FilterCls) => void;
  viewAllCls:   FilterCls;
  isEmpty:      boolean;
  children?:    React.ReactNode;
}) {
  const theme = INSIGHT_THEME[variant];

  return (
    <div className={`relative overflow-hidden rounded-[1.35rem] border transition-[background-color,border-color,box-shadow] duration-200 ${theme.panel}`}>
      <div className={`absolute left-0 top-0 bottom-0 w-[3px] ${theme.rail}`} />

      {/* Header */}
      <div className={`px-5 py-4 ${theme.headerSurface}`}>
        <div className={`flex items-start ${showIcon ? 'gap-3' : 'gap-0'}`}>
          {showIcon && (
            <span className={`inline-flex h-8 w-8 items-center justify-center rounded-[0.95rem] border flex-shrink-0 ${theme.headerIcon}`}>
              <InsightVariantIcon variant={variant} />
            </span>
          )}
          <div className="min-w-0">
            <p className={`text-[10px] font-semibold uppercase tracking-[0.15em] ${theme.titleClass}`}>{title}</p>
            <p className={`mt-1.5 text-[12px] leading-[1.65] ${theme.explanationClass}`}>{explanation}</p>
          </div>
        </div>
      </div>

      {isEmpty ? (
        <div className="px-5 pb-5 pt-1 space-y-3 text-center">
          <p className="text-sm text-muted">{explanation}</p>
          <button onClick={() => onViewAll(viewAllCls)} className="qalens-insight-cta mx-auto">
            <span>Open full breakdown</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path d="M2.5 6h6.5M6 3l3 3-3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
          </button>
        </div>
      ) : (
        <>
          {children}
          {/* Footer */}
          <div className={`flex justify-end px-5 py-3.5 border-t ${theme.footerBorder}`}>
            <button onClick={() => onViewAll(viewAllCls)} className="qalens-insight-cta group">
              <span>{viewAllLabel.replace(/\s*→$/, '')}</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true" className="opacity-80">
                <path d="M2.5 6h6.5M6 3l3 3-3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Compact comparison strip — shared across all three panels.
// Three variants: pass_rate | flaky | regressions
// Intentionally lightweight — no card borders, no shadows,
// no bg fills. Feels like a contextual annotation, not a
// second copy of the main ranked cards below.
// ─────────────────────────────────────────────────────────────

type StripVariant = 'pass_rate' | 'flaky' | 'regressions';

function ComparisonStrip({ ranked, variant }: { ranked: RankedEntity[]; variant: StripVariant }) {
  const best = ranked[0];
  const theme = INSIGHT_THEME[variantFromDrill(variant)];

  // Per-entity derived data used across variants
  const entityData = ranked.map(e => {
    const failingCnt  = e.rows.filter(r => classifyRow(r) === 'failing').length;
    const flakyCnt    = e.rows.filter(r => classifyRow(r) === 'flaky').length;
    const stableCnt   = e.rows.filter(r => classifyRow(r) === 'stable').length;
    const unstableCnt = failingCnt + flakyCnt;
    const total       = e.metrics.total_tests || 1;
    const windowRuns  = Math.max(0, ...e.rows.map(r => r.run_history.length));
    const regrCnt     = e.rows.filter(r => r.status_b === 'passed' && r.status_a !== 'passed').length;
    const isBest      = e.label === best.label;
    return { e, failingCnt, flakyCnt, stableCnt, unstableCnt, total, windowRuns, regrCnt, isBest };
  });

  return (
    <div className={`px-5 pb-3.5 border-b ${theme.footerBorder} space-y-2.5`}>
      {entityData.map(({ e, failingCnt, flakyCnt, stableCnt, unstableCnt, total, windowRuns, regrCnt, isBest }) => {
        const isWorst = e.label === ranked[ranked.length - 1].label;
        const rowShell = [
          'flex items-center gap-3 rounded-[1rem] px-3.5 py-3 transition-[background-color,box-shadow] duration-150',
          isWorst ? `${theme.emphasis}` : theme.stripPeer,
        ].join(' ');

        if (variant === 'pass_rate') {
          const barColor = e.winPassRate >= 0.8 ? 'bg-success' : e.winPassRate >= 0.6 ? 'bg-warning' : 'bg-danger';
          const rateTone = e.winPassRate >= 0.8 ? 'text-success' : e.winPassRate >= 0.6 ? 'text-warning' : 'text-danger';
          return (
            <div key={e.label} className={rowShell}>
              <span className="inline-block h-5 w-5 flex-shrink-0" />
              {/* Name — fixed width so bars align */}
              <span className="text-[11px] w-[72px] flex-shrink-0 truncate text-primary font-medium">{e.label.split(' ')[0]}</span>
              {/* Proportional bar */}
              <div className={`flex-1 h-1.5 rounded-full ${theme.stripTrack} overflow-hidden`}>
                <div className={`h-full rounded-full ${barColor}`} style={{ width: `${Math.round(e.winPassRate * 100)}%` }} />
              </div>
              {/* Pass rate number */}
              <span className={`text-[12px] font-bold tabular-nums w-[40px] text-right flex-shrink-0 ${rateTone}`}>{pct(e.winPassRate)}</span>
              {/* Secondary stats — weaker entities get more detail */}
              {!isBest ? (
                <span className="text-[10px] text-muted flex-shrink-0 min-w-[118px] text-left">
                  {failingCnt > 0 && <span className="text-danger font-medium">{failingCnt} broken</span>}
                  {failingCnt > 0 && flakyCnt > 0 && <span className="text-border-strong"> · </span>}
                  {flakyCnt > 0 && <span className="text-warning font-medium">{flakyCnt} flaky</span>}
                  {unstableCnt === 0 && <span className="text-success">all stable</span>}
                </span>
              ) : (
                <span className="text-[10px] text-muted flex-shrink-0 min-w-[118px] text-left">
                  {stableCnt} stable{flakyCnt > 0 ? ` · ${flakyCnt} flaky` : ''}
                </span>
              )}
            </div>
          );
        }

        if (variant === 'flaky') {
          const unstablePct = Math.round((unstableCnt / total) * 100);
          const unstableTooltip = `${e.label.split(' ')[0]} has ${total} compared test${total !== 1 ? 's' : ''} in this window, and ${unstableCnt} of them were unstable across the last ${windowRuns} run${windowRuns !== 1 ? 's' : ''}, so this portfolio is ${unstablePct}% unstable.`;
          return (
            <div key={e.label} className={rowShell}>
              <span className="inline-block h-5 w-5 flex-shrink-0" />
              <span className="text-[11px] w-[72px] flex-shrink-0 truncate text-primary font-medium">{e.label.split(' ')[0]}</span>
              {/* Flaky count — the primary signal */}
              <span className={`text-[12px] font-bold tabular-nums flex-shrink-0 min-w-[58px] ${flakyCnt > 0 ? 'text-warning' : 'text-success'}`}>
                {flakyCnt} flaky
              </span>
              <span className="text-border-strong text-[9px] flex-shrink-0">·</span>
              <span className="text-[10px] text-muted flex-shrink-0 min-w-[46px]">{stableCnt} stable</span>
              {!isBest && unstablePct > 0 && (
                <>
                  <span className="text-border-strong text-[9px] flex-shrink-0">·</span>
                  <Tooltip
                    content={unstableTooltip}
                    className="flex-shrink-0"
                  >
                    <span className="inline-flex items-center gap-1 text-[10px] text-warning cursor-help decoration-dotted underline underline-offset-2">
                      <span>{unstablePct}% unstable</span>
                      <InfoCircleIcon className="opacity-90" size={12} />
                    </span>
                  </Tooltip>
                </>
              )}
            </div>
          );
        }

        // regressions variant
        return (
          <div key={e.label} className={rowShell}>
            <span className="inline-block h-5 w-5 flex-shrink-0" />
            <span className="text-[11px] w-[72px] flex-shrink-0 truncate text-primary font-medium">{e.label.split(' ')[0]}</span>
            <span className={`text-[12px] font-bold tabular-nums flex-shrink-0 min-w-[88px] ${regrCnt > 0 ? 'text-danger' : 'text-success'}`}>
              {regrCnt === 0 ? '0 regressions' : `${regrCnt} regression${regrCnt !== 1 ? 's' : ''}`}
            </span>
            {isBest && regrCnt === 0 && (
              <span className="text-[10px] text-muted flex-shrink-0">— stable baseline</span>
            )}
            {!isBest && regrCnt > 0 && (
              <span className="text-[10px] text-muted flex-shrink-0">
                · {e.rows.filter(r => r.status_b === 'passed' && r.status_a === 'passed').length} still passing
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function PassRatePanel({
  ranked,
  onViewAll,
  windowRunCount,
}: {
  ranked: RankedEntity[];
  onViewAll: (cls: FilterCls) => void;
  windowRunCount: number;
}) {
  const best    = ranked[0];
  const worst   = ranked[ranked.length - 1];
  const theme   = INSIGHT_THEME.pass_rate;
  const gapPct  = Math.round((best.winPassRate - worst.winPassRate) * 100);
  const worstFirst = worst.label.split(' ')[0];
  const bestFirst  = best.label.split(' ')[0];

  // Top contributors: tests with highest failure burden in weaker entities ONLY.
  // Explicitly exclude pure-flaky tests (those belong in the flakiness lens).
  // Sort by fail count — failure burden, not volatility.
  const LIMIT      = 4;
  const weaker     = ranked.slice(1);
  const topFailing = weaker.flatMap(e =>
    e.rows
      .filter(r => failCount(r) > 0 && classifyRow(r) !== 'flaky') // failure burden only
      .sort((a, b) => failCount(b) - failCount(a))
      .slice(0, LIMIT)
      .map(r => ({ row: r, entity: e }))
  ).sort((a, b) => failCount(b.row) - failCount(a.row)).slice(0, LIMIT);

  // Fallback: include flaky if no purely-failing tests found
  const contributors = topFailing.length > 0 ? topFailing : weaker.flatMap(e =>
    e.rows
      .filter(r => failCount(r) > 0)
      .sort((a, b) => failCount(b) - failCount(a))
      .slice(0, LIMIT)
      .map(r => ({ row: r, entity: e }))
  ).sort((a, b) => failCount(b.row) - failCount(a.row)).slice(0, LIMIT);

  const isEmpty = contributors.length === 0 && weaker.every(e => e.metrics.total_tests === 0);

  // Summary sentence that connects the two portfolios
  const worstUnstable = worst.rows.filter(r => classifyRow(r) !== 'stable').length;
  const bestUnstable  = best.rows.filter(r => classifyRow(r) !== 'stable').length;
  const summaryLine = worstUnstable > bestUnstable
    ? `${worstFirst} has ${worstUnstable} unstable test${worstUnstable !== 1 ? 's' : ''} vs ${bestFirst}'s ${bestUnstable} — this instability gap drives the ${gapPct}% difference.`
    : `${worstFirst}'s portfolio is the main contributor to the ${gapPct}% pass rate gap vs ${bestFirst}.`;

  return (
    <EvidencePanelShell
      title="Pass rate gap contributors"
      explanation={isEmpty ? `No individual test failures found in ${worstFirst}'s portfolio — the gap may be due to test count differences.` : summaryLine}
      variant="pass_rate"
      showIcon={false}
      viewAllLabel={`View all failing tests for ${worstFirst} →`}
      onViewAll={onViewAll}
      viewAllCls="failing"
      isEmpty={isEmpty}
    >
      {/* ── Compact comparison strip ─────────────────────────── */}
      <ComparisonStrip ranked={ranked} variant="pass_rate" />

      {/* ── Top contributing tests (failure burden) ─────────── */}
      {contributors.length > 0 && (
        <div>
          <p className="px-5 pt-3 pb-2.5 text-[10px] font-bold uppercase tracking-[0.16em] text-secondary">
            Top contributors — by failure burden
          </p>
          <div className="px-5 pb-4 max-h-[220px] overflow-y-auto">
            {contributors.map(({ row, entity }) => {
              const cls    = classifyRow(row);
              const fc     = failCount(row);
              const clsBg  = cls === 'failing' ? 'bg-danger/8 border-danger/15 text-danger' : 'bg-warning/8 border-warning/15 text-warning';
              return (
                <div key={`${row.canonical_name}-${entity.label}`} className={`px-3.5 py-3 transition-[background-color] duration-150 ${theme.row}`}>
                  <div className="flex items-start gap-2.5">
                    <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border flex-shrink-0 mt-0.5 ${clsBg}`}>
                      {cls === 'failing' ? 'Broken' : 'Flaky'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] font-mono text-primary font-medium leading-snug break-all">{row.display_name}</p>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        <span className="text-[9px] font-medium px-1.5 py-0.5 rounded border border-danger/15 bg-danger/[0.05] text-danger/80">
                          {entity.label.split(' ')[0]}
                        </span>
                        {row.suite && <><span className="text-border-strong text-[9px]">·</span><span className="text-[10px] text-muted truncate">{row.suite}</span></>}
                        <span className="text-border-strong text-[9px]">·</span>
                        <span className="text-[10px] text-secondary">failed {fc} time{fc !== 1 ? 's' : ''} across {windowRunCount} selected run{windowRunCount !== 1 ? 's' : ''}</span>
                      </div>
                      {row.error_message && <ErrorPreview msg={row.error_message} />}
                    </div>
                    <span className="text-[10px] font-bold tabular-nums text-danger flex-shrink-0 mt-0.5">{fc}✕</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </EvidencePanelShell>
  );
}

// ─────────────────────────────────────────────────────────────
// 2. Flakiness panel — volatility-first with run-history dots
// ─────────────────────────────────────────────────────────────

function FlakinessDot({ status }: { status: string }) {
  const bg =
    status === 'passed'                        ? 'bg-success'
    : status === 'failed' || status === 'broken' ? 'bg-danger'
    : status === 'skipped'                     ? 'bg-border-strong'
    :                                            'bg-surface-raised'; // absent
  return (
    <Tooltip content={status} className="inline-flex flex-shrink-0">
      <span className={`inline-block w-2 h-2 rounded-full ${bg}`} />
    </Tooltip>
  );
}

function FlakinessPanel({
  ranked,
  onViewAll,
  windowRunCount,
}: {
  ranked: RankedEntity[];
  onViewAll: (cls: FilterCls) => void;
  windowRunCount: number;
}) {
  const best        = ranked[0];
  const theme       = INSIGHT_THEME.flaky;
  const others      = ranked.slice(1);
  const beatenPeers = others.filter(o => best.metrics.flaky_count < o.metrics.flaky_count);
  const peerNames   = beatenPeers.map(o => o.label.split(' ')[0]).join(' and ');
  const totalFlaky  = beatenPeers.reduce((s, o) => s + o.metrics.flaky_count, 0);
  const LIMIT       = 6;

  // Flaky tests sorted by flip count (volatility), not fail count
  const flaky = beatenPeers.flatMap(e =>
    e.rows
      .filter(r => classifyRow(r) === 'flaky')
      .map(r => ({ row: r, entity: e, flips: flipCount(r), fc: failCount(r) }))
  ).sort((a, b) => b.flips - a.flips || b.fc - a.fc).slice(0, LIMIT);

  return (
    <EvidencePanelShell
      title="Flakiness gap"
      explanation={
        flaky.length > 0
          ? `${peerNames} ${totalFlaky === 1 ? 'has' : 'have'} ${totalFlaky} unstable test${totalFlaky !== 1 ? 's' : ''} vs ${best.label.split(' ')[0]}'s ${best.metrics.flaky_count}. Ranked by volatility — highest flip rate first.`
          : `No flaky tests found in the compared portfolios for this window.`
      }
      variant="flaky"
      showIcon={false}
      viewAllLabel={`View all flaky tests for ${peerNames} →`}
      onViewAll={onViewAll}
      viewAllCls="flaky"
      isEmpty={flaky.length === 0}
    >
      {/* ── Compact comparison strip ─────────────────────────── */}
      <ComparisonStrip ranked={ranked} variant="flaky" />

      {/* ── "Most unstable tests" list with run-history dots ─── */}
      <div>
        <p className="px-5 pt-3 pb-2.5 text-[10px] font-bold uppercase tracking-[0.16em] text-secondary">
          Most unstable tests — by flip count
        </p>
        <div className="px-5 pb-4 max-h-[280px] overflow-y-auto">
          {flaky.map(({ row, entity, flips, fc }) => {
            return (
              <div key={`${row.canonical_name}-${entity.label}`} className={`px-3.5 py-3 transition-[background-color] duration-150 ${theme.row}`}>
                <div className="flex items-start gap-2.5">
                  {/* Flip badge — the primary signal in this lens */}
                  <div className="flex flex-col items-center flex-shrink-0 mt-0.5">
                    <span className="text-[10px] font-bold tabular-nums text-warning leading-none">{flips}</span>
                    <span className="text-[8px] text-muted leading-none">flip{flips !== 1 ? 's' : ''}</span>
                  </div>

                  <div className="flex-1 min-w-0 space-y-1">
                    <p className="text-[11px] font-mono text-primary font-medium leading-snug break-all">{row.display_name}</p>
                    <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                      <span className="text-[9px] font-medium px-1.5 py-0.5 rounded border border-warning/20 bg-warning/[0.08] text-warning flex-shrink-0">
                        {entity.label.split(' ')[0]}
                      </span>
                      {row.suite && <><span className="text-border-strong text-[9px]">·</span><span className="text-[10px] text-muted truncate">{row.suite}</span></>}
                    </div>
                    {/* Run history sparkline */}
                    <div className="flex items-center gap-0.5">
                      {row.run_history.map((pt, i) => <FlakinessDot key={i} status={pt.status} />)}
                      <span className="text-[9px] text-muted ml-1.5">
                        {fc} failure{fc !== 1 ? 's' : ''} across {windowRunCount} selected run{windowRunCount !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </EvidencePanelShell>
  );
}

// ─────────────────────────────────────────────────────────────
// 3. Regression panel — temporal storytelling
//    Lens: "what changed recently?"
//    Each test tells a before/after story with plain-language
//    temporal description, NOT a generic status label.
//    Only includes tests with genuine recent transitions.
// ─────────────────────────────────────────────────────────────

function RegressionPanel({
  ranked,
  onViewAll,
  windowRunCount,
}: {
  ranked: RankedEntity[];
  onViewAll: (cls: FilterCls) => void;
  windowRunCount: number;
}) {
  const others    = ranked.slice(1);
  const theme     = INSIGHT_THEME.regressions;
  const peerNames = others.map(o => o.label.split(' ')[0]).join(' and ');
  const LIMIT     = 5;

  // Recency score: how many of the last N runs failed (higher = more recent failure).
  function recentFailScore(row: ApiEntityCompareRow): number {
    const pts    = row.run_history.filter(p => p.status !== 'absent');
    const tail   = Math.max(2, Math.ceil(pts.length / 2));
    const recent = pts.slice(-tail);
    return recent.filter(p => p.status === 'failed' || p.status === 'broken').length;
  }

  // "Previously stable" = passed in all early runs. "Now worsened" = failed in recent runs.
  function temporalStory(row: ApiEntityCompareRow): { before: string; now: string; isNew: boolean } {
    const pts     = row.run_history.filter(p => p.status !== 'absent');
    const half    = Math.ceil(pts.length / 2);
    const early   = pts.slice(0, half);
    const recent  = pts.slice(-half);

    const earlyPassCnt   = early.filter(p => p.status === 'passed').length;
    const recentPassCnt  = recent.filter(p => p.status === 'passed').length;
    const recentFailCnt  = recent.filter(p => p.status === 'failed' || p.status === 'broken').length;
    const becameFlaky    = recentPassCnt > 0 && recentFailCnt > 0;

    const before = earlyPassCnt === early.length
      ? `mostly passing earlier in this ${windowRunCount}-run window`
      : earlyPassCnt > 0
        ? `mostly passing earlier (${earlyPassCnt}/${early.length})`
        : 'unstable earlier';

    const now = becameFlaky
      ? `became flaky — ${recentFailCnt} failure${recentFailCnt !== 1 ? 's' : ''} in the recent half of this ${windowRunCount}-run window`
      : recentFailCnt > 0
        ? `failing in ${recentFailCnt} recent run${recentFailCnt !== 1 ? 's' : ''} within this ${windowRunCount}-run window`
        : 'status unclear';

    // "New" = failed only in the very last run (sharp recent break)
    const isNew = pts.length > 1 && pts[pts.length - 1].status !== 'passed' && pts[pts.length - 2].status === 'passed';

    return { before, now, isNew };
  }

  const regressed = others.flatMap(e =>
    e.rows
      .filter(r => r.status_b === 'passed' && r.status_a !== 'passed')
      .map(r => ({ row: r, entity: e, recentScore: recentFailScore(r), story: temporalStory(r) }))
  )
    // Sort: brand-new regressions first, then by recency score
    .sort((a, b) => {
      if (a.story.isNew !== b.story.isNew) return a.story.isNew ? -1 : 1;
      return b.recentScore - a.recentScore;
    })
    .slice(0, LIMIT);

  return (
    <EvidencePanelShell
      title="Recent regressions driving the decline"
      explanation={
        regressed.length > 0
          ? `${regressed.length} test${regressed.length !== 1 ? 's' : ''} recently worsened in ${peerNames}'s portfolio — these are the primary cause of the current decline.`
          : `No recent regressions found in this window — the performance gap may be from tests that have been failing consistently for longer.`
      }
      variant="regressions"
      showIcon={false}
      viewAllLabel="View all regressed tests →"
      onViewAll={onViewAll}
      viewAllCls="failing"
      isEmpty={regressed.length === 0}
    >
      {/* ── Compact comparison strip ─────────────────────────── */}
      <ComparisonStrip ranked={ranked} variant="regressions" />

      <div>
        <p className="px-5 pt-3 pb-2.5 text-[10px] font-bold uppercase tracking-[0.16em] text-secondary">
          Recently worsened tests
        </p>
        <div className="px-5 pb-4 max-h-[300px] overflow-y-auto">
          {regressed.map(({ row, entity, story }) => (
            <div key={`${row.canonical_name}-${entity.label}`} className={`px-3.5 py-3 transition-[background-color] duration-150 ${theme.row}`}>
              <div className="flex items-start gap-2.5">

                {/* NEW badge for sharp single-run breaks */}
                <div className="flex flex-col items-center flex-shrink-0 mt-0.5 min-w-[26px]">
                  {story.isNew ? (
                    <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-danger/8 border border-danger/15 text-danger leading-none">NEW</span>
                  ) : (
                    <span className="text-[8px] font-semibold text-muted leading-none">↓</span>
                  )}
                </div>

                {/* Temporal story */}
                <div className="flex-1 min-w-0 space-y-1.5">
                  <p className="text-[11px] font-mono text-primary font-medium leading-snug break-all">{row.display_name}</p>

                  {/* Before / Now narrative lines */}
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[9px] font-medium text-muted w-[42px] flex-shrink-0">Before</span>
                      <span className="text-[10px] text-secondary">{story.before}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[9px] font-medium text-muted w-[42px] flex-shrink-0">Now</span>
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-danger/70 flex-shrink-0" />
                      <span className="text-[10px] font-medium text-primary">{story.now}</span>
                    </div>
                  </div>

                  {/* Owner + suite + trajectory sparkline */}
                  <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded border border-border-default bg-white text-secondary flex-shrink-0">
                      {entity.label.split(' ')[0]}
                    </span>
                    {row.suite && <><span className="text-border-strong text-[9px]">·</span><span className="text-[10px] text-muted truncate">{row.suite}</span></>}
                    <span className="text-border-strong text-[9px]">·</span>
                    <div className="flex items-center gap-0.5">
                      {row.run_history.map((pt, i) => <FlakinessDot key={i} status={pt.status} />)}
                    </div>
                  </div>

                  {row.error_message && <ErrorPreview msg={row.error_message} />}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </EvidencePanelShell>
  );
}

// ─────────────────────────────────────────────────────────────
// 4. Failures panel — fallback for 'failures' drill type
// ─────────────────────────────────────────────────────────────

function FailuresPanel({
  ranked,
  onViewAll,
  windowRunCount,
}: {
  ranked: RankedEntity[];
  onViewAll: (cls: FilterCls) => void;
  windowRunCount: number;
}) {
  const worst  = ranked[ranked.length - 1];
  const theme  = INSIGHT_THEME.failures;
  const LIMIT  = 6;
  const rows   = worst.rows
    .filter(r => failCount(r) > 0)
    .sort((a, b) => failCount(b) - failCount(a))
    .slice(0, LIMIT);

  return (
    <EvidencePanelShell
      title="Tests with failures"
      explanation={
        rows.length > 0
          ? `These tests from ${worst.label.split(' ')[0]}'s portfolio recorded failures in this window.`
          : `No test failures found for ${worst.label.split(' ')[0]} in this comparison window.`
      }
      variant="failures"
      viewAllLabel={`View all failing tests for ${worst.label.split(' ')[0]} →`}
      onViewAll={onViewAll}
      viewAllCls="failing"
      isEmpty={rows.length === 0}
    >
      <div className="px-5 pb-4 pt-1 max-h-[280px] overflow-y-auto">
        {rows.map(r => {
          const cls   = classifyRow(r);
          const fc    = failCount(r);
          const clsBg = cls === 'failing' ? 'bg-danger/8 border-danger/15 text-danger' : 'bg-warning/8 border-warning/15 text-warning';
          return (
            <div key={r.canonical_name} className={`px-3.5 py-3 transition-[background-color] duration-150 ${theme.row}`}>
              <div className="flex items-start gap-2.5">
                <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border flex-shrink-0 mt-0.5 ${clsBg}`}>
                  {cls === 'failing' ? 'Broken' : 'Flaky'}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-mono text-primary font-medium leading-snug break-all">{r.display_name}</p>
                  <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                    {r.suite && <span className="text-[10px] text-muted truncate">{r.suite}</span>}
                    <span className="text-border-strong text-[9px]">·</span>
                    <span className="text-[10px] text-secondary">failed {fc} time{fc !== 1 ? 's' : ''} across {windowRunCount} selected run{windowRunCount !== 1 ? 's' : ''}</span>
                  </div>
                  {r.error_message && <ErrorPreview msg={r.error_message} />}
                </div>
                <span className="text-[10px] font-bold tabular-nums text-danger flex-shrink-0 mt-0.5">{fc}✕</span>
              </div>
            </div>
          );
        })}
      </div>
    </EvidencePanelShell>
  );
}

// ─────────────────────────────────────────────────────────────
// EvidencePanel — routes to the correct typed panel
// ─────────────────────────────────────────────────────────────

function EvidencePanel({
  type,
  ranked,
  onViewAll,
  windowRunCount,
}: {
  type:      DrillType;
  ranked:    RankedEntity[];
  onViewAll: (cls: FilterCls) => void;
  windowRunCount: number;
}) {
  switch (type) {
    case 'pass_rate':   return <PassRatePanel   ranked={ranked} onViewAll={onViewAll} windowRunCount={windowRunCount} />;
    case 'flaky':       return <FlakinessPanel  ranked={ranked} onViewAll={onViewAll} windowRunCount={windowRunCount} />;
    case 'regressions': return <RegressionPanel ranked={ranked} onViewAll={onViewAll} windowRunCount={windowRunCount} />;
    default:            return <FailuresPanel   ranked={ranked} onViewAll={onViewAll} windowRunCount={windowRunCount} />;
  }
}

function VerdictBanner({ ranked, runCount, onViewAll }: { ranked: RankedEntity[]; runCount: number; onViewAll: (cls: FilterCls) => void }) {
  const best    = ranked[0];
  const worst   = ranked[ranked.length - 1];
  const isThreeWay = ranked.length === 3;
  const scoreDiff  = best.score - worst.score;
  const isTied     = scoreDiff < 0.02;
  const isLarge    = scoreDiff >= 0.2;

  const [activeType, setActiveType] = useState<DrillType | null>(null);

  const reasons  = isTied ? [] : buildReasons(best, ranked);
  const gapLabel = isTied   ? 'Performance is comparable'
                 : isLarge  ? 'Significant performance gap'
                 :            'Moderate performance gap';

  // Actionable recommendation driven by the worst entity's health status
  const recommendation = (() => {
    if (isTied) return null;
    const cls   = classifyEntity(worst);
    const name  = worst.label.split(' ')[0];
    if (cls.label === 'Regressing')
      return `Focus on ${name}'s tests — highest regression and lowest stability in this window.`;
    if (cls.label === 'Flaky' && worst.metrics.flaky_count > 0)
      return `${name}'s ${worst.metrics.flaky_count} flaky test${worst.metrics.flaky_count !== 1 ? 's' : ''} are the highest risk — investigate to improve reliability.`;
    if (worst.metrics.new_failures > 0)
      return `Review ${name}'s ${worst.metrics.new_failures} new failure${worst.metrics.new_failures !== 1 ? 's' : ''} — they appeared recently and may indicate a regression.`;
    return null;
  })();

  return (
    <section className="qalens-fade-up space-y-4">

      {/* ── Classification row ───────────────────────────────── */}
      <div className="flex flex-wrap gap-3">
        {ranked.map((e, i) => {
          const cls      = classifyEntity(e);
          const isTop    = i === 0;
          const isBottom = i === ranked.length - 1;
          // Top performer gets a positive "Most Stable" badge regardless of underlying classification
          // — calling the best entity "Flaky" is misleading when they outperform everyone else.
          const displayCls = isTop
            ? { label: 'Most Stable', tone: 'text-success', bg: 'bg-success/8', border: 'border-success/20' }
            : cls;
          return (
            <div key={e.label} className={`flex items-center gap-2.5 px-4 py-3.5 rounded-[1rem] border bg-surface shadow-[0_8px_22px_rgba(15,23,42,0.04)] flex-1 min-w-[150px] ${displayCls.border} ${isBottom && !isTied ? 'ring-1 ring-danger/10' : ''}`}>
              <div className={`flex h-7 w-7 items-center justify-center rounded-full bg-current/10 flex-shrink-0 ${displayCls.tone}`}>
                {isTop ? (
                  <CheckIcon size={12} />
                ) : isBottom && !isTied ? (
                  <AlertTriangleIcon />
                ) : (
                  <MinusIcon size={12} />
                )}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <p className={`text-[10px] font-bold uppercase tracking-[0.13em] ${displayCls.tone}`}>{displayCls.label}</p>
                  {isTop && <span className="text-[9px] font-semibold uppercase tracking-wide text-muted">· #1</span>}
                </div>
                <p className="text-sm font-semibold text-primary truncate">{e.label}</p>
                <p className="text-[11px] text-muted">{pct(e.winPassRate)} pass rate</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Analytical insight box ───────────────────────────── */}
      <div className="rounded-[1.45rem] border border-border-default bg-surface px-5 py-5 shadow-[0_18px_46px_rgba(15,23,42,0.05)] space-y-4">

        {/* Key insight line */}
        <div className="relative overflow-hidden rounded-[1.2rem] border border-[rgb(var(--info-rgb)/0.16)] bg-[rgb(var(--info-rgb)/0.06)] px-4 py-4 shadow-[0_12px_28px_rgba(79,70,229,0.05)]">
          <div className="absolute left-0 top-0 bottom-0 w-[4px] rounded-l-[1.2rem] bg-info/60" />
          <div className="flex items-start gap-3">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-[1rem] border border-[rgb(var(--info-rgb)/0.16)] bg-surface text-info shadow-[0_6px_14px_rgba(79,70,229,0.06)] flex-shrink-0">
              <InfoCircleIcon size={14} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">Headline insight</p>
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${isTied ? 'border-border-default bg-surface text-muted' : isLarge ? 'border-danger/15 bg-danger/[0.08] text-danger' : 'border-warning/15 bg-warning/[0.08] text-warning'}`}>
                  {gapLabel}
                </span>
              </div>
              {isTied ? (
                <p className="mt-2 text-[16px] font-semibold leading-[1.45] text-primary">
                  {ranked.map(e => e.label.split(' ')[0]).join(', ')} are performing similarly over the last {runCount} run{runCount !== 1 ? 's' : ''}.
                </p>
              ) : (
                <p className="mt-2 text-[16px] font-semibold leading-[1.45] text-primary">
                  <span className="font-semibold text-primary">{best.label.split(' ')[0]}</span>
                  <span className="text-secondary"> leads across the window, while </span>
                  <span className="font-semibold text-primary">{worst.label.split(' ')[0]}</span>
                  <span className="text-secondary"> is driving the current gap.</span>
                </p>
              )}
              {!isTied && (
                <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
                  The comparison spans {runCount} run{runCount !== 1 ? 's' : ''}, with the biggest separation showing up in pass-rate resilience and test stability.
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Actionable recommendation */}
        {recommendation && (
          <div className="flex items-start gap-2 rounded-[1rem] border border-warning/20 bg-warning/[0.04] px-3.5 py-3">
            <AlertTriangleIcon className="text-warning mt-0.5 flex-shrink-0" />
            <p className="text-xs text-secondary leading-relaxed">{recommendation}</p>
          </div>
        )}

        {/* Group overview — always shown for 3-way */}
        {isThreeWay && (
          <div className="space-y-1.5 border-t border-border-subtle pt-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mb-2">Group overview</p>
            {ranked.map((e, i) => (
              <div key={e.label} className="flex items-baseline gap-2 text-sm">
                <span className="text-muted w-3 text-right flex-shrink-0">{i + 1}.</span>
                <span className="font-semibold text-primary">{e.label.split(' ')[0]}</span>
                <span className="text-muted text-xs">— {entitySummaryLine(e, i + 1, ranked.length)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Reasons why best ranks higher — each bullet is a drill-down trigger */}
        {!isTied && reasons.length > 0 && (
          <div className="space-y-1 border-t border-border-subtle pt-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mb-2">
              Why {best.label.split(' ')[0]} ranks higher
            </p>
            <ul className="space-y-2">
              {reasons.map(r => {
                const isActive = activeType === r.drillType;
                return (
                  <li key={r.description}>
                    <button
                      onClick={() => setActiveType(t => t === r.drillType ? null : r.drillType)}
                      className={[
                        'w-full flex items-center gap-2 text-sm text-left rounded-[1rem] px-3.5 py-2.5 transition-all duration-200 group',
                        isActive ? triggerClasses(r.drillType, true) : triggerClasses(r.drillType, false),
                      ].join(' ')}
                    >
                      <span className="text-muted select-none flex-shrink-0">•</span>
                      <span className={`font-semibold tabular-nums flex-shrink-0 ${r.tone}`}>{r.delta}</span>
                      <span className="text-secondary">{r.description}</span>
                      {/* Chevron: points right → down when active */}
                      <svg
                        width="10" height="10" viewBox="0 0 12 12" fill="none"
                        className={[
                          'ml-auto flex-shrink-0 transition-all duration-200',
                          isActive
                            ? 'text-info rotate-90 opacity-100'
                            : 'text-muted opacity-70 group-hover:opacity-100 group-hover:text-secondary',
                        ].join(' ')}
                      >
                        <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </button>
                    {/* Inline evidence panel — expands directly below this bullet */}
                    {isActive && (
                      <div className="qalens-insight-reveal mt-2 pl-3">
                        <EvidencePanel
                          type={r.drillType}
                          ranked={ranked}
                          onViewAll={onViewAll}
                          windowRunCount={runCount}
                        />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>

    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 2. Ranked Suite / Owner Card
// ─────────────────────────────────────────────────────────────

function RankedCard({ entity, totalEntities }: { entity: RankedEntity; totalEntities: number }) {
  const { metrics, rows, rank, winPassRate } = entity;
  const trend = computeTrend(rows);

  const isFirst = rank === 1;
  const isLast  = rank === totalEntities;

  const accentColor = isFirst ? 'bg-success'
                    : isLast  ? 'bg-danger'
                    :           'bg-border-strong';

  const rankBg = isFirst ? 'bg-success/10 text-success border-success/20'
               : isLast  ? 'bg-danger/10 text-danger border-danger/20'
               :           'bg-surface-subtle text-muted border-border-default';

  const passTone = winPassRate >= 0.9 ? 'text-success'
                 : winPassRate >= 0.7 ? 'text-warning'
                 : 'text-danger';

  // Trend lines: one line per direction that actually changed
  const trendLines: { text: string; cls: string }[] = [];
  if (trend.regressed > 0) trendLines.push({ text: `↓ ${trend.regressed} regressed`, cls: 'text-danger'  });
  if (trend.improved  > 0) trendLines.push({ text: `↑ ${trend.improved}  recovered`, cls: 'text-success' });

  // Baseline pass rate from status_b — used to show movement on the bar
  const baselineRate = rows.length > 0
    ? rows.filter(r => r.status_b === 'passed').length / rows.length
    : null;
  const baselineMoved = baselineRate !== null && Math.abs(baselineRate - winPassRate) > 0.02;

  const mostUnstable = [...rows]
    .sort((a, b) => failCount(b) - failCount(a))
    .find(r => failCount(r) > 0);

  const failingCount = rows.filter(r => classifyRow(r) === 'failing').length;
  const flakyCount   = rows.filter(r => classifyRow(r) === 'flaky').length;
  const stableCount  = rows.filter(r => classifyRow(r) === 'stable').length;
  const allHealthy   = failingCount === 0 && flakyCount === 0;

  return (
    <article className="qalens-card qalens-fade-up relative overflow-hidden">
      {/* Left accent bar — inset so it respects border-radius at both corners */}
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-[1.25rem] ${accentColor}`} />

      {/* Header */}
      <div className="flex items-start justify-between gap-3 p-5 pb-4">
        <div className="flex items-center gap-3 min-w-0">
          {/* Rank badge */}
          <span className={`inline-flex items-center justify-center h-6 w-6 rounded-full text-[11px] font-bold border flex-shrink-0 ${rankBg}`}>
            {isFirst ? (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="text-current">
                <path d="M5 2h6v5a3 3 0 0 1-6 0V2Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
                <path d="M2 2h3v3a3 3 0 0 1-3 0V2ZM11 2h3v3a3 3 0 0 1-3 0V2Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
                <path d="M8 10v3M5.5 13h5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
              </svg>
            ) : rank}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-primary truncate">{metrics.label}</p>
            <p className="text-[11px] text-muted">{metrics.total_tests} tests</p>
          </div>
        </div>

        {/* Pass rate + trend */}
        <div className="text-right flex-shrink-0">
          <p className={`text-2xl font-bold tabular-nums tracking-tight leading-none ${passTone}`}>
            {pct(winPassRate)}
          </p>
          <p className="text-[10px] text-muted mt-0.5">across window</p>
          <div className="flex flex-col items-end gap-0.5 mt-1">
            {trendLines.length === 0
              ? <span className="text-[11px] text-muted">— no change</span>
              : trendLines.map(l => (
                  <span key={l.text} className={`text-[11px] font-medium tabular-nums ${l.cls}`}>{l.text}</span>
                ))
            }
          </div>
        </div>
      </div>

      {/* Pass rate bar with optional baseline marker */}
      <div className="px-5 pb-4">
        <div className="relative h-1.5 rounded-full bg-surface-raised">
          {/* Current fill */}
          <div
            className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ${
              isFirst ? 'bg-success' : isLast ? 'bg-danger' : 'bg-border-strong'
            }`}
            style={{ width: `${Math.round(winPassRate * 100)}%` }}
          />
          {/* Baseline tick — only shown when there's meaningful movement */}
          {baselineMoved && baselineRate !== null && (
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
              style={{ left: `${Math.round(baselineRate * 100)}%` }}
            >
              <Tooltip content={`Baseline: ${pct(baselineRate)}`} className="inline-flex">
                <div className="w-px h-3.5 rounded-full bg-muted/40" />
              </Tooltip>
            </div>
          )}
        </div>
        {/* Baseline label */}
        {baselineMoved && baselineRate !== null && (
          <p className="text-[10px] text-muted mt-1.5">
            was {pct(baselineRate)} in baseline
          </p>
        )}
      </div>

      {/* Key stats row — counts derived from classifyRow() so they match the table exactly */}
      <div className="flex items-center gap-0 border-t border-border-subtle divide-x divide-border-subtle">
        {[
          { label: 'Broken', value: failingCount, tone: failingCount > 0 ? 'text-danger'  : 'text-muted', tooltip: 'Consistently failing — never passed in this run window'    },
          { label: 'Flaky',  value: flakyCount,   tone: flakyCount > 0   ? 'text-warning' : 'text-muted', tooltip: 'Unreliable — passes sometimes, fails sometimes across runs' },
          { label: 'Stable', value: stableCount,  tone: allHealthy       ? 'text-success' : 'text-muted', tooltip: 'Consistently passing across all runs in this window'        },
        ].map(s => (
          <Tooltip key={s.label} content={s.tooltip} className="flex-1">
            <div className="px-4 py-3 text-center cursor-default">
              <p className={`text-sm font-semibold tabular-nums ${s.tone}`}>{s.value}</p>
              <p className="text-[10px] text-muted mt-0.5">{s.label}</p>
            </div>
          </Tooltip>
        ))}
      </div>

      {/* Risk highlight */}
      {mostUnstable ? (
        <div className="px-5 py-3.5 border-t border-border-subtle bg-surface-subtle">
          <div className="flex items-start gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-danger/70 mt-0.5 flex-shrink-0">Risk</span>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 flex-wrap">
                <p className="text-[11px] font-mono text-secondary leading-snug break-all">{mostUnstable.display_name}</p>
                <ClassBadge cls={classifyRow(mostUnstable)} />
              </div>
              <p className="text-[10px] text-muted mt-0.5">
                {failCount(mostUnstable)} failure{failCount(mostUnstable) !== 1 ? 's' : ''} in window
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="px-5 py-3.5 border-t border-border-subtle bg-success/5">
          <p className="text-xs text-success font-medium">✓ All tests stable in this window</p>
        </div>
      )}

    </article>
  );
}

// ─────────────────────────────────────────────────────────────
// 3. Run history dot
// ─────────────────────────────────────────────────────────────

function fmtRunDate(ts: number | null | undefined): string {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function runPassRateColor(rate: number): string {
  if (rate >= 0.9) return 'text-success';
  if (rate >= 0.7) return 'text-warning';
  return 'text-danger';
}

function RunStateGlyph({ status, seq }: { status: string; seq: number }) {
  const label = `Run #${seq}: ${status}`;
  if (status === 'passed') {
    return (
      <Tooltip content={label} className="inline-flex">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-success text-white">
          <svg viewBox="0 0 12 12" fill="none" className="h-3 w-3">
            <path d="M2.5 6.25L4.8 8.5 9.5 3.75" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </Tooltip>
    );
  }
  if (status === 'failed' || status === 'broken') {
    return (
      <Tooltip content={label} className="inline-flex">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-danger text-white">
          <svg viewBox="0 0 12 12" fill="none" className="h-3 w-3">
            <path d="M3.5 3.5L8.5 8.5M8.5 3.5L3.5 8.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </span>
      </Tooltip>
    );
  }
  if (status === 'skipped') {
    return (
      <Tooltip content={label} className="inline-flex">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-md border border-border-default bg-surface-subtle text-muted">
          <span className="h-px w-2.5 rounded-full bg-current" />
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip content={label} className="inline-flex">
      <span className="inline-flex h-5 w-5 items-center justify-center rounded-md border border-border-subtle bg-transparent" />
    </Tooltip>
  );
}

// ─────────────────────────────────────────────────────────────
// 4. Classification badge
// ─────────────────────────────────────────────────────────────

function ClassBadge({ cls }: { cls: 'stable' | 'flaky' | 'failing' }) {
  if (cls === 'failing') return <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-danger/10 border border-danger/20 text-danger">Broken</span>;
  if (cls === 'flaky')   return <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-warning/10 border border-warning/20 text-warning">Flaky</span>;
  return                        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-success/10 border border-success/20 text-success">Stable</span>;
}

// ─────────────────────────────────────────────────────────────
// 5. Test breakdown table
// ─────────────────────────────────────────────────────────────

type SortKey   = 'failures' | 'name' | 'suite' | 'owner';
type FilterCls = 'all' | 'failing' | 'flaky' | 'stable';

function EntityTestTable({ rows, labels, dimension, externalFilter, windowRunCount, runsOrdered }: {
  rows:            ApiEntityCompareRow[];
  labels:          string[];
  dimension:       string;
  externalFilter?: FilterCls;
  windowRunCount:  number;
  runsOrdered:     { run_sequence: number; display_name: string; started_at?: number | null }[];
}) {
  const [filterCls,   setFilterCls]   = useState<FilterCls>('all');
  const [filterOwner, setFilterOwner] = useState<string>('all');
  const [search,      setSearch]      = useState('');
  const [sortKey,     setSortKey]     = useState<SortKey>('failures');

  // Sync external filter from "View all" drill-down CTA
  useEffect(() => {
    if (externalFilter) {
      setFilterCls(externalFilter);
      setFilterOwner('all');
    }
  }, [externalFilter]);

  const entityLabel = dimension === 'owner' ? 'Owner' : 'Suite';

  // Per-run pass rate computed from all rows' run_history
  const runPassRates = new Map<number, number>(
    runsOrdered.map(run => {
      let passed = 0, total = 0;
      for (const row of rows) {
        const pt = row.run_history.find(p => p.run_sequence === run.run_sequence);
        if (pt && pt.status !== 'absent') {
          total++;
          if (pt.status === 'passed') passed++;
        }
      }
      return [run.run_sequence, total > 0 ? passed / total : 0];
    })
  );

  // Apply owner + search filters first so counts reflect what the user is looking at
  const ownerFiltered = rows
    .filter(r => filterOwner === 'all' || r.owner === filterOwner || r.suite_name === filterOwner)
    .filter(r => search === '' || r.display_name.toLowerCase().includes(search.toLowerCase()));

  const clsCounts = {
    all:     ownerFiltered.length,
    failing: ownerFiltered.filter(r => classifyRow(r) === 'failing').length,
    flaky:   ownerFiltered.filter(r => classifyRow(r) === 'flaky').length,
    stable:  ownerFiltered.filter(r => classifyRow(r) === 'stable').length,
  };

  const visible = ownerFiltered
    .filter(r => filterCls === 'all' || classifyRow(r) === filterCls)
    .sort((a, b) => {
      if (sortKey === 'failures') return failCount(b) - failCount(a);
      if (sortKey === 'suite')    return (a.suite ?? '').localeCompare(b.suite ?? '');
      if (sortKey === 'owner')    return (a.owner ?? a.suite_name ?? '').localeCompare(b.owner ?? b.suite_name ?? '');
      return a.display_name.localeCompare(b.display_name);
    });

  const filterBtns: { key: FilterCls; label: string; count: number }[] = [
    { key: 'all',     label: 'All',     count: clsCounts.all     },
    { key: 'failing', label: 'Broken',  count: clsCounts.failing },
    { key: 'flaky',   label: 'Flaky',   count: clsCounts.flaky   },
    { key: 'stable',  label: 'Stable',  count: clsCounts.stable  },
  ];

  return (
    <div id="entity-test-breakdown" className="space-y-3">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Test Breakdown</h3>
          <p className="mt-1 text-xs text-secondary">Showing run history across {windowRunCount} selected run{windowRunCount !== 1 ? 's' : ''}.</p>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 rounded-full border border-border-default bg-surface-subtle p-1">
          {filterBtns.map(f => (
            <button
              key={f.key}
              onClick={() => setFilterCls(f.key)}
              className={[
                'qalens-pill px-3 py-1.5',
                filterCls === f.key ? 'qalens-pill-active' : 'border-transparent bg-transparent hover:bg-hover',
              ].join(' ')}
            >
              <span>{f.label}</span>
              <span className="text-[10px] text-muted tabular-nums">({f.count})</span>
            </button>
          ))}
        </div>

        <Dropdown
          value={filterOwner}
          onChange={setFilterOwner}
          triggerClassName="px-3 py-2 text-sm"
          options={[
            { value: 'all', label: `All ${entityLabel}s` },
            ...labels.map(label => ({ value: label, label: label.split(' ')[0] })),
          ]}
        />

        <div className="qalens-control relative flex-1 min-w-[180px] max-w-xs">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter tests…"
            className="qalens-input pl-8 pr-3 py-2 text-sm"
          />
        </div>

        <Dropdown
          value={sortKey}
          onChange={value => setSortKey(value as SortKey)}
          triggerClassName="px-3 py-2 text-sm"
          options={[
            { value: 'failures', label: 'Sort: by failures' },
            { value: 'name',     label: 'Sort: by name'     },
            { value: 'suite',    label: 'Sort: by suite'    },
            { value: 'owner',    label: `Sort: by ${dimension}` },
          ]}
        />

        <span className="text-xs text-muted tabular-nums">{visible.length} of {rows.length} tests</span>
      </div>

      <div className="qalens-table-shell">
        <div className="overflow-x-auto" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgb(203 213 225) transparent' }}>
          <table className="qalens-table w-full text-sm border-collapse" style={{ minWidth: `${400 + runsOrdered.length * 72}px` }}>
            <thead className="qalens-table-head">
              <tr>
                {/* Sticky left: Test name */}
                <th className="text-left px-4 py-3 bg-surface-subtle"
                    style={{ position: 'sticky', left: 0, width: 280, minWidth: 280, zIndex: 2 }}>
                  Test
                </th>
                {/* Sticky left: Owner/Suite */}
                <th className="text-left px-4 py-3 bg-surface-subtle border-r border-border-subtle"
                    style={{ position: 'sticky', left: 280, width: 110, minWidth: 110, zIndex: 2 }}>
                  {entityLabel}
                </th>
                {/* Run columns */}
                {runsOrdered.map(run => {
                  const rate = runPassRates.get(run.run_sequence) ?? 0;
                  return (
                    <th key={run.run_sequence} className="text-center px-2 py-3" style={{ width: 72, minWidth: 72 }}>
                      <div className="flex flex-col items-center gap-0.5">
                        <span className="text-[10px] font-semibold">{run.display_name}</span>
                        {run.started_at && (
                          <span className="text-[9px] text-muted font-normal">{fmtRunDate(run.started_at)}</span>
                        )}
                        <span className={`text-[9px] font-medium ${runPassRateColor(rate)}`}>
                          {Math.round(rate * 100)}%
                        </span>
                      </div>
                    </th>
                  );
                })}
                {/* Sticky right: Status */}
                <th className="text-center px-4 py-3 bg-surface-subtle border-l border-border-subtle"
                    style={{ position: 'sticky', right: 56, width: 80, minWidth: 80, zIndex: 2 }}>
                  Status
                </th>
                {/* Sticky right: Fails */}
                <th className="text-center px-4 py-3 bg-surface-subtle"
                    style={{ position: 'sticky', right: 0, width: 56, minWidth: 56, zIndex: 2 }}>
                  Fails
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 ? (
                <tr>
                  <td colSpan={4 + runsOrdered.length} className="qalens-table-cell text-center py-12 text-muted">
                    No tests match the current filter
                  </td>
                </tr>
              ) : (
                visible.map(row => {
                  const cls    = classifyRow(row);
                  const fails  = failCount(row);
                  const entity = row.owner ?? row.suite_name ?? '';
                  return (
                    <tr key={row.canonical_name} className="qalens-table-row">
                      {/* Sticky left: Test name */}
                      <td className="qalens-table-cell px-4 py-3 bg-surface"
                          style={{ position: 'sticky', left: 0, zIndex: 1 }}>
                        <div className="space-y-0.5" style={{ maxWidth: 260 }}>
                          <div className="font-medium text-primary text-xs leading-snug break-words font-mono">
                            {row.display_name}
                          </div>
                          {row.suite && <div className="text-[10px] text-muted">{row.suite}</div>}
                        </div>
                      </td>
                      {/* Sticky left: Owner/Suite label */}
                      <td className="qalens-table-cell px-4 py-3 bg-surface border-r border-border-subtle"
                          style={{ position: 'sticky', left: 280, zIndex: 1 }}>
                        <span className="qalens-pill text-[11px]">{entity.split(' ')[0]}</span>
                      </td>
                      {/* Run result glyphs */}
                      {runsOrdered.map(run => {
                        const pt = row.run_history.find(p => p.run_sequence === run.run_sequence);
                        const status = pt?.status ?? 'absent';
                        return (
                          <td key={run.run_sequence} className="qalens-table-cell text-center px-2 py-3">
                            <RunStateGlyph status={status} seq={run.run_sequence} />
                          </td>
                        );
                      })}
                      {/* Sticky right: Status badge */}
                      <td className="qalens-table-cell text-center px-4 py-3 bg-surface border-l border-border-subtle"
                          style={{ position: 'sticky', right: 56, zIndex: 1 }}>
                        <ClassBadge cls={cls} />
                      </td>
                      {/* Sticky right: Fail count */}
                      <td className="qalens-table-cell text-center px-4 py-3 bg-surface"
                          style={{ position: 'sticky', right: 0, zIndex: 1 }}>
                        <span className={`text-sm font-semibold tabular-nums ${fails > 0 ? 'text-danger' : 'text-muted'}`}>
                          {fails}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Root: EntityComparisonView
// ─────────────────────────────────────────────────────────────

export function EntityComparisonView({ data }: { data: ApiEntityCompareResult }) {
  const ranked = rankEntities(data);

  const [drillFilter, setDrillFilter] = useState<FilterCls | null>(null);

  function handleViewAll(cls: FilterCls) {
    setDrillFilter(cls);
    setTimeout(() => {
      document.getElementById('entity-test-breakdown')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  const labels = [
    data.label_a,
    data.label_b,
    ...(data.label_c ? [data.label_c] : []),
  ];

  const cardGrid = ranked.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2';

  return (
    <div className="space-y-6">

      {/* 1. Ranked suite/owner cards */}
      <div className={`grid grid-cols-1 gap-4 ${cardGrid}`}>
        {ranked.map(entity => (
          <RankedCard
            key={entity.label}
            entity={entity}
            totalEntities={ranked.length}
          />
        ))}
      </div>

      {/* 2. Verdict + Narrative + Evidence drilldown */}
      <VerdictBanner ranked={ranked} runCount={data.run_count} onViewAll={handleViewAll} />

      {/* 3. Detailed test breakdown — externalFilter applied when user clicks "View all" from drill panel */}
      <EntityTestTable
        rows={data.rows}
        labels={labels}
        dimension={data.dimension}
        externalFilter={drillFilter ?? undefined}
        windowRunCount={data.run_count}
        runsOrdered={data.runs_ordered}
      />

    </div>
  );
}
