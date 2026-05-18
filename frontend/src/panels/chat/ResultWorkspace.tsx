import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  HistoryState,
  OwnerFailureRateResult,
  OwnerFlakyTestsResult,
  SharedSuiteFailuresResult,
  SuiteFailureRankingResult,
  OwnerSuiteRegressionsResult,
  OwnerTestGapResult,
  OwnerSuiteComparisonResult,
  OwnerWindowComparisonResult,
  QaLensResult,
  RiskRankingResult,
  RiskTier,
  ExceptionRetrievalResult,
  RunRetrievalResult,
  StabilityTrendResult,
  RootCauseInsightResult,
  PerformanceTimingResult,
  NewFailuresIntroducedResult,
  RunComparisonResult,
  FailureTrendResult,
  TestFixPlaybookResult,
} from './types';

const TIER_STYLES: Record<RiskTier, {
  badge: string;
  dot: string;
  value: string;
  ring: string;
}> = {
  CRITICAL: {
    badge: 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300',
    dot: 'bg-red-500',
    value: 'text-red-600 dark:text-red-300',
    ring: 'from-red-50 via-white to-red-100/70 dark:from-red-500/10 dark:via-slate-950 dark:to-red-500/5',
  },
  HIGH: {
    badge: 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300',
    dot: 'bg-orange-500',
    value: 'text-orange-600 dark:text-orange-300',
    ring: 'from-orange-50 via-white to-amber-100/70 dark:from-orange-500/10 dark:via-slate-950 dark:to-amber-500/10',
  },
  MEDIUM: {
    badge: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
    dot: 'bg-amber-500',
    value: 'text-amber-700 dark:text-amber-300',
    ring: 'from-amber-50 via-white to-yellow-100/70 dark:from-amber-500/10 dark:via-slate-950 dark:to-yellow-500/10',
  },
  LOW: {
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
    dot: 'bg-emerald-500',
    value: 'text-emerald-700 dark:text-emerald-300',
    ring: 'from-emerald-50 via-white to-green-100/70 dark:from-emerald-500/10 dark:via-slate-950 dark:to-green-500/10',
  },
};

function pct(value: number | undefined) {
  if (value == null || Number.isNaN(value)) return 'NA';
  return `${Math.round(value * 100)}%`;
}

function formatDurationMs(ms: number | null | undefined) {
  if (ms == null || Number.isNaN(ms)) return 'NA';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function normalizeResultTestName(testName: string) {
  return testName.trim().toLowerCase();
}

function panelHref(tab: string) {
  if (typeof window === 'undefined') return `?tab=${tab}`;
  const url = new URL(window.location.href);
  url.searchParams.set('tab', tab);
  return `${url.pathname}${url.search}${url.hash}`;
}

function historyLabel(history: HistoryState[] | undefined) {
  if (!history || history.length === 0) return 'No recent history available';
  return history.map(item => item === 'PASS' ? 'pass' : item === 'FAIL' ? 'fail' : item === 'SKIP' ? 'skip' : 'unknown').join(', ');
}

function HistoryStrip({ history }: { history?: HistoryState[] }) {
  if (!history || history.length === 0) {
    return <span className="text-xs text-slate-400 dark:text-slate-500">No recent history</span>;
  }

  return (
    <div className="flex max-w-full flex-wrap items-center gap-1" aria-label={`Recent history: ${historyLabel(history)}`}>
      {history.map((item, index) => (
        <span
          key={`${item}-${index}`}
          className={[
            'inline-flex h-4 w-4 items-center justify-center rounded-[5px] border text-[9px] font-semibold',
            item === 'PASS'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300'
              : item === 'FAIL'
                ? 'border-red-200 bg-red-50 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
                : item === 'SKIP'
                  ? 'border-slate-200 bg-slate-50 text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-500'
                  : 'border-slate-200 bg-slate-50 text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-500',
          ].join(' ')}
          aria-hidden="true"
        >
          {item === 'PASS' ? '✓' : item === 'FAIL' ? '×' : item === 'SKIP' ? '•' : '·'}
        </span>
      ))}
    </div>
  );
}

function TierBadge({ tier }: { tier: RiskTier }) {
  const style = TIER_STYLES[tier];
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold tracking-[0.12em] ${style.badge}`}>
      <span className={`inline-block h-2 w-2 rounded-full ${style.dot}`} />
      {tier}
    </span>
  );
}

function MiniStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-2 break-words text-2xl font-semibold leading-tight tracking-tight text-slate-950 dark:text-slate-50">{value}</p>
    </div>
  );
}

function statusBadgeClass(status: string) {
  if (status === 'passed') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300';
  }
  if (status === 'failed' || status === 'broken') {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300';
  }
  if (status === 'skipped') {
    return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';
  }
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';
}

function classificationBadgeClass(classification: string) {
  const normalized = classification.toLowerCase();
  if (normalized.includes('flaky')) {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300';
  }
  if (normalized.includes('broken')) {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300';
  }
  if (normalized.includes('stable')) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300';
  }
  if (normalized.includes('consistent')) {
    return 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300';
  }
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';
}

function causeFamilyBadgeClass(family: string) {
  const normalized = family.toLowerCase();
  if (normalized.includes('ui') || normalized.includes('test script')) {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300';
  }
  if (normalized.includes('product') || normalized.includes('backend')) {
    return 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300';
  }
  if (normalized.includes('environment') || normalized.includes('service')) {
    return 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300';
  }
  if (normalized.includes('data')) {
    return 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-300';
  }
  if (normalized.includes('configuration')) {
    return 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300';
  }
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';
}

function useCopySummary(summaryText: string) {
  const [copied, setCopied] = useState(false);

  function handleCopySummary() {
    navigator.clipboard.writeText(summaryText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return { copied, handleCopySummary };
}


type WorkspaceEvidenceTest = {
  type: 'test';
  canonical_name: string;
  title: string;
  classification: string;
  risk_tier: string;
  risk_pct: number;
  pass_rate: number;
  flip_score: number;
  run_count: number;
  sparkline: string;
  why_relevant: string[];
  recent_runs: { run_id: string; run_label: string; status: string; timestamp: string }[];
  most_frequent_error: { category: string; message: string } | null;
};

function EvidenceDrawer({
  item,
  onClose,
}: {
  item: RiskRankingResult['ranking'][number];
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const evidence = item.evidence ?? [];
  const signals = item.signals ?? {};
  const failBurden = signals.failureBurden ?? (1 - item.passRate);
  const failStreak = signals.failStreak ?? 0;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-950/30 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <aside
        ref={panelRef}
        tabIndex={-1}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950"
        aria-label={`Evidence details for ${item.testName}`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5 dark:border-slate-800">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Selected test</p>
            <h3 className="mt-2 truncate font-mono text-lg font-semibold text-slate-950 dark:text-slate-50">{item.testName}</h3>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <TierBadge tier={item.riskTier} />
              <span className="text-sm text-slate-600 dark:text-slate-300">Pass rate: <span className="font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.passRate * 100)}%</span></span>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close evidence drawer"
            className="rounded-full border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-200"
          >
            <svg viewBox="0 0 14 14" fill="none" className="h-4 w-4">
              <path d="M2 2l10 10M12 2 2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <section className="space-y-2">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Why it ranked high</h4>
            <p className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
              {item.primaryReason}
            </p>
          </section>

          <section className="space-y-3">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Signal breakdown</h4>
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                ['Volatility', pct(signals.volatility)],
                ['Failure burden', pct(failBurden)],
                ['Recent decline', pct(signals.recentDecline)],
                ['Fail streak', failStreak ? `${failStreak} fail${failStreak === 1 ? '' : 's'}` : 'NA'],
                ['Duration spike', pct(signals.durationSpike)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
                  <p className="mt-2 text-base font-semibold text-slate-950 dark:text-slate-50">{value}</p>
                </div>
              ))}
            </div>
          </section>

          {evidence.length > 0 && (
            <section className="space-y-3">
              <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Evidence</h4>
              <div className="space-y-2">
                {evidence.map((entry, index) => (
                  <div key={`${entry.label}-${index}`} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{entry.label}</p>
                    <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">{entry.value}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-3">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Recent history</h4>
            <HistoryStrip history={item.history} />
          </section>

          <section className="space-y-3">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Formula used</h4>
            <pre className="overflow-x-auto rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 font-mono text-sm leading-7 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">{`risk = 0.30 × volatility
+ 0.25 × failure_burden
+ 0.25 × recent_decline
+ 0.15 × fail_streak
+ 0.05 × duration_spike`}</pre>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              This ranking is based on the blended QaLens risk formula, not pass rate alone.
            </p>
          </section>
        </div>
      </aside>
    </>
  );
}

function RiskWorkspace({
  result,
  loading,
}: {
  result: RiskRankingResult;
  loading: boolean;
}) {
  const [selected, setSelected] = useState<RiskRankingResult['ranking'][number] | null>(null);

  const lowestPassRate = useMemo(() => {
    if (result.summary.lowestPassRate != null) return Math.round(result.summary.lowestPassRate * 100);
    if (result.ranking.length === 0) return null;
    return Math.round(Math.min(...result.ranking.map(item => item.passRate)) * 100);
  }, [result]);

  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Ranked by QaLens risk score across the selected run window',
      `Scope: ${result.scope.label}${result.scope.windowEnd ? ` • Ends at ${result.scope.windowEnd}` : ''}`,
      `Eligible tests: ${result.scope.eligibleTests}`,
      `High risk: ${result.summary.highRisk}`,
      `Medium risk: ${result.summary.mediumRisk}`,
      `Low risk: ${result.summary.lowRisk}`,
      ...(lowestPassRate != null ? [`Lowest pass rate: ${lowestPassRate}%`] : []),
      '',
      'Top ranked tests:',
      ...result.ranking.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.testName} — ${item.riskTier} · ${Math.round(item.passRate * 100)}% pass rate · ${item.primaryReason}`,
      ),
    ];
    return lines.join('\n');
  }, [lowestPassRate, result]);

  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <EvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Ranked by QaLens risk score across the selected run window'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            {result.scope.windowEnd && (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                Ends at {result.scope.windowEnd}
              </span>
            )}
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Eligible tests" value={String(result.scope.eligibleTests)} />
        <MiniStat label="High risk" value={String(result.summary.highRisk)} />
        <MiniStat label="Medium risk" value={String(result.summary.mediumRisk)} />
        <MiniStat label="Lowest pass rate" value={lowestPassRate == null ? 'NA' : `${lowestPassRate}%`} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Ranked risk list</h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Decision-first ranking with reasons, pass rate, and recent history.</p>
            </div>
            {loading && <span className="text-xs text-slate-500 dark:text-slate-400">Refreshing evidence…</span>}
          </div>
        </div>

        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.ranking.map(item => {
            const tierStyle = TIER_STYLES[item.riskTier];
            return (
              <div
                key={`${item.rank}-${item.testName}`}
                className="px-6 py-5"
                data-result-test={normalizeResultTestName(item.testName)}
              >
                <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                  <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                    {String(item.rank).padStart(2, '0')}
                  </div>

                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-3">
                      <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                        {item.testName}
                      </code>
                      <TierBadge tier={item.riskTier} />
                    </div>
                    <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
                      <span className="font-medium text-slate-950 dark:text-slate-50">Pass rate:</span>{' '}
                      <span className={tierStyle.value}>{Math.round(item.passRate * 100)}%</span>
                    </p>
                    <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">
                      <span className="font-medium text-slate-950 dark:text-slate-50">Primary reason:</span>{' '}
                      {item.primaryReason}
                    </p>
                  </div>

                  <div className="min-w-0 space-y-3 xl:pl-2">
                    <div className="space-y-2">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">History</p>
                      <HistoryStrip history={item.history} />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => setSelected(item)}
                        aria-label={`Open evidence for ${item.testName}`}
                        className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                      >
                        Open evidence
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-3 text-sm text-slate-600 dark:text-slate-300">
            <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 text-slate-400 dark:border-slate-700 dark:text-slate-500">i</span>
            <p className="leading-6">
              Risk score is a blended priority score. “Fail next run” and “Flip next run” are separate likelihoods to help distinguish repeat failure from state changes.
            </p>
          </div>
          <a
            href={panelHref('risk')}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            View full details →
          </a>
        </div>
      </div>
    </div>
  );
}

function WorkspaceEmptyState() {
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/80 px-8 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
      <div className="max-w-md space-y-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">Structured results show up here</h2>
        <p className="text-sm leading-7 text-slate-600 dark:text-slate-300">
          Ask a question like “What tests are most likely to fail next?” and QaLens will keep the conversation on the left while rendering ranked evidence and drill-down analysis here.
        </p>
      </div>
    </div>
  );
}

function OwnerGapEvidenceDrawer({
  item,
  onClose,
}: {
  item: OwnerTestGapResult['tests'][number];
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [evidence, setEvidence] = useState<WorkspaceEvidenceTest | null>(null);
  const [loading, setLoading] = useState(Boolean(item.canonicalName));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    panelRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    if (!item.canonicalName) {
      setLoading(false);
      setEvidence(null);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    setError(null);
    setEvidence(null);
    fetch(`/api/evidence/test/${encodeURIComponent(item.canonicalName)}`)
      .then(response => response.ok ? response.json() as Promise<WorkspaceEvidenceTest> : Promise.reject(`API ${response.status}`))
      .then(payload => {
        if (!cancelled && payload.type === 'test') {
          setEvidence(payload);
        }
      })
      .catch(err => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item.canonicalName]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-950/30 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <aside
        ref={panelRef}
        tabIndex={-1}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950"
        aria-label={`Evidence details for ${item.testName}`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5 dark:border-slate-800">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Selected test</p>
            <h3 className="mt-2 truncate font-mono text-lg font-semibold text-slate-950 dark:text-slate-50">{item.testName}</h3>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <TierBadge tier={item.riskTier} />
              <span className="text-sm text-slate-600 dark:text-slate-300">Pass rate: <span className="font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.passRate * 100)}%</span></span>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close evidence drawer"
            className="rounded-full border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-200"
          >
            <svg viewBox="0 0 14 14" fill="none" className="h-4 w-4">
              <path d="M2 2l10 10M12 2 2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <section className="space-y-2">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Why this test stands out</h4>
            <p className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
              {item.primaryReason}
            </p>
          </section>

          <section className="grid gap-3 sm:grid-cols-2">
            {[
              ['Current status', item.currentStatus],
              ['Suite', item.suite ?? 'Unknown suite'],
              ['Failures in scope', String(item.failCount)],
              ['Pass rate', `${Math.round(item.passRate * 100)}%`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
                <p className="mt-2 text-base font-semibold capitalize text-slate-950 dark:text-slate-50">{value}</p>
              </div>
            ))}
          </section>

          {item.errorMessage && (
            <section className="space-y-2">
              <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest error</h4>
              <div className="rounded-2xl border border-red-100 bg-red-50/70 px-4 py-3 font-mono text-sm text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
                {item.errorMessage}
              </div>
            </section>
          )}

          <section className="space-y-2">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">History</h4>
            <HistoryStrip history={item.history} />
          </section>

          {loading && <p className="text-sm text-slate-500 dark:text-slate-400">Loading deeper evidence…</p>}
          {error && <p className="text-sm text-red-600 dark:text-red-300">Failed to load evidence: {error}</p>}

          {evidence && (
            <>
              <section className="space-y-3">
                <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Deeper signals</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                  {[
                    ['Classification', evidence.classification],
                    ['Risk tier', evidence.risk_tier.toUpperCase()],
                    ['Risk score', `${Math.round(evidence.risk_pct)}%`],
                    ['Flip score', `${Math.round(evidence.flip_score * 100)}%`],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
                      <p className="mt-2 text-base font-semibold text-slate-950 dark:text-slate-50">{value}</p>
                    </div>
                  ))}
                </div>
              </section>

              {evidence.why_relevant.length > 0 && (
                <section className="space-y-2">
                  <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Why relevant</h4>
                  <ul className="space-y-2">
                    {evidence.why_relevant.map((reason, index) => (
                      <li key={`${reason}-${index}`} className="flex gap-2 text-sm leading-6 text-slate-700 dark:text-slate-200">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400 dark:bg-slate-500" />
                        <span>{reason}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {evidence.most_frequent_error && (
                <section className="space-y-2">
                  <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Frequent error</h4>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                    <span className="font-semibold text-slate-950 dark:text-slate-50">{evidence.most_frequent_error.category}:</span>{' '}
                    {evidence.most_frequent_error.message}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function OwnerFailureRateDrawer({
  item,
  onClose,
}: {
  item: OwnerFailureRateResult['ranking'][number];
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-950/30 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <aside
        ref={panelRef}
        tabIndex={-1}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950"
        aria-label={`Owner failure rate details for ${item.ownerName}`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5 dark:border-slate-800">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Selected owner</p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{item.ownerName}</h3>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              Failure rate: <span className="font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.failureRate * 100)}%</span>
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close owner details drawer"
            className="rounded-full border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-200"
          >
            <svg viewBox="0 0 14 14" fill="none" className="h-4 w-4">
              <path d="M2 2l10 10M12 2 2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <section className="space-y-2">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Why this owner stands out</h4>
            <p className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
              {item.primaryReason}
            </p>
          </section>

          <section className="grid gap-3 sm:grid-cols-2">
            {[
              ['Failure rate', `${Math.round(item.failureRate * 100)}%`],
              ['Failed executions', String(item.failedExecutions)],
              ['Total executions', String(item.totalExecutions)],
              ['Failing tests', `${item.failingTests}/${item.totalTests}`],
              ['Runs observed', String(item.runCount)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</p>
                <p className="mt-2 text-base font-semibold text-slate-950 dark:text-slate-50">{value}</p>
              </div>
            ))}
          </section>

          {item.evidence && item.evidence.length > 0 && (
            <section className="space-y-3">
              <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Evidence</h4>
              <div className="space-y-2">
                {item.evidence.map((entry, index) => (
                  <div key={`${entry.label}-${index}`} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{entry.label}</p>
                    <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">{entry.value}</p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}

function OwnerRateBadge({
  emphasis,
}: {
  emphasis?: 'highest_rate' | 'most_failures';
}) {
  const tone = emphasis === 'highest_rate'
    ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
    : 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300';
  const label = emphasis === 'highest_rate' ? 'Highest rate' : 'Most failures';

  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${tone}`}>
      {label}
    </span>
  );
}

function OwnerFailureRateWorkspace({
  result,
}: {
  result: OwnerFailureRateResult;
}) {
  const [selected, setSelected] = useState<OwnerFailureRateResult['ranking'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Failure-rate ranking by owner across current all-time ownership history',
      `Scope: ${result.scope.label}${result.scope.totalRuns != null ? ` • ${result.scope.totalRuns} total runs` : ''}`,
      `Owners ranked: ${result.scope.owners}`,
      `Highest failure rate: ${Math.round(result.summary.highestFailureRate * 100)}%`,
      `Most failures: ${result.summary.mostFailures}`,
      `Most failing tests: ${result.summary.mostFailingTests}`,
      '',
      'Top owners:',
      ...result.ranking.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.ownerName} — ${Math.round(item.failureRate * 100)}% failure rate · ${item.failingTests}/${item.totalTests} failing tests · ${item.primaryReason}`,
      ),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <OwnerFailureRateDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Failure-rate ranking by owner across current all-time ownership history'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            {result.scope.totalRuns != null && (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                {result.scope.totalRuns} total runs
              </span>
            )}
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Owners ranked" value={String(result.scope.owners)} />
        <MiniStat label="Highest failure rate" value={`${Math.round(result.summary.highestFailureRate * 100)}%`} />
        <MiniStat label="Most failures" value={String(result.summary.mostFailures)} />
        <MiniStat label="Most failing tests" value={String(result.summary.mostFailingTests)} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Owner failure ranking</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Current-owner rollup of failure rate, burden, and failing test concentration.</p>
        </div>

        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.ranking.map(item => (
            <div key={`${item.rank}-${item.ownerName}`} className="px-6 py-5">
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="truncate text-lg font-semibold tracking-tight text-slate-950 dark:text-slate-50">
                      {item.ownerName}
                    </span>
                    {item.emphasis && <OwnerRateBadge emphasis={item.emphasis} />}
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Failure rate:</span>{' '}
                    <span className="text-red-600 dark:text-red-300">{Math.round(item.failureRate * 100)}%</span>
                  </p>
                  <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Primary reason:</span>{' '}
                    {item.primaryReason}
                  </p>
                </div>

                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Executions</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.failedExecutions}/{item.totalExecutions}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Failing tests</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.failingTests}/{item.totalTests}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => setSelected(item)}
                      aria-label={`Open owner evidence for ${item.ownerName}`}
                      className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                    >
                      Open evidence
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function OwnerFlakyTestsWorkspace({
  result,
}: {
  result: OwnerFlakyTestsResult;
}) {
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Owner-level rollup of flaky test concentration.',
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      `Owners ranked: ${result.scope.owners}`,
      `Highest flaky-test count: ${result.summary.highestFlakyCount}`,
      `Average flip score: ${Math.round(result.summary.avgFlipScore * 100)}%`,
      `Average pass rate: ${Math.round(result.summary.avgPassRate * 100)}%`,
      '',
      'Top owners:',
      ...result.ranking.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.ownerName} — ${item.flakyCount} flaky tests · ${Math.round(item.avgFlipScore * 100)}% avg flip score · ${Math.round(item.avgPassRate * 100)}% avg pass rate`,
      ),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Owner-level rollup of flaky test concentration.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.totalEvaluated} flaky tests evaluated
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Owners ranked" value={String(result.scope.owners)} />
        <MiniStat label="Highest flaky count" value={String(result.summary.highestFlakyCount)} />
        <MiniStat label="Avg flip score" value={`${Math.round(result.summary.avgFlipScore * 100)}%`} />
        <MiniStat label="Avg pass rate" value={`${Math.round(result.summary.avgPassRate * 100)}%`} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          This view ranks owners by how many flaky tests they currently carry in the selected scope, with volatility used to break ties.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Owner flaky ranking</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Owners ranked by flaky-test concentration across the selected scope.</p>
        </div>

        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.ranking.map(item => (
            <div key={`${item.rank}-${item.ownerName}`} className="px-6 py-5">
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(320px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <span className="truncate text-lg font-semibold tracking-tight text-slate-950 dark:text-slate-50">
                    {item.ownerName}
                  </span>
                  <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Flaky tests:</span>{' '}
                    <span className="text-amber-600 dark:text-amber-300">{item.flakyCount}</span> of {item.totalTests}
                  </p>
                  <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Primary reason:</span>{' '}
                    {item.primaryReason}
                  </p>
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Avg flip score</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.avgFlipScore * 100)}%</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Avg pass rate</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.avgPassRate * 100)}%</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Top flaky tests</p>
                    <div className="space-y-2">
                      {item.topTests.map(test => (
                        <div key={`${item.ownerName}-${test.testName}`} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                          <code className="block truncate font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{test.testName}</code>
                          <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                            {Math.round(test.flipScore * 100)}% flip score · {Math.round(test.passRate * 100)}% pass rate
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SuiteDeltaCard({
  title,
  subtitle,
  count,
}: {
  title: string;
  subtitle: string;
  count: number;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{title}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{count}</p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
    </div>
  );
}

function OwnerSuiteComparisonWorkspace({
  result,
}: {
  result: OwnerSuiteComparisonResult;
}) {
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Current-owner suite overlap and unique suite ownership.',
      `Compared owners: ${result.owners.ownerA} vs ${result.owners.ownerB}`,
      `Shared suites: ${result.summary.sharedSuites}`,
      `${result.owners.ownerA}-only suites: ${result.summary.ownerAOnlySuites}`,
      `${result.owners.ownerB}-only suites: ${result.summary.ownerBOnlySuites}`,
      '',
      `${result.owners.ownerA} only:`,
      ...(result.ownerAOnly.length > 0
        ? result.ownerAOnly.slice(0, 5).map(item => `- ${item.suiteName} (${item.tests} tests)`)
        : ['- none']),
      '',
      `${result.owners.ownerB} only:`,
      ...(result.ownerBOnly.length > 0
        ? result.ownerBOnly.slice(0, 5).map(item => `- ${item.suiteName} (${item.tests} tests)`)
        : ['- none']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Current-owner suite overlap and unique suite ownership. Ask QaLens to narrow this to a specific run window for recent health.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <SuiteDeltaCard title="Shared suites" subtitle="Owned by both engineers" count={result.summary.sharedSuites} />
        <SuiteDeltaCard title={result.owners.ownerA} subtitle="Unique suites" count={result.summary.ownerAOnlySuites} />
        <SuiteDeltaCard title={result.owners.ownerB} subtitle="Unique suites" count={result.summary.ownerBOnlySuites} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_1fr_1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
          <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
            <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Shared suites</h3>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Suites both owners currently touch under the latest ownership mapping.</p>
          </div>
          <div className="divide-y divide-slate-200 dark:divide-slate-800">
            {result.shared.length === 0 ? (
              <div className="px-5 py-5 text-sm text-slate-500 dark:text-slate-400">No shared suites were found.</div>
            ) : result.shared.map(item => (
              <div key={item.suiteName} className="px-5 py-4">
                <p className="font-medium text-slate-950 dark:text-slate-50">{item.suiteName}</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.owners.ownerA}</p>
                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">{item.ownerATests} tests</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.owners.ownerB}</p>
                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">{item.ownerBTests} tests</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {[
          { title: `${result.owners.ownerA} only`, owner: result.owners.ownerA, suites: result.ownerAOnly },
          { title: `${result.owners.ownerB} only`, owner: result.owners.ownerB, suites: result.ownerBOnly },
        ].map(section => (
          <div key={section.title} className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
              <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{section.title}</h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Suites unique to this owner in the current ownership model.</p>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-slate-800">
              {section.suites.length === 0 ? (
                <div className="px-5 py-5 text-sm text-slate-500 dark:text-slate-400">No owner-only suites were found.</div>
              ) : section.suites.map(item => (
                <div key={item.suiteName} className="px-5 py-4">
                  <p className="font-medium text-slate-950 dark:text-slate-50">{item.suiteName}</p>
                  <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">
                    {item.tests} tests
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
          This view shows the current suite ownership split only. If you want to compare recent health within these suites, ask QaLens to narrow the analysis to a time window like the last 5 or 10 runs.
        </p>
      </div>
    </div>
  );
}

function OwnerWindowComparisonWorkspace({
  result,
}: {
  result: OwnerWindowComparisonResult;
}) {
  const isSingleRun = result.owners.runCount === 1;
  const leaderIsA = result.summary.leader === result.owners.ownerA;
  const leaderMetrics = leaderIsA ? result.metrics.ownerA : result.metrics.ownerB;
  const laggerMetrics = leaderIsA ? result.metrics.ownerB : result.metrics.ownerA;
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? (isSingleRun ? 'Latest-run owner comparison' : 'Recent owner comparison across the selected run window'),
      `Scope: ${result.owners.timeLabel} • ${result.owners.runCount} run${result.owners.runCount === 1 ? '' : 's'} compared`,
      `Leader: ${result.summary.leader}`,
      `Pass-rate gap: ${Math.round(result.summary.passRateGap * 100)}%`,
      `Flaky-test gap: ${result.summary.flakyGap}`,
      `Regression gap: ${result.summary.regressionGap}`,
      '',
      `${result.owners.ownerA}: ${Math.round(result.metrics.ownerA.passRate * 100)}% pass rate · ${result.metrics.ownerA.regressed} regressed · ${result.metrics.ownerA.recovered} recovered · ${result.metrics.ownerA.flakyCount} flaky`,
      `${result.owners.ownerB}: ${Math.round(result.metrics.ownerB.passRate * 100)}% pass rate · ${result.metrics.ownerB.regressed} regressed · ${result.metrics.ownerB.recovered} recovered · ${result.metrics.ownerB.flakyCount} flaky`,
    ];
    return lines.join('\n');
  }, [isSingleRun, result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? (isSingleRun ? 'Latest-run owner comparison' : 'Recent owner comparison across the selected run window')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.owners.timeLabel}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.owners.runCount} runs compared
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Recent leader" value={result.summary.leader} />
        <MiniStat label="Pass-rate gap" value={`${Math.round(result.summary.passRateGap * 100)}%`} />
        <MiniStat label="Flaky-test gap" value={String(result.summary.flakyGap)} />
        <MiniStat label="Regression gap" value={String(result.summary.regressionGap)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          {result.summary.leader} is leading {isSingleRun ? 'in the latest run' : 'in this selected window'} with a {Math.round(leaderMetrics.passRate * 100)}% pass rate versus{' '}
          {Math.round(laggerMetrics.passRate * 100)}%, while carrying {leaderMetrics.flakyCount} flaky tests versus {laggerMetrics.flakyCount} and
          showing {leaderMetrics.regressed} regressed tests versus {laggerMetrics.regressed}. This is a {isSingleRun ? 'single-run' : 'recent-window'} comparison, not an all-time owner ranking.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {[
          { owner: result.owners.ownerA, metrics: result.metrics.ownerA },
          { owner: result.owners.ownerB, metrics: result.metrics.ownerB },
        ].map(section => (
          <div key={section.owner} className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{section.owner}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Pass rate</p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-50">{Math.round(section.metrics.passRate * 100)}%</p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{isSingleRun ? 'Within the latest run' : 'Across the selected run window'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Failure rate</p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-50">{Math.round(section.metrics.failureRate * 100)}%</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Failed tests</p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-50">{section.metrics.failed}/{section.metrics.totalTests}</p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Currently failing in the latest run</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Flaky tests</p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-50">{section.metrics.flakyCount}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Regressed</p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-50">{section.metrics.regressed}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Recovered</p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-50">{section.metrics.recovered}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {[
          { owner: result.owners.ownerA, items: result.topRisks.ownerA },
          { owner: result.owners.ownerB, items: result.topRisks.ownerB },
        ].map(section => (
          <div key={section.owner} className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
              <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{section.owner} top failing tests</h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Highest failure counts in the selected comparison window.</p>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-slate-800">
              {section.items.length === 0 ? (
                <div className="px-5 py-5 text-sm text-slate-500 dark:text-slate-400">No failing tests were found in this window.</div>
              ) : section.items.map((item, index) => (
                <div key={`${item.testName}-${index}`} className="px-5 py-4">
                  <p className="font-mono text-sm font-semibold text-slate-950 dark:text-slate-50">{item.testName}</p>
                  <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">
                    {item.suite ? `${item.suite} · ` : ''}{item.failCount} failure{item.failCount !== 1 ? 's' : ''} in window
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OwnerTestGapWorkspace({
  result,
}: {
  result: OwnerTestGapResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const isFailingMode = result.mode === 'failing_tests';
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? `Focused test-level view for ${result.owner}.`,
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      `Currently failing: ${result.summary.currentlyFailing}`,
      `Regressed: ${result.summary.regressed}`,
      `Flaky: ${result.summary.flaky}`,
      ...(result.summary.topSuite ? [`Top suite: ${result.summary.topSuite}`] : []),
      '',
      isFailingMode ? 'Currently failing tests:' : 'Top drivers:',
      ...result.tests.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.testName} — ${Math.round(item.passRate * 100)}% pass rate · ${item.primaryReason}`,
      ),
    ];
    return lines.join('\n');
  }, [isFailingMode, result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? `Focused test-level view for ${result.owner}.`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.totalTests} tests
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Owner focus" value={result.owner} />
        <MiniStat label="Currently failing" value={String(result.summary.currentlyFailing)} />
        <MiniStat label="Regressed" value={String(result.summary.regressed)} />
        <MiniStat label="Flaky" value={String(result.summary.flaky)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          {isFailingMode
            ? `These are the tests currently failing for ${result.owner}, ranked by failure pressure and instability across ${result.scope.label.toLowerCase()}.`
            : `These are the tests contributing most to ${result.owner}&apos;s current comparison gap${result.comparedAgainst ? ` versus ${result.comparedAgainst}` : ''},
          prioritized by current failures, regressions, and instability across ${result.scope.label.toLowerCase()}.`}
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{isFailingMode ? 'Currently failing tests' : 'Top driver tests'}</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {isFailingMode
              ? 'Current failures for this owner across the selected scope.'
              : 'Current failures, regressions, and flakiness across the selected scope.'}
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.tests.map(item => (
            <div
              key={`${item.rank}-${item.testName}`}
              className="px-6 py-5"
              data-result-test={normalizeResultTestName(item.testName)}
            >
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                      {item.testName}
                    </code>
                    <TierBadge tier={item.riskTier} />
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span>{' '}
                    {item.suite ?? 'Unknown suite'}
                  </p>
                  <p className="mt-1 text-sm leading-7 text-slate-600 dark:text-slate-300">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Pass rate:</span>{' '}
                    <span className={TIER_STYLES[item.riskTier].value}>{Math.round(item.passRate * 100)}%</span>
                  </p>
                  <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Primary reason:</span>{' '}
                    {item.primaryReason}
                  </p>
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Status</p>
                      <p className="mt-1 text-sm font-semibold capitalize text-slate-950 dark:text-slate-50">{item.currentStatus}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Failures in scope</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.failCount}</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">History</p>
                    <HistoryStrip history={item.history} />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => setSelected(item)}
                      aria-label={`Open evidence for ${item.testName}`}
                      className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                    >
                      Open evidence
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function OwnerSuiteRegressionsWorkspace({
  result,
}: {
  result: OwnerSuiteRegressionsResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? `Suite-level regression view for ${result.owner}.`,
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      `Suites ranked: ${result.scope.totalSuites}`,
      `Regressed suites: ${result.summary.regressedSuites}`,
      `Currently failing suites: ${result.summary.currentlyFailingSuites}`,
      `Flaky suites: ${result.summary.flakySuites}`,
      ...(result.summary.topSuite ? [`Top suite: ${result.summary.topSuite}`] : []),
      '',
      'Top suite hotspots:',
      ...result.suites.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.suiteName} — ${item.regressed} regressed · ${item.currentlyFailing} currently failing · ${item.flaky} flaky tests`,
      ),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? `Suite-level regression view for ${result.owner}.`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.totalSuites} suites
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Owner focus" value={result.owner} />
        <MiniStat label="Regressed suites" value={String(result.summary.regressedSuites)} />
        <MiniStat label="Currently failing" value={String(result.summary.currentlyFailingSuites)} />
        <MiniStat label="Flaky suites" value={String(result.summary.flakySuites)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          These suites are creating the most regression pressure for {result.owner}{result.comparedAgainst ? ` versus ${result.comparedAgainst}` : ''},
          based on regressed tests, currently failing tests, and flaky tests across {result.scope.label.toLowerCase()}.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Suite hotspots</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Grouped by suite so it is easier to see where this owner&apos;s regressions are concentrated.</p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.suites.map(item => (
            <div key={`${item.rank}-${item.suiteName}`} className="px-6 py-5">
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.2fr)_minmax(0,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <p className="text-lg font-semibold tracking-tight text-slate-950 dark:text-slate-50">{item.suiteName}</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Regressed</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.regressed}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Currently failing</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.currentlyFailing}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Flaky tests</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.flaky}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Lowest pass rate</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.lowestPassRate * 100)}%</p>
                    </div>
                  </div>
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Top tests in this suite</p>
                    <div className="space-y-2">
                      {item.topTests.map(test => (
                        <div key={test.testName} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                          <div className="flex items-center justify-between gap-3">
                            <code className="truncate font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{test.testName}</code>
                            <button
                              onClick={() => setSelected({
                                rank: item.rank,
                                testName: test.testName,
                                canonicalName: test.canonicalName,
                                suite: item.suiteName,
                                passRate: test.passRate,
                                failCount: test.failCount,
                                currentStatus: test.currentStatus,
                                regressed: test.regressed,
                                flaky: test.flaky,
                                riskTier: test.regressed || test.currentStatus === 'failed' || test.currentStatus === 'broken' ? 'HIGH' : test.flaky ? 'MEDIUM' : 'LOW',
                                history: undefined,
                                primaryReason: `${test.failCount} failures in scope${test.regressed ? ' and recently regressed' : ''}.`,
                                errorMessage: test.errorMessage ?? null,
                              })}
                              className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                            >
                              Open evidence
                            </button>
                          </div>
                          <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                            {test.failCount} failure{test.failCount === 1 ? '' : 's'} · {Math.round(test.passRate * 100)}% pass rate
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SharedSuiteFailuresWorkspace({
  result,
}: {
  result: SharedSuiteFailuresResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Shared suites ranked by failure pressure.',
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      `Shared suites: ${result.summary.sharedSuites}`,
      ...(result.summary.topSuite ? [`Top suite: ${result.summary.topSuite}`] : []),
      '',
      'Top shared-suite hotspots:',
      ...result.suites.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.suiteName} — ${result.owners.ownerA}: ${item.ownerA.currentlyFailing} failing, ${result.owners.ownerB}: ${item.ownerB.currentlyFailing} failing`,
      ),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  function openEvidence(test: SharedSuiteFailuresResult['suites'][number]['ownerA']['topTests'][number], suiteName: string, rank: number) {
    setSelected({
      rank,
      testName: test.testName,
      canonicalName: test.canonicalName,
      suite: suiteName,
      passRate: test.passRate,
      failCount: test.failCount,
      currentStatus: test.currentStatus,
      regressed: test.regressed,
      flaky: test.flaky,
      riskTier: test.regressed || test.currentStatus === 'failed' || test.currentStatus === 'broken' ? 'HIGH' : test.flaky ? 'MEDIUM' : 'LOW',
      history: undefined,
      primaryReason: `${test.failCount} failures in scope${test.regressed ? ' and recently regressed' : ''}.`,
      errorMessage: test.errorMessage ?? null,
    });
  }

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Shared suites ranked by failure pressure.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.sharedSuites} shared suites
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <MiniStat label="Shared suites" value={String(result.summary.sharedSuites)} />
        <MiniStat label={result.owners.ownerA} value={result.owners.ownerA} />
        <MiniStat label={result.owners.ownerB} value={result.owners.ownerB} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          These are the suites both owners currently touch, ranked by how much shared failure pressure they carry across {result.scope.label.toLowerCase()}.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Shared suite hotspots</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Side-by-side failure pressure for suites both owners currently own.</p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.suites.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">No shared suites were found for these owners.</div>
          ) : result.suites.map(item => (
            <div key={`${item.rank}-${item.suiteName}`} className="px-6 py-5">
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1fr)_minmax(0,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <p className="text-lg font-semibold tracking-tight text-slate-950 dark:text-slate-50">{item.suiteName}</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.owners.ownerA} failing</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.ownerA.currentlyFailing}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.owners.ownerB} failing</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.ownerB.currentlyFailing}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Combined pressure</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.combinedPressure}</p>
                    </div>
                  </div>
                </div>
                <div className="min-w-0 grid gap-3 lg:grid-cols-2">
                  {[
                    { owner: result.owners.ownerA, data: item.ownerA },
                    { owner: result.owners.ownerB, data: item.ownerB },
                  ].map(section => (
                    <div key={section.owner} className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{section.owner}</p>
                      <p className="text-xs text-slate-600 dark:text-slate-300">
                        {section.data.currentlyFailing} failing · {section.data.regressed} regressed · {section.data.failuresInScope} failures in scope
                      </p>
                      <div className="space-y-2">
                        {section.data.topTests.map(test => (
                          <div key={test.testName} className="rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950">
                            <div className="flex items-center justify-between gap-3">
                              <code className="truncate font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{test.testName}</code>
                              <button
                                onClick={() => openEvidence(test, item.suiteName, item.rank)}
                                className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                              >
                                Open evidence
                              </button>
                            </div>
                            <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                              {test.failCount} failure{test.failCount === 1 ? '' : 's'} · {Math.round(test.passRate * 100)}% pass rate
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StabilityTrendWorkspace({
  result,
}: {
  result: StabilityTrendResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'QaLens stability analysis.',
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      `Matches: ${result.summary.matches} of ${result.scope.totalEvaluated} evaluated tests`,
      `Average pass rate: ${Math.round(result.summary.avgPassRate * 100)}%`,
      `Average flip score: ${Math.round(result.summary.avgFlipScore * 100)}%`,
      `Highest failure count: ${result.summary.highestFailCount}`,
      `Actively failing: ${result.summary.activelyFailing}`,
      '',
      `${result.query.label}:`,
      ...(result.tests.length > 0
        ? result.tests.slice(0, 10).map(item =>
            `${String(item.rank).padStart(2, '0')}. ${item.testName} — ${Math.round(item.passRate * 100)}% pass rate · ${item.classification} · ${item.primaryReason}`,
          )
        : ['- No matching tests']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  const meaningText = useMemo(() => {
    switch (result.query.kind) {
      case 'flaky_tests':
        return 'These tests are the most volatile in the selected scope, with repeated pass↔fail transitions that make them hard to trust from one run to the next.';
      case 'low_pass_rate':
        return 'These tests have the weakest reliability in the selected scope, so even if they are not highly volatile they are still dragging down confidence.';
      case 'low_pass_rate_and_failure_count':
        return 'These tests are both low-reliability and repeatedly failing in the selected scope, which makes them the clearest candidates for concentrated stability debt.';
      case 'high_pass_rate':
        return 'These tests have stayed reliably green in the selected scope, making them the strongest examples of stable behavior and repeatable health.';
      case 'highest_failure_frequency':
        return 'These tests accumulated the most failures in the selected scope, making them the biggest contributors to current test burden.';
      case 'failed_every_run':
        return 'These tests failed in every observed run in the selected scope, making them consistently broken rather than intermittent.';
      case 'never_failed':
        return 'These tests never failed in the selected scope, making them the strongest stable baseline for comparison against less reliable tests.';
      case 'unstable_tests':
        return 'These tests are unstable because they are either consistently broken or highly volatile across the selected scope.';
      case 'intermittent_failures':
        return 'These tests mix passes and failures in the selected scope, which usually points to environmental sensitivity, timing, or nondeterministic behavior.';
      case 'failed_after_passing':
        return 'These tests were passing earlier in the selected scope and are now failing, which makes them strong candidates for recent regressions.';
      case 'improved_over_time':
        return 'These tests failed earlier in the selected scope but are now back to passing, which makes them the clearest examples of recovery or improving stability.';
      default:
        return 'These tests were selected from QaLens stability signals across the chosen scope.';
    }
  }, [result]);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'QaLens stability analysis.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.totalEvaluated} evaluated
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Matches" value={String(result.summary.matches)} />
        <MiniStat label="Avg pass rate" value={`${Math.round(result.summary.avgPassRate * 100)}%`} />
        <MiniStat label="Avg flip score" value={`${Math.round(result.summary.avgFlipScore * 100)}%`} />
        <MiniStat label="Actively failing" value={String(result.summary.activelyFailing)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{meaningText}</p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.query.label}</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {result.tests.length < result.summary.matches
              ? `Showing ${result.tests.length} of ${result.summary.matches} matching tests ranked by QaLens stability signals.`
              : `${result.summary.matches} matching test${result.summary.matches === 1 ? '' : 's'} ranked by QaLens stability signals.`}
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.tests.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No tests matched this stability query in the selected scope.
            </div>
          ) : result.tests.map(item => (
            <div
              key={`${item.rank}-${item.testName}`}
              className="px-6 py-5"
              data-result-test={normalizeResultTestName(item.testName)}
            >
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                      {item.testName}
                    </code>
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${classificationBadgeClass(item.classification)}`}>
                      {item.classification}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span> {item.suite ?? 'Unknown suite'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Owner:</span> {item.owner ?? 'Unassigned'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Pass rate:</span> <span className={TIER_STYLES[item.tier].value}>{Math.round(item.passRate * 100)}%</span></span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Flip score:</span> {Math.round(item.flipScore * 100)}%</span>
                  </div>
                  <p className="mt-2 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Why it matched:</span>{' '}
                    {item.primaryReason}
                  </p>
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Failure count</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.failCount} / {item.runCount}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Current streak</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">
                        {item.currentStreak > 0
                          ? `${item.currentStreak} pass${item.currentStreak === 1 ? '' : 'es'}`
                          : item.currentStreak < 0
                            ? `${Math.abs(item.currentStreak)} fail${Math.abs(item.currentStreak) === 1 ? '' : 's'}`
                            : 'No active streak'}
                      </p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">History</p>
                    <HistoryStrip history={item.history} />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {item.canonicalName && (
                      <button
                        onClick={() => setSelected({
                          rank: item.rank,
                          testName: item.testName,
                          canonicalName: item.canonicalName ?? undefined,
                          suite: item.suite ?? undefined,
                          passRate: item.passRate,
                          failCount: item.failCount,
                          currentStatus: item.currentStreak < 0 ? 'failed' : item.currentStreak > 0 ? 'passed' : 'unknown',
                          regressed: item.currentStreak < 0 && item.lastPassedRun != null,
                          flaky: item.classification.toLowerCase().includes('flaky') || (item.passCount > 0 && item.failCount > 0),
                          riskTier: item.tier,
                          history: item.history,
                          primaryReason: item.primaryReason,
                          errorMessage: null,
                        })}
                        aria-label={`Open evidence for ${item.testName}`}
                        className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                      >
                        Open evidence
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PerformanceTimingWorkspace({
  result,
}: {
  result: PerformanceTimingResult;
}) {
  const isSlowestQuery = result.query.kind === 'slowest_tests';
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Execution-time analysis from QaLens.',
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      isSlowestQuery
        ? `Ranked slowest tests shown: ${result.summary.matches} of ${result.scope.totalEvaluated} evaluated tests`
        : `Matches: ${result.summary.matches} of ${result.scope.totalEvaluated} evaluated tests`,
      `Average duration: ${formatDurationMs(result.summary.avgDurationMs)}`,
      `Slowest duration: ${formatDurationMs(result.summary.slowestDurationMs)}`,
      `Highest slowdown trend: ${Math.round(result.summary.highestTrendScore * 100)}%`,
      `Currently slow: ${result.summary.currentlySlow}`,
      '',
      `${result.query.label}:`,
      ...(result.tests.length > 0
        ? result.tests.slice(0, 10).map(item =>
            `${String(item.rank).padStart(2, '0')}. ${item.testName} — latest ${formatDurationMs(item.latestDurationMs)} · average ${formatDurationMs(item.avgDurationMs)} · ${item.primaryReason}`,
          )
        : ['- No matching tests']),
    ];
    return lines.join('\n');
  }, [isSlowestQuery, result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  const meaningText = useMemo(() => {
    switch (result.query.kind) {
      case 'threshold_exceeded':
        return 'These tests are crossing the selected duration threshold, so they are the clearest candidates for slow execution or user-visible latency in this scope.';
      case 'slowest_tests':
        return 'These are the longest-running tests in the selected scope, which makes them the biggest contributors to total execution time.';
      case 'duration_increasing':
        return 'These tests are getting slower over time, which is often an early sign of performance drift, timing sensitivity, or growing setup overhead.';
      case 'performance_regressions':
        return 'These tests are not just slow; they are trending slower than their recent baseline, which makes them the strongest performance-regression candidates in this scope.';
      default:
        return 'These timing results show where execution time is putting the most pressure on the selected scope.';
    }
  }, [result]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Execution-time analysis from QaLens.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.totalEvaluated} evaluated
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label={isSlowestQuery ? 'Top ranked' : 'Matches'} value={String(result.summary.matches)} />
        <MiniStat label="Avg duration" value={formatDurationMs(result.summary.avgDurationMs)} />
        <MiniStat label="Slowest duration" value={formatDurationMs(result.summary.slowestDurationMs)} />
        <MiniStat label="Currently slow" value={String(result.summary.currentlySlow)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{meaningText}</p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.query.label}</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {isSlowestQuery
              ? `Showing the top ${result.summary.matches} slowest tests out of ${result.scope.totalEvaluated} evaluated in this scope.`
              : result.tests.length === result.summary.matches
                ? `${result.summary.matches} matching test${result.summary.matches === 1 ? '' : 's'} ranked by timing pressure.`
                : `Showing ${result.tests.length} of ${result.summary.matches} matching tests ranked by timing pressure.`}
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.tests.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No tests matched this timing query in the selected scope.
            </div>
          ) : result.tests.map(item => (
            <div
              key={`${item.rank}-${item.testName}`}
              className="px-6 py-5"
              data-result-test={normalizeResultTestName(item.testName)}
            >
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                      {item.testName}
                    </code>
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${TIER_STYLES[item.tier].badge}`}>
                      {item.tier}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span> {item.suite ?? 'Unknown suite'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Owner:</span> {item.owner ?? 'Unassigned'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Status:</span> {item.currentStatus.replace('_', ' ')}</span>
                  </div>
                  <p className="mt-2 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Why it matched:</span>{' '}
                    {item.primaryReason}
                  </p>
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Average duration</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{formatDurationMs(item.avgDurationMs)}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest duration</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{formatDurationMs(item.latestDurationMs)}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Max duration</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{formatDurationMs(item.maxDurationMs)}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Slowdown trend</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{Math.round(item.trendScore * 100)}%</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                      Recent durations · {item.slowRunCount}/{item.runCount} slow
                    </p>
                    <div className="flex max-w-full flex-wrap gap-1.5">
                      {(item.recentDurationsMs ?? []).map((duration, index) => (
                        <span
                          key={`${item.testName}-duration-${index}`}
                          className={[
                            'inline-flex items-center rounded-lg border px-2 py-1 text-[11px] font-medium',
                            duration >= (result.query.thresholdMs ?? 5000)
                              ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300'
                              : 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300',
                          ].join(' ')}
                        >
                          {formatDurationMs(duration)}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function NewFailuresIntroducedWorkspace({
  result,
}: {
  result: NewFailuresIntroducedResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Latest-run regressions relative to the immediately prior run.',
      `Scope: ${result.scope.label}`,
      `Latest run: ${result.scope.latestRun ?? 'Unknown'}`,
      `Previous run: ${result.scope.previousRun ?? 'Unknown'}`,
      `New failures: ${result.summary.newFailures}`,
      `Affected suites: ${result.summary.affectedSuites}`,
      `Affected owners: ${result.summary.affectedOwners}`,
      `Flaky among new: ${result.summary.flakyAmongNew}`,
      '',
      'Newly failing tests:',
      ...(result.tests.length > 0
        ? result.tests.slice(0, 10).map(item =>
            `${String(item.rank).padStart(2, '0')}. ${item.testName} — ${item.primaryReason}`,
          )
        : ['- No newly introduced failures']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Latest-run regressions relative to the immediately prior run.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            {result.scope.latestRun && (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                {result.scope.latestRun} vs {result.scope.previousRun ?? 'prior run'}
              </span>
            )}
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="New failures" value={String(result.summary.newFailures)} />
        <MiniStat label="Affected suites" value={String(result.summary.affectedSuites)} />
        <MiniStat label="Affected owners" value={String(result.summary.affectedOwners)} />
        <MiniStat label="Flaky among new" value={String(result.summary.flakyAmongNew)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          These are tests that were passing or otherwise not failing in {result.scope.previousRun ?? 'the prior run'}, but are now failing in {result.scope.latestRun ?? 'the latest run'}. They are the clearest signals of fresh regression pressure in this comparison window.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Introduced failures</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {result.tests.length === result.summary.newFailures
              ? `${result.summary.newFailures} newly failing test${result.summary.newFailures === 1 ? '' : 's'} identified in the latest run transition.`
              : `Showing ${result.tests.length} of ${result.summary.newFailures} newly failing tests from the latest run transition.`}
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.tests.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No newly introduced failures were found in this scope.
            </div>
          ) : result.tests.map(item => (
            <div
              key={`${item.rank}-${item.testName}`}
              className="px-6 py-5"
              data-result-test={normalizeResultTestName(item.testName)}
            >
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                      {item.testName}
                    </code>
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${TIER_STYLES[item.tier].badge}`}>
                      {item.tier}
                    </span>
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${classificationBadgeClass(item.classification)}`}>
                      {item.classification.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span> {item.suite ?? 'Unknown suite'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Owner:</span> {item.owner ?? 'Unassigned'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Pass rate:</span> {Math.round(item.passRate * 100)}%</span>
                  </div>
                  <p className="mt-2 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Why it matched:</span>{' '}
                    {item.primaryReason}
                  </p>
                  {item.message && (
                    <p className="mt-2 text-sm leading-7 text-slate-600 dark:text-slate-300">{item.message}</p>
                  )}
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Previous status</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.previousStatus.replace(/_/g, ' ')}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest status</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.latestStatus.replace(/_/g, ' ')}</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">History</p>
                    <HistoryStrip history={item.history} />
                  </div>
                  {item.canonicalName && (
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => setSelected({
                          rank: item.rank,
                          testName: item.testName,
                          canonicalName: item.canonicalName ?? undefined,
                          suite: item.suite ?? undefined,
                          passRate: item.passRate,
                          failCount: 1,
                          currentStatus: item.latestStatus,
                          regressed: true,
                          flaky: item.classification.toLowerCase().includes('flaky'),
                          riskTier: item.tier,
                          history: item.history,
                          primaryReason: item.primaryReason,
                          errorMessage: item.message ?? null,
                        })}
                        aria-label={`Open evidence for ${item.testName}`}
                        className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                      >
                        Open evidence
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RunComparisonWorkspace({
  result,
}: {
  result: RunComparisonResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Failure changes between the selected runs.',
      `Scope: ${result.scope.label}`,
      `Baseline run: ${result.scope.baselineRun ?? 'Unknown'}`,
      `Latest run: ${result.scope.latestRun ?? 'Unknown'}`,
      `New failures: ${result.summary.newFailures}`,
      `Recovered: ${result.summary.recovered}`,
      `Still failing: ${result.summary.stillFailing}`,
      `Changed tests: ${result.summary.changedTests}`,
      '',
      'Changed tests:',
      ...(result.tests.length > 0
        ? result.tests.slice(0, 10).map(item =>
            `${String(item.rank).padStart(2, '0')}. ${item.testName} — ${item.primaryReason}`,
          )
        : ['- No changed tests']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Failure changes between the selected runs.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <MiniStat label="New failures" value={String(result.summary.newFailures)} />
        <MiniStat label="Recovered" value={String(result.summary.recovered)} />
        <MiniStat label="Still failing" value={String(result.summary.stillFailing)} />
        <MiniStat label="Baseline failed" value={String(result.summary.baselineFailed)} />
        <MiniStat label="Latest failed" value={String(result.summary.latestFailed)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          This compares {result.scope.baselineRun ?? 'the baseline run'} against {result.scope.latestRun ?? 'the latest run'} and highlights which tests newly broke, which recovered, and which remained failing across both runs.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Changed failures</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {result.tests.length === result.summary.changedTests
              ? `${result.summary.changedTests} changed test${result.summary.changedTests === 1 ? '' : 's'} across the compared runs.`
              : `Showing ${result.tests.length} of ${result.summary.changedTests} changed tests across the compared runs.`}
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.tests.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No failure-state changes were found between these runs.
            </div>
          ) : result.tests.map(item => (
            <div
              key={`${item.rank}-${item.testName}`}
              className="px-6 py-5"
              data-result-test={normalizeResultTestName(item.testName)}
            >
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                      {item.testName}
                    </code>
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${TIER_STYLES[item.tier].badge}`}>
                      {item.delta.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span> {item.suite ?? 'Unknown suite'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Owner:</span> {item.owner ?? 'Unassigned'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Pass rate:</span> {Math.round(item.passRate * 100)}%</span>
                  </div>
                  <p className="mt-2 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Why it changed:</span>{' '}
                    {item.primaryReason}
                  </p>
                  {item.message && (
                    <p className="mt-2 text-sm leading-7 text-slate-600 dark:text-slate-300">{item.message}</p>
                  )}
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Baseline status</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.baselineStatus.replace(/_/g, ' ')}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Latest status</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.latestStatus.replace(/_/g, ' ')}</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">History</p>
                    <HistoryStrip history={item.history} />
                  </div>
                  {item.canonicalName && (
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => setSelected({
                          rank: item.rank,
                          testName: item.testName,
                          canonicalName: item.canonicalName ?? undefined,
                          suite: item.suite ?? undefined,
                          passRate: item.passRate,
                          failCount: item.latestStatus === 'failed' || item.latestStatus === 'broken' ? 1 : 0,
                          currentStatus: item.latestStatus,
                          regressed: item.delta === 'new_failure',
                          flaky: item.classification.toLowerCase().includes('flaky'),
                          riskTier: item.tier,
                          history: item.history,
                          primaryReason: item.primaryReason,
                          errorMessage: item.message ?? null,
                        })}
                        aria-label={`Open evidence for ${item.testName}`}
                        className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                      >
                        Open evidence
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function FailureTrendWorkspace({
  result,
}: {
  result: FailureTrendResult;
}) {
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Run-by-run failure trend from QaLens.',
      `Scope: ${result.scope.label}`,
      `Direction: ${result.summary.direction}`,
      `${result.scope.baselineRun ?? 'Baseline'} failed: ${result.summary.baselineFailed}`,
      `${result.scope.latestRun ?? 'Latest'} failed: ${result.summary.latestFailed}`,
      `Peak failures: ${result.summary.peakFailed}${result.summary.peakRun ? ` in ${result.summary.peakRun}` : ''}`,
      '',
      'Runs:',
      ...result.runs.map(run => `${run.runLabel}: ${run.failed} failed · ${run.passed} passed · ${run.skipped} skipped`),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  const directionStyle =
    result.summary.direction === 'INCREASING'
      ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
      : result.summary.direction === 'DECREASING'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300'
        : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300';

  const meaning =
    result.summary.direction === 'INCREASING'
      ? `${result.scope.latestRun ?? 'The latest run'} is carrying more failures than ${result.scope.baselineRun ?? 'the baseline run'}, so failure pressure is trending upward in this scope.`
      : result.summary.direction === 'DECREASING'
        ? `${result.scope.latestRun ?? 'The latest run'} is carrying fewer failures than ${result.scope.baselineRun ?? 'the baseline run'}, so failure pressure is easing across this scope.`
        : `Failure counts are flat between ${result.scope.baselineRun ?? 'the baseline run'} and ${result.scope.latestRun ?? 'the latest run'}, so there is no meaningful directional change in this scope.`;

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Run-by-run failure trend from QaLens.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className={`rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] ${directionStyle}`}>
              {result.summary.direction.toLowerCase()}
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Direction" value={result.summary.direction.toLowerCase()} />
        <MiniStat label="Failure delta" value={`${result.summary.deltaFailed > 0 ? '+' : ''}${result.summary.deltaFailed}`} />
        <MiniStat label="Peak failures" value={String(result.summary.peakFailed)} />
        <MiniStat label="Latest transition" value={`+${result.summary.latestNewFailures} / -${result.summary.latestRecovered}`} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{meaning}</p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Run-by-run failure counts</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {result.scope.runCount} runs shown in chronological order so you can verify whether failure counts are rising or falling.
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.runs.map((run) => (
            <div key={run.runLabel} className="grid gap-4 px-6 py-5 lg:grid-cols-[90px_minmax(0,1fr)_220px] lg:items-start">
              <div>
                <p className="text-4xl font-semibold tracking-tight text-slate-300 dark:text-slate-700">
                  {String(run.rank).padStart(2, '0')}
                </p>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="text-lg font-semibold text-slate-950 dark:text-slate-50">{run.runLabel}</h3>
                  {run.isPeak ? (
                    <span className="rounded-full border border-red-200 bg-red-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                      Peak
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                  <span><span className="font-medium text-slate-950 dark:text-slate-50">Passed:</span> {run.passed}</span>
                  <span><span className="font-medium text-slate-950 dark:text-slate-50">Failed:</span> {run.failed}</span>
                  <span><span className="font-medium text-slate-950 dark:text-slate-50">Skipped:</span> {run.skipped}</span>
                  <span><span className="font-medium text-slate-950 dark:text-slate-50">Pass rate:</span> {pct(run.passRate)}</span>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Failed</p>
                  <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{run.failed}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Total</p>
                  <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{run.total}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RootCauseInsightWorkspace({
  result,
}: {
  result: RootCauseInsightResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Evidence-backed root cause analysis from QaLens.',
      `Scope: ${result.scope.label}`,
      `Total failures analyzed: ${result.summary.totalFailures}`,
      `Affected tests: ${result.summary.affectedTests}`,
      `Affected runs: ${result.summary.affectedRuns}`,
      ...(result.summary.dominantFamily ? [`Dominant cause family: ${result.summary.dominantFamily}`] : []),
      '',
      'Top cause groups:',
      ...(result.causes.length > 0
        ? result.causes.slice(0, 5).map(item =>
            `${String(item.rank).padStart(2, '0')}. ${item.family} — ${item.count} failures across ${item.affectedTests} tests`,
          )
        : ['- No categorized failure evidence found']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  const meaningText = useMemo(() => {
    if (!result.summary.dominantFamily) {
      return 'QaLens could not isolate a dominant failure cause from the available evidence, so manual inspection is still required.';
    }
    if (result.scope.kind === 'test_frequency' && result.scope.targetTest) {
      return `${result.scope.targetTest} is failing repeatedly because the same cause family is showing up across its recent failing runs. The strongest evidence is grouped below so you can verify the pattern quickly.`;
    }
    if (result.scope.kind === 'cause_mix') {
      return `QaLens compared UI/test-script style failures against product/backend style failures. The dominant family below shows which side is contributing more of the failure pressure in this scope.`;
    }
    if (result.scope.kind === 'flaky_causes') {
      return `These cause groups are taken only from tests already classified as flaky, so the dominant family points to what is driving instability rather than just raw failure count.`;
    }
    return `The dominant failure family in this scope is ${result.summary.dominantFamily}. The grouped causes below show which categories are contributing most and what to investigate first.`;
  }, [result]);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Evidence-backed root cause analysis from QaLens.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            {result.scope.targetTest && (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                {result.scope.targetTest}
              </span>
            )}
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Failures analyzed" value={String(result.summary.totalFailures)} />
        <MiniStat label="Affected tests" value={String(result.summary.affectedTests)} />
        <MiniStat label="Affected runs" value={String(result.summary.affectedRuns)} />
        <MiniStat label="Dominant cause" value={result.summary.dominantCategory ? result.summary.dominantCategory.replace(/_/g, ' ') : 'Unknown'} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{meaningText}</p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Cause groups</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            Grouped by failure category so you can see the strongest patterns without reading every raw failure message.
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.causes.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No categorized failure evidence was found for this scope.
            </div>
          ) : result.causes.map(cause => (
            <div key={`${cause.rank}-${cause.category}`} className="px-6 py-5">
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1.7fr)_minmax(280px,1fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(cause.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${causeFamilyBadgeClass(cause.family)}`}>
                      {cause.family}
                    </span>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                      {cause.category.replace(/_/g, ' ')}
                    </span>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                      {cause.confidence} confidence
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Likely cause:</span>{' '}
                    {cause.probableCause}
                  </p>
                  <p className="mt-1 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    <span className="font-medium text-slate-950 dark:text-slate-50">Recommended next check:</span>{' '}
                    {cause.recommendedAction}
                  </p>
                  {cause.sampleMessages.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {cause.sampleMessages.map((message, index) => (
                        <div key={`${cause.category}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                          {message}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="min-w-0 space-y-3 xl:pl-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Failures</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{cause.count}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Affected tests</p>
                      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-50">{cause.affectedTests}</p>
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-900">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Top affected tests</p>
                    <div className="mt-2 space-y-2">
                      {cause.topTests.map(test => (
                        <div key={`${cause.category}-${test.testName}`} className="flex items-center justify-between gap-3">
                          <code className="truncate font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{test.testName}</code>
                          {test.canonicalName && (
                            <button
                              onClick={() => setSelected({
                                rank: cause.rank,
                                testName: test.testName,
                                canonicalName: test.canonicalName ?? undefined,
                                suite: undefined,
                                passRate: 0,
                                failCount: test.count,
                                currentStatus: 'failed',
                                regressed: false,
                                flaky: false,
                                riskTier: 'MEDIUM',
                                history: undefined,
                                primaryReason: `${cause.family} is the dominant cause group in ${result.scope.label.toLowerCase()}.`,
                                errorMessage: cause.sampleMessages[0] ?? null,
                              })}
                              className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                            >
                              Open evidence
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TestFixPlaybookWorkspace({
  result,
}: {
  result: TestFixPlaybookResult;
}) {
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.summary,
      result.errorType ? `Error type: ${result.errorType}` : '',
      result.evidence ? `Evidence: ${result.evidence}` : '',
      '',
      'Recommended fix:',
      result.recommendedFix ?? '',
      '',
      'Verification:',
      ...(result.verification ?? []).map(item => `- ${item}`),
    ].filter(Boolean);
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  const observed = result.observedRuns ?? [];
  const causes = result.causes ?? [];
  const checks = result.checks ?? [];
  const verification = result.verification ?? [];

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Fix playbook</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{result.subtitle ?? 'Evidence-backed triage checklist from recent QaLens runs.'}</p>
          </div>
          <button
            type="button"
            onClick={handleCopySummary}
            className="w-fit rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            {copied ? 'Copied' : 'Copy summary'}
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Test" value={result.testName} />
        <MiniStat label="Failed runs" value={String(result.scope?.failedRuns ?? 0)} />
        <MiniStat label="Window" value={`${result.scope?.windowRuns ?? 0} runs`} />
        <MiniStat label="Confidence" value={result.confidence ?? 'NA'} />
      </div>

      {!result.hasActiveFailure ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-5 text-sm leading-7 text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-200">
          {result.summary}
        </div>
      ) : (
        <>
          <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
            <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">Diagnosis</h3>
            <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{result.summary}</p>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {result.errorType && <MiniStat label="Error type" value={result.errorType.split('.').pop() ?? result.errorType} />}
              {observed.length > 0 && <MiniStat label="Observed in" value={observed.join(', ')} />}
            </div>
            {result.evidence && (
              <p className="mt-4 rounded-xl border border-blue-100 bg-white/70 px-4 py-3 font-mono text-xs leading-6 text-slate-700 dark:border-blue-500/20 dark:bg-slate-950/40 dark:text-slate-200">
                {result.evidence}
              </p>
            )}
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <ChecklistCard title="Most likely causes" items={causes} tone="amber" />
            <ChecklistCard title="What to check first" items={checks} tone="blue" />
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
            <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Recommended fix</h3>
            <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{result.recommendedFix}</p>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <ChecklistCard title="Verification steps" items={verification} tone="emerald" />
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
              <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Confidence / limits</h3>
              <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{result.confidenceText}</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ChecklistCard({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: 'amber' | 'blue' | 'emerald';
}) {
  const toneClass = tone === 'amber'
    ? 'border-amber-200 bg-amber-50/60 dark:border-amber-500/25 dark:bg-amber-500/10'
    : tone === 'emerald'
      ? 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/25 dark:bg-emerald-500/10'
      : 'border-blue-200 bg-blue-50/60 dark:border-blue-500/25 dark:bg-blue-500/10';

  return (
    <div className={`rounded-2xl border p-5 ${toneClass}`}>
      <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-700 dark:text-slate-200">{title}</h3>
      <ul className="mt-4 space-y-3">
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className="flex gap-3 text-sm leading-6 text-slate-700 dark:text-slate-200">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-xs font-semibold text-slate-600 shadow-sm dark:bg-slate-950 dark:text-slate-300">
              {index + 1}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SuiteFailureRankingWorkspace({
  result,
}: {
  result: SuiteFailureRankingResult;
}) {
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Suites ranked by failure concentration.',
      `Scope: ${result.scope.label} • ${result.scope.runCount} run${result.scope.runCount === 1 ? '' : 's'}`,
      `Suites ranked: ${result.scope.totalSuites}`,
      `Total failures: ${result.summary.totalFailures}`,
      ...(result.summary.topSuite ? [`Top suite: ${result.summary.topSuite}`] : []),
      '',
      'Top suites:',
      ...result.ranking.slice(0, 5).map(item =>
        `${String(item.rank).padStart(2, '0')}. ${item.suiteName} — ${item.failedExecutions}/${item.totalExecutions} failed executions · ${Math.round(item.failureRate * 100)}% failure rate`,
      ),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Suites ranked by failure concentration.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.totalSuites} suites
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Suites ranked" value={String(result.scope.totalSuites)} />
        <MiniStat label="Total failures" value={String(result.summary.totalFailures)} />
        <MiniStat label="Failing suites" value={String(result.summary.currentlyFailingSuites)} />
        <MiniStat label="Flaky suites" value={String(result.summary.flakySuites)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this means</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          This ranks suites by failed executions first, then by currently failing tests and failure rate, so the top suite is the best place to look for concentrated failure pressure.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Suite failure ranking</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Failure concentration by suite, including owners and representative tests.</p>
        </div>

        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.ranking.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">No suite failures were found in this scope.</div>
          ) : result.ranking.map(item => (
            <div key={`${item.rank}-${item.suiteName}`} className="px-6 py-5">
              <div className="grid gap-5 xl:grid-cols-[64px_minmax(0,1fr)_minmax(280px,0.9fr)] xl:items-start">
                <div className="text-3xl font-semibold tracking-tight text-slate-300 dark:text-slate-600">
                  {String(item.rank).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <p className="text-lg font-semibold tracking-tight text-slate-950 dark:text-slate-50">{item.suiteName}</p>
                  <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">{item.primaryReason}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.owners.slice(0, 4).map(owner => (
                      <span key={owner} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                        {owner}
                      </span>
                    ))}
                    {item.owners.length > 4 && (
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                        +{item.owners.length - 4} more
                      </span>
                    )}
                  </div>
                  <div className="mt-4 grid gap-2 sm:grid-cols-4">
                    <MiniStat label="Failure rate" value={pct(item.failureRate)} />
                    <MiniStat label="Failed execs" value={`${item.failedExecutions}/${item.totalExecutions}`} />
                    <MiniStat label="Failing tests" value={String(item.failingTests)} />
                    <MiniStat label="Flaky tests" value={String(item.flakyTests)} />
                  </div>
                </div>
                <div className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Top failing tests</p>
                  <div className="mt-3 space-y-2">
                    {item.topTests.length === 0 ? (
                      <p className="text-sm text-slate-500 dark:text-slate-400">No failing test detail available.</p>
                    ) : item.topTests.map(test => (
                      <div key={`${item.suiteName}-${test.testName}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950">
                        <div className="flex items-start justify-between gap-3">
                          <code className="min-w-0 truncate font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{test.testName}</code>
                          <span className={['shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]', statusBadgeClass(test.currentStatus)].join(' ')}>
                            {test.currentStatus}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                          {test.failCount} failure{test.failCount === 1 ? '' : 's'} · {pct(test.passRate)} pass rate{test.owner ? ` · ${test.owner}` : ''}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RunRetrievalWorkspace({
  result,
}: {
  result: RunRetrievalResult;
}) {
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Run-level retrieval from QaLens.',
      `Run: ${result.run.label}${result.run.project ? ` • ${result.run.project}` : ''}`,
      `Query: ${result.query.label}`,
      `Total: ${result.summary.total}`,
      `Passed: ${result.summary.passed}`,
      `Failed: ${result.summary.failed}`,
      `Skipped: ${result.summary.skipped}`,
      '',
      `${result.query.label}:`,
      ...(result.tests.length > 0
        ? result.tests.slice(0, 10).map(test => `- ${test.name} — ${test.status}${test.errorType ? ` · ${test.errorType}` : ''}`)
        : ['- No matching tests']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  const focusText = useMemo(() => {
    if (result.query.kind === 'status_lookup') {
      return result.tests.length > 0
        ? `QaLens found ${result.tests.length} matching test${result.tests.length === 1 ? '' : 's'} for this status lookup in ${result.run.label}.`
        : `QaLens did not find a matching test for this status lookup in ${result.run.label}.`;
    }
    if (result.query.kind === 'run_counts') {
      return `This is a run-level breakdown for ${result.run.label}, with the full executed test list shown below so you can verify the counts quickly.`;
    }
    return `Showing ${result.query.label.toLowerCase()} for ${result.run.label}.`;
  }, [result]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Run-level retrieval from QaLens.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.run.label}
            </span>
            {result.run.project && (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                {result.run.project}
              </span>
            )}
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Total tests" value={String(result.summary.total)} />
        <MiniStat label="Passed" value={String(result.summary.passed)} />
        <MiniStat label="Failed" value={String(result.summary.failed)} />
        <MiniStat label="Skipped" value={String(result.summary.skipped)} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this shows</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">{focusText}</p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{result.query.label}</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {result.query.matchedTests} matching test{result.query.matchedTests === 1 ? '' : 's'} in {result.run.label}.
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.tests.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No tests matched this run query.
            </div>
          ) : result.tests.map(test => (
            <div key={`${test.name}-${test.status}`} className="px-6 py-5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                    {test.name}
                  </code>
                  <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${statusBadgeClass(test.status)}`}>
                    {test.status}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                  <span><span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span> {test.suite ?? 'Unknown suite'}</span>
                  <span><span className="font-medium text-slate-950 dark:text-slate-50">Owner:</span> {test.owner ?? 'Unassigned'}</span>
                  {test.errorType && <span><span className="font-medium text-slate-950 dark:text-slate-50">Error:</span> {test.errorType}</span>}
                </div>
                {test.message && (
                  <p className="mt-2 text-sm leading-7 text-slate-700 dark:text-slate-200">
                    {test.message}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ExceptionRetrievalWorkspace({
  result,
}: {
  result: ExceptionRetrievalResult;
}) {
  const [selected, setSelected] = useState<OwnerTestGapResult['tests'][number] | null>(null);
  const summaryText = useMemo(() => {
    const lines = [
      result.title,
      result.subtitle ?? 'Exception-based failure retrieval from QaLens.',
      `Scope: ${result.scope.label}`,
      `Query: ${result.scope.query}`,
      `Matches: ${result.summary.matches}`,
      `Unique tests: ${result.summary.uniqueTests}`,
      `Affected runs: ${result.summary.affectedRuns}`,
      ...(result.summary.dominantCategory ? [`Dominant category: ${result.summary.dominantCategory}`] : []),
      '',
      'Top matches:',
      ...(result.matches.length > 0
        ? result.matches.slice(0, 10).map(item => `- ${item.testName} — ${item.runLabel}${item.errorType ? ` · ${item.errorType}` : ''}`)
        : ['- No matching failures']),
    ];
    return lines.join('\n');
  }, [result]);
  const { copied, handleCopySummary } = useCopySummary(summaryText);

  return (
    <div className="space-y-5">
      {selected && <OwnerGapEvidenceDrawer item={selected} onClose={() => setSelected(null)} />}

      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Result workspace</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">{result.title}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {result.subtitle ?? 'Exception-based failure retrieval from QaLens.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.label}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {result.scope.query}
            </span>
            <button
              type="button"
              onClick={handleCopySummary}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-900"
              aria-label="Copy result summary"
            >
              {copied ? 'Copied' : 'Copy summary'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniStat label="Matches" value={String(result.summary.matches)} />
        <MiniStat label="Unique tests" value={String(result.summary.uniqueTests)} />
        <MiniStat label="Affected runs" value={String(result.summary.affectedRuns)} />
        <MiniStat label="Category" value={result.summary.dominantCategory ?? 'Mixed'} />
      </div>

      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-500/20 dark:bg-blue-500/10">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">What this shows</h3>
        <p className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-200">
          QaLens matched failed tests using exception type and first-line failure message text, so this view catches both exact exception names and close message variants like timeout or element-location errors.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Matching failures</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {result.summary.matches} matching failure{result.summary.matches === 1 ? '' : 's'} across {result.scope.label.toLowerCase()}.
          </p>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {result.matches.length === 0 ? (
            <div className="px-6 py-6 text-sm text-slate-500 dark:text-slate-400">
              No matching failures were found for this exception query.
            </div>
          ) : result.matches.map((item, index) => (
            <div
              key={`${item.testName}-${item.runLabel}-${index}`}
              className="px-6 py-5"
              data-result-test={normalizeResultTestName(item.testName)}
            >
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(240px,0.95fr)] lg:items-start">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="truncate rounded-xl bg-slate-50 px-2.5 py-1 font-mono text-sm font-semibold text-slate-900 dark:bg-slate-900 dark:text-slate-100">
                      {item.testName}
                    </code>
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] ${statusBadgeClass(item.status)}`}>
                      {item.status}
                    </span>
                    {item.category && (
                      <span className="inline-flex items-center rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300">
                        {item.category}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Run:</span> {item.runLabel}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Suite:</span> {item.suite ?? 'Unknown suite'}</span>
                    <span><span className="font-medium text-slate-950 dark:text-slate-50">Owner:</span> {item.owner ?? 'Unassigned'}</span>
                  </div>
                  {item.message && (
                    <p className="mt-2 text-sm leading-7 text-slate-700 dark:text-slate-200">{item.message}</p>
                  )}
                </div>
                <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Matched error</p>
                    <p className="mt-2 text-sm font-semibold text-slate-950 dark:text-slate-50">{item.errorType ?? 'Failure message match'}</p>
                  </div>
                  {item.canonicalName && (
                    <button
                      onClick={() => setSelected({
                        rank: index + 1,
                        testName: item.testName,
                        canonicalName: item.canonicalName ?? undefined,
                        suite: item.suite ?? undefined,
                        passRate: 0,
                        failCount: 1,
                        currentStatus: item.status,
                        regressed: false,
                        flaky: false,
                        riskTier: item.status === 'failed' || item.status === 'broken' ? 'HIGH' : 'LOW',
                        history: undefined,
                        primaryReason: `Matched the exception filter "${result.scope.query}" in ${item.runLabel}.`,
                        errorMessage: item.message ?? null,
                      })}
                      className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                    >
                      Open evidence
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ResultWorkspace({
  result,
  loading = false,
}: {
  result: QaLensResult | null;
  loading?: boolean;
}) {
  if (!result) return <WorkspaceEmptyState />;

  if (result.type === 'risk_ranking') {
    return <RiskWorkspace result={result} loading={loading} />;
  }

  if (result.type === 'owner_failure_rate') {
    return <OwnerFailureRateWorkspace result={result} />;
  }

  if (result.type === 'owner_flaky_tests') {
    return <OwnerFlakyTestsWorkspace result={result} />;
  }

  if (result.type === 'owner_suite_comparison') {
    return <OwnerSuiteComparisonWorkspace result={result} />;
  }

  if (result.type === 'owner_window_comparison') {
    return <OwnerWindowComparisonWorkspace result={result} />;
  }

  if (result.type === 'owner_test_gap') {
    return <OwnerTestGapWorkspace result={result} />;
  }

  if (result.type === 'owner_suite_regressions') {
    return <OwnerSuiteRegressionsWorkspace result={result} />;
  }

  if (result.type === 'shared_suite_failures') {
    return <SharedSuiteFailuresWorkspace result={result} />;
  }

  if (result.type === 'suite_failure_ranking') {
    return <SuiteFailureRankingWorkspace result={result} />;
  }

  if (result.type === 'run_retrieval') {
    return <RunRetrievalWorkspace result={result} />;
  }

  if (result.type === 'exception_retrieval') {
    return <ExceptionRetrievalWorkspace result={result} />;
  }

  if (result.type === 'stability_trend') {
    return <StabilityTrendWorkspace result={result} />;
  }

  if (result.type === 'performance_timing') {
    return <PerformanceTimingWorkspace result={result} />;
  }

  if (result.type === 'new_failures_introduced') {
    return <NewFailuresIntroducedWorkspace result={result} />;
  }

  if (result.type === 'run_comparison') {
    return <RunComparisonWorkspace result={result} />;
  }

  if (result.type === 'failure_trend') {
    return <FailureTrendWorkspace result={result} />;
  }

  if (result.type === 'root_cause_insight') {
    return <RootCauseInsightWorkspace result={result} />;
  }

  if (result.type === 'test_fix_playbook') {
    return <TestFixPlaybookWorkspace result={result} />;
  }

  return <WorkspaceEmptyState />;
}
