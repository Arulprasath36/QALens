import React from 'react';
import { useCompareState } from './hooks/useCompareState';
import { useCompareData, useCatalogue } from './hooks/useCompareData';
import { CompareControlBar } from './components/CompareControlBar';
import { ComparisonSummaryCards } from './components/output/ComparisonSummaryCards';
import { ComparisonTable } from './components/output/ComparisonTable';
import { DIMENSION_CONFIG, TIME_MODE_LABELS } from './types';

// ─────────────────────────────────────────────────────────────
// Empty state
// ─────────────────────────────────────────────────────────────

function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
      <div className="text-4xl">🔍</div>
      <p className="text-zinc-300 font-medium">{message}</p>
      {hint && <p className="text-sm text-zinc-600 max-w-xs">{hint}</p>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex-1 h-24 bg-zinc-800 rounded-xl" />
        ))}
      </div>
      <div className="h-64 bg-zinc-800 rounded-xl" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Compare Engine — top-level compositor
// ─────────────────────────────────────────────────────────────

export function CompareEngine() {
  const compareState = useCompareState();
  const { owners, runs, suites } = useCatalogue();
  const { result, loading, error } = useCompareData(compareState.state);

  const { state } = compareState;
  const cfg = DIMENSION_CONFIG[state.dimension];

  // Build a human-readable context label: "Last 5 runs (Feb 17 → Feb 21)"
  const timeLabel = result
    ? result.timeLabel
    : TIME_MODE_LABELS[state.timeMode];

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6 space-y-6">

      {/* ── Page header ─────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <span className="text-base">{cfg.icon}</span>
            Compare {cfg.label}
          </h1>
          <p className="text-sm text-zinc-500 mt-0.5">{cfg.description}</p>
        </div>

        {compareState.canCompare && (
          <button
            onClick={compareState.reset}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700"
          >
            Reset
          </button>
        )}
      </div>

      {/* ── Control bar ─────────────────────────────────────── */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
        <CompareControlBar
          {...compareState}
          owners={owners}
          runs={runs}
          suites={suites}
          timeLabel={timeLabel}
        />
      </div>

      {/* ── Output area ─────────────────────────────────────── */}
      <div className="space-y-5">

        {/* Not enough selections */}
        {!compareState.canCompare && !loading && (
          <EmptyState
            message={`Select ${cfg.maxSelections} ${cfg.label.toLowerCase()} to compare`}
            hint={`Choose from the "${cfg.label}" picker above. Time scope: ${TIME_MODE_LABELS[state.timeMode]}`}
          />
        )}

        {/* Loading */}
        {loading && <Skeleton />}

        {/* Error */}
        {error && !loading && (
          <div className="flex items-center gap-3 px-5 py-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
            <span className="text-lg">⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* Result */}
        {result && !loading && !error && (
          <>
            {/* Time label banner */}
            <div className="flex items-center gap-2 text-sm">
              <span className="px-3 py-1 bg-zinc-800 border border-zinc-700 rounded-full text-zinc-400 font-medium">
                {result.timeLabel}
              </span>
              <span className="text-zinc-600">
                {result.metricsA.label}  <span className="text-zinc-500">vs</span>  {result.metricsB.label}
              </span>
            </div>

            {/* Summary cards */}
            <ComparisonSummaryCards
              metricsA={result.metricsA}
              metricsB={result.metricsB}
            />

            {/* Comparison table */}
            <div>
              <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-3">
                Test Breakdown
              </h2>
              <ComparisonTable
                rows={result.rows}
                metricsA={result.metricsA}
                metricsB={result.metricsB}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
