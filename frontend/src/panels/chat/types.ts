export type RiskTier = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export type HistoryState = 'PASS' | 'FAIL' | 'SKIP' | 'UNKNOWN';

export type RiskRankingResult = {
  type: 'risk_ranking';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    windowEnd?: string;
    eligibleTests: number;
  };
  summary: {
    highRisk: number;
    mediumRisk: number;
    lowRisk: number;
    lowestPassRate?: number;
  };
  ranking: Array<{
    rank: number;
    testName: string;
    riskTier: RiskTier;
    passRate: number;
    primaryReason: string;
    history?: HistoryState[];
    signals?: {
      volatility?: number;
      failureBurden?: number;
      recentDecline?: number;
      failStreak?: number;
      durationSpike?: number;
    };
    evidence?: Array<{
      label: string;
      value: string;
    }>;
  }>;
};

export type OwnerFailureRateResult = {
  type: 'owner_failure_rate';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    totalRuns?: number;
    owners: number;
  };
  summary: {
    highestFailureRate: number;
    mostFailures: number;
    mostFailingTests: number;
  };
  ranking: Array<{
    rank: number;
    ownerName: string;
    failureRate: number;
    failedExecutions: number;
    totalExecutions: number;
    failingTests: number;
    totalTests: number;
    runCount: number;
    primaryReason: string;
    emphasis?: 'highest_rate' | 'most_failures';
    evidence?: Array<{
      label: string;
      value: string;
    }>;
  }>;
};

export type OwnerFlakyTestsResult = {
  type: 'owner_flaky_tests';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    runCount: number;
    owners: number;
    totalEvaluated: number;
  };
  summary: {
    highestFlakyCount: number;
    avgFlipScore: number;
    avgPassRate: number;
  };
  ranking: Array<{
    rank: number;
    ownerName: string;
    flakyCount: number;
    totalTests: number;
    avgFlipScore: number;
    avgPassRate: number;
    primaryReason: string;
    topTests: Array<{
      testName: string;
      canonicalName?: string | null;
      flipScore: number;
      passRate: number;
    }>;
  }>;
};

export type OwnerSuiteComparisonResult = {
  type: 'owner_suite_comparison';
  title: string;
  subtitle?: string;
  owners: {
    ownerA: string;
    ownerB: string;
    timeLabel: string;
    runCount: number;
  };
  summary: {
    sharedSuites: number;
    ownerAOnlySuites: number;
    ownerBOnlySuites: number;
    ownerAFailingSuites: number;
    ownerBFailingSuites: number;
  };
  metrics: {
    ownerA: {
      passRate: number;
      failed: number;
      totalTests: number;
      flakyCount: number;
    };
    ownerB: {
      passRate: number;
      failed: number;
      totalTests: number;
      flakyCount: number;
    };
  };
  shared: Array<{
    suiteName: string;
    ownerATests: number;
    ownerAFailing: number;
    ownerBTests: number;
    ownerBFailing: number;
  }>;
  ownerAOnly: Array<{
    suiteName: string;
    tests: number;
    failing: number;
    newFailures: number;
  }>;
  ownerBOnly: Array<{
    suiteName: string;
    tests: number;
    failing: number;
    newFailures: number;
  }>;
};

export type OwnerWindowComparisonResult = {
  type: 'owner_window_comparison';
  title: string;
  subtitle?: string;
  owners: {
    ownerA: string;
    ownerB: string;
    timeLabel: string;
    runCount: number;
  };
  metrics: {
    ownerA: {
      totalTests: number;
      passRate: number;
      failureRate: number;
      failed: number;
      flakyCount: number;
      regressed: number;
      recovered: number;
      score: number;
    };
    ownerB: {
      totalTests: number;
      passRate: number;
      failureRate: number;
      failed: number;
      flakyCount: number;
      regressed: number;
      recovered: number;
      score: number;
    };
  };
  summary: {
    leader: string;
    passRateGap: number;
    flakyGap: number;
    regressionGap: number;
  };
  topRisks: {
    ownerA: Array<{
      testName: string;
      suite?: string;
      failCount: number;
    }>;
    ownerB: Array<{
      testName: string;
      suite?: string;
      failCount: number;
    }>;
  };
};

export type OwnerTestGapResult = {
  type: 'owner_test_gap';
  title: string;
  subtitle?: string;
  owner: string;
  comparedAgainst?: string | null;
  mode?: 'gap' | 'failing_tests';
  scope: {
    label: string;
    runCount: number;
    totalTests: number;
  };
  summary: {
    currentlyFailing: number;
    regressed: number;
    flaky: number;
    topSuite?: string | null;
  };
  tests: Array<{
    rank: number;
    testName: string;
    canonicalName?: string;
    suite?: string;
    passRate: number;
    failCount: number;
    currentStatus: string;
    regressed: boolean;
    flaky: boolean;
    riskTier: RiskTier;
    history?: HistoryState[];
    primaryReason: string;
    errorMessage?: string | null;
  }>;
};

export type OwnerSuiteRegressionsResult = {
  type: 'owner_suite_regressions';
  title: string;
  subtitle?: string;
  owner: string;
  comparedAgainst?: string | null;
  scope: {
    label: string;
    runCount: number;
    totalSuites: number;
  };
  summary: {
    topSuite?: string | null;
    regressedSuites: number;
    currentlyFailingSuites: number;
    flakySuites: number;
  };
  suites: Array<{
    rank: number;
    suiteName: string;
    tests: number;
    currentlyFailing: number;
    regressed: number;
    flaky: number;
    failuresInScope: number;
    lowestPassRate: number;
    topTests: Array<{
      testName: string;
      canonicalName?: string;
      passRate: number;
      failCount: number;
      currentStatus: string;
      regressed: boolean;
      flaky: boolean;
      errorMessage?: string | null;
    }>;
  }>;
};

export type SharedSuiteFailuresResult = {
  type: 'shared_suite_failures';
  title: string;
  subtitle?: string;
  owners: {
    ownerA: string;
    ownerB: string;
  };
  scope: {
    label: string;
    runCount: number;
    sharedSuites: number;
  };
  summary: {
    topSuite?: string | null;
    sharedSuites: number;
  };
  suites: Array<{
    rank: number;
    suiteName: string;
    combinedPressure: number;
    ownerA: {
      currentlyFailing: number;
      regressed: number;
      failuresInScope: number;
      topTests: Array<{
        testName: string;
        canonicalName?: string;
        passRate: number;
        failCount: number;
        currentStatus: string;
        regressed: boolean;
        flaky: boolean;
        errorMessage?: string | null;
      }>;
    };
    ownerB: {
      currentlyFailing: number;
      regressed: number;
      failuresInScope: number;
      topTests: Array<{
        testName: string;
        canonicalName?: string;
        passRate: number;
        failCount: number;
        currentStatus: string;
        regressed: boolean;
        flaky: boolean;
        errorMessage?: string | null;
      }>;
    };
  }>;
};

export type SuiteFailureRankingResult = {
  type: 'suite_failure_ranking';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    runCount: number;
    totalSuites: number;
    totalTests: number;
  };
  summary: {
    topSuite?: string | null;
    totalFailures: number;
    currentlyFailingSuites: number;
    flakySuites: number;
  };
  ranking: Array<{
    rank: number;
    suiteName: string;
    totalTests: number;
    failedExecutions: number;
    totalExecutions: number;
    failureRate: number;
    failingTests: number;
    flakyTests: number;
    owners: string[];
    primaryReason: string;
    topTests: Array<{
      testName: string;
      owner?: string | null;
      failCount: number;
      passRate: number;
      currentStatus: string;
      flaky: boolean;
    }>;
  }>;
};

export type RunRetrievalResult = {
  type: 'run_retrieval';
  title: string;
  subtitle?: string;
  run: {
    label: string;
    project?: string | null;
    runId?: string | null;
  };
  query: {
    kind: 'failed_tests' | 'skipped_tests' | 'all_tests' | 'status_lookup' | 'run_counts';
    label: string;
    targetTest?: string | null;
    matchedTests: number;
  };
  summary: {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
    passRate: number;
  };
  tests: Array<{
    name: string;
    status: string;
    suite?: string | null;
    owner?: string | null;
    errorType?: string | null;
    message?: string | null;
  }>;
};

export type ExceptionRetrievalResult = {
  type: 'exception_retrieval';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    query: string;
    runCount: number;
  };
  summary: {
    matches: number;
    uniqueTests: number;
    affectedRuns: number;
    dominantCategory?: string | null;
  };
  matches: Array<{
    testName: string;
    canonicalName?: string | null;
    runLabel: string;
    status: string;
    suite?: string | null;
    owner?: string | null;
    errorType?: string | null;
    message?: string | null;
    category?: string | null;
  }>;
};

export type StabilityTrendResult = {
  type: 'stability_trend';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    runCount: number;
    latestRun?: string | null;
    totalEvaluated: number;
  };
  query: {
    kind:
      | 'flaky_tests'
      | 'low_pass_rate'
      | 'low_pass_rate_and_failure_count'
      | 'high_pass_rate'
      | 'highest_failure_frequency'
      | 'failed_every_run'
      | 'never_failed'
      | 'unstable_tests'
      | 'intermittent_failures'
      | 'failed_after_passing'
      | 'improved_over_time';
    label: string;
    threshold?: number | null;
    failureCountThreshold?: number | null;
  };
  summary: {
    matches: number;
    avgPassRate: number;
    avgFlipScore: number;
    highestFailCount: number;
    activelyFailing: number;
  };
  tests: Array<{
    rank: number;
    testName: string;
    canonicalName?: string | null;
    suite?: string | null;
    owner?: string | null;
    classification: string;
    passRate: number;
    flipScore: number;
    failCount: number;
    passCount: number;
    runCount: number;
    currentStreak: number;
    lastPassedRun?: number | null;
    lastFailedRun?: number | null;
    history?: HistoryState[];
    primaryReason: string;
    tier: RiskTier;
  }>;
};

export type RootCauseInsightResult = {
  type: 'root_cause_insight';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    kind: 'test_frequency' | 'cause_mix' | 'common_patterns' | 'flaky_causes' | 'root_cause_scope';
    runCount: number;
    latestRun?: string | null;
    targetTest?: string | null;
    totalTestsEvaluated: number;
  };
  summary: {
    totalFailures: number;
    affectedTests: number;
    affectedRuns: number;
    dominantCategory?: string | null;
    dominantFamily?: string | null;
  };
  causes: Array<{
    rank: number;
    category: string;
    family: string;
    count: number;
    affectedTests: number;
    affectedRuns: number;
    probableCause: string;
    recommendedAction: string;
    confidence: 'High' | 'Medium' | 'Low' | string;
    sampleMessages: string[];
    topTests: Array<{
      testName: string;
      canonicalName?: string | null;
      count: number;
    }>;
  }>;
};

export type PerformanceTimingResult = {
  type: 'performance_timing';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    runCount: number;
    latestRun?: string | null;
    totalEvaluated: number;
  };
  query: {
    kind:
      | 'threshold_exceeded'
      | 'slowest_tests'
      | 'duration_increasing'
      | 'performance_regressions';
    label: string;
    thresholdMs?: number | null;
  };
  summary: {
    matches: number;
    avgDurationMs: number;
    slowestDurationMs: number;
    highestTrendScore: number;
    currentlySlow: number;
  };
  tests: Array<{
    rank: number;
    testName: string;
    canonicalName?: string | null;
    suite?: string | null;
    owner?: string | null;
    currentStatus: string;
    avgDurationMs: number;
    latestDurationMs: number;
    maxDurationMs: number;
    trendScore: number;
    slowRunCount: number;
    runCount: number;
    recentDurationsMs?: number[];
    primaryReason: string;
    tier: RiskTier;
  }>;
};

export type NewFailuresIntroducedResult = {
  type: 'new_failures_introduced';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    runCount: number;
    latestRun?: string | null;
    previousRun?: string | null;
    totalEvaluated: number;
  };
  summary: {
    newFailures: number;
    affectedSuites: number;
    affectedOwners: number;
    flakyAmongNew: number;
  };
  tests: Array<{
    rank: number;
    testName: string;
    canonicalName?: string | null;
    suite?: string | null;
    owner?: string | null;
    classification: string;
    passRate: number;
    previousStatus: string;
    latestStatus: string;
    errorType?: string | null;
    message?: string | null;
    history?: HistoryState[];
    primaryReason: string;
    tier: RiskTier;
  }>;
};

export type RunComparisonResult = {
  type: 'run_comparison';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    baselineRun?: string | null;
    latestRun?: string | null;
    runCount: number;
    totalEvaluated: number;
  };
  summary: {
    newFailures: number;
    recovered: number;
    stillFailing: number;
    changedTests: number;
    baselineFailed: number;
    latestFailed: number;
  };
  tests: Array<{
    rank: number;
    testName: string;
    canonicalName?: string | null;
    suite?: string | null;
    owner?: string | null;
    classification: string;
    passRate: number;
    baselineStatus: string;
    latestStatus: string;
    delta: 'new_failure' | 'recovered' | 'still_failing';
    errorType?: string | null;
    message?: string | null;
    history?: HistoryState[];
    primaryReason: string;
    tier: RiskTier;
  }>;
};

export type FailureTrendResult = {
  type: 'failure_trend';
  title: string;
  subtitle?: string;
  scope: {
    label: string;
    runCount: number;
    totalEvaluated: number;
    baselineRun?: string | null;
    latestRun?: string | null;
  };
  summary: {
    direction: 'INCREASING' | 'DECREASING' | 'STABLE';
    baselineFailed: number;
    latestFailed: number;
    deltaFailed: number;
    peakFailed: number;
    peakRun?: string | null;
    latestNewFailures: number;
    latestRecovered: number;
  };
  runs: Array<{
    rank: number;
    runLabel: string;
    failed: number;
    passed: number;
    skipped: number;
    total: number;
    passRate: number;
    isPeak: boolean;
  }>;
};

export type GenericAnswerResult = {
  type: 'generic_answer';
  title: string;
  body?: string;
};

export type TestFixPlaybookResult = {
  type: 'test_fix_playbook';
  title: string;
  subtitle?: string;
  testName: string;
  hasActiveFailure: boolean;
  diagnosis?: string;
  summary: string;
  errorType?: string | null;
  evidence?: string | null;
  observedRuns?: string[];
  causes?: string[];
  checks?: string[];
  recommendedFix?: string;
  verification?: string[];
  confidence?: string;
  confidenceText?: string;
  scope?: {
    windowRuns?: number;
    failedRuns?: number;
    dominantOccurrences?: number;
  };
};

export type QaLensResult =
  | RiskRankingResult
  | OwnerFailureRateResult
  | OwnerFlakyTestsResult
  | OwnerSuiteComparisonResult
  | OwnerWindowComparisonResult
  | OwnerTestGapResult
  | OwnerSuiteRegressionsResult
  | SharedSuiteFailuresResult
  | SuiteFailureRankingResult
  | RunRetrievalResult
  | ExceptionRetrievalResult
  | StabilityTrendResult
  | RootCauseInsightResult
  | PerformanceTimingResult
  | NewFailuresIntroducedResult
  | RunComparisonResult
  | FailureTrendResult
  | TestFixPlaybookResult
  | GenericAnswerResult;

export type AssistantUiHints = {
  openWorkspace?: boolean;
  activeTab?: 'chat' | 'results';
  selectedEntity?: string;
};
