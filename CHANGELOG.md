# Changelog

All notable changes to QA Lens will be documented in this file.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/)
and uses semantic versioning once public releases begin.

## Unreleased

### Added

- `qalens` CLI for report detection, extraction, ingestion, analysis, comparison, history, report export, and local serving.
- Local React/FastAPI web UI with Runs, Incidents, Analysis, Risk, Compare, Chat, and Settings views.
- Parsers for Allure, Extent, JUnit, TestNG, Playwright, and Cypress/Mochawesome report outputs.
- SQLite-backed run history for deterministic comparison, trend, risk, and flakiness analysis.
- Shareable deterministic HTML, Markdown, and JSON report exports.
- Optional token auth and GitHub OAuth for shared deployments.
- Optional LLM-assisted chat with local-first defaults and explicit cloud opt-in.

### Changed

- Renamed the public product to QA Lens.
- Renamed the Python package metadata to `qalens-insights`.
- Standardized the CLI command as `qalens`.

### Security

- Raised vulnerable dependency floors for `lxml`, `python-multipart`, and `pytest`.
- Documented local-first security boundaries, report parsing risks, LLM data egress, and network deployment precautions.
