# Plugin Guide

QaLens is designed for extensibility. This guide explains how to add custom parsers, categorization rules, and output writers without forking the project.

---

## Adding a Custom Parser

### Step 1: Implement `BaseParser`

```python
# my_plugin/parsers/myformat.py
from pathlib import Path
from qalens.parsers.base import BaseParser, DetectionResult
from qalens.models.run import TestRun

class MyFormatParser(BaseParser):
    """Parser for MyFormat test reports."""

    parser_key = "myformat"           # required: short unique id, lowercase
    parser_name = "MyFormat Reports"  # required: human-readable display name

    def can_parse(self, report_path: Path) -> DetectionResult:
        """Return a DetectionResult indicating how confident we are this is a MyFormat report."""
        marker = report_path / "myformat-marker.json"
        if marker.exists():
            return DetectionResult(confidence=0.9, evidence=["myformat-marker.json found"])
        return DetectionResult(confidence=0.0, evidence=[])

    def parse(self, report_path: Path) -> TestRun:
        """Parse the report and return a canonical TestRun."""
        ...
```

`DetectionResult.confidence` is a float in `[0, 1]`:
- `≥ 0.8` — high confidence (multiple strong signals)
- `0.5 – 0.79` — medium confidence (partial match)
- `< 0.5` — not matched (parser will be skipped)

### Step 2: Register your parser

```python
from qalens.parsers.detector import Detector
from my_plugin.parsers.myformat import MyFormatParser

detector = Detector()
detector.register(MyFormatParser())
```

Or, if using the library API:

```python
from qalens.api.library import QaLensClient
from my_plugin.parsers.myformat import MyFormatParser

client = QaLensClient(extra_parsers=[MyFormatParser()])
run = client.extract_report("./reports/myformat-report")
```

### Parser contract

- `parser_key` and `parser_name` must be set as class attributes
- `can_parse(path)` must be fast (no heavy I/O) — it is called during detection
- `parse(path)` must return a `TestRun`, even if partially populated
- Use `self._warn(...)` to record `ExtractionWarning` for missing fields — never raise for optional data
- Do not perform any analysis inside the parser

---

## Adding a Custom Categorization Rule

Categorization rules are simple functions that evaluate a `FailureInfo` in context and return an optional `Insight`.

```python
# my_plugin/rules/my_rule.py
from qalens.models.failure import FailureInfo
from qalens.models.insight import Insight, InsightCategory
from qalens.models.test_case import TestCaseResult

def my_custom_rule(
    test: TestCaseResult,
    failure: FailureInfo,
) -> Insight | None:
    """Detect failures caused by our custom infra setup step."""
    if failure.message and "MyInfraSetup.initialize" in (failure.stack_trace or ""):
        return Insight(
            category=InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
            confidence=0.85,
            explanation="Failure occurred inside MyInfraSetup.initialize, indicating custom infra setup failure.",
            evidence=["stack_trace contains MyInfraSetup.initialize"],
            related_tests=[test.test_id],
        )
    return None
```

### Register the rule

```python
from qalens.analyzers.categorizer import Categorizer
from my_plugin.rules.my_rule import my_custom_rule

categorizer = Categorizer(extra_rules=[my_custom_rule])
```

Or via the library API:

```python
from qalens.api.library import QaLensClient
from my_plugin.rules.my_rule import my_custom_rule

client = QaLensClient(extra_categorizer_rules=[my_custom_rule])
```

---

## Adding a Custom Output Writer

> **Note:** A formal `BaseWriter` interface is not yet implemented. Custom output
> is currently achieved by consuming `AnalysisSummary` directly from the library API:

```python
from qalens.api.library import QaLensClient

client = QaLensClient()
run = client.extract_report("./reports/myformat-report")
analysis = client.analyze_report(run)
summary = analysis  # AnalysisSummary — consume however you need

# Example: post to a Slack webhook
import httpx
httpx.post("https://hooks.slack.com/...", json={"text": str(summary)})
```

A pluggable `BaseWriter` interface is planned for a future release.

---

## Future Plugin Discovery (Planned)

In a future release, QaLens will support automatic plugin discovery via Python entry points:

```toml
# your plugin's pyproject.toml
[project.entry-points."qalens.parsers"]
myformat = "my_plugin.parsers.myformat:MyFormatParser"

[project.entry-points."qalens.rules"]
my_rule = "my_plugin.rules.my_rule:my_custom_rule"
```

This will allow `pip install qalens-myformat-plugin` to automatically extend QaLens.

> **Note**: The entry-point plugin loader is not yet implemented in v1. The programmatic API above is the supported extension mechanism for now.
