"""QA Lens canonical data models.

All parsers normalize their extracted data into these Pydantic models.
Analyzers consume these models exclusively — they never touch raw HTML or JSON.
"""

from qalens.models.attachment import Attachment
from qalens.models.failure import FailureInfo
from qalens.models.insight import AnalysisSummary, FailureCluster, Insight, InsightCategory
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import StepResult, TestCaseResult, TestStatus
from qalens.models.warnings import ExtractionWarning, WarningSeverity

__all__ = [
    "Attachment",
    "FailureInfo",
    "Insight",
    "InsightCategory",
    "FailureCluster",
    "AnalysisSummary",
    "RunMetadata",
    "TestRun",
    "StepResult",
    "TestCaseResult",
    "TestStatus",
    "ExtractionWarning",
    "WarningSeverity",
]
