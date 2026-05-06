import { useState, useEffect, useMemo, useCallback } from 'react';
import { useProject } from '../hooks/useProject';
import { Dropdown } from '../components/Dropdown';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

type CellState = 'passed' | 'failed' | 'broken' | 'skipped' | 'absent' | string;

interface ApiHistoryCell {
  run_id: string;
  state: CellState;
  fingerprint: string | null;
  error_type: string | null;
  message: string | null;
  stack_trace?: string | null;
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
  health: { pass_rate: number; flip_score: number; classification: string };
  cells: ApiHistoryCell[];
}

interface ApiHistoryRun {
  run_id: string;
  run_sequence: number;
  display_name: string;
  started_at: number | null;
  branch: string | null;
  build_number: string | null;
  report_format: string;
  status_summary: { passed: number; failed: number; skipped: number; total: number };
}

interface ApiHistoryResult {
  project: string | null;
  report_format: string;
  runs: ApiHistoryRun[];
  summary: {
    window_size: number; unique_tests: number; flaky_tests: number;
    consistently_broken: number; stable_tests: number;
    new_failures_latest: number; fixed_latest: number; insufficient_history: number;
  };
  rows: ApiHistoryRow[];
  facets: { suites: string[]; owners: string[]; features: string[]; modules: string[] };
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
}

// ─────────────────────────────────────────────────────────────
// Domain types
// ─────────────────────────────────────────────────────────────

interface Regression {
  id: string;
  name: string;
  owner: string | null;
  ownerInitials: string;
  suite: string | null;
  error: string | null;
  errorKind: string | null;
  stack: string[];
  failures: number;
  flips: number;
  passRate: number;
  incidentId: string | null;
  lastRun: string | null;
  duration: string | null;
  status: 'Failed';
  firstFailed: string | null;
  firstSeenOverall: string | null;
  releaseNumber: string | null;
  branch: string | null;
  runStates: CellState[];
}

interface IncidentCluster {
  id: string;
  badge: string;
  title: string;
  signature: string;
  likelyCause: string | null;
  suggestion: string | null;
  tests: Regression[];
}

// ─────────────────────────────────────────────────────────────
// Row helpers
// ─────────────────────────────────────────────────────────────

function isFailure(state?: CellState | null)  { return state === 'failed' || state === 'broken'; }
function isPassing(state?: CellState | null)   { return state === 'passed'; }
function latestCell(row: ApiHistoryRow)        { return row.cells[row.cells.length - 1] ?? null; }
function baselineCell(row: ApiHistoryRow)      { return row.cells.find(c => c.state !== 'absent') ?? row.cells[0] ?? null; }
function isRegression(row: ApiHistoryRow)      { return isPassing(baselineCell(row)?.state) && isFailure(latestCell(row)?.state); }
function isRecovered(row: ApiHistoryRow)       { return isFailure(baselineCell(row)?.state) && isPassing(latestCell(row)?.state); }
function isStable(row: ApiHistoryRow)          { return row.health.classification === 'STABLE' && isPassing(latestCell(row)?.state); }
function isFlaky(row: ApiHistoryRow)           { return row.health.classification === 'FLAKY'; }

function failureCount(row: ApiHistoryRow) {
  return row.cells.filter(c => isFailure(c.state)).length;
}
function flipCount(row: ApiHistoryRow) {
  const states = row.cells.filter(c => c.state !== 'absent').map(c => isPassing(c.state));
  let flips = 0;
  for (let i = 1; i < states.length; i++) if (states[i] !== states[i - 1]) flips++;
  return flips;
}

function mkInitials(name: string | null): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return (parts[0][0] ?? '?').toUpperCase();
  return ((parts[0][0] ?? '') + (parts[parts.length - 1][0] ?? '')).toUpperCase();
}

function fmtRelative(ts: number | null): string {
  if (ts == null) return '';
  const mins = Math.floor((Date.now() / 1000 - ts) / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return hrs < 24 ? `${hrs}h ago` : `${Math.floor(hrs / 24)}d ago`;
}

function fmtTime(ts: number | null): string {
  if (ts == null) return '';
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
}

function fmtDateTime(ts: number | null): string {
  if (ts == null) return '';
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function trunc(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function signatureMeta(kind: string | null): { color: string; bg: string; border: string } {
  const map: Record<string, { color: string; bg: string; border: string }> = {
    ConnectionPoolExhausted: { color: 'var(--color-warning)', bg: 'rgb(var(--warning-rgb) / 0.12)', border: 'rgb(var(--warning-rgb) / 0.2)' },
    NullPointerException:    { color: 'var(--color-danger)',  bg: 'rgb(var(--danger-rgb) / 0.12)',  border: 'rgb(var(--danger-rgb) / 0.2)' },
    AssertionError:          { color: 'var(--color-info)',    bg: 'rgb(var(--info-rgb) / 0.12)',    border: 'rgb(var(--info-rgb) / 0.2)' },
    TimeoutError:            { color: 'var(--text-muted)',    bg: 'var(--bg-subtle)',                border: 'var(--border-default)' },
  };
  return map[kind ?? ''] ?? map['TimeoutError'];
}

function RunStateStrip({ states, id }: { states: CellState[]; id: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {states.map((state, idx) => {
        const passing = isPassing(state);
        const failing = isFailure(state);
        const tone = passing
          ? 'border-success/25 bg-success/[0.08] text-success'
          : failing
          ? 'border-danger/25 bg-danger/[0.08] text-danger'
          : 'border-border-default bg-surface-subtle text-muted';
        return (
          <span
            key={`${id}-${idx}`}
            className={`inline-flex h-4 w-4 items-center justify-center rounded-full border text-[9px] font-semibold ${tone}`}
          >
            {passing ? '✓' : failing ? '×' : '•'}
          </span>
        );
      })}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────
// Data builders
// ─────────────────────────────────────────────────────────────

function buildRegressions(
  rows: ApiHistoryRow[],
  groups: ApiFailureGroup[],
  runs: ApiHistoryRun[],
): Regression[] {
  const fpToGroup = new Map<string, ApiFailureGroup>();
  for (const g of groups) fpToGroup.set(g.fingerprint, g);
  const runById = new Map(runs.map(run => [run.run_id, run]));

  const latestRun = runs[runs.length - 1] ?? null;

  return rows.filter(isRegression).map(row => {
    const failedCell = [...row.cells].reverse().find(c => isFailure(c.state)) ?? null;
    const firstFailedCell = row.cells.find(c => isFailure(c.state)) ?? null;
    const firstFailedRun = firstFailedCell ? (runById.get(firstFailedCell.run_id) ?? null) : null;
    const fp         = failedCell?.fingerprint ?? null;
    const group      = fp ? (fpToGroup.get(fp) ?? null) : null;
    return {
      id:            row.canonical_name,
      name:          row.display_name,
      owner:         row.owner,
      ownerInitials: mkInitials(row.owner),
      suite:         row.suite,
      error:         failedCell?.message ?? null,
      errorKind:     failedCell?.error_type ?? group?.error_type ?? null,
      stack:         failedCell?.stack_trace ? failedCell.stack_trace.split('\n') : [],
      failures:      failureCount(row),
      flips:         flipCount(row),
      passRate:      row.health.pass_rate,
      incidentId:    group ? group.fingerprint : null,
      lastRun:       latestRun ? fmtRelative(latestRun.started_at) : null,
      duration:      null,
      status:        'Failed' as const,
      firstFailed:   firstFailedRun ? fmtDateTime(firstFailedRun.started_at) : null,
      firstSeenOverall: group?.first_seen_seq != null ? `Run #${group.first_seen_seq}` : null,
      releaseNumber: firstFailedRun?.build_number ?? null,
      branch:        firstFailedRun?.branch ?? null,
      runStates:     row.cells.map(cell => cell.state),
    };
  });
}

function buildClusters(regressions: Regression[], groups: ApiFailureGroup[]): IncidentCluster[] {
  const fpToGroup = new Map<string, ApiFailureGroup>();
  for (const g of groups) fpToGroup.set(g.fingerprint, g);

  const clusterMap = new Map<string, Regression[]>();
  for (const r of regressions) {
    const key = r.incidentId ?? '__uncat__';
    const arr = clusterMap.get(key) ?? [];
    arr.push(r);
    clusterMap.set(key, arr);
  }

  const clusters: IncidentCluster[] = [];
  for (const [id, tests] of clusterMap.entries()) {
    if (id === '__uncat__') continue;
    const g = fpToGroup.get(id);
    clusters.push({
      id,
      badge:       g?.error_type ?? trunc(id, 10),
      title:       g?.error_type ?? trunc(g?.message ?? id, 52),
      signature:   trunc(g?.message ?? id, 44),
      likelyCause: g?.category && g.category !== 'unknown' ? g.category : null,
      suggestion:  null,
      tests,
    });
  }
  clusters.sort((a, b) => b.tests.length - a.tests.length);
  return clusters;
}

// ─────────────────────────────────────────────────────────────
// Icons
// ─────────────────────────────────────────────────────────────

function ChevronIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
// ─────────────────────────────────────────────────────────────
// Atoms
// ─────────────────────────────────────────────────────────────

function Avatar({ initials }: { initials: string }) {
  return (
    <span style={{
      width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
      background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
      fontSize: 9, fontWeight: 600,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      border: '1px solid var(--border-subtle)',
    }}>
      {initials}
    </span>
  );
}

function Dot() {
  return (
    <span style={{
      width: 3, height: 3, borderRadius: 3,
      background: 'var(--text-faint)', display: 'inline-block', flexShrink: 0,
    }} />
  );
}

// ─────────────────────────────────────────────────────────────
// ExpandedDetail — shared between clustered + flat rows
// ─────────────────────────────────────────────────────────────

function ExpandedDetail({ test }: { test: Regression }) {
  const contextRows = [
    { k: 'First failed in window', v: test.firstFailed ?? 'NA' },
    { k: 'First seen overall',     v: test.firstSeenOverall ?? 'NA' },
    { k: 'Release number',         v: test.releaseNumber ?? 'NA' },
    { k: 'Branch',                 v: test.branch ?? 'NA' },
  ];

  return (
    <div
      className="qara-fade-up"
      style={{
        padding: '0.85rem 1.35rem 1.1rem 2.85rem',
        background: 'var(--bg-subtle)',
        borderTop: '1px dashed var(--border-default)',
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr)', gap: '1.25rem' }}>

        {/* Left — error + stack */}
        <div style={{ minWidth: 0 }}>
          <p className="type-eyebrow" style={{ marginBottom: '0.4rem' }}>Error</p>
          {test.error ? (
            <div
              className="mono"
              style={{
                fontSize: '0.8125rem', color: 'var(--color-danger)',
                background: 'var(--bg-surface)', padding: '0.55rem 0.7rem',
                border: '1px solid rgb(var(--danger-rgb) / 0.2)', borderRadius: '0.55rem',
                marginBottom: '0.5rem', wordBreak: 'break-word',
              }}
            >
              {test.error}
            </div>
          ) : (
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
              No error message recorded.
            </p>
          )}
          <p className="type-eyebrow" style={{ marginBottom: '0.4rem', marginTop: '0.75rem' }}>Stack trace</p>
          {test.stack.length > 0 ? (
            <pre
              className="mono"
              style={{
                margin: 0, fontSize: '0.75rem', color: 'var(--text-secondary)',
                whiteSpace: 'pre', overflowX: 'auto', overflowY: 'auto', lineHeight: 1.6,
                background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
                borderRadius: '0.55rem', padding: '0.6rem 0.75rem', maxHeight: '12rem',
              }}
            >
              {test.stack.join('\n')}
            </pre>
          ) : (
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              No stack trace available.
            </p>
          )}
        </div>

        {/* Right — context key/value */}
        <div>
          <p className="type-eyebrow" style={{ marginBottom: '0.4rem' }}>Context</p>
          {contextRows.map(({ k, v }) => (
            <div
              key={k}
              style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '0.35rem 0', borderBottom: '1px solid var(--border-subtle)',
                fontSize: '0.8125rem',
              }}
            >
              <span style={{ color: 'var(--text-muted)' }}>{k}</span>
              <span className="mono type-nums">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// TestRow — clustered view
// ─────────────────────────────────────────────────────────────

function TestRow({ test, open, onToggle }: { test: Regression; open: boolean; onToggle: () => void }) {
  return (
    <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <div
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.75rem',
          padding: '0.7rem 1.35rem 0.7rem 2.85rem',
          cursor: 'pointer', transition: 'background 120ms ease',
          background: open ? 'var(--bg-subtle)' : undefined,
        }}
      >
        <span style={{
          display: 'inline-flex', flexShrink: 0, width: 14,
          color: 'var(--text-faint)',
          transition: 'transform 150ms ease',
          transform: open ? 'rotate(90deg)' : 'none',
        }}>
          <ChevronIcon size={12} />
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span className="mono" style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {test.name}
            </span>
            <span className="qara-badge-danger" style={{ padding: '0.2rem 0.5rem', fontSize: '0.65rem' }}>
              New regression
            </span>
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.45rem',
            fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', flexWrap: 'wrap',
          }}>
            <Avatar initials={test.ownerInitials} />
            <span>{test.owner ?? 'Unassigned'}</span>
            <Dot />
            <span>{test.suite ?? 'No suite'}</span>
            <Dot />
            <span className="type-nums">
              {Math.round(test.passRate * 100)}% pass · {test.failures}f · {test.flips} flip{test.flips !== 1 ? 's' : ''}
            </span>
            {test.runStates.length > 0 && (
              <>
                <Dot />
                <RunStateStrip states={test.runStates} id={test.id} />
              </>
            )}
          </div>
        </div>

      </div>
      {open && <ExpandedDetail test={test} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// FlatRow — flat list view
// ─────────────────────────────────────────────────────────────

function FlatRow({ test, open, onToggle }: { test: Regression; open: boolean; onToggle: () => void }) {
  const sig = signatureMeta(test.errorKind);
  return (
    <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <div
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.75rem',
          padding: '0.75rem 1.35rem',
          cursor: 'pointer', transition: 'background 120ms ease',
          background: open ? 'var(--bg-subtle)' : undefined,
        }}
      >
        <span style={{
          display: 'inline-flex', flexShrink: 0, width: 14,
          color: 'var(--text-faint)',
          transition: 'transform 150ms ease',
          transform: open ? 'rotate(90deg)' : 'none',
        }}>
          <ChevronIcon size={12} />
        </span>

        <div style={{ flex: '0 1 42%', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="qara-badge-danger" style={{ padding: '0.2rem 0.5rem', fontSize: '0.65rem' }}>
              New regression
            </span>
            <span className="mono" style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {test.name}
            </span>
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.45rem',
            fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem',
          }}>
            <Avatar initials={test.ownerInitials} />
            <span>{test.owner ?? 'Unassigned'}</span>
            <Dot />
            <span>{test.suite ?? 'No suite'}</span>
          </div>
        </div>

        {/* Signature */}
        <div style={{ width: 210, flexShrink: 0 }}>
          {test.errorKind && (
            <span style={{
              display: 'inline-flex', alignItems: 'center',
              fontSize: '0.6875rem', fontWeight: 600,
              padding: '0.25rem 0.55rem', borderRadius: 999,
              color: sig.color, background: sig.bg, border: `1px solid ${sig.border}`,
              fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'nowrap',
            }}>
              {test.errorKind}
            </span>
          )}
        </div>

        {/* Fail rate */}
        <div style={{ width: 240, textAlign: 'right', flexShrink: 0, marginLeft: 'auto' }}>
          <div className="type-nums" style={{ fontSize: '0.875rem', color: 'var(--color-danger)', fontWeight: 600 }}>
            {Math.round((1 - test.passRate) * 100)}% fail
          </div>
          <div style={{ fontSize: '0.6875rem', color: 'var(--text-faint)', marginTop: '0.1rem' }}>
            {test.failures}f · {test.flips} flip{test.flips !== 1 ? 's' : ''}
          </div>
          {test.runStates.length > 0 && (
            <div style={{ marginTop: '0.35rem', display: 'flex', justifyContent: 'flex-end' }}>
              <RunStateStrip states={test.runStates} id={test.id} />
            </div>
          )}
        </div>
      </div>
      {open && <ExpandedDetail test={test} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// IncidentGroup — one cluster in the clustered view
// ─────────────────────────────────────────────────────────────

function IncidentGroup({
  cluster, open, onToggle, openRows, onToggleRow, isFirst,
}: {
  cluster: IncidentCluster;
  open: boolean;
  onToggle: () => void;
  openRows: Set<string>;
  onToggleRow: (id: string) => void;
  isFirst: boolean;
}) {
  const isNamed = cluster.id !== '__uncat__';
  const count   = cluster.tests.length;

  return (
    <div style={{ borderTop: isFirst ? '1px solid var(--border-subtle)' : '1px solid var(--border-subtle)' }}>
      {/* Group header */}
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '0.9rem 1.35rem',
          background: 'var(--bg-surface)', border: 'none', cursor: 'pointer', textAlign: 'left',
          font: 'inherit', color: 'inherit', gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap', minWidth: 0 }}>
          <span style={{
            display: 'inline-flex', color: 'var(--text-muted)',
            transition: 'transform 150ms ease',
            transform: open ? 'rotate(90deg)' : 'none',
          }}>
            <ChevronIcon size={14} />
          </span>
          {isNamed ? null : (
            <span className="qara-pill">UNGROUPED</span>
          )}
          <span style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            {cluster.title}
          </span>
          <span style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
            <span className="type-nums" style={{ color: 'var(--color-danger)', fontWeight: 600 }}>{count}</span>
            {' '}{count === 1 ? 'test' : 'tests'} affected
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexShrink: 0 }}>
          <span style={{ color: 'var(--text-faint)', fontSize: '0.75rem' }}>
            {open ? 'Hide' : 'Show'}
          </span>
        </div>
      </button>

      {/* Group body */}
      {open && (
        <div className="qara-fade-up">
          {cluster.tests.map(t => (
            <TestRow
              key={t.id}
              test={t}
              open={openRows.has(t.id)}
              onToggle={() => onToggleRow(t.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// RegressionsCard
// ─────────────────────────────────────────────────────────────

type SortBy = 'severity' | 'suite' | 'owner' | 'time';

function RegressionsCard({
  regressions,
  clusters,
}: {
  regressions: Regression[];
  clusters: IncidentCluster[];
}) {
  const [view, setView]               = useState<'clustered' | 'flat'>('clustered');
  const [openIds, setOpenIds]         = useState<Set<string>>(new Set());
  const [openClusters, setOpenClusters] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy]           = useState<SortBy>('severity');
  const allClusterIds = useMemo(
    () => [...clusters.map(c => c.id), '__uncat__'],
    [clusters],
  );

  // Keep cluster set in sync when data changes; default to collapsed.
  useEffect(() => {
    setOpenClusters(new Set());
  }, [allClusterIds]);

  const toggleRow = useCallback((id: string) => {
    setOpenIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }, []);
  const toggleCluster = useCallback((id: string) => {
    setOpenClusters(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }, []);

  const expandAll   = () => {
    if (view === 'clustered') {
      setOpenClusters(new Set(allClusterIds));
      return;
    }
    setOpenIds(new Set(regressions.map(r => r.id)));
  };
  const collapseAll = () => {
    if (view === 'clustered') {
      setOpenClusters(new Set());
      return;
    }
    setOpenIds(new Set());
  };

  const uncategorized = regressions.filter(r => !r.incidentId);

  const sorted = useMemo(() => {
    const arr = [...regressions];
    if (sortBy === 'severity') arr.sort((a, b) => b.failures - a.failures);
    if (sortBy === 'suite')    arr.sort((a, b) => (a.suite ?? '').localeCompare(b.suite ?? ''));
    if (sortBy === 'owner')    arr.sort((a, b) => (a.owner ?? '').localeCompare(b.owner ?? ''));
    if (sortBy === 'time')     arr.sort((a, b) => (a.firstFailed ?? '').localeCompare(b.firstFailed ?? ''));
    return arr;
  }, [regressions, sortBy]);

  return (
    <div className="qara-card" style={{ overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
        padding: '1.1rem 1.35rem 1rem',
        borderBottom: '1px solid var(--border-subtle)',
        background: 'var(--bg-subtle)',
        gap: '1rem', flexWrap: 'wrap',
      }}>
        <div>
          <p className="type-eyebrow" style={{ marginBottom: '0.35rem' }}>New regressions</p>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            <span className="type-nums" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
              {regressions.length}
            </span>
            <span style={{ color: 'var(--text-faint)' }}>{'  ·  '}</span>
            Transition: Passed → Failed
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
          <div className="qara-toolbar-segment" role="tablist" aria-label="View mode">
            <button
              role="tab"
              aria-selected={view === 'clustered'}
              onClick={() => setView('clustered')}
              className={`qara-segment-button${view === 'clustered' ? ' qara-segment-button-active' : ''}`}
            >
              Clustered
            </button>
            <button
              role="tab"
              aria-selected={view === 'flat'}
              onClick={() => setView('flat')}
              className={`qara-segment-button${view === 'flat' ? ' qara-segment-button-active' : ''}`}
            >
              Flat list
            </button>
          </div>
          {view === 'flat' && (
            <Dropdown
              value={sortBy}
              onChange={value => setSortBy(value as SortBy)}
              ariaLabel="Sort flat regression list"
              options={[
                { value: 'severity', label: 'Sort: Severity' },
                { value: 'suite', label: 'Sort: Suite' },
                { value: 'owner', label: 'Sort: Owner' },
                { value: 'time', label: 'Sort: First failed' },
              ]}
              triggerClassName="type-nums px-3.5 text-[0.8125rem]"
            />
          )}
          <button
            className="qara-chip"
            onClick={view === 'clustered' ? (openClusters.size ? collapseAll : expandAll) : (openIds.size ? collapseAll : expandAll)}
          >
            {view === 'clustered'
              ? (openClusters.size ? 'Collapse all' : 'Expand all')
              : (openIds.size ? 'Collapse all' : 'Expand all')}
          </button>
        </div>
      </div>

      {/* Clustered view */}
      {view === 'clustered' && (
        <div>
          {clusters.map((cluster, i) => (
            <IncidentGroup
              key={cluster.id}
              cluster={cluster}
              open={openClusters.has(cluster.id)}
              onToggle={() => toggleCluster(cluster.id)}
              openRows={openIds}
              onToggleRow={toggleRow}
              isFirst={i === 0}
            />
          ))}
          {uncategorized.length > 0 && (
            <IncidentGroup
              cluster={{
                id: '__uncat__',
                badge: 'UNGROUPED',
                title: 'Uncategorized',
                signature: 'No shared signature — likely unrelated failures',
                likelyCause: null,
                suggestion: null,
                tests: uncategorized,
              }}
              open={openClusters.has('__uncat__')}
              onToggle={() => toggleCluster('__uncat__')}
              openRows={openIds}
              onToggleRow={toggleRow}
              isFirst={clusters.length === 0}
            />
          )}
        </div>
      )}

      {/* Flat view */}
      {view === 'flat' && (
        <div>
          {/* Column header */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.75rem',
            padding: '0.55rem 1.35rem',
            fontSize: '0.6875rem', fontWeight: 600, letterSpacing: '0.08em',
            textTransform: 'uppercase', color: 'var(--text-muted)',
            background: 'var(--bg-subtle)',
            borderTop: '1px solid var(--border-subtle)',
            borderBottom: '1px solid var(--border-subtle)',
          }}>
            <div style={{ width: 14 }} />
            <div style={{ flex: '0 1 42%', minWidth: 0 }}>Test</div>
            <div style={{ width: 210 }}>Signature</div>
            <div style={{ width: 240, textAlign: 'right', marginLeft: 'auto' }}>Fail rate</div>
          </div>
          {sorted.map(t => (
            <FlatRow
              key={t.id}
              test={t}
              open={openIds.has(t.id)}
              onToggle={() => toggleRow(t.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// RegressionsView — main export
// ─────────────────────────────────────────────────────────────

export function RegressionsView({
  runIds,
  runsWindow,
}: {
  runIds: string[];
  runsWindow: number;
}) {
  const { currentProject } = useProject();
  const [history, setHistory] = useState<ApiHistoryResult | null>(null);
  const [groups,  setGroups]  = useState<ApiFailureGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const groupParams = new URLSearchParams({ limit: '20' });
    if (currentProject) groupParams.set('project', currentProject);

    const historyRequest = runIds.length > 0
      ? fetch('/api/compare/custom', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ run_ids: runIds, filters: {} }),
        })
      : fetch(`/api/compare/history?${new URLSearchParams({
          limit: String(runsWindow),
          ...(currentProject ? { project: currentProject } : {}),
        })}`);

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

  const rows       = history?.rows ?? [];
  const regressions = useMemo(() => buildRegressions(rows, groups, history?.runs ?? []), [rows, groups, history]);
  const clusters    = useMemo(() => buildClusters(regressions, groups), [regressions, groups]);

  if (loading) {
    return (
      <div className="space-y-3 animate-pulse">
        {[1, 2, 3].map(i => <div key={i} className="h-16 rounded-2xl bg-surface-subtle" />)}
      </div>
    );
  }

  if (error) {
    return <div className="qara-error-banner">Failed to load regressions: {error}</div>;
  }

  if (!history || regressions.length === 0) {
    return (
      <div className="qara-empty-state">
        <div className="qara-empty-icon">✓</div>
        <p className="type-empty-title">No regressions found</p>
        <p className="type-empty-subtitle">All tests are stable or recovering in this window.</p>
      </div>
    );
  }

  return <RegressionsCard regressions={regressions} clusters={clusters} />;
}
