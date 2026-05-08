import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from 'react';
import { Tooltip } from '../components/Tooltip';
import { useProject } from '../hooks/useProject';
import { ResultWorkspace } from './chat/ResultWorkspace';
import { renderMarkdown } from './chat/markdown';
import type {
  AssistantUiHints,
  HistoryState,
  OwnerFailureRateResult,
  QaraResult,
  RiskRankingResult,
  RiskTier,
} from './chat/types';

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

interface ApiHomepageCard {
  id:        string;
  icon:      string;
  title:     string;
  metric:    string | null;
  question:  string;
  available: boolean;
}

interface ApiSource {
  type:              string;
  icon:              string;
  label:             string;
  meta:              string;
  run_id?:           string;
  name?:             string;
  metric?:           string;
  failure_rate?:     number;
  failed_executions?: number;
  total_executions?: number;
  failing_tests?:    number;
  total_tests?:      number;
  run_count?:        number;
  rank_label?:       string | null;
}

interface ApiAskResponse {
  answer:       string;
  context_mode: string;
  sources:      ApiSource[];
  intent:       string;
  follow_ups:   string[];
  result?:      QaraResult;
  uiHints?:     AssistantUiHints;
}

// Backend intent string emitted by AskResponse for ranked test answers.
const INTENT_RANKING_LIST = 'ranking_list';

interface ApiLlmInfo {
  provider: string;
  model:    string;
}

interface ApiEvidenceRun {
  type:          'run';
  run_id:        string;
  title:         string;
  project:       string | null;
  started_at:    string | null;
  total_tests:   number;
  passed_count:  number;
  failed_count:  number;
  skipped_count: number;
  top_failed:    { name: string; status: string; error_type: string | null; message: string | null }[];
}

interface ApiEvidenceTest {
  type:            'test';
  canonical_name:  string;
  title:           string;
  classification:  string;
  risk_tier:       string;
  risk_pct:        number;
  pass_rate:       number;
  flip_score:      number;
  run_count:       number;
  sparkline:       string;
  why_relevant:    string[];
  recent_runs:     { run_id: string; run_label: string; status: string; timestamp: string }[];
  most_frequent_error: { category: string; message: string } | null;
}

type ApiEvidence = ApiEvidenceRun | ApiEvidenceTest;

interface ConvMessage {
  id:         string;
  role:       'user' | 'assistant';
  content:    string;
  sources?:   ApiSource[];
  followUps?: string[];
  intent?:    string;
  resultType?: QaraResult['type'];
  loading?:   boolean;
}

interface SuggestedQuestion {
  id: string;
  question: string;
  label?: string;
  icon?: string;
}

const CHAT_PANEL_WIDTH_KEY = 'qara-chat-panel-width';
const DEFAULT_CHAT_PANEL_WIDTH = 440;
const MIN_CHAT_PANEL_WIDTH = 380;
const MAX_CHAT_PANEL_WIDTH = 620;

const DEFAULT_SUGGESTED_QUESTIONS: SuggestedQuestion[] = [
  { id: 'latest-run', label: 'Latest run', icon: '🔥', question: 'What broke in the latest run?' },
  { id: 'new-failures', label: 'Failures', icon: '🔥', question: 'What new failures were introduced?' },
  { id: 'failed-every-run', label: 'Trends', icon: '📈', question: 'Which tests failed in every run?' },
  { id: 'never-failed', label: 'Trends', icon: '📈', question: 'Which tests never failed?' },
  { id: 'stability-trending', label: 'Trends', icon: '📈', question: 'How is stability trending?' },
  { id: 'owner-flaky', label: 'Owners', icon: '👤', question: 'Which engineer owns the most flaky tests?' },
  { id: 'owner-failure-rate', label: 'Owners', icon: '👤', question: 'Compare failure rate per engineer' },
  { id: 'owner-suite', label: 'Owners', icon: '👤', question: 'Which suite is causing the most failures?' },
];

function clampChatPanelWidth(width: number) {
  return Math.min(MAX_CHAT_PANEL_WIDTH, Math.max(MIN_CHAT_PANEL_WIDTH, width));
}

function uniqueSuggestions(items: SuggestedQuestion[], limit: number) {
  const seen = new Set<string>();
  const result: SuggestedQuestion[] = [];
  for (const item of items) {
    const key = normalizeQuestion(item.question);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
    if (result.length >= limit) break;
  }
  return result;
}

function normalizeQuestion(question: string) {
  return question
    .trim()
    .toLowerCase()
    .replace(/[?!.]+$/g, '')
    .replace(/\s+/g, ' ');
}

function suggestionsFromHomepageCards(cards: ApiHomepageCard[]): SuggestedQuestion[] {
  return cards
    .filter(card => card.available)
    .map(card => ({
      id: `card-${card.id}`,
      question: card.question,
      label: card.title,
      icon: card.icon,
    }));
}

function contextualSuggestions(result: QaraResult | null, cards: ApiHomepageCard[]): SuggestedQuestion[] {
  const homepage = suggestionsFromHomepageCards(cards);
  if (!result) return uniqueSuggestions([...homepage, ...DEFAULT_SUGGESTED_QUESTIONS], 8);

  if (result.type === 'risk_ranking') {
    return uniqueSuggestions([
      { id: 'risk-flaky', question: 'Which of these tests are flaky?' },
      { id: 'risk-failed-every-run', question: 'Which tests failed in every run?' },
      { id: 'risk-root-cause', question: 'What should I fix first?' },
      { id: 'risk-never-failed', question: 'Which tests never failed?' },
      ...DEFAULT_SUGGESTED_QUESTIONS,
    ], 6);
  }

  if (result.type === 'stability_trend') {
    return uniqueSuggestions([
      { id: 'stable-risk', question: 'Which tests are most likely to fail next run?' },
      { id: 'stable-new-failures', question: 'What new failures were introduced?' },
      { id: 'stable-every-run', question: 'Which tests failed in every run?' },
      { id: 'stable-never-failed', question: 'Which tests never failed?' },
      { id: 'stable-low-pass', question: 'Show tests with pass rate below 60%' },
    ], 6);
  }

  if (result.type === 'run_retrieval') {
    return uniqueSuggestions([
      { id: 'run-new', question: 'What new failures were introduced?' },
      { id: 'run-flaky', question: 'Were any of these failures flaky before?' },
      { id: 'run-risk', question: 'Which tests are most likely to fail next run?' },
      { id: 'run-root', question: 'What is the most common root cause?' },
    ], 6);
  }

  if (result.type === 'run_comparison' || result.type === 'new_failures_introduced' || result.type === 'failure_trend') {
    return uniqueSuggestions([
      { id: 'compare-flaky', question: 'Were any of these tests flaky before this regression?' },
      { id: 'compare-recovered', question: 'Which tests recovered?' },
      { id: 'compare-every-run', question: 'Which tests failed in every run?' },
      { id: 'compare-fix-first', question: 'What should I fix first?' },
      { id: 'compare-risk', question: 'Which tests are most likely to fail next run?' },
    ], 6);
  }

  if (
    result.type === 'owner_failure_rate'
    || result.type === 'owner_flaky_tests'
    || result.type === 'owner_window_comparison'
    || result.type === 'owner_test_gap'
    || result.type === 'owner_suite_regressions'
    || result.type === 'owner_suite_comparison'
    || result.type === 'shared_suite_failures'
    || result.type === 'suite_failure_ranking'
  ) {
    return uniqueSuggestions([
      { id: 'owner-flaky', question: 'Which engineer owns the most flaky tests?' },
      { id: 'owner-fail-rate', question: 'Compare failure rate per engineer' },
      { id: 'owner-suite', question: 'Which suite is causing the most failures?' },
      { id: 'owner-risk', question: 'Which tests are most likely to fail next run?' },
    ], 6);
  }

  return uniqueSuggestions([...homepage, ...DEFAULT_SUGGESTED_QUESTIONS], 6);
}

// ─────────────────────────────────────────────────────────────
// Evidence Drawer
// ─────────────────────────────────────────────────────────────

function EvidenceDrawer({
  source, allSources, currentIndex, onNavigate, onClose, project,
}: {
  source:       ApiSource;
  allSources:   ApiSource[];
  currentIndex: number;
  onNavigate:   (idx: number) => void;
  onClose:      () => void;
  project:      string;
}) {
  const [evidence, setEvidence] = useState<ApiEvidence | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null); setEvidence(null);
    let url = '';
    if (source.run_id)                     url = `/api/evidence/run/${encodeURIComponent(source.run_id)}`;
    else if (source.type === 'test' && source.name)  url = `/api/evidence/test/${encodeURIComponent(source.name)}`;
    else if (source.type === 'test' && source.label) url = `/api/evidence/test/${encodeURIComponent(source.label.toLowerCase().replace(/[()]/g, ''))}`;
    if (!url) { setLoading(false); return; }
    fetch(url)
      .then(r => r.ok ? r.json() as Promise<ApiEvidence> : Promise.reject(`API ${r.status}`))
      .then(d => { if (!cancelled) setEvidence(d); })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [source]);

  function openInNewTab() {
    const params = new URLSearchParams({ tab: source.run_id ? 'runs' : 'analysis' });
    if (project) params.set('project', project);
    if (source.run_id) params.set('run', source.run_id);
    window.open(`/?${params}`, '_blank', 'noopener,noreferrer');
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <aside
        className="fixed top-0 right-0 h-full w-full max-w-md z-50 flex flex-col"
        style={{ background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-default)', boxShadow: 'var(--shadow-overlay)' }}
        aria-label="Evidence details"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-base">{source.icon}</span>
            <span className="text-sm font-semibold text-primary truncate">{source.label}</span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {allSources.length > 1 && (
              <div className="flex items-center gap-1">
                <button onClick={() => onNavigate(currentIndex - 1)} disabled={currentIndex === 0}
                  className="qara-control p-1.5 disabled:opacity-30 disabled:cursor-not-allowed">
                  <svg viewBox="0 0 14 14" fill="none" className="w-3 h-3"><path d="M9 3l-4 4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </button>
                <span className="text-xs text-muted tabular-nums">{currentIndex + 1}/{allSources.length}</span>
                <button onClick={() => onNavigate(currentIndex + 1)} disabled={currentIndex >= allSources.length - 1}
                  className="qara-control p-1.5 disabled:opacity-30 disabled:cursor-not-allowed">
                  <svg viewBox="0 0 14 14" fill="none" className="w-3 h-3"><path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </button>
              </div>
            )}
            <Tooltip content="Open in panel" className="inline-flex">
              <button onClick={openInNewTab} className="qara-control p-1.5">
                <svg viewBox="0 0 14 14" fill="none" className="w-3.5 h-3.5"><path d="M6 2H3a1 1 0 00-1 1v8a1 1 0 001 1h8a1 1 0 001-1v-3M8 2h4m0 0v4m0-4L7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </button>
            </Tooltip>
            <button onClick={onClose} className="qara-control p-1.5 text-muted hover:text-primary" aria-label="Close">
              <svg viewBox="0 0 14 14" fill="none" className="w-3.5 h-3.5"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && (
            <div className="space-y-3 animate-pulse">
              {[1,2,3].map(i => <div key={i} className="h-12 rounded-xl bg-surface-subtle" />)}
            </div>
          )}
          {error && <p className="text-sm text-danger">Failed to load evidence: {error}</p>}
          {evidence?.type === 'run'  && <RunEvidenceView  data={evidence} />}
          {evidence?.type === 'test' && <TestEvidenceView data={evidence} />}
        </div>
      </aside>
    </>
  );
}

function RunEvidenceView({ data }: { data: ApiEvidenceRun }) {
  const passRate = data.total_tests > 0 ? Math.round(data.passed_count / data.total_tests * 100) : null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2.5">
        {[
          { label: 'Total',     value: data.total_tests,  cls: 'text-primary' },
          { label: 'Passed',    value: data.passed_count, cls: 'text-success' },
          { label: 'Failed',    value: data.failed_count, cls: 'text-danger'  },
          ...(passRate != null ? [{ label: 'Pass Rate', value: `${passRate}%`, cls: passRate >= 80 ? 'text-success' : 'text-danger' }] : []),
        ].map(c => (
          <div key={c.label} className="qara-card-soft px-3.5 py-2.5">
            <p className="type-eyebrow mb-1">{c.label}</p>
            <p className={`text-xl font-bold tabular-nums ${c.cls}`}>{c.value}</p>
          </div>
        ))}
      </div>
      {data.top_failed.length > 0 && (
        <div>
          <p className="type-eyebrow mb-2">Top Failures</p>
          <div className="space-y-2">
            {data.top_failed.slice(0, 5).map((t, i) => (
              <div key={i} className="qara-card-soft px-3.5 py-2.5">
                <p className="text-sm font-medium text-primary truncate">{t.name}</p>
                {t.error_type && <p className="text-xs text-danger mt-0.5">{t.error_type}</p>}
                {t.message    && <p className="text-xs text-muted mt-0.5 truncate">{t.message}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TestEvidenceView({ data }: { data: ApiEvidenceTest }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2.5">
        {[
          { label: 'Classification', value: data.classification,           cls: 'text-primary text-sm' },
          { label: 'Risk Tier',      value: data.risk_tier.toUpperCase(),  cls: 'text-warning' },
          { label: 'Pass Rate',      value: `${Math.round(data.pass_rate * 100)}%`, cls: data.pass_rate >= 0.8 ? 'text-success' : 'text-danger' },
          { label: 'Runs',           value: String(data.run_count),        cls: 'text-primary' },
        ].map(c => (
          <div key={c.label} className="qara-card-soft px-3.5 py-2.5">
            <p className="type-eyebrow mb-1">{c.label}</p>
            <p className={`font-bold ${c.cls}`}>{c.value}</p>
          </div>
        ))}
      </div>
      {data.why_relevant.length > 0 && (
        <div>
          <p className="type-eyebrow mb-2">Why It's Relevant</p>
          <ul className="space-y-1.5">
            {data.why_relevant.map((w, i) => (
              <li key={i} className="flex gap-2 text-sm text-secondary">
                <span className="text-muted shrink-0 mt-0.5">·</span>{w}
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.recent_runs.length > 0 && (
        <div>
          <p className="type-eyebrow mb-2">Recent Runs</p>
          <div className="space-y-1.5">
            {data.recent_runs.slice(0, 6).map((r, i) => (
              <div key={i} className="flex items-center justify-between px-3.5 py-2 rounded-xl" style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)' }}>
                <span className="text-xs text-muted">{r.run_label}</span>
                <span className={`text-xs font-semibold ${r.status === 'passed' ? 'text-success' : r.status === 'skipped' ? 'text-muted' : 'text-danger'}`}>
                  {r.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function testNameFromSource(s: ApiSource): string | null {
  if (s.name) return s.name;
  if (s.type === 'test' && s.label) return s.label.toLowerCase().replace(/[()]/g, '');
  return null;
}

function parseRiskTier(meta: string): RiskTier {
  const match = meta.match(/\b(CRITICAL|HIGH|MEDIUM|LOW)\b/i)?.[1]?.toUpperCase();
  if (match === 'CRITICAL' || match === 'HIGH' || match === 'MEDIUM' || match === 'LOW') return match;
  return 'MEDIUM';
}

function parsePassRate(meta: string): number {
  const match = meta.match(/(\d+(?:\.\d+)?)%\s+pass rate/i);
  return match ? Number(match[1]) / 100 : 0;
}

function parseEligibleTests(answer: string, fallback: number) {
  const match = answer.match(/(?:a total of|total of|there are)\s+(\d+)\s+eligible tests/i);
  return match ? Number(match[1]) : fallback;
}

function parseScopeLabel(answer: string, contextMode: string) {
  const runMatch = answer.match(/across the last\s+(\d+)\s+runs/i);
  if (runMatch) return `Last ${runMatch[1]} runs`;
  if (contextMode === 'latest_vs_previous') return 'Latest vs previous';
  if (contextMode === 'last5') return 'Last 5 runs';
  if (contextMode === 'last10') return 'Last 10 runs';
  return 'Selected run window';
}

function historyFromSparkline(sparkline: string): HistoryState[] {
  return [...sparkline].map(char => {
    if (char === '✓') return 'PASS';
    if (char === '✗' || char === 'x' || char === 'X') return 'FAIL';
    if (char === '•') return 'SKIP';
    return 'UNKNOWN';
  });
}

function trailingFailStreak(runs: ApiEvidenceTest['recent_runs']) {
  let streak = 0;
  for (const run of runs) {
    if (run.status === 'failed') streak += 1;
    else break;
  }
  return streak;
}

function provisionalRiskResult(data: ApiAskResponse, question: string): RiskRankingResult | null {
  const testSources = data.sources.filter(source => source.type === 'test');
  if (data.intent !== INTENT_RANKING_LIST || testSources.length === 0) return null;
  const lowerQuestion = question.toLowerCase();
  const lowerAnswer = data.answer.toLowerCase();
  const looksLikeRiskRanking =
    lowerQuestion.includes('likely to fail')
    || lowerQuestion.includes('highest risk')
    || lowerQuestion.includes('risk')
    || lowerAnswer.includes('risk score')
    || lowerAnswer.includes('likely to fail next run');
  if (!looksLikeRiskRanking) return null;

  const ranking = testSources.map((source, index) => ({
    rank: index + 1,
    testName: source.label,
    riskTier: parseRiskTier(source.meta),
    passRate: parsePassRate(source.meta),
    primaryReason: 'Detailed evidence is loading in the result workspace.',
    evidence: source.meta ? [{ label: 'Source summary', value: source.meta }] : [],
  }));

  const highRisk = ranking.filter(item => item.riskTier === 'CRITICAL' || item.riskTier === 'HIGH').length;
  const mediumRisk = ranking.filter(item => item.riskTier === 'MEDIUM').length;
  const lowRisk = ranking.filter(item => item.riskTier === 'LOW').length;

  return {
    type: 'risk_ranking',
    title: 'Most likely to fail next run',
    subtitle: 'Ranked by QARA risk score across the selected run window',
    scope: {
      label: parseScopeLabel(data.answer, data.context_mode),
      eligibleTests: parseEligibleTests(data.answer, testSources.length),
    },
    summary: {
      highRisk,
      mediumRisk,
      lowRisk,
      lowestPassRate: ranking.length > 0 ? Math.min(...ranking.map(item => item.passRate)) : undefined,
    },
    ranking,
  };
}

function ownerPrimaryReason(source: ApiSource) {
  const failureRate = source.failure_rate ?? 0;
  const failedExecutions = source.failed_executions ?? 0;
  const totalExecutions = source.total_executions ?? 0;
  const failingTests = source.failing_tests ?? 0;
  const totalTests = source.total_tests ?? 0;

  if (source.rank_label === 'Highest') {
    return `Highest owner failure rate at ${Math.round(failureRate * 100)}% across ${failedExecutions}/${totalExecutions} executions.`;
  }
  if (failingTests > 0 && totalTests > 0) {
    return `${failingTests} of ${totalTests} owned tests are currently contributing failures.`;
  }
  return `${failedExecutions} failed executions observed across the current ownership history.`;
}

function provisionalOwnerFailureRateResult(data: ApiAskResponse): OwnerFailureRateResult | null {
  const ownerSources = data.sources.filter(
    source => source.type === 'owner' && source.metric === 'failure_rate',
  );
  if (ownerSources.length === 0) return null;

  const totalRuns = Math.max(
    0,
    ...ownerSources.map(source => source.run_count ?? 0),
  );

  const ranking = ownerSources.map((source, index) => ({
    rank: index + 1,
    ownerName: source.label,
    failureRate: source.failure_rate ?? 0,
    failedExecutions: source.failed_executions ?? 0,
    totalExecutions: source.total_executions ?? 0,
    failingTests: source.failing_tests ?? 0,
    totalTests: source.total_tests ?? 0,
    runCount: source.run_count ?? 0,
    primaryReason: ownerPrimaryReason(source),
    emphasis: (source.rank_label === 'Highest'
      ? 'highest_rate'
      : (source.failed_executions ?? 0) >= Math.max(...ownerSources.map(item => item.failed_executions ?? 0))
        ? 'most_failures'
        : undefined) as 'highest_rate' | 'most_failures' | undefined,
    evidence: [
      { label: 'Source summary', value: source.meta },
      { label: 'Failure rate', value: `${Math.round((source.failure_rate ?? 0) * 100)}%` },
      { label: 'Failed executions', value: `${source.failed_executions ?? 0}/${source.total_executions ?? 0}` },
      { label: 'Failing tests', value: `${source.failing_tests ?? 0}/${source.total_tests ?? 0}` },
    ],
  }));

  return {
    type: 'owner_failure_rate',
    title: 'Owners with the highest failure rate',
    subtitle: 'Ranked by current-owner failure rate across the available run history',
    scope: {
      label: 'All-time ownership history',
      totalRuns: totalRuns || undefined,
      owners: ranking.length,
    },
    summary: {
      highestFailureRate: ranking.length > 0 ? Math.max(...ranking.map(item => item.failureRate)) : 0,
      mostFailures: ranking.length > 0 ? Math.max(...ranking.map(item => item.failedExecutions)) : 0,
      mostFailingTests: ranking.length > 0 ? Math.max(...ranking.map(item => item.failingTests)) : 0,
    },
    ranking,
  };
}

async function hydrateRiskResult(
  result: RiskRankingResult,
  sources: ApiSource[],
): Promise<RiskRankingResult> {
  let derivedWindowEnd: string | undefined;
  const hydratedRanking = await Promise.all(result.ranking.map(async item => {
    const source = sources.find(candidate => candidate.label === item.testName);
    const canonical = source ? testNameFromSource(source) : null;
    if (!canonical) return item;

    try {
      const response = await fetch(`/api/evidence/test/${encodeURIComponent(canonical)}`);
      if (!response.ok) return item;
      const payload = await response.json() as ApiEvidence;
      if (payload.type !== 'test') return item;

      const failStreak = trailingFailStreak(payload.recent_runs);
      const recentDecline = payload.why_relevant.some(reason => /declin/i.test(reason)) ? Math.min(1, (1 - payload.pass_rate) * 0.6) : undefined;
      if (!derivedWindowEnd && payload.recent_runs[0]?.run_label) {
        derivedWindowEnd = payload.recent_runs[0].run_label;
      }

      return {
        ...item,
        riskTier: parseRiskTier(payload.risk_tier),
        passRate: payload.pass_rate,
        primaryReason: payload.why_relevant[0] ?? item.primaryReason,
        history: historyFromSparkline(payload.sparkline),
        signals: {
          volatility: payload.flip_score,
          failureBurden: 1 - payload.pass_rate,
          recentDecline,
          failStreak: failStreak > 0 ? failStreak : undefined,
        },
        evidence: [
          { label: 'Risk score', value: `${Math.round(payload.risk_pct)}%` },
          { label: 'Classification', value: payload.classification },
          ...(payload.recent_runs[0]?.run_label ? [{ label: 'Recent run', value: payload.recent_runs[0].run_label }] : []),
          ...(payload.most_frequent_error
            ? [{ label: payload.most_frequent_error.category, value: payload.most_frequent_error.message }]
            : []),
          ...payload.why_relevant.map(reason => ({ label: 'Why relevant', value: reason })),
        ],
      };
    } catch {
      return item;
    }
  }));

  return {
    ...result,
    scope: {
      ...result.scope,
      windowEnd: derivedWindowEnd ?? result.scope.windowEnd,
    },
    summary: {
      ...result.summary,
      lowestPassRate: hydratedRanking.length > 0 ? Math.min(...hydratedRanking.map(item => item.passRate)) : result.summary.lowestPassRate,
    },
    ranking: hydratedRanking,
  };
}


function ownerFailureRateSummary(result: OwnerFailureRateResult) {
  const topOwners = result.ranking.slice(0, 3);
  const bullets = topOwners.map(item =>
    `${item.rank}. ${item.ownerName} — ${Math.round(item.failureRate * 100)}% failure rate · ${item.failedExecutions}/${item.totalExecutions} failed executions`,
  );

  return [
    `I ranked ${result.ranking.length} owners by failure rate across the current ownership history.`,
    '',
    'Top owners:',
    ...bullets,
    '',
    'The detailed owner comparison is shown in the Results workspace.',
  ].join('\n');
}

// ─────────────────────────────────────────────────────────────
// Message bubbles
// ─────────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[78%] px-4 py-3 rounded-2xl rounded-tr-md text-sm leading-relaxed text-white"
        style={{ background: 'var(--color-info)' }}>
        {content}
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-1">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-border-strong animate-bounce"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  );
}

function AssistantBubble({
  msg, askedQuestionKeys, onSourceClick, onFollowUp, onViewResults, onCodeClick,
}: {
  msg:              ConvMessage;
  askedQuestionKeys: Set<string>;
  onSourceClick:    (source: ApiSource, all: ApiSource[], idx: number) => void;
  onFollowUp:       (q: string) => void;
  onViewResults:    () => void;
  onCodeClick:      (name: string) => void;
}) {
  const sources = msg.sources ?? [];
  const hasStructuredResult = Boolean(msg.resultType);
  const followUps = (msg.followUps ?? []).filter(q => !askedQuestionKeys.has(normalizeQuestion(q)));

  return (
    <div className="flex justify-start gap-3">
      {/* Avatar */}
      <div className="shrink-0 mt-1 w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-info"
        style={{ background: 'rgb(var(--info-rgb) / 0.1)', border: '1px solid rgb(var(--info-rgb) / 0.2)' }}>
        AI
      </div>

      <div className="max-w-[88%] space-y-2.5 min-w-0">
        {/* Content bubble */}
        <div className="px-4 py-3.5 rounded-2xl rounded-tl-md"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', boxShadow: 'var(--shadow-card)' }}>
          {msg.loading ? <ThinkingDots /> : (
            <div
              className="prose prose-sm max-w-none
                         prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-ol:my-1
                         prose-headings:font-semibold prose-headings:text-primary
                         prose-h3:text-base prose-h3:mt-3 prose-h3:mb-1.5
                         prose-strong:text-primary
                         prose-code:text-info prose-code:bg-info/[0.08]
                         prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-[0.85em]
                         prose-code:cursor-pointer
                         prose-pre:bg-surface-subtle prose-pre:border prose-pre:border-border-subtle prose-pre:rounded-xl
                         text-secondary [&_p]:text-secondary [&_li]:text-secondary"
              onClick={(event) => {
                const target = event.target as HTMLElement | null;
                const code = target?.closest('code');
                const text = code?.textContent?.trim();
                if (!text || !text.includes('(') || !text.includes(')')) return;
                onCodeClick(text);
              }}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
            />
          )}
        </div>

        {!msg.loading && hasStructuredResult && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={onViewResults}
              className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
            >
              View results workspace
            </button>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Structured evidence lives in the results panel.
            </span>
          </div>
        )}

        {!msg.loading && sources.length > 0 && !hasStructuredResult && (
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
              Related evidence
            </p>
            <div className="space-y-2">
              {sources.slice(0, 3).map((s, i) => (
                <button
                  key={i}
                  onClick={() => onSourceClick(s, sources, i)}
                  className="group w-full rounded-2xl border border-slate-200 bg-white px-3.5 py-3 text-left shadow-sm transition hover:border-blue-200 hover:bg-blue-50/40 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-blue-500/30 dark:hover:bg-blue-500/10"
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-sm dark:border-slate-700 dark:bg-slate-900">
                      <span aria-hidden="true">{s.icon}</span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-50">
                          {s.label}
                        </p>
                        <span className="shrink-0 text-slate-400 transition group-hover:text-blue-500 dark:text-slate-500 dark:group-hover:text-blue-300">
                          <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5">
                            <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </span>
                      </div>
                      {s.meta && (
                        <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
                          {s.meta}
                        </p>
                      )}
                    </div>
                  </div>
                </button>
              ))}
              {sources.length > 3 && (
                <button
                  onClick={() => onSourceClick(sources[3], sources, 3)}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-blue-500/30 dark:hover:bg-blue-500/10 dark:hover:text-blue-300"
                >
                  Open {sources.length - 3} more evidence item{sources.length - 3 === 1 ? '' : 's'}
                </button>
              )}
            </div>
          </div>
        )}

        {!msg.loading && followUps.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
              Follow-up questions
            </p>
            <div className="flex flex-wrap gap-1.5">
              {followUps.map((q, i) => (
              <button key={i} onClick={() => onFollowUp(q)}
                className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition-colors hover:border-blue-300 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-45 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20">
                {q}
              </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SuggestedQuestions({
  questions,
  onSelect,
  disabled = false,
  compact = false,
}: {
  questions: SuggestedQuestion[];
  onSelect: (question: string) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  if (questions.length === 0) return null;

  const groups = questions.reduce<Array<{ label: string; icon?: string; items: SuggestedQuestion[] }>>((acc, item) => {
    const label = item.label ?? 'Suggested';
    const existing = acc.find(group => group.label === label);
    if (existing) {
      existing.items.push(item);
    } else {
      acc.push({ label, icon: item.icon, items: [item] });
    }
    return acc;
  }, []);

  return (
    <div className={compact ? 'space-y-2 px-4' : 'w-full max-w-xl space-y-5'}>
      <div className="flex items-center gap-2">
        <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5 text-info" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7 1.75v1.5M7 10.75v1.5M12.25 7h-1.5M3.25 7h-1.5M10.7 3.3 9.65 4.35M4.35 9.65 3.3 10.7M10.7 10.7 9.65 9.65M4.35 4.35 3.3 3.3"/>
        </svg>
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">Suggested questions</p>
      </div>

      {compact ? (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {questions.map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.question)}
              disabled={disabled}
              className="qara-pill shrink-0 max-w-[280px] truncate text-left text-xs transition-colors hover:border-info/20 hover:bg-info/[0.06] hover:text-info disabled:cursor-not-allowed disabled:opacity-45"
            >
              {item.question}
            </button>
          ))}
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map(group => (
            <div key={group.label} className="space-y-2">
              <div className="flex items-center gap-2">
                {group.icon && <span className="text-base" aria-hidden="true">{group.icon}</span>}
                <p className="text-sm font-semibold text-primary">{group.label}</p>
              </div>
              <div className="space-y-2">
                {group.items.map(item => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelect(item.question)}
                    disabled={disabled}
                    className="group flex min-h-11 w-full items-center gap-3 rounded-xl border border-border-subtle bg-surface px-3.5 py-2.5 text-left shadow-sm transition-colors hover:border-info/25 hover:bg-info/[0.04] disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5 shrink-0 text-info/70" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="6" cy="6" r="3.75"/>
                      <path d="m9 9 2.5 2.5"/>
                    </svg>
                    <span className="min-w-0 flex-1 text-sm leading-5 text-secondary group-hover:text-primary">
                      {item.question}
                    </span>
                    <svg viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5 shrink-0 text-muted transition group-hover:text-info" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 3.5 8.5 7 5 10.5"/>
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// ChatPanel
// ─────────────────────────────────────────────────────────────

export function ChatPanel() {
  const { currentProject } = useProject();

  const [messages,         setMessages]         = useState<ConvMessage[]>([]);
  const [input,            setInput]            = useState('');
  const [sending,          setSending]          = useState(false);
  const [cards,            setCards]            = useState<ApiHomepageCard[]>([]);
  const [drawerSource,     setDrawerSource]     = useState<{ source: ApiSource; all: ApiSource[]; idx: number } | null>(null);
  const [llmInfo,          setLlmInfo]          = useState<ApiLlmInfo | null>(null);
  const [activeResult,     setActiveResult]     = useState<QaraResult | null>(null);
  const [activeResultToken, setActiveResultToken] = useState<string | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [mobilePane,       setMobilePane]       = useState<'chat' | 'results'>('chat');
  const [chatPanelWidth,   setChatPanelWidth]   = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_CHAT_PANEL_WIDTH;
    const raw = window.localStorage.getItem(CHAT_PANEL_WIDTH_KEY);
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? clampChatPanelWidth(parsed) : DEFAULT_CHAT_PANEL_WIDTH;
  });

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatMessagesRef = useRef<HTMLDivElement>(null);
  const resultScrollRef = useRef<HTMLDivElement>(null);
  const resizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const idCounter   = useRef(0);
  const uid         = () => String(++idCounter.current);

  useEffect(() => {
    const params = new URLSearchParams();
    if (currentProject) params.set('project', currentProject);
    fetch(`/api/homepage-cards?${params}`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => setCards((d.cards ?? []) as ApiHomepageCard[]))
      .catch(() => {});
  }, [currentProject]);

  useEffect(() => {
    fetch('/api/llm/info')
      .then(r => r.ok ? r.json() as Promise<ApiLlmInfo> : Promise.reject())
      .then(info => setLlmInfo(info))
      .catch(() => {});
  }, []);

  const scrollChatToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const el = chatMessagesRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  const scrollWorkspaceToTop = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const el = resultScrollRef.current;
    if (!el) return;
    el.scrollTo({ top: 0, behavior });
  }, []);

  useEffect(() => {
    if (messages.length === 0) return;
    requestAnimationFrame(() => {
      scrollChatToBottom('smooth');
    });
  }, [messages, scrollChatToBottom]);

  useEffect(() => {
    if (!activeResultToken) return;
    requestAnimationFrame(() => {
      scrollWorkspaceToTop('smooth');
    });
  }, [activeResultToken, scrollWorkspaceToTop]);

  useEffect(() => {
    window.localStorage.setItem(CHAT_PANEL_WIDTH_KEY, String(chatPanelWidth));
  }, [chatPanelWidth]);

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }

  function buildHistory() {
    return messages.filter(m => !m.loading).slice(-12).map(m => ({ role: m.role, content: m.content }));
  }

  const send = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || sending) return;
    const userMsg: ConvMessage    = { id: uid(), role: 'user',      content: q };
    const loadingMsg: ConvMessage = { id: uid(), role: 'assistant', content: '', loading: true };
    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInput('');
    setSending(true);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    const history = buildHistory();
    try {
      const res = await fetch('/api/ask', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ question: q, project: currentProject || null, history }),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data: ApiAskResponse = await res.json();
      const provisionalResult =
        data.result
        ?? provisionalRiskResult(data, q)
        ?? provisionalOwnerFailureRateResult(data);
      const answerContent = provisionalResult?.type === 'owner_failure_rate'
          ? ownerFailureRateSummary(provisionalResult)
          : data.answer;
      const assistantMsg: ConvMessage = {
        id:        loadingMsg.id,
        role:      'assistant',
        content:   answerContent,
        sources:   data.sources,
        followUps: data.follow_ups,
        intent:    data.intent,
        resultType: provisionalResult?.type,
      };
      setMessages(prev => prev.map(m => m.id === loadingMsg.id ? assistantMsg : m));
      if (provisionalResult) {
        setActiveResult(provisionalResult);
        setActiveResultToken(loadingMsg.id);
        setMobilePane(data.uiHints?.activeTab ?? 'results');
      } else {
        setActiveResult(null);
        setActiveResultToken(null);
        setMobilePane('chat');
      }
      if (!data.result && provisionalResult?.type === 'risk_ranking') {
        setWorkspaceLoading(true);
        void hydrateRiskResult(provisionalResult, data.sources)
          .then(hydrated => setActiveResult(hydrated))
          .finally(() => setWorkspaceLoading(false));
      } else {
        setWorkspaceLoading(false);
      }
    } catch (e) {
      const errorMsg: ConvMessage = { id: loadingMsg.id, role: 'assistant', content: `Something went wrong: ${e instanceof Error ? e.message : String(e)}` };
      setMessages(prev => prev.map(m => m.id === loadingMsg.id ? errorMsg : m));
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }, [sending, currentProject, messages]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); send(input); }
  }

  function handleNewConversation() {
    setMessages([]);
    setInput('');
    setActiveResult(null);
    setActiveResultToken(null);
    setWorkspaceLoading(false);
    setMobilePane('chat');
    setTimeout(() => textareaRef.current?.focus(), 50);
  }

  function handleViewResults() {
    setMobilePane('results');
    requestAnimationFrame(() => {
      scrollWorkspaceToTop('smooth');
    });
  }

  const focusResultTest = useCallback((testName: string) => {
    setMobilePane('results');
    requestAnimationFrame(() => {
      const container = resultScrollRef.current;
      if (!container) return;
      const normalized = testName.trim().toLowerCase();
      const target = container.querySelector<HTMLElement>(`[data-result-test="${CSS.escape(normalized)}"]`);
      if (!target) {
        scrollWorkspaceToTop('smooth');
        return;
      }
      const containerRect = container.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const nextTop = container.scrollTop + (targetRect.top - containerRect.top) - 24;
      container.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' });
      const previousTransition = target.style.transition;
      const previousBoxShadow = target.style.boxShadow;
      const previousBorderColor = target.style.borderColor;
      target.style.transition = 'box-shadow 220ms ease, border-color 220ms ease';
      target.style.boxShadow = '0 0 0 3px rgb(var(--info-rgb) / 0.18)';
      target.style.borderColor = 'var(--color-info)';
      window.setTimeout(() => {
        target.style.boxShadow = previousBoxShadow;
        target.style.borderColor = previousBorderColor;
        target.style.transition = previousTransition;
      }, 2200);
    });
  }, [scrollWorkspaceToTop]);

  const handleResizeStart = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    resizeStateRef.current = { startX: event.clientX, startWidth: chatPanelWidth };
    const onMouseMove = (moveEvent: MouseEvent) => {
      const state = resizeStateRef.current;
      if (!state) return;
      const nextWidth = clampChatPanelWidth(state.startWidth + (moveEvent.clientX - state.startX));
      setChatPanelWidth(nextWidth);
    };
    const onMouseUp = () => {
      resizeStateRef.current = null;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, [chatPanelWidth]);

  const showWelcome = messages.length === 0;
  const askedQuestionKeys = useMemo(
    () => new Set(messages.filter(msg => msg.role === 'user').map(msg => normalizeQuestion(msg.content))),
    [messages],
  );
  const visibleFollowUpQuestionKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const msg of messages) {
      if (msg.role !== 'assistant' || msg.loading) continue;
      for (const question of msg.followUps ?? []) {
        const key = normalizeQuestion(question);
        if (key && !askedQuestionKeys.has(key)) keys.add(key);
      }
    }
    return keys;
  }, [askedQuestionKeys, messages]);
  const suggestedQuestions = useMemo(
    () => contextualSuggestions(activeResult, cards)
      .filter(item => !askedQuestionKeys.has(normalizeQuestion(item.question))),
    [activeResult, askedQuestionKeys, cards],
  );
  const compactSuggestedQuestions = useMemo(
    () => suggestedQuestions
      .filter(item => !visibleFollowUpQuestionKeys.has(normalizeQuestion(item.question)))
      .slice(0, 4),
    [suggestedQuestions, visibleFollowUpQuestionKeys],
  );
  const desktopGridStyle = useMemo(
    () => ({ '--chat-panel-width': `${chatPanelWidth}px` } as React.CSSProperties),
    [chatPanelWidth],
  );

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-4">

      {/* Evidence drawer */}
      {drawerSource && (
        <EvidenceDrawer
          source={drawerSource.source}
          allSources={drawerSource.all}
          currentIndex={drawerSource.idx}
          onNavigate={idx => setDrawerSource(prev => prev ? { ...prev, source: prev.all[idx], idx } : null)}
          onClose={() => setDrawerSource(null)}
          project={currentProject}
        />
      )}

      <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm lg:hidden dark:border-slate-800 dark:bg-slate-950">
        {(['chat', 'results'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setMobilePane(tab)}
            className={[
              'flex-1 rounded-xl px-3 py-2 text-sm font-medium transition',
              mobilePane === tab
                ? 'bg-selected text-primary shadow-sm'
                : 'text-muted hover:bg-hover hover:text-secondary',
            ].join(' ')}
          >
            {tab === 'chat' ? 'Chat' : 'Results'}
          </button>
        ))}
      </div>

      <div
        className="grid min-h-0 flex-1 gap-4 lg:gap-0 lg:[grid-template-columns:var(--chat-panel-width)_10px_minmax(0,1fr)]"
        style={desktopGridStyle}
      >
        <section
          className={[
            'min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950',
            mobilePane === 'chat' ? 'flex' : 'hidden',
            'lg:flex',
          ].join(' ')}
        >
          {/* ── Chat header (conversation active only) ── */}
          {!showWelcome && (
            <div className="flex shrink-0 items-center justify-between border-b border-border-subtle px-4 py-2.5">
              <span className="text-xs font-medium text-muted">Conversation</span>
              <Tooltip content="New conversation">
                <button
                  onClick={handleNewConversation}
                  aria-label="New conversation"
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-hover hover:text-primary transition-colors"
                >
                  <svg viewBox="0 0 14 14" fill="none" className="h-4 w-4">
                    <line x1="7" y1="2" x2="7" y2="12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    <line x1="2" y1="7" x2="12" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                </button>
              </Tooltip>
            </div>
          )}

          {/* Scroll area */}
          <div ref={chatMessagesRef} className="min-h-0 flex-1 overflow-y-auto pb-2">

            {/* ── Welcome ── */}
            {showWelcome && (
              <div className="flex flex-col items-center gap-8 px-4 pb-6 pt-12">
                <div className="space-y-2 text-center">
                  <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-2xl"
                    style={{ background: 'rgb(var(--info-rgb) / 0.1)', border: '1px solid rgb(var(--info-rgb) / 0.18)' }}>
                    <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6 text-info" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                  </div>
                  <h2 className="text-2xl font-semibold tracking-tight text-primary">Ask me anything</h2>
                  <p className="max-w-xs text-sm text-muted">
                    about your test quality, failures, flaky tests, and risk signals
                  </p>
                </div>

                <SuggestedQuestions
                  questions={suggestedQuestions}
                  onSelect={send}
                  disabled={sending}
                />
              </div>
            )}

            {!showWelcome && (
              <div className="space-y-5 px-4 pt-5">
                {messages.map(msg => (
                  msg.role === 'user'
                    ? <UserBubble key={msg.id} content={msg.content} />
                    : <AssistantBubble
                        key={msg.id}
                        msg={msg}
                        askedQuestionKeys={askedQuestionKeys}
                        onSourceClick={(s, all, i) => setDrawerSource({ source: s, all, idx: i })}
                        onFollowUp={q => send(q)}
                        onViewResults={handleViewResults}
                        onCodeClick={focusResultTest}
                      />
                ))}
              </div>
            )}
          </div>

          {/* ── Input bar ── */}
          <div className="shrink-0 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
            {!showWelcome && compactSuggestedQuestions.length > 0 && (
              <div className="pb-3">
                <SuggestedQuestions
                  questions={compactSuggestedQuestions}
                  onSelect={send}
                  disabled={sending}
                  compact
                />
              </div>
            )}

            <div className="flex items-end gap-2 px-4">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your tests… (⌘↵ to send)"
                rows={1}
                disabled={sending}
                className="flex-1 resize-none rounded-2xl px-4 py-3 text-sm leading-relaxed
                           text-primary placeholder-muted disabled:opacity-50 overflow-hidden
                           focus:outline-none"
                style={{
                  minHeight: '48px',
                  maxHeight: '200px',
                  background:  'var(--bg-surface)',
                  border:      '1px solid var(--border-default)',
                  boxShadow:   'var(--shadow-card)',
                  transition:  'border-color 150ms ease, box-shadow 150ms ease',
                }}
                onFocus={e => {
                  e.target.style.borderColor = 'var(--color-info)';
                  e.target.style.boxShadow   = '0 0 0 3px rgb(var(--info-rgb) / 0.1), var(--shadow-card)';
                }}
                onBlur={e => {
                  e.target.style.borderColor = 'var(--border-default)';
                  e.target.style.boxShadow   = 'var(--shadow-card)';
                }}
              />
              <button
                onClick={() => send(input)}
                disabled={!input.trim() || sending}
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl
                           font-medium text-white transition-all duration-150
                           hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35"
                style={{ background: 'var(--color-info)' }}
                aria-label="Send message"
              >
                {sending ? (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                ) : (
                  <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4">
                    <path d="M13 8L3 3l2 5-2 5 10-5z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
                  </svg>
                )}
              </button>
            </div>

            <div className="mt-1.5 flex items-center justify-center gap-1.5 pb-2 text-[11px] text-muted">
              <svg viewBox="0 0 14 14" fill="none" className="h-3 w-3 text-muted" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="7" cy="7" r="5"/><path d="M7 5v2l1.5 1.5"/>
              </svg>
              <span>Powered by</span>
              <span className="font-medium text-secondary">{llmInfo?.model ?? 'Gemma'}</span>
              <span className="mx-1 text-border-strong">·</span>
              <span>⌘↵ to send</span>
            </div>
          </div>
        </section>

        <div className="hidden min-h-0 lg:flex lg:items-stretch lg:justify-center">
          <button
            type="button"
            onMouseDown={handleResizeStart}
            aria-label="Resize chat panel"
            className="group flex w-[10px] cursor-col-resize items-center justify-center"
          >
            <span className="h-20 w-[4px] rounded-full bg-slate-200 transition group-hover:bg-blue-300 dark:bg-slate-700 dark:group-hover:bg-blue-500/70" />
          </button>
        </div>

        <section
          className={[
            'min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/50 shadow-sm dark:border-slate-800 dark:bg-slate-950/60',
            mobilePane === 'results' ? 'flex' : 'hidden',
            'lg:flex',
          ].join(' ')}
        >
          <div ref={resultScrollRef} className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-5">
            <ResultWorkspace result={activeResult} loading={workspaceLoading} />
          </div>
        </section>
      </div>
    </div>
  );
}
