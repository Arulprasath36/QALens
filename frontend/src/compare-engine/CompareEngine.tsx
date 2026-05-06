import { useState, useRef, useEffect } from 'react';
import { useCompareState } from './hooks/useCompareState';
import { useCompareData, useCatalogue } from './hooks/useCompareData';
import { PageHeader } from '../components/PageHeader';
import { CompareControlBar } from './components/CompareControlBar';
import { ComparisonSummaryCards } from './components/output/ComparisonSummaryCards';
import { ComparisonTable } from './components/output/ComparisonTable';
import { EntityComparisonView } from './components/output/EntityComparisonView';
import { HistoryMatrixView } from './components/output/HistoryMatrixView';
import { DIMENSION_CONFIG, TIME_MODE_LABELS } from './types';
import type { ComparisonResult, DeltaDirection } from './types';

// ─────────────────────────────────────────────────────────────
// Inline selection hint
// ─────────────────────────────────────────────────────────────

function SelectionHint({ dimension, selected, maxSelections }: {
  dimension:     string;
  selected:      string[];
  maxSelections: number;
}) {
  if (dimension === 'runs') {
    return (
      <p className="text-xs text-muted">
        Select one or more runs to compare.
      </p>
    );
  }

  const remaining = maxSelections - selected.length;
  if (remaining <= 0) return null;

  const noun = dimension === 'runs' ? 'run' : dimension.slice(0, -1); // "owner", "suite"
  const message = remaining === maxSelections
    ? `Select up to ${maxSelections} ${noun}s to compare`
    : selected.length >= 2
      ? `Comparing ${selected.length} — add 1 more ${noun} or compare now`
      : `Select ${remaining} more ${noun}${remaining > 1 ? 's' : ''} (${selected.length}/${maxSelections})`;

  return (
    <p className="text-xs text-muted">
      {message}
    </p>
  );
}

// ─────────────────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex-1 h-24 qara-card-soft" />
        ))}
      </div>
      <div className="h-64 qara-card-soft" />
    </div>
  );
}

function formatPassRate(passCount: number, totalTests: number): string {
  if (!totalTests) return '0%';
  return `${Math.round((passCount / totalTests) * 100)}%`;
}

type DriverPriority = 'primary' | 'secondary' | 'offset';

interface DriverItem {
  priority:  DriverPriority;
  headline:  string;           // explanatory phrase, not just a count
  context:   string;           // one-line reason
  tone:      'danger' | 'warning' | 'success' | 'neutral';
  filter?:   string;           // future: maps to a table filter key
}

function buildDrivers(
  latest:   ComparisonResult['metricsB'],
  baseline: ComparisonResult['metricsA'],
  result:   ComparisonResult,
): DriverItem[] {
  const candidates: (DriverItem & { weight: number })[] = [];

  if (latest.newFailures > 0)
    candidates.push({
      priority: 'primary',
      headline: `+${latest.newFailures} new failure${latest.newFailures > 1 ? 's' : ''} introduced`,
      context:  'Tests that passed before are now failing',
      tone:     'danger',
      filter:   'regressed',
      weight:   latest.newFailures * 3,
    });

  const brokenCount = result.rows.filter(r => r.delta === 'broken').length;
  if (brokenCount > 0)
    candidates.push({
      priority: 'secondary',
      headline: `${brokenCount} test${brokenCount > 1 ? 's' : ''} persistently broken`,
      context:  'Failing in both runs — not a new regression',
      tone:     'danger',
      filter:   'broken',
      weight:   brokenCount * 2,
    });

  if (latest.fixedTests > 0)
    candidates.push({
      priority: 'offset',
      headline: `+${latest.fixedTests} test${latest.fixedTests > 1 ? 's' : ''} recovered`,
      context:  'Previously failing tests are now passing',
      tone:     'success',
      filter:   'improved',
      weight:   latest.fixedTests,
    });

  const testDelta = latest.totalTests - baseline.totalTests;
  if (Math.abs(testDelta) > 0)
    candidates.push({
      priority: 'secondary',
      headline: testDelta > 0
        ? `${testDelta} test${testDelta > 1 ? 's' : ''} added to suite`
        : `${Math.abs(testDelta)} test${Math.abs(testDelta) > 1 ? 's' : ''} removed from suite`,
      context:  'Suite coverage changed between runs',
      tone:     'neutral',
      weight:   Math.abs(testDelta),
    });

  // Sort by weight, take top 3
  return candidates
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3);
}

const TONE_TEXT: Record<DriverItem['tone'], string> = {
  danger:  'text-danger',
  warning: 'text-warning',
  success: 'text-success',
  neutral: 'text-secondary',
};

const TONE_DOT: Record<DriverItem['tone'], string> = {
  danger:  'bg-danger',
  warning: 'bg-warning',
  success: 'bg-success',
  neutral: 'bg-border-strong',
};

function PairwiseHero({ result, onDriverClick }: {
  result: ComparisonResult;
  onDriverClick?: (filter: string) => void;
}) {
  const baseline = result.metricsA;
  const latest   = result.metricsB;

  const baselineRate = baseline.totalTests > 0 ? baseline.passCount / baseline.totalTests : 0;
  const latestRate   = latest.totalTests   > 0 ? latest.passCount   / latest.totalTests   : 0;

  const deltaPct  = Math.round((latestRate - baselineRate) * 100);
  const regressed = deltaPct < 0;
  const improved  = deltaPct > 0;
  const neutral   = deltaPct === 0;

  const verdictClass = neutral ? 'text-muted' : regressed ? 'text-danger' : 'text-success';
  const deltaSign    = improved ? '+' : '';

  const drivers = buildDrivers(latest, baseline, result);

  // Shared surface tint based on outcome
  const surfaceTint = neutral   ? 'bg-surface-subtle'
                    : regressed ? 'bg-danger/[0.03]'
                    :             'bg-success/[0.03]';

  const dividerColor = neutral   ? 'border-border-subtle'
                     : regressed ? 'border-danger/10'
                     :             'border-success/10';

  return (
    <section className="border-b border-border-subtle pb-6 md:pb-7">
      <div className={`rounded-2xl border ${dividerColor} ${surfaceTint} overflow-hidden`}>
        <div className="grid grid-cols-1 lg:w-fit lg:grid-cols-[560px_320px]">

          {/* ── LEFT: comparison ──────────────────────────────── */}
          <div className="p-6 lg:p-7">

            {/* Run names */}
            <p className="text-[13px] text-muted mb-5">
              <span className="font-semibold text-primary">{latest.label}</span>
              <span className="mx-2 text-faint">vs</span>
              <span className="font-medium">{baseline.label}</span>
            </p>

            {/* Pass rates */}
            <div className="flex items-end gap-7">
              <div>
                <span className={`text-[clamp(2rem,4.5vw,3.2rem)] font-semibold tracking-tight tabular-nums leading-none ${
                  neutral ? 'text-primary' : regressed ? 'text-danger' : 'text-success'
                }`}>
                  {formatPassRate(latest.passCount, latest.totalTests)}
                </span>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mt-2">Latest</p>
              </div>
              <div className="pb-[1.6rem]">
                <span className="text-[clamp(1.4rem,3vw,2rem)] font-semibold tracking-tight text-secondary tabular-nums leading-none opacity-60">
                  {formatPassRate(baseline.passCount, baseline.totalTests)}
                </span>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mt-2">Previous</p>
              </div>
            </div>

            {/* Delta chip */}
            <div className="flex items-center gap-2.5 mt-5">
              <span className={[
                'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold border',
                neutral   ? 'border-border-default text-muted bg-surface'
                : regressed ? 'border-danger/25 bg-danger/8 text-danger'
                :             'border-success/25 bg-success/8 text-success',
              ].join(' ')}>
                {neutral ? '—' : regressed ? '↓' : '↑'}
                {' '}{neutral ? 'No change' : `${deltaSign}${deltaPct}% pass rate`}
              </span>
              {!neutral && (
                <span className={`text-xs ${verdictClass} opacity-70`}>
                  {regressed ? 'regression' : 'improvement'}
                </span>
              )}
            </div>

            {/* Date */}
            {result.contextLabel && (
              <p className="text-[11px] text-faint mt-4">{result.contextLabel}</p>
            )}
          </div>

          {/* ── RIGHT: insight panel ──────────────────────────── */}
          {drivers.length > 0 && (
            <div className={`border-t lg:border-t-0 lg:border-l ${dividerColor} p-6 lg:p-7 flex flex-col`}>
              <p className="text-[11px] font-semibold text-muted uppercase tracking-[0.14em] mb-4">
                {neutral ? 'What changed?' : regressed ? 'Why did this regress?' : 'Why did this improve?'}
              </p>

              <ul className="space-y-1 flex-1">
                {drivers.map((d, i) => (
                  <li key={i}>
                    <button
                      onClick={() => d.filter && onDriverClick?.(d.filter)}
                      className={[
                        'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left',
                        'transition-colors duration-100',
                        d.filter
                          ? 'hover:bg-surface cursor-pointer'
                          : 'cursor-default',
                      ].join(' ')}
                    >
                      {/* Tone dot */}
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${TONE_DOT[d.tone]}`} />

                      {/* Headline */}
                      <span className={`text-[0.875rem] font-semibold leading-snug flex-1 ${TONE_TEXT[d.tone]}`}>
                        {d.headline}
                      </span>

                      {/* Chevron affordance */}
                      {d.filter && (
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-faint flex-shrink-0">
                          <path d="M4.5 2.5L8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </button>
                  </li>
                ))}
              </ul>

              {/* Hint */}
              <p className="text-[10px] text-faint mt-4 px-3">
                Click a driver to filter the test breakdown below
              </p>
            </div>
          )}

        </div>
      </div>
    </section>
  );
}

function fmtWindowDate(iso: string | null) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ─────────────────────────────────────────────────────────────
// Compare Engine — top-level compositor
// ─────────────────────────────────────────────────────────────

export function CompareEngine() {
  const compareState = useCompareState();
  const { owners, runs, suites } = useCatalogue();
  const { result, historyResult, entityResult, loading, error } = useCompareData(compareState.state);
  const [tableFilter, setTableFilter] = useState<DeltaDirection | 'all'>('all');
  const tableRef   = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const hydratedRunIdsRef = useRef(false);

  useEffect(() => {
    if (hydratedRunIdsRef.current) return;
    const params = new URLSearchParams(window.location.search);
    const runIds = (params.get('run_ids') ?? '')
      .split(',')
      .map(id => id.trim())
      .filter(Boolean)
      .slice(0, 3);

    hydratedRunIdsRef.current = true;
    if (runIds.length === 0) return;
    compareState.setDimension('runs');
    compareState.setCustomRuns(runIds);
  }, [compareState]);

  function handleDriverClick(filter: string) {
    setTableFilter(filter as DeltaDirection | 'all');
    setTimeout(() => {
      tableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  const { state } = compareState;
  const cfg = DIMENSION_CONFIG[state.dimension];

  const isEntityDimension = state.dimension === 'owners' || state.dimension === 'suites';
  const isRunsDimension   = state.dimension === 'runs';
  const isWindowMode      = isRunsDimension && (state.timeMode === 'last5' || state.timeMode === 'last10');
  const isManualPairMode  = isRunsDimension && state.timeMode === 'custom' && state.customRunIds.length === 2;
  const isMultiRunMode    = isRunsDimension && (isWindowMode || (state.timeMode === 'custom' && state.customRunIds.length !== 2));
  const isPairwiseMode    = isRunsDimension && (state.timeMode === 'latest_vs_previous' || isManualPairMode);


  const timeLabel = (() => {
    // Custom mode: derive reactively from current selection so label
    // updates immediately when runs are added/removed (avoids stale
    // range label when only middle runs change).
    if (state.timeMode === 'custom' && state.customRunIds.length > 0) {
      const selectedRuns = runs.filter(r => state.customRunIds.includes(r.id));
      if (selectedRuns.length === 1) return selectedRuns[0].label;
      if (selectedRuns.length === 2) {
        const sorted = [...selectedRuns].sort((a, b) => a.sequence - b.sequence);
        return `${sorted[0].label} – ${sorted[1].label}`;
      }
      // 3+ runs: range label is misleading for non-contiguous selections,
      // show count instead so removing any run immediately reflects.
      return `${selectedRuns.length} runs`;
    }
    if (historyResult && historyResult.runs.length > 0) {
      const first = historyResult.runs[0];
      const last  = historyResult.runs[historyResult.runs.length - 1];
      return first.runId === last.runId
        ? last.label
        : `${first.label} – ${last.label}`;
    }
    if (result) return result.timeLabel;
    return TIME_MODE_LABELS[state.timeMode];
  })();

  const windowContextLabel = (() => {
    if (!historyResult || !isWindowMode || historyResult.runs.length === 0) return null;
    const first = historyResult.runs[0];
    const last = historyResult.runs[historyResult.runs.length - 1];
    const startDate = fmtWindowDate(first.startedAt);
    const endDate = fmtWindowDate(last.startedAt);
    return `${TIME_MODE_LABELS[state.timeMode]}${startDate && endDate ? ` • ${startDate} → ${endDate}` : ''}`;
  })();

  return (
    <div className="min-h-screen bg-page text-primary p-6 lg:p-8 space-y-6">

      {/* ── Page header ─────────────────────────────────────── */}
      <PageHeader
        tier="full"
        title={`Compare ${cfg.label}`}
        description={cfg.description}
        icon={cfg.icon}
      />

      {/* ── Control bar ─────────────────────────────────────── */}
      <div className="qara-fade-up relative z-10 border-b border-border-subtle pb-5">
        <CompareControlBar
          {...compareState}
          owners={owners}
          runs={runs}
          suites={suites}
          timeLabel={timeLabel}
          onReset={compareState.reset}
        />
        {!compareState.canCompare && !loading && (
          <div className="mt-3 pl-0.5">
            <SelectionHint
              dimension={state.dimension}
              selected={state.dimension === 'runs' ? state.customRunIds : state.selections}
              maxSelections={cfg.maxSelections}
            />
          </div>
        )}
      </div>

      {/* ── Sticky comparison summary bar (entity dimensions) ── */}
      {isEntityDimension && compareState.canCompare && (
        <div className="flex items-center justify-between gap-4 py-1 qara-fade-up">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted flex-shrink-0">
              Comparing
            </span>
            <div className="flex items-center gap-1 flex-wrap">
              {state.selections.map((id, i) => {
                const name = state.dimension === 'suites'
                  ? (suites.find(s => s.id === id)?.name ?? id)
                  : id;
                return (
                  <span key={id} className="flex items-center gap-1">
                    {i > 0 && <span className="text-faint text-[11px] mx-0.5">·</span>}
                    <span className="text-xs font-medium text-primary">{name}</span>
                  </span>
                );
              })}
            </div>
          </div>
          <button
            onClick={() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            className="flex-shrink-0 flex items-center gap-1.5 text-xs font-medium text-info hover:text-primary transition-colors"
          >
            <span>Jump to results</span>
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M6 2v8M2 7l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>
      )}

      {/* ── Output area ─────────────────────────────────────── */}
      <div id="compare-results" ref={resultsRef} className="space-y-5">

        {/* Loading */}
        {loading && <Skeleton />}

        {/* Error */}
        {error && !loading && (
          <div className="qara-card flex items-center gap-3 px-5 py-4 border-danger/20 bg-danger/10 text-danger text-sm">
            <span className="text-lg">⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* ── Pairwise comparison (latest_vs_previous) ── */}
        {result && isPairwiseMode && !loading && !error && (
          <>
            <PairwiseHero result={result} onDriverClick={handleDriverClick} />
            <ComparisonSummaryCards
              metricsA={result.metricsA}
              metricsB={result.metricsB}
            />
            <div ref={tableRef}>
              <h2 className="text-xs font-semibold text-muted uppercase tracking-[0.18em] mb-3">
                Test Breakdown
              </h2>
              <ComparisonTable
                rows={result.rows}
                metricsA={result.metricsA}
                metricsB={result.metricsB}
                initialFilter={tableFilter}
              />
            </div>
          </>
        )}

        {/* ── Multi-run history matrix (last5 / last10 / custom) ── */}
        {historyResult && isMultiRunMode && !loading && !error && (
          <>
            {windowContextLabel ? (
              <p className="text-sm text-muted">
                {windowContextLabel}
              </p>
            ) : (
              <div className="flex items-center gap-2 text-sm">
                <span className="qara-pill">{timeLabel}</span>
                <span className="qara-pill">{historyResult.summary.uniqueTests} tests</span>
              </div>
            )}
            <h2 className="text-xs font-semibold text-muted uppercase tracking-[0.18em]">
              Run History
            </h2>
            <HistoryMatrixView data={historyResult} />
          </>
        )}

        {/* ── Entity view (owners / suites) ── */}
        {entityResult && isEntityDimension && !loading && !error && (
          <div key={state.selections.slice().sort().join(',')} className="qara-fade-up space-y-5">
            <div className="flex items-center gap-2 text-sm flex-wrap">
              <span className="qara-pill">{entityResult.time_label}</span>
              <span className="text-muted">
                {[entityResult.label_a, entityResult.label_b, entityResult.label_c]
                  .filter(Boolean)
                  .map((label, i, arr) => (
                    <span key={label}>
                      {label}
                      {i < arr.length - 1 && <span className="text-faint mx-1">vs</span>}
                    </span>
                  ))}
              </span>
            </div>
            <EntityComparisonView data={entityResult} />
          </div>
        )}

      </div>
    </div>
  );
}
