import { useMemo, useState } from 'react';
import { Dropdown } from '../../../components/Dropdown';
import { Tooltip } from '../../../components/Tooltip';
import type { HistoryResult, HistoryRow, HistoryRunMeta, HistorySummary } from '../../types';

// ─────────────────────────────────────────────────────────────
// Filter / sort state
// ─────────────────────────────────────────────────────────────

type FilterCls = 'all' | 'stable' | 'flaky' | 'broken' | 'new_failures' | 'fixed';
type SortKey   = 'failures' | 'pass_rate' | 'flip_score' | 'name' | 'suite';

// ─────────────────────────────────────────────────────────────
// Cell state -> compact result glyph
// ─────────────────────────────────────────────────────────────

function RunStateGlyph({ state }: { state: string }) {
  if (state === 'passed') {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-success text-white">
        <svg viewBox="0 0 12 12" fill="none" className="h-3 w-3">
          <path d="M2.5 6.25L4.8 8.5 9.5 3.75" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }

  if (state === 'failed' || state === 'broken') {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-danger text-white">
        <svg viewBox="0 0 12 12" fill="none" className="h-3 w-3">
          <path d="M3.5 3.5L8.5 8.5M8.5 3.5L3.5 8.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </span>
    );
  }

  if (state === 'skipped') {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center rounded-md border border-border-default bg-subtle text-muted">
        <span className="h-px w-2 rounded-full bg-current" />
      </span>
    );
  }

  return (
    <span className="inline-flex h-4 w-4 items-center justify-center rounded-md border border-border-subtle bg-transparent" />
  );
}

function cellTitle(state: string, runLabel: string): string {
  return `${runLabel}: ${state}`;
}

// ─────────────────────────────────────────────────────────────
// Classification badge
// ─────────────────────────────────────────────────────────────

function ClassBadge({ cls }: { cls: string }) {
  if (cls === 'broken' || cls === 'consistently_broken') {
    return <span className="qalens-badge-danger">Failing</span>;
  }
  if (cls === 'flaky') {
    return <span className="qalens-badge-warning">Flaky</span>;
  }
  return <span className="qalens-badge-success">Stable</span>;
}

// ─────────────────────────────────────────────────────────────
// Summary stat cards (window-level, not A vs B)
// ─────────────────────────────────────────────────────────────

function StatCard({ label, value, tone }: { label: string; value: number; tone?: 'danger' | 'warning' | 'success' | 'neutral' }) {
  const valueClass =
    tone === 'danger'  ? 'text-danger'  :
    tone === 'warning' ? 'text-warning' :
    tone === 'success' ? 'text-success' :
    'text-primary';

  return (
    <article className="qalens-card qalens-fade-up flex-1 min-w-[130px] p-5">
      <p className="qalens-metric-label">{label}</p>
      <p className={`qalens-metric-value text-[clamp(1.8rem,3vw,2.5rem)] font-semibold leading-none mt-3 ${valueClass}`}>
        {value}
      </p>
    </article>
  );
}

function HistorySummaryStats({ summary, runCount }: { summary: HistorySummary; runCount: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <StatCard label="Runs"               value={runCount}                  tone="neutral" />
      <StatCard label="Tests"              value={summary.uniqueTests}       tone="neutral" />
      <StatCard label="Stable"             value={summary.stableTests}       tone="success" />
      <StatCard label="Flaky"              value={summary.flakyTests}        tone={summary.flakyTests > 0 ? 'warning' : 'neutral'} />
      <StatCard label="Consistently Failing" value={summary.consistentlyBroken} tone={summary.consistentlyBroken > 0 ? 'danger' : 'neutral'} />
      <StatCard label="New Failures"       value={summary.newFailuresLatest} tone={summary.newFailuresLatest > 0 ? 'danger' : 'neutral'} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Run header row
// ─────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function passRateColor(rate: number): string {
  if (rate >= 0.9) return 'text-success';
  if (rate >= 0.7) return 'text-warning';
  return 'text-danger';
}

function SuiteChip({ suite }: { suite: string }) {
  return (
    <Tooltip content={suite} className="inline-flex max-w-full">
      <span className="qalens-suite-label">{suite}</span>
    </Tooltip>
  );
}

// ─────────────────────────────────────────────────────────────
// Row-level helpers
// ─────────────────────────────────────────────────────────────

function failureCount(row: HistoryRow): number {
  return row.cells.filter(c => c.state === 'failed' || c.state === 'broken').length;
}

function isNewFailure(row: HistoryRow, runs: HistoryRunMeta[]): boolean {
  if (runs.length < 2) return false;
  const latestRun  = runs[runs.length - 1];
  const prevRun    = runs[runs.length - 2];
  const latestCell = row.cells.find(c => c.runId === latestRun.runId);
  const prevCell   = row.cells.find(c => c.runId === prevRun.runId);
  const latestFail = latestCell?.state === 'failed' || latestCell?.state === 'broken';
  const prevPass   = prevCell?.state === 'passed' || prevCell?.state == null || prevCell?.state === 'absent';
  return latestFail && prevPass;
}

function isFixed(row: HistoryRow, runs: HistoryRunMeta[]): boolean {
  if (runs.length < 2) return false;
  const latestRun  = runs[runs.length - 1];
  const prevRun    = runs[runs.length - 2];
  const latestCell = row.cells.find(c => c.runId === latestRun.runId);
  const prevCell   = row.cells.find(c => c.runId === prevRun.runId);
  return latestCell?.state === 'passed' &&
         (prevCell?.state === 'failed' || prevCell?.state === 'broken');
}

// ─────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────

interface HistoryMatrixViewProps {
  data: HistoryResult;
}

export function HistoryMatrixView({ data }: HistoryMatrixViewProps) {
  const [filterCls, setFilterCls] = useState<FilterCls>('all');
  const [search, setSearch]       = useState('');
  const [sortKey, setSortKey]     = useState<SortKey>('failures');

  const { runs, rows, summary } = data;

  const rowsMeta = useMemo(() => rows.map(row => {
    const cellsByRunId = new Map(row.cells.map(cell => [cell.runId, cell]));
    return {
      row,
      cellsByRunId,
      failures:     failureCount(row),
      isNewFailure: isNewFailure(row, runs),
      isFixed:      isFixed(row, runs),
    };
  }), [rows, runs]);

  // Filter
  const sorted = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = rowsMeta.filter(({ row, isNewFailure: nf, isFixed: fx }) => {
      if (filterCls === 'stable'       && row.classification !== 'stable') return false;
      if (filterCls === 'flaky'        && row.classification !== 'flaky') return false;
      if (filterCls === 'broken'       && row.classification !== 'broken' && row.classification !== 'consistently_broken') return false;
      if (filterCls === 'new_failures' && !nf) return false;
      if (filterCls === 'fixed'        && !fx) return false;
      if (needle !== '' && !row.displayName.toLowerCase().includes(needle) &&
          !row.suite.toLowerCase().includes(needle)) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      if (sortKey === 'failures')  return b.failures - a.failures;
      if (sortKey === 'pass_rate') return a.row.passRate - b.row.passRate;
      if (sortKey === 'flip_score')return b.row.flipScore - a.row.flipScore;
      if (sortKey === 'suite')     return a.row.suite.localeCompare(b.row.suite);
      return a.row.displayName.localeCompare(b.row.displayName);
    });
  }, [filterCls, rowsMeta, search, sortKey]);

  // Filter pill counts
  const counts = useMemo(() => ({
    all:          rows.length,
    stable:       rows.filter(r => r.classification === 'stable').length,
    flaky:        rows.filter(r => r.classification === 'flaky').length,
    broken:       rows.filter(r => r.classification === 'broken' || r.classification === 'consistently_broken').length,
    new_failures: rowsMeta.filter(r => r.isNewFailure).length,
    fixed:        rowsMeta.filter(r => r.isFixed).length,
  }), [rows, rowsMeta]);

  const filterPills: { key: FilterCls; label: string; count: number }[] = [
    { key: 'all',          label: 'All',          count: counts.all },
    { key: 'broken',       label: 'Failing',       count: counts.broken },
    { key: 'flaky',        label: 'Flaky',         count: counts.flaky },
    { key: 'stable',       label: 'Stable',        count: counts.stable },
    { key: 'new_failures', label: 'New Failures',  count: counts.new_failures },
    { key: 'fixed',        label: 'Fixed',         count: counts.fixed },
  ];

  return (
    <div className="space-y-5">

      {/* ── Window summary stats ─────────────────────────── */}
      <HistorySummaryStats summary={summary} runCount={runs.length} />

      {/* ── Toolbar ──────────────────────────────────────── */}
      <div className="qalens-card p-4 lg:p-5">
        <div className="flex flex-wrap items-end gap-3">

          {/* Filter pills */}
          <div className="flex items-center gap-1 rounded-full border border-border-default bg-surface-subtle p-1">
            {filterPills.map(pill => (
              <button
                key={pill.key}
                onClick={() => setFilterCls(pill.key)}
                className={[
                  'qalens-pill px-3 py-1.5',
                  filterCls === pill.key
                    ? 'qalens-pill-active'
                    : 'border-transparent bg-transparent hover:bg-hover',
                ].join(' ')}
              >
                <span>{pill.label}</span>
                <span className="text-[10px] text-muted tabular-nums">{pill.count}</span>
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="qalens-control relative flex-1 min-w-[200px] max-w-sm">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted">
              <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
              <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search tests or suites…"
              className="qalens-input h-11 pl-8 pr-3 text-sm"
            />
          </div>

          {/* Sort */}
          <Dropdown
            value={sortKey}
            onChange={value => setSortKey(value as SortKey)}
            triggerClassName="h-11 px-3 text-sm"
            options={[
              { value: 'failures', label: 'Sort: most failures' },
              { value: 'flip_score', label: 'Sort: most unstable' },
              { value: 'pass_rate', label: 'Sort: lowest pass rate' },
              { value: 'suite', label: 'Sort: by suite' },
              { value: 'name', label: 'Sort: by name' },
            ]}
          />

          <span className="text-xs text-muted tabular-nums">
            {sorted.length} of {rows.length} tests
          </span>
        </div>
      </div>

      {/* ── Matrix table ─────────────────────────────────── */}
      <div className="qalens-table-shell">
        <div
          className="overflow-x-auto"
          style={{
            scrollbarWidth: 'thin',
            scrollbarColor: 'rgb(203 213 225) transparent',
          }}
        >
          <table
            className="qalens-table w-full text-sm border-collapse"
            style={{ minWidth: `${420 + runs.length * 64}px` }}
          >
            <thead className="qalens-table-head">
              <tr>
                {/* Sticky left: Test */}
                <th
                  className="text-left px-4 py-3 bg-surface-subtle"
                  style={{ position: 'sticky', left: 0, width: 280, minWidth: 280, zIndex: 2 }}
                >
                  Test
                </th>

                {/* Sticky left: Suite */}
                <th
                  className="text-left px-4 py-3 bg-surface-subtle border-r border-border-subtle"
                  style={{ position: 'sticky', left: 280, width: 120, minWidth: 120, zIndex: 2 }}
                >
                  Suite
                </th>

                {/* Run columns */}
                {runs.map(run => (
                  <th
                    key={run.runId}
                    className="text-center px-2 py-3"
                    style={{ width: 64, minWidth: 64 }}
                  >
                    <div className="flex flex-col items-center gap-0.5">
                      <span className="text-[10px] font-semibold">{run.label}</span>
                      {run.startedAt && (
                        <span className="text-[9px] text-muted font-normal">{fmtDate(run.startedAt)}</span>
                      )}
                      <span className={`text-[9px] font-medium ${passRateColor(run.passRate)}`}>
                        {Math.round(run.passRate * 100)}%
                      </span>
                    </div>
                  </th>
                ))}

                {/* Sticky right: Status */}
                <th
                  className="text-center px-4 py-3 bg-surface-subtle border-l border-border-subtle"
                  style={{ position: 'sticky', right: 64, width: 80, minWidth: 80, zIndex: 2 }}
                >
                  Status
                </th>

                {/* Sticky right: Fails */}
                <th
                  className="text-center px-4 py-3 bg-surface-subtle"
                  style={{ position: 'sticky', right: 0, width: 64, minWidth: 64, zIndex: 2 }}
                >
                  Fails
                </th>
              </tr>
            </thead>

            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td
                    colSpan={4 + runs.length}
                    className="px-6 py-16 text-center text-muted"
                  >
                    No tests match the current filter
                  </td>
                </tr>
              ) : (
                sorted.map(({ row, cellsByRunId, failures }) => (
                  <tr key={row.testName} className="qalens-table-row">

                    {/* Sticky left: Test name */}
                    <td
                      className="qalens-table-cell px-4 py-3 bg-surface"
                      style={{ position: 'sticky', left: 0, zIndex: 1 }}
                    >
                      <div className="space-y-0.5">
                        <div className="font-medium text-primary leading-snug break-words" style={{ maxWidth: 260 }}>
                          {row.displayName}
                        </div>
                        {row.owner && (
                          <div className="text-[11px] text-muted">{row.owner}</div>
                        )}
                      </div>
                    </td>

                    {/* Sticky left: Suite */}
                    <td
                      className="qalens-table-cell px-4 py-3 bg-surface border-r border-border-subtle"
                      style={{ position: 'sticky', left: 280, zIndex: 1 }}
                    >
                      {row.suite ? (
                        <SuiteChip suite={row.suite} />
                      ) : (
                        <span className="text-muted text-xs">—</span>
                      )}
                    </td>

                    {/* Run result glyphs */}
                    {runs.map(run => {
                      const cell = cellsByRunId.get(run.runId);
                      const state = cell?.state ?? 'absent';
                      return (
                        <td key={run.runId} className="qalens-table-cell text-center px-2 py-3">
                          <Tooltip content={cellTitle(state, run.label)} className="inline-flex">
                            <RunStateGlyph state={state} />
                          </Tooltip>
                        </td>
                      );
                    })}

                    {/* Sticky right: Status */}
                    <td
                      className="qalens-table-cell text-center px-4 py-3 bg-surface border-l border-border-subtle"
                      style={{ position: 'sticky', right: 64, zIndex: 1 }}
                    >
                      <ClassBadge cls={row.classification} />
                    </td>

                    {/* Sticky right: Fails */}
                    <td
                      className="qalens-table-cell text-center px-4 py-3 bg-surface"
                      style={{ position: 'sticky', right: 0, zIndex: 1 }}
                    >
                      <span className={`text-sm font-semibold tabular-nums ${failures > 0 ? 'text-danger' : 'text-muted'}`}>
                        {failures}
                      </span>
                    </td>

                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
