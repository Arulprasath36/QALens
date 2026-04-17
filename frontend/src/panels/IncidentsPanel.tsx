import { useState, useEffect, useCallback, Fragment } from 'react';
import { Dropdown } from '../components/Dropdown';
import { PageHeader } from '../components/PageHeader';
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
  skipped_count: number | null;
  branch:        string | null;
  build_number:  string | null;
}

interface ApiIncident {
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

// ─────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────

const SEV_CONFIG = {
  critical: {
    label:     'Critical',
    text:      'text-red-400',
    bg:        'bg-red-500/10',
    border:    'border-red-500/30',
    dot:       'bg-red-400',
  },
  high: {
    label:     'High',
    text:      'text-orange-400',
    bg:        'bg-orange-500/10',
    border:    'border-orange-500/30',
    dot:       'bg-orange-400',
  },
  medium: {
    label:     'Medium',
    text:      'text-amber-400',
    bg:        'bg-amber-500/10',
    border:    'border-amber-500/30',
    dot:       'bg-amber-400',
  },
  low: {
    label:     'Low',
    text:      'text-green-400',
    bg:        'bg-green-500/10',
    border:    'border-green-500/30',
    dot:       'bg-green-400',
  },
} as const;

const CONF_LABEL: Record<string, string> = {
  high:   'High confidence',
  medium: 'Medium confidence',
  low:    'Low confidence',
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
          ? <code key={i} className="px-1 py-0.5 rounded bg-zinc-700 text-zinc-200 text-xs font-mono">
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
      className="qara-chip type-chip"
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

function StatCards({ incidents }: { incidents: ApiIncident[] }) {
  const total      = incidents.length;
  const totalTests = incidents.reduce((s, i) => s + i.impacted_test_count, 0);
  const counts     = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const inc of incidents) counts[inc.severity]++;

  const cards: { label: string; value: number; valueClass: string }[] = [
    { label: 'Incidents',      value: total,      valueClass: 'text-zinc-100' },
    { label: 'Tests Affected', value: totalTests,  valueClass: 'text-red-400' },
    ...(counts.critical ? [{ label: 'Critical', value: counts.critical, valueClass: 'text-red-400' }]     : []),
    ...(counts.high     ? [{ label: 'High',     value: counts.high,     valueClass: 'text-orange-400' }]  : []),
    ...(counts.medium   ? [{ label: 'Medium',   value: counts.medium,   valueClass: 'text-amber-400' }]   : []),
    ...(counts.low      ? [{ label: 'Low',      value: counts.low,      valueClass: 'text-green-400' }]   : []),
  ];

  return (
    <div className="qara-stat-grid">
      {cards.map(c => (
        <div key={c.label} className="qara-stat-card">
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

function IncidentCard({ incident: inc }: { incident: ApiIncident }) {
  const [open,      setOpen]      = useState(false);
  const [testsOpen, setTestsOpen] = useState(false);

  const sev    = SEV_CONFIG[inc.severity] ?? SEV_CONFIG.low;
  const sig8   = inc.signature ? inc.signature.slice(0, 8) : null;
  const steps  = parseActionSteps(inc.recommended_action);

  return (
    <div className="qara-accordion">

      {/* ── Header (clickable) ────────────────────────────── */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3
                   text-left rounded-xl"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Severity badge */}
          <span className={`shrink-0 inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full
                            text-xs font-semibold border ${sev.text} ${sev.bg} ${sev.border}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${sev.dot}`} />
            {sev.label}
          </span>

          {/* Title */}
          <span className="type-section-title truncate">{inc.title}</span>

          {/* Signature hash */}
          {sig8 && (
            <span className="shrink-0 text-xs text-zinc-600 font-mono">#{sig8}</span>
          )}
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <span className="qara-inline-note">
            {inc.impacted_test_count} test{inc.impacted_test_count !== 1 ? 's' : ''} affected
          </span>
          <svg
            className={`w-4 h-4 text-zinc-500 transition-transform ${open ? 'rotate-90' : ''}`}
            viewBox="0 0 16 16" fill="none"
          >
            <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </button>

      {/* ── Body ─────────────────────────────────────────── */}
      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-zinc-800 pt-4">

          {/* Meta line */}
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            <span>
              <span className="text-zinc-400 font-medium">{inc.impacted_test_count}</span> tests affected
            </span>
            <span className="text-zinc-700">·</span>
            <span className="capitalize">{inc.root_cause_category.replace(/_/g, ' ')}</span>
            <span className="text-zinc-700">·</span>
            <span className={
              inc.confidence === 'high' ? 'text-green-400' :
              inc.confidence === 'medium' ? 'text-amber-400' : 'text-zinc-500'
            }>
              {CONF_LABEL[inc.confidence] ?? inc.confidence}
            </span>
          </div>

          {/* Hero: root cause */}
          <div className="qara-card-soft px-4 py-3 text-sm text-zinc-200 leading-relaxed">
            {inc.probable_root_cause}
          </div>

          {/* Why this is happening */}
          {inc.evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                Why this is happening
              </p>
              <ul className="space-y-1.5">
                {inc.evidence.map((e, i) => (
                  <li key={i} className="flex gap-2 text-sm text-zinc-400">
                    <span className="text-zinc-600 mt-0.5 shrink-0">•</span>
                    <span><EvidenceText text={e} /></span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Affected areas */}
          {inc.components.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                Affected areas
              </p>
              <div className="flex flex-wrap gap-1.5">
                {inc.components.map(c => (
                  <span key={c} className="qara-pill">
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
                <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                  What to do next
                </p>
                <CopyButton text={inc.recommended_action} />
              </div>
              <ol className="space-y-1.5 list-none">
                {steps.map((step, i) => (
                  <li key={i} className="flex gap-2.5 text-sm text-zinc-400">
                    <span className="shrink-0 w-5 h-5 rounded-full bg-zinc-800 border
                                     border-zinc-700 text-zinc-500 text-xs flex items-center
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
                className="flex items-center gap-1.5 text-xs text-zinc-500
                           hover:text-zinc-300 transition-colors"
              >
                <svg
                  className={`w-3 h-3 transition-transform ${testsOpen ? 'rotate-90' : ''}`}
                  viewBox="0 0 12 12" fill="none"
                >
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
                    <li key={i} className="text-xs text-zinc-500 font-mono truncate">
                      {name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Stack trace (if present) */}
          {inc.representative_stack_trace && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                  Stack Trace
                </p>
                <CopyButton text={inc.representative_stack_trace} label="Copy trace" />
              </div>
              <pre className="qara-code-block text-xs text-zinc-500 font-mono p-3 overflow-x-auto max-h-48
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

// ─────────────────────────────────────────────────────────────
// IncidentsPanel
// ─────────────────────────────────────────────────────────────

export function IncidentsPanel() {
  const { currentProject } = useProject();

  const [runs,              setRuns]              = useState<ApiRun[]>([]);
  const [selectedRunId,     setSelectedRunId]     = useState<string>('');
  const [incidents,         setIncidents]         = useState<ApiIncident[]>([]);
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

  // ── Fetch incidents for selected run ──────────────────────

  const fetchIncidents = useCallback((runId: string) => {
    if (!runId) { setIncidents([]); return; }

    let cancelled = false;
    setIncidentsLoading(true);
    setIncidentsError(null);
    setIncidents([]);

    fetch(`/api/runs/${runId}/incidents`)
      .then(r => r.ok ? r.json() as Promise<ApiIncident[]> : Promise.reject(`API ${r.status}`))
      .then(data => { if (!cancelled) setIncidents(data); })
      .catch(e => { if (!cancelled) setIncidentsError(String(e)); })
      .finally(() => { if (!cancelled) setIncidentsLoading(false); });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (selectedRunId) fetchIncidents(selectedRunId);
  }, [selectedRunId, fetchIncidents]);

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="qara-page">

      {/* Page header */}
      <PageHeader
        tier="compact"
        kicker="Failure Intelligence"
        title="Incidents"
        icon="🚨"
        meta={!runsLoading && selectedRunId ? `${incidents.length} detected` : undefined}
      />

      {/* Run selector */}
      <div className="qara-toolbar">
        <label className="type-input-label shrink-0">
          Run
        </label>
        {runsError ? (
          <span className="text-sm text-red-400">{runsError}</span>
        ) : (
          <Dropdown
            value={selectedRunId}
            onChange={setSelectedRunId}
            disabled={runsLoading || runs.length === 0}
            triggerClassName="min-w-[280px] px-3.5 text-sm disabled:opacity-40"
            options={
              runsLoading
                ? [{ value: '', label: 'Loading runs...', disabled: true }]
                : runs.map(r => ({
                    value: r.run_id,
                    label: `#${r.run_sequence}${r.project ? ` · ${r.project}` : ''}${r.started_at ? ` — ${formatTs(r.started_at)}` : ''}`,
                  }))
            }
          />
        )}
      </div>

      {/* Stat cards */}
      {!incidentsLoading && !incidentsError && incidents.length > 0 && (
        <StatCards incidents={incidents} />
      )}

      {/* Loading */}
      {incidentsLoading && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-14 rounded-xl bg-zinc-800" />
          ))}
        </div>
      )}

      {/* Error */}
      {incidentsError && !incidentsLoading && (
        <div className="qara-error-banner">
          <span>⚠️</span>
          <span>Failed to load incidents: {incidentsError}</span>
        </div>
      )}

      {/* Empty state */}
      {!incidentsLoading && !incidentsError && selectedRunId && incidents.length === 0 && (
        <div className="qara-empty-state">
          <div className="qara-empty-icon">✅</div>
          <p className="type-empty-title">No incidents detected</p>
          <p className="type-empty-subtitle max-w-xs">
            No failure clusters were found in this run.
          </p>
        </div>
      )}

      {/* No run selected */}
      {!incidentsLoading && !incidentsError && !selectedRunId && !runsLoading && (
        <div className="qara-empty-state">
          <div className="qara-empty-icon">🔍</div>
          <p className="type-empty-title">Select a run above</p>
        </div>
      )}

      {/* Incident cards */}
      {!incidentsLoading && !incidentsError && incidents.length > 0 && (
        <div className="space-y-3">
          {incidents.map(inc => (
            <IncidentCard key={inc.incident_id} incident={inc} />
          ))}
        </div>
      )}

    </div>
  );
}
