"""Canonical enums and data models for the QARA answer-planning pipeline.

Contains the core type definitions that other LLM modules depend on:

* :class:`RankingMetric` — which metric to rank tests by.
* :class:`AnswerIntent` — what the user is asking about.
* :class:`AnswerType` — what shape the answer should take.
* :class:`AnswerScope` — hard boundary defining which tests/runs the LLM can discuss.
* :class:`PayloadSection` / :class:`StructuredPayload` — backend-computed answer structure.

These are extracted from ``answer_plan.py`` to reduce coupling: downstream
modules can import lightweight type definitions without pulling in the full
planning and detection machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RankingMetric(str, Enum):
    """Which metric the user wants to rank tests by."""

    FLAKINESS = "flakiness"
    """flip_score — pass↔fail transition count (default)."""

    RISK = "risk"
    """Predicted failure risk / risk tier from the predictor."""

    FAILURE_BURDEN = "failure_burden"
    """Raw failure count across runs."""

    DURATION = "duration"
    """Average or spike execution time."""


class AnswerIntent(str, Enum):
    """Seven intent types that drive distinct answer shapes."""

    RANKING_LIST = "ranking_list"
    """User wants a sorted/ranked list — top/most/worst/flakiest/riskiest."""

    DIAGNOSTIC_ROOT_CAUSE = "diagnostic_root_cause"
    """User wants to know *why* something failed — why/cause/explain."""

    COMPARISON_CHANGE = "comparison_change"
    """User compares two states — vs/compare/changed/difference."""

    DRILL_DOWN_DETAIL = "drill_down_detail"
    """User wants exact records — specific run, timeline, history."""

    RECOMMENDATION_ACTION = "recommendation_action"
    """User wants actionable advice — what should I, fix first, prioritize."""

    NEW_REGRESSIONS = "new_regressions"
    """User wants specifically the tests that newly failed (passed before, failed now)."""

    SUMMARY_OVERVIEW = "summary_overview"
    """User wants a high-level snapshot — summarize, overview, health."""


class AnswerType(str, Enum):
    """Canonical output shape for an answer.

    While :class:`AnswerIntent` captures *what the user is asking about*,
    ``AnswerType`` captures *what shape the answer should take*.  Each
    answer type maps to a deterministic output structure so the backend
    can pre-compute sections, groupings, and counts.

    The mapping is **many-to-one** from intent → answer type in some cases
    (e.g. ``DIAGNOSTIC_ROOT_CAUSE`` can resolve to ``FLAKINESS_BINARY``,
    ``FLAKINESS_RANKING``, or ``ROOT_CAUSE`` depending on the question).
    """

    REGRESSION_DIFF = "regression_diff"
    """Newly failing / recovered / consistently failing sections."""

    FLAKINESS_BINARY = "flakiness_binary"
    """Yes/no verdict + per-test flip count bullets (pre-built)."""

    FLAKINESS_RANKING = "flakiness_ranking"
    """Numbered list of tests ranked by flakiness percentage."""

    RISK_RANKING = "risk_ranking"
    """Numbered list of tests ranked by predicted failure risk."""

    TREND = "trend"
    """Per-run pass-rate trend with direction and confidence."""

    ROOT_CAUSE = "root_cause"
    """Evidence-based diagnostic with confidence level."""

    DETAIL = "detail"
    """Single-fact lookup or exact record retrieval."""

    SUMMARY = "summary"
    """Project health overview / snapshot."""

    RECOMMENDATION = "recommendation"
    """Prioritised actionable advice."""


# ---------------------------------------------------------------------------
# AnswerScope — strict test-set boundary for the LLM
# ---------------------------------------------------------------------------


@dataclass
class DefaultScopeInfo:
    """Records that QARA applied a default data scope because the question was underspecified.

    When the user's question specifies no run, time window, or dataset, QARA
    applies a sensible default (last N runs) and attaches this object to the
    :class:`~qara.llm.answer_plan.AnswerPlan`.  The prompt builder reads it to
    inject scope-disclosure instructions so the LLM always states what data
    was used and offers refinement options.

    Attributes:
        window_runs:  Number of most-recent runs used as the default scope.
        description:  Human-readable scope label (e.g. ``"Last 10 runs"``).
    """

    window_runs: int = 10
    description: str = "Last 10 runs"


@dataclass
class AnswerScope:
    """Defines the exact set of tests/runs the LLM answer must cover.

    Enforces a hard boundary: the LLM may only discuss items within this
    scope.  The backend computes the scope and injects it as a
    ``=== SCOPE: {label} ===`` block in the context.

    Attributes:
        tests:  Display names of scoped tests.
        runs:   Run labels (e.g. ``"Run #53"``).
        groups: Root-cause groups (when applicable).
        total:  Total number of scoped items.
        label:  Human-readable scope label (e.g. ``"NEWLY FAILING TESTS"``).
    """

    tests: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    total: int = 0
    label: str = ""

    def format_block(self) -> str:
        """Return the formatted scope block for prompt injection."""
        lines = [f"=== SCOPE: {self.label} ==="]
        lines.append(f"Total scoped tests: {self.total}")
        lines.append("")
        for t in self.tests:
            lines.append(f"- {t}")
        if self.runs:
            lines.append("")
            lines.append("Runs: " + ", ".join(self.runs))
        lines.append("")
        lines.append("Use ONLY these tests in your answer. Do not mention tests outside this list.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# PayloadSection / StructuredPayload — backend-computed answer structure
# ---------------------------------------------------------------------------


@dataclass
class PayloadSection:
    """A single section in a backend-structured answer payload.

    Attributes:
        heading:     Section heading (e.g. ``"Newly Failing"``).
        items:       Formatted bullet items.
        empty:       When True, this section has no items and should be suppressed.
        format_hint: Optional rendering instruction for the LLM (e.g. ``"group
                     items by root-cause heading"``).  When present the prompt
                     injects this hint instead of the verbose static addenda.
    """

    heading: str
    items: list[str] = field(default_factory=list)
    empty: bool = False
    format_hint: str = ""


@dataclass
class StructuredPayload:
    """Complete backend-computed answer structure.

    When populated, the LLM narrates this structure rather than computing
    it from raw context.  The ``verdict`` line is always emitted first.

    Attributes:
        sections: Ordered list of sections.
        verdict:  Optional top-line verdict (e.g. ``"Yes — 6 of 8..."``).
    """

    sections: list[PayloadSection] = field(default_factory=list)
    verdict: str | None = None

    def format_block(self) -> str:
        """Return the fully formatted payload for prompt injection."""
        parts: list[str] = []
        if self.verdict:
            parts.append(self.verdict)
        for sec in self.sections:
            if sec.empty:
                continue
            parts.append("")
            parts.append(f"**{sec.heading}**")
            if sec.format_hint:
                parts.append(f"[Render: {sec.format_hint}]")
            parts.extend(sec.items)
        return "\n".join(parts)
