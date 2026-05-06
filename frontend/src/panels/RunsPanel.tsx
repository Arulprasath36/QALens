import { useState, useEffect, useMemo, useCallback, useRef, Fragment } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
import { Tooltip } from '../components/Tooltip';
import { useProject } from '../hooks/useProject';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

interface ApiRun {
  run_id:         string;
  project:        string | null;
  suite:          string | null;
  report_format:  string;
  environment:    string | null;
  branch:         string | null;
  build_number:   string | null;
  started_at:     number | null;
  finished_at:    number | null;
  total_ms:       number | null;
  ingested_at:    number | null;
  run_sequence:   number | null;
  total_tests:    number | null;
  passed_count:   number | null;
  failed_count:   number | null;
  skipped_count:  number | null;
}

interface ApiAttachment {
  name:          string | null;
  kind:          string | null;
  resolved_path: string | null;
}

interface ApiTestCase {
  tc_id:        string;
  run_id:       string;
  name:         string;
  canonical_name: string;
  status:       string;
  duration_ms:  number | null;
  suite:        string | null;
  feature:      string | null;
  story:        string | null;
  owner:        string | null;
  tags:         string[];
  is_retry:     boolean;
  retry_count:  number;
  error_type:   string | null;
  message:      string | null;
  stack_trace:  string | null;
  fingerprint:  string | null;
  failed_step:  string | null;
  attachments:  ApiAttachment[];
}

interface ApiIncident {
  incident_id:                string;
  run_id:                     string;
  title:                      string;
  severity:                   'critical' | 'high' | 'medium' | 'low';
  impacted_test_count:        number;
  impacted_tests:             string[];
  probable_root_cause:        string;
  confidence:                 'high' | 'medium' | 'low';
  root_cause_category:        string;
  evidence:                   string[];
  recommended_action:         string;
  signature:                  string | null;
  error_type:                 string | null;
  representative_message:     string | null;
  representative_stack_trace: string | null;
  components:                 string[];
}

// ─────────────────────────────────────────────────────────────
// Config / helpers
// ─────────────────────────────────────────────────────────────

const PAGE_SIZES = [10, 25, 50];
const INITIAL_RUN_LIMIT = 100;
const STATUS_BADGE: Record<string, string> = {
  passed: 'qara-badge-success',
  failed: 'qara-badge-danger',
  broken: 'qara-badge-danger',
  skipped: 'qara-badge-neutral',
};

function formatDate(ts: number | null): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function formatMs(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

function fmt(n: number | null): string {
  return n == null ? '—' : n.toLocaleString();
}

function pctLabel(value: number | null): string {
  return value == null ? '—' : `${value}%`;
}

function buildDonutSegments(items: Array<{ value: number; color: string }>) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (total <= 0) return [];
  let offset = 0;
  return items
    .filter(item => item.value > 0)
    .map(item => {
      const fraction = item.value / total;
      const segment = { ...item, fraction, offset };
      offset += fraction;
      return segment;
    });
}

function runHealthLabel(passRate: number | null, failed: number) {
  if (failed > 0 && passRate != null && passRate < 85) return 'Regressed';
  if (failed > 0) return 'Needs attention';
  if (passRate != null && passRate >= 95) return 'Healthy';
  return 'Stable';
}

function runHealthTone(passRate: number | null, failed: number) {
  if (failed > 0 && passRate != null && passRate < 85) return 'text-red-400';
  if (failed > 0) return 'text-amber-400';
  return 'text-green-400';
}

function StatusDonut({
  passed,
  failed,
  skipped,
}: {
  passed: number;
  failed: number;
  skipped: number;
}) {
  const total = passed + failed + skipped;
  const segments = buildDonutSegments([
    { value: passed,  color: '#22c55e' },
    { value: failed,  color: '#ef4444' },
    { value: skipped, color: '#94a3b8' },
  ]);
  const radius = 38;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="flex items-center gap-4">
      <svg width="112" height="112" viewBox="0 0 112 112" role="img" aria-label="Run status mix">
        <circle cx="56" cy="56" r={radius} fill="none" stroke="var(--border-subtle)" strokeWidth="13" />
        {segments.map((segment, index) => (
          <circle
            key={`${segment.color}-${index}`}
            cx="56"
            cy="56"
            r={radius}
            fill="none"
            stroke={segment.color}
            strokeWidth="13"
            strokeDasharray={`${segment.fraction * circumference} ${circumference}`}
            strokeDashoffset={-segment.offset * circumference}
            strokeLinecap="round"
            transform="rotate(-90 56 56)"
          />
        ))}
        <text x="56" y="53" textAnchor="middle" className="fill-slate-950 text-[18px] font-bold dark:fill-slate-50">
          {total}
        </text>
        <text x="56" y="70" textAnchor="middle" className="fill-slate-500 text-[10px] font-semibold uppercase tracking-[0.12em] dark:fill-slate-400">
          tests
        </text>
      </svg>
      <div className="space-y-2 text-sm">
        {[
          ['Passed', passed, 'bg-green-400'],
          ['Failed', failed, 'bg-red-400'],
          ['Skipped', skipped, 'bg-slate-400'],
        ].map(([label, value, dot]) => (
          <div key={label} className="flex items-center gap-2 text-secondary">
            <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
            <span className="min-w-[58px]">{label}</span>
            <span className="font-semibold text-primary">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

type SuiteFailureRow = {
  suite: string;
  failures: number;
  total: number;
  owners: string[];
  failedTests: string[];
};

type RunInsightType = 'infra' | 'regression' | 'pattern' | 'hotspot' | 'flaky' | 'performance';
type RunInsightConfidence = 'high' | 'medium' | 'low';

type RunInsight = {
  id: string;
  priority: number;
  type: RunInsightType;
  title: string;
  summary: string;
  impact: string;
  confidence: RunInsightConfidence;
  evidence: string[];
  action: string;
  cta?: string;
  payload?: Record<string, unknown>;
};

const INSIGHT_PRIORITY: Record<RunInsightType, number> = {
  infra: 1,
  regression: 2,
  hotspot: 3,
  pattern: 4,
  flaky: 5,
  performance: 6,
};

function isFailureStatus(status: string) {
  return status === 'failed' || status === 'broken';
}

function isPreviousFailureCandidate(candidate: ApiRun, current: ApiRun) {
  if (candidate.run_id === current.run_id) return false;
  if (current.project && candidate.project && current.project !== candidate.project) return false;
  if (current.branch && candidate.branch && current.branch !== candidate.branch) return false;
  if (current.environment && candidate.environment && current.environment !== candidate.environment) return false;
  if (current.report_format && candidate.report_format && current.report_format !== candidate.report_format) return false;
  if (current.run_sequence != null && candidate.run_sequence != null) {
    return candidate.run_sequence < current.run_sequence;
  }
  if (current.started_at != null && candidate.started_at != null) {
    return candidate.started_at < current.started_at;
  }
  return false;
}

function runSortValue(run: ApiRun) {
  return run.run_sequence ?? run.started_at ?? 0;
}

function testKey(test: ApiTestCase) {
  return test.canonical_name || test.name;
}

function sentenceList(items: string[], max = 3) {
  const visible = items.filter(Boolean).slice(0, max);
  if (visible.length === 0) return '';
  return visible.join(', ');
}

function suiteRiskTier(failureRate: number): 'Critical' | 'Elevated' | 'Watch' {
  if (failureRate >= 70) return 'Critical';
  if (failureRate >= 40) return 'Elevated';
  return 'Watch';
}

function suiteRiskClasses(tier: 'Critical' | 'Elevated' | 'Watch') {
  if (tier === 'Critical') {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300';
  }
  if (tier === 'Elevated') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300';
  }
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';
}

function suiteHeroClasses(tier: 'Critical' | 'Elevated' | 'Watch') {
  if (tier === 'Critical') {
    return 'border-red-200 bg-red-50/70 dark:border-red-500/25 dark:bg-red-500/[0.08]';
  }
  if (tier === 'Elevated') {
    return 'border-amber-200 bg-amber-50/70 dark:border-amber-500/25 dark:bg-amber-500/[0.08]';
  }
  return 'border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-900/70';
}

function SuiteFailureHotspots({
  rows,
  totalFailures,
  onSuiteSelect,
}: {
  rows: SuiteFailureRow[];
  totalFailures: number;
  onSuiteSelect?: (suiteName: string) => void;
}) {
  const topRows = rows.slice(0, 5);
  const primary = topRows[0] ?? null;
  const secondaryRows = topRows.slice(1);

  if (topRows.length === 0) {
    return (
      <div className="rounded-xl border border-border-subtle bg-subtle px-5 py-8 text-center">
        <p className="text-sm font-semibold text-primary">No suite hotspots</p>
        <p className="mt-2 text-sm text-muted">This run has no failing tests grouped by suite.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {primary && (() => {
        const failureRate = Math.round((primary.failures / Math.max(1, primary.total)) * 100);
        const failureShare = Math.round((primary.failures / Math.max(1, totalFailures)) * 100);
        const tier = suiteRiskTier(failureRate);
        const Wrapper = onSuiteSelect ? 'button' : 'div';
        return (
          <Wrapper
            type={onSuiteSelect ? 'button' : undefined}
            onClick={onSuiteSelect ? () => onSuiteSelect(primary.suite) : undefined}
            aria-label={onSuiteSelect ? `View failed tests in ${primary.suite}` : undefined}
            className={[
              'w-full rounded-xl border px-5 py-5 text-left transition-colors',
              suiteHeroClasses(tier),
              onSuiteSelect ? 'hover:border-info/40 hover:bg-info/[0.04]' : '',
            ].join(' ')}
          >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">Primary hotspot</p>
                <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${suiteRiskClasses(tier)}`}>
                  {tier}
                </span>
              </div>
              <h4 className="mt-2 truncate text-xl font-semibold text-primary">{primary.suite}</h4>
              <p className="mt-3 text-sm text-secondary">
                {primary.failures} of {totalFailures} run failure{totalFailures === 1 ? '' : 's'} live here.
              </p>
              <p className="mt-1.5 text-sm text-muted">
                {tier === 'Critical'
                  ? 'High failure rate and largest share of this run’s failures.'
                  : tier === 'Elevated'
                    ? 'Elevated failure rate with meaningful concentration in this run.'
                    : 'Worth watching because failures are grouped here.'}
              </p>
            </div>
            <div className="grid gap-2 sm:min-w-[330px] sm:grid-cols-3">
              <div className="rounded-lg border border-border-subtle bg-surface/80 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Failure rate</p>
                <p className="mt-1 text-xl font-semibold text-primary">{failureRate}%</p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface/80 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Failure share</p>
                <p className="mt-1 text-xl font-semibold text-primary">{failureShare}%</p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface/80 px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Failed tests</p>
                <p className="mt-1 text-xl font-semibold text-primary">{primary.failures}/{primary.total}</p>
              </div>
            </div>
          </div>
          {onSuiteSelect && (
            <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-info">
              View tests
              <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
                <path d="M5 3.5 8.5 7 5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          )}
          </Wrapper>
        );
      })()}

      {secondaryRows.length > 0 && (
        <div className="space-y-2">
        {secondaryRows.map((row, index) => {
          const failureRate = Math.round((row.failures / Math.max(1, row.total)) * 100);
          const share = Math.round((row.failures / Math.max(1, totalFailures)) * 100);
          const tier = suiteRiskTier(failureRate);
          const barClass =
            tier === 'Critical'
              ? 'bg-red-400'
              : tier === 'Elevated'
                ? 'bg-amber-400'
                : 'bg-slate-400';
          const Wrapper = onSuiteSelect ? 'button' : 'div';
          return (
            <Wrapper
              key={row.suite}
              type={onSuiteSelect ? 'button' : undefined}
              onClick={onSuiteSelect ? () => onSuiteSelect(row.suite) : undefined}
              aria-label={onSuiteSelect ? `View failed tests in ${row.suite}` : undefined}
              className={[
                'grid w-full gap-3 rounded-xl border border-border-subtle bg-subtle px-4 py-3 text-left transition-colors lg:grid-cols-[40px_minmax(0,1fr)_150px_90px_auto] lg:items-center',
                onSuiteSelect ? 'hover:border-info/30 hover:bg-info/[0.04]' : '',
              ].join(' ')}
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-subtle bg-surface text-sm font-semibold text-muted">
                {index + 2}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-semibold text-primary">{row.suite}</p>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${suiteRiskClasses(tier)}`}>
                    {tier}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted">
                  {row.failures} failed · {row.total} total · {share}% of failures
                </p>
                <p className="mt-1 truncate text-xs text-muted">
                  {row.failedTests.slice(0, 2).join(', ') || 'No failed test names available'}
                </p>
              </div>
              <div className="space-y-1.5">
                <div className="h-2 overflow-hidden rounded-full bg-surface">
                  <div className={`h-full rounded-full ${barClass}`} style={{ width: `${Math.max(6, failureRate)}%` }} />
                </div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Failure rate</p>
              </div>
              <div className="text-right text-sm font-semibold text-primary">
                {failureRate}%
              </div>
              {onSuiteSelect && (
                <span className="inline-flex items-center justify-end gap-1 text-xs font-medium text-info">
                  View tests
                  <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
                    <path d="M5 3.5 8.5 7 5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </span>
              )}
            </Wrapper>
          );
        })}
        </div>
      )}
    </div>
  );
}

function confidenceClasses(confidence: RunInsightConfidence) {
  if (confidence === 'high') return 'border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300';
  if (confidence === 'medium') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300';
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';
}

function insightSeverityClasses(type: RunInsightType, isTopPriority: boolean) {
  const cardBase = isTopPriority
    ? {
        infra: 'border-red-200 bg-red-50/40 hover:border-red-300 dark:border-red-500/25 dark:bg-red-500/[0.07] dark:hover:border-red-500/40',
        regression: 'border-amber-200 bg-amber-50/45 hover:border-amber-300 dark:border-amber-500/25 dark:bg-amber-500/[0.07] dark:hover:border-amber-500/40',
        hotspot: 'border-orange-200 bg-orange-50/40 hover:border-orange-300 dark:border-orange-500/25 dark:bg-orange-500/[0.07] dark:hover:border-orange-500/40',
        pattern: 'border-violet-200 bg-violet-50/35 hover:border-violet-300 dark:border-violet-500/25 dark:bg-violet-500/[0.07] dark:hover:border-violet-500/40',
        flaky: 'border-yellow-200 bg-yellow-50/35 hover:border-yellow-300 dark:border-yellow-500/25 dark:bg-yellow-500/[0.07] dark:hover:border-yellow-500/40',
        performance: 'border-blue-200 bg-blue-50/35 hover:border-blue-300 dark:border-blue-500/25 dark:bg-blue-500/[0.07] dark:hover:border-blue-500/40',
      }
    : {
        infra: 'border-border-subtle bg-surface hover:border-red-200 dark:hover:border-red-500/30',
        regression: 'border-border-subtle bg-surface hover:border-amber-200 dark:hover:border-amber-500/30',
        hotspot: 'border-border-subtle bg-surface hover:border-orange-200 dark:hover:border-orange-500/30',
        pattern: 'border-border-subtle bg-surface hover:border-violet-200 dark:hover:border-violet-500/30',
        flaky: 'border-border-subtle bg-surface hover:border-yellow-200 dark:hover:border-yellow-500/30',
        performance: 'border-border-subtle bg-surface hover:border-blue-200 dark:hover:border-blue-500/30',
      };

  if (type === 'infra') {
    return {
      card: cardBase.infra,
      rail: 'bg-red-400',
      number: 'border-red-200 bg-red-100 text-red-700 dark:border-red-500/30 dark:bg-red-500/15 dark:text-red-200',
    };
  }
  if (type === 'regression') {
    return {
      card: cardBase.regression,
      rail: 'bg-amber-400',
      number: 'border-amber-200 bg-amber-100 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-200',
    };
  }
  if (type === 'hotspot') {
    return {
      card: cardBase.hotspot,
      rail: 'bg-orange-400',
      number: 'border-orange-200 bg-orange-100 text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/15 dark:text-orange-200',
    };
  }
  if (type === 'pattern') {
    return {
      card: cardBase.pattern,
      rail: 'bg-violet-400',
      number: 'border-violet-200 bg-violet-100 text-violet-700 dark:border-violet-500/30 dark:bg-violet-500/15 dark:text-violet-200',
    };
  }
  if (type === 'flaky') {
    return {
      card: cardBase.flaky,
      rail: 'bg-yellow-400',
      number: 'border-yellow-200 bg-yellow-100 text-yellow-700 dark:border-yellow-500/30 dark:bg-yellow-500/15 dark:text-yellow-200',
    };
  }
  return {
    card: cardBase.performance,
    rail: 'bg-blue-400',
    number: 'border-blue-200 bg-blue-100 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/15 dark:text-blue-200',
  };
}

function RunInsightsPanel({
  insights,
  regressionNote,
  onInsightAction,
}: {
  insights: RunInsight[];
  regressionNote?: string;
  onInsightAction?: (type: string, payload: Record<string, unknown>) => void;
}) {
  const [expandedEvidence, setExpandedEvidence] = useState<Record<string, boolean>>({});

  return (
    <section className="rounded-2xl border border-border-default bg-surface px-5 py-5 shadow-sm">
      <div>
        <p className="type-metric-label">Run insights</p>
        <h3 className="mt-2 text-lg font-semibold text-primary">Next best checks</h3>
        <p className="mt-1 text-sm text-muted">Deterministic signals from incidents, suite concentration, and comparable run history.</p>
      </div>

      {insights.length === 0 ? (
        <div className="mt-5 rounded-xl border border-border-subtle bg-subtle px-4 py-6 text-center">
          <p className="text-sm font-semibold text-primary">No major issues detected</p>
          <p className="mt-2 text-sm text-muted">This run looks stable. No high-risk patterns were found.</p>
          {regressionNote && <p className="mt-3 text-xs text-muted">{regressionNote}</p>}
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {insights.map((insight, index) => {
            const isActionable = Boolean(onInsightAction && insight.cta);
            const evidenceOpen = Boolean(expandedEvidence[insight.id]);
            const severity = insightSeverityClasses(insight.type, index === 0);
            return (
              <div
                key={insight.id}
                className={[
                  'relative w-full overflow-hidden rounded-xl border px-4 py-4 text-left transition-colors',
                  severity.card,
                ].join(' ')}
              >
                <span className={`absolute inset-y-0 left-0 w-1 ${severity.rail}`} aria-hidden="true" />
                <div className="flex items-start gap-3">
                  <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-xs font-semibold ${severity.number}`}>
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-primary">{insight.title}</p>
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${confidenceClasses(insight.confidence)}`}>
                        {insight.confidence}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-5 text-secondary">{insight.summary}</p>
                    <p className="mt-1 text-xs font-medium text-muted">
                      <span className="font-semibold text-secondary">Impact:</span> {insight.impact}
                    </p>
                    <p className="mt-3 text-xs leading-5 text-secondary">
                      <span className="font-semibold text-primary">Recommended action:</span> {insight.action}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {isActionable && (
                        <button
                          type="button"
                          onClick={() => onInsightAction?.(insight.type, insight.payload ?? {})}
                          aria-label={`${insight.cta}: ${insight.title}`}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-info/25 bg-info/[0.06] px-3 py-1.5 text-xs font-semibold text-info transition-colors hover:border-info/40 hover:bg-info/[0.1]"
                        >
                          {insight.cta}
                          <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
                            <path d="M5 3.5 8.5 7 5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </button>
                      )}
                      {insight.evidence.length > 0 && (
                        <button
                          type="button"
                          aria-expanded={evidenceOpen}
                          aria-label={`${evidenceOpen ? 'Hide' : 'Show'} details for ${insight.title}`}
                          onClick={() => setExpandedEvidence(current => ({
                            ...current,
                            [insight.id]: !current[insight.id],
                          }))}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface/70 px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-primary"
                        >
                          {evidenceOpen ? 'Hide details' : 'Show details'}
                          <svg className={`h-3.5 w-3.5 transition-transform ${evidenceOpen ? 'rotate-90' : ''}`} viewBox="0 0 14 14" fill="none" aria-hidden="true">
                            <path d="M5 3.5 8.5 7 5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </button>
                      )}
                    </div>
                    {evidenceOpen && insight.evidence.length > 0 && (
                      <ul className="mt-3 space-y-1.5 rounded-lg border border-border-subtle bg-surface/70 px-3 py-2">
                        {insight.evidence.map(item => (
                          <li key={item} className="flex gap-2 text-xs leading-5 text-muted">
                            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-current" />
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {regressionNote && <p className="px-1 text-xs text-muted">{regressionNote}</p>}
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Test case row (expandable)
// ─────────────────────────────────────────────────────────────

function TestCaseRow({ tc }: { tc: ApiTestCase }) {
  const [open, setOpen] = useState(false);
  const statusBadge = STATUS_BADGE[tc.status] ?? 'qara-badge-neutral';
  const serveableAttachments = tc.attachments.filter(a => a.resolved_path);
  const hasDetail = !!(tc.message || tc.stack_trace || serveableAttachments.length);

  return (
    <>
      <tr
        className={`qara-table-row transition-colors ${hasDetail ? 'cursor-pointer' : ''}`}
        onClick={() => hasDetail && setOpen(o => !o)}
      >
        <td className="qara-table-cell">
          <div className="flex items-center gap-1.5">
            {hasDetail && (
              <svg className={`w-3 h-3 shrink-0 text-info transition-transform ${open ? 'rotate-90' : ''}`}
                   viewBox="0 0 12 12" fill="none">
                <path d="M4 3l3 3-3 3" stroke="currentColor" strokeWidth="1.5"
                      strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
            <Tooltip content={tc.name} className="block max-w-[280px]">
              <span className="type-td-primary block truncate">
                {tc.name}
              </span>
            </Tooltip>
          </div>
        </td>
        <td className="qara-table-cell">
          <span className={statusBadge}>
            {tc.status}
          </span>
        </td>
        <td className="qara-table-cell type-td-secondary truncate max-w-[140px]">
          {tc.suite ?? '—'}
        </td>
        <td className="qara-table-cell type-td-secondary">
          {tc.owner ?? '—'}
        </td>
        <td className="qara-table-cell type-td-num">
          {formatMs(tc.duration_ms)}
        </td>
        <td className="qara-table-cell type-td-secondary truncate max-w-[200px]">
          {tc.message ? tc.message.slice(0, 80) : '—'}
        </td>
      </tr>

      {open && hasDetail && (
        <tr className="qara-table-row" style={{ background: 'var(--bg-subtle)' }}>
          <td colSpan={6} className="px-8 py-5">
            {/* Meta grid */}
            {(tc.error_type || tc.failed_step || tc.feature || tc.story) && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-xs">
                {tc.error_type  && <div><span className="text-zinc-500">Error Type</span><div className="text-red-400 font-medium mt-0.5">{tc.error_type}</div></div>}
                {tc.failed_step && <div><span className="text-zinc-500">Failed Step</span><div className="text-zinc-300 mt-0.5">{tc.failed_step}</div></div>}
                {tc.feature     && <div><span className="text-zinc-500">Feature</span><div className="text-zinc-300 mt-0.5">{tc.feature}</div></div>}
                {tc.story       && <div><span className="text-zinc-500">Story</span><div className="text-zinc-300 mt-0.5">{tc.story}</div></div>}
              </div>
            )}

            {/* Message */}
            {tc.message && (
              <div className="mb-3">
                <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">
                  Message
                </p>
                <pre className="qara-code-block text-xs text-zinc-400
                                rounded-lg p-3 overflow-x-auto max-h-32 overflow-y-auto
                                whitespace-pre-wrap leading-relaxed font-mono">
                  {tc.message}
                </pre>
              </div>
            )}

            {/* Stack trace */}
            {tc.stack_trace ? (
              <div className="mb-3">
                <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">
                  Stack Trace
                </p>
                <pre className="qara-code-block text-xs text-zinc-500
                                rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto
                                whitespace-pre leading-relaxed font-mono">
                  {tc.stack_trace}
                </pre>
              </div>
            ) : null}

            {/* Attachments */}
            {serveableAttachments.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                  Attachments ({serveableAttachments.length})
                </p>
                <div className="flex flex-wrap gap-2">
                  {serveableAttachments.map((att, idx) => {
                    const origIdx = tc.attachments.indexOf(att);
                    const url = `/api/tests/${encodeURIComponent(tc.tc_id)}/attachment/${origIdx}`;
                    const isImg = att.kind === 'screenshot' || /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(att.name ?? '');
                    if (isImg) {
                      return (
                        <a key={idx} href={url} target="_blank" rel="noopener noreferrer">
                          <img src={url} alt={att.name ?? 'screenshot'} loading="lazy"
                               className="w-32 h-24 object-cover rounded-lg border border-zinc-700
                                          hover:border-zinc-500 transition-colors"
                          />
                        </a>
                      );
                    }
                    return (
                      <a key={idx} href={url} target="_blank" rel="noopener noreferrer"
                         className="qara-chip type-chip">
                        <span>📎</span>
                        {att.name ?? att.kind ?? 'file'}
                      </a>
                    );
                  })}
                </div>
              </div>
            )}

            {!tc.message && !tc.stack_trace && serveableAttachments.length === 0 && (
              <p className="text-xs text-zinc-600">
                No failure details extracted. Re-ingest with --force to refresh.
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Incident helpers (shared style with IncidentsPanel)
// ─────────────────────────────────────────────────────────────

const SEV_CONFIG = {
  critical: { label: 'Critical', text: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30',    dot: 'bg-red-400'    },
  high:     { label: 'High',     text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30', dot: 'bg-orange-400' },
  medium:   { label: 'Medium',   text: 'text-amber-400',  bg: 'bg-amber-500/10',  border: 'border-amber-500/30',  dot: 'bg-amber-400'  },
  low:      { label: 'Low',      text: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/30',  dot: 'bg-green-400'  },
} as const;

const CONF_LABEL: Record<string, string> = {
  high:   'High confidence',
  medium: 'Medium confidence',
  low:    'Low confidence',
};

function parseActionSteps(action: string): string[] {
  if (!action) return [];
  const numbered = action.match(/\d+\.\s+[^0-9]+?(?=\d+\.|$)/g);
  if (numbered && numbered.length >= 2) {
    return numbered.map(s => s.replace(/^\d+\.\s+/, '').trim()).filter(Boolean);
  }
  if (action.includes(';')) return action.split(';').map(s => s.trim()).filter(Boolean);
  return [action.trim()];
}

function EvidenceText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('`') && part.endsWith('`')
          ? <code key={i} className="px-1 py-0.5 rounded bg-zinc-700 text-zinc-200 text-xs font-mono">
              {part.slice(1, -1)}
            </code>
          : <Fragment key={i}>{part}</Fragment>
      )}
    </>
  );
}

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
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs
                 border border-zinc-700 text-zinc-400 hover:text-zinc-100
                 hover:border-zinc-500 transition-colors"
    >
      {copied ? <><span>✓</span> Copied</> : <><span>⎘</span> {label}</>}
    </button>
  );
}

function IncidentCard({ inc }: { inc: ApiIncident }) {
  const [open,      setOpen]      = useState(false);
  const [testsOpen, setTestsOpen] = useState(false);

  const sev   = SEV_CONFIG[inc.severity] ?? SEV_CONFIG.low;
  const sig8  = inc.signature ? inc.signature.slice(0, 8) : null;
  const steps = parseActionSteps(inc.recommended_action);

  return (
    <div className="rounded-xl border border-border-default bg-surface transition-colors">

      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left rounded-xl"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`shrink-0 inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full
                            text-xs font-semibold border ${sev.text} ${sev.bg} ${sev.border}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${sev.dot}`} />
            {sev.label}
          </span>
          <span className="text-sm font-medium text-primary truncate">{inc.title}</span>
          {sig8 && (
            <span className="shrink-0 text-xs text-muted font-mono">#{sig8}</span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-muted">
            {inc.impacted_test_count} test{inc.impacted_test_count !== 1 ? 's' : ''} affected
          </span>
          <svg className={`w-4 h-4 text-muted transition-transform ${open ? 'rotate-90' : ''}`}
               viewBox="0 0 16 16" fill="none">
            <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </button>

      {/* Body */}
      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-border-subtle pt-4">

          {/* Meta line */}
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>
              <span className="text-secondary font-medium">{inc.impacted_test_count}</span> tests affected
            </span>
            {inc.root_cause_category && (
              <>
                <span className="text-faint">·</span>
                <span className="capitalize">{inc.root_cause_category.replace(/_/g, ' ')}</span>
              </>
            )}
            <span className="text-faint">·</span>
            <span className={
              inc.confidence === 'high'   ? 'text-success' :
              inc.confidence === 'medium' ? 'text-warning' : 'text-muted'
            }>
              {CONF_LABEL[inc.confidence] ?? inc.confidence}
            </span>
          </div>

          {/* Root cause */}
          <div className="px-4 py-3 rounded-lg bg-subtle border border-border-subtle
                          text-sm text-secondary leading-relaxed">
            {inc.probable_root_cause}
          </div>

          {/* Evidence */}
          {inc.evidence?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">
                Why this is happening
              </p>
              <ul className="space-y-1.5">
                {inc.evidence.map((e, i) => (
                  <li key={i} className="flex gap-2 text-sm text-secondary">
                    <span className="text-faint mt-0.5 shrink-0">•</span>
                    <span><EvidenceText text={e} /></span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Affected areas */}
          {inc.components?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">
                Affected areas
              </p>
              <div className="flex flex-wrap gap-1.5">
                {inc.components.map(c => (
                  <span key={c} className="px-2.5 py-0.5 rounded-full text-xs border
                                           border-border-default bg-subtle text-secondary">
                    {c}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* What to do next */}
          {inc.recommended_action && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-muted uppercase tracking-wider">
                  What to do next
                </p>
                <CopyButton text={inc.recommended_action} />
              </div>
              <ol className="space-y-1.5 list-none">
                {steps.map((step, i) => (
                  <li key={i} className="flex gap-2.5 text-sm text-secondary">
                    <span className="shrink-0 w-5 h-5 rounded-full bg-subtle border
                                     border-border-default text-muted text-xs flex items-center
                                     justify-center font-medium mt-0.5">
                      {i + 1}
                    </span>
                    <span className="leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Impacted tests (collapsible) */}
          {inc.impacted_tests.length > 0 && (
            <div>
              <button
                onClick={() => setTestsOpen(o => !o)}
                className="flex items-center gap-1.5 text-xs text-muted
                           hover:text-secondary transition-colors"
              >
                <svg className={`w-3 h-3 transition-transform ${testsOpen ? 'rotate-90' : ''}`}
                     viewBox="0 0 12 12" fill="none">
                  <path d="M4 3l3 3-3 3" stroke="currentColor" strokeWidth="1.5"
                        strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                {testsOpen
                  ? 'Hide impacted tests'
                  : `Show ${inc.impacted_tests.length} impacted test${inc.impacted_tests.length !== 1 ? 's' : ''}`
                }
              </button>
              {testsOpen && (
                <ul className="mt-2 space-y-1 pl-4">
                  {inc.impacted_tests.map((name, i) => (
                    <li key={i} className="text-xs text-muted font-mono truncate">{name}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Stack trace */}
          {inc.representative_stack_trace && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-muted uppercase tracking-wider">
                  Stack Trace
                </p>
                <CopyButton text={inc.representative_stack_trace} label="Copy trace" />
              </div>
              <pre className="text-xs text-muted font-mono bg-subtle border
                              border-border-default rounded-lg p-3 overflow-x-auto max-h-48
                              overflow-y-auto whitespace-pre leading-relaxed">
                {inc.representative_stack_trace}
              </pre>
            </div>
          )}

        </div>
      )}
    </div>
  );
}

function IncidentsSection({ incidents }: { incidents: ApiIncident[] }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-xl border border-border-default bg-surface shadow-[0_10px_30px_rgba(15,23,42,0.04)]">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-semibold text-primary">
          ⚡ {incidents.length} Incident{incidents.length !== 1 ? 's' : ''} Detected
        </span>
        <svg className={`w-4 h-4 text-muted transition-transform ${open ? 'rotate-90' : ''}`}
             viewBox="0 0 16 16" fill="none">
          <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
      {open && (
        <div className="px-3 pb-3 border-t border-border-subtle bg-subtle/40">
          <div className="pt-2 space-y-2">
            {incidents.map(inc => (
              <IncidentCard key={inc.incident_id} inc={inc} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Run detail view
// ─────────────────────────────────────────────────────────────

function RunDetailView({
  run,
  runs,
  onSelectRun,
  onBack,
}: {
  run:         ApiRun;
  runs:        ApiRun[];
  onSelectRun: (runId: string) => void;
  onBack:      () => void;
}) {
  const [tests,     setTests]     = useState<ApiTestCase[]>([]);
  const [incidents, setIncidents] = useState<ApiIncident[]>([]);
  const [previousTests, setPreviousTests] = useState<ApiTestCase[] | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [incidentsLoading, setIncidentsLoading] = useState(false);
  const [error,     setError]     = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [suiteFilter, setSuiteFilter] = useState<string>('');
  const [fingerprintFilter, setFingerprintFilter] = useState<string>('');
  const [testNameFilter, setTestNameFilter] = useState<string[]>([]);
  const evidenceRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setIncidentsLoading(true);
    setError(null);
    setTests([]);
    setIncidents([]);

    fetch(`/api/runs/${run.run_id}/tests?include_details=false`)
      .then(r => r.ok ? r.json() as Promise<ApiTestCase[]> : Promise.reject(`API ${r.status}`))
      .then(tc => {
        if (cancelled) return;
        setTests(tc);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    fetch(`/api/runs/${run.run_id}/incidents`)
      .then(r => r.ok ? r.json() as Promise<ApiIncident[]> : Promise.reject(`API ${r.status}`))
      .then(inc => { if (!cancelled) setIncidents(inc); })
      .catch(() => { if (!cancelled) setIncidents([]); })
      .finally(() => { if (!cancelled) setIncidentsLoading(false); });

    return () => { cancelled = true; };
  }, [run.run_id]);

  const previousComparableRun = useMemo(() => {
    return runs
      .filter(candidate => isPreviousFailureCandidate(candidate, run))
      .sort((a, b) => runSortValue(b) - runSortValue(a))[0] ?? null;
  }, [runs, run]);

  useEffect(() => {
    let cancelled = false;
    setPreviousTests(null);
    if (!previousComparableRun) return () => { cancelled = true; };

    fetch(`/api/runs/${previousComparableRun.run_id}/tests?include_details=false`)
      .then(r => r.ok ? r.json() as Promise<ApiTestCase[]> : Promise.reject(`API ${r.status}`))
      .then(tc => { if (!cancelled) setPreviousTests(tc); })
      .catch(() => { if (!cancelled) setPreviousTests(null); });

    return () => { cancelled = true; };
  }, [previousComparableRun?.run_id]);

  const filtered = useMemo(() => {
    const suiteScoped = suiteFilter
      ? tests.filter(t => (t.suite || 'Unknown suite') === suiteFilter)
      : tests;
    const testNameSet = new Set(testNameFilter);
    const signalScoped = fingerprintFilter || testNameSet.size > 0
      ? suiteScoped.filter(t =>
          (fingerprintFilter && t.fingerprint === fingerprintFilter) ||
          testNameSet.has(t.name) ||
          testNameSet.has(t.canonical_name),
        )
      : suiteScoped;
    if (!statusFilter) return signalScoped;
    if (statusFilter === 'failed') return signalScoped.filter(t => isFailureStatus(t.status));
    if (statusFilter === 'slow') return signalScoped.filter(t => (t.duration_ms ?? 0) >= 5000);
    if (statusFilter === 'retry') return signalScoped.filter(t => t.is_retry || t.retry_count > 0);
    return signalScoped.filter(t => t.status === statusFilter);
  }, [tests, statusFilter, suiteFilter, fingerprintFilter, testNameFilter]);

  const passRate = run.total_tests ? Math.round((run.passed_count ?? 0) / run.total_tests * 100) : null;
  const failedCount = tests.filter(t => t.status === 'failed' || t.status === 'broken').length || (run.failed_count ?? 0);
  const passedCount = tests.filter(t => t.status === 'passed').length || (run.passed_count ?? 0);
  const skippedCount = tests.filter(t => t.status === 'skipped').length || (run.skipped_count ?? 0);
  const slowCount = tests.filter(t => (t.duration_ms ?? 0) >= 5000).length;
  const retryCount = tests.filter(t => t.is_retry || t.retry_count > 0).length;
  const healthLabel = runHealthLabel(passRate, failedCount);
  const healthTone = runHealthTone(passRate, failedCount);
  const topIncident = incidents[0] ?? null;
  const suiteFailures = useMemo(() => {
    const suites = new Map<string, { suite: string; failures: number; total: number; owners: Set<string>; failedTests: string[] }>();
    for (const test of tests) {
      const suite = test.suite || 'Unknown suite';
      const row = suites.get(suite) ?? { suite, failures: 0, total: 0, owners: new Set<string>(), failedTests: [] };
      row.total += 1;
      if (test.owner) row.owners.add(test.owner);
      if (test.status === 'failed' || test.status === 'broken') {
        row.failures += 1;
        row.failedTests.push(test.name);
      }
      suites.set(suite, row);
    }
    return [...suites.values()]
      .filter(row => row.failures > 0)
      .map(row => ({
        suite: row.suite,
        failures: row.failures,
        total: row.total,
        owners: [...row.owners].sort(),
        failedTests: row.failedTests,
      }))
      .sort((a, b) => b.failures - a.failures || b.total - a.total || a.suite.localeCompare(b.suite));
  }, [tests]);
  const totalSuiteFailures = suiteFailures.reduce((sum, row) => sum + row.failures, 0);
  const topSuite = suiteFailures[0] ?? null;
  const runComparison = useMemo(() => {
    if (!previousComparableRun || !previousTests) return null;
    const previousByName = new Map(previousTests.map(test => [testKey(test), test]));
    const newFailures = tests.filter(test => {
      if (!isFailureStatus(test.status)) return false;
      const previous = previousByName.get(testKey(test));
      return !previous || previous.status === 'passed' || previous.status === 'skipped';
    });
    const recovered = tests.filter(test => {
      const previous = previousByName.get(testKey(test));
      return test.status === 'passed' && previous && isFailureStatus(previous.status);
    });
    const persistentFailures = tests.filter(test => {
      const previous = previousByName.get(testKey(test));
      return isFailureStatus(test.status) && previous && isFailureStatus(previous.status);
    });
    const newlySkipped = tests.filter(test => {
      if (test.status !== 'skipped') return false;
      const previous = previousByName.get(testKey(test));
      return !previous || previous.status !== 'skipped';
    });
    return { newFailures, recovered, persistentFailures, newlySkipped };
  }, [previousComparableRun, previousTests, tests]);
  const runInsights = useMemo<RunInsight[]>(() => {
    const insights: RunInsight[] = [];
    const testByName = new Map<string, ApiTestCase>();
    for (const test of tests) {
      testByName.set(test.name, test);
      testByName.set(test.canonical_name, test);
    }

    const infraIncident = incidents.find(incident => incident.signature && incident.impacted_test_count >= 3);
    if (infraIncident) {
      const impactedSuites = new Set(
        infraIncident.impacted_tests
          .map(name => testByName.get(name)?.suite)
          .filter(Boolean) as string[],
      );
      const suiteCount = impactedSuites.size || infraIncident.components.length || 1;
      const primaryComponent = infraIncident.components[0]?.replace(/[_-]/g, ' ');
      const issueLabel = [primaryComponent, infraIncident.error_type]
        .filter(Boolean)
        .join(' ')
        .trim() || infraIncident.root_cause_category?.replace(/[_-]/g, ' ') || 'Shared failure signature';
      insights.push({
        id: `infra-${infraIncident.incident_id}`,
        priority: INSIGHT_PRIORITY.infra,
        type: 'infra',
        title: 'Infrastructure issue detected',
        summary: `${issueLabel} is breaking multiple tests.`,
        impact: `${infraIncident.impacted_test_count} tests · ${suiteCount} suite${suiteCount === 1 ? '' : 's'} affected`,
        confidence: 'high',
        evidence: [
          infraIncident.signature ? `Fingerprint ${infraIncident.signature.slice(0, 12)}` : '',
          sentenceList(infraIncident.impacted_tests, 3),
          impactedSuites.size > 0 ? `Impacted suites: ${sentenceList([...impactedSuites], 3)}` : '',
          infraIncident.representative_message || infraIncident.title,
        ].filter(Boolean),
        action: 'Fix the shared dependency before debugging individual tests.',
        cta: 'View tests',
        payload: {
          fingerprint: infraIncident.signature,
          testNames: infraIncident.impacted_tests,
        },
      });
    }

    if (previousComparableRun && runComparison && runComparison.newFailures.length > 0) {
      const impactedSuites = [...new Set(runComparison.newFailures.map(test => test.suite || 'Unknown suite'))];
      insights.push({
        id: `regression-${previousComparableRun.run_id}`,
        priority: INSIGHT_PRIORITY.regression,
        type: 'regression',
        title: `Regression: ${runComparison.newFailures.length} new failure${runComparison.newFailures.length === 1 ? '' : 's'}`,
        summary: `Compared to Run #${previousComparableRun.run_sequence ?? previousComparableRun.run_id.slice(0, 8)}.`,
        impact: `${runComparison.newFailures.length} new failure${runComparison.newFailures.length === 1 ? '' : 's'} · ${runComparison.recovered.length} recovered`,
        confidence: 'high',
        evidence: [
          `New failures: ${sentenceList(runComparison.newFailures.map(test => test.name), 3) || 'None'}`,
          `Impacted suites: ${sentenceList(impactedSuites, 3) || 'Unknown suite'}`,
          `Persistent failures: ${runComparison.persistentFailures.length}`,
          `Newly skipped: ${runComparison.newlySkipped.length}`,
          `Recovered: ${sentenceList(runComparison.recovered.map(test => test.name), 3) || 'None'}`,
        ],
        action: 'Compare with the previous comparable run to identify recent changes.',
        cta: `Compare with Run #${previousComparableRun.run_sequence ?? previousComparableRun.run_id.slice(0, 8)}`,
        payload: {
          previousRunId: previousComparableRun.run_id,
          currentRunId: run.run_id,
        },
      });
    }

    if (topSuite) {
      const failureShare = Math.round((topSuite.failures / Math.max(1, totalSuiteFailures)) * 100);
      if (failureShare > 20) {
        insights.push({
          id: `blast-radius-${topSuite.suite}`,
          priority: INSIGHT_PRIORITY.hotspot,
          type: 'hotspot',
          title: 'High-impact failure area',
          summary: `${topSuite.suite} contains the largest share of this run’s failures.`,
          impact: `${failureShare}% of failures originate here`,
          confidence: 'high',
          evidence: [
            `${topSuite.failures} failed test${topSuite.failures === 1 ? '' : 's'} in ${topSuite.suite}`,
            `${topSuite.total} total test${topSuite.total === 1 ? '' : 's'} in this suite`,
          ],
          action: 'Start triage in this suite before expanding to the rest of the run.',
          cta: 'View tests',
          payload: { suite: topSuite.suite },
        });
      }
    }

    if (incidents.length > 0 && incidents.length < failedCount) {
      const sizes = incidents
        .map(incident => incident.impacted_test_count)
        .sort((a, b) => b - a);
      insights.push({
        id: 'pattern-shared-clusters',
        priority: INSIGHT_PRIORITY.pattern,
        type: 'pattern',
        title: 'Failures share a common cause',
        summary: 'Several failed tests are failing for the same reason, so one fix may clear multiple failures.',
        impact: `${incidents.length} shared group${incidents.length === 1 ? '' : 's'} across ${failedCount} failed test${failedCount === 1 ? '' : 's'}`,
        confidence: 'medium',
        evidence: [
          `Largest group affects ${sizes[0] ?? 0} test${(sizes[0] ?? 0) === 1 ? '' : 's'}`,
          `Each number is one shared failure group: ${sizes.slice(0, 4).join(', ')} test${sizes.some(size => size !== 1) ? 's' : ''}`,
        ],
        action: 'Start with the largest shared failure group before debugging each test separately.',
        cta: 'Show failed',
        payload: { status: 'failed' },
      });
    }

    const retryTests = tests.filter(test => test.is_retry || test.retry_count > 0);
    if (retryTests.length > 0) {
      insights.push({
        id: 'flaky-retries',
        priority: INSIGHT_PRIORITY.flaky,
        type: 'flaky',
        title: 'Flaky behavior detected',
        summary: 'Tests show inconsistent retry behavior in this run.',
        impact: `${retryTests.length} test${retryTests.length === 1 ? '' : 's'} affected`,
        confidence: 'medium',
        evidence: [
          sentenceList(retryTests.map(test => test.name), 3),
          `Retry count signal from this run`,
        ],
        action: 'Stabilize or quarantine these tests before treating every failure as a product regression.',
        cta: 'View tests',
        payload: { status: 'retry' },
      });
    }

    if (previousTests) {
      const previousByName = new Map(previousTests.map(test => [testKey(test), test]));
      const durationSpikes = tests
        .map(test => {
          const previous = previousByName.get(testKey(test));
          if (!previous?.duration_ms || !test.duration_ms) return null;
          const increase = ((test.duration_ms - previous.duration_ms) / previous.duration_ms) * 100;
          return increase >= 50 && test.duration_ms - previous.duration_ms >= 1000
            ? { test, increase }
            : null;
        })
        .filter(Boolean) as Array<{ test: ApiTestCase; increase: number }>;
      if (durationSpikes.length > 0) {
        const averageIncrease = Math.round(durationSpikes.reduce((sum, item) => sum + item.increase, 0) / durationSpikes.length);
        insights.push({
          id: 'performance-duration-spike',
          priority: INSIGHT_PRIORITY.performance,
          type: 'performance',
          title: 'Performance degradation detected',
          summary: 'Test durations increased significantly versus the previous comparable run.',
          impact: `${averageIncrease}% average increase across ${durationSpikes.length} test${durationSpikes.length === 1 ? '' : 's'}`,
          confidence: durationSpikes.length >= 3 ? 'medium' : 'low',
          evidence: durationSpikes.slice(0, 3).map(item => `${item.test.name}: +${Math.round(item.increase)}%`),
          action: 'Investigate latency, backend performance, or environment contention for the slower tests.',
          cta: 'View slow',
          payload: { status: 'slow' },
        });
      }
    }

    return insights
      .sort((a, b) => a.priority - b.priority)
      .slice(0, 5);
  }, [tests, incidents, previousComparableRun, previousTests, runComparison, topSuite, totalSuiteFailures, failedCount, run.run_id]);
  const regressionNote = previousComparableRun
    ? undefined
    : 'No previous comparable run available for regression checks.';
  const triageFilters = [
    { value: '', label: 'All', count: tests.length, tone: 'text-primary' },
    { value: 'failed', label: 'Failed', count: failedCount, tone: 'text-red-400' },
    { value: 'passed', label: 'Passed', count: passedCount, tone: 'text-green-400' },
    { value: 'skipped', label: 'Skipped', count: skippedCount, tone: 'text-slate-400' },
    { value: 'slow', label: 'Slow', count: slowCount, tone: 'text-amber-400' },
    { value: 'retry', label: 'Retries', count: retryCount, tone: 'text-blue-400' },
  ];
  const runOptions = useMemo(
    () => runs.map(item => ({
      value: item.run_id,
      label: `Run #${item.run_sequence ?? item.run_id.slice(0, 8)}`,
    })),
    [runs],
  );

  const focusEvidence = useCallback(() => {
    requestAnimationFrame(() => {
      evidenceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

  const viewSuiteTests = useCallback((suiteName: string) => {
    setSuiteFilter(suiteName);
    setFingerprintFilter('');
    setTestNameFilter([]);
    setStatusFilter('failed');
    focusEvidence();
  }, [focusEvidence]);

  const handleInsightAction = useCallback((type: string, payload: Record<string, unknown>) => {
    if (type === 'infra') {
      setSuiteFilter('');
      setStatusFilter('failed');
      setFingerprintFilter(typeof payload.fingerprint === 'string' ? payload.fingerprint : '');
      setTestNameFilter(Array.isArray(payload.testNames) ? payload.testNames.filter((name): name is string => typeof name === 'string') : []);
      focusEvidence();
      return;
    }
    if (type === 'hotspot' && typeof payload.suite === 'string') {
      viewSuiteTests(payload.suite);
      return;
    }
    if (type === 'regression') {
      const previousRunId = typeof payload.previousRunId === 'string' ? payload.previousRunId : '';
      const currentRunId = typeof payload.currentRunId === 'string' ? payload.currentRunId : run.run_id;
      const params = new URLSearchParams(window.location.search);
      params.set('tab', 'compare');
      if (previousRunId) params.set('run_ids', `${previousRunId},${currentRunId}`);
      window.open(`${window.location.pathname}?${params.toString()}`, '_blank', 'noopener,noreferrer');
      return;
    }
    if (type === 'flaky') {
      setSuiteFilter('');
      setFingerprintFilter('');
      setTestNameFilter([]);
      setStatusFilter('retry');
      focusEvidence();
      return;
    }
    if (type === 'performance') {
      setSuiteFilter('');
      setFingerprintFilter('');
      setTestNameFilter([]);
      setStatusFilter('slow');
      focusEvidence();
      return;
    }
    setSuiteFilter('');
    setFingerprintFilter('');
    setTestNameFilter([]);
    setStatusFilter(typeof payload.status === 'string' ? payload.status : 'failed');
    focusEvidence();
  }, [focusEvidence, run.run_id, viewSuiteTests]);

  return (
    <div className="space-y-6">
      {/* Back + header */}
      <PageHeader
        tier="minimal"
        kicker="Run Detail"
        title={`Run #${run.run_sequence ?? run.run_id.slice(0, 8)}`}
        meta={run.project ?? undefined}
        titleAs="h2"
        actions={(
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="qara-control px-3.5 text-sm text-muted hover:text-primary"
            >
              <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4">
                <path d="M10 4L6 8l4 4" stroke="currentColor" strokeWidth="1.5"
                      strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              All Runs
            </button>
            <Dropdown
              value={run.run_id}
              onChange={onSelectRun}
              options={runOptions}
              align="right"
              triggerClassName="min-w-[148px] px-3 py-1.5 text-sm font-medium"
              renderValue={() => (
                <div className="flex min-w-0 flex-col leading-tight">
                  <span className="truncate text-[13px] font-semibold text-primary">
                    Run #{run.run_sequence ?? run.run_id.slice(0, 8)}
                  </span>
                  {run.started_at && (
                    <span className="truncate text-[10px] text-muted">
                      {formatDate(run.started_at)}
                    </span>
                  )}
                </div>
              )}
            />
          </div>
        )}
      />

      {/* Run story + visual summary */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
        <section className="rounded-2xl border border-border-default bg-surface px-6 py-5 shadow-sm">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <p className="type-metric-label">Run health</p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <h3 className={`text-3xl font-semibold tracking-tight ${healthTone}`}>
                  {healthLabel}
                </h3>
                {passRate != null && (
                  <span className="rounded-full border border-border-subtle bg-subtle px-3 py-1 text-sm font-semibold text-secondary">
                    {pctLabel(passRate)} pass rate
                  </span>
                )}
              </div>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-secondary">
                {failedCount > 0
                  ? `${failedCount} test${failedCount === 1 ? '' : 's'} failed${topSuite ? `, concentrated most in ${topSuite.suite}` : ''}${topIncident ? ` with ${incidents.length} incident cluster${incidents.length === 1 ? '' : 's'} detected` : ''}.`
                  : `No failed tests were found in this run${skippedCount > 0 ? `, with ${skippedCount} skipped test${skippedCount === 1 ? '' : 's'}` : ''}.`
                }
              </p>
              <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted">
                {run.branch && <span className="qara-pill font-mono">{run.branch}</span>}
                {run.build_number && <span className="qara-pill">Build #{run.build_number}</span>}
                {run.environment && <span className="qara-pill">{run.environment}</span>}
                {run.started_at && <span className="qara-pill">{formatDate(run.started_at)}</span>}
                {run.total_ms && <span className="qara-pill">Duration {formatMs(run.total_ms)}</span>}
              </div>
            </div>
            <div className="grid min-w-[220px] grid-cols-2 gap-3">
              <div className="rounded-xl border border-border-subtle bg-subtle px-4 py-3">
                <p className="type-metric-label">Failed</p>
                <p className="mt-2 text-2xl font-semibold text-red-400">{fmt(failedCount)}</p>
              </div>
              <div className="rounded-xl border border-border-subtle bg-subtle px-4 py-3">
                <p className="type-metric-label">Incidents</p>
                <p className="mt-2 text-2xl font-semibold text-amber-400">{fmt(incidents.length)}</p>
              </div>
              <div className="rounded-xl border border-border-subtle bg-subtle px-4 py-3">
                <p className="type-metric-label">Slow</p>
                <p className="mt-2 text-2xl font-semibold text-blue-400">{fmt(slowCount)}</p>
              </div>
              <div className="rounded-xl border border-border-subtle bg-subtle px-4 py-3">
                <p className="type-metric-label">Retries</p>
                <p className="mt-2 text-2xl font-semibold text-violet-400">{fmt(retryCount)}</p>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-border-default bg-surface px-5 py-5 shadow-sm">
          <p className="type-metric-label">Status mix</p>
          <div className="mt-3">
            <StatusDonut passed={passedCount} failed={failedCount} skipped={skippedCount} />
          </div>
        </section>
      </div>

      {/* Triage strip */}
      <div className="rounded-2xl border border-border-default bg-surface p-3 shadow-sm">
        <div className="mb-3 flex items-center justify-between gap-3 px-1">
          <div>
            <p className="text-sm font-semibold text-primary">Triage filters</p>
            <p className="text-xs text-muted">Use these to move from run summary to evidence.</p>
          </div>
          {topSuite && (
            <span className="hidden rounded-full border border-red-500/20 bg-red-500/10 px-3 py-1 text-xs font-medium text-red-400 sm:inline-flex">
              Top suite: {topSuite.suite}
            </span>
          )}
        </div>
        <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {triageFilters.map(filter => (
            <button
              key={filter.value}
              type="button"
              onClick={() => {
                setStatusFilter(filter.value);
                if (!filter.value) setSuiteFilter('');
                setFingerprintFilter('');
                setTestNameFilter([]);
              }}
              className={[
                'rounded-xl border px-4 py-3 text-left transition-colors',
                statusFilter === filter.value
                  ? 'border-info/30 bg-info/[0.08]'
                  : 'border-border-subtle bg-subtle hover:border-border-default hover:bg-surface',
              ].join(' ')}
            >
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{filter.label}</p>
              <p className={`mt-2 text-2xl font-semibold ${filter.tone}`}>{fmt(filter.count)}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Incidents summary */}
      {incidents.length > 0 && (
        <IncidentsSection incidents={incidents} />
      )}
      {incidentsLoading && !loading && (
        <div className="qara-inline-note">Loading incident groups…</div>
      )}

      {/* Failure concentration */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(300px,0.75fr)]">
        <section className="rounded-2xl border border-border-default bg-surface px-5 py-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="type-metric-label">Failure concentration</p>
              <h3 className="mt-2 text-lg font-semibold text-primary">Suite hotspots</h3>
              <p className="mt-1 text-sm text-muted">Where this run’s failures are concentrated.</p>
            </div>
            {suiteFailures.length > 1 && <span className="rounded-full border border-border-subtle bg-subtle px-3 py-1 text-xs font-medium text-muted">
              Top {Math.min(5, suiteFailures.length)}
            </span>}
          </div>
          <div className="mt-5">
            <SuiteFailureHotspots
              rows={suiteFailures}
              totalFailures={totalSuiteFailures}
              onSuiteSelect={viewSuiteTests}
            />
          </div>
        </section>

        <RunInsightsPanel
          insights={runInsights}
          regressionNote={regressionNote}
          onInsightAction={handleInsightAction}
        />
      </div>

      {/* Loading / error */}
      {loading && (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3].map(i => <div key={i} className="h-10 rounded-xl bg-zinc-800" />)}
        </div>
      )}
      {error && (
        <div className="qara-error-banner">
          Failed to load tests: {error}
        </div>
      )}

      {/* Tests */}
      {!loading && !error && (
        <div ref={evidenceRef} className="scroll-mt-6 space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-primary">Test evidence</h3>
              <p className="text-sm text-muted">
                Showing {filtered.length} of {tests.length} tests{statusFilter ? ` for ${triageFilters.find(f => f.value === statusFilter)?.label.toLowerCase()}` : ''}{suiteFilter ? ` in ${suiteFilter}` : ''}{(fingerprintFilter || testNameFilter.length > 0) ? ' matching selected insight' : ''}.
              </p>
            </div>
            {(statusFilter || suiteFilter || fingerprintFilter || testNameFilter.length > 0) && (
              <button
                type="button"
                onClick={() => {
                  setStatusFilter('');
                  setSuiteFilter('');
                  setFingerprintFilter('');
                  setTestNameFilter([]);
                }}
                className="qara-control px-3 py-1.5 text-sm text-muted hover:text-primary"
              >
                Clear filter
              </button>
            )}
          </div>

          {/* Table */}
          {filtered.length === 0 ? (
            <div className="qara-empty-state">
              <div className="qara-empty-icon">∅</div>
              <p className="type-empty-title">No tests match this filter</p>
              <p className="type-empty-subtitle">Try a broader status selection for this run.</p>
            </div>
          ) : (
            <div className="qara-table-shell">
              <div className="overflow-x-auto">
                <table className="qara-table w-full">
                  <thead className="qara-table-head">
                    <tr>
                      {['Test', 'Status', 'Suite', 'Owner', 'Duration', 'Message'].map(h => (
                        <th key={h} className="text-left">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(tc => <TestCaseRow key={tc.tc_id} tc={tc} />)}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Runs list view
// ─────────────────────────────────────────────────────────────

function RunsListView({
  runs,
  onSelect,
}: {
  runs:     ApiRun[];
  onSelect: (run: ApiRun) => void;
}) {
  const [page,     setPage]     = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [search,   setSearch]   = useState('');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return runs;
    return runs.filter(r =>
      (r.project ?? '').toLowerCase().includes(q) ||
      (r.branch ?? '').toLowerCase().includes(q) ||
      (r.build_number ?? '').toLowerCase().includes(q) ||
      String(r.run_sequence ?? '').includes(q),
    );
  }, [runs, search]);

  const totalPages = Math.ceil(filtered.length / pageSize);
  const start      = page * pageSize;
  const pageSlice  = filtered.slice(start, start + pageSize);

  // Reset page when filter changes
  useEffect(() => { setPage(0); }, [search, pageSize]);

  // Stat cards
  const projects = useMemo(
    () => [...new Set(runs.map(r => r.project).filter(Boolean))].length,
    [runs],
  );

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="qara-stat-grid">
        <div className="qara-stat-card">
          <span className="type-metric-label">Total Runs</span>
          <span className="type-metric-value text-zinc-100">{runs.length}</span>
        </div>
        <div className="qara-stat-card">
          <span className="type-metric-label">Projects</span>
          <span className="type-metric-value text-zinc-100">{projects}</span>
        </div>
        {runs[0]?.started_at && (
          <div className="qara-stat-card">
            <span className="type-metric-label">Latest</span>
            <span className="type-metric-value-sm text-zinc-200">{formatDate(runs[0].started_at)}</span>
          </div>
        )}
      </div>

      {/* Search + page size */}
      <div className="qara-toolbar">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500"
               viewBox="0 0 16 16" fill="none">
            <circle cx="6.5" cy="6.5" r="4" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M10 10l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <input
            type="text"
            placeholder="Search by project, branch…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="qara-control qara-input type-input w-full pl-9 pr-3"
          />
        </div>
        {search && (
          <span className="qara-inline-note">{filtered.length} of {runs.length} runs</span>
        )}
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="qara-empty-state">
          <div className="qara-empty-icon">∅</div>
          <p className="type-empty-title">No runs match the search</p>
          <p className="type-empty-subtitle">Search by project, branch, build number, or sequence.</p>
        </div>
      ) : (
        <>
          <div className="qara-table-shell">
            <div className="overflow-x-auto">
              <table className="qara-table w-full">
                <thead className="qara-table-head">
                  <tr>
                    {['#', 'Project', 'Format', 'Started', 'Duration', 'Tests', 'Passed', 'Failed', 'Skipped', 'Pass%', 'Branch', 'Build'].map(h => (
                      <th key={h} className="text-left">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {pageSlice.map(run => {
                    const passRate = run.total_tests ? Math.round((run.passed_count ?? 0) / run.total_tests * 100) : null;
                    const passClass = passRate == null ? 'text-zinc-500'
                      : passRate >= 90 ? 'text-green-400'
                      : passRate >= 60 ? 'text-amber-400'
                      : 'text-red-400';
                    return (
                      <tr key={run.run_id}
                          onClick={() => onSelect(run)}
                          className="qara-table-row cursor-pointer">
                        <td className="qara-table-cell type-td-num font-mono">
                          {run.run_sequence ?? '—'}
                        </td>
                        <td className="qara-table-cell type-td-primary truncate max-w-[140px]">
                          {run.project ?? '—'}
                        </td>
                        <td className="qara-table-cell type-td-secondary">
                          {run.report_format}
                        </td>
                        <td className="qara-table-cell type-td-secondary whitespace-nowrap">
                          {formatDate(run.started_at)}
                        </td>
                        <td className="qara-table-cell type-td-num">
                          {formatMs(run.total_ms)}
                        </td>
                        <td className="qara-table-cell type-td-num text-zinc-300">
                          {fmt(run.total_tests)}
                        </td>
                        <td className="qara-table-cell type-td-num text-green-400">
                          {fmt(run.passed_count)}
                        </td>
                        <td className="qara-table-cell type-td-num text-red-400">
                          {fmt(run.failed_count)}
                        </td>
                        <td className="qara-table-cell type-td-num text-zinc-500">
                          {fmt(run.skipped_count)}
                        </td>
                        <td className={`qara-table-cell type-td-num font-semibold ${passClass}`}>
                          {passRate != null ? `${passRate}%` : '—'}
                        </td>
                        <td className="qara-table-cell type-td-secondary font-mono truncate max-w-[100px]">
                          {run.branch ?? '—'}
                        </td>
                        <td className="qara-table-cell type-td-secondary font-mono">
                          {run.build_number ?? '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-end gap-3">
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              <span className="qara-inline-note whitespace-nowrap">Rows per page</span>
              <Dropdown
                value={String(pageSize)}
                onChange={value => setPageSize(Number(value))}
                align="right"
                triggerClassName="h-8 min-w-[58px] rounded-[0.65rem] border-transparent bg-subtle px-2 text-sm hover:border-border-default hover:bg-surface"
                menuClassName="min-w-[82px]"
                options={PAGE_SIZES.map(size => ({ value: String(size), label: String(size) }))}
              />
              <span className="qara-inline-note whitespace-nowrap">
                {start + 1}-{Math.min(start + pageSize, filtered.length)} of {filtered.length}
              </span>
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className="flex h-8 w-8 items-center justify-center rounded-[0.65rem] border border-transparent bg-transparent px-0 text-muted transition-colors hover:bg-subtle hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed"
                aria-label="Previous page"
              >
                <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4">
                  <path d="M10 4L6 8l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="flex h-8 w-8 items-center justify-center rounded-[0.65rem] border border-transparent bg-transparent px-0 text-muted transition-colors hover:bg-subtle hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed"
                aria-label="Next page"
              >
                <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4">
                  <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// RunsPanel
// ─────────────────────────────────────────────────────────────

export function RunsPanel() {
  const { currentProject } = useProject();

  const [runs,         setRuns]         = useState<ApiRun[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState<string | null>(null);
  const [selectedRun,  setSelectedRun]  = useState<ApiRun | null>(null);

  // Deep-link: ?run=<run_id>
  const deepLinkRunId = useMemo(() => {
    return new URLSearchParams(window.location.search).get('run');
  }, []);

  const projectCount = useMemo(
    () => [...new Set(runs.map(run => run.project).filter(Boolean))].length,
    [runs],
  );

  // Fetch runs
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedRun(null);

    const params = new URLSearchParams({ limit: String(INITIAL_RUN_LIMIT) });
    if (currentProject) params.set('project', currentProject);

    fetch(`/api/runs?${params}`)
      .then(r => r.ok ? r.json() as Promise<ApiRun[]> : Promise.reject(`API ${r.status}`))
      .then(async data => {
        if (cancelled) return;
        // Handle deep-link: find the run and navigate to it
        if (deepLinkRunId) {
          const target = data.find(r => r.run_id === deepLinkRunId);
          if (target) {
            setRuns(data);
            setSelectedRun(target);
            return;
          }

          const run = await fetch(`/api/runs/${encodeURIComponent(deepLinkRunId)}`)
            .then(r => r.ok ? r.json() as Promise<ApiRun> : Promise.reject(`API ${r.status}`));
          if (cancelled) return;
          setRuns([run, ...data.filter(item => item.run_id !== run.run_id)]);
          setSelectedRun(run);
          return;
        }
        setRuns(data);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [currentProject, deepLinkRunId]);

  const handleBack = useCallback(() => {
    setSelectedRun(null);
    // Clean up URL deep-link param if present
    if (deepLinkRunId) {
      const url = new URL(window.location.href);
      url.searchParams.delete('run');
      url.searchParams.delete('label');
      url.searchParams.delete('highlight');
      window.history.replaceState(null, '', url.toString());
    }
  }, [deepLinkRunId]);

  const handleSelectRun = useCallback((runId: string) => {
    const nextRun = runs.find(item => item.run_id === runId);
    if (!nextRun) return;
    setSelectedRun(nextRun);

    const url = new URL(window.location.href);
    url.searchParams.set('run', nextRun.run_id);
    window.history.replaceState(null, '', url.toString());
  }, [runs]);

  return (
    <div className="qara-page">
      {/* Page header */}
      {!selectedRun && (
        <PageHeader
          tier="compact"
          kicker="Operations"
          title="Runs"
          icon="▶"
          meta={`${runs.length} total${runs.length > 0 ? ` · ${projectCount} project${projectCount === 1 ? '' : 's'}` : ''}`}
        />
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-10 rounded-xl bg-zinc-800" />)}
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="qara-error-banner">
          <span>⚠️</span>
          <span>Failed to load runs: {error}</span>
        </div>
      )}

      {/* Content */}
      {!loading && !error && (
        selectedRun
          ? <RunDetailView run={selectedRun} runs={runs} onSelectRun={handleSelectRun} onBack={handleBack} />
          : runs.length === 0
          ? (
            <div className="qara-empty-state">
              <div className="qara-empty-icon">▶</div>
              <p className="type-empty-title">No runs found</p>
              <p className="type-empty-subtitle max-w-xs">
                Ingest a test report with <code className="text-zinc-400">qara ingest</code> to see runs here.
              </p>
            </div>
          )
          : <RunsListView runs={runs} onSelect={setSelectedRun} />
      )}
    </div>
  );
}
