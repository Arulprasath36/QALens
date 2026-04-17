import { useState, useEffect, useMemo, useCallback, Fragment } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
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
const STATUS_FILTERS = [
  { value: '',        label: 'All'     },
  { value: 'failed',  label: 'Failed'  },
  { value: 'passed',  label: 'Passed'  },
  { value: 'skipped', label: 'Skipped' },
] as const;

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

// ─────────────────────────────────────────────────────────────
// Test case row (expandable)
// ─────────────────────────────────────────────────────────────

function TestCaseRow({ tc }: { tc: ApiTestCase }) {
  const [open, setOpen] = useState(false);
  const statusBadge = STATUS_BADGE[tc.status] ?? 'qara-badge-neutral';
  const serveableAttachments = tc.attachments.filter(a => a.resolved_path);
  const hasDetail = !!(tc.message || tc.stack_trace || serveableAttachments.length || tc.status === 'failed' || tc.status === 'broken');

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
            <span className="type-td-primary truncate max-w-[280px]" title={tc.name}>
              {tc.name}
            </span>
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
            ) : (tc.status === 'failed' || tc.status === 'broken') ? (
              <p className="text-xs text-zinc-600">No stack trace was present in the report.</p>
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
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      fetch(`/api/runs/${run.run_id}/tests`).then(r => r.ok ? r.json() as Promise<ApiTestCase[]> : Promise.reject(`API ${r.status}`)),
      fetch(`/api/runs/${run.run_id}/incidents`).then(r => r.ok ? r.json() as Promise<ApiIncident[]> : Promise.reject(`API ${r.status}`)).catch(() => [] as ApiIncident[]),
    ])
      .then(([tc, inc]) => {
        if (cancelled) return;
        setTests(tc);
        setIncidents(inc);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [run.run_id]);

  const filtered = useMemo(() => {
    if (!statusFilter) return tests;
    if (statusFilter === 'failed') return tests.filter(t => t.status === 'failed' || t.status === 'broken');
    return tests.filter(t => t.status === statusFilter);
  }, [tests, statusFilter]);

  const passRate = run.total_tests ? Math.round((run.passed_count ?? 0) / run.total_tests * 100) : null;
  const runOptions = useMemo(
    () => runs.map(item => ({
      value: item.run_id,
      label: `Run #${item.run_sequence ?? item.run_id.slice(0, 8)}`,
    })),
    [runs],
  );

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
          </div>
        )}
      />

      {/* Meta line */}
      <div className="qara-toolbar">
        {run.branch && <span className="qara-pill font-mono">{run.branch}</span>}
        {run.build_number && <span>Build #{run.build_number}</span>}
        {run.environment  && <span>{run.environment}</span>}
        {run.started_at   && <span>{formatDate(run.started_at)}</span>}
        {run.total_ms     && <span>Duration: {formatMs(run.total_ms)}</span>}
      </div>

      {/* Stat cards */}
      <div className="qara-stat-grid">
        {[
          { label: 'Total',    value: fmt(run.total_tests),    cls: 'text-zinc-100' },
          { label: 'Passed',   value: fmt(run.passed_count),   cls: 'text-green-400' },
          { label: 'Failed',   value: fmt(run.failed_count),   cls: 'text-red-400' },
          { label: 'Skipped',  value: fmt(run.skipped_count),  cls: 'text-zinc-400' },
          ...(passRate != null ? [{ label: 'Pass Rate', value: `${passRate}%`, cls: passRate >= 90 ? 'text-green-400' : passRate >= 60 ? 'text-amber-400' : 'text-red-400' }] : []),
          ...(incidents.length > 0 ? [{ label: 'Incidents', value: fmt(incidents.length), cls: 'text-red-400' }] : []),
        ].map(c => (
          <div key={c.label} className="qara-stat-card">
            <span className="type-metric-label">{c.label}</span>
            <span className={`type-metric-value ${c.cls}`}>{c.value}</span>
          </div>
        ))}
      </div>

      {/* Incidents summary */}
      {incidents.length > 0 && (
        <IncidentsSection incidents={incidents} />
      )}

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
        <div className="space-y-3">
          {/* Status filter tabs */}
          <div className="qara-toolbar">
            {STATUS_FILTERS.map(f => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                className={[
                  'qara-chip type-chip',
                  statusFilter === f.value
                    ? 'qara-chip-active'
                    : '',
                ].join(' ')}
              >
                {f.label}
                {f.value === '' && <span className="ml-1 text-zinc-500">({tests.length})</span>}
                {f.value === 'failed' && (
                  <span className="ml-1 text-red-400">
                    ({tests.filter(t => t.status === 'failed' || t.status === 'broken').length})
                  </span>
                )}
              </button>
            ))}
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

    const params = new URLSearchParams({ limit: '500' });
    if (currentProject) params.set('project', currentProject);

    fetch(`/api/runs?${params}`)
      .then(r => r.ok ? r.json() as Promise<ApiRun[]> : Promise.reject(`API ${r.status}`))
      .then(data => {
        if (cancelled) return;
        setRuns(data);
        // Handle deep-link: find the run and navigate to it
        if (deepLinkRunId) {
          const target = data.find(r => r.run_id === deepLinkRunId);
          if (target) setSelectedRun(target);
        }
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
