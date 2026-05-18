import { useState, useEffect, useMemo } from 'react';
import { Dropdown } from '../../../components/Dropdown';
import type { ComparisonRow, ComparisonMetrics, DeltaDirection, TestStatus } from '../../types';

const STATUS_CONFIG: Record<TestStatus, { label: string; className: string }> = {
  passed:  { label: 'Pass',    className: 'qalens-badge-success' },
  failed:  { label: 'Fail',    className: 'qalens-badge-danger' },
  flaky:   { label: 'Flaky',   className: 'qalens-badge-warning' },
  skipped: { label: 'Skip',    className: 'qalens-badge-neutral' },
};

const DELTA_CONFIG: Record<DeltaDirection, { label: string; className: string }> = {
  improved:  { label: 'Recovered', className: 'qalens-badge-success' },
  regressed: { label: 'Regressed', className: 'qalens-badge-danger' },
  stable:    { label: 'Stable',    className: 'qalens-badge-neutral' },
  broken:    { label: 'Broken',    className: 'qalens-badge-danger'  },
  new:       { label: 'New',       className: 'qalens-badge-info' },
};

function StatusBadge({ status }: { status: TestStatus }) {
  const cfg = STATUS_CONFIG[status];
  return <span className={cfg.className}>{cfg.label}</span>;
}

function DeltaBadge({ delta }: { delta: DeltaDirection }) {
  const cfg = DELTA_CONFIG[delta];
  return <span className={cfg.className}>{cfg.label}</span>;
}

type FilterDelta = 'all' | DeltaDirection;

interface ComparisonTableProps {
  rows: ComparisonRow[];
  metricsA: ComparisonMetrics;
  metricsB: ComparisonMetrics;
  initialFilter?: FilterDelta;
}

export function ComparisonTable({ rows, metricsA, metricsB, initialFilter = 'all' }: ComparisonTableProps) {
  const [filter, setFilter] = useState<FilterDelta>(initialFilter);

  useEffect(() => {
    setFilter(initialFilter);
  }, [initialFilter]);
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<'delta' | 'suite' | 'name'>('delta');
  const sortOptions = [
    { value: 'delta', label: 'Sort: by change' },
    { value: 'suite', label: 'Sort: by suite' },
    { value: 'name', label: 'Sort: by name' },
  ] as const;

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows
      .filter(r => filter === 'all' || r.delta === filter)
      .filter(r =>
        needle === '' ||
        r.displayName.toLowerCase().includes(needle) ||
        r.suite.toLowerCase().includes(needle)
      )
      .sort((a, b) => {
        if (sortKey === 'delta') {
          const order: DeltaDirection[] = ['regressed', 'broken', 'new', 'improved', 'stable'];
          return order.indexOf(a.delta) - order.indexOf(b.delta);
        }
        if (sortKey === 'suite') return a.suite.localeCompare(b.suite);
        return a.displayName.localeCompare(b.displayName);
      });
  }, [filter, rows, search, sortKey]);

  const filterCounts = useMemo(() => ({
    all:       rows.length,
    regressed: rows.filter(r => r.delta === 'regressed').length,
    broken:    rows.filter(r => r.delta === 'broken').length,
    improved:  rows.filter(r => r.delta === 'improved').length,
    stable:    rows.filter(r => r.delta === 'stable').length,
    new:       rows.filter(r => r.delta === 'new').length,
  }), [rows]);

  const filterPills: { key: FilterDelta; label: string; count: number }[] = [
    { key: 'all',       label: 'All',       count: filterCounts.all       },
    { key: 'regressed', label: 'Regressed', count: filterCounts.regressed },
    { key: 'broken',    label: 'Broken',    count: filterCounts.broken    },
    { key: 'improved',  label: 'Recovered', count: filterCounts.improved  },
    { key: 'stable',    label: 'Stable',    count: filterCounts.stable    },
  ];

  return (
    <div className="space-y-4">
      <div className="qalens-card p-4 lg:p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-2 rounded-full border border-border-default bg-surface-subtle p-1">
            {filterPills.map(pill => (
              <button
                key={pill.key}
                onClick={() => setFilter(pill.key)}
                className={[
                  'qalens-pill px-3 py-1.5',
                  filter === pill.key ? 'qalens-pill-active' : 'border-transparent bg-transparent hover:bg-hover',
                ].join(' ')}
              >
                <span>{pill.label}</span>
                <span className="text-[10px] text-muted tabular-nums">{pill.count}</span>
              </button>
            ))}
          </div>

          <div className="qalens-control relative flex-1 min-w-[220px] max-w-sm">
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

          <Dropdown
            value={sortKey}
            onChange={value => setSortKey(value as typeof sortKey)}
            triggerClassName="h-11 px-3 text-sm"
            options={sortOptions.map(option => ({ value: option.value, label: option.label }))}
          />

          <span className="text-xs text-muted tabular-nums">
            {visible.length} of {rows.length} tests
          </span>
        </div>
      </div>

      <div className="qalens-table-shell">
        <table className="qalens-table w-full text-sm">
          <thead className="qalens-table-head">
            <tr>
              <th className="text-left w-[48%]">Test</th>
              <th className="text-left">Suite</th>
              <th className="text-center w-[12%]">{metricsA.label}</th>
              <th className="text-center w-[12%]">{metricsB.label}</th>
              <th className="text-center w-[14%]">Change</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-16 text-center text-muted">
                  No tests match the current filter
                </td>
              </tr>
            ) : (
              visible.map(row => (
                <tr
                  key={row.testName}
                  className="qalens-table-row"
                >
                  <td className="qalens-table-cell">
                    <div className="space-y-1">
                      <div className="font-medium text-primary leading-snug">
                        {row.displayName}
                      </div>
                      {row.owner && (
                        <div className="text-[11px] text-muted">
                          {row.owner}
                        </div>
                      )}
                    </div>
                  </td>

                  <td className="qalens-table-cell">
                    <span className="qalens-pill">
                      {row.suite}
                    </span>
                  </td>

                  <td className="qalens-table-cell text-center">
                    <StatusBadge status={row.statusA} />
                  </td>

                  <td className="qalens-table-cell text-center">
                    <StatusBadge status={row.statusB} />
                  </td>

                  <td className="qalens-table-cell text-center">
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
