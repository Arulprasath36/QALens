import { useState, useEffect, useMemo } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
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
  CRITICAL: { label: 'Critical', text: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30',    stroke: '#f87171' },
  HIGH:     { label: 'High',     text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30', stroke: '#fb923c' },
  MEDIUM:   { label: 'Medium',   text: 'text-amber-400',  bg: 'bg-amber-500/10',  border: 'border-amber-500/30',  stroke: '#fbbf24' },
  LOW:      { label: 'Low',      text: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/30',  stroke: '#4ade80' },
} as const;

const SIGNAL_CONFIG: Record<string, { label: string; tooltip: string; bg: string }> = {
  volatility:     { label: 'Volatile',   tooltip: 'Frequently switches between pass and fail.',       bg: 'bg-orange-500/20 text-orange-300' },
  failure_burden: { label: 'Failing',    tooltip: 'High all-time failure rate.',                      bg: 'bg-red-500/20 text-red-300' },
  recent_decline: { label: 'Declining',  tooltip: 'Recent runs have higher failure rate than average.', bg: 'bg-orange-500/20 text-orange-300' },
  fail_streak:    { label: 'Fail Streak',tooltip: 'Currently on consecutive failing runs.',           bg: 'bg-red-500/20 text-red-300' },
  duration_spike: { label: 'Slowing',    tooltip: 'Test is steadily getting slower.',                 bg: 'bg-zinc-500/20 text-zinc-400' },
};

// ─────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────

function RiskRing({ pct, tier }: { pct: number; tier: keyof typeof TIER_CONFIG }) {
  const r    = 13;
  const circ = 2 * Math.PI * r;
  const fill = Math.min((pct / 100) * circ, circ);
  const cfg  = TIER_CONFIG[tier] ?? TIER_CONFIG.LOW;

  return (
    <svg width="38" height="38" viewBox="0 0 38 38" aria-label={`${pct}% risk`}>
      {/* Track */}
      <circle cx="19" cy="19" r={r} fill="none" stroke="#3f3f46" strokeWidth="4" />
      {/* Progress */}
      <circle
        cx="19" cy="19" r={r}
        fill="none"
        stroke={cfg.stroke}
        strokeWidth="4"
        strokeDasharray={`${fill} ${circ}`}
        strokeLinecap="round"
        transform="rotate(-90 19 19)"
      />
      {/* Label */}
      <text x="19" y="23" textAnchor="middle" fill={cfg.stroke}
            fontSize="8" fontWeight="bold" fontFamily="monospace">
        {pct}%
      </text>
    </svg>
  );
}

function TierBadge({ tier }: { tier: keyof typeof TIER_CONFIG }) {
  const cfg = TIER_CONFIG[tier] ?? TIER_CONFIG.LOW;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full
                      text-xs font-semibold border ${cfg.text} ${cfg.bg} ${cfg.border}`}>
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
          <span key={key}
                title={cfg.tooltip}
                className={`px-2 py-0.5 rounded-full text-xs font-medium cursor-default ${cfg.bg}`}>
            {cfg.label}
          </span>
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
          <div key={tier} className={`qara-stat-card ${cfg.border}`}>
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

  return (
    <>
      <tr
        className="qara-table-row cursor-pointer"
        onClick={() => setExpanded(o => !o)}
      >
        {/* Test name */}
        <td className="qara-table-cell">
          <div className="type-td-primary truncate max-w-[260px]"
               title={entry.display_name}>
            {entry.display_name}
          </div>
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
        <tr className="qara-table-row" style={{ background: 'var(--bg-subtle)' }}>
          <td colSpan={8} className="px-6 py-5">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <div>
                <span className="text-zinc-500">Pass Rate</span>
                <div className="text-zinc-200 font-semibold mt-0.5">
                  {(entry.pass_rate * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <span className="text-zinc-500">Flip Score</span>
                <div className="text-zinc-200 font-semibold mt-0.5">
                  {(entry.flip_score * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <span className="text-zinc-500">Current Streak</span>
                <div className={`font-semibold mt-0.5 ${
                  entry.current_streak < 0 ? 'text-red-400' :
                  entry.current_streak > 0 ? 'text-green-400' : 'text-zinc-400'
                }`}>
                  {entry.current_streak < 0
                    ? `${Math.abs(entry.current_streak)} fails`
                    : entry.current_streak > 0
                    ? `${entry.current_streak} passes`
                    : '—'}
                </div>
              </div>
              <div>
                <span className="text-zinc-500">Suite</span>
                <div className="text-zinc-200 font-semibold mt-0.5 truncate">{entry.suite || '—'}</div>
              </div>
            </div>

            {/* All signals */}
            <div className="mt-3">
              <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                Risk Signals
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(entry.signals).map(([key, val]) => {
                  const cfg  = SIGNAL_CONFIG[key];
                  const pct  = Math.round(val * 100);
                  if (!cfg) return null;
                  return (
                    <div key={key}
                         title={cfg.tooltip}
                         className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs
                                     cursor-default ${pct > 15 ? cfg.bg : 'bg-zinc-800/60 text-zinc-600'}`}>
                      <span className="font-medium">{cfg.label}</span>
                      <span className="tabular-nums">{pct}%</span>
                    </div>
                  );
                })}
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
        description="Rank tests by failure risk using volatility, burden, streak, and slowdown signals."
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
                        Risk
                      </th>
                      <th className="text-left">
                        Tier
                      </th>
                      <th className="text-left">
                        Signals
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
