"""QARA canonical data models.

All parsers normalize their extracted data into these Pydantic models.
Analyzers consume these models exclusively — they never touch raw HTML or JSON.
"""

from qara.models.attachment import Attachment
from qara.models.failure import FailureInfo
from qara.models.insight import AnalysisSummary, FailureCluster, Insight, InsightCategory
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import StepResult, TestCaseResult, TestStatus
from qara.models.warnings import ExtractionWarning, WarningSeverity

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
