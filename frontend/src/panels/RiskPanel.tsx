import { useState, useEffect, useMemo, type ReactNode } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
import { Tooltip } from '../components/Tooltip';
import { useProject } from '../hooks/useProject';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

interface ApiRiskEntry {
  canonical_name:  string;
  display_name:    string;
  project:         string | null;
  suite:           string;
  module:          string;
  risk_score:      number;
  risk_pct:        number;
  tier:            'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  signals: {
    volatility:      number;
    failure_burden:  number;
    recent_decline:  number;
    fail_streak:     number;
    duration_spike:  number;
  };
  run_count:       number;
  pass_rate:       number;
  flip_score:      number;
  sparkline:       string;
  current_streak:  number;
  owner:           string;
}

// ─────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────

const TIER_ORDER: Array<'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'> = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

const TIER_CONFIG = {
  CRITICAL: { label: 'Critical', text: 'text-red-400',    badgeClass: 'qara-badge-danger',  ringTone: 'text-red-400',    cardBorder: 'border-red-500/30' },
  HIGH:     { label: 'High',     text: 'text-orange-400', badgeClass: 'qara-badge-warning', ringTone: 'text-orange-400', cardBorder: 'border-orange-500/30' },
  MEDIUM:   { label: 'Medium',   text: 'text-amber-400',  badgeClass: 'qara-badge-warning', ringTone: 'text-amber-400',  cardBorder: 'border-amber-500/30' },
  LOW:      { label: 'Low',      text: 'text-green-400',  badgeClass: 'qara-badge-success', ringTone: 'text-green-400',  cardBorder: 'border-green-500/30' },
} as const;

const SIGNAL_CONFIG: Record<string, { label: string; tooltip: string; badgeClass: string }> = {
  volatility:     { label: 'Volatile',    tooltip: 'Frequently switches between pass and fail.',         badgeClass: 'qara-badge-warning' },
  failure_burden: { label: 'Failing',     tooltip: 'High all-time failure rate.',                        badgeClass: 'qara-badge-danger' },
  recent_decline: { label: 'Declining',   tooltip: 'Recent runs have higher failure rate than average.', badgeClass: 'qara-badge-warning' },
  fail_streak:    { label: 'Fail Streak', tooltip: 'Currently on consecutive failing runs.',             badgeClass: 'qara-badge-danger' },
  duration_spike: { label: 'Slowing',     tooltip: 'Test is steadily getting slower.',                   badgeClass: 'qara-badge-neutral' },
};

function clampScore(value: number) {
  return Math.max(0, Math.min(1, value));
}

function failNextRunScore(signals: ApiRiskEntry['signals']) {
  return clampScore(
    0.45 * signals.failure_burden
    + 0.30 * signals.recent_decline
    + 0.20 * signals.fail_streak
    + 0.05 * signals.volatility,
  );
}

function flipNextRunScore(signals: ApiRiskEntry['signals']) {
  return clampScore(
    0.70 * signals.volatility
    + 0.20 * signals.recent_decline
    + 0.10 * signals.fail_streak,
  );
}

function scoreTier(score: number): keyof typeof TIER_CONFIG {
  if (score >= 0.62) return 'CRITICAL';
  if (score >= 0.41) return 'HIGH';
  if (score >= 0.24) return 'MEDIUM';
  return 'LOW';
}

type NextRunTier = 'Critical' | 'High' | 'Medium' | 'Low';

function nextRunTier(score: number): NextRunTier {
  if (score >= 0.85) return 'Critical';
  if (score >= 0.70) return 'High';
  if (score >= 0.40) return 'Medium';
  return 'Low';
}

// ─────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────

function RiskRing({ pct, tier }: { pct: number; tier: keyof typeof TIER_CONFIG }) {
  const r    = 14;
  const circ = 2 * Math.PI * r;
  const fill = Math.min((pct / 100) * circ, circ);
  const cfg  = TIER_CONFIG[tier] ?? TIER_CONFIG.LOW;

  return (
    <div
      className={`inline-flex h-11 w-11 items-center justify-center ${cfg.ringTone}`}
      aria-label={`${pct}% risk score`}
    >
      <svg width="44" height="44" viewBox="0 0 44 44" className="overflow-visible">
        <circle
          cx="22"
          cy="22"
          r={r}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.16"
          strokeWidth="4.5"
        />
        <circle
          cx="22"
          cy="22"
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth="4.5"
          strokeDasharray={`${fill} ${circ}`}
          strokeLinecap="round"
          transform="rotate(-90 22 22)"
        />
        <text
          x="22"
          y="22"
          textAnchor="middle"
          dominantBaseline="central"
          fill="currentColor"
          fontSize="9.5"
          fontWeight="800"
          fontFamily="Inter, ui-sans-serif, system-ui, sans-serif"
        >
          {pct}
        </text>
      </svg>
    </div>
  );
}

function TierBadge({ tier }: { tier: keyof typeof TIER_CONFIG }) {
  const cfg = TIER_CONFIG[tier] ?? TIER_CONFIG.LOW;
  return (
    <span className={`${cfg.badgeClass} shadow-[inset_0_1px_0_rgb(255_255_255_/_0.03)]`}>
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${cfg.ringTone.replace('text-', 'bg-')}`} />
      {cfg.label}
    </span>
  );
}

function SignalPills({ signals }: { signals: ApiRiskEntry['signals'] }) {
  const top2 = Object.entries(signals)
    .filter(([, v]) => v > 0.15)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 2);

  if (top2.length === 0) return <span className="text-xs text-zinc-600">—</span>;

  return (
    <div className="flex flex-wrap gap-1">
      {top2.map(([key]) => {
        const cfg = SIGNAL_CONFIG[key];
        if (!cfg) return null;
        return (
          <Tooltip key={key} content={cfg.tooltip} className="inline-flex">
            <span className={`${cfg.badgeClass} cursor-default px-2.5 py-1 shadow-[inset_0_1px_0_rgb(255_255_255_/_0.03)]`}>
              {cfg.label}
            </span>
          </Tooltip>
        );
      })}
    </div>
  );
}

function Sparkline({ sparkline }: { sparkline: string }) {
  const COLS = 7;
  const raw  = [...sparkline];

  const [tooltip, setTooltip] = useState<{ label: string; x: number; y: number } | null>(null);

  // Take last 28 runs (4 rows × 7 cols). Pad front to fill the grid left-to-right.
  const recent  = raw.slice(-COLS * 4);
  const leading = (COLS - (recent.length % COLS)) % COLS;
  const padded: (string | null)[] = [...Array(leading).fill(null), ...recent];

  // Split into rows — oldest row first, newest row last (GitHub direction)
  const rows: (string | null)[][] = [];
  for (let i = 0; i < padded.length; i += COLS) {
    rows.push(padded.slice(i, i + COLS));
  }

  function cellStyle(cell: string | null, rowIdx: number, totalRows: number): string {
    if (cell === null) return 'bg-zinc-900 opacity-0';
    const recency = (rowIdx + 1) / totalRows;
    if (cell === '\u2713') {
      return recency >= 0.75 ? 'bg-green-400'
           : recency >= 0.5  ? 'bg-green-500/80'
           : recency >= 0.25 ? 'bg-green-600/60'
           :                   'bg-green-700/40';
    }
    return recency >= 0.75 ? 'bg-red-400'
         : recency >= 0.5  ? 'bg-red-500/80'
         : recency >= 0.25 ? 'bg-red-600/60'
         :                   'bg-red-700/40';
  }

  const runIndex = (ri: number, ci: number) =>
    raw.length - recent.length + (ri * COLS + ci - leading);

  return (
    <div className="inline-flex flex-col gap-[3px]">
      {rows.map((row, ri) => (
        <div key={ri} className="flex gap-[3px]">
          {row.map((cell, ci) => {
            if (cell === null) {
              return (
                <span
                  key={ci}
                  className="inline-block w-[10px] h-[10px] rounded-[2px] opacity-0"
                />
              );
            }
            const idx   = runIndex(ri, ci);
            const label = cell === '\u2713'
              ? `Passed. Run #${idx + 1}`
              : `Failed. Run #${idx + 1}`;
            return (
              <span
                key={ci}
                className={`inline-block w-[10px] h-[10px] rounded-[2px] cursor-default ${cellStyle(cell, ri, rows.length)}`}
                onMouseEnter={e => {
                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  setTooltip({ label, x: rect.left + rect.width / 2, y: rect.top });
                }}
                onMouseLeave={() => setTooltip(null)}
              />
            );
          })}
        </div>
      ))}

      {tooltip && (
        <div
          className="fixed z-50 px-2 py-1 rounded-md bg-zinc-800 border border-zinc-700
                     text-xs text-zinc-100 whitespace-nowrap pointer-events-none shadow-lg"
          style={{ left: tooltip.x, top: tooltip.y - 30, transform: 'translateX(-50%)' }}
        >
          {tooltip.label}
        </div>
      )}
    </div>
  );
}

function InlineIcon({
  tone,
  children,
}: {
  tone: string;
  children: React.ReactNode;
}) {
  return (
    <span className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border ${tone}`}>
      {children}
    </span>
  );
}

function DecisionTierBadge({ tier, accent }: { tier: NextRunTier; accent: 'fail' | 'flip' }) {
  const tone =
    tier === 'Critical' ? 'border-red-200 bg-red-50 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
    : tier === 'High' ? accent === 'flip'
      ? 'border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300'
      : 'border-orange-200 bg-orange-50 text-orange-600 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300'
    : tier === 'Medium' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300'
    : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300';

  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-sm font-semibold ${tone}`}>
      {tier}
    </span>
  );
}

function RiskDecisionMetric({
  kind,
  score,
  helperText,
}: {
  kind: 'fail' | 'flip';
  score: number;
  helperText: string;
}) {
  const tier = nextRunTier(score);
  const pct = Math.round(score * 100);
  const isFail = kind === 'fail';
  const tone = isFail
    ? 'border-red-100 bg-gradient-to-br from-red-50 via-white to-orange-50/70 dark:border-red-500/20 dark:from-red-500/10 dark:via-slate-950 dark:to-orange-500/10'
    : 'border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50/80 dark:border-indigo-500/20 dark:from-indigo-500/10 dark:via-slate-950 dark:to-violet-500/10';
  const iconTone = isFail
    ? 'border-red-100 bg-red-50 text-red-500 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300'
    : 'border-indigo-100 bg-indigo-50 text-indigo-600 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-300';
  const valueTone = isFail ? 'text-red-500 dark:text-red-300' : 'text-indigo-600 dark:text-indigo-300';

  return (
    <div className={`rounded-2xl border p-5 ${tone}`}>
      <div className="flex items-center gap-4">
        <InlineIcon tone={iconTone}>
          {isFail ? (
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 16l5-5 4 4 7-7" />
              <path d="M18 8h2v2" />
              <path d="M4 20h16" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 2l4 4-4 4" />
              <path d="M3 11V9a4 4 0 0 1 4-4h14" />
              <path d="M7 22l-4-4 4-4" />
              <path d="M21 13v2a4 4 0 0 1-4 4H3" />
            </svg>
          )}
        </InlineIcon>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {isFail ? 'Fail next run' : 'Flip next run'}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className={`text-4xl font-semibold tracking-tight ${valueTone}`}>
              {pct}%
            </span>
            <DecisionTierBadge tier={tier} accent={kind} />
          </div>
          <p className="mt-3 text-base leading-7 text-slate-600 dark:text-slate-300">
            {helperText}
          </p>
        </div>
      </div>
    </div>
  );
}

function riskDrivers(entry: ApiRiskEntry) {
  const items = [
    {
      key: 'volatility',
      value: entry.signals.volatility,
      iconTone: 'border-orange-100 bg-orange-50 text-orange-500 dark:border-orange-500/20 dark:bg-orange-500/10 dark:text-orange-300',
      text: `High volatility (${Math.round(entry.signals.volatility * 100)}%)`,
      suffix: 'frequent status flips',
      icon: (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 12h4l3-7 4 14 3-7h4" />
        </svg>
      ),
    },
    {
      key: 'failure_burden',
      value: entry.signals.failure_burden,
      iconTone: 'border-red-100 bg-red-50 text-red-500 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300',
      text: `Failure rate is elevated (${Math.round(entry.signals.failure_burden * 100)}%)`,
      suffix: '',
      icon: (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 9v4" />
          <path d="M12 17h.01" />
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
        </svg>
      ),
    },
    {
      key: 'recent_decline',
      value: entry.signals.recent_decline,
      iconTone: 'border-amber-100 bg-amber-50 text-amber-600 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300',
      text: `Early signs of decline (${Math.round(entry.signals.recent_decline * 100)}%)`,
      suffix: '',
      icon: (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 17h5l3-5 4 3 6-8" />
          <path d="M17 7h4v4" />
        </svg>
      ),
    },
    {
      key: 'fail_streak',
      value: entry.signals.fail_streak,
      iconTone: 'border-rose-100 bg-rose-50 text-rose-500 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300',
      text: `Current fail streak: ${entry.current_streak < 0 ? Math.abs(entry.current_streak) : 0}`,
      suffix: '',
      icon: (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5" />
          <path d="M12 16h.01" />
        </svg>
      ),
    },
    {
      key: 'duration_spike',
      value: entry.signals.duration_spike,
      iconTone: 'border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300',
      text: `Execution time is slowing (${Math.round(entry.signals.duration_spike * 100)}%)`,
      suffix: '',
      icon: (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="13" r="8" />
          <path d="M12 9v4l2.5 2.5" />
          <path d="M9 2h6" />
        </svg>
      ),
    },
  ];

  return items
    .filter(item => item.key === 'fail_streak' ? entry.current_streak < 0 : item.value > 0.05)
    .sort((a, b) => b.value - a.value);
}

function meaningText(failScore: number, flipScore: number) {
  const failText = failScore >= 0.7 ? 'high' : failScore >= 0.4 ? 'moderate' : 'low';
  const flipText = flipScore >= 0.7 ? 'high' : flipScore >= 0.4 ? 'moderate' : 'low';
  return `This test is unstable and has a ${flipText} chance of changing state again. There is a ${failText} chance it will fail in the next run.`;
}

function SupportingMetric({
  iconTone,
  label,
  value,
  icon,
  className = '',
}: {
  iconTone: string;
  label: string;
  value: string;
  icon: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <InlineIcon tone={iconTone}>
        {icon}
      </InlineIcon>
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
          {label}
        </p>
        <p className="mt-1 text-[1.05rem] font-semibold text-slate-950 dark:text-slate-50">
          {value}
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Stat cards
// ─────────────────────────────────────────────────────────────

function StatCards({ data }: { data: ApiRiskEntry[] }) {
  const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
  for (const d of data) counts[d.tier] = (counts[d.tier] ?? 0) + 1;

  return (
    <div className="qara-stat-grid">
      {TIER_ORDER.map(tier => {
        const cfg = TIER_CONFIG[tier];
        return (
          <div key={tier} className={`qara-stat-card ${cfg.cardBorder}`}>
            <span className="type-metric-label">{cfg.label}</span>
            <span className={`type-metric-value ${cfg.text}`}>
              {counts[tier]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Filter bar
// ─────────────────────────────────────────────────────────────

interface Filters {
  search: string;
  tier:   string;
  module: string;
  owner:  string;
}

function FilterBar({
  filters,
  onChange,
  modules,
  owners,
}: {
  filters:  Filters;
  onChange: (f: Filters) => void;
  modules:  string[];
  owners:   string[];
}) {
  return (
    <div className="qara-toolbar">
      {/* Search */}
      <div className="relative flex-1 min-w-[200px] max-w-xs">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500"
             viewBox="0 0 16 16" fill="none">
          <circle cx="6.5" cy="6.5" r="4" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M10 10l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
        <input
          type="text"
          placeholder="Search tests…"
          value={filters.search}
          onChange={e => onChange({ ...filters, search: e.target.value })}
          className="qara-control qara-input type-input w-full pl-9 pr-3"
        />
      </div>

      {/* Tier */}
      <Dropdown
        value={filters.tier}
        onChange={value => onChange({ ...filters, tier: value })}
        triggerClassName="px-3.5 text-sm"
        options={[
          { value: '', label: 'All tiers' },
          ...TIER_ORDER.map(tier => ({ value: tier, label: TIER_CONFIG[tier].label })),
        ]}
      />

      {/* Module */}
      {modules.length > 0 && (
        <Dropdown
          value={filters.module}
          onChange={value => onChange({ ...filters, module: value })}
          triggerClassName="px-3.5 text-sm"
          options={[
            { value: '', label: 'All modules' },
            ...modules.map(module => ({ value: module, label: module })),
          ]}
        />
      )}

      {/* Owner */}
      {owners.length > 0 && (
        <Dropdown
          value={filters.owner}
          onChange={value => onChange({ ...filters, owner: value })}
          triggerClassName="px-3.5 text-sm"
          options={[
            { value: '', label: 'All owners' },
            ...owners.map(owner => ({ value: owner, label: owner })),
          ]}
        />
      )}

      {/* Clear */}
      {(filters.search || filters.tier || filters.module || filters.owner) && (
        <button
          onClick={() => onChange({ search: '', tier: '', module: '', owner: '' })}
          className="qara-chip type-chip"
        >
          Clear
        </button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Risk table row
// ─────────────────────────────────────────────────────────────

function RiskRow({ entry }: { entry: ApiRiskEntry }) {
  const [expanded, setExpanded] = useState(false);
  const nextFail = failNextRunScore(entry.signals);
  const nextFlip = flipNextRunScore(entry.signals);
  const drivers = riskDrivers(entry);
  const suiteLabel = entry.suite || entry.module || 'Unknown suite';

  return (
    <>
      <tr
        className="qara-table-row cursor-pointer"
        onClick={() => setExpanded(o => !o)}
      >
        {/* Test name */}
        <td className="qara-table-cell">
          <Tooltip content={entry.display_name} className="block max-w-[260px]">
            <div className="type-td-primary truncate">
              {entry.display_name}
            </div>
          </Tooltip>
          <div className="type-td-secondary truncate">{entry.module}</div>
        </td>

        {/* Owner */}
        <td className="qara-table-cell type-td-secondary whitespace-nowrap">
          {entry.owner || '—'}
        </td>

        {/* Risk ring */}
        <td className="qara-table-cell">
          <RiskRing pct={entry.risk_pct} tier={entry.tier} />
        </td>

        {/* Tier */}
        <td className="qara-table-cell">
          <TierBadge tier={entry.tier} />
        </td>

        {/* Signals */}
        <td className="qara-table-cell">
          <SignalPills signals={entry.signals} />
        </td>

        {/* Sparkline */}
        <td className="qara-table-cell">
          <Sparkline sparkline={entry.sparkline} />
        </td>

        {/* Run count */}
        <td className="qara-table-cell type-td-num text-right">
          {entry.run_count}
        </td>

        {/* Expand chevron */}
        <td className="qara-table-cell text-zinc-600">
          <svg className={`w-4 h-4 transition-transform ${expanded ? 'rotate-90' : ''}`}
               viewBox="0 0 16 16" fill="none">
            <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </td>
      </tr>

      {/* Expanded detail */}
      {expanded && (
        <tr className="qara-table-row">
          <td colSpan={8} className="px-6 pb-5">
            <div className="overflow-hidden rounded-b-2xl border border-t-0 border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
              <div className="grid grid-cols-1 gap-6 border-b border-slate-200 px-6 py-5 lg:grid-cols-2 lg:divide-x lg:divide-slate-200 dark:border-slate-800 dark:lg:divide-slate-800">
                <RiskDecisionMetric
                  kind="fail"
                  score={nextFail}
                  helperText="Chance that this test will fail in the next run"
                />
                <div className="lg:pl-6">
                  <RiskDecisionMetric
                    kind="flip"
                    score={nextFlip}
                    helperText="Chance that this test will change state in the next run"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-6 border-b border-slate-200 px-6 py-5 lg:grid-cols-2 lg:divide-x lg:divide-slate-200 dark:border-slate-800 dark:lg:divide-slate-800">
                <div>
                  <h4 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
                    Why this is risky
                  </h4>
                  <ul className="mt-5 space-y-4">
                    {drivers.map(driver => (
                      <li key={driver.key} className="flex items-start gap-3">
                        <InlineIcon tone={driver.iconTone}>
                          {driver.icon}
                        </InlineIcon>
                        <p className="pt-2 text-[1.1rem] leading-8 text-slate-700 dark:text-slate-200">
                          <span className="font-medium text-slate-950 dark:text-slate-50">{driver.text}</span>
                          {driver.suffix ? <span className="text-slate-500 dark:text-slate-400"> — {driver.suffix}</span> : null}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="lg:pl-6">
                  <div className="h-full rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
                    <div className="flex items-center gap-2 text-blue-700 dark:text-blue-300">
                      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 18h6" />
                        <path d="M10 22h4" />
                        <path d="M12 2a7 7 0 0 0-4 12.75c.58.41 1 1.02 1.18 1.7h5.64c.18-.68.6-1.29 1.18-1.7A7 7 0 0 0 12 2Z" />
                      </svg>
                      <h4 className="text-xl font-semibold">What this means</h4>
                    </div>
                    <p className="mt-4 text-[1.1rem] leading-9 text-slate-700 dark:text-slate-200">
                      {meaningText(nextFail, nextFlip)}
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 px-6 py-4 md:grid-cols-5">
                <SupportingMetric
                  iconTone="border-emerald-100 bg-emerald-50 text-emerald-600 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
                  label="Pass rate"
                  value={`${(entry.pass_rate * 100).toFixed(1)}%`}
                  icon={
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="m9 12 2 2 4-4" />
                      <rect x="3" y="3" width="18" height="18" rx="4" />
                    </svg>
                  }
                />
                <SupportingMetric
                  className="md:border-l md:border-slate-200 md:pl-4 dark:md:border-slate-800"
                  iconTone="border-indigo-100 bg-indigo-50 text-indigo-600 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-300"
                  label="Flip score"
                  value={`${(entry.flip_score * 100).toFixed(1)}%`}
                  icon={
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M17 2l4 4-4 4" />
                      <path d="M3 11V9a4 4 0 0 1 4-4h14" />
                      <path d="M7 22l-4-4 4-4" />
                      <path d="M21 13v2a4 4 0 0 1-4 4H3" />
                    </svg>
                  }
                />
                <SupportingMetric
                  className="md:border-l md:border-slate-200 md:pl-4 dark:md:border-slate-800"
                  iconTone="border-red-100 bg-red-50 text-red-500 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
                  label="Current streak"
                  value={entry.current_streak < 0 ? `${Math.abs(entry.current_streak)} fail${Math.abs(entry.current_streak) === 1 ? '' : 's'}` : entry.current_streak > 0 ? `${entry.current_streak} passes` : '—'}
                  icon={
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="9" />
                      <path d="M12 7v5" />
                      <path d="M12 16h.01" />
                    </svg>
                  }
                />
                <SupportingMetric
                  className="md:border-l md:border-slate-200 md:pl-4 dark:md:border-slate-800"
                  iconTone="border-blue-100 bg-blue-50 text-blue-600 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300"
                  label="Suite"
                  value={suiteLabel}
                  icon={
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 7.5h18" />
                      <path d="M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" />
                    </svg>
                  }
                />
                <SupportingMetric
                  className="md:border-l md:border-slate-200 md:pl-4 dark:md:border-slate-800"
                  iconTone="border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                  label="Runs"
                  value={String(entry.run_count)}
                  icon={
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="4" width="18" height="18" rx="3" />
                      <path d="M16 2v4" />
                      <path d="M8 2v4" />
                      <path d="M3 10h18" />
                    </svg>
                  }
                />
              </div>

              <div className="flex flex-col gap-3 border-t border-slate-200 px-6 py-5 md:flex-row md:items-center md:justify-between dark:border-slate-800">
                <div className="flex items-start gap-3 text-sm text-slate-500 dark:text-slate-400">
                  <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 text-slate-400 dark:border-slate-700 dark:text-slate-500">
                    i
                  </span>
                  <p className="max-w-4xl leading-6">
                    Risk score is a priority signal, not a direct failure probability. It combines multiple factors—like volatility, failure rate, recent decline, and fail streak—to help you decide what needs attention first.
                    <br /><br />
                    <strong>Fail next run</strong> → how likely the test will fail again.{' '}
                    <strong>Flip next run</strong> → how likely the test will change state (pass ↔ fail).
                  </p>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// RiskPanel
// ─────────────────────────────────────────────────────────────

export function RiskPanel() {
  const { currentProject } = useProject();

  const [data,    setData]    = useState<ApiRiskEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({ search: '', tier: '', module: '', owner: '' });

  // Fetch risk data
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData([]);

    const params = new URLSearchParams();
    if (currentProject) params.set('project', currentProject);

    fetch(`/api/risk?${params}`)
      .then(r => r.ok ? r.json() as Promise<ApiRiskEntry[]> : Promise.reject(`API ${r.status}`))
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [currentProject]);

  // Unique modules and owners for filter dropdowns
  const modules = useMemo(() => [...new Set(data.map(d => d.module).filter(Boolean))].sort(), [data]);
  const owners  = useMemo(() => [...new Set(data.map(d => d.owner).filter(Boolean))].sort(), [data]);

  // Client-side filtering
  const filtered = useMemo(() => {
    const q = filters.search.toLowerCase();
    return data.filter(d => {
      if (filters.tier   && d.tier   !== filters.tier)   return false;
      if (filters.module && d.module !== filters.module) return false;
      if (filters.owner  && d.owner  !== filters.owner)  return false;
      if (q && !d.display_name.toLowerCase().includes(q) &&
               !d.canonical_name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data, filters]);

  return (
    <div className="qara-page">

      {/* Page header */}
      <PageHeader
        tier="full"
        kicker="Predictive Quality"
        title="Risk"
        description="Prioritize tests most likely to fail next using volatility, streak, burden, and slowdown signals."
        icon="🎯"
      />

      {/* Loading */}
      {loading && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-12 rounded-xl bg-zinc-800" />
          ))}
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="qara-error-banner">
          <span>⚠️</span>
          <span>Failed to load risk data: {error}</span>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Stat cards */}
          {data.length > 0 && <StatCards data={data} />}

          {/* Filter bar */}
          <FilterBar
            filters={filters}
            onChange={setFilters}
            modules={modules}
            owners={owners}
          />

          {/* Empty state */}
          {filtered.length === 0 && data.length === 0 && (
            <div className="qara-empty-state">
              <div className="qara-empty-icon">✅</div>
              <p className="type-empty-title">No risk predictions available</p>
              <p className="type-empty-subtitle max-w-xs">
                Ingest more runs to generate risk scores (minimum 2 runs per test).
              </p>
            </div>
          )}

          {filtered.length === 0 && data.length > 0 && (
            <div className="qara-empty-state">
              <p className="type-empty-title">No tests match the current filters</p>
              <button
                onClick={() => setFilters({ search: '', tier: '', module: '', owner: '' })}
                className="qara-chip type-chip"
              >
                Clear filters
              </button>
            </div>
          )}

          {/* Table */}
          {filtered.length > 0 && (
            <div className="qara-table-shell">
              {/* Result count */}
              <div className="px-4 py-2.5 border-b border-zinc-800 bg-zinc-900">
                <span className="qara-inline-note">
                  {filtered.length === data.length
                    ? `${data.length} tests`
                    : `${filtered.length} of ${data.length} tests`}
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="qara-table w-full">
                  <thead className="qara-table-head">
                    <tr>
                      <th className="text-left">
                        Test
                      </th>
                      <th className="text-left">
                        Owner
                      </th>
                      <th className="text-left">
                        <Tooltip
                          content="Composite risk score used for prioritization. It is not a literal probability of failure."
                          className="inline-flex"
                        >
                          <span>Risk Score</span>
                        </Tooltip>
                      </th>
                      <th className="text-left">
                        Tier
                      </th>
                      <th className="text-left">
                        <Tooltip
                          content="Top contributing signals. Expand a row to see the full signal breakdown and percentages."
                          className="inline-flex"
                        >
                          <span>Signals</span>
                        </Tooltip>
                      </th>
                      <th className="text-left">
                        History
                      </th>
                      <th className="text-right">
                        Runs
                      </th>
                      <th className="w-8" />
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(entry => (
                      <RiskRow key={entry.canonical_name} entry={entry} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

    </div>
  );
}
