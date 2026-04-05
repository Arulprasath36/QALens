# Plugin Guide

QARA is designed for extensibility. This guide explains how to add custom parsers, categorization rules, and output writers without forking the project.

---

## Adding a Custom Parser

### Step 1: Implement `BaseParser`

```python
# my_plugin/parsers/myformat.py
from pathlib import Path
from qara.parsers.base import BaseParser
from qara.models.run import TestRun

class MyFormatParser(BaseParser):
    """Parser for MyFormat test reports."""

    def can_handle(self, report_path: Path) -> bool:
        """Return True if this parser can handle the given report path."""
        return (report_path / "myformat-marker.json").exists()

    def parse(self, report_path: Path) -> TestRun:
        """Parse the report and return a canonical TestRun."""
        ...
```

### Step 2: Register your parser

```python
from qara.parsers.detector import Detector
from my_plugin.parsers.myformat import MyFormatParser

detector = Detector()
detector.register(MyFormatParser())
```

Or, if using the library API:

```python
from qara.api.library import QARAClient
from my_plugin.parsers.myformat import MyFormatParser

client = QARAClient(extra_parsers=[MyFormatParser()])
run = client.extract_report("./reports/myformat-report")
```

### Parser contract

- `can_handle(path)` must be fast (no heavy I/O) — it is called during detection
- `parse(path)` must return a `TestRun`, even if partially populated
- Use `ExtractionWarning` for missing fields, never raise unhandled exceptions
- Do not perform any analysis inside the parser

---

## Adding a Custom Categorization Rule

Categorization rules are simple functions that evaluate a `FailureInfo` in context and return an optional `Insight`.

```python
# my_plugin/rules/my_rule.py
from qara.models.failure import FailureInfo
from qara.models.insight import Insight, InsightCategory
from qara.models.test_case import TestCaseResult

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
from qara.analyzers.categorizer import Categorizer
from my_plugin.rules.my_rule import my_custom_rule

categorizer = Categorizer(extra_rules=[my_custom_rule])
```

Or via the library API:

```python
from qara.api.library import QARAClient
from my_plugin.rules.my_rule import my_custom_rule

client = QARAClient(extra_categorizer_rules=[my_custom_rule])
```

---

## Adding a Custom Output Writer

```python
# my_plugin/outputs/slack_writer.py
from qara.outputs.base import BaseWriter
from qara.models.insight import AnalysisSummary

class SlackWriter(BaseWriter):
    """Writes QARA summaries as Slack block-kit messages."""

    def write(self, summary: AnalysisSummary, destination: str) -> None:
        blocks = self._build_blocks(summary)
        # post to Slack webhook at ``destination``
        ...

    def _build_blocks(self, summary: AnalysisSummary) -> list[dict]:
        ...
```

---

## Future Plugin Discovery (Planned)

In a future release, QARA will support automatic plugin discovery via Python entry points:

```toml
# your plugin's pyproject.toml
[project.entry-points."ari.parsers"]
myformat = "my_plugin.parsers.myformat:MyFormatParser"

[project.entry-points."ari.rules"]
my_rule = "my_plugin.rules.my_rule:my_custom_rule"
```

This will allow `pip install ari-myformat-plugin` to automatically extend ARI.

> **Note**: The entry-point plugin loader is not yet implemented in v1. The programmatic API above is the supported extension mechanism for now.
