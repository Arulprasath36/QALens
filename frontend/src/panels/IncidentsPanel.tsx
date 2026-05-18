import { useState, useEffect, useCallback, useMemo, Fragment } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
import { Tooltip } from '../components/Tooltip';
import { FailureFlakinessView } from './FailureFlakinessView';
import { RunTimelineStrip } from './RunTimelineStrip';
import { useProject } from '../hooks/useProject';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

interface ApiRun {
  run_id:        string;
  project:       string | null;
  run_sequence:  number;
  started_at:    number | null; // Unix timestamp
  total_tests:   number | null;
  passed_count:  number | null;
  failed_count:  number | null;
  flaky_count?:  number | null;
  skipped_count: number | null;
  branch:        string | null;
  build_number:  string | null;
}

export interface ApiIncident {
  incident_id:                string;
  run_id:                     string;
  title:                      string;
  severity:                   'critical' | 'high' | 'medium' | 'low';
  impacted_test_count:        number;
  impacted_tests:             string[];
  probable_root_cause:        string;
  root_cause_category:        string;
  confidence:                 'high' | 'medium' | 'low';
  evidence:                   string[];
  recommended_action:         string;
  signature:                  string | null;
  error_type:                 string | null;
  representative_message:     string | null;
  representative_stack_trace: string | null;
  components:                 string[];
}

interface AggregatedIncident extends ApiIncident {
  cluster_id:                  string;
  total_occurrences_in_scope:  number;
  runs_seen_count:             number;
  runs_seen_ids:               string[];
  run_sequences:               number[];
  first_seen_run_id:           string;
  last_seen_run_id:            string;
  first_seen_sequence:         number;
  last_seen_sequence:          number;
  latest_occurrence_count:     number;
  previous_occurrence_count:   number;
  trend:                       'new' | 'worsening' | 'stable' | 'improving' | 'reducing';
  related_tests:               string[];
  occurrence_count:            number;
}

type FailureMode = 'incidents' | 'failures';
type ViewMode = 'single' | 'window';

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
  category: string;
  scope: 'window' | 'all_time';
  window_size: number | null;
}

interface EnrichedCluster {
  fingerprint: string;
  error_type: string | null;
  message: string;
  occurrence_count: number;
  affected_tests: number;
  affected_runs: number;
  window_size: number | null;
  scope: 'window' | 'all_time';
  first_seen_seq: number | null;
  affected_canonical_names: string[];
  category: string;
  incident: AggregatedIncident | null;
}

function mergeGroupsWithIncidents(
  groups: ApiFailureGroup[],
  incidents: AggregatedIncident[],
): EnrichedCluster[] {
  // Build lookup: signature → incident
  const bySignature = new Map<string, AggregatedIncident>();
  for (const inc of incidents) {
    if (inc.signature) bySignature.set(inc.signature, inc);
  }

  return groups.map(group => ({
    fingerprint:              group.fingerprint,
    error_type:               group.error_type,
    message:                  group.message,
    occurrence_count:         group.occurrence_count,
    affected_tests:           group.affected_tests,
    affected_runs:            group.affected_runs,
    window_size:              group.window_size,
    scope:                    group.scope,
    first_seen_seq:           group.first_seen_seq,
    affected_canonical_names: group.affected_canonical_names,
    category:                 group.category,
    incident: bySignature.get(group.fingerprint) ?? null,
  }));
}

// ─────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────

const SEV_CONFIG = {
  critical: {
    label:        'Wide impact',
    tooltipTitle: 'Wide impact — 5 or more tests',
    tooltipBody:  'This failure cause broke 5 or more tests in a single run. Likely a systemic or shared dependency issue.',
    text:         'text-red-400',
    bg:           'bg-red-500/10',
    border:       'border-red-500/30',
    dot:          'bg-red-400',
  },
  high: {
    label:        'High impact',
    tooltipTitle: 'High impact — 3 to 4 tests',
    tooltipBody:  'This failure cause affected 3 to 4 tests. Suggests a shared code path or configuration is involved.',
    text:         'text-orange-400',
    bg:           'bg-orange-500/10',
    border:       'border-orange-500/30',
    dot:          'bg-orange-400',
  },
  medium: {
    label:        'Moderate impact',
    tooltipTitle: 'Moderate impact — 2 tests',
    tooltipBody:  'Two tests share this failure cause. May be coincidence or a narrow shared dependency.',
    text:         'text-amber-400',
    bg:           'bg-amber-500/10',
    border:       'border-amber-500/30',
    dot:          'bg-amber-400',
  },
  low: {
    label:        'Isolated',
    tooltipTitle: 'Isolated — 1 test',
    tooltipBody:  'Only one test is affected. Likely a test-specific issue or edge case.',
    text:         'text-green-400',
    bg:           'bg-green-500/10',
    border:       'border-green-500/30',
    dot:          'bg-green-400',
  },
} as const;

const INCIDENT_SCOPE_OPTIONS = [5, 10, 15, 20];

const SEVERITY_RANK: Record<ApiIncident['severity'], number> = {
  critical: 4,
  high:     3,
  medium:   2,
  low:      1,
};

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function formatTs(ts: number | null): string {
  if (ts == null) return '—';
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function scopeLabel(size: number): string {
  return size === 1 ? 'This run' : `Last ${size} runs`;
}

function runRangeLabel(windowRuns: ApiRun[]): string {
  if (windowRuns.length === 0) return 'selected runs';
  const sequences = windowRuns.map(run => run.run_sequence).sort((a, b) => a - b);
  const first = sequences[0];
  const last = sequences[sequences.length - 1];
  return first === last ? `Run #${first}` : `Runs #${first}-#${last}`;
}

function incidentGroupKey(inc: ApiIncident): string {
  return inc.signature || inc.incident_id;
}

function mergeUnique<T>(a: T[], b: T[]): T[] {
  return [...new Set([...a, ...b])];
}

function computeTrend(runImpacts: Map<string, number>, windowRuns: ApiRun[]): AggregatedIncident['trend'] {
  const endingRun = windowRuns[0];
  const endingRunImpact = runImpacts.get(endingRun.run_id) ?? 0;
  const previousImpacts = windowRuns.slice(1).map(run => runImpacts.get(run.run_id) ?? 0);
  const previousMax = Math.max(0, ...previousImpacts);
  const previousSeen = previousImpacts.filter(v => v > 0).length;

  if (endingRunImpact > 0 && previousSeen === 0) return 'new';
  if (endingRunImpact === 0 && previousSeen > 0) return 'improving';
  if (endingRunImpact > previousMax) return 'worsening';

  const midpoint = Math.ceil(windowRuns.length / 2);
  const recentSeen = windowRuns.slice(0, midpoint).filter(run => (runImpacts.get(run.run_id) ?? 0) > 0).length;
  const olderSeen = windowRuns.slice(midpoint).filter(run => (runImpacts.get(run.run_id) ?? 0) > 0).length;
  if (recentSeen > olderSeen + 1 && endingRunImpact >= previousMax) return 'worsening';
  if (endingRunImpact > 0 && endingRunImpact < previousMax) return 'reducing';
  if (recentSeen + 1 < olderSeen) return 'improving';
  return 'stable';
}

function aggregateIncidents(items: { incident: ApiIncident; run: ApiRun }[], windowRuns: ApiRun[]): AggregatedIncident[] {
  const grouped = new Map<string, {
    representative: ApiIncident;
    severity: ApiIncident['severity'];
    impactedTests: string[];
    evidence: string[];
    components: string[];
    runImpacts: Map<string, number>;
    runSequences: number[];
  }>();

  for (const { incident, run } of items) {
    const key = incidentGroupKey(incident);
    const existing = grouped.get(key);

    if (!existing) {
      grouped.set(key, {
        representative: incident,
        severity: incident.severity,
        impactedTests: incident.impacted_tests,
        evidence: incident.evidence,
        components: incident.components,
        runImpacts: new Map([[run.run_id, incident.impacted_test_count]]),
        runSequences: [run.run_sequence],
      });
      continue;
    }

    const keepSeverity = SEVERITY_RANK[incident.severity] > SEVERITY_RANK[existing.severity]
      ? incident.severity
      : existing.severity;

    existing.severity = keepSeverity;
    existing.impactedTests = mergeUnique(existing.impactedTests, incident.impacted_tests);
    existing.evidence = mergeUnique(existing.evidence, incident.evidence).slice(0, 6);
    existing.components = mergeUnique(existing.components, incident.components);
    existing.runSequences = mergeUnique(existing.runSequences, [run.run_sequence]).sort((a, b) => b - a);
    existing.runImpacts.set(
      run.run_id,
      Math.max(existing.runImpacts.get(run.run_id) ?? 0, incident.impacted_test_count),
    );
  }

  return [...grouped.entries()].map(([key, group]) => {
    const runsSeen = windowRuns.filter(run => group.runImpacts.has(run.run_id));
    const firstSeen = [...runsSeen].sort((a, b) => a.run_sequence - b.run_sequence)[0] ?? windowRuns[windowRuns.length - 1];
    const lastSeen = [...runsSeen].sort((a, b) => b.run_sequence - a.run_sequence)[0] ?? windowRuns[0];
    const latestOccurrenceCount = group.runImpacts.get(windowRuns[0]?.run_id) ?? 0;
    const previousOccurrenceCount = Math.max(0, ...windowRuns.slice(1).map(run => group.runImpacts.get(run.run_id) ?? 0));

    return {
      ...group.representative,
      incident_id: key,
      cluster_id: key,
      severity: group.severity,
      impacted_tests: group.impactedTests,
      impacted_test_count: group.impactedTests.length,
      evidence: group.evidence,
      components: group.components,
      total_occurrences_in_scope: runsSeen.length,
      runs_seen_count: runsSeen.length,
      runs_seen_ids: runsSeen.map(run => run.run_id),
      run_sequences: group.runSequences,
      first_seen_run_id: firstSeen.run_id,
      last_seen_run_id: lastSeen.run_id,
      first_seen_sequence: firstSeen.run_sequence,
      last_seen_sequence: lastSeen.run_sequence,
      latest_occurrence_count: latestOccurrenceCount,
      previous_occurrence_count: previousOccurrenceCount,
      trend: computeTrend(group.runImpacts, windowRuns),
      related_tests: group.impactedTests.slice(0, 8),
      occurrence_count: runsSeen.length,
    };
  }).sort((a, b) =>
    SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]
    || b.runs_seen_count - a.runs_seen_count
    || b.impacted_test_count - a.impacted_test_count,
  );
}


/** Split a recommended_action string into ordered steps. */
function parseActionSteps(action: string): string[] {
  if (!action) return [];

  // Numbered list: "1. Do something. 2. Do something else."
  const numbered = action.match(/\d+\.\s+[^0-9]+?(?=\d+\.|$)/g);
  if (numbered && numbered.length >= 2) {
    return numbered.map(s => s.replace(/^\d+\.\s+/, '').trim()).filter(Boolean);
  }

  // Semicolon-delimited steps
  if (action.includes(';')) {
    return action.split(';').map(s => s.trim()).filter(Boolean);
  }

  return [action.trim()];
}

/** Render an evidence string, turning `backtick-quoted` segments into <code>. */
function EvidenceText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('`') && part.endsWith('`')
          ? <code key={i} className="px-1 py-0.5 rounded bg-surface-subtle text-secondary text-xs font-mono">
              {part.slice(1, -1)}
            </code>
          : <Fragment key={i}>{part}</Fragment>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// CopyButton
// ─────────────────────────────────────────────────────────────

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      onClick={handleCopy}
      className="qalens-chip type-chip"
    >
      {copied
        ? <><span>✓</span> Copied</>
        : <><span>⎘</span> {label}</>
      }
    </button>
  );
}

// ─────────────────────────────────────────────────────────────
// Stat cards
// ─────────────────────────────────────────────────────────────

function StatCards({ incidents, scope }: { incidents: AggregatedIncident[]; scope: number }) {
  const total       = incidents.length;
  const totalTests  = incidents.reduce((s, i) => s + i.impacted_test_count, 0);
  const highCount   = incidents.filter(i => i.severity === 'critical' || i.severity === 'high').length;
  const actionCount = incidents.filter(i => i.trend === 'new' || i.trend === 'worsening').length;
  const cards: { label: string; value: number; valueClass: string }[] = [
    { label: scope === 1 ? 'Incidents' : 'Active clusters', value: total,      valueClass: 'text-primary' },
    { label: 'Tests affected',                              value: totalTests, valueClass: 'text-danger'  },
    { label: 'High severity',                               value: highCount,  valueClass: 'text-warning' },
  ];
  if (scope > 1) {
    cards.push({ label: 'New / worsening', value: actionCount, valueClass: 'text-danger' });
  }

  return (
    <div className="qalens-stat-grid">
      {cards.map(c => (
        <div key={c.label} className="qalens-stat-card">
          <span className="type-metric-label">{c.label}</span>
          <span className={`type-metric-value ${c.valueClass}`}>{c.value}</span>
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// IncidentCard
// ─────────────────────────────────────────────────────────────

const TREND_TOOLTIP: Record<AggregatedIncident['trend'], { title: string; body: string }> = {
  new: {
    title: 'New failure pattern',
    body: 'First observed in the latest run — likely introduced recently.',
  },
  worsening: {
    title: 'Increasing impact',
    body: 'Expanding across tests or appearing more frequently than before.',
  },
  improving: {
    title: 'No recent impact',
    body: 'Not seen in the latest run — likely resolved.',
  },
  stable: {
    title: 'Ongoing issue',
    body: 'Continues across runs with no meaningful improvement.',
  },
  reducing: {
    title: 'Reducing impact',
    body: 'Still present, but affecting fewer tests than earlier in the window.',
  },
};

function TrendBadge({ trend }: { trend: AggregatedIncident['trend'] }) {
  const cfg = {
    new:       'border-info/20 bg-info/[0.06] text-info',
    worsening: 'border-danger/20 bg-danger/[0.06] text-danger',
    stable:    'border-border-default bg-surface-subtle text-secondary',
    improving: 'border-success/20 bg-success/[0.06] text-success',
    reducing:  'border-warning/20 bg-warning/[0.06] text-warning',
  }[trend];

  const label = trend === 'new' ? 'New'
    : trend === 'worsening' ? 'Worsening'
    : trend === 'improving' ? 'Improving'
    : trend === 'reducing'  ? 'Reducing'
    : 'Persistent';

  const tip = TREND_TOOLTIP[trend];

  return (
    <Tooltip
      content={
        <div className="space-y-1 max-w-[220px]">
          <p className="font-semibold text-primary text-[12px]">{tip.title}</p>
          <p className="text-[11px] text-muted leading-relaxed">{tip.body}</p>
        </div>
      }
    >
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold cursor-default ${cfg}`}>
        {label}
      </span>
    </Tooltip>
  );
}


function EnrichedClusterCard({
  cluster,
  scope,
  highlighted = false,
}: {
  cluster: EnrichedCluster;
  scope: number;
  highlighted?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const inc    = cluster.incident;
  const sev    = inc ? (SEV_CONFIG[inc.severity] ?? SEV_CONFIG.low) : SEV_CONFIG.low;
  const steps  = inc ? parseActionSteps(inc.recommended_action) : [];
  const tests  = inc ? inc.impacted_tests : cluster.affected_canonical_names;

  // Filter out generic non-suite component labels (e.g. "Failures", "Unknown")
  const EXCLUDED_COMPONENTS = new Set(['failures', 'unknown', 'ungrouped', 'none']);
  const suites = (inc?.components ?? []).filter(c => !EXCLUDED_COMPONENTS.has(c.toLowerCase()));

  // Deduplicate evidence: same pattern with different leading counts → keep highest.
  // Drop any verbose "Failures span suites: ..." lines — suite count is shown in the title.
  const evidence = (() => {
    const seen = new Map<string, string>();
    for (const e of (inc?.evidence ?? [])) {
      if (/failures?\s+span/i.test(e) || /span.*suites?/i.test(e)) continue;
      const key = e.replace(/^\d+/, 'N');
      const existing = seen.get(key);
      if (!existing || (parseInt(e) || 0) > (parseInt(existing) || 0)) seen.set(key, e);
    }
    return [...seen.values()];
  })();

  const impactSurface = suites.length > 1
    ? 'multiple suites'
    : suites.length === 1
    ? suites[0]
    : cluster.affected_tests > 1
    ? 'multiple tests'
    : 'a single test';
  const activityMeta = (() => {
    if (inc && scope > 1 && inc.first_seen_sequence && inc.last_seen_sequence) {
      return inc.first_seen_sequence === inc.last_seen_sequence ? (
        <>
          <span className="text-muted">First surfaced in run </span>
          <span className="font-medium text-info">#{inc.first_seen_sequence}</span>
        </>
      ) : (
        <>
          <span className="text-muted">Active from run </span>
          <span className="font-medium text-info">#{inc.first_seen_sequence}</span>
          <span className="text-muted"> to </span>
          <span className="font-medium text-info">#{inc.last_seen_sequence}</span>
        </>
      );
    }
    if (scope > 1) {
      return (
        <>
          <span className="text-muted">Seen in </span>
          <span className="font-medium text-info">{cluster.affected_runs}</span>
          <span className="text-muted"> of </span>
          <span className="font-medium text-info">{cluster.window_size ?? scope}</span>
          <span className="text-muted"> runs</span>
        </>
      );
    }
    return <span className="text-muted">Active in selected run</span>;
  })();
  const synthesisLine = (() => {
    if (inc?.trend === 'reducing')  return `This failure pattern is reducing, but it still affects ${impactSurface}.`;
    if (inc?.trend === 'improving') return `This failure pattern is easing and now looks contained to ${impactSurface}.`;
    if (inc?.trend === 'worsening') return `This failure pattern is spreading and now impacts ${impactSurface}.`;
    if (inc?.trend === 'new')       return `This appears newly introduced and is already impacting ${impactSurface}.`;
    if (inc?.trend === 'stable')    return `This failure pattern remains active across ${impactSurface} with no clear sign of improvement.`;
    if (scope > 1)                  return 'This unresolved failure pattern continues to surface across the selected run window.';
    return 'This failure pattern is active in the selected run and needs investigation.';
  })();
  // TODO: align confidence taxonomy across incident surfaces so "confidence" consistently reads as correlation strength.
  const correlationLabel = inc ? (
    inc.confidence === 'high'
      ? 'Strong correlation'
      : inc.confidence === 'medium'
      ? 'Moderate correlation'
      : 'Weak correlation'
  ) : '';
  const confidenceClasses = inc ? (
    inc.confidence === 'high'
      ? 'text-[rgb(var(--warning-rgb))] border-[rgb(var(--warning-rgb)/0.24)] bg-[rgb(var(--warning-rgb)/0.1)]'
      : inc.confidence === 'medium'
      ? 'text-secondary border-border-default bg-surface-subtle'
      : 'text-muted border-border-default bg-surface-subtle'
  ) : '';
  const signatureSnippet = cluster.fingerprint.length > 8
    ? `${cluster.fingerprint.slice(0, 8)}...`
    : cluster.fingerprint;
  const [, ...supportingEvidence] = evidence;
  const secondaryEvidence = supportingEvidence.filter((item) => {
    const normalized = item.toLowerCase();
    if (cluster.error_type && normalized.includes(cluster.error_type.toLowerCase())) return false;
    if (normalized.includes('same failure signature')) return false;
    if (normalized.includes('identical failure signature')) return false;
    return true;
  });
  const impactedTestsGridClasses = tests.length > 9
    ? 'mt-3 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-flow-col sm:grid-rows-3 sm:grid-cols-4'
    : 'mt-3 grid gap-1 sm:grid-cols-2 lg:grid-cols-3';

  const runsLabel = cluster.window_size
    ? `${cluster.affected_runs}/${cluster.window_size}`
    : String(cluster.affected_runs);

  return (
    <div
      id={`incident-${cluster.fingerprint}`}
      className={[
        'rounded-2xl border border-border-default bg-surface overflow-hidden transition-[box-shadow] duration-700',
        highlighted ? 'ring-2 ring-warning/50 shadow-[0_0_0_4px_rgb(245_158_11_/_0.12)]' : 'shadow-sm',
      ].join(' ')}
    >
      {/* ── 1. HEADER ROW ──────────────────────────────────── */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full text-left px-5 py-3.5"
        aria-expanded={open}
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">

          {/* LEFT — title + badges + activity meta */}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start gap-2.5 md:gap-3">
              <span className="text-[0.98rem] font-semibold leading-tight tracking-[-0.02em] text-primary md:text-[1.05rem]">
                {cluster.error_type || cluster.category || 'Failure pattern'}
              </span>

              <Tooltip content={
                <div className="space-y-1 max-w-[210px]">
                  <p className="font-semibold text-primary text-[12px]">{sev.tooltipTitle}</p>
                  <p className="text-[11px] text-muted leading-relaxed">{sev.tooltipBody}</p>
                </div>
              }>
                <span className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-[1.1] cursor-default ${sev.text} ${sev.bg} ${sev.border}`}>
                  {sev.label}
                </span>
              </Tooltip>

              {scope > 1 && inc && <TrendBadge trend={inc.trend} />}
            </div>

            <p className="mt-1.5 max-w-[40rem] text-[13px] leading-5 text-secondary">
              {synthesisLine}
            </p>

            <div className="mt-1 flex items-center gap-1.5 text-[11px]">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-faint">
                <circle cx="12" cy="12" r="8"/>
                <path d="M12 7.5v5l3 2"/>
              </svg>
              <span>{activityMeta}</span>
            </div>
          </div>

          {/* RIGHT — 3 stat blocks + chevron */}
          <div className="flex items-stretch gap-1 shrink-0 self-start">
            {[
              { value: cluster.occurrence_count, label: 'Occurrences' },
              { value: cluster.affected_tests,   label: 'Tests impacted' },
              { value: runsLabel,                label: 'Seen in runs' },
            ].map(({ value, label }, i) => (
              <div key={label} className={`min-w-[72px] px-3 text-center ${i > 0 ? 'border-l border-border-default' : ''}`}>
                <p className="type-nums text-[1.45rem] font-semibold leading-none tracking-[-0.035em] text-primary">{value}</p>
                <p className="mt-0.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-muted">{label}</p>
              </div>
            ))}
            <div className="ml-1 flex items-center pl-2.5">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-faint">
                {open ? <polyline points="18 15 12 9 6 15"/> : <polyline points="6 9 12 15 18 9"/>}
              </svg>
            </div>
          </div>
        </div>
      </button>

      {/* ── EXPANDED CONTENT ──────────────────────────────── */}
      {open && (
        <div className="border-t border-border-default">

          {/* ── 2. ERROR BANNER ──────────────────────────── */}
          {cluster.message && (
            <div className="flex items-center gap-2.5 border-y border-[rgb(var(--danger-rgb)/0.2)] bg-[rgb(var(--danger-rgb)/0.08)] px-5 py-2 font-mono text-xs font-medium text-[rgb(var(--danger-rgb))]">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-[rgb(var(--danger-rgb))]">
                <circle cx="12" cy="12" r="9"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              <p className="leading-5">{cluster.message}</p>
            </div>
          )}

          {inc ? (
            <>
              {/* ── 3. ANALYSIS + ACTION ───────────────────── */}
              <div className="grid border-b border-border-default md:grid-cols-2">
                <div className="bg-[rgb(var(--info-rgb)/0.08)] px-5 py-3 md:border-r md:border-border-default">
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-muted">
                        <path d="M15.5 15.5L19 19"/>
                        <circle cx="10.5" cy="10.5" r="5.5"/>
                      </svg>
                      <p className="text-[0.95rem] font-semibold tracking-[-0.01em] text-primary">Probable Root Cause</p>
                    </div>
                    <span className={`inline-flex rounded-md border px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.08em] ${confidenceClasses}`}>
                      {correlationLabel}
                    </span>
                  </div>
                  <p className="text-[13px] leading-5 text-secondary">
                    {inc.probable_root_cause}
                  </p>
                </div>

                <div className="bg-[rgb(var(--success-rgb)/0.08)] px-5 py-3">
                  <div className="mb-2 flex items-center gap-2">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-success">
                      <path d="M4 7h10"/>
                      <path d="M4 12h14"/>
                      <path d="M4 17h8"/>
                      <path d="M18 7l2 2 3-4"/>
                    </svg>
                    <p className="text-[0.95rem] font-semibold tracking-[-0.01em] text-primary">Recommended Action</p>
                  </div>
                  {steps.length > 0 ? (
                    <ol className="mt-2 space-y-1.5 text-[13px] leading-5 text-secondary">
                      {steps.slice(0, 3).map((step, i) => (
                        <li key={i} className="flex gap-2">
                          <span className="font-medium text-success">{i + 1}.</span>
                          <span><EvidenceText text={step} /></span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-[13px] leading-5 text-secondary">No specific action recommended.</p>
                  )}
                </div>
              </div>

              {/* ── 4. SUITES + TESTS ─────────────────────── */}
              <div className="px-5 py-3">
                {suites.length > 0 && (
                  <div>
                    <p className="mb-2 text-[0.95rem] font-semibold tracking-[-0.01em] text-primary">
                      Affected Suites <span className="text-muted">({suites.length})</span>
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {suites.map(s => (
                        <span key={s} className="inline-flex items-center rounded-full border border-[rgb(79_70_229_/_0.08)] bg-[rgb(79_70_229_/_0.04)] px-2.5 py-1 text-[11px] font-medium text-secondary">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {tests.length > 0 && (
                  <div className={suites.length > 0 ? 'mt-3' : ''}>
                    <p className="mb-2 text-[0.95rem] font-semibold tracking-[-0.01em] text-primary">
                      Impacted Tests <span className="text-muted">({tests.length})</span>
                    </p>
                    <div className={impactedTestsGridClasses}>
                      {tests.map(t => (
                        <div
                          key={t}
                          className="rounded-lg bg-surface-subtle px-2 py-1.5"
                        >
                          <span className="font-mono text-sm text-primary">{t.endsWith('()') ? t : `${t}()`}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="border-t border-border-default px-5 py-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-muted">
                      <path d="M8 6h12" />
                      <path d="M8 12h12" />
                      <path d="M8 18h12" />
                      <path d="M4 6h.01" />
                      <path d="M4 12h.01" />
                      <path d="M4 18h.01" />
                    </svg>
                    <p className="text-[0.95rem] font-semibold tracking-[-0.01em] text-primary">Stack Trace</p>
                  </div>
                  {inc.representative_stack_trace && (
                    <CopyButton text={inc.representative_stack_trace} label="Copy trace" />
                  )}
                </div>
                {inc.representative_stack_trace ? (
                  <pre className="qalens-code-block max-h-48 overflow-x-auto overflow-y-auto whitespace-pre p-3 font-mono text-xs leading-relaxed text-muted">
                    {inc.representative_stack_trace}
                  </pre>
                ) : (
                  <p className="text-[13px] leading-5 text-muted">No stack trace available.</p>
                )}
              </div>

              {/* ── 5. EVIDENCE FOOTER ────────────────────── */}
              {evidence.length > 0 && (
                <div className="border-t border-border-default bg-surface-subtle px-5 py-5 md:px-6">
                  <div className="mb-2.5 flex items-center gap-2">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-muted">
                      <path d="M4 5h16v14H4z"/>
                      <path d="M8 9h8"/>
                      <path d="M8 13h5"/>
                      <path d="M7 5v14"/>
                    </svg>
                    <p className="text-[0.95rem] font-semibold tracking-[-0.01em] text-primary">Evidence &amp; Correlation</p>
                  </div>
                  <ul className="space-y-2.5 text-[13px] leading-6 text-secondary">
                    <li className="flex gap-2">
                      <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted" />
                      <span>
                        <span className="font-medium text-primary">Strong signal:</span>{' '}
                        {cluster.affected_tests} test{cluster.affected_tests === 1 ? '' : 's'} share the same failure signature{' '}
                        <code className="rounded bg-surface px-1.5 py-0.5 text-xs text-secondary">
                          {signatureSnippet}
                        </code>
                      </span>
                    </li>
                    {cluster.error_type && (
                      <li className="flex gap-2">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-faint" />
                        <span>
                          All failures raise{' '}
                          <code className="rounded bg-surface px-1.5 py-0.5 text-xs text-secondary">
                            {cluster.error_type}
                          </code>
                        </span>
                      </li>
                    )}
                    {secondaryEvidence.slice(0, 2).map((e, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-faint" />
                        <span><EvidenceText text={e} /></span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <div className="px-5 py-5 text-sm text-muted md:px-6">
              No incident analysis available for this pattern yet.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// IncidentsPanel
// ─────────────────────────────────────────────────────────────

export function IncidentsPanel() {
  const { currentProject } = useProject();

  const [activeMode,        setActiveMode]        = useState<FailureMode>('incidents');
  const [highlightedId,     setHighlightedId]     = useState<string | null>(null);
  const [incidentTypeFilter,setIncidentTypeFilter]= useState<string>('all');
  const [viewMode,          setViewMode]          = useState<ViewMode>('window');
  const [incidentScope,     setIncidentScope]     = useState(5);
  const [runs,              setRuns]              = useState<ApiRun[]>([]);
  const [selectedRunId,     setSelectedRunId]     = useState<string>('');
  const [incidents,         setIncidents]         = useState<AggregatedIncident[]>([]);
  const [failureGroups,     setFailureGroups]     = useState<ApiFailureGroup[]>([]);
  const [runsLoading,       setRunsLoading]       = useState(true);
  const [incidentsLoading,  setIncidentsLoading]  = useState(false);
  const [runsError,         setRunsError]         = useState<string | null>(null);
  const [incidentsError,    setIncidentsError]    = useState<string | null>(null);

  // ── Fetch run list ─────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    setRunsLoading(true);
    setRunsError(null);
    setRuns([]);
    setSelectedRunId('');
    setIncidents([]);

    const params = new URLSearchParams({ limit: '500' });
    if (currentProject) params.set('project', currentProject);

    fetch(`/api/runs?${params}`)
      .then(r => r.ok ? r.json() as Promise<ApiRun[]> : Promise.reject(`API ${r.status}`))
      .then(data => {
        if (cancelled) return;
        setRuns(data);
        if (data.length > 0) setSelectedRunId(data[0].run_id); // auto-select latest
      })
      .catch(e => { if (!cancelled) setRunsError(String(e)); })
      .finally(() => { if (!cancelled) setRunsLoading(false); });

    return () => { cancelled = true; };
  }, [currentProject]);

  // ── Fetch incidents for selected window ───────────────────

  const fetchIncidents = useCallback((windowRuns: ApiRun[]) => {
    if (windowRuns.length === 0) { setIncidents([]); setFailureGroups([]); return; }

    let cancelled = false;
    setIncidentsLoading(true);
    setIncidentsError(null);
    setIncidents([]);
    setFailureGroups([]);

    const runIds = windowRuns.map(r => r.run_id);
    const groupParams = new URLSearchParams({ limit: '50', run_ids: runIds.join(',') });
    if (currentProject) groupParams.set('project', currentProject);

    Promise.all([
      Promise.all(
        windowRuns.map(run =>
          fetch(`/api/runs/${run.run_id}/incidents`)
            .then(r => r.ok ? r.json() as Promise<ApiIncident[]> : Promise.reject(`API ${r.status}`))
            .then(data => data.map(incident => ({ incident, run }))),
        ),
      ).then(results => aggregateIncidents(results.flat(), windowRuns)),
      fetch(`/api/failure-groups?${groupParams}`)
        .then(r => r.ok ? r.json() as Promise<ApiFailureGroup[]> : Promise.reject(`API ${r.status}`)),
    ])
      .then(([aggregated, groups]) => {
        if (!cancelled) { setIncidents(aggregated); setFailureGroups(groups); }
      })
      .catch(e => { if (!cancelled) setIncidentsError(String(e)); })
      .finally(() => { if (!cancelled) setIncidentsLoading(false); });

    return () => { cancelled = true; };
  }, [currentProject]);

  const selectedRun = useMemo(
    () => runs.find(run => run.run_id === selectedRunId) ?? runs[0] ?? null,
    [runs, selectedRunId],
  );

  const selectedRunIndex = useMemo(
    () => selectedRun ? Math.max(0, runs.findIndex(run => run.run_id === selectedRun.run_id)) : -1,
    [runs, selectedRun],
  );

  const availableWindowSize = selectedRunIndex >= 0 ? runs.length - selectedRunIndex : 0;

  const scopedRuns = useMemo(() => {
    if (!selectedRun) return [];
    const windowSize = viewMode === 'single' ? 1 : incidentScope;
    return runs.slice(selectedRunIndex, selectedRunIndex + windowSize);
  }, [runs, selectedRun, selectedRunIndex, viewMode, incidentScope]);

  const scopedRunIds = useMemo(
    () => scopedRuns.map(run => run.run_id),
    [scopedRuns],
  );

  const enrichedClusters = useMemo(
    () => mergeGroupsWithIncidents(failureGroups, incidents),
    [failureGroups, incidents],
  );

  const incidentTypeOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const cluster of enrichedClusters) {
      const label = cluster.error_type || cluster.category || 'Failure pattern';
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }

    return [
      { value: 'all', label: `All incident types (${enrichedClusters.length})` },
      ...[...counts.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([label, count]) => ({
          value: label,
          label: `${label} (${count})`,
        })),
    ];
  }, [enrichedClusters]);

  const filteredClusters = useMemo(
    () => incidentTypeFilter === 'all'
      ? enrichedClusters
      : enrichedClusters.filter(cluster => (cluster.error_type || cluster.category || 'Failure pattern') === incidentTypeFilter),
    [enrichedClusters, incidentTypeFilter],
  );

  const timelineRuns = useMemo(
    () => [...runs].sort((a, b) => a.run_sequence - b.run_sequence),
    [runs],
  );

  useEffect(() => {
    const windowRuns = scopedRuns;
    if (windowRuns.length > 0) {
      fetchIncidents(windowRuns);
    }
  }, [scopedRuns, fetchIncidents]);

  useEffect(() => {
    if (!incidentTypeOptions.some(option => option.value === incidentTypeFilter)) {
      setIncidentTypeFilter('all');
    }
  }, [incidentTypeFilter, incidentTypeOptions]);

  const effectiveScope = viewMode === 'single' ? 1 : incidentScope;
  const pageMeta = activeMode === 'incidents'
    ? `${filteredClusters.length} active cluster${filteredClusters.length !== 1 ? 's' : ''} · ${viewMode === 'single' ? 'Single run' : scopeLabel(effectiveScope)}`
    : `Insights · ${viewMode === 'single' ? 'Single run' : scopeLabel(effectiveScope)}`;

  const windowRangeLabel = runRangeLabel(scopedRuns);
  // Intelligence signal: headline + supporting detail derived from real incident data
  const { insightHeadline, insightDetail, insightTone } = (() => {
    if (incidents.length === 0) return { insightHeadline: null, insightDetail: null, insightTone: null };

    const worseningCount = incidents.filter(i => i.trend === 'worsening').length;
    const newCount       = incidents.filter(i => i.trend === 'new').length;
    const stableCount    = incidents.filter(i => i.trend === 'stable').length;
    const reducingCount  = incidents.filter(i => i.trend === 'reducing').length;
    const critHighCount  = incidents.filter(i => i.severity === 'critical' || i.severity === 'high').length;
    const runCount       = scopedRuns.length;

    // Normalise component names: strip trailing "Tests", "Test", "Services", etc.
    const cleanArea = (name: string) =>
      name.replace(/\s*(Tests?|Services?|Module|Component|Suite)$/i, '').trim();

    const allComponents = incidents.flatMap(i => i.components ?? []);
    const componentFreq = allComponents.reduce<Record<string, number>>((acc, c) => {
      const key = cleanArea(c);
      if (key) acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {});
    const topAreas = Object.entries(componentFreq)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([c]) => c);

    const areaClause = topAreas.length > 0
      ? `Primarily in ${topAreas.join(' and ')} flows — `
      : '';

    // Priority 1: worsening — red signal
    if (worseningCount > 0 && worseningCount >= newCount) {
      return {
        insightHeadline: 'Instability is rising',
        insightDetail: `${areaClause}${worseningCount} cluster${worseningCount !== 1 ? 's are' : ' is'} intensifying across the last ${runCount} run${runCount !== 1 ? 's' : ''}, driving ongoing failures.`,
        insightTone: 'danger' as const,
      };
    }

    // Priority 2: new patterns — amber signal
    if (newCount > 0) {
      return {
        insightHeadline: 'New failure patterns are emerging',
        insightDetail: `${areaClause}${newCount} new cluster${newCount !== 1 ? 's' : ''} surfaced in the last ${runCount} run${runCount !== 1 ? 's' : ''}, contributing to recent instability.`,
        insightTone: 'warning' as const,
      };
    }

    // Priority 3: critical/high severity — amber signal
    if (critHighCount > 0) {
      return {
        insightHeadline: 'High-severity failures need attention',
        insightDetail: `${areaClause}${critHighCount} critical or high-severity cluster${critHighCount !== 1 ? 's' : ''} active across the last ${runCount} run${runCount !== 1 ? 's' : ''}.`,
        insightTone: 'warning' as const,
      };
    }

    // Priority 4: all stable or reducing — green signal
    if (stableCount + reducingCount === incidents.length) {
      const allReducing = reducingCount === incidents.length;
      return {
        insightHeadline: allReducing ? 'Impact is shrinking across the board' : 'No new activity — failures holding steady',
        insightDetail: `${areaClause}${incidents.length} known cluster${incidents.length !== 1 ? 's have' : ' has'} persisted across the last ${runCount} run${runCount !== 1 ? 's' : ''} without spreading.`,
        insightTone: 'success' as const,
      };
    }

    // Fallback
    return {
      insightHeadline: 'Failures are active across recent runs',
      insightDetail: `${areaClause}${incidents.length} cluster${incidents.length !== 1 ? 's' : ''} across the last ${runCount} run${runCount !== 1 ? 's' : ''} — monitor for signs of spread.`,
      insightTone: 'warning' as const,
    };
  })();

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="qalens-page">

      {/* Page header */}
      <PageHeader
        tier="compact"
        kicker="Failure Intelligence"
        title={activeMode === 'incidents' ? 'Incidents' : 'Insights'}
        icon="🚨"
        meta={!runsLoading && selectedRunId ? pageMeta : 'Status investigation'}
      />

      <section className="space-y-5 rounded-[1.5rem] bg-surface p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03),0_18px_45px_rgba(15,23,42,0.035)]">
        {/* Shared controls */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="type-input-label shrink-0">View</label>
            <div className="qalens-toolbar-segment">
              {([
                { id: 'single', label: 'Single Run' },
                { id: 'window', label: 'Window Analysis' },
              ] as const).map(mode => (
                <button
                  key={mode.id}
                  onClick={() => setViewMode(mode.id)}
                  className={[
                    'qalens-segment-button',
                    viewMode === mode.id ? 'qalens-segment-button-active' : '',
                  ].join(' ')}
                >
                  {mode.label}
                </button>
              ))}
            </div>

            {viewMode === 'single' && (
              <>
                <label className="type-input-label shrink-0">Run</label>
                {runsError ? (
                  <span className="text-sm text-red-400">{runsError}</span>
                ) : (
                  <Dropdown
                    value={selectedRunId}
                    onChange={setSelectedRunId}
                    disabled={runsLoading || runs.length === 0}
                    triggerClassName="min-w-[240px] px-3.5 text-sm disabled:opacity-40"
                    options={
                      runsLoading
                        ? [{ value: '', label: 'Loading runs...', disabled: true }]
                        : runs.map(run => ({
                            value: run.run_id,
                            label: `#${run.run_sequence}${run.started_at ? ` — ${formatTs(run.started_at)}` : ''}`,
                          }))
                    }
                  />
                )}
              </>
            )}

            {viewMode === 'window' && (
              <>
                <label className="type-input-label shrink-0">
                  Scope
                </label>
                <Dropdown
                  value={String(incidentScope)}
                  onChange={value => setIncidentScope(Number(value))}
                  disabled={runsLoading || runs.length === 0}
                  triggerClassName="min-w-[150px] px-3.5 text-sm disabled:opacity-40"
                  options={
                    runsLoading
                      ? [{ value: '', label: 'Loading scopes...', disabled: true }]
                      : INCIDENT_SCOPE_OPTIONS.map(option => ({
                            value: String(option),
                            label: scopeLabel(option),
                            disabled: availableWindowSize < option,
                          }))
                  }
                />
              </>
            )}
          </div>
        </div>

        {viewMode === 'window' && (
          <RunTimelineStrip
            runs={timelineRuns}
            selectedRunId={selectedRunId}
            scopeSize={effectiveScope}
            mode={viewMode}
          />
        )}
      </section>

      {/* Mode switch */}
      <div className="qalens-toolbar-segment mt-2 w-fit">
        {([
          { id: 'incidents',   label: 'Incidents' },
          { id: 'failures',    label: 'Insights' },
        ] as const).map(mode => (
          <button
            key={mode.id}
            onClick={() => setActiveMode(mode.id)}
            className={[
              'qalens-segment-button',
              activeMode === mode.id ? 'qalens-segment-button-active' : '',
            ].join(' ')}
          >
            {mode.label}
          </button>
        ))}
      </div>

      {/* Stat cards */}
      {activeMode === 'incidents' && !incidentsLoading && !incidentsError && enrichedClusters.length > 0 && (
        <StatCards incidents={incidents} scope={effectiveScope} />
      )}

      {/* Loading */}
      {activeMode === 'incidents' && incidentsLoading && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-14 rounded-xl bg-surface-subtle" />
          ))}
        </div>
      )}

      {/* Error */}
      {activeMode === 'incidents' && incidentsError && !incidentsLoading && (
        <div className="qalens-error-banner">
          <span>⚠️</span>
          <span>Failed to load incidents: {incidentsError}</span>
        </div>
      )}

      {/* Empty state */}
      {activeMode === 'incidents' && !incidentsLoading && !incidentsError && runs.length > 0 && enrichedClusters.length === 0 && (
        <div id="incident-clusters" className="qalens-empty-state">
          <div className="qalens-empty-icon">✅</div>
          <p className="type-empty-title">
            {viewMode === 'single' ? 'This run is clean' : `No recurring incident clusters detected in ${windowRangeLabel}`}
          </p>
          <p className="type-empty-subtitle max-w-xs">
            {viewMode === 'single'
              ? 'No failure clusters were found for the selected run.'
              : 'The selected window has no grouped root-cause clusters to triage.'}
          </p>
        </div>
      )}

      {/* No run selected */}
      {activeMode === 'incidents' && !incidentsLoading && !incidentsError && runs.length === 0 && !runsLoading && (
        <div className="qalens-empty-state">
          <div className="qalens-empty-icon">🔍</div>
          <p className="type-empty-title">Select a run above</p>
        </div>
      )}

      {/* Incident cards */}
      {activeMode === 'incidents' && !incidentsLoading && !incidentsError && enrichedClusters.length > 0 && (
        <section id="incident-clusters" className="space-y-3">
          {insightHeadline ? (
            <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
              <div
                style={{
                  borderLeft: `3px solid ${
                    insightTone === 'danger'  ? 'rgba(239,68,68,0.7)'   :
                    insightTone === 'warning' ? 'rgba(245,158,11,0.65)' :
                    insightTone === 'success' ? 'rgba(16,185,129,0.6)'  :
                    'var(--border-strong)'
                  }`,
                  paddingLeft: 12,
                  flex: '1 1 420px',
                }}
              >
                <p style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3, letterSpacing: '-0.01em', margin: 0 }}>
                  {insightHeadline}
                </p>
                {insightDetail && (
                  <p style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 3, lineHeight: 1.5, margin: '3px 0 0' }}>
                    {insightDetail}
                  </p>
                )}
              </div>
              <Dropdown
                value={incidentTypeFilter}
                onChange={setIncidentTypeFilter}
                options={incidentTypeOptions}
                align="right"
                hideChevron
                ariaLabel="Filter incident types"
                leftIcon={
                  <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
                    <path d="M2.5 4h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    <path d="M5 8h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    <path d="M6.5 12h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                }
                renderValue={(option) => (
                  <span className="truncate">
                    {incidentTypeFilter === 'all'
                      ? 'Filter incident type'
                      : option?.value ?? 'Filter incident type'}
                  </span>
                )}
                triggerClassName="min-h-[2.25rem] rounded-full border-border-default bg-surface px-3 py-1.5 text-sm font-medium text-secondary shadow-none"
                menuClassName="min-w-[260px]"
              />
            </div>
          ) : (
            <div className="mb-2 flex justify-end">
              <Dropdown
                value={incidentTypeFilter}
                onChange={setIncidentTypeFilter}
                options={incidentTypeOptions}
                align="right"
                hideChevron
                ariaLabel="Filter incident types"
                leftIcon={
                  <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
                    <path d="M2.5 4h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    <path d="M5 8h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    <path d="M6.5 12h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                }
                renderValue={(option) => (
                  <span className="truncate">
                    {incidentTypeFilter === 'all'
                      ? 'Filter incident type'
                      : option?.value ?? 'Filter incident type'}
                  </span>
                )}
                triggerClassName="min-h-[2.25rem] rounded-full border-border-default bg-surface px-3 py-1.5 text-sm font-medium text-secondary shadow-none"
                menuClassName="min-w-[260px]"
              />
            </div>
          )}
          {filteredClusters.length > 0 ? (
            filteredClusters.map(cluster => (
              <EnrichedClusterCard
                key={cluster.fingerprint}
                cluster={cluster}
                scope={effectiveScope}
                highlighted={highlightedId === cluster.fingerprint || highlightedId === cluster.incident?.incident_id}
              />
            ))
          ) : (
            <div className="qalens-empty-state">
              <div className="qalens-empty-icon">🔎</div>
              <p className="type-empty-title">No incident cards match this type</p>
              <p className="type-empty-subtitle max-w-sm">
                Clear the filter or pick another incident type to see matching clusters in this run window.
              </p>
            </div>
          )}
        </section>
      )}

      {activeMode === 'failures' && (
        <FailureFlakinessView
          incidents={incidents}
          runsWindow={effectiveScope}
          runIds={scopedRunIds}
          viewMode={viewMode}
          onOpenIncidents={(incidentId?: string) => {
            setActiveMode('incidents');
            if (incidentId) setHighlightedId(incidentId);
            setTimeout(() => {
              const target = incidentId
                ? document.getElementById(`incident-${incidentId}`)
                : document.getElementById('incident-clusters');
              target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 50);
            if (incidentId) setTimeout(() => setHighlightedId(null), 3000);
          }}
        />
      )}

    </div>
  );
}
