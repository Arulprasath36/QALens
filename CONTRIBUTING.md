# Contributing to QALens

Thank you for your interest in contributing to QALens — Quality Assurance + Lens!

QALens is an open-source project welcoming contributions from QA engineers, platform engineers, developers, and technical writers.

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

---

## Ways to Contribute

- **Report a bug** — open a GitHub issue with steps to reproduce
- **Suggest an enhancement** — open a GitHub issue describing the feature and its motivation
- **Submit a pull request** — bug fixes, new parsers, new heuristics, docs improvements
- **Improve documentation** — architecture docs, usage examples, tutorials
- **Share sample reports** — sanitized Extent or Allure report snapshots for test fixtures

---

## Development Setup

### Prerequisites

- Python 3.10 or higher
- `git`

### Clone and install

```bash
git clone https://github.com/your-org/qalens.git
cd qalens
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

### Verify your setup

```bash
pytest
ruff check src/ tests/
mypy src/
```

---

## Project Structure

```
src/qalens/
├── parsers/      # Report-specific HTML/JSON extractors
├── models/       # Canonical Pydantic data models
├── analyzers/    # Heuristic analysis and categorization
├── outputs/      # JSON, Markdown, console output writers
├── utils/        # Shared utilities (text, hashing, FS)
└── api/          # Public Python library surface

tests/
├── fixtures/     # Sample report HTML for parser tests
└── test_*.py     # Unit and integration tests
```

---

## Development Workflow

### Branching

- `main` — protected, always stable
- Feature branches: `feature/<short-description>`
- Bug-fix branches: `fix/<short-description>`
- Doc branches: `docs/<short-description>`

### Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add TestNG XML parser
fix: handle missing duration field in Allure report
docs: expand flaky detection heuristics
test: add fixture for Extent v5 multi-suite report
refactor: extract signature normalization into standalone fn
```

### Pull Requests

Before opening a PR:

1. Run the full test suite: `pytest --cov=src/qalens`
2. Run the linter: `ruff check src/ tests/`
3. Run type checks: `mypy src/`
4. Ensure pre-commit passes: `pre-commit run --all-files`
5. Add or update tests for your change
6. Update docstrings and docs if relevant

PR titles should follow the same Conventional Commits format.

---

## Adding a New Report Parser

1. Create `src/qalens/parsers/<format>.py` implementing `BaseParser` from `src/qalens/parsers/base.py`.
2. Register the parser in `src/qalens/parsers/detector.py`.
3. Add fixture HTML files under `tests/fixtures/<format>_sample/`.
4. Add tests in `tests/test_<format>_parser.py`.
5. Document the format signatures in `docs/parser-strategy.md`.

See [docs/parser-strategy.md](docs/parser-strategy.md) for the parser contract.

---

## Adding a New Analysis Rule

1. Identify the relevant module: `src/qalens/analyzers/categorizer.py` or `src/qalens/analyzers/signatures.py`.
2. Add the rule as a named function with a docstring explaining the heuristic.
3. Each rule must return a result with `category`, `confidence`, `explanation`, and `evidence`.
4. Add tests in `tests/test_categorizer.py` with realistic failure scenarios.

---

## Code Style

- **Formatting**: `ruff format` (Black-compatible)
- **Linting**: `ruff check`
- **Typing**: All public functions and methods must be fully typed
- **Docstrings**: All public modules, classes, and functions must have docstrings
- **Line length**: 100 characters

---

## Testing Expectations

- All new code must have tests.
- Parser tests must use fixture HTML files, not mocking of the HTML content.
- Analysis tests must use realistic (even if synthetic) failure inputs.
- Tests must pass in Python 3.10, 3.11, and 3.12.

---

## Questions?

Open a [GitHub Discussion](https://github.com/your-org/qalens/discussions) or an Issue.

Thank you for helping make QALens better!
