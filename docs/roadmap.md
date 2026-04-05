# QARA Roadmap

> QARA — Quality Analysis & Root Automation  
> This roadmap reflects the current development direction. Priorities may shift based on community feedback.

---

## v1.0 — Foundation (Current)

**Goal**: Reliable, local, explainable insights from Extent and Allure reports.

| Area | Status |
|---|---|
| Canonical Pydantic models | ✅ Done |
| Extent HTML parser | 🔄 In progress |
| Allure HTML/JSON parser | 🔄 In progress |
| Report type detector | 🔄 In progress |
| Failure signature engine | 🔄 In progress |
| Rule-based categorization | 🔄 In progress |
| Deterministic failure clustering | 🔄 In progress |
| Flaky scoring (with history) | 🔄 In progress |
| Summary generators | 🔄 In progress |
| JSON output writer | 🔄 In progress |
| Markdown output writer | 🔄 In progress |
| Console (Rich) output writer | 🔄 In progress |
| Typer CLI | 🔄 In progress |
| Python library API | 🔄 In progress |
| Unit + fixture-based tests | 🔄 In progress |
| Ruff + mypy + pre-commit | ✅ Done |

---

## v1.1 — Polish and Breadth

- pytest-html report parser
- JUnit XML parser (widely supported by CI systems)
- Improved Extent v5 parser coverage
- CI-friendly exit code semantics (fail on N product defects)
- GitHub Actions example workflow
- Shell completion for CLI (Typer built-in)
- `--threshold` flags for CI gate integration
- Machine-readable JSON output for all CLI commands

---

## v1.2 — Historical Intelligence

- File-based run history store (JSON lines)
- New/recurring/resolved failure detection across runs
- Trend charts in Markdown (sparklines)
- Historical flaky leaderboard
- `qara history list` command
- `qara compare <run1> <run2>` command

---

## v2.0 — ML Enrichment (Optional Layer)

- Optional TF-IDF + cosine similarity fuzzy clustering
- Optional sentence-transformer-based semantic grouping (local model, no cloud)
- Ensemble confidence scoring (heuristic + ML combined)
- Anomaly detection on timing patterns
- All ML features opt-in, clearly labeled, and explainable

---

## v2.1 — Richer Outputs

- Standalone HTML insight report (self-contained, no server needed)
- SARIF output (for GitHub Security tab and IDE integrations)
- Slack/Teams webhook notification output (plugin)
- PDF export option

---

## Future Considerations

- Plugin marketplace / entry-point auto-discovery
- TestNG XML parser
- Cypress / Playwright report parsers
- Test execution database (SQLite) for longer history windows
- VS Code extension for inline insight annotations

---

## Non-Goals (Permanent)

- QARA will never be a test reporting framework
- QARA will never replace Extent Reports or Allure
- QARA v1 will never require cloud connectivity
- QARA will never silently discard data without an `ExtractionWarning`

---

## Contributing to the Roadmap

If you have a use case that is not covered here, open a [GitHub Discussion](https://github.com/your-org/qara/discussions) or a feature request issue. We especially welcome:

- Report format parsers for tools used in your organization
- Heuristic categorization signals from your real-world failure patterns
- CI integration patterns and workflows
