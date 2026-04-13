import React, { useState } from 'react';
import type { ComparisonRow, ComparisonMetrics, DeltaDirection, TestStatus } from '../../types';

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

const STATUS_ICON: Record<TestStatus, string> = {
  passed:  '✅',
  failed:  '❌',
  flaky:   '⚠️',
  skipped: '⏭',
};

const STATUS_COLOR: Record<TestStatus, string> = {
  passed:  'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  failed:  'text-red-400     bg-red-500/10     border-red-500/20',
  flaky:   'text-amber-400   bg-amber-500/10   border-amber-500/20',
  skipped: 'text-zinc-400    bg-zinc-800       border-zinc-700',
};

const DELTA_CONFIG: Record<DeltaDirection, { label: string; color: string; icon: string }> = {
  improved:  { label: 'Improved',  color: 'text-emerald-400  bg-emerald-500/10  border-emerald-500/20',  icon: '↑' },
  regressed: { label: 'Regressed', color: 'text-red-400      bg-red-500/10      border-red-500/20',      icon: '↓' },
  stable:    { label: 'Stable',    color: 'text-zinc-500     bg-zinc-800        border-zinc-700',         icon: '—' },
  new:       { label: 'New',       color: 'text-violet-400   bg-violet-500/10   border-violet-500/20',   icon: '★' },
  fixed:     { label: 'Fixed',     color: 'text-sky-400      bg-sky-500/10      border-sky-500/20',       icon: '✓' },
};

function StatusBadge({ status }: { status: TestStatus }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full border ${STATUS_COLOR[status]}`}>
      {STATUS_ICON[status]} {status}
    </span>
  );
}

function DeltaBadge({ delta }: { delta: DeltaDirection }) {
  const cfg = DELTA_CONFIG[delta];
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${cfg.color}`}>
      {cfg.icon} {cfg.label}
    </span>
  );
}

type FilterDelta = 'all' | DeltaDirection;

// ─────────────────────────────────────────────────────────────
// Main table
// ─────────────────────────────────────────────────────────────

interface ComparisonTableProps {
  rows:     ComparisonRow[];
  metricsA: ComparisonMetrics;
  metricsB: ComparisonMetrics;
}

export function ComparisonTable({ rows, metricsA, metricsB }: ComparisonTableProps) {
  const [filter,  setFilter]  = useState<FilterDelta>('all');
  const [search,  setSearch]  = useState('');
  const [sortKey, setSortKey] = useState<'delta' | 'suite' | 'name'>('delta');

  // ── Filter / search / sort ─────────────────────────────────

  const visible = rows
    .filter(r => filter === 'all' || r.delta === filter)
    .filter(r =>
      search === '' ||
      r.displayName.toLowerCase().includes(search.toLowerCase()) ||
      r.suite.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => {
      if (sortKey === 'delta') {
        const order: DeltaDirection[] = ['regressed', 'new', 'flaky', 'stable', 'improved', 'fixed'];
        return order.indexOf(a.delta) - order.indexOf(b.delta);
      }
      if (sortKey === 'suite') return a.suite.localeCompare(b.suite);
      return a.displayName.localeCompare(b.displayName);
    });

  const filterCounts = {
    all:       rows.length,
    regressed: rows.filter(r => r.delta === 'regressed').length,
    improved:  rows.filter(r => r.delta === 'improved').length,
    stable:    rows.filter(r => r.delta === 'stable').length,
    fixed:     rows.filter(r => r.delta === 'fixed').length,
    new:       rows.filter(r => r.delta === 'new').length,
  };

  // ─────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">

      {/* ── Toolbar ────────────────────────────────────────── */}
      <div className="flex items-center gap-3 flex-wrap">

        {/* Delta filters */}
        <div className="flex items-center gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
          {(['all', 'regressed', 'improved', 'stable', 'fixed'] as FilterDelta[]).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={[
                'px-3 py-1 rounded-md text-xs font-medium transition-all duration-150 capitalize',
                filter === f
                  ? 'bg-zinc-700 text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-300',
              ].join(' ')}
            >
              {f === 'all' ? 'All' : f}
              {' '}
              <span className="opacity-60">({filterCounts[f as keyof typeof filterCounts] ?? 0})</span>
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter tests…"
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg pl-8 pr-3 py-1.5 text-sm text-zinc-300 placeholder:text-zinc-600 outline-none focus:border-zinc-600 transition-colors"
          />
        </div>

        {/* Sort */}
        <select
          value={sortKey}
          onChange={e => setSortKey(e.target.value as typeof sortKey)}
          className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-400 outline-none cursor-pointer hover:border-zinc-700 transition-colors appearance-none"
        >
          <option value="delta">Sort: by change</option>
          <option value="suite">Sort: by suite</option>
          <option value="name">Sort: by name</option>
        </select>

        <span className="text-xs text-zinc-600">
          {visible.length} of {rows.length} tests
        </span>
      </div>

      {/* ── Table ─────────────────────────────────────────── */}
      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/50">
              <th className="text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-4 py-3">
                Test
              </th>
              <th className="text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-3 py-3">
                Suite
              </th>
              <th className="text-center text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-3 py-3">
                {metricsA.label}
              </th>
              <th className="text-center text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-3 py-3">
                {metricsB.label}
              </th>
              <th className="text-center text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-3 py-3">
                Change
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center py-12 text-zinc-600">
                  No tests match the current filter
                </td>
              </tr>
            ) : (
              visible.map((row, i) => (
                <tr
                  key={row.testName}
                  className={[
                    'border-b border-zinc-800/50 transition-colors duration-100',
                    'hover:bg-zinc-800/40',
                    row.delta === 'regressed' ? 'bg-red-500/[0.03]' : '',
                    row.delta === 'improved'  ? 'bg-emerald-500/[0.03]' : '',
                  ].join(' ')}
                >
                  {/* Test name */}
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-xs text-zinc-200 font-medium">
                        {row.displayName}
                      </span>
                      {row.owner && (
                        <span className="text-[10px] text-zinc-600">{row.owner}</span>
                      )}
                    </div>
                  </td>

                  {/* Suite */}
                  <td className="px-3 py-3">
                    <span className="text-xs text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded-md">
                      {row.suite}
                    </span>
                  </td>

                  {/* Status A */}
                  <td className="px-3 py-3 text-center">
                    <StatusBadge status={row.statusA} />
                  </td>

                  {/* Status B */}
                  <td className="px-3 py-3 text-center">
                    <StatusBadge status={row.statusB} />
                  </td>

                  {/* Delta */}
                  <td className="px-3 py-3 text-center">
                    <DeltaBadge delta={row.delta} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
