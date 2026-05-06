import { useState, useEffect, useMemo, useRef, Fragment } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
import { Tooltip } from '../components/Tooltip';
import { useProject } from '../hooks/useProject';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

type Classification = 'FLAKY' | 'CONSISTENTLY_BROKEN' | 'STABLE' | 'CONSISTENT' | 'INSUFFICIENT_DATA';

interface ApiStabilityEntry {
  canonical_name:    string;
  display_name:      string;
  project:           string | null;
  run_count:         number;
  pass_count:        number;
  fail_count:        number;
  skip_count:        number;
  pass_rate:         number;
  flip_score:        number;
  classification:    Classification;
  history:           string[];
  last_passed_seq:   number | null;
  last_failed_seq:   number | null;
  current_streak:    number;
  owner:             string;
  fingerprints:      string[];
  sparkline:         string;
  flakiness_score:   number;
  suite:             string;
}

interface ApiTrendEntry {
  canonical_name: string;
  direction:      'improving' | 'declining' | 'stable';
  delta_pct:      number;
  confidence:     'high' | 'medium' | 'low';
}

interface BugLink {
  id:      number;
  bug_url: string;
  label:   string;
}

interface ApiFailureGroup {
  fingerprint:              string;
  occurrence_count:         number;
  affected_tests:           number;
  affected_runs:            number;
  error_type:               string | null;
  message:                  string;
  first_seen_seq:           number | null;
  last_seen_seq:            number | null;
  affected_canonical_names: string[];
  bug_links:                BugLink[];
  category:                 string;
}

const STABLE_PASS_THRESHOLD = 0.90;
const STABLE_FLIP_THRESHOLD = 0.10;

// ─────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────

const RUNS_WINDOW_OPTIONS = [5, 10, 20, 30, 50];

const CLASS_CONFIG: Record<Classification, { label: string; text: string; bg: string; border: string }> = {
  FLAKY:                { label: 'Flaky',        text: 'text-amber-400',  bg: 'bg-amber-500/10',  border: 'border-amber-500/30'  },
  CONSISTENTLY_BROKEN:  { label: 'Broken',       text: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30'    },
  STABLE:               { label: 'Stable',       text: 'text-green-700',  bg: 'bg-green-100',     border: 'border-green-400'     },
  CONSISTENT:           { label: 'Consistent',   text: 'text-green-600',  bg: 'bg-green-50',      border: 'border-green-300'     },
  INSUFFICIENT_DATA:    { label: 'Insufficient', text: 'text-zinc-400',   bg: 'bg-zinc-500/10',   border: 'border-zinc-700'      },
};

const CLASS_TOOLTIP: Record<Classification, string> = {
  FLAKY: 'Flaky means the test is changing state often across the selected runs.',
  CONSISTENTLY_BROKEN: 'Broken means the test is failing most of the time across the selected runs.',
  STABLE: 'Stable means the test has a high pass rate and low recent flip activity across the selected runs.',
  CONSISTENT: 'Consistent means the test has low recent flip activity in the selected runs, but it is not yet reliable enough to be considered truly stable.',
  INSUFFICIENT_DATA: 'Insufficient means there are not enough runs in the selected window to classify this test confidently.',
};

const TREND_CONFIG = {
  improving: { icon: '↑', text: 'text-green-400', label: 'Improving' },
  declining:  { icon: '↓', text: 'text-red-400',   label: 'Declining' },
  stable:     { icon: '→', text: 'text-zinc-500',  label: 'Stable'    },
};

function normalizeClassification(entry: ApiStabilityEntry): ApiStabilityEntry {
  if (
    entry.classification === 'STABLE'
    && (entry.pass_rate < STABLE_PASS_THRESHOLD || entry.flip_score > STABLE_FLIP_THRESHOLD)
  ) {
    return { ...entry, classification: 'CONSISTENT' };
  }
  return entry;
}

// ─────────────────────────────────────────────────────────────
// Helpers / small components
// ─────────────────────────────────────────────────────────────

function ClassBadge({ cls }: { cls: Classification }) {
  const cfg = CLASS_CONFIG[cls] ?? CLASS_CONFIG.INSUFFICIENT_DATA;
  return (
    <Tooltip content={CLASS_TOOLTIP[cls] ?? CLASS_TOOLTIP.INSUFFICIENT_DATA} className="inline-flex">
      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs
                        font-semibold border ${cfg.text} ${cfg.bg} ${cfg.border}`}>
        {cfg.label}
      </span>
    </Tooltip>
  );
}

function PassRateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-zinc-400 w-8 text-right">{pct}%</span>
    </div>
  );
}

function SparklineHeatmap({ sparkline, runsWindow }: { sparkline: string; runsWindow: number }) {
  const COLS = 7;
  const raw  = [...sparkline].slice(-runsWindow);

  const [tooltip, setTooltip] = useState<{ label: string; x: number; y: number } | null>(null);

  // Always size the grid to ceil(runsWindow / COLS) * COLS so every test
  // shows the same number of slots. Missing runs render as invisible cells.
  const gridSize = Math.ceil(runsWindow / COLS) * COLS;
  const leading  = gridSize - raw.length;
  const padded: (string | null)[] = [...Array(leading).fill(null), ...raw];

  const rows: (string | null)[][] = [];
  for (let i = 0; i < padded.length; i += COLS) {
    rows.push(padded.slice(i, i + COLS));
  }

  function cellStyle(cell: string | null, rowIdx: number, totalRows: number): string {
    if (cell === null) return 'opacity-0';
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

  return (
    <div className="inline-flex flex-col gap-[3px]">
      {rows.map((row, ri) => (
        <div key={ri} className="flex gap-[3px]">
          {row.map((cell, ci) => {
            if (cell === null) {
              return <span key={ci} className="inline-block w-[10px] h-[10px] rounded-[2px] opacity-0" />;
            }
            const posInRaw = ri * COLS + ci - leading;
            const label = cell === '\u2713'
              ? `Passed. Run #${posInRaw + 1}`
              : `Failed. Run #${posInRaw + 1}`;
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

function TrendCell({ entry }: { entry: ApiTrendEntry | undefined }) {
  if (!entry || entry.direction === 'stable') return <span className="text-zinc-600">—</span>;
  const cfg = TREND_CONFIG[entry.direction];
  return (
    <Tooltip content={cfg.label} className="inline-flex">
      <span className={`text-xs font-semibold ${cfg.text}`}>
        {cfg.icon} {Math.abs(entry.delta_pct).toFixed(0)}%
      </span>
    </Tooltip>
  );
}

// ─────────────────────────────────────────────────────────────
// Streak alert
// ─────────────────────────────────────────────────────────────

function StreakAlert({ data, runsWindow }: { data: ApiStabilityEntry[]; runsWindow: number }) {
  const [open, setOpen] = useState(false);
  const streakers = data
    .filter(r => r.current_streak <= -2)
    .sort((a, b) => a.current_streak - b.current_streak);

  if (streakers.length === 0) return null;

  const longestStreak = Math.abs(streakers[0]?.current_streak ?? 0);
  const avgPassRate = Math.round(
    streakers.reduce((sum, row) => sum + row.pass_rate, 0) / Math.max(streakers.length, 1) * 100,
  );
  const topOwner = (() => {
    const counts = new Map<string, number>();
    for (const row of streakers) {
      const owner = row.owner || 'Unassigned';
      counts.set(owner, (counts.get(owner) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0] ?? null;
  })();

  return (
    <div className="rounded-xl border border-red-500/30 bg-red-500/5">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start justify-between gap-4 px-4 py-3 text-left"
      >
        <div className="min-w-0">
          <p className="text-sm font-semibold text-red-400">
            🔴 {streakers.length} test{streakers.length !== 1 ? 's are' : ' is'} on an active fail streak
          </p>
          <p className="mt-1 text-sm text-zinc-300">
            Consecutive failures are persisting across recent runs, led by a {longestStreak}-run streak
            {topOwner ? ` and concentrated around ${topOwner[0]}.` : '.'}
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-zinc-400">
            <span className="rounded-full border border-red-500/20 bg-zinc-900/80 px-2.5 py-1">
              Longest streak: <span className="font-semibold text-red-400">{longestStreak} runs</span>
            </span>
            <span className="rounded-full border border-zinc-700 bg-zinc-900/80 px-2.5 py-1">
              Avg pass rate: <span className="font-semibold text-zinc-200">{avgPassRate}%</span>
            </span>
          </div>
        </div>
        <svg className={`w-4 h-4 text-zinc-500 transition-transform ${open ? 'rotate-90' : ''}`}
             viewBox="0 0 16 16" fill="none">
          <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
      {open && (
        <div className="px-4 pb-4 grid grid-cols-1 xl:grid-cols-2 gap-3">
          {streakers.map(r => (
            <div key={r.canonical_name}
                 className="rounded-xl border border-zinc-800 bg-zinc-900 px-3.5 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <Tooltip content={r.display_name} className="block min-w-0">
                      <span className="block truncate text-sm font-medium text-zinc-100">
                        {r.display_name}
                      </span>
                    </Tooltip>
                    <span className="shrink-0 rounded-full border border-red-500/25 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold text-red-400">
                      {Math.abs(r.current_streak)} straight fails
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-400">
                    {(r.owner || 'Unassigned')} · {(r.suite || 'Unknown suite')}
                  </p>
                </div>
                <ClassBadge cls={r.classification} />
              </div>

              <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                <span className="text-zinc-400">
                  Pass rate: <span className="font-semibold text-zinc-200">{Math.round(r.pass_rate * 100)}%</span>
                </span>
                <span className="text-zinc-400">
                  Fails: <span className="font-semibold text-red-400">{r.fail_count}</span>
                </span>
                <span className="text-zinc-400">
                  Last failed: <span className="font-semibold text-zinc-200">{r.last_failed_seq != null ? `Run #${r.last_failed_seq}` : 'Unknown'}</span>
                </span>
              </div>

              <div className="mt-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
                    Recent history
                  </p>
                  <div className="mt-2">
                    <SparklineHeatmap sparkline={r.sparkline} runsWindow={runsWindow} />
                  </div>
                </div>
                <div className="text-right text-[11px] text-zinc-500">
                  <p>{Math.min(runsWindow, r.run_count)} of {r.run_count} runs shown</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Stability table
// ─────────────────────────────────────────────────────────────

function StabilityTable({
  entries,
  trendMap,
  runsWindow,
  nested = false,
}: {
  entries:    ApiStabilityEntry[];
  trendMap:   Map<string, ApiTrendEntry>;
  runsWindow: number;
  nested?:    boolean;
}) {
  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center py-16 text-center gap-2">
        <p className="text-zinc-400">No tests match the current filters</p>
      </div>
    );
  }

  const inner = (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/80">
              {(['Test', 'Owner', 'Classification', 'Pass Rate', 'Flip', 'Trend', 'History', 'Runs'] as const).map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold
                                       text-zinc-500 uppercase tracking-wider whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-zinc-950">
            {entries.map(row => (
              <tr key={row.canonical_name}
                  className="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td className="px-4 py-3">
                  <Tooltip content={row.display_name} className="block max-w-[240px]">
                    <div className="text-sm font-medium text-zinc-200 truncate">
                      {row.display_name}
                    </div>
                  </Tooltip>
                  {row.suite && (
                    <div className="text-xs text-zinc-600 truncate">{row.suite}</div>
                  )}
                </td>
                <td className="px-4 py-3 text-sm text-zinc-400 whitespace-nowrap">
                  {row.owner || '—'}
                </td>
                <td className="px-4 py-3">
                  <ClassBadge cls={row.classification} />
                </td>
                <td className="px-4 py-3">
                  <PassRateBar rate={row.pass_rate} />
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-zinc-400">
                  {(row.flip_score * 100).toFixed(0)}%
                </td>
                <td className="px-4 py-3">
                  <TrendCell entry={trendMap.get(row.canonical_name)} />
                </td>
                <td className="px-4 py-3">
                  <SparklineHeatmap sparkline={row.sparkline} runsWindow={runsWindow} />
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-zinc-500 text-right">
                  {row.run_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
  );

  if (nested) return inner;

  return (
    <div className="rounded-xl border border-zinc-800 overflow-hidden">
      {inner}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Failure groups
// ─────────────────────────────────────────────────────────────

function BugLinksList({
  fingerprint,
  links,
  onUpdate,
}: {
  fingerprint: string;
  links:       BugLink[];
  onUpdate:    (links: BugLink[]) => void;
}) {
  const [adding, setAdding]   = useState(false);
  const [url,    setUrl]      = useState('');
  const [saving, setSaving]   = useState(false);
  const inputRef              = useRef<HTMLInputElement>(null);

  async function handleAdd() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/failure-groups/${fingerprint}/bug-links`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const newLink = await res.json() as BugLink;
      onUpdate([...links, newLink]);
      setUrl('');
      setAdding(false);
    } catch (e) {
      console.error('Failed to add bug link:', e);
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(id: number) {
    try {
      const res = await fetch(`/api/failure-groups/${fingerprint}/bug-links/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      onUpdate(links.filter(l => l.id !== id));
    } catch (e) {
      console.error('Failed to remove bug link:', e);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {links.map(link => (
        <span key={link.id}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                         text-xs bg-indigo-500/10 border border-indigo-500/30">
          <a href={link.bug_url} target="_blank" rel="noopener noreferrer"
             className="text-indigo-400 hover:text-indigo-300"
             onClick={e => e.stopPropagation()}>
            {link.label || link.bug_url}
          </a>
          <button
            onClick={e => { e.stopPropagation(); handleRemove(link.id); }}
            className="text-zinc-500 hover:text-zinc-300 ml-0.5"
            aria-label="Remove bug link"
          >
            ×
          </button>
        </span>
      ))}

      {adding ? (
        <div className="flex items-center gap-1">
          <input
            ref={inputRef}
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') setAdding(false); }}
            placeholder="Paste bug URL…"
            autoFocus
            className="px-2 py-0.5 text-xs bg-zinc-900 border border-zinc-600 rounded
                       text-zinc-200 focus:outline-none focus:border-indigo-500 w-48"
          />
          <button
            onClick={handleAdd}
            disabled={saving || !url.trim()}
            className="px-2 py-0.5 text-xs text-indigo-400 border border-indigo-500/40
                       rounded hover:bg-indigo-500/10 disabled:opacity-40"
          >
            {saving ? '…' : 'Add'}
          </button>
          <button
            onClick={() => setAdding(false)}
            className="text-xs text-zinc-500 hover:text-zinc-300"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={e => { e.stopPropagation(); setAdding(true); }}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs
                     text-zinc-500 border border-zinc-700 hover:border-zinc-500
                     hover:text-zinc-300 transition-colors"
        >
          + Link
        </button>
      )}
    </div>
  );
}

function FailureGroupCard({ group }: { group: ApiFailureGroup }) {
  const [open,  setOpen]  = useState(false);
  const [links, setLinks] = useState<BugLink[]>(group.bug_links);

  return (
    <div className={`rounded-xl border transition-colors bg-zinc-900
                     ${open ? 'border-zinc-700' : 'border-zinc-800'}`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-start gap-3 min-w-0">
          {group.error_type && (
            <span className="shrink-0 px-2 py-0.5 rounded-full text-xs font-semibold
                             bg-zinc-800 border border-zinc-700 text-zinc-400">
              {group.error_type}
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm text-zinc-200 line-clamp-2 text-left">{group.message}</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              {group.occurrence_count} occurrence{group.occurrence_count !== 1 ? 's' : ''} ·{' '}
              {group.affected_tests} test{group.affected_tests !== 1 ? 's' : ''} ·{' '}
              {group.affected_runs} run{group.affected_runs !== 1 ? 's' : ''}
              {group.category && group.category !== 'Unknown' ? ` · ${group.category}` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {links.length > 0 && (
            <span className="text-xs text-indigo-400">{links.length} link{links.length !== 1 ? 's' : ''}</span>
          )}
          <svg className={`w-4 h-4 text-zinc-500 transition-transform ${open ? 'rotate-90' : ''}`}
               viewBox="0 0 16 16" fill="none">
            <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-zinc-800 pt-3 space-y-3">
          {/* Fingerprint */}
          <div className="flex items-center gap-2 text-xs text-zinc-600">
            <span className="font-mono">{group.fingerprint.slice(0, 12)}</span>
            {group.last_seen_seq != null && (
              <span>· Last seen run #{group.last_seen_seq}</span>
            )}
          </div>

          {/* Affected tests */}
          <div>
            <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1.5">
              Affected Tests
            </p>
            <div className="flex flex-wrap gap-1.5">
              {group.affected_canonical_names.map(name => (
                <span key={name}
                      className="px-2 py-0.5 rounded text-xs font-mono
                                 bg-zinc-800 border border-zinc-700 text-zinc-400">
                  {name}
                </span>
              ))}
            </div>
          </div>

          {/* Bug links */}
          <div>
            <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1.5">
              Bug Links
            </p>
            <BugLinksList
              fingerprint={group.fingerprint}
              links={links}
              onUpdate={setLinks}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Owner summary
// ─────────────────────────────────────────────────────────────

function OwnerSection({
  owner,
  entries,
  trendMap,
  runsWindow,
}: {
  owner:      string;
  entries:    ApiStabilityEntry[];
  trendMap:   Map<string, ApiTrendEntry>;
  runsWindow: number;
}) {
  const [open, setOpen] = useState(false);
  const flaky   = entries.filter(e => e.classification === 'FLAKY').length;
  const broken  = entries.filter(e => e.classification === 'CONSISTENTLY_BROKEN').length;
  const stable  = entries.filter(e => e.classification === 'STABLE').length;
  const consistent = entries.filter(e => e.classification === 'CONSISTENT').length;
  const avgPass = entries.reduce((s, e) => s + e.pass_rate, 0) / entries.length;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-zinc-200">{owner}</span>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-zinc-500">{entries.length} tests</span>
              {stable  > 0 && <span className="text-green-400">{stable} stable</span>}
              {consistent > 0 && <span className="text-emerald-300">{consistent} consistent</span>}
              {flaky   > 0 && <span className="text-amber-400">{flaky} flaky</span>}
              {broken  > 0 && <span className="text-red-400">{broken} broken</span>}
            </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-zinc-500">{(avgPass * 100).toFixed(0)}% avg pass</span>
          <svg className={`w-4 h-4 text-zinc-500 transition-transform ${open ? 'rotate-90' : ''}`}
               viewBox="0 0 16 16" fill="none">
            <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </button>
      {open && (
        <div className="border-t border-zinc-800 overflow-x-auto">
          <StabilityTable nested entries={entries} trendMap={trendMap} runsWindow={runsWindow} />
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Stat cards
// ─────────────────────────────────────────────────────────────

function AnalysisStatCards({
  data,
  activeFilter,
  onSelectFilter,
  onOpenFilteredResults,
}: {
  data: ApiStabilityEntry[];
  activeFilter: Classification | '';
  onSelectFilter: (cls: Classification) => void;
  onOpenFilteredResults: () => void;
}) {
  const counts: Record<Classification, number> = {
    FLAKY: 0, CONSISTENTLY_BROKEN: 0, STABLE: 0, CONSISTENT: 0, INSUFFICIENT_DATA: 0,
  };
  for (const d of data) counts[d.classification] = (counts[d.classification] ?? 0) + 1;

  const cards: { key: Classification; label: string; valueClass: string }[] = [
    { key: 'FLAKY',               label: CLASS_CONFIG.FLAKY.label,               valueClass: 'text-amber-400' },
    { key: 'CONSISTENTLY_BROKEN', label: CLASS_CONFIG.CONSISTENTLY_BROKEN.label, valueClass: 'text-red-400' },
    { key: 'STABLE',              label: CLASS_CONFIG.STABLE.label,              valueClass: 'text-green-400' },
    { key: 'CONSISTENT',          label: CLASS_CONFIG.CONSISTENT.label,          valueClass: 'text-emerald-300' },
    { key: 'INSUFFICIENT_DATA',   label: CLASS_CONFIG.INSUFFICIENT_DATA.label,   valueClass: 'text-zinc-400' },
  ];

  return (
    <div className="qara-stat-grid">
      {cards.map(c => (
        <button
          key={c.key}
          type="button"
          onClick={() => onSelectFilter(c.key)}
          className={[
            `qara-stat-card ${CLASS_CONFIG[c.key].border}`,
            'text-left transition-colors hover:bg-surface-subtle/70',
            activeFilter === c.key ? 'ring-1 ring-border-strong' : '',
          ].join(' ')}
        >
          <Tooltip content={CLASS_TOOLTIP[c.key]} className="inline-flex self-start">
            <span className="type-metric-label">{c.label}</span>
          </Tooltip>
          <span className={`type-metric-value ${c.valueClass}`}>
            {counts[c.key]}
          </span>
          {activeFilter === c.key && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onOpenFilteredResults();
              }}
              className="mt-2 inline-flex text-xs font-medium text-info hover:text-primary"
            >
              Show {counts[c.key]} {c.label.toLowerCase()} test{counts[c.key] !== 1 ? 's' : ''} below
            </button>
          )}
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// AnalysisPanel
// ─────────────────────────────────────────────────────────────

export function AnalysisPanel() {
  const { currentProject } = useProject();
  const stabilityFiltersRef = useRef<HTMLDivElement>(null);

  const [stability,    setStability]    = useState<ApiStabilityEntry[]>([]);
  const [trends,       setTrends]       = useState<ApiTrendEntry[]>([]);
  const [groups,       setGroups]       = useState<ApiFailureGroup[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState<string | null>(null);
  const [runsWindow,   setRunsWindow]   = useState(30);
  const [search,       setSearch]       = useState('');
  const [classFilter,  setClassFilter]  = useState<string>('');
  const [ownerFilter,  setOwnerFilter]  = useState<string>('');
  const [activeSection, setActiveSection] = useState<'stability' | 'groups' | 'owners'>('stability');

  // Fetch all analysis data in parallel
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({ min_runs: '2', limit: String(runsWindow) });
    if (currentProject) params.set('project', currentProject);

    const gParams = new URLSearchParams();
    if (currentProject) gParams.set('project', currentProject);

    Promise.all([
      fetch(`/api/stability?${params}`).then(r => r.ok ? r.json() as Promise<ApiStabilityEntry[]> : Promise.reject(`API ${r.status}`)),
      fetch(`/api/stability/trends?${params}`).then(r => r.ok ? r.json() as Promise<ApiTrendEntry[]> : Promise.reject(`API ${r.status}`)),
      fetch(`/api/failure-groups?${gParams}`).then(r => r.ok ? r.json() as Promise<ApiFailureGroup[]> : Promise.reject(`API ${r.status}`)),
    ])
      .then(([stab, tr, grp]) => {
        if (cancelled) return;
        setStability(stab.map(normalizeClassification));
        setTrends(tr);
        setGroups(grp);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [currentProject, runsWindow]);

  // Build trend map for O(1) lookup
  const trendMap = useMemo(
    () => new Map(trends.map(t => [t.canonical_name, t])),
    [trends],
  );

  // Owners for filter dropdown
  const owners = useMemo(
    () => [...new Set(stability.map(s => s.owner).filter(Boolean))].sort(),
    [stability],
  );

  // Filtered stability entries
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return stability.filter(r => {
      if (classFilter && r.classification !== classFilter) return false;
      if (ownerFilter && r.owner !== ownerFilter) return false;
      if (q && !r.display_name.toLowerCase().includes(q) && !r.canonical_name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [stability, classFilter, ownerFilter, search]);

  // Grouped by owner (for Owner Summary section)
  const byOwner = useMemo(() => {
    const map = new Map<string, ApiStabilityEntry[]>();
    for (const e of filtered) {
      const owner = e.owner || '(unassigned)';
      if (!map.has(owner)) map.set(owner, []);
      map.get(owner)!.push(e);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  function selectClassification(cls: Classification) {
    setActiveSection('stability');
    setClassFilter(cls);
  }

  function openFilteredResults() {
    stabilityFiltersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  return (
    <div className="qara-page">

      {/* Page header */}
      <PageHeader
        tier="full"
        kicker="Health Overview"
        title="Analysis"
        description="Review stability classifications, a library of recurring failure signatures, and owner-level health trends."
        icon="📊"
      />

      {/* Loading */}
      {loading && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-12 rounded-xl bg-zinc-800" />)}
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="qara-error-banner">
          <span>⚠️</span>
          <span>Failed to load analysis data: {error}</span>
        </div>
      )}

      {!loading && !error && (
        <Fragment>
          <div className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                Analysis Scope
              </p>
              <p className="mt-1 text-sm text-secondary">
                Stability, active fail streaks, and recent history below are based on the selected run window.
              </p>
            </div>
            <Dropdown
              value={String(runsWindow)}
              onChange={value => setRunsWindow(Number(value))}
              triggerClassName="px-3.5 text-sm"
              options={RUNS_WINDOW_OPTIONS.map(option => ({
                value: String(option),
                label: `Last ${option} runs`,
              }))}
            />
          </div>

          {/* Stat cards */}
          {stability.length > 0 && (
            <AnalysisStatCards
              data={stability}
              activeFilter={activeSection === 'stability' ? (classFilter as Classification | '') : ''}
              onSelectFilter={selectClassification}
              onOpenFilteredResults={openFilteredResults}
            />
          )}

          {/* Streak alert */}
          <StreakAlert data={stability} runsWindow={runsWindow} />

          {/* Analysis controls */}
          <div ref={stabilityFiltersRef} className="rounded-xl border border-border-subtle bg-surface px-4 py-3 space-y-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                  Analyze By
                </p>
                <p className="mt-1 text-sm text-secondary">
                  {activeSection === 'stability'
                    ? 'Test-level stability and trend history across the selected runs.'
                    : activeSection === 'groups'
                      ? 'Recurring failure signatures across recent analysis history.'
                      : 'Ownership-level concentration and health across the selected runs.'}
                </p>
              </div>

              <div className="qara-toolbar-segment self-start">
                {([
                  { id: 'stability', label: 'Tests' },
                  { id: 'owners',   label: 'Owners' },
                  { id: 'groups',   label: `Patterns (${groups.length})` },
                ] as const).map(s => (
                  <button
                    key={s.id}
                    onClick={() => setActiveSection(s.id)}
                    className={[
                      'qara-segment-button',
                      activeSection === s.id
                        ? 'qara-segment-button-active'
                        : '',
                    ].join(' ')}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {(activeSection === 'stability' || activeSection === 'owners') ? (
              <div>
                <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                  {activeSection === 'owners' ? 'Filter owner tests' : 'Filter tests'}
                </p>

                <div className="qara-toolbar border-0 bg-transparent px-0 py-0 shadow-none">
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
                      value={search}
                      onChange={e => setSearch(e.target.value)}
                      className="qara-control qara-input type-input w-full pl-9 pr-3"
                    />
                  </div>

                  {/* Classification filter */}
                  <Dropdown
                    value={classFilter}
                    onChange={setClassFilter}
                    triggerClassName="px-3.5 text-sm"
                    options={[
                      { value: '', label: 'All statuses' },
                      { value: 'FLAKY', label: CLASS_CONFIG.FLAKY.label },
                      { value: 'CONSISTENTLY_BROKEN', label: CLASS_CONFIG.CONSISTENTLY_BROKEN.label },
                      { value: 'STABLE', label: CLASS_CONFIG.STABLE.label },
                      { value: 'CONSISTENT', label: CLASS_CONFIG.CONSISTENT.label },
                      { value: 'INSUFFICIENT_DATA', label: CLASS_CONFIG.INSUFFICIENT_DATA.label },
                    ]}
                  />

                  {/* Owner filter */}
                  {owners.length > 0 && (
                    <Dropdown
                      value={ownerFilter}
                      onChange={setOwnerFilter}
                      triggerClassName="px-3.5 text-sm"
                      options={[
                        { value: '', label: 'All owners' },
                        ...owners.map(owner => ({ value: owner, label: owner })),
                      ]}
                    />
                  )}

                  {(search || classFilter || ownerFilter) && (
                    <button
                      onClick={() => { setSearch(''); setClassFilter(''); setOwnerFilter(''); }}
                      className="qara-chip type-chip"
                    >
                      Clear
                    </button>
                  )}

                  <span className="qara-inline-note">
                    Showing {filtered.length} of {stability.length} test{stability.length !== 1 ? 's' : ''}
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-3">
                <p className="text-sm text-secondary">
                  Browse known recurring signatures and expand a pattern to inspect affected tests and linked bugs.
                </p>
                <span className="qara-inline-note">
                  {groups.length} recurring signature{groups.length !== 1 ? 's' : ''}
                </span>
              </div>
            )}
          </div>

          {/* ── Stability section ─────────────────── */}
          {activeSection === 'stability' && (
            stability.length === 0
              ? (
                <div className="qara-empty-state">
                  <div className="qara-empty-icon">📊</div>
                  <p className="type-empty-title">No stability data yet</p>
                  <p className="type-empty-subtitle max-w-xs">
                    Ingest more runs to generate stability metrics (minimum 2 runs per test).
                  </p>
                </div>
              )
              : <StabilityTable entries={filtered} trendMap={trendMap} runsWindow={runsWindow} />
          )}

          {/* ── Pattern library section ───────────── */}
          {activeSection === 'groups' && (
            <div className="space-y-3">
              {groups.length === 0 ? (
                <div className="qara-empty-state">
                  <div className="qara-empty-icon">✅</div>
                  <p className="type-empty-title">No recurring signatures found</p>
                  <p className="type-empty-subtitle max-w-sm">
                    Known failure patterns will appear here once repeated signatures emerge across analyzed runs.
                  </p>
                </div>
              ) : (
                groups.map(g => <FailureGroupCard key={g.fingerprint} group={g} />)
              )}
            </div>
          )}

          {/* ── Owner summary section ─────────────── */}
          {activeSection === 'owners' && (
            <div className="space-y-3">
              {byOwner.length === 0 ? (
                <div className="qara-empty-state">
                  <p className="type-empty-title">No tests found</p>
                </div>
              ) : (
                byOwner.map(([owner, entries]) => (
                  <OwnerSection
                    key={owner}
                    owner={owner}
                    entries={entries}
                    trendMap={trendMap}
                    runsWindow={runsWindow}
                  />
                ))
              )}
            </div>
          )}

        </Fragment>
      )}

    </div>
  );
}
