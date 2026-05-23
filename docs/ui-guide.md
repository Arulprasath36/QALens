# UI Guide

Start the UI:

```bash
qalens serve --db ./qalens.db
```

Open:

```text
http://127.0.0.1:8080
```

The UI is designed around triage flow: understand the latest state, identify related failures, inspect trend direction, and decide what to fix first.

## Project Selector

Use the project selector to scope the dashboard to one project.

Project scoping affects:

- Runs
- Action Brief
- Incidents
- Analysis
- Risk
- Compare
- Chat context
- Reports

If no project is selected, QA Lens shows data across all projects.

## Runs

The Runs page is the operational entry point.

Use it to answer:

- What was the latest run?
- How many tests passed or failed?
- Which tests failed in this run?
- What changed since the previous comparable run?

### Action Brief

Action Brief is the first decision surface in the Runs experience.

It answers:

```text
What changed, where is it going, and what should I fix first?
```

It combines:

- Latest run data.
- Previous comparable run.
- Recent trend window.
- Failure clusters.
- Risk signals.

Action Brief includes:

- Executive summary.
- Trend intelligence.
- Top prioritized actions.
- Evidence links.
- Time-window badges.

Important distinction:

- Regression badges compare the current run against the previous comparable run.
- Trend badges summarize the selected recent run window, such as the last 5 or last 10 runs.

Use **Inspect failures** to move from summary to detailed evidence.

### Run Detail

Run detail shows:

- Test status.
- Suite and owner metadata.
- Failure message.
- Error type.
- Attachments or artifact metadata when available.
- Incidents for the selected run.

Use Run Detail when you need to inspect one run deeply.

## Incidents

The Incidents page groups related failures over time.

Use it to answer:

- Are multiple tests failing for the same reason?
- Is this incident new, active, recurring, or resolved?
- How many failure occurrences happened?
- How many tests are affected?
- In how many runs did this appear?

Key terms:

| Term | Meaning |
|---|---|
| Failures / occurrences | Total failed or broken test executions matching the incident signature. |
| Affected tests | Number of distinct tests impacted by the incident. |
| Runs affected | Number of runs where the incident appeared in the selected window. |
| Active | The incident appears in the latest run. |
| Seen earlier | The incident appeared in earlier runs but is not active in the latest run. |

Use Incidents before debugging individual tests. If one fix clears many failures, it should be prioritized.

## Analysis

The Analysis page explains suite behavior over time.

Use it to answer:

- Is the suite trending up or down?
- Which suites need attention?
- Which owners carry the most failing work?
- Which active failure clusters are hurting us?
- Are tests getting slower?
- Is the health mix stable, flaky, broken, or improving?

### Trend Intelligence

Trend Intelligence summarizes direction:

- Stability
- Failures
- Flakiness
- Incidents

The cards compare selected windows. For example:

- Pass rate moved from one window baseline to the latest selected window.
- Failed test count may be lower or higher than the window start.
- Flakiness counts unstable transitions inside the selected window.

### Pass Rate Journey

The pass-rate chart shows pass percentage across recent runs.

Failure cluster markers show where a cluster appeared. They are event markers, not pass-rate values. A marker above the line means “a failure cluster appeared in this run,” not “the pass rate exceeded the chart.”

Hover behavior should reveal run-level details when supported by the UI build.

### Stability Snapshot

The stability snapshot classifies tests by recent behavior:

- Stable
- Consistent
- Flaky
- Broken

This is a current health mix, not the same metric as “flakiness increased by X” in trend intelligence. A trend card describes change over a selected window; the snapshot describes current classification counts.

### Owner Load

Owner Load shows ownership concentration.

Use it to identify:

- Owners with many assigned tests.
- Owners with high failing work.
- Owners with low pass rate.

Counts represent tests assigned to that owner in the selected scope. Pass rate is the owner’s recent pass percentage.

## Risk

The Risk page predicts which tests deserve attention before the next run.

Use it to answer:

- Which tests are most likely to fail next?
- Which tests are unstable even if not currently failing?
- Why is this test risky?
- Is risk driven by volatility, failure rate, current streak, slowdown, or declining trend?

Risk score is a prioritization signal. It is not a direct probability that the test will fail.

Risk factors include:

- Failure rate.
- Flip score.
- Current fail streak.
- Recent decline.
- Duration volatility.
- Suite concentration.

Use **Explain risk** to open the detailed reasoning for a row.

## Compare

The Compare page helps compare runs, owners, suites, modules, and other dimensions.

Use it to answer:

- What changed between two runs?
- Which owner improved?
- Which suite regressed?
- Which dimension has the highest failure concentration?

Comparison is useful after Action Brief identifies a change but you need broader context.

## Chat

Chat lets you ask natural-language questions about the data.

Examples:

```text
What broke in the latest run?
Which tests are flaky?
Which test should I fix first?
Which owner has the highest failure rate?
In the last 20 runs, which run had the highest and lowest pass percentage?
How can I fix testCreditCardPayment()?
```

Chat has two answer paths:

- Deterministic answers from QA Lens code and SQLite.
- Optional LLM-assisted narration or flexible interpretation.

When a structured result exists, QA Lens opens a Results workspace with tables, evidence, and follow-up questions.

## Settings

Settings shows:

- Runtime paths.
- Database path.
- Config path.
- LLM assistance toggle.
- Local or cloud provider choice.
- Model name and endpoint.
- Security boundary.
- Artifact policy defaults.

Settings are locked by default to prevent accidental edits. Click **Edit**, make changes, then **Save**. Save should remain disabled until a real change exists.

## Reports

Reports are deterministic exports from SQLite.

Use reports for:

- CI artifacts.
- Release triage handoff.
- QA summaries.
- Sharing a snapshot without exposing the live app.

Export from CLI:

```bash
qalens report --db ./qalens.db --out qalens-report.html
```

Export from API:

```text
GET /api/report/export?format=html
```

