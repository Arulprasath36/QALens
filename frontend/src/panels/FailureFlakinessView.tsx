import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import type { ApiIncident } from './IncidentsPanel';
import { useProject } from '../hooks/useProject';
import { Tooltip } from '../components/Tooltip';
import { RegressionsView } from './RegressionsView';

type CellState = 'passed' | 'failed' | 'broken' | 'skipped' | 'absent' | string;
type StatusFilter = 'all' | 'failed' | 'flaky' | 'regressed' | 'recovered' | 'stable';

interface ApiStatusSummary {
  passed: number;
  failed: number;
  skipped: number;
  total: number;
}

interface ApiHistoryRun {
  run_id: string;
  run_sequence: number;
  display_name: string;
  started_at: number | null;
  branch: string | null;
  build_number: string | null;
  report_format: string;
  status_summary: ApiStatusSummary;
}

interface ApiHistoryCell {
  run_id: string;
  state: CellState;
  fingerprint: string | null;
  error_type: string | null;
  message: string | null;
  root_cause_category: string | null;
  is_latest_change: boolean;
  tooltip: string;
}

interface ApiHistoryRow {
  canonical_name: string;
  display_name: string;
  suite: string | null;
  feature: string | null;
  owner: string | null;
  tags: string[];
  health: {
    pass_rate: number;
    flip_score: number;
    classification: string;
  };
  cells: ApiHistoryCell[];
}

interface ApiHistoryResult {
  project: string | null;
  report_format: string;
  runs: ApiHistoryRun[];
  summary: {
    window_size: number;
    unique_tests: number;
    flaky_tests: number;
    consistently_broken: number;
    stable_tests: number;
    new_failures_latest: number;
    fixed_latest: number;
    insufficient_history: number;
  };
  rows: ApiHistoryRow[];
  facets: {
    suites: string[];
    owners: string[];
    features: string[];
    modules: string[];
  };
}

interface ApiFailureGroup {
  fingerprint: string;
  occurrence_count: number;
  affected_tests: number;
  affected_runs: number;
  error_type: string | null;
  message: string;
  first_seen_seq: number | null;
  last_seen_seq: number | null;
  affected_canonical_names: string[];
  bug_links?: { id: number; bug_url: string; label: string }[];
  category: string;
  scope: 'window' | 'all_time';
  window_size: number | null;
}

const FILTER_LABELS: Record<StatusFilter, string> = {
  all:       'All',
  failed:    'Failed',
  flaky:     'Flaky',
  regressed: 'New regressions',
  recovered: 'Recovered',
  stable:    'Stable overall',
};

const STATUS_CARD_STYLE: Record<StatusFilter, string> = {
  all:       'border-info/18 bg-info/[0.035] text-info',
  failed:    'border-danger/18 bg-danger/[0.045] text-danger',
  flaky:     'border-warning/20 bg-warning/[0.055] text-warning',
  regressed: 'border-danger/18 bg-danger/[0.04] text-danger',
  recovered: 'border-success/18 bg-success/[0.05] text-success',
  stable:    'border-success/18 bg-success/[0.04] text-success',
};

const TRANSITION_META: Record<string, { label: string; sublabel: string; primary: boolean; tone: 'danger' | 'success' | 'warning' }> = {
  'Passed → Failed': { label: 'New regressions',    sublabel: 'Passed → Failed', primary: true,  tone: 'danger'  },
  'Failed → Passed': { label: 'Recovered',           sublabel: 'Failed → Passed', primary: true,  tone: 'success' },
  'Failed → Failed': { label: 'Existing failures',  sublabel: 'Failed → Failed', primary: false, tone: 'warning' },
  'Passed → Passed': { label: 'Currently passing',   sublabel: 'Passed → Passed', primary: false, tone: 'warning' },
};

const SOFT_DANGER_BADGE_STYLE: CSSProperties = {
  background: 'rgb(var(--danger-rgb) / 0.08)',
  borderColor: 'rgb(var(--danger-rgb) / 0.16)',
  color: 'rgb(var(--danger-rgb) / 0.9)',
};

// ─────────────────────────────────────────────────────────────
// Row helpers
// ─────────────────────────────────────────────────────────────

function isFailure(state?: CellState | null)  { return state === 'failed' || state === 'broken'; }
function isPassing(state?: CellState | null)   { return state === 'passed'; }

function readableState(state?: CellState | null) {
  if (state === 'broken' || state === 'failed') return 'Failed';
  if (state === 'passed')  return 'Passed';
  if (state === 'skipped') return 'Skipped';
  return 'Absent';
}

function latestCell(row: ApiHistoryRow)   { return row.cells[row.cells.length - 1] ?? null; }
function baselineCell(row: ApiHistoryRow) { return row.cells.find(c => c.state !== 'absent') ?? row.cells[0] ?? null; }
function failureCount(row: ApiHistoryRow) { return row.cells.filter(c => isFailure(c.state)).length; }

function flipCount(row: ApiHistoryRow) {
  const states = row.cells.filter(c => c.state !== 'absent').map(c => isPassing(c.state));
  let flips = 0;
  for (let i = 1; i < states.length; i++) if (states[i] !== states[i - 1]) flips++;
  return flips;
}

function isFlaky(row: ApiHistoryRow)     { return row.health.classification === 'FLAKY'; }
function isRegression(row: ApiHistoryRow) {
  return isPassing(baselineCell(row)?.state) && isFailure(latestCell(row)?.state);
}
function isRecovered(row: ApiHistoryRow) {
  return isFailure(baselineCell(row)?.state) && isPassing(latestCell(row)?.state);
}
function isStable(row: ApiHistoryRow) {
  return row.health.classification === 'STABLE' && isPassing(latestCell(row)?.state);
}
function transitionKey(row: ApiHistoryRow) {
  return `${readableState(baselineCell(row)?.state)} → ${readableState(latestCell(row)?.state)}`;
}

function primaryStatus(row: ApiHistoryRow): StatusFilter {
  if (isRegression(row))              return 'regressed';
  if (isFailure(latestCell(row)?.state)) return 'failed';
  if (isFlaky(row))                   return 'flaky';
  if (isRecovered(row))               return 'recovered';
  if (isStable(row))                  return 'stable';
  return 'all';
}

function statusBadge(row: ApiHistoryRow) {
  const status = primaryStatus(row);
  const label  = status === 'all'
    ? (isPassing(latestCell(row)?.state) ? 'Passing now' : readableState(latestCell(row)?.state))
    : FILTER_LABELS[status];
  const toneClass = (status === 'all' && (label === 'Passed' || label === 'Passing now'))
    ? 'border-success/18 bg-success/[0.05] text-success'
    : STATUS_CARD_STYLE[status];
  const toneStyle = label === 'Failed' ? SOFT_DANGER_BADGE_STYLE : undefined;
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass}`} style={toneStyle}>
      {label}
    </span>
  );
}

function pct(value: number) { return `${Math.round(value * 100)}%`; }

function passRateToneClass(value: number) {
  if (value >= 0.8) return 'text-success';
  if (value >= 0.5) return 'text-warning';
  return 'text-danger';
}

function fmtTs(ts: number | null) {
  if (ts == null) return '';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function groupConcentration(rows: ApiHistoryRow[], key: 'owner' | 'suite') {
  const map = new Map<string, { label: string; failed: number; flaky: number; regressed: number; total: number; totalTests: number }>();
  for (const row of rows) {
    const label  = (key === 'owner' ? row.owner : row.suite) || 'Unassigned';
    const bucket = map.get(label) ?? { label, failed: 0, flaky: 0, regressed: 0, total: 0, totalTests: 0 };
    bucket.totalTests++;
    const failed    = isFailure(latestCell(row)?.state);
    const flaky     = isFlaky(row);
    const regressed = isRegression(row);
    if (failed || flaky || regressed) {
      bucket.total++;
      if (failed)    bucket.failed++;
      if (flaky)     bucket.flaky++;
      if (regressed) bucket.regressed++;
    }
    map.set(label, bucket);
  }
  return [...map.values()].filter(v => v.total > 0).sort((a, b) => b.total - a.total).slice(0, 6);
}

function relatedIncident(row: ApiHistoryRow, incidents: ApiIncident[]) {
  return incidents.find(inc =>
    inc.impacted_tests.some(test =>
      test === row.canonical_name || test === row.display_name ||
      test.includes(row.display_name) || row.display_name.includes(test),
    ),
  );
}

// ─────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div>
      <p className="type-eyebrow">{title}</p>
      {subtitle && <p className="mt-1 text-sm text-secondary">{subtitle}</p>}
    </div>
  );
}

function OverflowTooltipLabel({
  label,
  content,
  className,
  innerClassName,
  innerStyle,
  showOnOverflowOnly = true,
}: {
  label: string;
  content?: ReactNode;
  className?: string;
  innerClassName?: string;
  innerStyle?: CSSProperties;
  showOnOverflowOnly?: boolean;
}) {
  const labelRef = useRef<HTMLSpanElement | null>(null);
  const [isOverflowed, setIsOverflowed] = useState(false);

  useEffect(() => {
    const node = labelRef.current;
    if (!node) return;

    const updateOverflow = () => {
      setIsOverflowed(node.scrollWidth > node.clientWidth || node.scrollHeight > node.clientHeight);
    };

    updateOverflow();

    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(updateOverflow);
      observer.observe(node);
      return () => observer.disconnect();
    }

    window.addEventListener('resize', updateOverflow);
    return () => window.removeEventListener('resize', updateOverflow);
  }, [label]);

  return (
    <Tooltip
      content={content ?? label}
      className={className}
      disabled={showOnOverflowOnly ? !isOverflowed : false}
    >
      <span ref={labelRef} className={innerClassName} style={innerStyle}>
        {label}
      </span>
    </Tooltip>
  );
}

function RunWindowStrip({
  cells,
  size = 'sm',
}: {
  cells: ApiHistoryCell[];
  size?: 'sm' | 'md';
}) {
  const classes = size === 'md'
    ? 'inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-semibold'
    : 'inline-flex h-4 w-4 items-center justify-center rounded-full border text-[9px] font-semibold';

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {cells.map((cell, idx) => {
        const passing = isPassing(cell.state);
        const failing = isFailure(cell.state);
        const tone = passing
          ? 'border-success/25 bg-success/[0.08] text-success'
          : failing
          ? 'border-danger/25 bg-danger/[0.08] text-danger'
          : 'border-border-default bg-surface-subtle text-muted';
        return (
          <span
            key={`${cell.run_id}-${idx}`}
            className={`${classes} ${tone}`}
          >
            {passing ? '✓' : failing ? '×' : '•'}
          </span>
        );
      })}
    </span>
  );
}

function CompositeBar({ total, regressed, max, totalTests }: { total: number; regressed: number; max: number; totalTests: number }) {
  const totalPct  = max > 0 ? Math.max(total > 0 ? 5 : 0, Math.round((total / max) * 100)) : 0;
  const regrShare = total > 0 ? Math.round((regressed / total) * 100) : 0;
  const existing  = total - regressed;
  return (
    <Tooltip
      content={
        <div className="space-y-1 text-[11px]">
          <div className="text-muted mb-1">{totalTests} test{totalTests !== 1 ? 's' : ''} total</div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-border-strong/70 shrink-0" />
            <span><strong>{total}</strong> unstable ({existing} existing{regressed > 0 ? `, ${regressed} new` : ''})</span>
          </div>
          {regressed > 0 && (
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-danger/80 shrink-0" />
              <span><strong>{regressed}</strong> new regression{regressed !== 1 ? 's' : ''} this window</span>
            </div>
          )}
        </div>
      }
    >
      <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-subtle cursor-default">
        <div className="absolute left-0 top-0 h-full rounded-full bg-border-strong/50" style={{ width: `${totalPct}%` }} />
        {regressed > 0 && (
          <div className="absolute left-0 top-0 h-full rounded-full bg-danger/70" style={{ width: `${Math.round(totalPct * regrShare / 100)}%` }} />
        )}
      </div>
    </Tooltip>
  );
}

function ConcentrationBar({
  total,
  regressed,
  max,
  totalTests,
  isWindowAnalysis,
}: {
  total: number;
  regressed: number;
  max: number;
  totalTests: number;
  isWindowAnalysis: boolean;
}) {
  if (!isWindowAnalysis) {
    const totalPct = max > 0 ? Math.max(total > 0 ? 5 : 0, Math.round((total / max) * 100)) : 0;
    return (
      <Tooltip
        content={
          <div className="space-y-1 text-[11px]">
            <div className="text-muted mb-1">{totalTests} test{totalTests !== 1 ? 's' : ''} total</div>
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-danger/80 shrink-0" />
              <span><strong>{total}</strong> failed in this run</span>
            </div>
          </div>
        }
      >
        <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-subtle cursor-default">
          <div className="absolute left-0 top-0 h-full rounded-full bg-danger/70" style={{ width: `${totalPct}%` }} />
        </div>
      </Tooltip>
    );
  }

  return <CompositeBar total={total} regressed={regressed} max={max} totalTests={totalTests} />;
}

/**
 * ConcentrationPanel — merged Owner + Suite view with internal segmented toggle.
 * Replaces the previous two-column OwnerResponsibilityList + SuiteConcentrationList.
 * Both lenses answer the same question ("where is failure concentrated?") so they
 * share one card with one toggle, halving vertical space and visual noise.
 */
function ConcentrationPanel({
  ownerRows,
  suiteRows,
  isWindowAnalysis,
}: {
  ownerRows: ReturnType<typeof groupConcentration>;
  suiteRows: ReturnType<typeof groupConcentration>;
  isWindowAnalysis: boolean;
}) {
  const [mode, setMode] = useState<'owner' | 'suite'>('owner');
  const rows = mode === 'owner' ? ownerRows : suiteRows;
  const max  = Math.max(1, ...rows.map(r => r.total));

  return (
    <div className="qara-card p-5">
      <div className="flex items-start justify-between gap-3">
        <SectionTitle
          title="Concentration"
          subtitle={mode === 'owner' ? 'Who should investigate first' : 'Where failures are concentrated'}
        />
        <div className="qara-toolbar-segment shrink-0" role="tablist" aria-label="Group failures by">
          {(['owner', 'suite'] as const).map(m => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={['qara-segment-button', mode === m ? 'qara-segment-button-active' : ''].join(' ')}
            >
              {m === 'owner' ? 'Owner' : 'Suite'}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 space-y-4">
        {rows.length === 0 ? (
          <p className="text-sm text-muted">
            {mode === 'owner' ? 'No owner data available.' : 'No concentration detected.'}
          </p>
        ) : rows.map((row, i) => (
          <div key={row.label}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm font-medium text-primary truncate">{row.label}</span>
                {mode === 'owner' && i === 0 && (
                  <span className="shrink-0 rounded-full border border-danger/20 bg-danger/[0.05] px-2 py-0.5 text-[10px] font-semibold text-danger">
                    Most affected
                  </span>
                )}
              </div>
              <span className="shrink-0 text-xs tabular-nums text-muted">{row.total} {isWindowAnalysis ? 'unstable' : 'failed'}</span>
            </div>
            <ConcentrationBar
              total={row.total}
              regressed={row.regressed}
              max={max}
              totalTests={row.totalTests}
              isWindowAnalysis={isWindowAnalysis}
            />
            <p className="mt-1 text-[11px] text-muted">
              {row.failed} failed
              {isWindowAnalysis && mode === 'suite' && <> · {row.flaky} flaky</>}
              {isWindowAnalysis && (row.regressed > 0
                ? <span className="text-danger"> · +{row.regressed} regression{row.regressed !== 1 ? 's' : ''}</span>
                : (mode === 'owner' ? ' · no new regressions' : null))}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────
// Failure pattern accordion helpers
// ─────────────────────────────────────────────────────────────

function ownerInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length === 1
    ? (parts[0][0] ?? '?').toUpperCase()
    : ((parts[0][0] ?? '') + (parts[parts.length - 1][0] ?? '')).toUpperCase();
}

function patternSeverity(group: ApiFailureGroup): 'high' | 'medium' | 'low' {
  const kind = (group.error_type ?? group.category ?? '').toLowerCase();
  if (/null|pool|connection|exhausted|memory|oom/.test(kind)) return 'high';
  if (/assertion|http|status|service/.test(kind))              return 'medium';
  return 'low';
}

const SEV_STYLE = {
  high:   { accent: 'var(--color-danger)',  halo: 'rgb(var(--danger-rgb)  / 0.15)' },
  medium: { accent: 'var(--color-warning)', halo: 'rgb(var(--warning-rgb) / 0.15)' },
  low:    { accent: 'var(--color-info)',    halo: 'rgb(var(--info-rgb)    / 0.15)' },
} as const;

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const w = 72, h = 24, p = 2;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => {
    const x = p + (i * (w - 2 * p)) / (values.length - 1);
    const y = h - p - ((v / max) * (h - 2 * p));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = values[values.length - 1];
  const lx = w - p, ly = h - p - ((last / max) * (h - 2 * p));
  return (
    <svg width={w} height={h} style={{ display: 'block', flexShrink: 0 }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5"
        strokeLinejoin="round" strokeLinecap="round" opacity="0.9" />
      <circle cx={lx} cy={ly} r="2.5" fill={color} />
    </svg>
  );
}

function PatternAvatarStack({ owners }: { owners: string[] }) {
  const unique = [...new Set(owners)].slice(0, 3);
  const extra  = [...new Set(owners)].length - 3;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center' }}>
      {unique.map((name, i) => (
        <span key={name} title={name} style={{
          width: 26, height: 26, borderRadius: '50%', flexShrink: 0,
          background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
          fontSize: 11, fontWeight: 600,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          border: '1.5px solid var(--bg-surface)',
          marginLeft: i === 0 ? 0 : -8,
        }}>
          {ownerInitials(name)}
        </span>
      ))}
      {extra > 0 && (
        <span style={{
          marginLeft: -8, width: 26, height: 26, borderRadius: '50%',
          background: 'var(--bg-elevated)', color: 'var(--text-muted)',
          fontSize: 11, fontWeight: 600,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          border: '1.5px solid var(--bg-surface)',
        }}>
          +{extra}
        </span>
      )}
    </span>
  );
}

function NestedDot() {
  return <span style={{ width: 3, height: 3, borderRadius: 3, background: 'var(--text-faint)', display: 'inline-block', flexShrink: 0 }} />;
}

function NestedTestRow({
  row,
  onOpen,
  isWindowAnalysis,
}: {
  row: ApiHistoryRow;
  onOpen: () => void;
  isWindowAnalysis: boolean;
}) {
  const latest     = latestCell(row);
  const failedCell = [...row.cells].reverse().find(c => isFailure(c.state));
  const failureLabel = failedCell?.error_type
    ?? failedCell?.root_cause_category?.replace(/_/g, ' ')
    ?? null;
  const failureDetail = failedCell?.message || failedCell?.fingerprint || null;
  return (
    <div
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}
      className={[
        'cursor-pointer transition-colors duration-150 hover:bg-hover',
        !isWindowAnalysis ? 'rounded-xl border border-border-subtle px-4 py-3' : '',
      ].join(' ')}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: '1rem',
        padding: !isWindowAnalysis ? undefined : '0.85rem 1.35rem 0.95rem 2.75rem',
        borderTop: !isWindowAnalysis ? 'none' : '1px solid var(--border-subtle)',
        background: 'var(--bg-surface)',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          {statusBadge(row)}
          <span className="mono" style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            {row.display_name}()
          </span>
          {!isWindowAnalysis && isFailure(latest?.state) && failureLabel && (
            <OverflowTooltipLabel
              label={`Failing with ${failureLabel}`}
              content={
                <div className="max-w-[360px] space-y-1.5">
                  <p className="font-mono text-[11px] font-semibold text-primary">
                    {failureLabel}
                  </p>
                  {failureDetail && (
                    <p className="font-mono text-[11px] leading-5 text-muted">
                      {failureDetail}
                    </p>
                  )}
                </div>
              }
              className="min-w-0 max-w-full"
              innerClassName="qara-badge-danger inline-flex min-w-0 max-w-full cursor-default items-center overflow-hidden text-ellipsis whitespace-nowrap"
              innerStyle={{ ...SOFT_DANGER_BADGE_STYLE, padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}
              showOnOverflowOnly={false}
            />
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem', flexWrap: 'wrap' }}>
          {row.owner && <span>{row.owner}</span>}
          {row.owner && row.suite && <NestedDot />}
          {row.suite && <span>{row.suite}</span>}
          {isWindowAnalysis && (
            <>
              <NestedDot />
              <span>{transitionKey(row)}</span>
            </>
          )}
        </div>
        {isWindowAnalysis && failedCell?.message && (
          <div className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.3rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {failedCell.message}
          </div>
        )}
        {isWindowAnalysis && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
            <span className="type-nums">{failureCount(row)} failures</span>
            <NestedDot />
            <span className="type-nums">{flipCount(row)} flips</span>
            <NestedDot />
            <span className={`type-nums ${passRateToneClass(row.health.pass_rate)}`}>{Math.round(row.health.pass_rate * 100)}% pass rate</span>
          </div>
        )}
      </div>
      {isWindowAnalysis && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.3rem', flexShrink: 0 }}>
          <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>Window-end status</div>
          <div style={{
            fontSize: '0.875rem', fontWeight: 600,
            color: isFailure(latest?.state) ? 'var(--color-danger)' : isPassing(latest?.state) ? 'var(--color-success)' : 'var(--color-warning)',
          }}>
            {readableState(latest?.state)}
          </div>
        </div>
      )}
    </div>
  );
}

function TestSidePanel({
  row,
  runs,
  onClose,
}: {
  row: ApiHistoryRow | null;
  runs: ApiHistoryRun[];
  onClose: () => void;
}) {
  useEffect(() => {
    if (!row) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [row, onClose]);

  const latest     = row ? latestCell(row) : null;
  const failedCell = row ? [...row.cells].reverse().find(c => isFailure(c.state)) : null;

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(15, 23, 42, 0.32)',
          opacity: row ? 1 : 0,
          pointerEvents: row ? 'auto' : 'none',
          transition: 'opacity 220ms ease',
          zIndex: 40,
        }}
      />
      <aside style={{
        position: 'fixed', top: 0, right: 0, bottom: 0,
        width: 'min(560px, 92vw)',
        background: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border-default)',
        boxShadow: 'var(--shadow-overlay)',
        transform: row ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 260ms cubic-bezier(0.22, 1, 0.36, 1)',
        zIndex: 50,
        display: 'flex', flexDirection: 'column',
        overflowY: 'auto',
      }}>
        {row && (
          <>
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: '1rem',
              padding: '1.35rem 1.35rem 1.1rem',
              borderBottom: '1px solid var(--border-subtle)',
              position: 'sticky', top: 0, background: 'var(--bg-surface)', zIndex: 1,
            }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                  {isRegression(row) ? (
                    <span className="qara-badge-danger" style={{ padding: '0.2rem 0.55rem', fontSize: '0.65rem' }}>New regression</span>
                  ) : (
                    <span className="qara-pill" style={{ padding: '0.22rem 0.55rem', fontSize: '0.65rem' }}>
                      {isFailure(latest?.state) ? 'Failed' : readableState(latest?.state)}
                    </span>
                  )}
                  {row.suite && <span className="type-eyebrow">{row.suite}</span>}
                </div>
                <div className="mono" style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.015em', wordBreak: 'break-word' }}>
                  {row.display_name}()
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                style={{
                  width: 32, height: 32,
                  border: '1px solid var(--border-default)', borderRadius: '0.6rem',
                  background: 'var(--bg-surface)', color: 'var(--text-muted)',
                  cursor: 'pointer', flexShrink: 0,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'all 140ms ease',
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            {/* Body */}
            <div style={{ padding: '1.25rem 1.35rem 2rem', flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                {row.owner && <span style={{ fontSize: '0.875rem', color: 'var(--text-primary)', fontWeight: 500 }}>{row.owner}</span>}
                <span style={{ color: 'var(--text-faint)', fontSize: '0.55rem' }}>●</span>
                <span style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>{transitionKey(row)}</span>
              </div>

              {/* Stat tiles */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.6rem', marginTop: '1rem' }}>
                {([
                  { label: 'Failures',  value: failureCount(row), color: 'var(--color-danger)'  },
                  { label: 'Flips',     value: flipCount(row),    color: 'var(--color-warning)' },
                  { label: 'Pass rate', value: `${Math.round(row.health.pass_rate * 100)}%`, color: 'var(--text-primary)' },
                ] as const).map(({ label, value, color }) => (
                  <div key={label} style={{ border: '1px solid var(--border-subtle)', borderRadius: '0.85rem', padding: '0.7rem 0.85rem', background: 'var(--bg-subtle)' }}>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginBottom: '0.25rem', letterSpacing: '0.04em' }}>{label}</div>
                    <div className="type-nums" style={{ fontSize: '1.25rem', fontWeight: 600, color, letterSpacing: '-0.02em' }}>{value}</div>
                  </div>
                ))}
              </div>

              {/* Error */}
              {failedCell?.message && (
                <div style={{ marginTop: '1.5rem' }}>
                  <p className="type-eyebrow" style={{ marginBottom: '0.45rem' }}>Error</p>
                  <div className="mono" style={{
                    fontSize: '0.8125rem', color: 'var(--color-danger)',
                    background: 'rgb(var(--danger-rgb) / 0.06)',
                    border: '1px solid rgb(var(--danger-rgb) / 0.2)',
                    borderRadius: '0.7rem', padding: '0.7rem 0.85rem',
                    lineHeight: 1.5, wordBreak: 'break-word',
                  }}>
                    {failedCell.message}
                  </div>
                </div>
              )}

              {/* Run timeline */}
              {runs.length > 0 && (
                <div style={{ marginTop: '1.25rem' }}>
                  <p className="type-eyebrow" style={{ marginBottom: '0.6rem' }}>
                    Results in selected window
                  </p>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                    <RunWindowStrip cells={row.cells} size="md" />
                    {runs.length > 0 && (
                      <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        #{runs[0]?.run_sequence} → #{runs[runs.length - 1]?.run_sequence}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </aside>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────

export function FailureFlakinessView({
  incidents,
  onOpenIncidents,
  runsWindow,
  runIds,
  viewMode,
}: {
  incidents: ApiIncident[];
  onOpenIncidents: (incidentId?: string) => void;
  runsWindow: number;
  runIds: string[];
  viewMode: 'single' | 'window';
}) {
  const { currentProject } = useProject();
  const [history, setHistory]                   = useState<ApiHistoryResult | null>(null);
  const [groups, setGroups]                     = useState<ApiFailureGroup[]>([]);
  const [loading, setLoading]                   = useState(true);
  const [error, setError]                       = useState<string | null>(null);
  const [statusFilter, setStatusFilter]           = useState<StatusFilter>('all');
  const [transitionFilter, setTransitionFilter]   = useState<string | null>(null);
  const [fingerprintFilter, setFingerprintFilter] = useState<string | null>(null);
  const [openPatternId, setOpenPatternId]         = useState<string | null>(null);
  const [activeTest, setActiveTest]               = useState<ApiHistoryRow | null>(null);
  const [regressionsExpanded, setRegressionsExpanded] = useState(false);
  const [patternsExpanded, setPatternsExpanded]       = useState(false);
  const closeTest = useCallback(() => setActiveTest(null), []);
  const isWindowAnalysis = viewMode === 'window' && runsWindow > 1;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const groupParams = new URLSearchParams({ limit: '12' });
    if (currentProject) groupParams.set('project', currentProject);
    if (runIds.length > 0) groupParams.set('run_ids', runIds.join(','));

    const historyRequest = runIds.length > 0
      ? fetch('/api/compare/custom', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ run_ids: runIds, filters: {} }),
        })
      : fetch(`/api/compare/history?${new URLSearchParams({ limit: String(runsWindow), ...(currentProject ? { project: currentProject } : {}) })}`);

    Promise.all([
      historyRequest.then(r => r.ok ? r.json() as Promise<ApiHistoryResult> : Promise.reject(`API ${r.status}`)),
      fetch(`/api/failure-groups?${groupParams}`).then(r => r.ok ? r.json() as Promise<ApiFailureGroup[]> : Promise.reject(`API ${r.status}`)),
    ])
      .then(([historyData, groupData]) => {
        if (cancelled) return;
        setHistory(historyData);
        setGroups(groupData);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [currentProject, runsWindow, runIds]);

  useEffect(() => {
    setStatusFilter('all');
    setTransitionFilter(null);
    setFingerprintFilter(null);
    setRegressionsExpanded(false);
    setPatternsExpanded(false);
  }, [viewMode, runsWindow, runIds]);

  const rows      = history?.rows ?? [];
  const latestRun = history?.runs[history.runs.length - 1] ?? null;
  const firstRun  = history?.runs[0] ?? null;

  const counts = useMemo(() => {
    const failed    = rows.filter(r => isFailure(latestCell(r)?.state)).length;
    const flaky     = rows.filter(isFlaky).length;
    const regressed = rows.filter(isRegression).length;
    const recovered = rows.filter(isRecovered).length;
    const stable    = rows.filter(isStable).length;
    return { all: rows.length, failed, flaky, regressed, recovered, stable };
  }, [rows]);

  const unstableRows = useMemo(
    () => rows.filter(r => isFailure(latestCell(r)?.state) || isFlaky(r) || isRegression(r)),
    [rows],
  );

  const transitions = useMemo(() => {
    const map = new Map<string, { label: string; count: number; tone: 'danger' | 'warning' | 'success' }>();
    for (const row of rows) {
      const key  = transitionKey(row);
      if (key.includes('Absent')) continue;
      const tone = isRegression(row) ? 'danger' : isRecovered(row) ? 'success' : 'warning';
      const cur  = map.get(key) ?? { label: key, count: 0, tone };
      cur.count++;
      cur.tone = cur.tone === 'danger' || tone === 'danger' ? 'danger' : cur.tone === 'success' ? 'success' : tone;
      map.set(key, cur);
    }
    return [...map.values()]
      .filter(t => t.count > 0)
      .sort((a, b) => {
        const rank = (t: string) =>
          t === 'Passed → Failed' ? 0 : t === 'Failed → Passed' ? 1 : t.includes('Failed') ? 2 : 3;
        return rank(a.label) - rank(b.label) || b.count - a.count;
      })
      .slice(0, 8);
  }, [rows]);

  const primaryTransitions   = transitions.filter(t => TRANSITION_META[t.label]?.primary);
  const secondaryTransitions = transitions.filter(t => !TRANSITION_META[t.label]?.primary);

  const ownerConcentration = useMemo(() => groupConcentration(rows, 'owner'), [rows]);
  const suiteConcentration = useMemo(() => groupConcentration(rows, 'suite'), [rows]);

const focusedRows = useMemo(() => {
    // When a transitionFilter is active, search all rows — some transitions
    // (e.g. Failed → Passed / Recovered) include tests that are currently
    // passing and are therefore absent from unstableRows.
    const baseRows = transitionFilter ? rows : unstableRows;
    return baseRows
      .filter(row => {
        if (statusFilter !== 'all') {
          if (statusFilter === 'failed'    && !isFailure(latestCell(row)?.state)) return false;
          if (statusFilter === 'flaky'     && !isFlaky(row))                      return false;
          if (statusFilter === 'regressed' && !isRegression(row))                 return false;
          if (statusFilter === 'recovered' && !isRecovered(row))                  return false;
          if (statusFilter === 'stable'    && !isStable(row))                     return false;
        }
        if (transitionFilter  && transitionKey(row) !== transitionFilter)                    return false;
        if (fingerprintFilter && !row.cells.some(c => c.fingerprint === fingerprintFilter)) return false;
        return true;
      })
      .sort((a, b) => {
        const score = (row: ApiHistoryRow) =>
          (isRegression(row) ? 100 : 0)
          + (isFailure(latestCell(row)?.state) ? 50 : 0)
          + failureCount(row) * 4
          + flipCount(row) * 2;
        return score(b) - score(a);
      })
      .slice(0, 12);
  }, [rows, unstableRows, statusFilter, transitionFilter, fingerprintFilter]);

  const activeContext = transitionFilter
    ? `Transition: ${transitionFilter}`
    : fingerprintFilter
      ? 'Filtered by failure pattern'
      : FILTER_LABELS[statusFilter];

  if (loading) {
    return (
      <div className="space-y-3 animate-pulse">
        {[1, 2, 3, 4].map(i => <div key={i} className="h-16 rounded-2xl bg-surface-subtle" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="qara-error-banner">
        <span>Failed to load failure intelligence: {error}</span>
      </div>
    );
  }

  if (!history || rows.length === 0) {
    return (
      <div className="qara-empty-state">
        <div className="qara-empty-icon">✓</div>
        <p className="type-empty-title">No status history found</p>
        <p className="type-empty-subtitle">Ingest more runs to analyze failures and flakiness.</p>
      </div>
    );
  }

  const topSuites    = suiteConcentration.slice(0, 2).map(s => s.label).join(' and ');
  const topOwners    = ownerConcentration.slice(0, 2).map(o => o.label.split(' ')[0]).join(' and ');
  const contextNote = isWindowAnalysis && firstRun && latestRun
    ? `Analyzing Runs #${firstRun.run_sequence}–#${latestRun.run_sequence}`
    : latestRun
      ? `Single-run · Run #${latestRun.run_sequence}`
      : 'Single-run debugging';

  const filterMatchCount = transitionFilter
    ? rows.filter(r => transitionKey(r) === transitionFilter).length
    : statusFilter === 'failed'
      ? counts.failed
    : statusFilter === 'stable'
      ? counts.stable
    : statusFilter === 'flaky'
      ? counts.flaky
      : 0;

  const filterLabel = transitionFilter
    ? transitionFilter === 'Failed → Passed' ? 'recovered tests'
    : (TRANSITION_META[transitionFilter]?.label ?? transitionFilter).toLowerCase()
    : statusFilter === 'failed'
      ? 'failed tests'
    : statusFilter === 'stable'
      ? 'currently passing tests'
    : 'flaky tests';

  return (
    <>
    <div className="space-y-5">

      {/* Context toolbar */}
      <div className="flex items-center justify-between">
        <div>
          <p className="type-eyebrow">Status investigation</p>
          <p className="mt-1 text-lg font-semibold text-primary tracking-tight">
            {isWindowAnalysis && firstRun && latestRun
              ? `${fmtTs(firstRun.started_at)} → ${fmtTs(latestRun.started_at)}`
              : latestRun
                ? `Run #${latestRun.run_sequence}${latestRun.started_at ? ` · ${fmtTs(latestRun.started_at)}` : ''}`
                : `Last ${runsWindow} runs`}
          </p>
        </div>
        <span className="qara-inline-note">{contextNote}</span>
      </div>

      {/* ① Headline — collapsed: one bold line + one rich subtext line that absorbs
            the prior priority strip's concentration + ownership context. */}
      <section className="qara-card-elevated overflow-hidden">
        <div className="px-6 py-5">
          <p className="type-eyebrow">Headline</p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-primary">
            {topSuites
              ? `${topSuites} flows are driving instability`
              : isWindowAnalysis ? 'Status history is stable in this window' : 'This run is stable'}
          </h2>
          <p className="mt-2 text-sm text-muted">
            {isWindowAnalysis ? (
              counts.regressed > 0 ? (
                <>
                  <span className="font-semibold text-danger">
                    {counts.regressed} new regression{counts.regressed !== 1 ? 's' : ''}
                  </span>
                  {topSuites && <> concentrated in <span className="text-secondary">{topSuites}</span></>}
                  {topOwners && <> · <span className="text-secondary">{topOwners}</span> most affected</>}
                  <> · {counts.failed} failing in the latest run ({counts.failed - counts.regressed} existing failure{counts.failed - counts.regressed !== 1 ? 's' : ''} + {counts.regressed} new regression{counts.regressed !== 1 ? 's' : ''})</>
                </>
              ) : (
                <>
                  {counts.failed} failing in latest run · {counts.flaky === 0 ? 'no flakiness detected' : `${counts.flaky} flaky`}
                </>
              )
            ) : (
              <>{counts.failed} failed test{counts.failed !== 1 ? 's' : ''} in this run</>
            )}
          </p>
        </div>
      </section>

      {/* Active filter chip — single, global indicator visible whenever a filter is in effect.
            Lets users see the current filter and clear it from one place at the top of the view. */}
      {(statusFilter !== 'all' || transitionFilter || fingerprintFilter) && (() => {
        const filterLabelText = transitionFilter
          ? (TRANSITION_META[transitionFilter]?.label ?? transitionFilter)
          : fingerprintFilter
            ? 'Failure pattern'
            : (FILTER_LABELS[statusFilter] ?? statusFilter);
        const clearAll = () => { setStatusFilter('all'); setTransitionFilter(null); setFingerprintFilter(null); };
        return (
          <div className="flex items-center gap-2 -mt-1" role="status" aria-live="polite">
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted shrink-0">
              Filtering by
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-info/30 bg-info/[0.06] py-0.5 pl-2.5 pr-1 text-xs font-medium text-info">
              <span className="h-1.5 w-1.5 rounded-full bg-info" aria-hidden="true" />
              <span>{filterLabelText}</span>
              <button
                type="button"
                onClick={clearAll}
                aria-label={`Clear filter: ${filterLabelText}`}
                className="ml-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-info hover:bg-info/15 transition-colors"
              >
                <svg viewBox="0 0 12 12" fill="none" className="h-2.5 w-2.5" aria-hidden="true">
                  <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </span>
            <button
              type="button"
              onClick={clearAll}
              className="text-xs text-muted hover:text-primary transition-colors underline-offset-2 hover:underline"
            >
              Clear
            </button>
          </div>
        );
      })()}

      {/* ③ Stat cards (single run) OR Transitions (window) */}
      {!isWindowAnalysis && (
        <div className="grid grid-cols-1 gap-3">
          {(['failed'] as StatusFilter[]).map(key => {
            const active = statusFilter === key && !transitionFilter && !fingerprintFilter;
            const showLink = active && filterMatchCount > 0;
            return (
              <button
                key={key}
                onClick={() => { setStatusFilter(key); setTransitionFilter(null); setFingerprintFilter(null); }}
                className={[
                  'qara-stat-card min-h-0 text-left transition-all duration-150 hover:-translate-y-0.5',
                  active ? 'ring-2 ring-info/20' : '',
                ].join(' ')}
              >
                <span className="type-metric-label">{FILTER_LABELS[key]}</span>
                <span className={`type-metric-value-md ${STATUS_CARD_STYLE[key].split(' ').slice(-1)[0]}`}>{counts[key]}</span>
                {showLink && (
                  <p className="mt-2 text-[11px] text-info">
                    ↳{' '}
                    <span
                      role="link"
                      tabIndex={0}
                      className="underline underline-offset-2 hover:text-info/80 transition-colors cursor-pointer"
                      onClick={e => { e.stopPropagation(); document.getElementById('unstable-tests')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}
                      onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.click(); }}
                    >
                      Showing {filterMatchCount} {filterLabel} below
                    </span>
                  </p>
                )}
              </button>
            );
          })}
        </div>
      )}

      {isWindowAnalysis && (
        <section className="qara-card p-5">
          <div className="flex items-start justify-between gap-3">
            <SectionTitle
              title="What changed"
              subtitle="Regressions and recoveries are actionable. Other counts provide context."
            />
            {(statusFilter !== 'all' || transitionFilter || fingerprintFilter) && (
              <button
                className="qara-chip type-chip"
                onClick={() => { setStatusFilter('all'); setTransitionFilter(null); setFingerprintFilter(null); }}
              >
                Clear filters
              </button>
            )}
          </div>

          {/* Actionable tier */}
          {primaryTransitions.length > 0 && (
            <>
              <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">Actionable</p>
              <div className="mt-2 grid grid-cols-2 gap-3">
                {primaryTransitions.map(t => {
                  const meta      = TRANSITION_META[t.label];
                  const isDanger  = meta.tone === 'danger';
                  const isSuccess = meta.tone === 'success';
                  const active    = transitionFilter === t.label;
                  const showLink  = active && filterMatchCount > 0;
                  return (
                    <button
                      key={t.label}
                      onClick={() => { setTransitionFilter(t.label); setStatusFilter('all'); setFingerprintFilter(null); }}
                      className={[
                        'rounded-2xl border px-4 py-4 text-left transition-all duration-150 hover:-translate-y-0.5',
                        isDanger  ? 'border-danger/30 bg-danger/[0.04]'   : 'border-success/30 bg-success/[0.04]',
                        active    ? 'ring-2 ring-inset ring-info/20'       : '',
                      ].join(' ')}
                    >
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">{meta.sublabel}</p>
                      <p className="mt-0.5 text-sm font-semibold text-primary">{meta.label}</p>
                      <p className={`mt-2 text-2xl font-bold tabular-nums ${isDanger ? 'text-danger' : isSuccess ? 'text-success' : 'text-warning'}`}>
                        {t.count}
                      </p>
                      {showLink && (
                        <p className="mt-2 text-[11px] text-info">
                          ↳{' '}
                          <span
                            role="link"
                            tabIndex={0}
                            className="underline underline-offset-2 hover:text-info/80 transition-colors cursor-pointer"
                            onClick={e => {
                              e.stopPropagation();
                              if (t.label === 'Passed → Failed') {
                                setRegressionsExpanded(prev => !prev);
                                if (!regressionsExpanded) {
                                  setTimeout(() => {
                                    document.getElementById('inline-regressions')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                  }, 50);
                                }
                              } else {
                                document.getElementById('unstable-tests')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                              }
                            }}
                            onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.click(); }}
                          >
                            {t.label === 'Passed → Failed'
                              ? (regressionsExpanded
                                  ? `Hide ${filterMatchCount} regression${filterMatchCount !== 1 ? 's' : ''}`
                                  : `View ${filterMatchCount} regression${filterMatchCount !== 1 ? 's' : ''} below`)
                              : `Showing ${filterMatchCount} ${filterLabel} below`}
                          </span>
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* Context tier */}
          <p className={`text-[10px] font-semibold uppercase tracking-[0.16em] text-muted ${primaryTransitions.length > 0 ? 'mt-4' : 'mt-4'}`}>Context</p>
          <div className="mt-2 grid grid-cols-3 gap-2">
            {secondaryTransitions.map(t => {
              const meta     = TRANSITION_META[t.label];
              const active   = transitionFilter === t.label;
              const showLink = active && filterMatchCount > 0;
              return (
                <button
                  key={t.label}
                  onClick={() => { setTransitionFilter(t.label); setStatusFilter('all'); setFingerprintFilter(null); }}
                  className={[
                    'rounded-xl border px-3 py-2.5 text-left transition-all duration-150 hover:bg-hover',
                    active ? 'border-info/30 bg-info/[0.04]' : 'border-border-subtle bg-surface',
                  ].join(' ')}
                >
                  <p className="text-[11px] text-muted">{meta?.label ?? t.label}</p>
                  <p className="mt-0.5 text-base font-semibold tabular-nums text-secondary">{t.count}</p>
                  {showLink && (
                    <p className="mt-1.5 text-[11px] text-info">
                      ↳{' '}
                      <span
                        role="link"
                        tabIndex={0}
                        className="underline underline-offset-2 hover:text-info/80 transition-colors cursor-pointer"
                        onClick={e => { e.stopPropagation(); document.getElementById('unstable-tests')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}
                        onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.click(); }}
                      >
                        Showing {filterMatchCount} {filterLabel} below
                      </span>
                    </p>
                  )}
                </button>
              );
            })}
            <button
              onClick={() => { setStatusFilter('flaky'); setTransitionFilter(null); setFingerprintFilter(null); }}
              className={[
                'rounded-xl border px-3 py-2.5 text-left transition-all duration-150 hover:bg-hover',
                statusFilter === 'flaky' && !transitionFilter ? 'border-info/30 bg-info/[0.04]' : 'border-border-subtle bg-surface',
              ].join(' ')}
            >
              <p className="text-[11px] text-muted">Flaky</p>
              <p className="mt-0.5 text-base font-semibold tabular-nums text-secondary">{counts.flaky}</p>
              {statusFilter === 'flaky' && !transitionFilter && filterMatchCount > 0 && (
                <p className="mt-1.5 text-[11px] text-info">
                  ↳{' '}
                  <span
                    role="link"
                    tabIndex={0}
                    className="underline underline-offset-2 hover:text-info/80 transition-colors cursor-pointer"
                    onClick={e => { e.stopPropagation(); document.getElementById('unstable-tests')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}
                    onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.click(); }}
                  >
                    Showing {filterMatchCount} {filterLabel} below
                  </span>
                </p>
              )}
            </button>
          </div>

          {/* Context hint */}
          <p className="mt-3 text-[11px] text-muted">
            Existing failures represent prior failure debt — not new issues in this window.
          </p>
        </section>
      )}

      {/* ③½ Inline regressions detail — expanded from "Passed → Failed" card */}
      {isWindowAnalysis && regressionsExpanded && (
        <section
          id="inline-regressions"
          className="qara-card overflow-hidden"
          aria-label="New regressions detail"
        >
          <header className="flex items-center justify-between gap-3 border-b border-border-subtle bg-surface-subtle px-5 py-3">
            <div>
              <p className="type-eyebrow">Drill-down</p>
              <p className="text-sm font-semibold text-primary">
                New regressions in this window
              </p>
            </div>
            <button
              type="button"
              className="qara-chip type-chip"
              onClick={() => setRegressionsExpanded(false)}
              aria-label="Collapse regressions detail"
            >
              Hide ▲
            </button>
          </header>
          <div className="p-5">
            <RegressionsView runIds={runIds} runsWindow={runsWindow} />
          </div>
        </section>
      )}

      {/* ④ Concentration — merged Owner + Suite panel with internal toggle */}
      <ConcentrationPanel ownerRows={ownerConcentration} suiteRows={suiteConcentration} isWindowAnalysis={isWindowAnalysis} />

      {/* ⑤ Failure patterns — lazy: collapsed by default. Toolbar always visible
            with a self-contained summary (count + top pattern); the heavy accordion
            only mounts when the user clicks "View patterns". */}
      <div className="qara-card" style={{ overflow: 'hidden' }}>
        {/* Toolbar — always visible, summarises everything important */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
          padding: '1.1rem 1.35rem 1rem',
          borderBottom: patternsExpanded ? '1px solid var(--border-subtle)' : 'none',
          background: 'var(--bg-surface)',
          gap: '1rem', flexWrap: 'wrap',
        }}>
          <div style={{ minWidth: 0, flex: '1 1 auto' }}>
            <p className="type-eyebrow" style={{ marginBottom: '0.35rem' }}>
              {isWindowAnalysis
                ? (groups.length > 0 && groups[0].scope === 'window' ? 'Failure patterns in this window' : 'Failure patterns')
                : 'Failure patterns in this run'}
            </p>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              {groups.length === 0 ? (
                'No recurring failure patterns detected.'
              ) : (
                <>
                  <span className="type-nums" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{groups.length}</span>
                  {' '}recurring pattern{groups.length !== 1 ? 's' : ''}
                  {isWindowAnalysis && groups[0].scope === 'window' && firstRun && latestRun && (
                    <>
                      {' '}across{' '}
                      <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                        Runs #{firstRun.run_sequence}–#{latestRun.run_sequence}
                      </span>
                    </>
                  )}
                  {!isWindowAnalysis && latestRun && (
                    <>
                      {' '}in{' '}
                      <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                        Run #{latestRun.run_sequence}
                      </span>
                    </>
                  )}
                  <span style={{ color: 'var(--text-faint)' }}>  ·  </span>
                  Top:{' '}
                  <span className="mono" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {groups[0].error_type || groups[0].category || 'Unknown error'}
                  </span>
                  {' '}
                  <span style={{ color: 'var(--text-muted)' }}>
                    ({groups[0].affected_tests} test{groups[0].affected_tests !== 1 ? 's' : ''})
                  </span>
                </>
              )}
            </p>
          </div>
          {groups.length > 0 && (
            <button
              className="qara-chip"
              onClick={() => setPatternsExpanded(prev => !prev)}
              aria-expanded={patternsExpanded}
              aria-controls="failure-patterns-accordion"
              style={{ flexShrink: 0 }}
            >
              {patternsExpanded ? 'Hide patterns ▲' : 'View patterns →'}
            </button>
          )}
        </div>

        {/* Pattern accordion rows — only mounted when expanded */}
        {patternsExpanded && groups.length > 0 && (
        <div id="failure-patterns-accordion">
        {groups.slice(0, 6).map((group, gi) => {
          const sev          = patternSeverity(group);
          const sevStyle     = SEV_STYLE[sev];
          const open         = openPatternId === group.fingerprint;
          const patternTests = rows.filter(r => group.affected_canonical_names.includes(r.canonical_name));
          const owners       = patternTests.map(r => r.owner).filter(Boolean) as string[];
          const trend        = (history?.runs ?? []).map((_, i) =>
            patternTests.filter(r => isFailure(r.cells[i]?.state)).length
          );
          const isScoped = group.scope === 'window';
          const winSize  = group.window_size;

          return (
            <div key={group.fingerprint} style={{ borderTop: gi === 0 ? '1px solid var(--border-subtle)' : '1px solid var(--border-subtle)' }}>
              {/* Pattern header row */}
              <button
                onClick={() => setOpenPatternId(prev => prev === group.fingerprint ? null : group.fingerprint)}
                aria-expanded={open}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: '0.85rem',
                  padding: '1rem 1.35rem 1rem 0.95rem',
                  background: 'var(--bg-surface)',
                  border: 'none', borderLeft: `3px solid ${open ? sevStyle.accent : 'transparent'}`,
                  cursor: 'pointer', textAlign: 'left', font: 'inherit', color: 'inherit',
                  transition: 'background 160ms ease, border-left-color 160ms ease',
                }}
              >
                {/* Chevron */}
                <span style={{ display: 'inline-flex', transition: 'transform 180ms ease', color: 'var(--text-muted)', flexShrink: 0, transform: open ? 'rotate(90deg)' : 'none' }}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </span>

                {/* Severity dot */}
                <span style={{ width: 8, height: 8, borderRadius: 999, background: sevStyle.accent, flexShrink: 0, boxShadow: `0 0 0 3px ${sevStyle.halo}` }} />

                {/* Main content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <span className="mono" style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
                      {group.error_type || group.category || 'Unknown error'}
                    </span>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: sevStyle.accent }}>
                      {sev}
                    </span>
                  </div>
                  <div className="mono" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.2rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {group.message || group.fingerprint}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                    {owners.length > 0 && <PatternAvatarStack owners={owners} />}
                    {owners.length > 0 && <NestedDot />}
                    {isWindowAnalysis && isScoped && winSize ? (
                      <span>Seen in <strong className="type-nums" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{group.affected_runs}/{winSize}</strong> runs</span>
                    ) : isWindowAnalysis ? (
                      <span>Seen in <strong className="type-nums" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{group.affected_runs}</strong> runs</span>
                    ) : (
                      <span><strong className="type-nums" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{group.occurrence_count}</strong> failures in this run</span>
                    )}
                    {isWindowAnalysis && (
                      <>
                        <NestedDot />
                        <span className="type-nums"><strong style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{group.occurrence_count}</strong> occurrences</span>
                      </>
                    )}
                    {isWindowAnalysis && group.first_seen_seq && (
                      <><NestedDot /><span>First seen Run #{group.first_seen_seq}</span></>
                    )}
                  </div>
                </div>

                {/* Sparkline */}
                {isWindowAnalysis && trend.some(v => v > 0) && (
                  <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.3rem' }}>
                    <Sparkline values={trend} color={sevStyle.accent} />
                    {firstRun && latestRun && (
                      <div style={{ fontSize: '0.625rem', color: 'var(--text-faint)', letterSpacing: '0.04em' }}>
                        #{firstRun.run_sequence} → #{latestRun.run_sequence}
                      </div>
                    )}
                  </div>
                )}

                {/* Test count */}
                <div style={{ flexShrink: 0, textAlign: 'right', minWidth: 52 }}>
                  <div className="type-nums" style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.03em', lineHeight: 1 }}>
                    {group.affected_tests}
                  </div>
                  <div className="type-eyebrow" style={{ marginTop: '0.2rem', color: 'var(--text-faint)' }}>tests</div>
                </div>
              </button>

              {/* Expanded: nested test rows */}
              {open && (
                <div className="qara-fade-up" style={{ position: 'relative', background: 'var(--bg-surface)', borderTop: '1px dashed var(--border-default)' }}>
                  {/* Left accent rail */}
                  {isWindowAnalysis && (
                    <div style={{
                      position: 'absolute', top: 0, bottom: 0, left: '1.35rem', width: 2,
                      background: `linear-gradient(to bottom, ${sevStyle.accent}, ${sevStyle.accent}00)`,
                      opacity: 0.35,
                    }} />
                  )}

                  {/* Sub-header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: isWindowAnalysis ? '0.85rem 1.35rem 0.7rem 2.75rem' : '0.85rem 1.35rem 0.7rem', gap: '1rem', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <span className="type-eyebrow">{isWindowAnalysis ? 'Tests matching this pattern' : 'Failed tests with this pattern'}</span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        <span className="type-nums" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{patternTests.length}</span>
                      </span>
                    </div>
                  </div>

                  {patternTests.length === 0 ? (
                    <p style={{ padding: isWindowAnalysis ? '1rem 2.75rem' : '1rem 1.35rem', fontSize: '0.875rem', color: 'var(--text-muted)' }}>No matching test history found.</p>
                  ) : isWindowAnalysis ? patternTests.map(row => (
                    <NestedTestRow key={row.canonical_name} row={row} onOpen={() => setActiveTest(row)} isWindowAnalysis={isWindowAnalysis} />
                  )) : (
                    <div className="grid gap-3 px-5 pb-5 md:grid-cols-2">
                      {patternTests.map(row => (
                        <NestedTestRow key={row.canonical_name} row={row} onOpen={() => setActiveTest(row)} isWindowAnalysis={isWindowAnalysis} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        </div>
        )}
      </div>

      {/* ⑦ Active failures and flaky tests — only shown when a filter is active.
            Note: when transitionFilter === 'Passed → Failed', the inline RegressionsView
            (section ③½) covers this case, so we suppress ⑦ to avoid a duplicate list. */}
      {(statusFilter !== 'all' || (transitionFilter && transitionFilter !== 'Passed → Failed') || fingerprintFilter) && <section className="qara-card p-5">
        {(() => {
          const sectionTitle = transitionFilter
            ? (TRANSITION_META[transitionFilter]?.label ?? transitionFilter)
            : fingerprintFilter
              ? 'Tests matching failure pattern'
              : FILTER_LABELS[statusFilter] ?? 'Active failures and flaky tests';
          const isRecoveredSection = transitionFilter === 'Failed → Passed' || statusFilter === 'recovered';
          const sectionSubtitle = isRecoveredSection
            ? `${focusedRows.length} recovered in this window · ${activeContext}`
            : `${focusedRows.length} shown · ${activeContext}`;
          return (
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionTitle
                title={sectionTitle}
                subtitle={sectionSubtitle}
              />
              {!isRecoveredSection && (
                <button className="qara-chip type-chip" onClick={() => onOpenIncidents()}>
                  Inspect incident clusters
                </button>
              )}
            </div>
          );
        })()}

        <div
          id="unstable-tests"
          className={[
            'mt-4',
            (() => {
              const isRecoveredSection = transitionFilter === 'Failed → Passed' || statusFilter === 'recovered';
              const isExistingFailuresSection = transitionFilter === 'Failed → Failed';
              const isSingleRunFailedSection = !isWindowAnalysis && statusFilter === 'failed' && !transitionFilter;
              return (isRecoveredSection || isExistingFailuresSection || isSingleRunFailedSection)
                ? 'grid grid-cols-1 gap-3 xl:grid-cols-2'
                : 'divide-y divide-border-subtle';
            })(),
          ].join(' ')}
        >
          {focusedRows.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted">No tests match the selected investigation filter.</div>
          ) : focusedRows.map(row => {
            const latest   = latestCell(row);
            const incident = relatedIncident(row, incidents);
            const failedCell  = [...row.cells].reverse().find(c => isFailure(c.state));
            const fingerprint = failedCell?.fingerprint;
            const isPassingNow = isPassing(latest?.state);
            const recoveryLabel = failedCell?.error_type
              ?? failedCell?.root_cause_category?.replace(/_/g, ' ')
              ?? null;
            const recoveredDetail = failedCell?.message || fingerprint || null;
            const isRecoveredSection = transitionFilter === 'Failed → Passed' || statusFilter === 'recovered';
            const isExistingFailuresSection = transitionFilter === 'Failed → Failed';
            const isSingleRunFailedSection = !isWindowAnalysis && statusFilter === 'failed' && !transitionFilter;
            const useCompactCard = (isRecoveredSection || isExistingFailuresSection || isSingleRunFailedSection) && (isPassingNow || isFailure(latest?.state));
            return (
              <div
                key={row.canonical_name}
                className={[
                  'transition-colors duration-150',
                  useCompactCard
                    ? 'rounded-xl border border-border-subtle px-4 py-3 hover:bg-hover'
                    : `${isPassingNow ? 'py-2.5' : 'py-3.5'} hover:bg-hover`,
                ].join(' ')}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      {statusBadge(row)}
                      <OverflowTooltipLabel
                        label={row.display_name}
                        content={<p className="max-w-[360px] font-mono text-[11px] text-primary">{row.display_name}</p>}
                        className="min-w-0 max-w-full"
                        innerClassName="block min-w-0 max-w-full truncate font-mono text-sm font-medium text-primary"
                      />
                      {isPassingNow && recoveryLabel && (
                        <OverflowTooltipLabel
                          label={`Recovered earlier from ${recoveryLabel}`}
                          content={
                            <div className="max-w-[360px] space-y-1.5">
                              <p className="font-mono text-[11px] font-semibold text-primary">
                                {recoveryLabel}
                              </p>
                              {recoveredDetail && (
                                <p className="font-mono text-[11px] leading-5 text-muted">
                                  {recoveredDetail}
                                </p>
                              )}
                            </div>
                          }
                          className="min-w-0 max-w-full"
                          innerClassName="qara-badge-info inline-flex min-w-0 max-w-full cursor-default items-center overflow-hidden text-ellipsis whitespace-nowrap"
                          innerStyle={{ padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}
                          showOnOverflowOnly={false}
                        />
                      )}
                      {!isPassingNow && isExistingFailuresSection && recoveryLabel && (
                        <OverflowTooltipLabel
                          label={`Still failing with ${recoveryLabel}`}
                          content={
                            <div className="max-w-[360px] space-y-1.5">
                              <p className="font-mono text-[11px] font-semibold text-primary">
                                {recoveryLabel}
                              </p>
                              {recoveredDetail && (
                                <p className="font-mono text-[11px] leading-5 text-muted">
                                  {recoveredDetail}
                                </p>
                              )}
                            </div>
                          }
                          className="min-w-0 max-w-full"
                          innerClassName="qara-badge-danger inline-flex min-w-0 max-w-full cursor-default items-center overflow-hidden text-ellipsis whitespace-nowrap"
                          innerStyle={{ ...SOFT_DANGER_BADGE_STYLE, padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}
                          showOnOverflowOnly={false}
                        />
                      )}
                      {!isPassingNow && isExistingFailuresSection && !recoveryLabel && (
                        <span className="qara-badge-danger" style={{ ...SOFT_DANGER_BADGE_STYLE, padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}>
                          Persisting in recent runs
                        </span>
                      )}
                      {!isPassingNow && isSingleRunFailedSection && recoveryLabel && (
                        <OverflowTooltipLabel
                          label={`Failing with ${recoveryLabel}`}
                          content={
                            <div className="max-w-[360px] space-y-1.5">
                              <p className="font-mono text-[11px] font-semibold text-primary">
                                {recoveryLabel}
                              </p>
                              {recoveredDetail && (
                                <p className="font-mono text-[11px] leading-5 text-muted">
                                  {recoveredDetail}
                                </p>
                              )}
                            </div>
                          }
                          className="min-w-0 max-w-full"
                          innerClassName="qara-badge-danger inline-flex min-w-0 max-w-full cursor-default items-center overflow-hidden text-ellipsis whitespace-nowrap"
                          innerStyle={{ ...SOFT_DANGER_BADGE_STYLE, padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}
                          showOnOverflowOnly={false}
                        />
                      )}
                      {!isPassingNow && isSingleRunFailedSection && !recoveryLabel && (
                        <span className="qara-badge-danger" style={{ ...SOFT_DANGER_BADGE_STYLE, padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}>
                          Current failure
                        </span>
                      )}
                      {isPassingNow && !recoveryLabel && (
                        <span className="qara-badge-success" style={{ padding: '0.22rem 0.5rem', fontSize: '0.625rem' }}>
                          No flips in recent runs
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                      <span>{row.owner || 'Unassigned'}</span>
                      <span>·</span>
                      <span>{row.suite || 'No suite'}</span>
                      {isWindowAnalysis && (
                        <>
                          <span>·</span>
                          <span>{transitionKey(row)}</span>
                        </>
                      )}
                    </div>
                    {/* Error message — only for currently failing tests */}
                    {isFailure(latest?.state) && (failedCell?.message || fingerprint) && (
                      (isExistingFailuresSection || isSingleRunFailedSection) ? null : (
                        <p className="mt-2 line-clamp-2 text-xs text-secondary">
                          {failedCell?.message || fingerprint}
                        </p>
                      )
                    )}

                    {(isWindowAnalysis || (incident && isFailure(latest?.state))) && (
                      <div className={`${isPassingNow ? 'mt-1.5' : 'mt-2'} flex flex-wrap items-center gap-2 text-[11px] text-muted`}>
                        {isWindowAnalysis && (
                          <>
                            <span className="text-danger">
                              <span className="font-semibold tabular-nums">{failureCount(row)}</span> failures
                            </span>
                            <span>·</span>
                            <span className="text-warning">
                              <span className="font-semibold tabular-nums">{flipCount(row)}</span> flips
                            </span>
                            <span>·</span>
                            <span className={passRateToneClass(row.health.pass_rate)}>
                              <span className="font-semibold tabular-nums">{pct(row.health.pass_rate)}</span> pass rate
                            </span>
                          </>
                        )}
                        {(isPassingNow || isExistingFailuresSection) && isWindowAnalysis && row.cells.length > 0 && (
                          <>
                            <span>·</span>
                            <RunWindowStrip cells={row.cells} />
                          </>
                        )}
                        {incident && isFailure(latest?.state) && (
                          <button onClick={() => onOpenIncidents(incident.incident_id)} className="qara-chip type-chip min-h-0 px-2 py-1 text-[11px]">
                            View incident
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    {!isPassingNow && !isExistingFailuresSection && !isSingleRunFailedSection && (
                      <>
                        <p className="text-xs text-muted">{isWindowAnalysis ? 'Window-end status' : 'Run status'}</p>
                        <p className={`mt-1 text-sm font-semibold ${isFailure(latest?.state) ? 'text-danger' : isPassing(latest?.state) ? 'text-success' : 'text-warning'}`}>
                          {readableState(latest?.state)}
                        </p>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>}

    </div>
    <TestSidePanel row={activeTest} runs={history?.runs ?? []} onClose={closeTest} />
    </>
  );
}
