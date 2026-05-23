# QA Lens Documentation

QA Lens turns existing test automation reports into local, explainable triage intelligence. It reads reports from tools such as Allure, Extent, JUnit, TestNG, Playwright, and Cypress/Mocha, stores normalized run history in SQLite, and helps teams answer operational QA questions:

- What failed in the latest run?
- Which failures share the same root cause?
- Which tests are flaky or high risk?
- Which suites, owners, and modules are degrading?
- What should the team fix first?
- Is the test system getting better or worse?

This documentation is intended for the product-site **Docs** menu. Keep the repository `README.md` as the quick-start landing page, and use these pages for detailed feature and operations guidance.

## Documentation Map

| Page | Purpose |
|---|---|
| [Getting Started](getting-started.md) | First successful run from a clean machine. |
| [Installation](installation.md) | PyPI install, source install, development setup, and requirements. |
| [Ingesting Reports](ingesting-reports.md) | Supported formats, ingestion commands, artifact policy, projects, owners, and database behavior. |
| [CLI Reference](cli-reference.md) | Practical command reference for `qalens`. |
| [UI Guide](ui-guide.md) | Runs, Action Brief, Incidents, Analysis, Risk, Compare, Chat, Reports, and Settings. |
| [Chat and LLMs](chat-and-llm.md) | Deterministic answers, local LLMs, cloud providers, and security boundaries. |
| [API Reference](api-reference.md) | Interactive API docs location and endpoint groups. |
| [Security and Deployment](security-and-deployment.md) | Auth, local-first defaults, LLM opt-in, report parsing, and deployment notes. |
| [Troubleshooting](troubleshooting.md) | Common setup, ingestion, UI, LLM, and API issues. |
| [Architecture](architecture.md) | Internal pipeline and module map. |

## How QA Lens Works

QA Lens has four main layers:

1. **Ingestion**
   - Detects the report format.
   - Parses the source report.
   - Normalizes results into QA Lens models.
   - Stores runs, tests, failures, and artifact metadata in SQLite.

2. **Deterministic analysis**
   - Computes failure signatures.
   - Groups related incidents.
   - Calculates flakiness, risk, trend direction, and owner/suite health.
   - Produces Action Brief and decision summaries without requiring an LLM.

3. **Optional LLM assistance**
   - Local or cloud LLMs can help with flexible narration, intent parsing, and follow-up questions.
   - Deterministic answers remain available even when LLM assistance is disabled.
   - Cloud providers are opt-in because report context may leave the local machine.

4. **UI and API**
   - The web UI is served by the Python package.
   - The API is FastAPI and exposes Swagger at `/api/docs`.
   - The CLI and UI use the same database and analysis model.

## Recommended Reading Path

New users:

1. [Getting Started](getting-started.md)
2. [Ingesting Reports](ingesting-reports.md)
3. [UI Guide](ui-guide.md)
4. [Chat and LLMs](chat-and-llm.md)

Developers and maintainers:

1. [Architecture](architecture.md)
2. [API Reference](api-reference.md)
3. [Security and Deployment](security-and-deployment.md)
4. [CLI Reference](cli-reference.md)
