import { useState } from 'react';
import { Dropdown } from '../../../components/Dropdown';
import type { ApiEntityCompareResult, ApiEntityCompareRow, ApiEntityMetrics } from '../../hooks/useCompareData';

// ─────────────────────────────────────────────────────────────
// Tiny shared helpers
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

// ─────────────────────────────────────────────────────────────
// 1. Insight Banner — works for 2 or 3 entities
// ─────────────────────────────────────────────────────────────

function InsightBanner({ data }: { data: ApiEntityCompareResult }) {
  const { run_count } = data;

  const allEntities = [
    { label: data.label_a, m: data.metrics_a },
    { label: data.label_b, m: data.metrics_b },
    ...(data.metrics_c ? [{ label: data.label_c!, m: data.metrics_c }] : []),
  ];

  const ranked = [...allEntities].sort((a, b) => b.m.pass_rate - a.m.pass_rate);
  const best  = ranked[0];
  const worst = ranked[ranked.length - 1];
  const isTied = ranked.every(e => Math.abs(e.m.pass_rate - best.m.pass_rate) < 0.03);

  if (isTied) {
    const names = allEntities.map(e => e.label.split(' ')[0]);
    const nameList = names.length === 2
      ? `${names[0]} and ${names[1]}`
      : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
    return (
      <section className="qara-card-soft qara-fade-up px-5 py-4">
        <p className="text-sm text-secondary">
          <span className="font-medium text-primary">{nameList}</span> are performing similarly
          over the last {run_count} run{run_count !== 1 ? 's' : ''}.
        </p>
      </section>
    );
  }

  const chips: string[] = [];
  if (Math.abs(best.m.pass_rate - worst.m.pass_rate) >= 0.03)
    chips.push(`Higher pass rate (${pct(best.m.pass_rate)} vs ${pct(worst.m.pass_rate)})`);
  if (Math.abs(best.m.failure_rate - worst.m.failure_rate) >= 0.03)
    chips.push(`Lower failure rate (${pct(best.m.failure_rate)} vs ${pct(worst.m.failure_rate)})`);
  if (best.m.flaky_count !== worst.m.flaky_count)
    chips.push(`Fewer flaky tests (${best.m.flaky_count} vs ${worst.m.flaky_count})`);

  return (
    <section className="qara-card-soft qara-fade-up px-5 py-4">
      <div className="space-y-3">
        <p className="text-sm text-primary">
          <span className="font-semibold text-info">{best.label.split(' ')[0]}</span> is most stable
          over the last {run_count} run{run_count !== 1 ? 's' : ''}.
          <span className="text-muted font-normal ml-1">({worst.label.split(' ')[0]} trails)</span>
        </p>
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {chips.map(chip => (
              <span key={chip} className="qara-pill">{chip}</span>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 2. Metric Comparison Strip — N-entity aware
// ─────────────────────────────────────────────────────────────

interface MetricStripCardProps {
  label:         string;
  values:        number[];
  names:         string[];
  format:        'pct' | 'count';
  lowerIsBetter: boolean;
}

function MetricStripCard({ label, values, names, format, lowerIsBetter }: MetricStripCardProps) {
  const fmt = (v: number) => format === 'pct' ? pct(v) : String(v);
  const threshold = format === 'pct' ? 0.01 : 0.5;

  const best  = lowerIsBetter ? Math.min(...values) : Math.max(...values);
  const worst = lowerIsBetter ? Math.max(...values) : Math.min(...values);
  const spread = Math.abs(best - worst);
  const tied  = spread < threshold;

  const colorFor = (v: number) =>
    tied ? 'text-primary' : v === best ? 'text-success' : v === worst ? 'text-danger' : 'text-primary';

  let deltaLabel = 'Even';
  let deltaClass = 'qara-badge-neutral';
  if (!tied) {
    const raw = format === 'pct' ? pct(spread) : String(Math.round(spread));
    const bestIdx = values.findIndex(v => v === best);
    deltaLabel = `${names[bestIdx].split(' ')[0]} +${raw}`;
    deltaClass = 'qara-badge-success';
  }

  const colGrid = values.length === 3 ? 'grid-cols-3' : 'grid-cols-2';

  return (
    <article className="qara-card qara-fade-up p-5">
      <div className="flex items-start justify-between gap-3 mb-4">
        <p className="qara-metric-label">{label}</p>
        <span className={deltaClass}>{deltaLabel}</span>
      </div>
      <div className={`grid ${colGrid} gap-3`}>
        {values.map((v, i) => (
          <div key={names[i]} className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted truncate" title={names[i]}>
              {names[i].split(' ')[0]}
            </p>
            <div className={`qara-metric-value text-2xl font-semibold leading-none ${colorFor(v)}`}>
              {fmt(v)}
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}

function MetricStrip({ data }: { data: ApiEntityCompareResult }) {
  const allM = [data.metrics_a, data.metrics_b, ...(data.metrics_c ? [data.metrics_c] : [])];
  const names = allM.map(m => m.label);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
      <MetricStripCard label="Tests Owned"  values={allM.map(m => m.total_tests)}  names={names} format="count" lowerIsBetter={false} />
      <MetricStripCard label="Pass Rate"    values={allM.map(m => m.pass_rate)}    names={names} format="pct"   lowerIsBetter={false} />
      <MetricStripCard label="Failure Rate" values={allM.map(m => m.failure_rate)} names={names} format="pct"   lowerIsBetter={true}  />
      <MetricStripCard label="Flaky Tests"  values={allM.map(m => m.flaky_count)}  names={names} format="count" lowerIsBetter={true}  />
      <MetricStripCard label="New Failures" values={allM.map(m => m.new_failures)} names={names} format="count" lowerIsBetter={true}  />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// 3. Entity Cards
// ─────────────────────────────────────────────────────────────

function EntityCard({ metrics, rows }: {
  metrics: ApiEntityMetrics;
  rows:    ApiEntityCompareRow[];
}) {
  const failing = rows.filter(r => classifyRow(r) === 'failing');
  const flaky   = rows.filter(r => classifyRow(r) === 'flaky');

  const mostUnstable = [...rows]
    .sort((a, b) => failCount(b) - failCount(a))
    .find(r => failCount(r) > 0);

  const initial   = metrics.label.charAt(0).toUpperCase();
  const passTone  = metrics.pass_rate >= 0.9 ? 'text-success'
                  : metrics.pass_rate >= 0.7 ? 'text-warning'
                  : 'text-danger';

  return (
    <article className="qara-card qara-fade-up overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 p-5 border-b border-border-subtle">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-border-default bg-selected text-sm font-semibold text-info">
            {initial}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-primary truncate">{metrics.label}</p>
            <p className="text-[11px] text-muted">{metrics.total_tests} tests owned</p>
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          <p className={`text-2xl font-bold tabular-nums tracking-tight ${passTone}`}>
            {pct(metrics.pass_rate)}
          </p>
          <p className="text-[10px] text-muted mt-0.5">pass rate</p>
        </div>
      </div>

      {/* Metric rows */}
      <div className="px-5 divide-y divide-border-subtle">
        {[
          { label: 'Failures',     value: metrics.failed,       color: metrics.failed > 0       ? 'text-danger'  : 'text-muted' },
          { label: 'Flaky tests',  value: metrics.flaky_count,  color: metrics.flaky_count > 0  ? 'text-warning' : 'text-muted' },
          { label: 'New failures', value: metrics.new_failures, color: metrics.new_failures > 0 ? 'text-warning' : 'text-muted' },
        ].map(s => (
          <div key={s.label} className="flex items-center justify-between py-2.5">
            <span className="text-xs text-muted">{s.label}</span>
            <span className={`text-sm font-semibold tabular-nums ${s.color}`}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Pass rate bar */}
      <div className="px-5 py-3 border-t border-border-subtle">
        <div className="qara-meter-track">
          <div
            className="qara-meter-fill transition-all duration-500"
            style={{ width: `${Math.round(metrics.pass_rate * 100)}%` }}
          />
        </div>
      </div>

      {/* Most unstable */}
      {mostUnstable ? (
        <div className="px-5 pb-4 border-t border-border-subtle pt-3">
          <p className="text-[10px] text-muted uppercase tracking-wider mb-2">Most unstable</p>
          <span className="text-[11px] text-secondary font-mono leading-relaxed break-all block">
            {mostUnstable.display_name}
          </span>
          <p className="text-[10px] text-muted mt-1">
            {failCount(mostUnstable)} failure{failCount(mostUnstable) !== 1 ? 's' : ''} in window
          </p>
        </div>
      ) : (
        <div className="px-5 pb-4 border-t border-border-subtle pt-3">
          <span className="text-xs text-success">All tests passing</span>
        </div>
      )}

      {/* Classification chips */}
      <div className="px-5 pb-4 flex gap-2 flex-wrap">
        {failing.length > 0 && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-danger/10 border border-danger/20 text-danger">
            {failing.length} failing
          </span>
        )}
        {flaky.length > 0 && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-warning/10 border border-warning/20 text-warning">
            {flaky.length} flaky
          </span>
        )}
        {failing.length === 0 && flaky.length === 0 && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-success/10 border border-success/20 text-success">
            All stable
          </span>
        )}
      </div>
    </article>
  );
}

// ─────────────────────────────────────────────────────────────
// 4. Run history pills
// ─────────────────────────────────────────────────────────────

function RunPill({ status, seq }: { status: string; seq: number }) {
  const cfg =
    status === 'passed'                        ? { bg: 'bg-success', title: `Run #${seq}: passed`  } :
    status === 'failed' || status === 'broken' ? { bg: 'bg-danger',  title: `Run #${seq}: failed`  } :
    status === 'skipped'                       ? { bg: 'bg-border-strong', title: `Run #${seq}: skipped` } :
                                                 { bg: 'bg-surface-raised', title: `Run #${seq}: absent` };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${cfg.bg} flex-shrink-0`}
      title={cfg.title}
    />
  );
}

// ─────────────────────────────────────────────────────────────
// 5. Classification badge
// ─────────────────────────────────────────────────────────────

function ClassBadge({ cls }: { cls: 'stable' | 'flaky' | 'failing' }) {
  if (cls === 'failing') return (
    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-danger/10 border border-danger/20 text-danger">
      Failing
    </span>
  );
  if (cls === 'flaky') return (
    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-warning/10 border border-warning/20 text-warning">
      Flaky
    </span>
  );
  return (
    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-success/10 border border-success/20 text-success">
      Stable
    </span>
  );
}

// ─────────────────────────────────────────────────────────────
// 6. Entity test table — dynamic label list
// ─────────────────────────────────────────────────────────────

type SortKey   = 'failures' | 'name' | 'suite' | 'owner';
type FilterCls = 'all' | 'failing' | 'flaky' | 'stable';

function EntityTestTable({ rows, labels, dimension }: {
  rows:      ApiEntityCompareRow[];
  labels:    string[];
  dimension: string;
}) {
  const [filterCls,   setFilterCls]   = useState<FilterCls>('all');
  const [filterOwner, setFilterOwner] = useState<string>('all');
  const [search,      setSearch]      = useState('');
  const [sortKey,     setSortKey]     = useState<SortKey>('failures');

  const clsCounts = {
    all:     rows.length,
    failing: rows.filter(r => classifyRow(r) === 'failing').length,
    flaky:   rows.filter(r => classifyRow(r) === 'flaky').length,
    stable:  rows.filter(r => classifyRow(r) === 'stable').length,
  };

  const entityLabel = dimension === 'owner' ? 'Owner' : 'Suite';

  const visible = rows
    .filter(r => filterCls === 'all' || classifyRow(r) === filterCls)
    .filter(r => filterOwner === 'all' || r.owner === filterOwner || r.suite_name === filterOwner)
    .filter(r => search === '' || r.display_name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sortKey === 'failures') return failCount(b) - failCount(a);
      if (sortKey === 'suite')    return (a.suite ?? '').localeCompare(b.suite ?? '');
      if (sortKey === 'owner')    return (a.owner ?? a.suite_name ?? '').localeCompare(b.owner ?? b.suite_name ?? '');
      return a.display_name.localeCompare(b.display_name);
    });

  const filterBtns: { key: FilterCls; label: string; count: number }[] = [
    { key: 'all',     label: 'All',     count: clsCounts.all     },
    { key: 'failing', label: 'Failing', count: clsCounts.failing },
    { key: 'flaky',   label: 'Flaky',   count: clsCounts.flaky   },
    { key: 'stable',  label: 'Stable',  count: clsCounts.stable  },
  ];

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
        Test Breakdown
      </h3>

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Status filter pills */}
        <div className="flex items-center gap-1 rounded-full border border-border-default bg-surface-subtle p-1">
          {filterBtns.map(f => (
            <button
              key={f.key}
              onClick={() => setFilterCls(f.key)}
              className={[
                'qara-pill px-3 py-1.5',
                filterCls === f.key ? 'qara-pill-active' : 'border-transparent bg-transparent hover:bg-hover',
              ].join(' ')}
            >
              <span>{f.label}</span>
              <span className="text-[10px] text-muted tabular-nums">({f.count})</span>
            </button>
          ))}
        </div>

        {/* Entity filter */}
        <Dropdown
          value={filterOwner}
          onChange={setFilterOwner}
          triggerClassName="px-3 py-2 text-sm"
          options={[
            { value: 'all', label: `All ${entityLabel}s` },
            ...labels.map(label => ({ value: label, label: label.split(' ')[0] })),
          ]}
        />

        {/* Search */}
        <div className="qara-control relative flex-1 min-w-[180px] max-w-xs">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter tests…"
            className="qara-input pl-8 pr-3 py-2 text-sm"
          />
        </div>

        {/* Sort */}
        <Dropdown
          value={sortKey}
          onChange={value => setSortKey(value as SortKey)}
          triggerClassName="px-3 py-2 text-sm"
          options={[
            { value: 'failures', label: 'Sort: by failures' },
            { value: 'name', label: 'Sort: by name' },
            { value: 'suite', label: 'Sort: by suite' },
            { value: 'owner', label: `Sort: by ${dimension}` },
          ]}
        />

        <span className="text-xs text-muted tabular-nums">{visible.length} of {rows.length} tests</span>
      </div>

      {/* Table */}
      <div className="qara-table-shell">
        <table className="qara-table w-full text-sm">
          <thead className="qara-table-head">
            <tr>
              <th className="text-left w-[38%]">Test</th>
              <th className="text-left">{entityLabel}</th>
              <th className="text-center">Run History</th>
              <th className="text-center">Failures</th>
              <th className="text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="qara-table-cell text-center py-12 text-muted">
                  No tests match the current filter
                </td>
              </tr>
            ) : (
              visible.map(row => {
                const cls    = classifyRow(row);
                const fails  = failCount(row);
                const entity = row.owner ?? row.suite_name ?? '';

                return (
                  <tr key={row.canonical_name} className="qara-table-row">
                    <td className="qara-table-cell">
                      <span className="font-mono text-xs text-primary font-medium leading-relaxed break-all">
                        {row.display_name}
                      </span>
                      {row.suite && (
                        <p className="text-[10px] text-muted mt-0.5">{row.suite}</p>
                      )}
                    </td>
                    <td className="qara-table-cell">
                      <span className="qara-pill text-[11px]">
                        {entity.split(' ')[0]}
                      </span>
                    </td>
                    <td className="qara-table-cell">
                      <div className="flex items-center justify-center gap-1">
                        {row.run_history.map(pt => (
                          <RunPill key={pt.run_sequence} status={pt.status} seq={pt.run_sequence} />
                        ))}
                      </div>
                    </td>
                    <td className="qara-table-cell text-center">
                      <span className={`text-sm font-semibold tabular-nums ${fails > 0 ? 'text-danger' : 'text-muted'}`}>
                        {fails}
                      </span>
                    </td>
                    <td className="qara-table-cell text-center">
                      <ClassBadge cls={cls} />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Top-level: EntityComparisonView
// ─────────────────────────────────────────────────────────────

export function EntityComparisonView({ data }: { data: ApiEntityCompareResult }) {
  const rowsA = data.rows.filter(r => (r.owner ?? r.suite_name) === data.label_a);
  const rowsB = data.rows.filter(r => (r.owner ?? r.suite_name) === data.label_b);
  const rowsC = data.label_c
    ? data.rows.filter(r => (r.owner ?? r.suite_name) === data.label_c)
    : [];

  const entityCount = data.metrics_c ? 3 : 2;
  const cardGrid    = entityCount === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2';

  const labels = [
    data.label_a,
    data.label_b,
    ...(data.label_c ? [data.label_c] : []),
  ];

  return (
    <div className="space-y-6">
      <InsightBanner data={data} />
      <MetricStrip data={data} />
      <div className={`grid grid-cols-1 gap-4 ${cardGrid}`}>
        <EntityCard metrics={data.metrics_a} rows={rowsA} />
        <EntityCard metrics={data.metrics_b} rows={rowsB} />
        {data.metrics_c && <EntityCard metrics={data.metrics_c} rows={rowsC} />}
      </div>
      <EntityTestTable
        rows={data.rows}
        labels={labels}
        dimension={data.dimension}
      />
    </div>
  );
}
