import { useState, useEffect } from 'react';
import { useProject } from '../../hooks/useProject';
import type {
  CompareState,
  ComparisonResult,
  ComparisonMetrics,
  ComparisonRow,
  HistoryResult,
  HistoryRunMeta,
  HistoryRow,
  Owner,
  Run,
  Suite,
  TestStatus,
  DeltaDirection,
} from '../types';

// ─────────────────────────────────────────────────────────────
// API response shapes (internal — not exported)
// ─────────────────────────────────────────────────────────────

// Returned by POST /api/compare/owners and POST /api/compare/suites
export interface ApiEntityMetrics {
  label:        string;
  total_tests:  number;
  passed:       number;
  failed:       number;
  skipped:      number;
  pass_rate:    number;
  failure_rate: number;
  flaky_count:  number;
  new_failures: number;
  fixed_tests:  number;
}

export interface ApiRunPoint {
  run_sequence: number;
  status:       string; // passed | failed | broken | skipped | absent
}

export interface ApiEntityCompareRow {
  canonical_name: string;
  display_name:   string;
  suite:          string | null;
  owner:          string | null;
  suite_name:     string | null;
  status_a:       string;
  status_b:       string;
  error_message:  string | null;
  run_history:    ApiRunPoint[];
}

export interface ApiEntityCompareResult {
  dimension:    string;
  label_a:      string;
  label_b:      string;
  label_c?:     string;
  time_label:   string;
  run_count:    number;
  runs_ordered: { run_sequence: number; display_name: string; started_at?: number | null }[];
  metrics_a:    ApiEntityMetrics;
  metrics_b:    ApiEntityMetrics;
  metrics_c?:   ApiEntityMetrics;
  rows:         ApiEntityCompareRow[];
}

interface ApiStatusSummary {
  passed:  number;
  failed:  number;
  skipped: number;
  total:   number;
}

interface ApiRunSummary {
  run_id:         string;
  run_sequence:   number;
  display_name:   string;
  started_at:     number | null; // Unix timestamp
  branch:         string | null;
  build_number:   string | null;
  report_format:  string;
  status_summary: ApiStatusSummary;
}

interface ApiCompareCell {
  run_id:              string;
  state:               string; // passed | failed | broken | skipped | absent
  fingerprint:         string | null;
  error_type:          string | null;
  message:             string | null;
  root_cause_category: string | null;
  is_latest_change:    boolean;
  tooltip:             string;
}

interface ApiCompareRow {
  canonical_name: string;
  display_name:   string;
  suite:          string | null;
  feature:        string | null;
  owner:          string | null;
  tags:           string[];
  health: {
    pass_rate:      number;
    flip_score:     number;
    classification: string;
  };
  cells: ApiCompareCell[];
}

interface ApiCompareSummary {
  window_size:          number;
  unique_tests:         number;
  flaky_tests:          number;
  consistently_broken:  number;
  stable_tests:         number;
  new_failures_latest:  number;
  fixed_latest:         number;
  insufficient_history: number;
}

interface ApiCompareResult {
  project:       string | null;
  report_format: string;
  runs:          ApiRunSummary[];
  summary:       ApiCompareSummary;
  rows:          ApiCompareRow[];
  facets: {
    suites:   string[];
    owners:   string[];
    features: string[];
    modules:  string[];
  };
}

interface ApiAvailableRun {
  run_id:        string;
  run_sequence:  number;
  display_name:  string;
  started_at:    number | null; // Unix timestamp
  branch:        string | null;
  build_number:  string | null;
  total_tests:   number;
  passed_count:  number;
  failed_count:  number;
  skipped_count: number;
}

interface ApiCompareFacetItem {
  name:       string;
  test_count: number;
}

interface ApiCompareFacetsResponse {
  owners: ApiCompareFacetItem[];
  suites: ApiCompareFacetItem[];
}

// ─────────────────────────────────────────────────────────────
// Adapter helpers
// ─────────────────────────────────────────────────────────────

function timeModeToLimit(timeMode: string): number {
  if (timeMode === 'last10')             return 10;
  if (timeMode === 'last5')              return 5;
  if (timeMode === 'latest_vs_previous') return 2;
  return 10; // custom without run_ids — default to a reasonable window
}

function formatCompareDate(timestamp: number | null): string {
  if (timestamp == null) return '';
  return new Date(timestamp * 1000).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });
}

function apiStateToStatus(state: string): TestStatus {
  if (state === 'passed')                       return 'passed';
  if (state === 'failed' || state === 'broken') return 'failed';
  if (state === 'skipped')                      return 'skipped';
  return 'skipped'; // absent → treat as skipped in A/B view
}

/**
 * Compute the change direction.
 * a = old/baseline status, b = new/latest status.
 * "Improved"  → test was failing/skipped and is now passing.
 * "Regressed" → test was passing and is now failing/skipped.
 */
function calcDelta(a: TestStatus, b: TestStatus): DeltaDirection {
  if (a === b) return a === 'passed' ? 'stable' : 'broken';
  if (b === 'passed' && a !== 'passed') return 'improved';
  if (b !== 'passed' && a === 'passed') return 'regressed';
  return 'broken'; // both non-passing but different states (e.g. skipped → failed)
}

/**
 * Map the backend matrix response to the pairwise ComparisonResult.
 * Only used for latest_vs_previous mode.
 *
 * A = baseline run (runs[last-1]) — LEFT column, older
 * B = latest run   (runs[last])   — RIGHT column, newer
 *
 * Column order matches the time label "baseline → latest" (left = old, right = new).
 */
function apiToPairwiseResult(data: ApiCompareResult): ComparisonResult | null {
  const runs = data.runs; // oldest-first
  if (runs.length === 0) return null;

  const latest   = runs[runs.length - 1];
  const baseline = runs.length >= 2 ? runs[runs.length - 2] : runs[0];

  // A = baseline (left / older), B = latest (right / newer)
  const metricsA: ComparisonMetrics = {
    label:       baseline.display_name,
    failureRate: baseline.status_summary.total > 0
      ? baseline.status_summary.failed / baseline.status_summary.total
      : 0,
    flakyCount:  0,
    newFailures: 0,
    fixedTests:  0,
    totalTests:  baseline.status_summary.total,
    passCount:   baseline.status_summary.passed,
    failCount:   baseline.status_summary.failed,
  };

  const metricsB: ComparisonMetrics = {
    label:       latest.display_name,
    failureRate: latest.status_summary.total > 0
      ? latest.status_summary.failed / latest.status_summary.total
      : 0,
    flakyCount:  data.summary.flaky_tests,
    newFailures: data.summary.new_failures_latest,
    fixedTests:  data.summary.fixed_latest,
    totalTests:  latest.status_summary.total,
    passCount:   latest.status_summary.passed,
    failCount:   latest.status_summary.failed,
  };

  const rows: ComparisonRow[] = data.rows.map(row => {
    const cellBaseline = row.cells.find(c => c.run_id === baseline.run_id);
    const cellLatest   = row.cells.find(c => c.run_id === latest.run_id);
    // statusA = baseline (old), statusB = latest (new) — matches calcDelta(old, new)
    const statusA = apiStateToStatus(cellBaseline?.state ?? 'absent');
    const statusB = apiStateToStatus(cellLatest?.state   ?? 'absent');

    return {
      testName:     row.canonical_name,
      displayName:  row.display_name,
      suite:        row.suite ?? '',
      owner:        row.owner ?? undefined,
      statusA,
      statusB,
      delta:        calcDelta(statusA, statusB),
      errorMessage: cellLatest?.message ?? undefined,
    };
  });

  const timeLabel = runs.length >= 2
    ? `${baseline.display_name} → ${latest.display_name}`
    : latest.display_name;
  const leftDate = formatCompareDate(baseline.started_at);
  const rightDate = formatCompareDate(latest.started_at);
  const contextLabel = leftDate && rightDate
    ? `Latest vs previous • ${leftDate} → ${rightDate}`
    : 'Latest vs previous';

  return { metricsA, metricsB, rows, timeLabel, contextLabel };
}

/**
 * Map the backend matrix response to the multi-run HistoryResult.
 * Used for last5, last10, and custom modes.
 */
function apiToHistoryResult(data: ApiCompareResult): HistoryResult {
  const runs: HistoryRunMeta[] = data.runs.map(r => ({
    runId:       r.run_id,
    sequence:    r.run_sequence,
    label:       r.display_name,
    startedAt:   r.started_at != null ? new Date(r.started_at * 1000).toISOString() : null,
    passRate:    r.status_summary.total > 0
      ? r.status_summary.passed / r.status_summary.total
      : 0,
    failedCount: r.status_summary.failed,
    totalTests:  r.status_summary.total,
  }));

  const rows: HistoryRow[] = data.rows.map(row => ({
    testName:       row.canonical_name,
    displayName:    row.display_name,
    suite:          row.suite ?? '',
    owner:          row.owner ?? null,
    passRate:       row.health.pass_rate,
    flipScore:      row.health.flip_score,
    classification: row.health.classification,
    cells: row.cells.map(c => ({
      runId:   c.run_id,
      state:   c.state,
      message: c.message,
    })),
  }));

  return {
    runs,
    summary: {
      windowSize:          data.summary.window_size,
      uniqueTests:         data.summary.unique_tests,
      flakyTests:          data.summary.flaky_tests,
      consistentlyBroken:  data.summary.consistently_broken,
      stableTests:         data.summary.stable_tests,
      newFailuresLatest:   data.summary.new_failures_latest,
      fixedLatest:         data.summary.fixed_latest,
    },
    rows,
  };
}

/**
 * Map the owner/suite entity comparison response to the A/B ComparisonResult.
 */
function toMetrics(m: ApiEntityMetrics): ComparisonMetrics {
  return {
    label:       m.label,
    failureRate: m.failure_rate,
    flakyCount:  m.flaky_count,
    newFailures: m.new_failures,
    fixedTests:  m.fixed_tests,
    totalTests:  m.total_tests,
    passCount:   m.passed,
    failCount:   m.failed,
  };
}

function apiEntityToResult(data: ApiEntityCompareResult): ComparisonResult {
  const rows: ComparisonRow[] = data.rows.map(row => {
    const statusA = apiStateToStatus(row.status_a);
    const statusB = apiStateToStatus(row.status_b);
    return {
      testName:     row.canonical_name,
      displayName:  row.display_name,
      suite:        row.suite ?? '',
      owner:        row.owner ?? undefined,
      statusA,
      statusB,
      delta:        calcDelta(statusA, statusB),
      errorMessage: row.error_message ?? undefined,
    };
  });

  return {
    metricsA:  toMetrics(data.metrics_a),
    metricsB:  toMetrics(data.metrics_b),
    metricsC:  data.metrics_c ? toMetrics(data.metrics_c) : undefined,
    rows,
    timeLabel: data.time_label,
  };
}

function apiAvailableRunToRun(r: ApiAvailableRun): Run {
  return {
    id:          r.run_id,
    label:       r.display_name,
    sequence:    r.run_sequence,
    startedAt:   r.started_at != null
      ? new Date(r.started_at * 1000).toISOString()
      : '',
    passRate:    r.total_tests > 0 ? r.passed_count / r.total_tests : 0,
    branch:      r.branch  ?? undefined,
    project:     undefined,
    totalTests:  r.total_tests,
    failedCount: r.failed_count,
  };
}

// ─────────────────────────────────────────────────────────────
// useCatalogue — feeds the dimension pickers
// ─────────────────────────────────────────────────────────────

// Returned by GET /api/owner-stats
interface ApiOwnerStat {
  owner:            string;
  total_tests:      number;
  failing_tests:    number;
  total_executions: number;
  failed_executions: number;
  failure_rate:     number;
  run_count:        number;
}

interface ApiOwnerStatsResponse {
  total_runs: number;
  owners:     ApiOwnerStat[];
}

export function useCatalogue() {
  const { currentProject } = useProject();

  const [runs,   setRuns]   = useState<Run[]>([]);
  const [owners, setOwners] = useState<Owner[]>([]);
  const [suites, setSuites] = useState<Suite[]>([]);

  useEffect(() => {
    let cancelled = false;

    const params = new URLSearchParams({ limit: '50' });
    if (currentProject) params.set('project', currentProject);

    // Fetch available runs for the RunPicker
    const fetchRuns = fetch(`/api/compare/runs?${params}`)
      .then(r => r.ok ? r.json() as Promise<ApiAvailableRun[]> : Promise.reject(r.statusText))
      .then(data => {
        if (!cancelled) setRuns(data.map(apiAvailableRunToRun));
      });

    const ownerParams = new URLSearchParams();
    if (currentProject) ownerParams.set('project', currentProject);

    const facetParams = new URLSearchParams({ limit: '20' });
    if (currentProject) facetParams.set('project', currentProject);

    const fetchFacets = fetch(`/api/compare/facets?${facetParams}`)
      .then(r => r.ok ? r.json() as Promise<ApiCompareFacetsResponse> : Promise.reject(r.statusText));

    const fetchOwnerStats = fetch(`/api/owner-stats?${ownerParams}`)
      .then(r => r.ok ? r.json() as Promise<ApiOwnerStatsResponse> : Promise.reject(r.statusText));

    Promise.allSettled([fetchFacets, fetchOwnerStats]).then(([facetsResult, ownerStatsResult]) => {
      if (cancelled) return;

      const statsMap = new Map<string, ApiOwnerStat>();
      if (ownerStatsResult.status === 'fulfilled') {
        for (const s of ownerStatsResult.value.owners) {
          statsMap.set(s.owner, s);
        }
      }

      const facetOwners = facetsResult.status === 'fulfilled' ? facetsResult.value.owners : [];
      const facetSuites = facetsResult.status === 'fulfilled' ? facetsResult.value.suites : [];

      if (facetOwners.length > 0) {
        setOwners(facetOwners.map(({ name, test_count }) => {
          const s = statsMap.get(name);
          return {
            id:          name,
            name,
            testCount:   s?.total_tests   ?? test_count,
            flakyCount:  0,
            failureRate: s?.failure_rate  ?? 0,
          };
        }));
      } else if (ownerStatsResult.status === 'fulfilled') {
        setOwners(ownerStatsResult.value.owners.map(s => ({
          id:          s.owner,
          name:        s.owner,
          testCount:   s.total_tests,
          flakyCount:  0,
          failureRate: s.failure_rate,
        })));
      }

      if (facetSuites.length > 0) {
        setSuites(facetSuites.map(({ name, test_count }) => ({
          id: name, name, testCount: test_count, failureRate: 0, flakyCount: 0,
        })));
      }
    });

    Promise.allSettled([fetchRuns]);

    return () => { cancelled = true; };
  }, [currentProject]);

  return { owners, runs, suites };
}

// ─────────────────────────────────────────────────────────────
// useCompareData — executes the compare query
// ─────────────────────────────────────────────────────────────

interface UseCompareDataReturn {
  /** Populated for latest_vs_previous mode (pairwise). */
  result:        ComparisonResult | null;
  /** Populated for last5 / last10 / custom modes (multi-run history matrix). */
  historyResult: HistoryResult | null;
  /** Raw entity payload for owners / suites dimensions. */
  entityResult:  ApiEntityCompareResult | null;
  loading:       boolean;
  error:         string | null;
}

export function useCompareData(state: CompareState): UseCompareDataReturn {
  const { currentProject } = useProject();

  const [result,        setResult]        = useState<ComparisonResult | null>(null);
  const [historyResult, setHistoryResult] = useState<HistoryResult | null>(null);
  const [entityResult,  setEntityResult]  = useState<ApiEntityCompareResult | null>(null);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState<string | null>(null);

  const isRunsDimension = state.dimension === 'runs';
  const isEntityDimension = state.dimension === 'owners' || state.dimension === 'suites';
  const isCustomMode    = state.timeMode === 'custom';
  const isWindowMode    = state.timeMode === 'last5' || state.timeMode === 'last10';
  const isManualPairMode = isCustomMode && state.customRunIds.length === 2;
  const shouldShowPairwise = isRunsDimension && (state.timeMode === 'latest_vs_previous' || isWindowMode || isManualPairMode);
  const shouldShowHistory = isRunsDimension && (isWindowMode || (isCustomMode && state.customRunIds.length !== 2));

  const canFetch = isRunsDimension
    ? (isCustomMode ? state.customRunIds.length >= 1 : true)
    : isEntityDimension
      ? state.selections.length >= 2   // always fetchable; uses limit or run_ids as available
      : state.selections.length >= 2;

  const cacheKey = [
    state.dimension,
    state.timeMode,
    state.customRunIds.join(','),
    state.selections.join(','),
    currentProject,
  ].join('|');

  useEffect(() => {
    if (!canFetch) {
      setResult(null);
      setHistoryResult(null);
      setEntityResult(null);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;

    setResult(null);
    setHistoryResult(null);
    setEntityResult(null);

    async function fetchComparison() {
      setLoading(true);
      setError(null);

      try {
        if (state.dimension === 'runs') {
          let data: ApiCompareResult;

          if (state.timeMode === 'custom') {
            // POST /api/compare/custom — explicit multi-run set
            const res = await fetch('/api/compare/custom', {
              method:  'POST',
              headers: { 'Content-Type': 'application/json' },
              body:    JSON.stringify({ run_ids: state.customRunIds, filters: {} }),
            });
            if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
            data = await res.json();
          } else {
            // GET /api/compare/history — sliding window of N most recent runs
            const params = new URLSearchParams({
              limit: String(timeModeToLimit(state.timeMode)),
            });
            if (currentProject) params.set('project', currentProject);
            const res = await fetch(`/api/compare/history?${params}`);
            if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
            data = await res.json();
          }

          if (!cancelled) {
            setResult(shouldShowPairwise ? apiToPairwiseResult(data) : null);
            setHistoryResult(shouldShowHistory ? apiToHistoryResult(data) : null);
            setLoading(false);
          }

        } else if (state.dimension === 'owners' || state.dimension === 'suites') {
          const isOwners = state.dimension === 'owners';
          // Use run_ids when custom IDs are present (regardless of timeMode),
          // otherwise fall back to a limit derived from the window mode.
          const hasCustomRuns = state.customRunIds.length > 0;
          const runSpec = hasCustomRuns
            ? { run_ids: state.customRunIds }
            : { limit: timeModeToLimit(state.timeMode) };
          const body = isOwners
            ? {
                owner_a: state.selections[0],
                owner_b: state.selections[1],
                ...(state.selections[2] ? { owner_c: state.selections[2] } : {}),
                ...runSpec,
                project: currentProject ?? undefined,
              }
            : {
                suite_a: state.selections[0],
                suite_b: state.selections[1],
                ...(state.selections[2] ? { suite_c: state.selections[2] } : {}),
                ...runSpec,
                project: currentProject ?? undefined,
              };
          const res = await fetch(`/api/compare/${state.dimension}`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(body),
          });
          if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
          const entityData: ApiEntityCompareResult = await res.json();
          if (!cancelled) {
            setEntityResult(entityData);
            setResult(apiEntityToResult(entityData));
            setLoading(false);
          }

        } else {
          throw new Error(`The '${state.dimension}' dimension is not yet supported.`);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Comparison failed');
          setLoading(false);
        }
      }
    }

    void fetchComparison();
    return () => { cancelled = true; };
  }, [cacheKey, canFetch]); // eslint-disable-line react-hooks/exhaustive-deps

  return { result, historyResult, entityResult, loading, error };
}
