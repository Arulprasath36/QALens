# Insight Engine

This document describes how QALens transforms normalized `TestRun` data into actionable insights.

---

## Overview

The insight engine is a sequential analysis pipeline:

```
TestRun
  ↓
SignatureEngine     → normalized signatures, FailureInfo enriched
  ↓
Categorizer         → Insight(category, confidence, explanation, evidence)
  ↓
ClusterEngine       → FailureCluster list
  ↓
FlakyScorer         → flaky_score per test (optional, needs history)
  ↓
Summarizer          → AnalysisSummary
```

---

## Failure Signatures

Defined in `src/qalens/analyzers/signatures.py`.

A **failure signature** is a short stable string that identifies the "shape" of a failure independent of dynamic runtime noise.

### Normalization steps

1. Remove timestamps (ISO 8601, epoch, log-format)
2. Remove UUIDs (`[0-9a-f]{8}-[0-9a-f]{4}-...`)
3. Remove memory addresses (`0x[0-9a-fA-F]+`)
4. Remove session IDs and token strings
5. Remove dynamic numeric IDs (e.g., user IDs, order IDs) where bounded context confirms they are IDs
6. Normalize whitespace (collapse to single spaces, strip leading/trailing)
7. Lowercase the message

### Stack trace normalization

From the full stack trace:
1. Extract the exception type and message (topmost line)
2. Take the top N frames that belong to the application under test (or test code)
3. Strip line numbers from frame references (configurable)
4. Remove generated/anonymous frame patterns

### Signature generation

```
signature = sha256(
    normalized_error_type +
    "|" + normalized_message_prefix +
    "|" + top_3_normalized_frames_joined
)[:16]  # 16 hex chars — compact but collision-resistant
```

This produces a stable deterministic ID usable for grouping.

---

## Categorization Rules

Defined in `src/qalens/analyzers/categorizer.py`.

### Rule evaluation

Rules are evaluated in order. The first rule that achieves confidence ≥ 0.8 is selected. If no rule clears the threshold, multiple rules are combined, and the highest confidence wins (with `unknown` as fallback at < 0.35).

### Category definitions

#### `likely_flaky`

Signals:
- Test passed on a subsequent retry
- Error type is timeout/wait-related (`TimeoutException`, `WaitException`, `StaleElementReferenceException`, etc.)
- Historical alternation (pass/fail/pass/fail pattern)
- Signature is inconsistent across runs (high variance)
- Duration variance is high (≥ 2× for same test)

#### `likely_environment_issue`

Signals:
- `SessionNotCreatedException`, `WebDriverException: session`, `RemoteDriverServerException`
- DNS resolution failure (`UnknownHostException`, `getaddrinfofail`)
- Connection refused / timeout at infrastructure level
- Auth/token failure affecting > 5 unrelated tests
- Test helper setup fails before any app interaction (step ≤ 2 is in an `@Before` / `setup` step)

#### `likely_test_script_issue`

Signals:
- `NoSuchElementException`, `StaleElementReferenceException` on specific locators
- `NullPointerException` in test utility class (stack trace contains test harness package)
- Assertion failure referencing specific hard-coded test data values
- Failure isolated to a single test (unique signature, no cluster peers)
- Locator-pattern words in message: `xpath`, `css`, `id=`, `data-testid`

#### `likely_product_defect`

Signals:
- Same functional assertion fails consistently across ≥ 3 tests
- Stable signature (appears in ≥ 2 consecutive runs)
- Error originates from application code (non-test stack frame is topmost)
- HTTP 4xx/5xx returned by application endpoint
- Business-rule validation error with non-test package in top frame

#### `likely_test_data_issue`

Signals:
- `DuplicateKeyException`, `ConstraintViolationException`
- "User not found", "Entity not found", "Invalid account"
- `DataIntegrityViolationException`
- Test data setup step failed (step name contains `seed`, `create`, `setup`, `init`)
- Parameter value in failure message is a recognizable test entity reference

#### `unknown`

- Default when no rule reaches confidence ≥ 0.35.

---

## Confidence Scoring

Each rule returns a float in [0.0, 1.0]:

| Range | Label |
|---|---|
| 0.8 – 1.0 | High confidence |
| 0.5 – 0.79 | Medium confidence |
| 0.35 – 0.49 | Low confidence |
| < 0.35 | Unknown |

Confidence is computed from:
- Number of matching signals
- Strength of each signal (primary signal vs. corroborating signal)
- Whether the dominant signal is unambiguous (e.g., passed_on_retry is very strong for flaky)

---

## Failure Clusters

Defined in `src/qalens/analyzers/clustering.py`.

### Layer 1 — Deterministic clustering

Group by exact `failure_signature`. All tests sharing a signature form a cluster.

### Layer 2 — Fuzzy clustering (optional)

When enabled, uses TF-IDF vectorization of normalized error messages + cosine similarity to merge nearby clusters.

```python
qalens analyze ./reports/allure --fuzzy-clusters
```

This is disabled by default to keep v1 deterministic and explainable.

---

## Flaky Scoring

Defined in `src/qalens/analyzers/flaky.py`.

The flaky score is a float in [0.0, 1.0]:

```
flaky_score = weighted_average(
    passed_on_retry_rate:       weight=0.40,
    historical_alternation:     weight=0.30,
    timing_variance:            weight=0.15,
    signature_variance:         weight=0.15,
)
```

- `passed_on_retry_rate`: proportion of runs where this test recovered on retry
- `historical_alternation`: rate of pass/fail switching across recent runs (window=10)
- `timing_variance`: coefficient of variation of test duration
- `signature_variance`: number of distinct signatures seen for this test historically

---

## Summary Generation

Defined in `src/qalens/analyzers/summarizer.py`.

Three summary types:

| Summary | Audience | Key content |
|---|---|---|
| Executive | Management | Pass rate, top clusters, risk signal |
| Engineering | Developers | Product defects, cluster details, stack frames |
| QA Lead | QA lead | All categories, flaky list, recommended actions |
