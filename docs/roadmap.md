# QALens Roadmap

> QALens — Quality Assurance + Lens  
> This roadmap reflects the current development direction. Priorities may shift based on community feedback.

---

## v1.0 — Foundation

**Goal**: Reliable, local, explainable insights from Extent and Allure reports.

| Area | Status |
|---|---|
| Canonical Pydantic models | ✅ Done |
| Extent HTML parser | ✅ Done |
| Allure HTML/JSON parser | ✅ Done |
| Report type detector | ✅ Done |
| Failure signature engine | ✅ Done |
| Rule-based categorization | ✅ Done |
| Deterministic failure clustering | ✅ Done |
| Flaky scoring with run history | ✅ Done |
| Summary generators | ✅ Done |
| JSON output | ✅ Done |
| Markdown output | ✅ Done |
| Console/Rich output | ✅ Done |
| Typer CLI | ✅ Done |
| Python library API | ✅ Done |
| SQLite run history store | ✅ Done |
| Web UI/API server | ✅ Done |
| Run comparison engine | ✅ Done |
| LLM chat/ask integration | ✅ Done |
| Security hardening baseline | ✅ Done |
| Unit + fixture-based tests | ✅ Done |
| Ruff + mypy + pre-commit | ✅ Done |

---

## v1.1 — Current Polish

| Area | Status |
|---|---|
| CI-friendly exit code semantics | ✅ Done |
| GitHub Actions example workflow | ✅ Done |
| Machine-readable analysis output | ✅ Done |
| Demo dataset for GitHub users | ✅ Done |
| Deterministic `qalens ask` answers for factual aggregate questions | ✅ Done |
| Frontend XSS sanitizer regression coverage | ✅ Done |
| Dependency/security CI checks | ✅ Done |
| Improved Extent v5 parser coverage | 🔄 Ongoing |
| Shell completion documentation | ⏳ Planned |
| Broader CLI JSON output coverage | ⏳ Planned |

---

## v1.2 — Historical Intelligence

| Area | Status |
|---|---|
| SQLite-backed run history | ✅ Done |
| New/recurring/recovered failure detection | ✅ Done |
| Historical flaky leaderboard | ✅ Done |
| Run comparison API and UI | ✅ Done |
| Trend analysis facts | ✅ Done |
| Trend charts in Markdown | ⏳ Planned |
| `qalens history list` command | ⏳ Planned |
| `qalens compare <run1> <run2>` command | ⏳ Planned |

---

## v1.3 — Parser Breadth

- pytest-html report parser
- JUnit XML parser
- TestNG XML parser
- Cypress / Playwright report parsers
- More real-world Extent and Allure fixture variants

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
- VS Code extension for inline insight annotations
- Slack/Teams notification plugins
- SARIF export

---

## Non-Goals (Permanent)

- QALens will never be a test reporting framework
- QALens will never replace Extent Reports or Allure
- QALens v1 will never require cloud connectivity
- QALens will never silently discard data without an `ExtractionWarning`

---

## Contributing to the Roadmap

If you have a use case that is not covered here, open a [GitHub Discussion](https://github.com/Arulprasath36/QALens/discussions) or a feature request issue. We especially welcome:

- Report format parsers for tools used in your organization
- Heuristic categorization signals from your real-world failure patterns
- CI integration patterns and workflows
