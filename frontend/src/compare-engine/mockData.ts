import type { Owner, Run, Suite, ComparisonResult } from './types';

// ── Owners ────────────────────────────────────────────────────

export const MOCK_OWNERS: Owner[] = [
  { id: 'fatima',  name: 'Fatima Al-Rashid', testCount: 24, flakyCount: 3, failureRate: 0.33 },
  { id: 'arjun',   name: 'Arjun Mehta',      testCount: 18, flakyCount: 1, failureRate: 0.12 },
  { id: 'sofia',   name: 'Sofia Nguyen',      testCount: 31, flakyCount: 5, failureRate: 0.19 },
  { id: 'lucas',   name: 'Lucas Ferreira',    testCount: 15, flakyCount: 0, failureRate: 0.07 },
  { id: 'priya',   name: 'Priya Sharma',      testCount: 22, flakyCount: 2, failureRate: 0.23 },
  { id: 'wei',     name: 'Wei Zhang',         testCount: 19, flakyCount: 4, failureRate: 0.42 },
  { id: 'omar',    name: 'Omar Khalid',       testCount: 11, flakyCount: 1, failureRate: 0.09 },
  { id: 'elena',   name: 'Elena Vasquez',     testCount: 28, flakyCount: 2, failureRate: 0.14 },
];

// ── Runs ──────────────────────────────────────────────────────

export const MOCK_RUNS: Run[] = [
  { id: 'run-53', label: 'Run #53', sequence: 53, startedAt: '2025-02-21T14:22:00Z', passRate: 0.61, branch: 'main',    totalTests: 128, failedCount: 50 },
  { id: 'run-52', label: 'Run #52', sequence: 52, startedAt: '2025-02-20T11:15:00Z', passRate: 0.79, branch: 'main',    totalTests: 128, failedCount: 27 },
  { id: 'run-51', label: 'Run #51', sequence: 51, startedAt: '2025-02-19T09:44:00Z', passRate: 0.84, branch: 'develop', totalTests: 125, failedCount: 20 },
  { id: 'run-50', label: 'Run #50', sequence: 50, startedAt: '2025-02-18T16:30:00Z', passRate: 0.91, branch: 'main',    totalTests: 122, failedCount: 11 },
  { id: 'run-49', label: 'Run #49', sequence: 49, startedAt: '2025-02-17T10:05:00Z', passRate: 0.88, branch: 'develop', totalTests: 120, failedCount: 14 },
  { id: 'run-48', label: 'Run #48', sequence: 48, startedAt: '2025-02-16T08:50:00Z', passRate: 0.93, branch: 'main',    totalTests: 118, failedCount:  8 },
  { id: 'run-47', label: 'Run #47', sequence: 47, startedAt: '2025-02-15T13:22:00Z', passRate: 0.86, branch: 'main',    totalTests: 117, failedCount: 16 },
  { id: 'run-46', label: 'Run #46', sequence: 46, startedAt: '2025-02-14T15:11:00Z', passRate: 0.90, branch: 'develop', totalTests: 115, failedCount: 11 },
];

// ── Suites ────────────────────────────────────────────────────

export const MOCK_SUITES: Suite[] = [
  { id: 'auth',     name: 'Authentication',    testCount: 22, failureRate: 0.41, flakyCount: 4 },
  { id: 'cart',     name: 'Shopping Cart',     testCount: 18, failureRate: 0.17, flakyCount: 2 },
  { id: 'payments', name: 'Payments',          testCount: 15, failureRate: 0.53, flakyCount: 1 },
  { id: 'orders',   name: 'Order Management',  testCount: 20, failureRate: 0.30, flakyCount: 3 },
  { id: 'reports',  name: 'Reports & Exports', testCount: 12, failureRate: 0.08, flakyCount: 0 },
  { id: 'catalog',  name: 'Product Catalog',   testCount: 25, failureRate: 0.04, flakyCount: 1 },
  { id: 'search',   name: 'Search & Filter',   testCount: 16, failureRate: 0.12, flakyCount: 2 },
];

// ── Comparison results ─────────────────────────────────────────

export const MOCK_COMPARISON_FATIMA_VS_ARJUN: ComparisonResult = {
  timeLabel: 'Last 5 runs (Feb 17 → Feb 21)',
  metricsA: {
    label: 'Fatima Al-Rashid',
    failureRate: 0.33,
    flakyCount: 3,
    newFailures: 5,
    fixedTests: 1,
    totalTests: 24,
    passCount: 16,
    failCount: 8,
  },
  metricsB: {
    label: 'Arjun Mehta',
    failureRate: 0.12,
    flakyCount: 1,
    newFailures: 1,
    fixedTests: 3,
    totalTests: 18,
    passCount: 16,
    failCount: 2,
  },
  rows: [
    { testName: 'testTwoFactorAuthFlow',      displayName: 'testTwoFactorAuthFlow()',      suite: 'Authentication',   owner: 'Fatima Al-Rashid', statusA: 'failed',  statusB: 'passed', delta: 'improved'  },
    { testName: 'testValidUserLogin',          displayName: 'testValidUserLogin()',          suite: 'Authentication',   owner: 'Fatima Al-Rashid', statusA: 'failed',  statusB: 'passed', delta: 'improved'  },
    { testName: 'testAddItemToCart',           displayName: 'testAddItemToCart()',           suite: 'Shopping Cart',    owner: 'Arjun Mehta',      statusA: 'passed',  statusB: 'failed', delta: 'regressed' },
    { testName: 'testPlaceOrderConfirmation',  displayName: 'testPlaceOrderConfirmation()',  suite: 'Order Management', owner: 'Fatima Al-Rashid', statusA: 'failed',  statusB: 'failed', delta: 'stable'    },
    { testName: 'testCreditCardPayment',       displayName: 'testCreditCardPayment()',       suite: 'Payments',         owner: 'Fatima Al-Rashid', statusA: 'failed',  statusB: 'passed', delta: 'improved'  },
    { testName: 'testPayPalRedirect',          displayName: 'testPayPalRedirect()',          suite: 'Payments',         owner: 'Arjun Mehta',      statusA: 'passed',  statusB: 'passed', delta: 'stable'    },
    { testName: 'testCreateOrder',             displayName: 'testCreateOrder()',             suite: 'Order Management', owner: 'Fatima Al-Rashid', statusA: 'flaky',   statusB: 'passed', delta: 'improved'  },
    { testName: 'testOrderHistoryList',        displayName: 'testOrderHistoryList()',        suite: 'Order Management', owner: 'Arjun Mehta',      statusA: 'passed',  statusB: 'failed', delta: 'regressed' },
    { testName: 'testSearchByKeyword',         displayName: 'testSearchByKeyword()',         suite: 'Search & Filter',  owner: 'Arjun Mehta',      statusA: 'passed',  statusB: 'passed', delta: 'stable'    },
    { testName: 'testExportMonthlyReport',     displayName: 'testExportMonthlyReport()',     suite: 'Reports & Exports',owner: 'Fatima Al-Rashid', statusA: 'skipped', statusB: 'passed', delta: 'fixed'     },
  ],
};

export const MOCK_COMPARISON_RUN53_VS_RUN52: ComparisonResult = {
  timeLabel: 'Run #53 vs Run #52',
  metricsA: {
    label: 'Run #53  ·  Feb 21',
    failureRate: 0.39,
    flakyCount: 6,
    newFailures: 23,
    fixedTests: 0,
    totalTests: 128,
    passCount: 78,
    failCount: 50,
  },
  metricsB: {
    label: 'Run #52  ·  Feb 20',
    failureRate: 0.21,
    flakyCount: 3,
    newFailures: 4,
    fixedTests: 7,
    totalTests: 128,
    passCount: 101,
    failCount: 27,
  },
  rows: [
    { testName: 'testTwoFactorAuthFlow',  displayName: 'testTwoFactorAuthFlow()',  suite: 'Authentication',   statusA: 'failed',  statusB: 'passed', delta: 'regressed', errorMessage: "Cannot read properties of undefined (reading 'otp')" },
    { testName: 'testValidUserLogin',      displayName: 'testValidUserLogin()',      suite: 'Authentication',   statusA: 'failed',  statusB: 'passed', delta: 'regressed', errorMessage: 'No connections available in pool' },
    { testName: 'testAddItemToCart',       displayName: 'testAddItemToCart()',       suite: 'Shopping Cart',    statusA: 'failed',  statusB: 'passed', delta: 'regressed', errorMessage: 'No connections available in pool' },
    { testName: 'testCreditCardPayment',   displayName: 'testCreditCardPayment()',   suite: 'Payments',         statusA: 'failed',  statusB: 'failed', delta: 'stable'    },
    { testName: 'testPayPalRedirect',      displayName: 'testPayPalRedirect()',      suite: 'Payments',         statusA: 'failed',  statusB: 'passed', delta: 'regressed' },
    { testName: 'testSearchByKeyword',     displayName: 'testSearchByKeyword()',     suite: 'Search & Filter',  statusA: 'passed',  statusB: 'passed', delta: 'stable'    },
    { testName: 'testExportReport',        displayName: 'testExportReport()',        suite: 'Reports & Exports',statusA: 'passed',  statusB: 'failed', delta: 'improved'  },
    { testName: 'testProductImageGallery', displayName: 'testProductImageGallery()', suite: 'Product Catalog',  statusA: 'passed',  statusB: 'passed', delta: 'stable'    },
  ],
};
