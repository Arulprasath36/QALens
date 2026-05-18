import { useState, useEffect, useMemo } from 'react';
import { useProject } from '../hooks/useProject';
import { Dropdown } from '../components/Dropdown';
import { Tooltip } from '../components/Tooltip';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

type Classification = 'FLAKY' | 'CONSISTENTLY_BROKEN' | 'STABLE' | 'CONSISTENT' | 'INSUFFICIENT_DATA';

interface ApiRun {
  run_id:         string;
  run_sequence:   number;
  started_at:     number | null;
  total_tests:    number;
  passed_count:   number;
  failed_count:   number;
  skipped_count:  number;
  total_ms:       number | null;
  branch:         string | null;
  build_number:   string | null;
  project:        string | null;
}

interface ApiStabilityEntry {
  canonical_name:  string;
  display_name:    string;
  project:         string | null;
  run_count:       number;
  pass_count:      number;
  fail_count:      number;
  skip_count:      number;
  pass_rate:       number;
  flip_score:      number;
  classification:  Classification;
  current_streak:  number;
  owner:           string;
  fingerprints:    string[];
  sparkline:       string;
  suite:           string;
}

interface ApiTrendEntry {
  canonical_name: string;
  direction:      'improving' | 'declining' | 'stable';
  delta_pct:      number;
  confidence:     'high' | 'medium' | 'low';
}

interface BugLink { id: number; bug_url: string; label: string; }

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

interface ApiRiskEntry {
  canonical_name: string;
  display_name:   string;
  risk_pct:       number;
  tier:           string;
  owner:          string;
  pass_rate:      number;
  sparkline:      string;
  signals:        { duration_spike?: number; volatility?: number; failure_burden?: number; recent_decline?: number };
}

interface ApiOwnerStatEntry {
  owner:              string;
  total_tests:        number;
  failing_tests:      number;
  total_executions:   number;
  failed_executions:  number;
  failure_rate:       number;
  run_count:          number;
}

interface ApiDecisionSummary {
  scope:               { project: string | null; run_id: string | null; run_sequence: number | null; window: number; has_previous_run: boolean };
  executive_summary:   string[];
  trend_intelligence:  { metric: string; direction: string; delta: number; detail: string }[];
  fix_first?:          { rank: number; severity: string; title: string; reason: string }[];
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function pct(v: number) { return `${Math.round(v * 100)}%`; }
function fmt(n: number) { return n.toLocaleString(); }
function passRateOf(run: ApiRun) { return run.total_tests > 0 ? run.passed_count / run.total_tests : 0; }

function initialsOf(name: string) {
  const parts = name.trim().split(/\s+/);
  return parts.length >= 2 ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase() : (parts[0][0] ?? '?').toUpperCase();
}

function toneFor(rate: number) {
  if (rate >= 0.8) return 'text-success';
  if (rate >= 0.5) return 'text-warning';
  return 'text-danger';
}

function bgToneFor(rate: number) {
  if (rate >= 0.8) return 'bg-success/10 border-success/20';
  if (rate >= 0.5) return 'bg-warning/10 border-warning/20';
  return 'bg-danger/10 border-danger/20';
}

function clampPct(value: number) {
  return Math.max(0, Math.min(100, value));
}

// ─────────────────────────────────────────────────────────────
// Small components
// ─────────────────────────────────────────────────────────────

function SectionCard({ children, source }: { children: React.ReactNode; source?: string }) {
  return (
    <div className="qalens-card p-5">
      {children}
      {source && (
        <div className="mt-4 pt-3 border-t border-border-subtle flex items-center gap-1.5">
          <span className="text-[9px] font-semibold uppercase tracking-widest text-muted">Source</span>
          <code className="text-[10px] text-muted font-mono">{source}</code>
        </div>
      )}
    </div>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <p className="type-eyebrow mb-1.5">{children}</p>;
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-primary mb-0">{children}</h3>;
}

function KpiSparkline({ series, color }: { series: number[]; color: string }) {
  if (series.length < 2) return null;
  const w = 120, h = 52, p = 4;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = Math.max(max - min, 0.001);
  const pts = series.map((v, i) => ({
    x: p + (i * (w - 2 * p)) / (series.length - 1),
    y: h - p - ((v - min) / range) * (h - 2 * p),
  }));
  const path = pts.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)},${pt.y.toFixed(1)}`).join(' ');
  const area = `${path} L ${pts[pts.length-1].x},${h-p} L ${pts[0].x},${h-p} Z`;
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} className="shrink-0">
      <path d={area} fill={color} opacity="0.12" />
      <path d={path} fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last.x} cy={last.y} r="3" fill={color} stroke="white" strokeWidth="1.5" />
    </svg>
  );
}

function SparkFromString({ sparkline, color }: { sparkline: string; color: string }) {
  const vals = [...sparkline].map(c => c === '✓' ? 1 : 0);
  if (vals.length < 2) return null;
  const w = 64, h = 20, p = 2;
  const pts = vals.map((v, i) => ({
    x: p + (i * (w - 2 * p)) / (vals.length - 1),
    y: v === 1 ? p : h - p,
  }));
  const path = pts.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)},${pt.y.toFixed(1)}`).join(' ');
  return (
    <svg width={w} height={h}>
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.7" />
    </svg>
  );
}

function InitialsAvatar({ name }: { name: string }) {
  return (
    <div className="w-7 h-7 rounded-full bg-info/15 flex items-center justify-center shrink-0">
      <span className="text-[10px] font-bold text-info">{initialsOf(name)}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// KPI Tile
// ─────────────────────────────────────────────────────────────

function KpiTile({ label, value, delta, deltaSuffix = '', inverted = false, series, source }: {
  label: string; value: string; delta: number; deltaSuffix?: string;
  inverted?: boolean; series: number[]; source: string;
}) {
  const isWorse  = inverted ? delta > 0 : delta < 0;
  const isBetter = inverted ? delta < 0 : delta > 0;
  const color = delta === 0 ? 'var(--text-muted)' : isWorse ? 'var(--color-danger)' : 'var(--color-success)';
  const arrow = delta === 0 ? '→' : delta > 0 ? '↑' : '↓';
  const sparkColor = isWorse ? 'var(--color-danger)' : isBetter ? 'var(--color-success)' : 'var(--color-info)';
  const deltaStr = `${delta > 0 ? '+' : ''}${delta}${deltaSuffix}`;

  return (
    <div className="qalens-card p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Eyebrow>{label}</Eyebrow>
          <div className="text-3xl font-bold tracking-tight text-primary type-nums leading-none mt-1">{value}</div>
          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
            <span className="text-xs font-semibold type-nums" style={{ color }}>{arrow} {deltaStr}</span>
            <span className="text-xs text-muted">vs window start</span>
          </div>
        </div>
        <KpiSparkline series={series} color={sparkColor} />
      </div>
      <div className="pt-2 border-t border-border-subtle flex items-center gap-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-muted">Source</span>
        <code className="text-[10px] text-muted font-mono">{source}</code>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Pass Rate Journey (SVG chart)
// ─────────────────────────────────────────────────────────────

function PassRateJourney({ runs, failureGroups }: { runs: ApiRun[]; failureGroups: ApiFailureGroup[] }) {
  const [hovered, setHovered] = useState<{
    x: number;
    y: number;
    run: ApiRun;
    passRate: number;
    clusters: ApiFailureGroup[];
  } | null>(null);
  const sorted = [...runs].sort((a, b) => a.run_sequence - b.run_sequence);
  if (sorted.length < 2) return <p className="text-sm text-muted py-4">Not enough runs to chart.</p>;

  const W = 860, H = 200, pL = 36, pR = 12, pT = 14, pB = 28;
  const series = sorted.map(r => r.total_tests > 0 ? r.passed_count / r.total_tests : 0);
  const minY = Math.max(0, Math.floor(Math.min(...series) * 10) / 10 - 0.05);
  const maxY = 1;
  const xAt = (i: number) => pL + (i * (W - pL - pR)) / (sorted.length - 1);
  const yAt = (v: number) => pT + ((maxY - v) / (maxY - minY)) * (H - pT - pB);
  const pts = series.map((v, i) => ({ x: xAt(i), y: yAt(v), v, run: sorted[i] }));
  const linePath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L ${pts[pts.length-1].x},${H - pB} L ${pts[0].x},${H - pB} Z`;

  const gridLines: number[] = [];
  for (let g = minY; g <= maxY + 0.001; g += 0.1) gridLines.push(parseFloat(g.toFixed(2)));

  const events = failureGroups
    .filter(g => g.first_seen_seq != null)
    .map(g => {
      const idx = sorted.findIndex(r => r.run_sequence === g.first_seen_seq);
      return idx >= 0 ? { idx, group: g } : null;
    })
    .filter((e): e is { idx: number; group: ApiFailureGroup } => e !== null);

  const clustersByRun = events.reduce((map, event) => {
    const groups = map.get(event.idx) ?? [];
    groups.push(event.group);
    map.set(event.idx, groups);
    return map;
  }, new Map<number, ApiFailureGroup[]>());
  const tooltipSide =
    hovered == null ? 'above'
    : hovered.y < 86 ? 'below'
    : 'above';
  const tooltipTransform =
    hovered == null ? 'translate(-50%, -115%)'
    : hovered.x > W - 150
      ? tooltipSide === 'below' ? 'translate(-100%, 12px)' : 'translate(-100%, -115%)'
      : hovered.x < 150
        ? tooltipSide === 'below' ? 'translate(0, 12px)' : 'translate(0, -115%)'
        : tooltipSide === 'below' ? 'translate(-50%, 12px)' : 'translate(-50%, -115%)';

  return (
    <div className="relative" style={{ width: '100%', overflowX: 'auto' }} onMouseLeave={() => setHovered(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minWidth: 480, height: H + 8, display: 'block' }}>
        {/* Grid */}
        {gridLines.map((g, i) => (
          <g key={i}>
            <line x1={pL} y1={yAt(g)} x2={W - pR} y2={yAt(g)} stroke="var(--color-border-subtle)" strokeWidth="1" />
            <text x={pL - 6} y={yAt(g) + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="JetBrains Mono, monospace">
              {Math.round(g * 100)}%
            </text>
          </g>
        ))}
        {/* X labels */}
        {sorted.map((r, i) => (i === 0 || i === sorted.length - 1 || i % Math.max(1, Math.floor(sorted.length / 6)) === 0) && (
          <text key={i} x={xAt(i)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--text-muted)" fontFamily="JetBrains Mono, monospace">
            #{r.run_sequence}
          </text>
        ))}
        {/* Area + line */}
        <path d={areaPath} fill="var(--color-info)" opacity="0.07" />
        <path d={linePath} fill="none" stroke="var(--color-info)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        {/* Failure cluster markers */}
        {events.map((e, i) => (
          <g key={i}>
            <line x1={xAt(e.idx)} y1={pT} x2={xAt(e.idx)} y2={H - pB} stroke="var(--color-danger)" strokeDasharray="3,3" strokeWidth="1" opacity="0.5" />
            <circle cx={xAt(e.idx)} cy={yAt(series[e.idx])} r="5" fill="var(--color-danger)" stroke="white" strokeWidth="1.5">
              <title>{e.group.error_type}: {e.group.message}</title>
            </circle>
          </g>
        ))}
        {/* Data points */}
        {pts.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={i === pts.length - 1 ? 4 : 2.5}
            fill={i === pts.length - 1 ? 'var(--color-info)' : 'white'}
            stroke="var(--color-info)" strokeWidth="1.5">
            <title>Run #{p.run.run_sequence}: {Math.round(p.v * 100)}%{p.run.branch ? ` · ${p.run.branch}` : ''}</title>
          </circle>
        ))}
        {/* Wide hover targets so the chart behaves like an interactive timeline. */}
        {pts.map((p, i) => {
          const left = i === 0 ? pL : (xAt(i - 1) + p.x) / 2;
          const right = i === pts.length - 1 ? W - pR : (p.x + xAt(i + 1)) / 2;
          return (
            <rect
              key={`hover-${p.run.run_id}`}
              x={left}
              y={pT}
              width={Math.max(1, right - left)}
              height={H - pT - pB}
              fill="transparent"
              onMouseEnter={() => setHovered({
                x: p.x,
                y: p.y,
                run: p.run,
                passRate: p.v,
                clusters: clustersByRun.get(i) ?? [],
              })}
              onMouseMove={() => setHovered({
                x: p.x,
                y: p.y,
                run: p.run,
                passRate: p.v,
                clusters: clustersByRun.get(i) ?? [],
              })}
            />
          );
        })}
      </svg>
      {hovered && (
        <div
          className="pointer-events-none absolute z-20 w-64 rounded-xl border border-border-default bg-surface px-3 py-2.5 text-xs shadow-lg"
          style={{
            left: `${(hovered.x / W) * 100}%`,
            top: `${(hovered.y / H) * 100}%`,
            transform: tooltipTransform,
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-semibold text-primary">Run #{hovered.run.run_sequence}</div>
              <div className="mt-0.5 text-muted">
                {hovered.run.project ?? 'All projects'}{hovered.run.branch ? ` · ${hovered.run.branch}` : ''}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-bold text-info type-nums">{Math.round(hovered.passRate * 100)}%</div>
              <div className="text-[10px] text-muted">pass rate</div>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 border-t border-border-subtle pt-2 text-center">
            <div>
              <div className="font-semibold text-success type-nums">{hovered.run.passed_count}</div>
              <div className="text-[10px] text-muted">passed</div>
            </div>
            <div>
              <div className="font-semibold text-danger type-nums">{hovered.run.failed_count}</div>
              <div className="text-[10px] text-muted">failed</div>
            </div>
            <div>
              <div className="font-semibold text-primary type-nums">{hovered.run.total_tests}</div>
              <div className="text-[10px] text-muted">total</div>
            </div>
          </div>
          {hovered.clusters.length > 0 && (
            <div className="mt-2 border-t border-border-subtle pt-2">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-danger">
                Failure cluster appeared
              </div>
              <div className="space-y-1">
                {hovered.clusters.slice(0, 3).map(cluster => (
                  <div key={cluster.fingerprint} className="truncate text-muted">
                    {cluster.error_type ?? cluster.category}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {events.length > 0 && (
        <div className="flex flex-wrap gap-3 mt-2">
          {events.map((e, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs text-muted">
              <span className="w-2 h-2 rounded-full bg-danger shrink-0" />
              <span className="font-mono text-secondary font-medium">#{e.group.first_seen_seq}</span>
              <span className="text-border-default">·</span>
              <span>{e.group.error_type}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Stability snapshot mix bar
// ─────────────────────────────────────────────────────────────

function ClassMixBar({ counts, total }: { counts: Record<string, number>; total: number }) {
  const segments = [
    { key: 'STABLE',              label: 'Stable',        color: 'var(--color-success)', textClass: 'text-success' },
    { key: 'CONSISTENT',          label: 'Consistent',    color: 'var(--color-success)', textClass: 'text-success', opacity: '0.6' },
    { key: 'FLAKY',               label: 'Flaky tests',   color: 'var(--color-warning)', textClass: 'text-warning' },
    { key: 'CONSISTENTLY_BROKEN', label: 'Broken',        color: 'var(--color-danger)',  textClass: 'text-danger'  },
    { key: 'INSUFFICIENT_DATA',   label: 'Insufficient',  color: 'var(--text-muted)',    textClass: 'text-muted'   },
  ];

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-4xl font-bold tracking-tight text-primary type-nums leading-none">{fmt(total)}</span>
        <span className="text-sm text-muted">tests tracked</span>
      </div>
      <div className="h-2.5 rounded-full overflow-hidden flex">
        {segments.map(s => {
          if (total <= 0) return null;
          const w = ((counts[s.key] ?? 0) / total) * 100;
          if (w === 0) return null;
          return <div key={s.key} title={`${s.label}: ${counts[s.key]}`}
            style={{ width: `${w}%`, background: s.color, opacity: s.opacity ?? 1 }} />;
        })}
      </div>
      <div className="mt-3 space-y-1.5">
        {segments.map(s => (counts[s.key] ?? 0) > 0 && (
          <div key={s.key} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: s.color, opacity: s.opacity ?? 1 }} />
            <span className="text-xs text-secondary flex-1">{s.label}</span>
            <span className={`text-xs font-semibold type-nums ${s.textClass}`}>{counts[s.key]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Active failure cluster timeline bar
// ─────────────────────────────────────────────────────────────

function ClusterRow({ group, firstSeq, lastSeq }: { group: ApiFailureGroup; firstSeq: number; lastSeq: number }) {
  const span = Math.max(lastSeq - firstSeq, 1);
  const hasFirstSeen = group.first_seen_seq != null;
  const hasLastSeen = group.last_seen_seq != null;
  const rawStartPct = (((group.first_seen_seq ?? firstSeq) - firstSeq) / span) * 100;
  const rawEndPct   = (((group.last_seen_seq  ?? lastSeq)  - firstSeq) / span) * 100;
  const startPct = clampPct(rawStartPct);
  const endPct = clampPct(rawEndPct);
  const widthPct = Math.max(endPct - startPct, 3);
  const isActive = hasLastSeen && group.last_seen_seq === lastSeq;
  const timingLabel = hasFirstSeen && hasLastSeen
    ? isActive
      ? `First seen Run #${group.first_seen_seq} · active in latest run`
      : `Seen Run #${group.first_seen_seq} to #${group.last_seen_seq} · not active in latest run`
    : 'Seen in selected window · exact run range unavailable';

  return (
    <div className="space-y-1.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-sm font-semibold text-primary truncate">{group.error_type ?? group.category}</div>
          <div className="font-mono text-xs text-muted truncate mt-0.5">{group.message}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className="inline-flex items-baseline gap-1 rounded-lg border border-danger/20 bg-danger/[0.05] px-2 py-1 text-danger">
            <span className="text-sm font-bold type-nums">{group.occurrence_count}</span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em]">
              occurrence{group.occurrence_count !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted">
            impacts {group.affected_tests} test{group.affected_tests !== 1 ? 's' : ''}
          </div>
        </div>
      </div>
      <div className="space-y-1.5">
        <div className="text-xs text-muted">{timingLabel}</div>
        <div className="relative h-4 rounded bg-surface-subtle overflow-hidden">
          <div className="absolute top-1 bottom-1 rounded"
            style={{ left: `${startPct}%`, width: `${widthPct}%`, background: isActive ? 'var(--color-danger)' : 'var(--color-warning)', opacity: 0.7 }} />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Suite card
// ─────────────────────────────────────────────────────────────

function SuiteCard({ name, tests, passRate, sparkline }: { name: string; tests: number; passRate: number; sparkline: string }) {
  const tone = passRate >= 0.8 ? 'var(--color-success)' : passRate >= 0.5 ? 'var(--color-warning)' : 'var(--color-danger)';
  const textTone = toneFor(passRate);
  return (
    <div className={`rounded-xl border p-3.5 ${bgToneFor(passRate)}`}>
      <div className="text-sm font-semibold text-primary truncate">{name}</div>
      <div className="text-xs text-muted mt-0.5"><span className="type-nums">{tests}</span> tests</div>
      <div className="flex items-end justify-between mt-2 gap-2">
        <div className={`text-2xl font-bold type-nums tracking-tight leading-none ${textTone}`}>
          {Math.round(passRate * 100)}%
        </div>
        <SparkFromString sparkline={sparkline} color={tone} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Signal chip (trend intelligence)
// ─────────────────────────────────────────────────────────────

function SignalChip({ sig }: { sig: { metric: string; direction: string; delta: number; detail: string } }) {
  const metric = sig.metric.toLowerCase();
  const harmful = sig.direction === 'declining' || sig.direction === 'worsening' || sig.direction === 'new' ||
    (sig.direction === 'increasing' && metric !== 'stability' && metric !== 'pass_rate');
  const helpful = sig.direction === 'improving' || sig.direction === 'recovering' || sig.direction === 'reducing';
  const tone = harmful ? 'danger' : helpful ? 'success' : 'neutral';
  const borderColor = tone === 'danger' ? 'border-danger/25' : tone === 'success' ? 'border-success/25' : 'border-border-subtle';
  const bgColor     = tone === 'danger' ? 'bg-danger/5' : tone === 'success' ? 'bg-success/5' : 'bg-surface-subtle';
  const textColor   = tone === 'danger' ? 'text-danger' : tone === 'success' ? 'text-success' : 'text-muted';
  const arrow       = sig.direction === 'declining' || sig.direction === 'worsening' || sig.direction === 'reducing' ? '↓'
    : sig.direction === 'improving' || sig.direction === 'recovering' || sig.direction === 'increasing' || sig.direction === 'new' ? '↑'
    : '→';

  const absDelta = Math.abs(Number(sig.delta) || 0);
  const displayMetric = metric === 'flakiness' ? 'Volatility' : sig.metric.replace(/_/g, ' ');
  const unit = metric === 'wall_clock_ms' ? 's'
    : metric === 'stability' || metric === 'pass_rate' || metric === 'failures' ? ' pts'
    : metric === 'flakiness' ? ' transitions'
    : '';
  const normalizedDelta = metric === 'wall_clock_ms' ? Math.round(absDelta / 1000) : absDelta;
  const deltaLabel = metric === 'failures' && sig.delta < 0
    ? `${normalizedDelta}${unit} below baseline`
    : metric === 'failures' && sig.delta > 0
      ? `${normalizedDelta}${unit} above baseline`
      : sig.direction === 'reducing'
        ? `${normalizedDelta}${unit} lower`
        : sig.direction === 'declining'
          ? `${normalizedDelta}${unit} down`
          : sig.direction === 'flat' || sig.direction === 'stable'
            ? `${normalizedDelta}${unit}`
            : `${normalizedDelta === 0 ? '' : '+'}${normalizedDelta}${unit}`;

  return (
    <div className={`rounded-xl border p-3 ${borderColor} ${bgColor}`}>
      <div className="flex items-center gap-1.5">
        <span className={`text-base font-bold ${textColor}`}>{arrow}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wider ${textColor}`}>
          {displayMetric}
        </span>
        <span className={`text-sm font-bold type-nums ${textColor}`}>{deltaLabel}</span>
      </div>
      <div className="text-xs text-muted mt-1 leading-relaxed">{sig.detail}</div>
    </div>
  );
}

function SlowingTestsList({ tests }: { tests: ApiRiskEntry[] }) {
  if (tests.length === 0) {
    return <p className="text-sm text-muted mt-3">No tests showing significant duration spikes.</p>;
  }

  return (
    <div className="mt-3 space-y-3">
      {tests.map(r => (
        <div key={r.canonical_name} className="flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="font-mono text-sm font-semibold text-primary truncate">
              {r.display_name.replace(/\(\)$/, '')}()
            </div>
            <div className="text-xs text-muted mt-0.5">
              <span className="font-medium text-secondary">{r.owner}</span>
              {' · '}
              <span className="text-warning">Spike {Math.round((r.signals?.duration_spike ?? 0) * 100)}/100</span>
            </div>
          </div>
          <div className="w-20 h-1.5 rounded-full bg-surface-subtle overflow-hidden shrink-0">
            <div
              className="h-full rounded-full bg-warning"
              style={{ width: `${(r.signals?.duration_spike ?? 0) * 100}%` }}
            />
          </div>
          <Tooltip content={`${r.tier} risk tier`}>
            <span className="text-xs font-semibold text-warning bg-warning/10 border border-warning/20 px-1.5 py-0.5 rounded-full shrink-0">
              {r.tier}
            </span>
          </Tooltip>
        </div>
      ))}
    </div>
  );
}

function summaryTone(text: string) {
  const lowered = text.toLowerCase();
  const stabilityMatch = lowered.match(/test stability moved from (\d+)% to (\d+)%/);
  if (stabilityMatch) {
    const from = Number(stabilityMatch[1]);
    const to = Number(stabilityMatch[2]);
    if (to < from) return { label: 'Needs attention', dotClass: 'bg-danger', textClass: 'text-danger' };
    if (to > from) return { label: 'Improved', dotClass: 'bg-success', textClass: 'text-success' };
  }
  if (lowered.includes('new failure') && !lowered.includes('0 new failure')) {
    return { label: 'Regression', dotClass: 'bg-danger', textClass: 'text-danger' };
  }
  if (lowered.includes('recovered') && lowered.includes('0 new failure')) {
    return { label: 'Recovery', dotClass: 'bg-success', textClass: 'text-success' };
  }
  if (lowered.includes('major incident') && !lowered.includes('0 major incident')) {
    return { label: 'Incident risk', dotClass: 'bg-danger', textClass: 'text-danger' };
  }
  return { label: 'Context', dotClass: 'bg-info', textClass: 'text-info' };
}

function SummaryBullet({ text }: { text: string }) {
  const tone = summaryTone(text);

  return (
    <li className="flex items-start gap-2 text-sm text-primary leading-relaxed">
      <span className={`mt-1.5 w-1.5 h-1.5 rounded-full ${tone.dotClass} shrink-0`} />
      <span>
        <span className={`mr-1.5 font-semibold ${tone.textClass}`}>{tone.label}:</span>
        {text}
      </span>
    </li>
  );
}

// ─────────────────────────────────────────────────────────────
// Main panel
// ─────────────────────────────────────────────────────────────

export function AnalysisPanel() {
  const { currentProject } = useProject();
  const [window_, setWindow] = useState(10);

  const [runs,            setRuns]            = useState<ApiRun[]>([]);
  const [stability,       setStability]       = useState<ApiStabilityEntry[]>([]);
  const [trends,          setTrends]          = useState<ApiTrendEntry[]>([]);
  const [failureGroups,   setFailureGroups]   = useState<ApiFailureGroup[]>([]);
  const [risk,            setRisk]            = useState<ApiRiskEntry[]>([]);
  const [ownerStats,      setOwnerStats]      = useState<ApiOwnerStatEntry[]>([]);
  const [decisionSummary, setDecisionSummary] = useState<ApiDecisionSummary | null>(null);
  const [loading,         setLoading]         = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(window_) });
    if (currentProject) params.set('project', currentProject);
    const p = params.toString();

    Promise.all([
      fetch(`/api/runs?${p}`).then(r => r.ok ? r.json() : []),
      fetch(`/api/stability?${p}`).then(r => r.ok ? r.json() : []),
      fetch(`/api/stability/trends?${p}`).then(r => r.ok ? r.json() : []),
      fetch(`/api/failure-groups?${p}`).then(r => r.ok ? r.json() : []),
      fetch(`/api/risk?${p}`).then(r => r.ok ? r.json() : []),
      fetch(`/api/owner-stats?${new URLSearchParams(currentProject ? { project: currentProject } : {})}`).then(r => r.ok ? r.json() : { owners: [] }),
      fetch(`/api/decision-summary?${new URLSearchParams({ window: String(window_), ...(currentProject ? { project: currentProject } : {}) })}`).then(r => r.ok ? r.json() : null),
    ]).then(([runsData, stabData, trendsData, fgData, riskData, ownerData, dsData]) => {
      setRuns(runsData as ApiRun[]);
      setStability(stabData as ApiStabilityEntry[]);
      setTrends(trendsData as ApiTrendEntry[]);
      setFailureGroups(fgData as ApiFailureGroup[]);
      setRisk(riskData as ApiRiskEntry[]);
      setOwnerStats((ownerData as { owners: ApiOwnerStatEntry[] })?.owners ?? []);
      setDecisionSummary(dsData as ApiDecisionSummary | null);
    }).finally(() => setLoading(false));
  }, [currentProject, window_]);

  // ── Derived data ──────────────────────────────────────────

  const sortedRuns = useMemo(() => [...runs].sort((a, b) => a.run_sequence - b.run_sequence), [runs]);
  const latestRun  = sortedRuns[sortedRuns.length - 1];
  const firstRun   = sortedRuns[0];

  const passRateSeries = sortedRuns.map(passRateOf);
  const durationSeries = sortedRuns.map(r => Math.round((r.total_ms ?? 0) / 1000));
  const failedSeries   = sortedRuns.map(r => r.failed_count);

  const passRateDelta = latestRun && firstRun && latestRun !== firstRun
    ? Math.round((passRateOf(latestRun) - passRateOf(firstRun)) * 100)
    : 0;
  const durationDelta = latestRun && firstRun && latestRun !== firstRun
    ? Math.round(((latestRun.total_ms ?? 0) - (firstRun.total_ms ?? 0)) / 1000)
    : 0;
  const failedDelta = latestRun && firstRun && latestRun !== firstRun
    ? latestRun.failed_count - firstRun.failed_count
    : 0;

  const classCounts = useMemo(() => {
    const c: Record<string, number> = {};
    stability.forEach(t => { c[t.classification] = (c[t.classification] ?? 0) + 1; });
    return c;
  }, [stability]);

  const totalTests = useMemo(() => Object.values(classCounts).reduce((s, n) => s + n, 0), [classCounts]);

  const trendCounts = useMemo(() =>
    trends.reduce((m, t) => { m[t.direction] = (m[t.direction] ?? 0) + 1; return m; },
      { declining: 0, improving: 0, stable: 0 } as Record<string, number>),
    [trends]);

  const suites = useMemo(() => {
    const map = new Map<string, { tests: number; passSum: number; sparks: string[] }>();
    stability.forEach(t => {
      const s = map.get(t.suite) ?? { tests: 0, passSum: 0, sparks: [] };
      s.tests++;
      s.passSum += t.pass_rate;
      s.sparks.push(t.sparkline);
      map.set(t.suite, s);
    });
    return [...map.entries()]
      .map(([name, s]) => ({
        name,
        tests: s.tests,
        passRate: s.passSum / s.tests,
        sparkline: s.sparks[0] ?? '',
      }))
      .sort((a, b) => a.passRate - b.passRate);
  }, [stability]);

  const slowing = useMemo(() =>
    risk.filter(r => (r.signals?.duration_spike ?? 0) > 0.5)
      .sort((a, b) => (b.signals?.duration_spike ?? 0) - (a.signals?.duration_spike ?? 0))
      .slice(0, 5),
    [risk]);

  const sortedOwners = useMemo(() =>
    [...ownerStats].sort((a, b) => b.failing_tests - a.failing_tests),
    [ownerStats]);

  // ── First/last seq for cluster timeline ──────────────────
  const firstSeq = sortedRuns[0]?.run_sequence ?? 1;
  const lastSeq  = sortedRuns[sortedRuns.length - 1]?.run_sequence ?? 1;

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        {[1,2,3,4].map(i => <div key={i} className="h-32 rounded-2xl bg-surface-subtle" />)}
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-8">

      {/* ── Header ───────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="type-eyebrow text-info mb-1.5">
            Analysis{currentProject ? ` · ${currentProject}` : ''}
            {sortedRuns.length > 1 ? ` · runs #${firstSeq}–#${lastSeq}` : ''}
          </p>
          <h1 className="text-2xl font-bold tracking-tight text-primary">Suite trends &amp; behavior</h1>
          <p className="text-sm text-muted mt-1">
            How your suite is moving over time. Triage today's failures in{' '}
            <span className="font-medium text-secondary">Runs</span>, error clusters in{' '}
            <span className="font-medium text-secondary">Incidents</span>, predicted failures in{' '}
            <span className="font-medium text-secondary">Risk</span>.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted">Analysis window</span>
          <Dropdown
            value={String(window_)}
            onChange={value => setWindow(Number(value))}
            triggerClassName="min-w-[128px] px-3.5 text-sm"
            align="right"
            options={[5, 10, 20, 50].map(n => ({
              value: String(n),
              label: `Last ${n} runs`,
            }))}
          />
        </div>
      </div>

      {/* ── Trend intelligence strip ──────────────────────── */}
      {decisionSummary && (
        <SectionCard source="/api/decision-summary">
          <Eyebrow>Analysis brief</Eyebrow>
          <CardTitle>Latest transition and selected-window trend</CardTitle>
          {decisionSummary.executive_summary.length > 0 && (
            <div className="mt-3 rounded-xl border border-border-subtle bg-surface-subtle p-3.5">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted">
                Latest transition
              </p>
              <ul className="mt-2 grid gap-x-6 gap-y-1.5 md:grid-cols-2">
                {decisionSummary.executive_summary.map((s, i) => (
                  <SummaryBullet key={i} text={s} />
                ))}
              </ul>
            </div>
          )}
          {decisionSummary.trend_intelligence.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted">
                Selected-window trend
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-2">
                {decisionSummary.trend_intelligence.map((sig, i) => (
                  <SignalChip key={i} sig={sig} />
                ))}
              </div>
            </div>
          )}
        </SectionCard>
      )}

      {/* ── KPI row ───────────────────────────────────────── */}
      {latestRun && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <KpiTile
            label="Pass rate"
            value={latestRun.total_tests > 0 ? pct(latestRun.passed_count / latestRun.total_tests) : '—'}
            delta={passRateDelta}
            deltaSuffix=" pts"
            series={passRateSeries}
            source="/api/runs"
          />
          <KpiTile
            label="Wall-clock"
            value={latestRun.total_ms ? `${Math.round(latestRun.total_ms / 1000)}s` : '—'}
            delta={durationDelta}
            deltaSuffix="s"
            inverted
            series={durationSeries}
            source="/api/runs · total_ms"
          />
          <KpiTile
            label="Failed tests"
            value={String(latestRun.failed_count)}
            delta={failedDelta}
            inverted
            series={failedSeries}
            source="/api/runs · failed_count"
          />
        </div>
      )}

      {/* ── Pass rate journey ─────────────────────────────── */}
      {sortedRuns.length >= 2 && (
        <SectionCard source="/api/runs + /api/failure-groups">
          <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
            <div>
              <Eyebrow>Pass rate journey</Eyebrow>
              <CardTitle>Is the suite trending up or down?</CardTitle>
            </div>
            <div className="flex items-center gap-4 text-xs text-muted flex-wrap">
              <div className="flex items-center gap-1.5">
                <svg width="24" height="4"><line x1="0" y1="2" x2="24" y2="2" stroke="var(--color-info)" strokeWidth="2" /></svg>
                Pass rate
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-danger shrink-0" />
                Failure cluster appeared
              </div>
            </div>
          </div>
          <PassRateJourney runs={sortedRuns} failureGroups={failureGroups} />
        </SectionCard>
      )}

      {/* ── Two-column: stability snapshot + active clusters ─ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SectionCard source="/api/stability + /api/stability/trends">
          <Eyebrow>Stability snapshot</Eyebrow>
          <CardTitle>What's the current health mix?</CardTitle>
          <div className="mt-4">
            <ClassMixBar counts={classCounts} total={totalTests} />
          </div>
          {trendCounts && (
            <div className="mt-5 pt-4 border-t border-border-subtle">
              <Eyebrow>Per-test trend direction</Eyebrow>
              <div className="grid grid-cols-3 gap-3 mt-2">
                {[
                  { label: 'Declining', key: 'declining', color: 'text-danger' },
                  { label: 'Stable',    key: 'stable',    color: 'text-muted'   },
                  { label: 'Improving', key: 'improving', color: 'text-success' },
                ].map(t => (
                  <div key={t.key} className="text-center">
                    <div className={`text-2xl font-bold type-nums leading-none ${t.color}`}>{trendCounts[t.key] ?? 0}</div>
                    <div className="text-xs text-muted mt-0.5">{t.label}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="mt-5 pt-4 border-t border-border-subtle">
            <Eyebrow>Slowing tests</Eyebrow>
            <CardTitle>What's getting slower over time?</CardTitle>
            <SlowingTestsList tests={slowing} />
          </div>
        </SectionCard>

        <SectionCard source="/api/failure-groups">
          <Eyebrow>Active failure clusters</Eyebrow>
          <CardTitle>How long have these been hurting us?</CardTitle>
          {failureGroups.length === 0 ? (
            <p className="text-sm text-muted mt-4">No recurring failure clusters found.</p>
          ) : (
            <div className="mt-4">
              <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-muted">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-5 rounded-full bg-danger" />
                  Active in latest run
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-5 rounded-full bg-warning" />
                  Seen earlier in window
                </span>
              </div>
              <div className="space-y-5">
                {failureGroups.slice(0, 5).map(g => (
                  <ClusterRow key={g.fingerprint} group={g} firstSeq={firstSeq} lastSeq={lastSeq} />
                ))}
              </div>
            </div>
          )}
        </SectionCard>
      </div>

      <SectionCard source="/api/stability (aggregated by suite)">
        <Eyebrow>By suite</Eyebrow>
        <CardTitle>Which suites are degrading?</CardTitle>
        {suites.length === 0 ? (
          <p className="text-sm text-muted mt-4">No suite data available.</p>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
            {suites.map(s => (
              <SuiteCard key={s.name} name={s.name} tests={s.tests} passRate={s.passRate} sparkline={s.sparkline} />
            ))}
          </div>
        )}
      </SectionCard>

      {/* ── Owner load ────────────────────────────────────── */}
      {sortedOwners.length > 0 && (
        <SectionCard source="/api/owner-stats">
          <Eyebrow>Owner load</Eyebrow>
          <CardTitle>Where's the test ownership concentrated?</CardTitle>
          <div className="mt-4 space-y-3">
            {sortedOwners.slice(0, 8).map(o => {
              const passRate = Math.max(0, Math.min(1, 1 - o.failure_rate));
              const failRate = Math.max(0, Math.min(1, o.failure_rate));
              const passW = passRate * 100;
              const failW = failRate * 100;
              return (
                <div key={o.owner} className="flex items-center gap-3">
                  <InitialsAvatar name={o.owner} />
                  <div className="w-36 shrink-0 text-sm text-primary truncate">{o.owner}</div>
                  <div className="flex-1 h-2 rounded-full bg-surface-subtle overflow-hidden relative">
                    <div className="absolute top-0 left-0 h-full rounded-full bg-success/60"
                      style={{ width: `${passW}%` }} />
                    <div className="absolute top-0 h-full rounded-full bg-danger"
                      style={{ left: `${passW}%`, width: `${failW}%` }} />
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-semibold type-nums text-primary">{o.total_tests} tests</div>
                    <div className="text-xs text-muted">{Math.round(passRate * 100)}% pass</div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex items-center gap-4 mt-4 text-xs text-muted">
            <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-success/60" />Passing</div>
            <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-danger" />Failing</div>
          </div>
        </SectionCard>
      )}

    </div>
  );
}
