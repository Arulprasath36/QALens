// ─────────────────────────────────────────────────────────────
// Core domain types for the QA Lens Compare Engine
// ─────────────────────────────────────────────────────────────

export type CompareDimension = 'runs' | 'owners' | 'suites';
export type TimeMode = 'last5' | 'last10' | 'latest_vs_previous' | 'custom';
export type TestStatus = 'passed' | 'failed' | 'flaky' | 'skipped';
export type DeltaDirection = 'improved' | 'regressed' | 'stable' | 'broken' | 'new';

// ── Dimension metadata ───────────────────────────────────────

export interface DimensionConfig {
  label: string;
  icon: string;
  description: string;
  defaultTimeMode: TimeMode;
  maxSelections: number;
}

export const DIMENSION_CONFIG: Record<CompareDimension, DimensionConfig> = {
  runs: {
    label: 'Runs',
    icon: '⚡',
    description: 'Compare test results across run history',
    defaultTimeMode: 'latest_vs_previous',
    maxSelections: 2,
  },
  owners: {
    label: 'Owners',
    icon: '👤',
    description: 'Compare failure rates between engineers',
    defaultTimeMode: 'last5',
    maxSelections: 3,
  },
  suites: {
    label: 'Suites',
    icon: '📦',
    description: 'Compare health across test suites',
    defaultTimeMode: 'last10',
    maxSelections: 3,
  },
};

export const TIME_MODE_LABELS: Record<TimeMode, string> = {
  last5: 'Last 5 runs',
  last10: 'Last 10 runs',
  latest_vs_previous: 'Latest vs Previous',
  custom: 'Custom range',
};

// ── State ────────────────────────────────────────────────────

export interface CompareState {
  dimension: CompareDimension;
  timeMode: TimeMode;
  /** IDs of selected entities (owner names / suite names / run IDs / status values) */
  selections: string[];
  /** Only populated when timeMode === 'custom' */
  customRunIds: string[];
}

// ── Entity types ─────────────────────────────────────────────

export interface Owner {
  id: string;
  name: string;
  testCount: number;
  flakyCount: number;
  /** 0–1 */
  failureRate: number;
}

export interface Run {
  id: string;
  label: string;
  sequence: number;
  startedAt: string;
  /** 0–1 */
  passRate: number;
  branch?: string;
  project?: string;
  totalTests: number;
  failedCount: number;
}

export interface Suite {
  id: string;
  name: string;
  testCount: number;
  /** 0–1 */
  failureRate: number;
  flakyCount: number;
}

// ── Comparison output ─────────────────────────────────────────

export interface ComparisonMetrics {
  label: string;
  /** 0–1 */
  failureRate: number;
  flakyCount: number;
  newFailures: number;
  fixedTests: number;
  totalTests: number;
  passCount: number;
  failCount: number;
}

export interface ComparisonRow {
  testName: string;
  displayName: string;
  suite: string;
  owner?: string;
  statusA: TestStatus;
  statusB: TestStatus;
  delta: DeltaDirection;
  errorMessage?: string;
}

export interface ComparisonResult {
  metricsA: ComparisonMetrics;
  metricsB: ComparisonMetrics;
  metricsC?: ComparisonMetrics;
  rows: ComparisonRow[];
  timeLabel: string;
  contextLabel?: string;
}

// ── History / multi-run matrix types ─────────────────────────
// Used by last5, last10, and custom modes on the runs dimension.

export interface HistoryRunMeta {
  runId: string;
  sequence: number;
  label: string;
  startedAt: string | null;
  passRate: number;
  failedCount: number;
  totalTests: number;
}

export interface HistoryCell {
  runId: string;
  /** passed | failed | broken | skipped | absent */
  state: string;
  message: string | null;
}

export interface HistoryRow {
  testName: string;
  displayName: string;
  suite: string;
  owner: string | null;
  passRate: number;
  flipScore: number;
  /** stable | flaky | broken */
  classification: string;
  cells: HistoryCell[];
}

export interface HistorySummary {
  windowSize: number;
  uniqueTests: number;
  flakyTests: number;
  consistentlyBroken: number;
  stableTests: number;
  newFailuresLatest: number;
  fixedLatest: number;
}

export interface HistoryResult {
  runs: HistoryRunMeta[];
  summary: HistorySummary;
  rows: HistoryRow[];
}

/** True when the time mode is a multi-run history window, not pairwise. */
export function isHistoryMode(timeMode: TimeMode): boolean {
  return timeMode === 'last5' || timeMode === 'last10' || timeMode === 'custom';
}
