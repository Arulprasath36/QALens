"""LLM Ask route handler for the QA Lens FastAPI server.

Factory function :func:`make_llm_router` registers the ``/api/ask`` endpoint.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from qalens.server.models import AskRequest, AskResponse


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (in-memory, no external dependency)
# ---------------------------------------------------------------------------

class _SlidingWindowLimiter:
    """Thread-safe per-key sliding-window rate limiter."""

    def __init__(self, max_calls: int, window_seconds: int) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._lock = threading.Lock()
        self._log: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        """Raise HTTP 429 if *key* has exceeded the allowed call rate."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            calls = self._log[key]
            # Drop timestamps outside the current window
            while calls and calls[0] < cutoff:
                calls.pop(0)
            if len(calls) >= self._max:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded: max {self._max} requests "
                        f"per {self._window}s. Please wait before retrying."
                    ),
                    headers={"Retry-After": str(self._window)},
                )
            calls.append(now)


# One limiter instance shared across all requests: 10 calls / 60 s per IP.
_ask_limiter = _SlidingWindowLimiter(max_calls=10, window_seconds=60)


def _ask_rate_limit(request: Request) -> None:
    """FastAPI dependency — enforces the /api/ask rate limit."""
    key = request.client.host if request.client else "unknown"
    _ask_limiter.check(key)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


# ---------------------------------------------------------------------------
# Off-topic / harmful query guard
# ---------------------------------------------------------------------------

_DESTRUCTIVE_VERBS = re.compile(
    r"\b(delete|drop|truncat|wipe|eras|remov|clear|delet|destroy|purge|reset)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_OBJECTS = re.compile(
    r"\b(database|data|record|table|test data|row|entry|entries|schema)\b",
    re.IGNORECASE,
)
_MUTATION_PATTERNS = re.compile(
    r"\b(insert|update|modif|edit|creat|add|write|overwrite|alter|patch)\b.{0,40}"
    r"\b(database|data|record|table|test)\b",
    re.IGNORECASE,
)
_INJECTION_PATTERNS = re.compile(
    r"ignore (previous|prior|all|your)|disregard (your|the|all)|"
    r"forget (your|the|all|previous)|you are now|pretend (you are|to be)|"
    r"act as (a |an )?(different|new|unrestricted|unfiltered|jailbreak|dan\b)|"
    r"new persona|override (your|the) (instructions?|prompt|system)|"
    r"bypass (your|the) (filter|guard|restriction|safeguard)|"
    r"do anything now|jailbreak|prompt injection",
    re.IGNORECASE,
)
_UNRELATED_PATTERNS = re.compile(
    r"\b(write (me )?(a |an )?(poem|story|essay|email|letter|song|joke|code(?! review)|script)|"
    r"translate (this|to|into)|what is the weather|stock price|recipe for|"
    r"help me (with )?(homework|dating|relationships?)|"
    r"political (opinion|view)|who (won|is winning) the)\b",
    re.IGNORECASE,
)

_REFUSAL_MESSAGE = (
    "I'm a read-only test analytics assistant — I can only analyse data that's "
    "already in your test reports.\n\n"
    "I can help with things like:\n"
    "- Which tests failed and why\n"
    "- Flaky or high-risk tests\n"
    "- Failure trends across runs\n"
    "- Owner-level quality breakdowns\n\n"
    "I can't delete, modify, create, or export any data."
)


def _is_off_topic_or_harmful(question: str) -> bool:
    """Return True if the question is outside QA Lens's scope or requests harmful actions."""
    # Destructive data operations
    if _DESTRUCTIVE_VERBS.search(question) and _DESTRUCTIVE_OBJECTS.search(question):
        return True
    # Write/mutation attempts
    if _MUTATION_PATTERNS.search(question):
        return True
    # Prompt injection
    if _INJECTION_PATTERNS.search(question):
        return True
    # Clearly unrelated topics
    if _UNRELATED_PATTERNS.search(question):
        return True
    return False


def _deterministic_context_answer(
    *,
    question: str,
    context: str,
    mode: str,
    structured_facts: str | None,
) -> str:
    """Return a compact non-LLM answer from the deterministic context block."""
    question_text = question.strip()
    context_text = context.strip()
    if not context_text:
        return (
            "I could not reach the configured LLM, and QA Lens did not find enough "
            "deterministic context to answer this question."
        )

    if context_text.lower().startswith("no test matching"):
        return context_text

    def _first_matching_line(*labels: str) -> str | None:
        wanted = tuple(label.lower() for label in labels)
        for line in context_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(wanted):
                return stripped
        return None

    def _section_title() -> str | None:
        for line in context_text.splitlines():
            stripped = line.strip("= ").strip()
            if stripped:
                return stripped
        return None

    facts_lines = [
        line.strip()
        for line in (structured_facts or "").splitlines()
        if line.strip()
        and not line.strip().startswith(("[", "{", "}", '"type"', '"scope"'))
    ][:3]

    title = _section_title()
    if mode == "test":
        fields = [
            _first_matching_line("=== Test:", "Test:"),
            _first_matching_line("Pass rate"),
            _first_matching_line("Flip score"),
            _first_matching_line("Classification"),
            _first_matching_line("Current streak"),
        ]
        details = [field for field in fields if field]
        if details:
            return (
                "I could not reach the configured LLM, so QA Lens is returning the "
                f"deterministic test summary for: {question_text}\n\n"
                + "\n".join(f"- {line}" for line in details)
            )

    summary_lines: list[str] = []
    if title:
        summary_lines.append(title)
    for label in (
        "Project:",
        "Runs:",
        "Latest run:",
        "Total tests:",
        "Passed:",
        "Failed:",
        "Skipped:",
        "Failed tests:",
        "New failures:",
        "Flaky tests:",
        "Consistently broken:",
    ):
        line = _first_matching_line(label)
        if line and line not in summary_lines:
            summary_lines.append(line)
        if len(summary_lines) >= 6:
            break

    if not summary_lines and facts_lines:
        summary_lines = facts_lines

    if not summary_lines:
        summary_lines = [
            line.strip()
            for line in context_text.splitlines()
            if line.strip()
        ][:6]

    return (
        "I could not reach the configured LLM, so QA Lens is returning a "
        f"deterministic summary for: {question_text}\n\n"
        + "\n".join(f"- {line}" for line in summary_lines)
    )


def _risk_ranking_fallback_summary(fact_bundle: dict[str, object]) -> str:
    """Return a deterministic fallback summary for risk-ranking chat answers."""
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    eligible_tests = int(fact_bundle.get("eligible_tests", 0) or 0)
    top_tests = list(fact_bundle.get("top_tests", []))

    if not top_tests:
        return (
            f"Across the {scope_label}, there are {eligible_tests} eligible tests in scope. "
            "I did not find any tests with sufficient history to rank for next-run risk."
        )

    top = top_tests[0]
    second = top_tests[1] if len(top_tests) > 1 else None
    top_sentence = (
        f"{top['name']} ranks highest at {top['risk_pct']}% risk ({str(top['tier']).lower()}) "
        f"driven by {top['driver']}."
    )
    if second is not None:
        second_sentence = (
            f"{second['name']} is next at {second['risk_pct']}% risk ({str(second['tier']).lower()}) "
            f"with {second['driver']}."
        )
    else:
        second_sentence = ""

    summary_parts = [
        f"Across the {scope_label}, there are {eligible_tests} eligible tests in scope.",
        top_sentence,
    ]
    if second_sentence:
        summary_parts.append(second_sentence)
    summary_parts.append("See the Results workspace for the full ranked risk list.")
    return " ".join(summary_parts)


def _risk_ranking_result_from_fact_bundle(
    fact_bundle: dict[str, object],
    *,
    title: str = "Most likely to fail next run",
    subtitle: str = "Ranked by QA Lens risk score across the selected run window",
) -> dict:
    """Convert a risk-ranking fact bundle into the Result Workspace payload."""
    top_tests = list(fact_bundle.get("top_tests", []))
    ranking = []
    for index, item in enumerate(top_tests, 1):
        name = str(item.get("name", "Unknown test"))
        tier = str(item.get("tier", "MEDIUM")).upper()
        risk_pct = item.get("risk_pct", 0)
        pass_rate = float(item.get("pass_rate", 0) or 0)
        driver = str(item.get("driver", "historical risk signals"))
        ranking.append({
            "rank": int(item.get("rank", index) or index),
            "testName": name,
            "riskTier": tier if tier in {"CRITICAL", "HIGH", "MEDIUM", "LOW"} else "MEDIUM",
            "passRate": pass_rate,
            "primaryReason": (
                f"Prioritize this test first: {risk_pct}% predicted failure risk, "
                f"driven by {driver}."
            ),
            "evidence": [
                {"label": "Risk score", "value": f"{risk_pct}%"},
                {"label": "Risk driver", "value": driver},
            ],
        })

    return {
        "type": "risk_ranking",
        "title": title,
        "subtitle": subtitle,
        "scope": {
            "label": str(fact_bundle.get("scope_label", "Selected run window")),
            "eligibleTests": int(fact_bundle.get("eligible_tests", 0) or 0),
        },
        "summary": {
            "highRisk": int(fact_bundle.get("high_risk", 0) or 0),
            "mediumRisk": int(fact_bundle.get("medium_risk", 0) or 0),
            "lowRisk": int(fact_bundle.get("low_risk", 0) or 0),
            "lowestPassRate": min((item["passRate"] for item in ranking), default=None),
        },
        "ranking": ranking,
    }


def _fix_first_fallback_summary(fact_bundle: dict[str, object]) -> str:
    """Return a deterministic fallback summary for fix-first workspace answers."""
    top_tests = list(fact_bundle.get("top_tests", []))
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    if not top_tests:
        return (
            f"Across the {scope_label}, I did not find enough ranked risk evidence "
            "to recommend a first fix. The Results workspace shows the evaluated scope."
        )

    first = top_tests[0]
    return (
        f"Across the {scope_label}, fix {first['name']} first. "
        f"It has {first['risk_pct']}% predicted failure risk and is driven by {first['driver']}. "
        "The Results workspace shows the rest of the prioritized list."
    )


def _finalize_risk_ranking_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure required scope/workspace cues exist in the narrated summary."""
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    eligible_tests = int(fact_bundle.get("eligible_tests", 0) or 0)
    normalized = answer.strip()
    lowered = normalized.lower()

    prefix = f"Across the {scope_label}, there are {eligible_tests} eligible tests in scope."
    if "eligible tests" not in lowered:
        normalized = f"{prefix} {normalized}".strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} See the Results workspace for the full ranked risk list."

    return normalized


def _owner_window_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for owner window comparison narration."""
    owners = result["owners"]
    metrics = result["metrics"]
    summary = result["summary"]
    owner_a = owners["ownerA"]
    owner_b = owners["ownerB"]
    metrics_a = metrics["ownerA"]
    metrics_b = metrics["ownerB"]

    return {
        "type": "owner_window_comparison",
        "scope_label": owners["timeLabel"],
        "run_count": owners["runCount"],
        "leader": summary["leader"],
        "pass_rate_gap": round(summary["passRateGap"] * 100),
        "flaky_gap": summary["flakyGap"],
        "regression_gap": summary["regressionGap"],
        "owners": [
            {
                "name": owner_a,
                "pass_rate_pct": round(metrics_a["passRate"] * 100),
                "failure_rate_pct": round(metrics_a["failureRate"] * 100),
                "failed_tests": metrics_a["failed"],
                "total_tests": metrics_a["totalTests"],
                "regressed": metrics_a["regressed"],
                "recovered": metrics_a["recovered"],
                "flaky_count": metrics_a["flakyCount"],
            },
            {
                "name": owner_b,
                "pass_rate_pct": round(metrics_b["passRate"] * 100),
                "failure_rate_pct": round(metrics_b["failureRate"] * 100),
                "failed_tests": metrics_b["failed"],
                "total_tests": metrics_b["totalTests"],
                "regressed": metrics_b["regressed"],
                "recovered": metrics_b["recovered"],
                "flaky_count": metrics_b["flakyCount"],
            },
        ],
    }


def _finalize_owner_window_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure owner comparison narration includes scope and workspace cue."""
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    run_count = int(fact_bundle.get("run_count", 0) or 0)
    normalized = answer.strip()
    lowered = normalized.lower()

    scope_prefix = (
        f"Across the {scope_label}, "
        if run_count != 1
        else f"In the {scope_label.lower()}, "
    )
    if not (
        lowered.startswith("across the ")
        or lowered.startswith("in the latest run")
        or lowered.startswith("in the most recent run")
    ):
        normalized = f"{scope_prefix}{normalized[:1].lower() + normalized[1:] if normalized else ''}".strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed comparison is shown in the Results workspace."

    return normalized


def _owner_flaky_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return (
        "flaky" in normalized
        and any(
            phrase in normalized
            for phrase in (
                "who owns",
                "which owner",
                "which engineer",
                "most flaky tests",
                "highest flaky",
            )
        )
    )


def _build_owner_flaky_result(*, scope_label: str, run_count: int, results: list) -> dict:
    buckets: dict[str, dict[str, object]] = {}
    for item in results:
        classification = str(getattr(item.classification, "value", item.classification)).lower()
        if classification != "flaky":
            continue
        owner = getattr(item, "owner", None) or "Unassigned"
        bucket = buckets.setdefault(
            owner,
            {
                "ownerName": owner,
                "flakyCount": 0,
                "totalTests": 0,
                "flipScoreSum": 0.0,
                "passRateSum": 0.0,
                "topTests": [],
            },
        )
        bucket["flakyCount"] = int(bucket["flakyCount"]) + 1
        bucket["totalTests"] = int(bucket["totalTests"]) + 1
        bucket["flipScoreSum"] = float(bucket["flipScoreSum"]) + float(item.flip_score)
        bucket["passRateSum"] = float(bucket["passRateSum"]) + float(item.pass_rate)
        top_tests = list(bucket["topTests"])
        top_tests.append(
            {
                "testName": item.display_name,
                "canonicalName": item.canonical_name,
                "flipScore": item.flip_score,
                "passRate": item.pass_rate,
            }
        )
        top_tests.sort(key=lambda row: (-row["flipScore"], row["passRate"], str(row["testName"]).lower()))
        bucket["topTests"] = top_tests[:3]

    ranking = []
    for owner_name, bucket in buckets.items():
        flaky_count = int(bucket["flakyCount"])
        avg_flip = float(bucket["flipScoreSum"]) / flaky_count if flaky_count else 0.0
        avg_pass = float(bucket["passRateSum"]) / flaky_count if flaky_count else 0.0
        ranking.append(
            {
                "ownerName": owner_name,
                "flakyCount": flaky_count,
                "totalTests": int(bucket["totalTests"]),
                "avgFlipScore": avg_flip,
                "avgPassRate": avg_pass,
                "primaryReason": (
                    f"{flaky_count} flaky test{'s' if flaky_count != 1 else ''} "
                    f"with an average flip score of {round(avg_flip * 100)}% across {scope_label.lower()}."
                ),
                "topTests": bucket["topTests"],
            }
        )
    ranking.sort(key=lambda row: (-row["flakyCount"], -row["avgFlipScore"], row["avgPassRate"], str(row["ownerName"]).lower()))
    ranked = [{"rank": index + 1, **item} for index, item in enumerate(ranking)]
    avg_flip = (sum(item["avgFlipScore"] for item in ranked) / len(ranked)) if ranked else 0.0
    avg_pass = (sum(item["avgPassRate"] for item in ranked) / len(ranked)) if ranked else 0.0
    return {
        "type": "owner_flaky_tests",
        "title": "Owners with the most flaky tests",
        "subtitle": f"Owner-level flaky test concentration across {scope_label.lower()}.",
        "scope": {
            "label": scope_label,
            "runCount": run_count,
            "owners": len(ranked),
            "totalEvaluated": sum(item["flakyCount"] for item in ranked),
        },
        "summary": {
            "highestFlakyCount": max((item["flakyCount"] for item in ranked), default=0),
            "avgFlipScore": avg_flip,
            "avgPassRate": avg_pass,
        },
        "ranking": ranked,
    }


def _owner_flaky_summary(result: dict) -> str:
    ranking = result["ranking"]
    scope = result["scope"]["label"].lower()
    if not ranking:
        return f"I did not find any flaky tests owned by anyone across {scope}. The detailed owner ranking is shown in the Results workspace."
    leader = ranking[0]
    names = ", ".join(test["testName"] for test in leader["topTests"][:2]) if leader["topTests"] else "No representative tests were available"
    return " ".join([
        f"Across {scope}, {leader['ownerName']} owns the most flaky tests with {leader['flakyCount']} total.",
        f"The average flip score for that owner is {round(leader['avgFlipScore'] * 100)}% with an average pass rate of {round(leader['avgPassRate'] * 100)}%.",
        f"Representative flaky tests include {names}.",
        "The detailed owner ranking is shown in the Results workspace.",
    ])


def _owner_failure_rate_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return any(
        phrase in normalized
        for phrase in (
            "failure rate per engineer",
            "failure rates per engineer",
            "failure rate per owner",
            "failure rates per owner",
            "compare failure rate per engineer",
            "compare failure rates per engineer",
            "compare failure rate per owner",
            "compare failure rates per owner",
            "which engineer has the highest failure count",
            "which owner has the highest failure count",
            "highest failure count per engineer",
            "highest failure count per owner",
        )
    )


def _build_owner_failure_rate_result_from_sources(sources: list[dict]) -> dict:
    owner_sources = [source for source in sources if source.get("type") == "owner" and source.get("metric") == "failure_rate"]
    ranking = []
    for source in owner_sources:
        owner = str(source.get("label") or "Unassigned")
        failure_rate = float(source.get("failure_rate") or 0)
        failed = int(source.get("failed_executions") or 0)
        total = int(source.get("total_executions") or 0)
        failing_tests = int(source.get("failing_tests") or 0)
        total_tests = int(source.get("total_tests") or 0)
        run_count = int(source.get("run_count") or 0)
        ranking.append({
            "ownerName": owner,
            "failureRate": failure_rate,
            "failedExecutions": failed,
            "totalExecutions": total,
            "failingTests": failing_tests,
            "totalTests": total_tests,
            "runCount": run_count,
            "primaryReason": (
                f"{owner} has a {round(failure_rate * 100)}% failure rate "
                f"across {failed}/{total} executions, with {failing_tests}/{total_tests} owned tests failing."
            ),
            "evidence": [
                {"label": "Failure rate", "value": f"{round(failure_rate * 100)}%"},
                {"label": "Failed executions", "value": f"{failed}/{total}"},
                {"label": "Failing tests", "value": f"{failing_tests}/{total_tests}"},
                {"label": "Runs observed", "value": str(run_count)},
            ],
        })

    ranking.sort(key=lambda item: (-item["failureRate"], -item["failedExecutions"], str(item["ownerName"]).lower()))
    most_failures = max((item["failedExecutions"] for item in ranking), default=0)
    ranked = []
    for index, item in enumerate(ranking, 1):
        emphasis = "highest_rate" if index == 1 else ("most_failures" if item["failedExecutions"] == most_failures and most_failures > 0 else None)
        ranked.append({"rank": index, **item, "emphasis": emphasis})

    total_runs = max((item["runCount"] for item in ranked), default=0)
    return {
        "type": "owner_failure_rate",
        "title": "Failure rate per engineer",
        "subtitle": "Current-owner rollup ranked by failure rate across available run history.",
        "scope": {
            "label": "All-time ownership history",
            "totalRuns": total_runs or None,
            "owners": len(ranked),
        },
        "summary": {
            "highestFailureRate": max((item["failureRate"] for item in ranked), default=0),
            "mostFailures": most_failures,
            "mostFailingTests": max((item["failingTests"] for item in ranked), default=0),
        },
        "ranking": ranked,
    }


def _owner_failure_rate_summary(result: dict) -> str:
    ranking = result["ranking"]
    if not ranking:
        return "I did not find owner failure-rate data for this project."
    leader = ranking[0]
    return (
        f"{leader['ownerName']} has the highest failure rate at {round(leader['failureRate'] * 100)}%, "
        f"based on {leader['failedExecutions']}/{leader['totalExecutions']} failed executions. "
        f"{result['scope']['owners']} engineers are ranked in the Results workspace."
    )


def _owner_flaky_fact_bundle(result: dict) -> dict[str, object]:
    return {
        "type": "owner_flaky_tests",
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "owners": result["scope"]["owners"],
        "total_flaky_tests": result["scope"]["totalEvaluated"],
        "highest_flaky_count": result["summary"]["highestFlakyCount"],
        "avg_flip_score_pct": round(result["summary"]["avgFlipScore"] * 100),
        "avg_pass_rate_pct": round(result["summary"]["avgPassRate"] * 100),
        "top_owners": [
            {
                "rank": item["rank"],
                "name": item["ownerName"],
                "flaky_count": item["flakyCount"],
                "avg_flip_score_pct": round(item["avgFlipScore"] * 100),
                "avg_pass_rate_pct": round(item["avgPassRate"] * 100),
                "top_tests": [test["testName"] for test in item["topTests"][:2]],
            }
            for item in result["ranking"][:5]
        ],
    }


def _finalize_owner_flaky_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    normalized = answer.strip()
    lowered = normalized.lower()
    if not (lowered.startswith("across ") or lowered.startswith("in ")):
        normalized = f"Across {scope_label}, {normalized[:1].lower() + normalized[1:] if normalized else ''}".strip()
        lowered = normalized.lower()
    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed owner ranking is shown in the Results workspace."
    return normalized


def _run_retrieval_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for run retrieval narration."""
    query = result["query"]
    tests = result["tests"][:5]
    return {
        "type": "run_retrieval",
        "run_label": result["run"]["label"],
        "project": result["run"].get("project"),
        "query_kind": query["kind"],
        "query_label": query["label"],
        "target_test": query.get("targetTest"),
        "matched_tests": query["matchedTests"],
        "summary": {
            "total": result["summary"]["total"],
            "passed": result["summary"]["passed"],
            "failed": result["summary"]["failed"],
            "skipped": result["summary"]["skipped"],
            "pass_rate_pct": round(result["summary"]["passRate"] * 100),
        },
        "tests": [
            {
                "name": item["name"],
                "status": item["status"],
                "suite": item.get("suite"),
                "owner": item.get("owner"),
                "error_type": item.get("errorType"),
            }
            for item in tests
        ],
    }


def _finalize_run_retrieval_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure run retrieval narration preserves run identity and workspace cue."""
    run_label = str(fact_bundle.get("run_label", "the requested run"))
    normalized = answer.strip()
    lowered = normalized.lower()
    if run_label.lower() not in lowered:
        normalized = f"{run_label}: {normalized}"
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed run breakdown is shown in the Results workspace."

    return normalized


def _stability_trend_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for stability trend narration."""
    return {
        "type": "stability_trend",
        "scope_label": result["scope"]["label"],
        "query_label": result["query"]["label"],
        "query_kind": result["query"]["kind"],
        "threshold_pct": (
            round(result["query"]["threshold"] * 100)
            if result["query"].get("threshold") is not None
            else None
        ),
        "failure_count_threshold": result["query"].get("failureCountThreshold"),
        "matches": result["summary"]["matches"],
        "avg_pass_rate_pct": round(result["summary"]["avgPassRate"] * 100),
        "avg_flip_score_pct": round(result["summary"]["avgFlipScore"] * 100),
        "highest_fail_count": result["summary"]["highestFailCount"],
        "actively_failing": result["summary"]["activelyFailing"],
        "top_tests": [
            {
                "rank": item["rank"],
                "name": item["testName"],
                "classification": item["classification"],
                "pass_rate_pct": round(item["passRate"] * 100),
                "flip_score_pct": round(item["flipScore"] * 100),
                "fail_count": item["failCount"],
                "current_streak": item["currentStreak"],
                "primary_reason": item["primaryReason"],
            }
            for item in result["tests"][:5]
        ],
    }


def _finalize_stability_trend_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure trend narration includes scope and workspace cue."""
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    matches = int(fact_bundle.get("matches", 0) or 0)
    query_label = str(fact_bundle.get("query_label", "this trend")).lower()
    normalized = answer.strip()
    lowered = normalized.lower()

    if matches == 0 and "did not find" not in lowered and "no " not in lowered:
        normalized = (
            f'I did not find any tests matching "{query_label}" across {scope_label}. '
            f"{normalized}"
        ).strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed stability breakdown is shown in the Results workspace."

    return normalized


def _root_cause_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for root-cause narration."""
    return {
        "type": "root_cause_insight",
        "scope_label": result["scope"]["label"],
        "scope_kind": result["scope"]["kind"],
        "target_test": result["scope"].get("targetTest"),
        "run_count": result["scope"]["runCount"],
        "latest_run": result["scope"].get("latestRun"),
        "total_tests_evaluated": result["scope"]["totalTestsEvaluated"],
        "summary": {
            "total_failures": result["summary"]["totalFailures"],
            "affected_tests": result["summary"]["affectedTests"],
            "affected_runs": result["summary"]["affectedRuns"],
            "dominant_category": result["summary"].get("dominantCategory"),
            "dominant_family": result["summary"].get("dominantFamily"),
        },
        "top_causes": [
            {
                "rank": item["rank"],
                "family": item["family"],
                "category": item["category"],
                "count": item["count"],
                "affected_tests": item["affectedTests"],
                "affected_runs": item["affectedRuns"],
                "probable_cause": item["probableCause"],
                "recommended_action": item["recommendedAction"],
                "confidence": item["confidence"],
                "sample_message": item["sampleMessages"][0] if item["sampleMessages"] else None,
                "top_test": item["topTests"][0]["testName"] if item["topTests"] else None,
            }
            for item in result["causes"][:5]
        ],
    }


def _finalize_root_cause_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure root-cause narration preserves no-evidence and workspace cues."""
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    top_causes = list(fact_bundle.get("top_causes", []))
    target_test = fact_bundle.get("target_test")
    normalized = answer.strip()
    lowered = normalized.lower()

    if not top_causes and "did not find enough failure evidence" not in lowered:
        if target_test:
            normalized = (
                f"I did not find enough failure evidence to explain why {target_test} is failing across {scope_label}. "
                f"{normalized}"
            ).strip()
        else:
            normalized = (
                f"I did not find enough failure evidence to explain the root cause across {scope_label}. "
                f"{normalized}"
            ).strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed cause breakdown is shown in the Results workspace."

    return normalized


def _exception_retrieval_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for exception retrieval narration."""
    return {
        "type": "exception_retrieval",
        "scope_label": result["scope"]["label"],
        "query": result["scope"]["query"],
        "run_count": result["scope"]["runCount"],
        "summary": {
            "matches": result["summary"]["matches"],
            "unique_tests": result["summary"]["uniqueTests"],
            "affected_runs": result["summary"]["affectedRuns"],
            "dominant_category": result["summary"].get("dominantCategory"),
        },
        "top_matches": [
            {
                "test_name": item["testName"],
                "run_label": item["runLabel"],
                "status": item["status"],
                "error_type": item.get("errorType"),
                "category": item.get("category"),
                "message": item.get("message"),
            }
            for item in result["matches"][:5]
        ],
    }


def _finalize_exception_retrieval_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure exception narration preserves no-match and workspace cues."""
    scope_label = str(fact_bundle.get("scope_label", "selected scope")).lower()
    query = str(fact_bundle.get("query", "this failure match"))
    matches = int((fact_bundle.get("summary") or {}).get("matches", 0) or 0)
    normalized = answer.strip()
    lowered = normalized.lower()

    if matches == 0 and "did not find any failures" not in lowered:
        normalized = (
            f'I did not find any failures matching "{query}" in {scope_label}. '
            f"{normalized}"
        ).strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed exception breakdown is shown in the Results workspace."

    return normalized


def _owner_suite_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for owner suite comparison narration."""
    return {
        "type": "owner_suite_comparison",
        "owner_a": result["owners"]["ownerA"],
        "owner_b": result["owners"]["ownerB"],
        "summary": {
            "shared_suites": result["summary"]["sharedSuites"],
            "owner_a_only_suites": result["summary"]["ownerAOnlySuites"],
            "owner_b_only_suites": result["summary"]["ownerBOnlySuites"],
            "owner_a_failing_suites": result["summary"]["ownerAFailingSuites"],
            "owner_b_failing_suites": result["summary"]["ownerBFailingSuites"],
        },
        "shared": [
            {
                "suite_name": item["suiteName"],
                "owner_a_tests": item["ownerATests"],
                "owner_a_failing": item["ownerAFailing"],
                "owner_b_tests": item["ownerBTests"],
                "owner_b_failing": item["ownerBFailing"],
            }
            for item in result["shared"][:5]
        ],
        "owner_a_only": [
            {
                "suite_name": item["suiteName"],
                "tests": item["tests"],
                "failing": item["failing"],
                "new_failures": item["newFailures"],
            }
            for item in result["ownerAOnly"][:5]
        ],
        "owner_b_only": [
            {
                "suite_name": item["suiteName"],
                "tests": item["tests"],
                "failing": item["failing"],
                "new_failures": item["newFailures"],
            }
            for item in result["ownerBOnly"][:5]
        ],
    }


def _finalize_owner_suite_narration(answer: str) -> str:
    """Ensure owner suite narration includes workspace and narrowing cues."""
    normalized = answer.strip()
    lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed suite comparison is shown in the Results workspace."
        lowered = normalized.lower()

    if "narrow" not in lowered and "last 5" not in lowered and "last 10" not in lowered:
        normalized = (
            f"{normalized} If you want, QA Lens can also narrow this to a particular run window like the last 5 or 10 runs."
        )

    return normalized


def _owner_test_gap_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for owner test-gap narration."""
    return {
        "type": "owner_test_gap",
        "mode": result.get("mode", "gap"),
        "owner": result["owner"],
        "compared_against": result.get("comparedAgainst"),
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "total_tests": result["scope"]["totalTests"],
        "summary": {
            "currently_failing": result["summary"]["currentlyFailing"],
            "regressed": result["summary"]["regressed"],
            "flaky": result["summary"]["flaky"],
            "top_suite": result["summary"].get("topSuite"),
        },
        "top_tests": [
            {
                "rank": item["rank"],
                "test_name": item["testName"],
                "suite": item.get("suite"),
                "pass_rate_pct": round(item["passRate"] * 100),
                "fail_count": item["failCount"],
                "current_status": item["currentStatus"],
                "regressed": item["regressed"],
                "flaky": item["flaky"],
                "risk_tier": item["riskTier"],
                "primary_reason": item["primaryReason"],
            }
            for item in result["tests"][:5]
        ],
    }


def _finalize_owner_test_gap_narration(answer: str) -> str:
    """Ensure owner test-gap narration includes the workspace cue."""
    normalized = answer.strip()
    if "results workspace" not in normalized.lower():
        normalized = f"{normalized} The detailed ranked view is shown in the Results workspace."
    return normalized


def _shared_suite_failure_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for shared-suite failure narration."""
    owner_a = result["owners"]["ownerA"]
    owner_b = result["owners"]["ownerB"]
    return {
        "type": "shared_suite_failures",
        "owner_a": owner_a,
        "owner_b": owner_b,
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "summary": {
            "shared_suites": result["summary"]["sharedSuites"],
            "top_suite": result["summary"].get("topSuite"),
        },
        "top_suites": [
            {
                "rank": item["rank"],
                "suite_name": item["suiteName"],
                "owner_a_currently_failing": item["ownerA"]["currentlyFailing"],
                "owner_a_regressed": item["ownerA"]["regressed"],
                "owner_a_failures_in_scope": item["ownerA"]["failuresInScope"],
                "owner_b_currently_failing": item["ownerB"]["currentlyFailing"],
                "owner_b_regressed": item["ownerB"]["regressed"],
                "owner_b_failures_in_scope": item["ownerB"]["failuresInScope"],
                "combined_pressure": item["combinedPressure"],
            }
            for item in result["suites"][:5]
        ],
    }


def _finalize_shared_suite_failure_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    """Ensure shared-suite narration preserves no-shared-suite and workspace cues."""
    owner_a = str(fact_bundle.get("owner_a", "owner A"))
    owner_b = str(fact_bundle.get("owner_b", "owner B"))
    shared_suites = int((fact_bundle.get("summary") or {}).get("shared_suites", 0) or 0)
    normalized = answer.strip()
    lowered = normalized.lower()

    if shared_suites == 0 and "no shared suites" not in lowered:
        normalized = f"No shared suites were found between {owner_a} and {owner_b}. {normalized}".strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed shared-suite breakdown is shown in the Results workspace."

    return normalized


def _owner_suite_regression_fact_bundle(result: dict) -> dict[str, object]:
    """Return a compact fact bundle for owner suite-regression narration."""
    return {
        "type": "owner_suite_regressions",
        "owner": result["owner"],
        "compared_against": result.get("comparedAgainst"),
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "total_suites": result["scope"]["totalSuites"],
        "summary": {
            "top_suite": result["summary"].get("topSuite"),
            "regressed_suites": result["summary"]["regressedSuites"],
            "currently_failing_suites": result["summary"]["currentlyFailingSuites"],
            "flaky_suites": result["summary"]["flakySuites"],
        },
        "top_suites": [
            {
                "rank": item["rank"],
                "suite_name": item["suiteName"],
                "tests": item["tests"],
                "currently_failing": item["currentlyFailing"],
                "regressed": item["regressed"],
                "flaky": item["flaky"],
                "failures_in_scope": item["failuresInScope"],
                "lowest_pass_rate_pct": round(item["lowestPassRate"] * 100),
            }
            for item in result["suites"][:5]
        ],
    }


def _finalize_owner_suite_regression_narration(answer: str) -> str:
    """Ensure owner suite-regression narration includes the workspace cue."""
    normalized = answer.strip()
    if "results workspace" not in normalized.lower():
        normalized = f"{normalized} The detailed suite breakdown is shown in the Results workspace."
    return normalized


def _suite_comparison_question(question: str) -> bool:
    normalized = _normalize_text(question)
    asks_compare = any(token in normalized for token in ("compare", "difference", "versus", "vs"))
    asks_suite = "suite" in normalized or "suites" in normalized
    return asks_compare and asks_suite


def _owner_pair_compare_question(question: str) -> bool:
    normalized = _normalize_text(question)
    asks_compare = any(token in normalized for token in (
        "compare",
        "comparison",
        "difference",
        "versus",
        "vs",
        "better than",
        "worse than",
        "who performs better",
        "performs better",
        "performs worse",
        "performance",
        "outperform",
        "doing better",
    ))
    asks_ownerish = any(token in normalized for token in (
        "owner",
        "owners",
        "tests",
        "test",
        "failure rate",
        "failure rates",
        "pass rate",
        "pass rates",
    ))
    return asks_compare or asks_ownerish


def _owner_focus_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return any(
        phrase in normalized
        for phrase in (
            "driving the current gap",
            "driving the gap",
            "top failing tests",
            "which of",
            "suite level regressions",
            "suite-level regressions",
        )
    ) and any(
        phrase in normalized
        for phrase in (
            "tests",
            "test",
            "regressions",
            "gap",
        )
    )


def _owner_failing_tests_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return (
        any(
            phrase in normalized
            for phrase in (
                "which tests owned by",
                "tests owned by",
                "owned by",
            )
        )
        and any(
            phrase in normalized
            for phrase in (
                "are failing",
                "failing now",
                "currently failing",
                "failed",
            )
        )
    )


def _explicit_owner_constraint(question: str) -> str | None:
    patterns = [
        r"\bowned\s+by\s+(.+?)(?:[?.!]|$)",
        r"\bfor\s+owner\s+(.+?)(?:[?.!]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" ?!.:,;\"'")
            if candidate:
                return candidate
    return None


def _owner_suite_regression_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return "suite" in normalized and any(
        phrase in normalized
        for phrase in (
            "causing most",
            "most regressions",
            "suite level regressions",
            "suite-level regressions",
            "regressions",
        )
    )


def _shared_suite_failure_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return (
        "shared suite" in normalized or "shared suites" in normalized
    ) and any(
        phrase in normalized
        for phrase in (
            "failing",
            "failing most",
            "fail most",
            "most failures",
            "most of the failures",
        )
    )


def _suite_failure_ranking_question(question: str) -> bool:
    normalized = _normalize_text(question)
    if "suite" not in normalized and "suites" not in normalized:
        return False
    return any(
        phrase in normalized
        for phrase in (
            "causing the most failures",
            "causing most failures",
            "most failures",
            "most failing",
            "highest failure",
            "failure rate",
            "failure burden",
            "which suite is causing",
            "which suites are causing",
        )
    )


def _comparison_window_limit(question: str) -> int:
    normalized = _normalize_text(question)
    if any(phrase in normalized for phrase in ("last run", "latest run", "most recent run", "current run")):
        return 1
    match = re.search(r"\blast\s+(\d+)\s+runs?\b", normalized)
    if match:
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            return 10
    return 10


_RUN_NUMBER_RE = re.compile(
    r"\brun\s*(?:no\.?|number|#|num\.?)?\s*(\d{1,5})\b",
    re.IGNORECASE,
)


def _extract_run_number(question: str) -> int | None:
    match = _RUN_NUMBER_RE.search(question)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_run_numbers(question: str) -> list[int]:
    seen: list[int] = []
    for match in _RUN_NUMBER_RE.finditer(question):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if value not in seen:
            seen.append(value)
    return seen


def _mentions_latest_run(question: str) -> bool:
    normalized = _normalize_text(question)
    return any(
        phrase in normalized
        for phrase in ("latest run", "last run", "most recent run", "current run")
    )


def _run_comparison_question(question: str) -> bool:
    normalized = _normalize_text(question)
    has_compare_cue = any(
        phrase in normalized
        for phrase in (
            "compare",
            "difference between",
            "what changed between",
            "changed between",
            "versus",
            "vs",
        )
    )
    run_numbers = _extract_run_numbers(question)
    if len(run_numbers) >= 2 and has_compare_cue:
        return True
    if has_compare_cue and any(phrase in normalized for phrase in ("last two runs", "latest two runs", "last 2 runs")):
        return True
    return False


def _new_failures_introduced_question(question: str) -> bool:
    normalized = _normalize_text(question)
    phrases = (
        "new failures",
        "new failure",
        "failures were introduced",
        "introduced failures",
        "introduced regressions",
        "new regressions",
        "started failing recently",
        "started failing",
    )
    if any(phrase in normalized for phrase in phrases):
        return True
    return "what changed" in normalized and "run" in normalized and "failure" in normalized


def _failure_trend_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return any(
        phrase in normalized
        for phrase in (
            "are failures increasing or decreasing",
            "is failure count increasing or decreasing",
            "failure trend",
            "trend of failures",
            "are failures increasing",
            "are failures decreasing",
        )
    )


def _extract_status_lookup_test(question: str) -> str | None:
    backtick = re.search(r"`([^`]+)`", question)
    if backtick:
        candidate = backtick.group(1).strip()
        return candidate or None

    match = re.search(
        r"\bstatus\s+of\s+(.+?)\s+in\s+(?:run\b|the\s+latest\s+run|latest\s+run|the\s+last\s+run|last\s+run|the\s+most\s+recent\s+run|most\s+recent\s+run|current\s+run)",
        question,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    candidate = match.group(1).strip(" ?!.:,;\"'")
    return candidate or None


def _run_retrieval_kind(question: str) -> str | None:
    normalized = _normalize_text(question)
    has_run_scope = _extract_run_number(question) is not None or _mentions_latest_run(question)
    if not has_run_scope:
        return None

    if "status of" in normalized:
        return "status_lookup"
    if "passed vs failed" in normalized or ("count" in normalized and "passed" in normalized and "failed" in normalized):
        return "run_counts"
    if "skipped" in normalized:
        return "skipped_tests"
    if any(token in normalized for token in ("failed", "failures", "broke", "broken")):
        return "failed_tests"
    if any(token in normalized for token in ("all tests", "all test cases", "executed", "tests executed")):
        return "all_tests"
    return None


def _exception_query_term(question: str) -> str | None:
    def _clean_exception_candidate(value: str) -> str:
        cleaned = re.sub(
            r"\s+(?:and\s+)?belong(?:s)?\s+to\s+.+?\s+(?:module|team)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+(?:and\s+)?(?:in|from)\s+.+?\s+(?:module|suite)\b.*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+(?:and\s+)?owned\s+by\s+.+$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" ?!.:,;\"'")

    patterns = [
        r"(?:due to|caused by)\s+(.+?)(?:\s+in\s+run\b|\s+in\s+the\s+latest\s+run\b|\s+in\s+the\s+last\s+run\b|\s+across\s+all\s+runs\b|\s+across\s+runs\b|[?.!]|$)",
        r"(?:failing with|failed with|fail with|failures caused by)\s+(.+?)(?:\s+in\s+run\b|\s+in\s+the\s+latest\s+run\b|\s+in\s+the\s+last\s+run\b|\s+across\s+all\s+runs\b|\s+across\s+runs\b|[?.!]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            candidate = _clean_exception_candidate(match.group(1))
            if candidate:
                return candidate

    normalized = _normalize_text(question)
    known_terms = (
        "nosuchelementexception",
        "staleelementreferenceexception",
        "nullpointerexception",
        "assertion errors",
        "assertion error",
        "timeout exceptions",
        "timeout exception",
        "timeout",
        "element not clickable",
        "stale element",
        "no such element",
    )
    for term in known_terms:
        if term in normalized:
            return term
    return None


def _extract_exception_secondary_filter(question: str) -> dict[str, str] | None:
    stripped = question.strip()
    patterns = [
        (r"\bbelong(?:s)?\s+to\s+(.+?)\s+module\b", "module"),
        (r"\bin\s+(.+?)\s+module\b", "module"),
        (r"\bfrom\s+(.+?)\s+module\b", "module"),
        (r"\bin\s+(.+?)\s+suite\b", "suite"),
        (r"\bfrom\s+(.+?)\s+suite\b", "suite"),
        (r"\bowned\s+by\s+(.+?)(?:[?.!]|$)", "owner"),
        (r"\bbelong(?:s)?\s+to\s+(.+?)\s+team\b", "team"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" ?!.:,;\"'")
            if value:
                return {"kind": kind, "value": value}
    return None


def _matches_exception_secondary_filter(tc, extra_filter: dict[str, str] | None) -> bool:
    if not extra_filter:
        return True

    normalized_value = _normalize_text(extra_filter["value"])
    kind = extra_filter["kind"]
    if kind == "suite":
        return normalized_value in _normalize_text(tc.suite or "")
    if kind == "owner":
        return normalized_value in _normalize_text(tc.owner or "")
    if kind in {"module", "team"}:
        haystacks = [
            _normalize_text(tc.feature or ""),
            _normalize_text(tc.story or ""),
            _normalize_text(tc.suite or ""),
            *[_normalize_text(str(tag)) for tag in (tc.tags or [])],
        ]
        return any(normalized_value in haystack for haystack in haystacks if haystack)
    return True


def _exception_query_label(query_term: str, extra_filter: dict[str, str] | None) -> str:
    if not extra_filter:
        return query_term
    value = extra_filter["value"]
    kind = extra_filter["kind"]
    if kind == "module":
        return f"{query_term} in {value} module"
    if kind == "suite":
        return f"{query_term} in {value} suite"
    if kind == "owner":
        return f"{query_term} owned by {value}"
    if kind == "team":
        return f"{query_term} in {value} team"
    return query_term


def _is_exception_retrieval_question(question: str) -> bool:
    normalized = _normalize_text(question)
    if _exception_query_term(question) is None:
        return False
    return any(
        token in normalized
        for token in (
            "failed",
            "failure",
            "failures",
            "failing",
            "tests",
            "test",
            "show all failures",
            "list all tests",
            "find tests",
        )
    )


def _exception_scope_label(question: str, run_label: str | None, run_count: int) -> str:
    if run_label is not None:
        return run_label
    if run_count == 1:
        return "Latest run"
    return "All recorded runs"


def _failure_matches_query(*, query_term: str, error_type: str | None, message: str | None) -> tuple[bool, str | None]:
    from qalens.analyzers.categorizer import FailureCategory, categorize_failure

    normalized_query = _normalize_text(query_term)
    combined = " ".join(
        part for part in (
            error_type or "",
            (error_type or "").split(".")[-1],
            message or "",
        )
        if part
    )
    normalized_combined = _normalize_text(combined)
    category = categorize_failure(error_type=error_type, message=message)
    category_label = category.label

    category_map = {
        "timeout": FailureCategory.TIMEOUT,
        "timeout exception": FailureCategory.TIMEOUT,
        "timeout exceptions": FailureCategory.TIMEOUT,
        "assertion": FailureCategory.ASSERTION,
        "assertion error": FailureCategory.ASSERTION,
        "assertion errors": FailureCategory.ASSERTION,
        "stale element": FailureCategory.STALE_ELEMENT,
        "staleelementreferenceexception": FailureCategory.STALE_ELEMENT,
        "no such element": FailureCategory.ELEMENT_NOT_FOUND,
        "nosuchelementexception": FailureCategory.ELEMENT_NOT_FOUND,
    }
    mapped = category_map.get(normalized_query)
    if mapped is not None and category == mapped:
        return True, category_label

    if normalized_query and normalized_query in normalized_combined:
        return True, category_label

    tokens = [token for token in normalized_query.split() if token not in {"exception", "exceptions", "error", "errors"}]
    if tokens and all(token in normalized_combined for token in tokens):
        return True, category_label

    return False, category_label


def _build_exception_retrieval_result(*, query_term: str, scope_label: str, runs: list, matches: list[dict]) -> dict:
    unique_tests = len({item["canonicalName"] or item["testName"] for item in matches})
    affected_runs = len({item["runLabel"] for item in matches})
    category_counts: dict[str, int] = defaultdict(int)
    for item in matches:
        if item.get("category"):
            category_counts[item["category"]] += 1
    dominant_category = max(category_counts.items(), key=lambda item: item[1])[0] if category_counts else None

    return {
        "type": "exception_retrieval",
        "title": f'Failures matching "{query_term}"',
        "subtitle": f'Exception and failure-message matches from {scope_label.lower()}.',
        "scope": {
            "label": scope_label,
            "query": query_term,
            "runCount": len(runs),
        },
        "summary": {
            "matches": len(matches),
            "uniqueTests": unique_tests,
            "affectedRuns": affected_runs,
            "dominantCategory": dominant_category,
        },
        "matches": matches,
    }


def _exception_retrieval_summary(result: dict) -> str:
    matches = result["matches"]
    if not matches:
        return "\n".join([
            f'I did not find any failures matching "{result["scope"]["query"]}" in {result["scope"]["label"].lower()}.',
            "",
            "The scope breakdown is shown in the Results workspace.",
        ])

    lines = [
        f'I found {result["summary"]["matches"]} matching failure{"s" if result["summary"]["matches"] != 1 else ""} for "{result["scope"]["query"]}" in {result["scope"]["label"].lower()}.',
        "",
        "Top matches:",
        *[
            f'- {item["testName"]} — {item["runLabel"]}'
            + (f' · {item["errorType"]}' if item.get("errorType") else "")
            for item in matches[:5]
        ],
        "",
        "The detailed exception breakdown is shown in the Results workspace.",
    ]
    return "\n".join(lines)


def _match_tests_in_run(test_cases: list, query: str) -> list:
    from qalens.analyzers.canonical import to_canonical_name

    query_canonical = to_canonical_name(query)
    exact = [
        tc for tc in test_cases
        if tc.canonical_name == query_canonical or to_canonical_name(tc.name) == query_canonical
    ]
    if exact:
        return exact

    tokens = set(query_canonical.split())
    partial = [
        tc for tc in test_cases
        if query_canonical in tc.canonical_name
        or query_canonical in to_canonical_name(tc.name)
        or (tokens and tokens & set(tc.canonical_name.split()))
    ]
    return partial


def _run_retrieval_visible_tests(question_kind: str, test_cases: list, target_test: str | None) -> tuple[list, str]:
    if question_kind == "failed_tests":
        return [tc for tc in test_cases if tc.status in ("failed", "broken")], "Failed tests"
    if question_kind == "skipped_tests":
        return [tc for tc in test_cases if tc.status == "skipped"], "Skipped tests"
    if question_kind == "status_lookup":
        return (_match_tests_in_run(test_cases, target_test or "") if target_test else []), "Matched tests"
    return list(test_cases), "Executed tests"


def _run_query_subtitle(kind: str, run_label: str, target_test: str | None) -> str:
    if kind == "failed_tests":
        return f"Failed tests and error details for {run_label}."
    if kind == "skipped_tests":
        return f"Skipped tests recorded in {run_label}."
    if kind == "status_lookup":
        return f"Status lookup for {target_test or 'the requested test'} in {run_label}."
    if kind == "run_counts":
        return f"Passed, failed, and skipped counts for {run_label}, with the executed test list below."
    return f"Executed tests captured in {run_label}."


def _build_run_retrieval_result(run, test_cases: list, question: str) -> dict:
    kind = _run_retrieval_kind(question) or "all_tests"
    target_test = _extract_status_lookup_test(question)
    visible_tests, visible_label = _run_retrieval_visible_tests(kind, test_cases, target_test)

    passed = sum(1 for tc in test_cases if tc.status == "passed")
    failed = sum(1 for tc in test_cases if tc.status in ("failed", "broken"))
    skipped = sum(1 for tc in test_cases if tc.status == "skipped")
    total = len(test_cases)
    pass_rate = (passed / total) if total else 0.0
    run_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id

    ordered_tests = sorted(
        visible_tests,
        key=lambda tc: (
            0 if tc.status in ("failed", "broken") else 1 if tc.status == "skipped" else 2,
            tc.name.lower(),
        ),
    )

    return {
        "type": "run_retrieval",
        "title": run_label,
        "subtitle": _run_query_subtitle(kind, run_label, target_test),
        "run": {
            "label": run_label,
            "project": run.project,
            "runId": run.run_id,
        },
        "query": {
            "kind": kind,
            "label": visible_label,
            "targetTest": target_test,
            "matchedTests": len(ordered_tests),
        },
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "passRate": pass_rate,
        },
        "tests": [
            {
                "name": tc.name,
                "status": tc.status,
                "suite": tc.suite,
                "owner": tc.owner,
                "errorType": tc.error_type.split(".")[-1] if tc.error_type else None,
                "message": (tc.message.split("\n")[0][:180] if tc.message else None),
            }
            for tc in ordered_tests
        ],
    }


def _run_retrieval_summary(result: dict) -> str:
    run_label = result["run"]["label"]
    kind = result["query"]["kind"]
    target_test = result["query"].get("targetTest")
    tests = result["tests"]
    summary = result["summary"]

    if kind == "status_lookup":
        if not tests:
            return "\n".join([
                f"I checked {run_label}, but I could not find a test matching {target_test or 'that name'}.",
                "",
                "The run breakdown is shown in the Results workspace.",
            ])
        status_lines = [
            f"{item['name']} — {item['status'].replace('_', ' ')}"
            + (f" · {item['errorType']}" if item.get("errorType") else "")
            for item in tests[:3]
        ]
        return "\n".join([
            f"I checked the status of {target_test or 'that test'} in {run_label}.",
            "",
            *status_lines,
            "",
            "The run breakdown is shown in the Results workspace.",
        ])

    if kind == "run_counts":
        return "\n".join([
            f"{run_label} executed {summary['total']} tests.",
            "",
            f"Passed: {summary['passed']}",
            f"Failed: {summary['failed']}",
            f"Skipped: {summary['skipped']}",
            "",
            "The detailed run breakdown is shown in the Results workspace.",
        ])

    if kind == "skipped_tests":
        if not tests:
            return "\n".join([
                f"There were no skipped tests in {run_label}.",
                "",
                "The full run breakdown is shown in the Results workspace.",
            ])
        bullet_lines = [f"- {item['name']}" for item in tests[:5]]
        return "\n".join([
            f"I found {len(tests)} skipped test{'s' if len(tests) != 1 else ''} in {run_label}.",
            "",
            *bullet_lines,
            "",
            "The full run breakdown is shown in the Results workspace.",
        ])

    if kind == "failed_tests":
        if not tests:
            return "\n".join([
                f"There were no failed tests in {run_label}.",
                "",
                "The full run breakdown is shown in the Results workspace.",
            ])
        bullet_lines = [
            f"- {item['name']}" + (f" — {item['errorType']}" if item.get("errorType") else "")
            for item in tests[:5]
        ]
        return "\n".join([
            f"I found {len(tests)} failed test{'s' if len(tests) != 1 else ''} in {run_label}.",
            "",
            *bullet_lines,
            "",
            "The full run breakdown is shown in the Results workspace.",
        ])

    bullet_lines = [f"- {item['name']} — {item['status'].replace('_', ' ')}" for item in tests[:5]]
    return "\n".join([
        f"{run_label} contains {summary['total']} executed tests.",
        "",
        *bullet_lines,
        "",
        "The full run breakdown is shown in the Results workspace.",
    ])


def _performance_timing_kind(question: str) -> str | None:
    normalized = _normalize_text(question)
    if "slowest" in normalized:
        return "slowest_tests"

    threshold_ms = _performance_threshold_ms(question)
    if threshold_ms is not None and any(
        token in normalized
        for token in (
            "taking more than",
            "more than",
            "over",
            "above",
            "longer than",
        )
    ) and any(
        token in normalized
        for token in (
            "slow",
            "duration",
            "execution time",
            "taking",
            "performance",
            "tests",
            "test",
        )
    ):
        return "threshold_exceeded"

    if any(
        phrase in normalized
        for phrase in (
            "execution times increasing",
            "execution time increasing",
            "times increasing",
            "taking longer",
            "running longer",
            "getting slower",
            "slowing down",
            "duration trend",
            "duration increase",
        )
    ):
        return "duration_increasing"

    if (
        "performance regression" in normalized
        or "performance regressions" in normalized
        or ("performance" in normalized and "regression" in normalized)
    ):
        return "performance_regressions"

    if "slow tests" in normalized or "slow test" in normalized:
        return "slowest_tests"

    return None


def _performance_threshold_ms(question: str) -> int | None:
    from qalens.utils.text import parse_duration_ms

    match = re.search(
        r"(?:more than|over|above|longer than)\s+(\d+(?:\.\d+)?)\s*(milliseconds?|ms|seconds?|secs?|s|minutes?|mins?|m)\b",
        question,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    value = match.group(1)
    unit = match.group(2).lower()
    if unit.startswith("millisecond"):
        unit = "ms"
    elif unit.startswith("sec") or unit.startswith("second"):
        unit = "s"
    elif unit.startswith("min") or unit.startswith("minute"):
        unit = "m"
    return parse_duration_ms(f"{value}{unit}")


def _format_duration_ms(ms: int | float | None) -> str:
    if ms is None:
        return "NA"
    value = float(ms)
    if value < 1000:
        return f"{int(round(value))}ms"
    if value < 60_000:
        return f"{value / 1000:.1f}s"
    minutes = int(value // 60_000)
    seconds = (value % 60_000) / 1000
    if seconds < 1:
        return f"{minutes}m"
    return f"{minutes}m {seconds:.0f}s"


def _performance_query_label(kind: str, threshold_ms: int | None) -> str:
    if kind == "threshold_exceeded":
        threshold_label = _format_duration_ms(threshold_ms or 5000)
        return f"Tests taking more than {threshold_label}"
    if kind == "slowest_tests":
        return "Slowest tests"
    if kind == "duration_increasing":
        return "Tests with increasing execution time"
    if kind == "performance_regressions":
        return "Performance regressions"
    return "Performance timing"


def _performance_title(kind: str) -> str:
    if kind == "threshold_exceeded":
        return "Slow tests over threshold"
    if kind == "slowest_tests":
        return "Slowest tests"
    if kind == "duration_increasing":
        return "Tests with increasing execution time"
    if kind == "performance_regressions":
        return "Performance regressions"
    return "Performance timing"


def _performance_row_tier(item: dict, kind: str, threshold_ms: int | None) -> str:
    avg_ms = float(item["avgDurationMs"])
    latest_ms = float(item["latestDurationMs"])
    trend_score = float(item["trendScore"])
    threshold = float(threshold_ms or 5000)

    if kind == "performance_regressions":
        if trend_score >= 0.2 or latest_ms >= threshold * 2:
            return "HIGH"
        if trend_score >= 0.1 or latest_ms >= threshold:
            return "MEDIUM"
        return "LOW"

    if kind == "duration_increasing":
        if trend_score >= 0.2:
            return "HIGH"
        if trend_score >= 0.08:
            return "MEDIUM"
        return "LOW"

    if max(avg_ms, latest_ms) >= threshold * 2:
        return "HIGH"
    if max(avg_ms, latest_ms) >= threshold:
        return "MEDIUM"
    return "LOW"


def _performance_primary_reason(item: dict, kind: str, scope_label: str, threshold_ms: int | None) -> str:
    avg_label = _format_duration_ms(item["avgDurationMs"])
    latest_label = _format_duration_ms(item["latestDurationMs"])
    max_label = _format_duration_ms(item["maxDurationMs"])
    trend_pct = round(item["trendScore"] * 100)

    if kind == "threshold_exceeded":
        threshold_label = _format_duration_ms(threshold_ms or 5000)
        if item["runCount"] == 1:
            return f"Duration in the selected run was {latest_label}, above the {threshold_label} threshold."
        return (
            f"Average duration is {avg_label} with the latest run at {latest_label}, "
            f"crossing the {threshold_label} threshold in this scope."
        )
    if kind == "slowest_tests":
        if item["runCount"] == 1:
            return f"This was one of the slowest tests in the selected run at {latest_label}."
        return f"Average duration is {avg_label} across {scope_label.lower()}, peaking at {max_label}."
    if kind == "duration_increasing":
        return (
            f"Execution time trend is rising by {trend_pct}% across {scope_label.lower()}, "
            f"with the latest run at {latest_label} versus a {avg_label} average."
        )
    return (
        f"Performance is regressing: the latest run took {latest_label} versus a {avg_label} average, "
        f"with a {trend_pct}% slowdown trend."
    )


def _load_performance_items(conn, runs: list) -> list[dict]:
    from qalens.analyzers.predictor import _duration_trend

    if not runs:
        return []

    placeholders = ",".join("?" for _ in runs)
    run_ids = [run.run_id for run in runs]
    rows = conn.execute(
        f"""
        SELECT
            tc.canonical_name,
            tc.name,
            tc.status,
            tc.duration_ms,
            tc.suite,
            tc.owner,
            r.run_sequence
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        WHERE tc.duration_ms IS NOT NULL
          AND tc.run_id IN ({placeholders})
        ORDER BY tc.canonical_name ASC, r.run_sequence ASC
        """,
        run_ids,
    ).fetchall()

    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        key = row["canonical_name"] or row["name"]
        grouped[key].append(row)

    items: list[dict] = []
    for canonical_name, entries in grouped.items():
        durations = [float(entry["duration_ms"]) for entry in entries if entry["duration_ms"] is not None]
        if not durations:
            continue
        latest = entries[-1]
        items.append(
            {
                "canonicalName": canonical_name,
                "testName": latest["name"] or canonical_name,
                "suite": latest["suite"],
                "owner": latest["owner"],
                "currentStatus": latest["status"] or "unknown",
                "avgDurationMs": sum(durations) / len(durations),
                "latestDurationMs": float(latest["duration_ms"]),
                "maxDurationMs": max(durations),
                "trendScore": _duration_trend(durations),
                "runCount": len(durations),
                "recentDurationsMs": [int(round(value)) for value in durations[-6:]],
            }
        )
    return items


def _build_performance_timing_result(
    *,
    kind: str,
    scope_label: str,
    run_count: int,
    latest_run_label: str | None,
    threshold_ms: int | None,
    items: list[dict],
) -> dict:
    threshold = threshold_ms or 5000

    if kind == "threshold_exceeded":
        filtered = [
            item for item in items
            if (
                item["latestDurationMs"] >= threshold
                if run_count == 1
                else max(item["avgDurationMs"], item["latestDurationMs"]) >= threshold
            )
        ]
        filtered.sort(
            key=lambda item: (
                -max(item["latestDurationMs"], item["avgDurationMs"]),
                -item["trendScore"],
                str(item["testName"]).lower(),
            )
        )
    elif kind == "duration_increasing":
        filtered = [
            item for item in items
            if item["runCount"] >= 3 and item["trendScore"] >= 0.05
        ]
        filtered.sort(key=lambda item: (-item["trendScore"], -item["latestDurationMs"], str(item["testName"]).lower()))
    elif kind == "performance_regressions":
        filtered = [
            item for item in items
            if item["runCount"] >= 3
            and item["trendScore"] >= 0.08
            and item["latestDurationMs"] >= item["avgDurationMs"] * 1.1
        ]
        filtered.sort(
            key=lambda item: (
                -(item["trendScore"] * item["latestDurationMs"]),
                -item["latestDurationMs"],
                str(item["testName"]).lower(),
            )
        )
    else:
        filtered = list(items)
        filtered.sort(
            key=lambda item: (
                -(item["latestDurationMs"] if run_count == 1 else item["avgDurationMs"]),
                -item["maxDurationMs"],
                str(item["testName"]).lower(),
            )
        )

    display_items = filtered[:20]
    avg_duration_ms = (sum(item["avgDurationMs"] for item in filtered) / len(filtered)) if filtered else 0.0
    slowest_duration_ms = max((item["maxDurationMs"] for item in filtered), default=0.0)
    highest_trend_score = max((item["trendScore"] for item in filtered), default=0.0)
    currently_slow = sum(1 for item in filtered if item["latestDurationMs"] >= threshold)
    summary_matches = len(display_items) if kind == "slowest_tests" else len(filtered)

    return {
        "type": "performance_timing",
        "title": _performance_title(kind),
        "subtitle": f"Execution-time analysis across {scope_label.lower()}.",
        "scope": {
            "label": scope_label,
            "runCount": run_count,
            "latestRun": latest_run_label,
            "totalEvaluated": len(items),
        },
        "query": {
            "kind": kind,
            "label": _performance_query_label(kind, threshold_ms),
            "thresholdMs": threshold_ms,
        },
        "summary": {
            "matches": summary_matches,
            "avgDurationMs": avg_duration_ms,
            "slowestDurationMs": slowest_duration_ms,
            "highestTrendScore": highest_trend_score,
            "currentlySlow": currently_slow,
        },
        "tests": [
            {
                "rank": index + 1,
                "testName": item["testName"],
                "canonicalName": item["canonicalName"],
                "suite": item["suite"],
                "owner": item["owner"],
                "currentStatus": item["currentStatus"],
                "avgDurationMs": round(item["avgDurationMs"]),
                "latestDurationMs": round(item["latestDurationMs"]),
                "maxDurationMs": round(item["maxDurationMs"]),
                "trendScore": round(item["trendScore"], 4),
                "slowRunCount": sum(1 for duration in item["recentDurationsMs"] if duration >= threshold),
                "runCount": item["runCount"],
                "recentDurationsMs": item["recentDurationsMs"],
                "primaryReason": _performance_primary_reason(item, kind, scope_label, threshold_ms),
                "tier": _performance_row_tier(item, kind, threshold_ms),
            }
            for index, item in enumerate(display_items)
        ],
    }


def _performance_timing_summary(result: dict) -> str:
    tests = result["tests"]
    if not tests:
        return "\n".join([
            f'I did not find any tests matching "{result["query"]["label"].lower()}" across {result["scope"]["label"].lower()}.',
            "",
            "The Results workspace still shows the timing scope and summary counts.",
        ])

    if result["query"]["kind"] == "slowest_tests":
        lines = [
            f'I ranked the top {result["summary"]["matches"]} slowest test{"s" if result["summary"]["matches"] != 1 else ""} out of {result["scope"]["totalEvaluated"]} evaluated across {result["scope"]["label"].lower()}.',
            "",
            "Top timing hotspots:",
            *[
                f'- {item["testName"]} — latest {_format_duration_ms(item["latestDurationMs"])} · average {_format_duration_ms(item["avgDurationMs"])}'
                for item in tests[:5]
            ],
            "",
            "The detailed timing breakdown is shown in the Results workspace.",
        ]
        return "\n".join(lines)

    lines = [
        f'I found {result["summary"]["matches"]} test{"s" if result["summary"]["matches"] != 1 else ""} for {result["query"]["label"].lower()} across {result["scope"]["label"].lower()}.',
        "",
        "Top timing hotspots:",
        *[
            f'- {item["testName"]} — latest {_format_duration_ms(item["latestDurationMs"])} · average {_format_duration_ms(item["avgDurationMs"])}'
            for item in tests[:5]
        ],
        "",
        "The detailed timing breakdown is shown in the Results workspace.",
    ]
    return "\n".join(lines)


def _performance_timing_fact_bundle(result: dict) -> dict[str, object]:
    return {
        "type": "performance_timing",
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "total_evaluated": result["scope"]["totalEvaluated"],
        "query_kind": result["query"]["kind"],
        "query_label": result["query"]["label"],
        "threshold_ms": result["query"].get("thresholdMs"),
        "matches": result["summary"]["matches"],
        "avg_duration_ms": round(result["summary"]["avgDurationMs"]),
        "slowest_duration_ms": round(result["summary"]["slowestDurationMs"]),
        "highest_trend_pct": round(result["summary"]["highestTrendScore"] * 100),
        "currently_slow": result["summary"]["currentlySlow"],
        "top_tests": [
            {
                "name": item["testName"],
                "latest_duration_ms": item["latestDurationMs"],
                "avg_duration_ms": item["avgDurationMs"],
                "trend_pct": round(item["trendScore"] * 100),
                "driver": item["primaryReason"],
            }
            for item in result["tests"][:5]
        ],
    }


def _finalize_performance_timing_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    normalized = answer.strip()
    lowered = normalized.lower()

    if not (lowered.startswith("across ") or lowered.startswith("in ")):
        normalized = f"Across {scope_label}, {normalized[:1].lower() + normalized[1:] if normalized else ''}".strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed timing breakdown is shown in the Results workspace."

    return normalized


def _history_state_from_compare_cell(state: str | None) -> str:
    normalized = (state or "").lower()
    if normalized in {"passed", "pass"}:
        return "PASS"
    if normalized in {"failed", "broken", "fail"}:
        return "FAIL"
    if normalized == "skipped":
        return "SKIP"
    return "UNKNOWN"


def _new_failures_tier(classification: str, pass_rate: float) -> str:
    normalized = classification.lower()
    if pass_rate <= 0.35:
        return "HIGH"
    if "broken" in normalized or "flaky" in normalized:
        return "MEDIUM"
    return "LOW"


def _new_failures_primary_reason(
    *,
    latest_run: str,
    previous_run: str,
    error_type: str | None,
) -> str:
    if error_type:
        return f"Passed or was not failing in {previous_run}, then failed in {latest_run} with {error_type}."
    return f"Passed or was not failing in {previous_run}, then failed in {latest_run}."


def _build_new_failures_introduced_result(
    comparison: dict,
    *,
    scope_label: str,
) -> dict:
    runs = comparison.get("runs", [])
    rows = comparison.get("rows", [])
    latest_run = runs[-1]["display_name"] if runs else None
    previous_run = runs[-2]["display_name"] if len(runs) >= 2 else None

    items: list[dict] = []
    for row in rows:
        cells = row.get("cells", [])
        if len(cells) < 2:
            continue
        latest = cells[-1]
        prior = cells[-2]
        latest_state = (latest.get("state") or "").lower()
        prior_state = (prior.get("state") or "").lower()
        latest_failed = latest_state in {"failed", "broken"}
        prior_failed = prior_state in {"failed", "broken"}
        if not latest_failed or prior_failed:
            continue

        classification = row.get("health", {}).get("classification", "unknown")
        pass_rate = float(row.get("health", {}).get("pass_rate", 0.0) or 0.0)
        error_type = latest.get("error_type")
        error_label = error_type.split(".")[-1] if error_type else None
        message = latest.get("message")
        items.append({
            "testName": row.get("display_name") or row.get("canonical_name") or "Unknown test",
            "canonicalName": row.get("canonical_name"),
            "suite": row.get("suite"),
            "owner": row.get("owner"),
            "classification": classification,
            "passRate": round(pass_rate, 4),
            "previousStatus": prior_state or "unknown",
            "latestStatus": latest_state or "unknown",
            "errorType": error_label,
            "message": message.split("\n")[0][:180] if message else None,
            "history": [_history_state_from_compare_cell(cell.get("state")) for cell in cells[-10:]],
            "primaryReason": _new_failures_primary_reason(
                latest_run=latest_run or "the latest run",
                previous_run=previous_run or "the prior run",
                error_type=error_label,
            ),
            "tier": _new_failures_tier(classification, pass_rate),
        })

    def sort_key(item: dict) -> tuple:
        tier_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(item["tier"], 3)
        return (
            tier_rank,
            item["passRate"],
            str(item["suite"] or "").lower(),
            str(item["testName"]).lower(),
        )

    items.sort(key=sort_key)
    display_items = items[:25]

    affected_suites = len({item["suite"] for item in items if item.get("suite")})
    affected_owners = len({item["owner"] for item in items if item.get("owner")})
    flaky_among_new = sum(1 for item in items if "flaky" in item["classification"].lower())

    return {
        "type": "new_failures_introduced",
        "title": "New failures introduced",
        "subtitle": (
            f"Tests that were not failing before and are failing in {latest_run} compared with {previous_run}."
            if latest_run and previous_run
            else "Tests that were not failing before and are failing in the latest run."
        ),
        "scope": {
            "label": scope_label,
            "runCount": len(runs),
            "latestRun": latest_run,
            "previousRun": previous_run,
            "totalEvaluated": comparison.get("summary", {}).get("unique_tests", 0),
        },
        "summary": {
            "newFailures": len(items),
            "affectedSuites": affected_suites,
            "affectedOwners": affected_owners,
            "flakyAmongNew": flaky_among_new,
        },
        "tests": [
            {
                "rank": index + 1,
                **item,
            }
            for index, item in enumerate(display_items)
        ],
    }


def _new_failures_introduced_summary(result: dict) -> str:
    health = "Regressed" if int(result["summary"]["newFailures"]) > 0 else "Stable"
    scope_label = str(result["scope"].get("label") or "selected run window")
    run_count = int(result["scope"].get("runCount") or 0)
    latest_run = result["scope"].get("latestRun") or "Latest run"
    previous_run = result["scope"].get("previousRun") or "Previous run"
    tests = result["tests"]
    prefix = (
        f"Across {scope_label.lower()}, the latest transition ({latest_run} vs {previous_run})"
        if run_count > 2
        else f"{latest_run} vs {previous_run}"
    )
    if not tests:
        return (
            f"{prefix}. "
            f"Build Health: {health}. "
            "No newly introduced failures were found in this transition. "
            "The detailed regression breakdown is shown in the Results workspace."
        )

    top_names = [item["testName"] for item in tests[:2]]
    names_sentence = f" Primary risks include {' and '.join(top_names)}." if top_names else ""
    return (
        f"{prefix}. "
        f"Build Health: {health}. "
        f"The latest transition introduced {result['summary']['newFailures']} new failure{'s' if result['summary']['newFailures'] != 1 else ''} "
        f"across {result['summary']['affectedSuites']} suite{'s' if result['summary']['affectedSuites'] != 1 else ''} "
        f"and {result['summary']['affectedOwners']} owner{'s' if result['summary']['affectedOwners'] != 1 else ''}, "
        f"with {result['summary']['flakyAmongNew']} of those tests already classified as flaky."
        f"{names_sentence} "
        "The detailed regression breakdown is shown in the Results workspace."
    )


def _new_failures_introduced_fact_bundle(result: dict) -> dict[str, object]:
    return {
        "type": "new_failures_introduced",
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "latest_run": result["scope"].get("latestRun"),
        "previous_run": result["scope"].get("previousRun"),
        "build_health": "Regressed" if int(result["summary"]["newFailures"]) > 0 else "Stable",
        "total_evaluated": result["scope"]["totalEvaluated"],
        "new_failures": result["summary"]["newFailures"],
        "affected_suites": result["summary"]["affectedSuites"],
        "affected_owners": result["summary"]["affectedOwners"],
        "flaky_among_new": result["summary"]["flakyAmongNew"],
        "top_tests": [
            {
                "name": item["testName"],
                "suite": item.get("suite"),
                "owner": item.get("owner"),
                "driver": item["primaryReason"],
            }
            for item in result["tests"][:5]
        ],
    }


def _finalize_new_failures_introduced_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    normalized = answer.strip()
    lowered = normalized.lower()
    run_count = int(fact_bundle.get("run_count") or 0)
    scope_label = str(fact_bundle.get("scope_label") or "selected run window").lower()

    if not (
        lowered.startswith("across ")
        or lowered.startswith("in ")
        or lowered.startswith("run #")
        or lowered.startswith("comparing ")
    ):
        latest_run = str(fact_bundle.get("latest_run") or "Latest run")
        previous_run = str(fact_bundle.get("previous_run") or "Previous run")
        prefix = (
            f"Across {scope_label}, the latest transition ({latest_run} vs {previous_run})."
            if run_count > 2
            else f"{latest_run} vs {previous_run}."
        )
        normalized = f"{prefix} {normalized}".strip()
        lowered = normalized.lower()

    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed regression breakdown is shown in the Results workspace."

    return normalized


def _build_run_comparison_result(comparison: dict, *, scope_label: str) -> dict:
    runs = comparison.get("runs", [])
    rows = comparison.get("rows", [])
    latest_run = runs[-1]["display_name"] if runs else None
    baseline_run = runs[-2]["display_name"] if len(runs) >= 2 else None

    changed: list[dict] = []
    new_failures = recovered = still_failing = unchanged = 0
    for row in rows:
        cells = row.get("cells", [])
        if len(cells) < 2:
            continue
        baseline = cells[-2]
        latest = cells[-1]
        baseline_state = (baseline.get("state") or "").lower()
        latest_state = (latest.get("state") or "").lower()
        baseline_failed = baseline_state in {"failed", "broken"}
        latest_failed = latest_state in {"failed", "broken"}

        if latest_failed and not baseline_failed:
            delta = "new_failure"
            new_failures += 1
        elif baseline_failed and not latest_failed:
            delta = "recovered"
            recovered += 1
        elif baseline_failed and latest_failed:
            delta = "still_failing"
            still_failing += 1
        else:
            delta = "unchanged"
            unchanged += 1

        if delta == "unchanged":
            continue

        latest_message = latest.get("message")
        latest_error = latest.get("error_type")
        error_label = latest_error.split(".")[-1] if latest_error else None
        classification = row.get("health", {}).get("classification", "unknown")
        pass_rate = float(row.get("health", {}).get("pass_rate", 0.0) or 0.0)
        if delta == "new_failure":
            reason = f"Became failing in {latest_run} after not failing in {baseline_run}."
            tier = "HIGH"
        elif delta == "recovered":
            reason = f"Recovered in {latest_run} after failing in {baseline_run}."
            tier = "LOW"
        else:
            reason = f"Failed in both {baseline_run} and {latest_run}."
            tier = "MEDIUM"

        changed.append({
            "testName": row.get("display_name") or row.get("canonical_name") or "Unknown test",
            "canonicalName": row.get("canonical_name"),
            "suite": row.get("suite"),
            "owner": row.get("owner"),
            "classification": classification,
            "passRate": round(pass_rate, 4),
            "baselineStatus": baseline_state or "unknown",
            "latestStatus": latest_state or "unknown",
            "delta": delta,
            "errorType": error_label,
            "message": latest_message.split("\n")[0][:180] if latest_message else None,
            "history": [_history_state_from_compare_cell(cell.get("state")) for cell in cells[-10:]],
            "primaryReason": reason,
            "tier": tier,
        })

    order = {"new_failure": 0, "still_failing": 1, "recovered": 2}
    changed.sort(key=lambda item: (order[item["delta"]], item["passRate"], str(item["testName"]).lower()))
    display = changed[:25]

    return {
        "type": "run_comparison",
        "title": f"Comparing {baseline_run or 'baseline'} and {latest_run or 'latest run'}",
        "subtitle": (
            f"Failure changes between {baseline_run} and {latest_run}."
            if baseline_run and latest_run
            else "Failure changes between the selected runs."
        ),
        "scope": {
            "label": scope_label,
            "baselineRun": baseline_run,
            "latestRun": latest_run,
            "runCount": len(runs),
            "totalEvaluated": comparison.get("summary", {}).get("unique_tests", 0),
        },
        "summary": {
            "newFailures": new_failures,
            "recovered": recovered,
            "stillFailing": still_failing,
            "changedTests": len(changed),
            "baselineFailed": sum(1 for row in rows if len(row.get("cells", [])) >= 2 and (row["cells"][-2].get("state") or "").lower() in {"failed", "broken"}),
            "latestFailed": sum(1 for row in rows if row.get("cells") and (row["cells"][-1].get("state") or "").lower() in {"failed", "broken"}),
        },
        "tests": [
            {
                "rank": index + 1,
                **item,
            }
            for index, item in enumerate(display)
        ],
    }


def _run_comparison_health_label(result: dict) -> str:
    new_failures = int(result["summary"]["newFailures"])
    recovered = int(result["summary"]["recovered"])
    latest_failed = int(result["summary"]["latestFailed"])
    baseline_failed = int(result["summary"]["baselineFailed"])

    if new_failures > recovered or latest_failed > baseline_failed:
        return "Regressed"
    if recovered > new_failures or latest_failed < baseline_failed:
        return "Improved"
    return "Stable"


def _run_comparison_summary(result: dict) -> str:
    health = _run_comparison_health_label(result)
    latest_run = result["scope"].get("latestRun") or "Latest run"
    baseline_run = result["scope"].get("baselineRun") or "Baseline run"
    if not result["tests"]:
        return (
            f"{latest_run} vs {baseline_run}. "
            f"Build Health: {health}. "
            f"I did not find any failure-state changes between {baseline_run} and {latest_run}. "
            "The detailed comparison is shown in the Results workspace."
        )
    return (
        f"{latest_run} vs {baseline_run}. "
        f"Build Health: {health}. "
        f"{latest_run} shows {result['summary']['newFailures']} new failures, {result['summary']['recovered']} recovered tests, "
        f"and {result['summary']['stillFailing']} tests still failing. "
        "The detailed comparison is shown in the Results workspace."
    )


def _run_comparison_fact_bundle(result: dict) -> dict[str, object]:
    return {
        "type": "run_comparison",
        "scope_label": result["scope"]["label"],
        "baseline_run": result["scope"].get("baselineRun"),
        "latest_run": result["scope"].get("latestRun"),
        "build_health": _run_comparison_health_label(result),
        "total_evaluated": result["scope"]["totalEvaluated"],
        "new_failures": result["summary"]["newFailures"],
        "recovered": result["summary"]["recovered"],
        "still_failing": result["summary"]["stillFailing"],
        "changed_tests": result["summary"]["changedTests"],
        "top_tests": [
            {
                "name": item["testName"],
                "delta": item["delta"],
                "driver": item["primaryReason"],
            }
            for item in result["tests"][:5]
        ],
    }


def _finalize_run_comparison_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    normalized = answer.strip()
    lowered = normalized.lower()
    if not (
        lowered.startswith("across ")
        or lowered.startswith("between ")
        or lowered.startswith("in ")
        or lowered.startswith("run #")
        or lowered.startswith("comparing ")
    ):
        latest_run = str(fact_bundle.get("latest_run") or "Latest run")
        baseline_run = str(fact_bundle.get("baseline_run") or "Baseline run")
        normalized = f"{latest_run} vs {baseline_run}. {normalized}".strip()
        lowered = normalized.lower()
    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed comparison is shown in the Results workspace."
    return normalized


def _failure_trend_direction(*, baseline_failed: int, latest_failed: int) -> str:
    if latest_failed > baseline_failed:
        return "INCREASING"
    if latest_failed < baseline_failed:
        return "DECREASING"
    return "STABLE"


def _build_failure_trend_result(comparison: dict, *, scope_label: str) -> dict:
    runs = comparison.get("runs", [])
    run_rows: list[dict] = []
    for index, run in enumerate(runs):
        status = run.get("status_summary") or {}
        failed = int(status.get("failed") or 0)
        passed = int(status.get("passed") or 0)
        skipped = int(status.get("skipped") or 0)
        total = int(status.get("total") or 0)
        run_rows.append({
            "rank": index + 1,
            "runLabel": run.get("display_name") or f"Run #{run.get('run_sequence')}",
            "failed": failed,
            "passed": passed,
            "skipped": skipped,
            "total": total,
            "passRate": (passed / total) if total else 0.0,
        })

    baseline_run = run_rows[0]["runLabel"] if run_rows else None
    latest_run = run_rows[-1]["runLabel"] if run_rows else None
    baseline_failed = run_rows[0]["failed"] if run_rows else 0
    latest_failed = run_rows[-1]["failed"] if run_rows else 0
    peak = max(run_rows, key=lambda item: item["failed"], default=None)
    direction = _failure_trend_direction(baseline_failed=baseline_failed, latest_failed=latest_failed)

    return {
        "type": "failure_trend",
        "title": "Failure trend across runs",
        "subtitle": f"Run-by-run failure counts across {scope_label.lower()}.",
        "scope": {
            "label": scope_label,
            "runCount": len(run_rows),
            "totalEvaluated": int(comparison.get("summary", {}).get("unique_tests") or 0),
            "baselineRun": baseline_run,
            "latestRun": latest_run,
        },
        "summary": {
            "direction": direction,
            "baselineFailed": baseline_failed,
            "latestFailed": latest_failed,
            "deltaFailed": latest_failed - baseline_failed,
            "peakFailed": int(peak["failed"]) if peak else 0,
            "peakRun": peak["runLabel"] if peak else None,
            "latestNewFailures": int(comparison.get("summary", {}).get("new_failures_latest") or 0),
            "latestRecovered": int(comparison.get("summary", {}).get("fixed_latest") or 0),
        },
        "runs": [
            {
                **item,
                "isPeak": bool(peak and item["runLabel"] == peak["runLabel"] and item["failed"] == peak["failed"]),
            }
            for item in run_rows
        ],
    }


def _failure_trend_summary(result: dict) -> str:
    summary = result["summary"]
    baseline_run = result["scope"].get("baselineRun") or "the baseline run"
    latest_run = result["scope"].get("latestRun") or "the latest run"
    direction = str(summary["direction"]).lower()
    return (
        f"Across {result['scope']['label'].lower()}, failures are {direction}. "
        f"{latest_run} shows {summary['latestFailed']} failures versus {summary['baselineFailed']} in {baseline_run}, "
        f"with a peak of {summary['peakFailed']} failures in {summary['peakRun'] or 'the busiest run'}. "
        "The detailed run-by-run failure trend is shown in the Results workspace."
    )


def _failure_trend_fact_bundle(result: dict) -> dict[str, object]:
    return {
        "type": "failure_trend",
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "baseline_run": result["scope"].get("baselineRun"),
        "latest_run": result["scope"].get("latestRun"),
        "direction": result["summary"]["direction"],
        "baseline_failed": result["summary"]["baselineFailed"],
        "latest_failed": result["summary"]["latestFailed"],
        "delta_failed": result["summary"]["deltaFailed"],
        "peak_failed": result["summary"]["peakFailed"],
        "peak_run": result["summary"].get("peakRun"),
        "latest_new_failures": result["summary"]["latestNewFailures"],
        "latest_recovered": result["summary"]["latestRecovered"],
        "runs": [
            {
                "run_label": item["runLabel"],
                "failed": item["failed"],
                "pass_rate_pct": round(item["passRate"] * 100),
            }
            for item in result["runs"][:10]
        ],
    }


def _finalize_failure_trend_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    normalized = answer.strip()
    lowered = normalized.lower()
    scope_label = str(fact_bundle.get("scope_label") or "selected run window").lower()
    if not (
        lowered.startswith("across ")
        or lowered.startswith("in ")
        or lowered.startswith("between ")
    ):
        normalized = f"Across {scope_label}, {normalized[:1].lower() + normalized[1:] if normalized else ''}".strip()
        lowered = normalized.lower()
    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed run-by-run failure trend is shown in the Results workspace."
    return normalized


def _trend_query_kind(question: str) -> str | None:
    normalized = _normalize_text(question)
    lowered = question.lower()
    has_low_pass_rate_phrase = bool(
        re.search(r"\bpass\s+(?:rate|percentage)\s+(?:below|under|less than)\s+\d+", normalized)
        or re.search(r"\bpass\s+(?:rate|percentage)\s*(?:<|<=)\s*\d+%?\b", lowered)
        or re.search(r"\bbelow\s+\d+%?\b", normalized)
        or re.search(r"\bunders?\s+\d+%?\b", normalized)
    )
    has_high_pass_rate_phrase = bool(
        re.search(r"\bpass\s+(?:rate|percentage)\s+(?:above|over|greater than|more than)\s+\d+", normalized)
        or re.search(r"\bpass\s+(?:rate|percentage)\s*(?:>|>=)\s*\d+%?\b", lowered)
    )
    has_failure_count_phrase = bool(
        re.search(r"\bfailed?\s+(?:more than|over|above)\s+\d+\s+times?\b", normalized)
        or re.search(r"\bmore than\s+\d+\s+failures?\b", normalized)
        or re.search(r"\bmore than\s+\d+\s+times\b", normalized)
    )

    if "flaky" in normalized:
        return "flaky_tests"

    if has_low_pass_rate_phrase and has_failure_count_phrase:
        return "low_pass_rate_and_failure_count"

    if has_low_pass_rate_phrase:
        return "low_pass_rate"

    if has_high_pass_rate_phrase:
        return "high_pass_rate"

    if any(
        phrase in normalized
        for phrase in (
            "stability trending",
            "stability trend",
            "test stability trend",
            "test stability over time",
            "stability over time",
            "quality trend",
            "quality over time",
            "reliability trend",
            "reliability over time",
        )
    ):
        return "unstable_tests"

    if any(
        phrase in normalized
        for phrase in (
            "failed in every run",
            "failed every run",
            "fail in every run",
            "fail every run",
            "always failed",
            "always failing",
            "never passed",
        )
    ):
        return "failed_every_run"

    if any(
        phrase in normalized
        for phrase in (
            "never failed",
            "never fail",
            "never failing",
            "always passed",
            "always passing",
            "most reliable test",
            "most reliable tests",
            "most stable test",
            "most stable tests",
        )
    ):
        if any(phrase in normalized for phrase in ("most reliable", "most stable")):
            return "high_pass_rate"
        return "never_failed"

    if any(
        phrase in normalized
        for phrase in (
            "highest failure frequency",
            "failed most often",
            "most failures",
        )
    ):
        return "highest_failure_frequency"

    if any(
        phrase in normalized
        for phrase in (
            "unstable tests",
            "identify unstable tests",
            "problematic tests",
            "problem tests",
            "troubled tests",
            "trouble tests",
            "tests are problematic",
            "tests look problematic",
            "tests need attention",
            "tests that need attention",
        )
    ):
        return "unstable_tests"

    if "intermittent" in normalized or "failed intermittently" in normalized:
        return "intermittent_failures"

    if any(
        phrase in normalized
        for phrase in (
            "failed after previously passing",
            "failed after previously passed",
            "previously passing",
            "previously passed",
        )
    ):
        return "failed_after_passing"

    if any(
        phrase in normalized
        for phrase in (
            "improved over time",
            "which tests improved",
            "which tests recovered",
            "tests recovered",
            "show recovered tests",
            "show me recovered tests",
            "recovered tests",
            "tests improved over time",
            "recovered after failures",
            "recovered over time",
        )
    ):
        return "improved_over_time"

    return None


def _trend_threshold(question: str, default_threshold: float = 0.60) -> float:
    lowered = question.lower()
    patterns = (
        r"pass\s+(?:rate|percentage)\s+(?:below|under|less than|above|over|greater than|more than)\s+(\d{1,3})\s*%?",
        r"pass\s+(?:rate|percentage)\s*(?:<|<=|>|>=)\s*(\d{1,3})\s*%?",
        r"\bbelow\s+(\d{1,3})\s*%?\b",
        r"\bunders?\s+(\d{1,3})\s*%?\b",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            break
    if not match:
        return default_threshold
    try:
        value = int(match.group(1))
    except ValueError:
        return default_threshold
    return max(0.0, min(1.0, value / 100))


def _trend_fail_count_threshold(question: str, default_threshold: int = 3) -> int:
    normalized = _normalize_text(question)
    patterns = (
        r"\bfailed?\s+(?:more than|over|above)\s+(\d+)\s+times?\b",
        r"\bmore than\s+(\d+)\s+failures?\b",
        r"\bmore than\s+(\d+)\s+times\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        try:
            return max(0, int(match.group(1)))
        except ValueError:
            continue
    return default_threshold


def _trend_scope(question: str, available_runs: int) -> tuple[int, str, bool, bool]:
    normalized = _normalize_text(question)
    if any(phrase in normalized for phrase in ("across all runs", "all runs", "across runs", "long term", "long term stability")):
        return max(available_runs, 1), "All recorded runs", False, False

    if any(phrase in normalized for phrase in ("latest run", "last run", "most recent run", "current run")):
        return 1, "Latest run", False, False

    match = re.search(r"\blast\s+(\d+)\s+runs?\b", normalized)
    if match:
        try:
            count = max(1, int(match.group(1)))
        except ValueError:
            count = 10
        return count, f"Last {count} runs", False, False

    default_count = min(max(available_runs, 1), 10)
    return default_count, f"Last {default_count} runs", True, True


def _trend_classification_label(value) -> str:
    normalized = str(getattr(value, "value", value or "")).strip().lower()
    mapping = {
        "flaky": "Flaky",
        "consistently_broken": "Broken",
        "stable": "Stable",
        "consistent": "Consistent",
        "insufficient_data": "Insufficient data",
    }
    return mapping.get(normalized, normalized.replace("_", " ").title() or "Unknown")


def _trend_row_tier(result, kind: str) -> str:
    classification = str(getattr(result.classification, "value", result.classification)).lower()
    if classification == "consistently_broken":
        return "HIGH"
    if classification == "flaky":
        return "HIGH" if result.flip_score >= 0.6 else "MEDIUM"
    if kind == "low_pass_rate":
        return "HIGH" if result.pass_rate <= 0.4 else "MEDIUM"
    if kind == "low_pass_rate_and_failure_count":
        return "HIGH" if result.pass_rate <= 0.4 and result.fail_count >= 5 else "MEDIUM"
    if kind == "high_pass_rate":
        return "LOW" if result.pass_rate >= 0.9 else "MEDIUM"
    if kind == "highest_failure_frequency":
        return "HIGH" if result.fail_count >= max(3, result.run_count // 2) else "MEDIUM"
    if kind == "failed_every_run":
        return "HIGH"
    if kind == "never_failed":
        return "LOW"
    if kind == "failed_after_passing":
        return "MEDIUM" if result.current_streak < 0 else "LOW"
    if kind == "improved_over_time":
        return "LOW" if result.current_streak >= 2 else "MEDIUM"
    return "LOW"


def _trend_primary_reason(result, kind: str, scope_label: str) -> str:
    if kind == "flaky_tests":
        return (
            f"High volatility with a {round(result.flip_score * 100)}% flip score "
            f"across {scope_label.lower()}."
        )
    if kind == "low_pass_rate":
        return (
            f"Pass rate is only {round(result.pass_rate * 100)}% with "
            f"{result.fail_count} failure{'s' if result.fail_count != 1 else ''} in scope."
        )
    if kind == "low_pass_rate_and_failure_count":
        return (
            f"Pass rate is only {round(result.pass_rate * 100)}% with "
            f"{result.fail_count} failure{'s' if result.fail_count != 1 else ''} across {scope_label.lower()}."
        )
    if kind == "high_pass_rate":
        return (
            f"Pass rate is {round(result.pass_rate * 100)}% with only "
            f"{result.fail_count} failure{'s' if result.fail_count != 1 else ''} across {scope_label.lower()}."
        )
    if kind == "highest_failure_frequency":
        return (
            f"Failed in {result.fail_count} of {result.run_count} run"
            f"{'' if result.run_count == 1 else 's'} in this scope."
        )
    if kind == "failed_every_run":
        return (
            f"Failed in every observed run in this scope "
            f"({result.fail_count}/{result.run_count} failures)."
        )
    if kind == "never_failed":
        return (
            f"Never failed across {result.run_count} observed run"
            f"{'' if result.run_count == 1 else 's'} in this scope."
        )
    if kind == "unstable_tests":
        if str(getattr(result.classification, "value", result.classification)).lower() == "consistently_broken":
            return (
                f"Consistently broken with a {round(result.pass_rate * 100)}% pass rate "
                f"and a {abs(result.current_streak)}-run fail streak."
            )
        return (
            f"Unstable due to mixed pass/fail history and a {round(result.flip_score * 100)}% flip score."
        )
    if kind == "intermittent_failures":
        return (
            f"Alternates between pass and fail states, with {result.fail_count} failures after "
            f"{result.pass_count} passes in scope."
        )
    if kind == "failed_after_passing":
        return (
            f"Was passing earlier in the scope and is now on a {abs(result.current_streak)}-run fail streak."
            if result.current_streak < 0
            else "Previously passed in scope before failing later."
        )
    if kind == "improved_over_time":
        return (
            f"Recovered from earlier failures and is now on a {result.current_streak}-run pass streak."
            if result.current_streak > 0
            else "Recovered after failing earlier in the selected scope."
        )
    return f"Scored from QA Lens stability history across {scope_label.lower()}."


def _trend_query_label(
    kind: str,
    threshold: float | None = None,
    fail_count_threshold: int | None = None,
) -> str:
    if kind == "flaky_tests":
        return "Flaky tests"
    if kind == "low_pass_rate":
        pct = round((threshold or 0) * 100)
        return f"Tests with pass rate below {pct}%"
    if kind == "low_pass_rate_and_failure_count":
        pct = round((threshold or 0) * 100)
        count = fail_count_threshold if fail_count_threshold is not None else 3
        return f"Tests with pass rate below {pct}% and more than {count} failures"
    if kind == "high_pass_rate":
        pct = round((threshold or 0) * 100)
        return f"Tests with pass rate above {pct}%"
    if kind == "highest_failure_frequency":
        return "Highest failure frequency"
    if kind == "failed_every_run":
        return "Tests that failed in every run"
    if kind == "never_failed":
        return "Tests that never failed"
    if kind == "unstable_tests":
        return "Unstable tests"
    if kind == "intermittent_failures":
        return "Intermittent failures"
    if kind == "failed_after_passing":
        return "Failed after previously passing"
    if kind == "improved_over_time":
        return "Tests improved over time"
    return "Stability trends"


def _trend_title(kind: str) -> str:
    if kind == "flaky_tests":
        return "Flaky tests"
    if kind == "low_pass_rate":
        return "Low pass-rate tests"
    if kind == "low_pass_rate_and_failure_count":
        return "Tests with low pass rate and repeated failures"
    if kind == "high_pass_rate":
        return "Tests with high pass rate"
    if kind == "highest_failure_frequency":
        return "Tests with the highest failure frequency"
    if kind == "failed_every_run":
        return "Tests that failed in every run"
    if kind == "never_failed":
        return "Tests that never failed"
    if kind == "unstable_tests":
        return "Unstable tests"
    if kind == "intermittent_failures":
        return "Tests failing intermittently"
    if kind == "failed_after_passing":
        return "Tests that failed after previously passing"
    if kind == "improved_over_time":
        return "Tests that improved over time"
    return "Stability trends"


def _build_stability_trend_result(
    *,
    kind: str,
    scope_label: str,
    run_count: int,
    query_threshold: float | None,
    fail_count_threshold: int | None,
    results: list,
    total_evaluated: int,
    latest_run_label: str | None,
) -> dict:
    filtered: list = []
    for item in results:
        classification = str(getattr(item.classification, "value", item.classification)).lower()
        if kind == "flaky_tests":
            if classification == "flaky":
                filtered.append(item)
        elif kind == "low_pass_rate":
            if item.pass_rate < (query_threshold or 0.6):
                filtered.append(item)
        elif kind == "low_pass_rate_and_failure_count":
            if item.pass_rate < (query_threshold or 0.6) and item.fail_count > (fail_count_threshold or 3):
                filtered.append(item)
        elif kind == "high_pass_rate":
            if item.pass_rate > (query_threshold or 0.7):
                filtered.append(item)
        elif kind == "highest_failure_frequency":
            if item.fail_count > 0:
                filtered.append(item)
        elif kind == "failed_every_run":
            if item.run_count > 0 and item.fail_count == item.run_count:
                filtered.append(item)
        elif kind == "never_failed":
            if item.run_count > 0 and item.fail_count == 0:
                filtered.append(item)
        elif kind == "unstable_tests":
            if classification in {"flaky", "consistently_broken"}:
                filtered.append(item)
        elif kind == "intermittent_failures":
            if item.pass_count > 0 and item.fail_count > 0:
                filtered.append(item)
        elif kind == "failed_after_passing":
            if item.pass_count > 0 and item.current_streak < 0:
                filtered.append(item)
        elif kind == "improved_over_time":
            if item.fail_count > 0 and item.current_streak > 0:
                filtered.append(item)

    if kind == "highest_failure_frequency":
        filtered.sort(key=lambda item: (-item.fail_count, item.pass_rate, -item.flip_score, item.display_name.lower()))
    elif kind == "failed_every_run":
        filtered.sort(key=lambda item: (-item.run_count, item.display_name.lower()))
    elif kind == "never_failed":
        filtered.sort(key=lambda item: (-item.run_count, -item.pass_rate, item.flip_score, item.display_name.lower()))
    elif kind in {"low_pass_rate", "low_pass_rate_and_failure_count"}:
        filtered.sort(key=lambda item: (item.pass_rate, -item.fail_count, -item.flip_score, item.display_name.lower()))
    elif kind == "high_pass_rate":
        filtered.sort(key=lambda item: (-item.pass_rate, item.fail_count, item.flip_score, item.display_name.lower()))
    elif kind == "failed_after_passing":
        filtered.sort(key=lambda item: (item.current_streak, -item.fail_count, item.display_name.lower()))
    elif kind == "improved_over_time":
        filtered.sort(key=lambda item: (-item.current_streak, -item.pass_rate, -item.fail_count, item.display_name.lower()))
    elif kind == "unstable_tests":
        filtered.sort(
            key=lambda item: (
                0 if str(getattr(item.classification, "value", item.classification)).lower() == "consistently_broken" else 1,
                item.pass_rate,
                -item.flip_score,
                item.display_name.lower(),
            )
        )
    else:
        filtered.sort(key=lambda item: (-item.flip_score, item.pass_rate, item.display_name.lower()))

    display_limit = 25
    display_items = filtered[:display_limit]
    avg_pass_rate = (sum(item.pass_rate for item in filtered) / len(filtered)) if filtered else 0.0
    avg_flip_score = (sum(item.flip_score for item in filtered) / len(filtered)) if filtered else 0.0
    highest_fail_count = max((item.fail_count for item in filtered), default=0)
    actively_failing = sum(1 for item in filtered if item.current_streak < 0)

    return {
        "type": "stability_trend",
        "title": _trend_title(kind),
        "subtitle": f"QA Lens stability analysis across {scope_label.lower()}.",
        "scope": {
            "label": scope_label,
            "runCount": run_count,
            "latestRun": latest_run_label,
            "totalEvaluated": total_evaluated,
        },
        "query": {
            "kind": kind,
            "label": _trend_query_label(kind, query_threshold, fail_count_threshold),
            "threshold": query_threshold,
            "failureCountThreshold": fail_count_threshold,
        },
        "summary": {
            "matches": len(filtered),
            "avgPassRate": avg_pass_rate,
            "avgFlipScore": avg_flip_score,
            "highestFailCount": highest_fail_count,
            "activelyFailing": actively_failing,
        },
        "tests": [
            {
                "rank": index + 1,
                "testName": item.display_name,
                "canonicalName": item.canonical_name,
                "suite": getattr(item, "suite", None),
                "owner": item.owner,
                "classification": _trend_classification_label(item.classification),
                "passRate": item.pass_rate,
                "flipScore": item.flip_score,
                "failCount": item.fail_count,
                "passCount": item.pass_count,
                "runCount": item.run_count,
                "currentStreak": item.current_streak,
                "lastPassedRun": item.last_passed_seq,
                "lastFailedRun": item.last_failed_seq,
                "history": [_history_state(status) for status in item.history],
                "primaryReason": _trend_primary_reason(item, kind, scope_label),
                "tier": _trend_row_tier(item, kind),
            }
            for index, item in enumerate(display_items)
        ],
    }


def _stability_trend_summary(result: dict) -> str:
    tests = result["tests"]
    if not tests:
        return "\n".join([
            f'I did not find any tests matching "{result["query"]["label"].lower()}" across {result["scope"]["label"].lower()}.',
            "",
            "The Results workspace still shows the scope and summary counts.",
        ])

    lines = [
        f'I found {result["summary"]["matches"]} test{"s" if result["summary"]["matches"] != 1 else ""} for {result["query"]["label"].lower()} across {result["scope"]["label"].lower()}.',
        "",
        "Top matches:",
        *[
            f'- {item["testName"]} — {round(item["passRate"] * 100)}% pass rate · {item["classification"]}'
            for item in tests[:5]
        ],
        "",
        "The detailed stability breakdown is shown in the Results workspace.",
    ]
    return "\n".join(lines)


def _build_suite_failure_ranking_result(*, scope_label: str, run_count: int, test_cases: list) -> dict:
    suites: dict[str, dict] = {}
    test_buckets: dict[tuple[str, str], dict] = {}

    for tc in test_cases:
        suite_name = getattr(tc, "suite", None) or "Unknown suite"
        owner = getattr(tc, "owner", None) or "Unassigned"
        status = str(getattr(tc, "status", "") or "").lower()
        canonical = getattr(tc, "canonical_name", None) or getattr(tc, "name", "")
        name = getattr(tc, "name", None) or canonical or "Unknown test"
        failed = status in {"failed", "broken"}
        passed = status == "passed"

        suite = suites.setdefault(
            suite_name,
            {
                "suiteName": suite_name,
                "totalExecutions": 0,
                "failedExecutions": 0,
                "owners": set(),
                "tests": set(),
            },
        )
        suite["totalExecutions"] += 1
        suite["failedExecutions"] += 1 if failed else 0
        suite["owners"].add(owner)
        suite["tests"].add(canonical or name)

        key = (suite_name, canonical or name)
        test_bucket = test_buckets.setdefault(
            key,
            {
                "testName": name,
                "owner": owner,
                "failCount": 0,
                "passCount": 0,
                "runCount": 0,
                "currentStatus": status or "unknown",
            },
        )
        test_bucket["failCount"] += 1 if failed else 0
        test_bucket["passCount"] += 1 if passed else 0
        test_bucket["runCount"] += 1
        if test_bucket["runCount"] == 1:
            test_bucket["currentStatus"] = status or "unknown"
            test_bucket["owner"] = owner
            test_bucket["testName"] = name

    suite_tests: dict[str, list[dict]] = defaultdict(list)
    for (suite_name, _canonical), item in test_buckets.items():
        run_count_for_test = int(item["runCount"])
        pass_rate = float(item["passCount"]) / run_count_for_test if run_count_for_test else 0.0
        suite_tests[suite_name].append({
            "testName": item["testName"],
            "owner": item["owner"],
            "failCount": int(item["failCount"]),
            "passRate": pass_rate,
            "currentStatus": item["currentStatus"],
            "flaky": int(item["failCount"]) > 0 and int(item["passCount"]) > 0,
        })

    ranking = []
    for suite_name, suite in suites.items():
        tests = suite_tests.get(suite_name, [])
        failed_executions = int(suite["failedExecutions"])
        total_executions = int(suite["totalExecutions"])
        failing_tests = sum(1 for item in tests if item["currentStatus"] in {"failed", "broken"})
        flaky_tests = sum(1 for item in tests if item["flaky"])
        failure_rate = failed_executions / total_executions if total_executions else 0.0
        top_tests = sorted(
            tests,
            key=lambda item: (-item["failCount"], item["passRate"], str(item["testName"]).lower()),
        )[:5]
        ranking.append({
            "suiteName": suite_name,
            "totalTests": len(suite["tests"]),
            "failedExecutions": failed_executions,
            "totalExecutions": total_executions,
            "failureRate": failure_rate,
            "failingTests": failing_tests,
            "flakyTests": flaky_tests,
            "owners": sorted(str(owner) for owner in suite["owners"]),
            "topTests": top_tests,
            "primaryReason": (
                f"{suite_name} has {failed_executions} failed executions "
                f"across {total_executions} test executions ({round(failure_rate * 100)}% failure rate)."
            ),
        })

    ranking.sort(key=lambda item: (-item["failedExecutions"], -item["failingTests"], -item["failureRate"], item["suiteName"].lower()))
    ranked = [{"rank": index + 1, **item} for index, item in enumerate(ranking)]
    return {
        "type": "suite_failure_ranking",
        "title": "Suites causing the most failures",
        "subtitle": f"Suite-level failure concentration across {scope_label.lower()}.",
        "scope": {
            "label": scope_label,
            "runCount": run_count,
            "totalSuites": len(ranked),
            "totalTests": sum(item["totalTests"] for item in ranked),
        },
        "summary": {
            "topSuite": ranked[0]["suiteName"] if ranked else None,
            "totalFailures": sum(item["failedExecutions"] for item in ranked),
            "currentlyFailingSuites": sum(1 for item in ranked if item["failingTests"] > 0),
            "flakySuites": sum(1 for item in ranked if item["flakyTests"] > 0),
        },
        "ranking": ranked,
    }


def _suite_failure_ranking_summary(result: dict) -> str:
    ranking = result["ranking"]
    scope = result["scope"]["label"].lower()
    if not ranking:
        return f"I did not find suite-level failures across {scope}."
    leader = ranking[0]
    return (
        f"Across {scope}, {leader['suiteName']} is causing the most failures with "
        f"{leader['failedExecutions']} failed executions and a {round(leader['failureRate'] * 100)}% failure rate. "
        "The Results workspace shows the full suite ranking."
    )


def _suite_failure_ranking_fact_bundle(result: dict) -> dict[str, object]:
    return {
        "type": "suite_failure_ranking",
        "scope_label": result["scope"]["label"],
        "run_count": result["scope"]["runCount"],
        "total_suites": result["scope"]["totalSuites"],
        "total_tests": result["scope"]["totalTests"],
        "top_suite": result["summary"].get("topSuite"),
        "total_failures": result["summary"]["totalFailures"],
        "currently_failing_suites": result["summary"]["currentlyFailingSuites"],
        "flaky_suites": result["summary"]["flakySuites"],
        "top_suites": [
            {
                "rank": item["rank"],
                "suite_name": item["suiteName"],
                "failed_executions": item["failedExecutions"],
                "total_executions": item["totalExecutions"],
                "failure_rate_pct": round(item["failureRate"] * 100),
                "failing_tests": item["failingTests"],
                "flaky_tests": item["flakyTests"],
                "owners": item["owners"][:4],
                "top_tests": [
                    {
                        "name": test["testName"],
                        "owner": test.get("owner"),
                        "fail_count": test["failCount"],
                        "pass_rate_pct": round(test["passRate"] * 100),
                        "current_status": test["currentStatus"],
                    }
                    for test in item["topTests"][:3]
                ],
            }
            for item in result["ranking"][:5]
        ],
    }


def _finalize_suite_failure_ranking_narration(answer: str, fact_bundle: dict[str, object]) -> str:
    scope_label = str(fact_bundle.get("scope_label", "selected run window")).lower()
    normalized = answer.strip()
    lowered = normalized.lower()
    if not (lowered.startswith("across ") or lowered.startswith("in ")):
        normalized = f"Across {scope_label}, {normalized[:1].lower() + normalized[1:] if normalized else ''}".strip()
        lowered = normalized.lower()
    if "results workspace" not in lowered:
        normalized = f"{normalized} The detailed suite ranking is shown in the Results workspace."
    return normalized


_CAUSE_FAMILY_BY_CATEGORY = {
    "element_not_found": "UI / test script issue",
    "stale_element": "UI / test script issue",
    "timeout": "Flaky timing / synchronization",
    "assertion": "Product / backend defect",
    "null_pointer": "Product / backend defect",
    "network": "Environment / service issue",
    "authentication": "Environment / service issue",
    "infrastructure": "Environment / service issue",
    "test_data": "Test data issue",
    "permission": "Environment / service issue",
    "configuration": "Configuration issue",
    "unknown": "Needs manual investigation",
}

_CAUSE_TEXT_BY_CATEGORY = {
    "element_not_found": "Likely selector drift or UI structure change.",
    "stale_element": "Likely DOM refresh or stale element reuse in the test flow.",
    "timeout": "Likely synchronization, wait strategy, or slow dependency behavior.",
    "assertion": "Likely product behavior mismatch against the expected outcome.",
    "null_pointer": "Likely null or missing state in application or test setup.",
    "network": "Likely network, service connectivity, or downstream dependency issue.",
    "authentication": "Likely auth/session failure or expired credentials.",
    "infrastructure": "Likely environment, driver, or infrastructure instability.",
    "test_data": "Likely missing, stale, or invalid fixture/test data.",
    "permission": "Likely access control or permission configuration problem.",
    "configuration": "Likely environment configuration drift or missing settings.",
    "unknown": "No strong pattern matched; manual inspection is still required.",
}

_ACTION_TEXT_BY_CATEGORY = {
    "element_not_found": "Inspect selector drift, page markup changes, and render timing.",
    "stale_element": "Add or refine waits around DOM refresh points before reusing elements.",
    "timeout": "Inspect waits, retries, and any slow backend or async steps in this flow.",
    "assertion": "Compare expected vs actual values and verify product state transitions.",
    "null_pointer": "Check initialization, object lifecycle, and missing dependencies or state.",
    "network": "Check dependent service health, connectivity, and transient network errors.",
    "authentication": "Verify credentials, token/session expiry, and auth service health.",
    "infrastructure": "Compare environment and driver health against the last known-good setup.",
    "test_data": "Verify fixtures, seeded records, and reset/cleanup between runs.",
    "permission": "Inspect roles, grants, and service-to-service access permissions.",
    "configuration": "Diff config and environment variables against the passing baseline.",
    "unknown": "Inspect full stack traces and reproduce in isolation to narrow the cause.",
}


def _root_cause_query_kind(question: str) -> str | None:
    normalized = _normalize_text(question)
    if normalized.startswith("why ") and "failing" in normalized:
        return "test_frequency"
    if "ui changes or backend issues" in normalized or "ui changes or backend issue" in normalized:
        return "cause_mix"
    if "common failure patterns" in normalized or "failure patterns across runs" in normalized:
        return "common_patterns"
    if "causing most flaky failures" in normalized or "most flaky failures" in normalized:
        return "flaky_causes"
    if "root cause" in normalized or "what is causing" in normalized or "what caused" in normalized:
        return "root_cause_scope"
    return None


def _root_cause_target_test(question: str) -> str | None:
    backtick = re.search(r"`([^`]+)`", question)
    if backtick:
        candidate = backtick.group(1).strip()
        return candidate or None
    match = re.search(r"\bwhy(?:\s+is)?\s+(.+?)\s+failing\b", question, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" ?!.:,;\"'") or None
    return None


def _root_cause_scope(question: str, available_runs: int) -> tuple[int, str]:
    normalized = _normalize_text(question)
    if any(phrase in normalized for phrase in ("across all runs", "all runs", "across runs")):
        return max(available_runs, 1), "All recorded runs"
    if any(phrase in normalized for phrase in ("latest run", "last run", "most recent run", "current run")):
        return 1, "Latest run"
    run_number = _extract_run_number(question)
    if run_number is not None:
        return 1, f"Run #{run_number}"
    match = re.search(r"\blast\s+(\d+)\s+runs?\b", normalized)
    if match:
        try:
            count = max(1, int(match.group(1)))
        except ValueError:
            count = 10
        return count, f"Last {count} runs"
    count = min(max(available_runs, 1), 10)
    return count, f"Last {count} runs"


def _match_test_result_by_name(results: list, query: str):
    normalized = _normalize_text(query)
    if not normalized:
        return None
    exact = [
        item for item in results
        if _normalize_text(item.display_name) == normalized or _normalize_text(item.canonical_name) == normalized
    ]
    if exact:
        return exact[0]
    partial = [
        item for item in results
        if normalized in _normalize_text(item.display_name) or normalized in _normalize_text(item.canonical_name)
    ]
    return partial[0] if partial else None


def _root_cause_confidence(count: int, total: int) -> str:
    if total <= 0:
        return "Low"
    share = count / total
    if count >= 3 and share >= 0.4:
        return "High"
    if count >= 2 and share >= 0.2:
        return "Medium"
    return "Low"


def _root_cause_build_result(
    *,
    kind: str,
    scope_label: str,
    run_count: int,
    latest_run_label: str | None,
    target_test: str | None,
    failures: list[dict],
    total_tests_evaluated: int,
) -> dict:
    category_buckets: dict[str, dict] = {}
    for entry in failures:
        category = entry["category"]
        bucket = category_buckets.setdefault(category, {
            "category": category,
            "family": _CAUSE_FAMILY_BY_CATEGORY.get(category, "Needs manual investigation"),
            "count": 0,
            "tests": set(),
            "runs": set(),
            "sampleMessages": [],
            "topTests": {},
        })
        bucket["count"] += 1
        bucket["tests"].add(entry["canonicalName"] or entry["testName"])
        bucket["runs"].add(entry["runLabel"])
        if entry.get("message"):
            first_line = entry["message"]
            if first_line not in bucket["sampleMessages"] and len(bucket["sampleMessages"]) < 2:
                bucket["sampleMessages"].append(first_line)
        top_test_bucket = bucket["topTests"].setdefault(entry["testName"], {
            "testName": entry["testName"],
            "canonicalName": entry["canonicalName"],
            "count": 0,
        })
        top_test_bucket["count"] += 1

    ordered_categories = sorted(
        category_buckets.values(),
        key=lambda item: (-item["count"], -len(item["tests"]), item["category"]),
    )
    total_failures = len(failures)
    dominant = ordered_categories[0]["category"] if ordered_categories else None
    dominant_family = ordered_categories[0]["family"] if ordered_categories else None

    causes = []
    for index, bucket in enumerate(ordered_categories[:6]):
        top_tests = sorted(
            bucket["topTests"].values(),
            key=lambda item: (-item["count"], item["testName"]),
        )[:3]
        causes.append({
            "rank": index + 1,
            "category": bucket["category"],
            "family": bucket["family"],
            "count": bucket["count"],
            "affectedTests": len(bucket["tests"]),
            "affectedRuns": len(bucket["runs"]),
            "probableCause": _CAUSE_TEXT_BY_CATEGORY.get(bucket["category"], "Manual inspection required."),
            "recommendedAction": _ACTION_TEXT_BY_CATEGORY.get(bucket["category"], "Inspect the affected failures directly."),
            "confidence": _root_cause_confidence(bucket["count"], total_failures),
            "sampleMessages": bucket["sampleMessages"],
            "topTests": [
                {"testName": item["testName"], "canonicalName": item["canonicalName"], "count": item["count"]}
                for item in top_tests
            ],
        })

    return {
        "type": "root_cause_insight",
        "title": (
            f"Why {target_test} is failing frequently"
            if kind == "test_frequency" and target_test
            else "Failure root cause summary"
        ),
        "subtitle": f"Evidence-backed cause analysis across {scope_label.lower()}.",
        "scope": {
            "label": scope_label,
            "kind": kind,
            "runCount": run_count,
            "latestRun": latest_run_label,
            "targetTest": target_test,
            "totalTestsEvaluated": total_tests_evaluated,
        },
        "summary": {
            "totalFailures": total_failures,
            "affectedTests": len({entry["canonicalName"] or entry["testName"] for entry in failures}),
            "affectedRuns": len({entry["runLabel"] for entry in failures}),
            "dominantCategory": dominant,
            "dominantFamily": dominant_family,
        },
        "causes": causes,
    }


def _root_cause_summary(result: dict) -> str:
    if not result["causes"]:
        return "\n".join([
            f'I did not find enough failure evidence to explain the root cause across {result["scope"]["label"].lower()}.',
            "",
            "The Results workspace still shows the evaluated scope.",
        ])

    top = result["causes"][0]
    header = (
        f'I looked at why {result["scope"]["targetTest"]} is failing frequently across {result["scope"]["label"].lower()}.'
        if result["scope"].get("targetTest")
        else f'I analyzed the likely root causes across {result["scope"]["label"].lower()}.'
    )
    lines = [
        header,
        "",
        f"Strongest pattern: {top['family']} ({top['category'].replace('_', ' ')}) — {top['count']} failure match{'es' if top['count'] != 1 else ''}.",
        "",
        "Top cause groups:",
        *[
            f"- {item['family']} — {item['count']} failures across {item['affectedTests']} tests"
            for item in result["causes"][:3]
        ],
        "",
        "The detailed cause breakdown is shown in the Results workspace.",
    ]
    return "\n".join(lines)


def _load_known_owners(conn, *, project: str | None) -> list[str]:
    params: list[str] = []
    project_clause = ""
    if project:
        project_clause = "JOIN runs r ON r.run_id = tc.run_id WHERE r.project = ? AND tc.owner IS NOT NULL"
        params.append(project)
    else:
        project_clause = "WHERE tc.owner IS NOT NULL"

    rows = conn.execute(
        f"""
        SELECT DISTINCT tc.owner
        FROM test_cases tc
        {project_clause}
        ORDER BY tc.owner
        """,
        params,
    ).fetchall()
    return [row[0] for row in rows if row and row[0]]


def _owners_in_text(text: str, owners: list[str]) -> list[str]:
    normalized_text = _normalize_text(text)
    matches: list[tuple[int, str]] = []
    for owner in owners:
        normalized_owner = _normalize_text(owner)
        if not normalized_owner:
            continue
        pos = normalized_text.find(normalized_owner)
        if pos >= 0:
            matches.append((pos, owner))

    ordered: list[str] = []
    seen: set[str] = set()
    for _, owner in sorted(matches, key=lambda item: item[0]):
        if owner in seen:
            continue
        seen.add(owner)
        ordered.append(owner)
    if ordered:
        return ordered

    words = re.findall(r"[a-z0-9]+", normalized_text)
    token_positions = {word: normalized_text.find(word) for word in words if len(word) >= 3}
    partial_matches: list[tuple[int, str]] = []
    for owner in owners:
        owner_tokens = [token for token in re.findall(r"[a-z0-9]+", _normalize_text(owner)) if len(token) >= 3]
        if not owner_tokens:
            continue
        matched_positions = [
            token_positions[token]
            for token in owner_tokens
            if token in token_positions
        ]
        if matched_positions:
            partial_matches.append((min(matched_positions), owner))

    for _, owner in sorted(partial_matches, key=lambda item: item[0]):
        if owner in seen:
            continue
        seen.add(owner)
        ordered.append(owner)
    return ordered


def _extract_owner_pair(question: str, owners: list[str]) -> tuple[str, str] | None:
    ordered = _owners_in_text(question, owners)
    if len(ordered) >= 2:
        ordered = ordered[:2]
        if len(ordered) == 2:
            return ordered[0], ordered[1]
    return None


def _extract_owner_from_question(question: str, owners: list[str]) -> str | None:
    matched = _owners_in_text(question, owners)
    return matched[0] if matched else None


def _owner_pair_from_history(
    question: str,
    history: list[dict[str, str]],
    owners: list[str],
) -> tuple[str, str] | None:
    pair = _extract_owner_pair(question, owners)
    if pair is not None:
        return pair

    combined = "\n".join(
        msg.get("content", "")
        for msg in history
        if msg.get("role") in {"user", "assistant"}
    )
    ordered = _owners_in_text(combined, owners)
    if len(ordered) >= 2:
        return ordered[0], ordered[1]
    return None


def _comparison_window_limit_from_history(question: str, history: list[dict[str, str]]) -> int:
    direct = _comparison_window_limit(question)
    if direct != 10:
        return direct
    for msg in reversed(history or []):
        content = msg.get("content", "")
        parsed = _comparison_window_limit(content)
        if parsed != 10 or "last 10 runs" in _normalize_text(content):
            return parsed
    return 10


def _suite_stats_for_owner(rows: list[dict], owner: str) -> dict[str, dict[str, int | str]]:
    stats: dict[str, dict[str, int | str]] = {}
    for row in rows:
        if row.get("owner") != owner:
            continue
        suite_name = row.get("suite") or "Unknown suite"
        bucket = stats.setdefault(suite_name, {
            "suiteName": suite_name,
            "tests": 0,
            "failing": 0,
            "newFailures": 0,
        })
        bucket["tests"] = int(bucket["tests"]) + 1
        if row.get("status_a") in ("failed", "broken"):
            bucket["failing"] = int(bucket["failing"]) + 1
        if row.get("status_a") in ("failed", "broken") and row.get("status_b") not in ("failed", "broken"):
            bucket["newFailures"] = int(bucket["newFailures"]) + 1
    return stats


def _build_owner_suite_result(compare_payload: dict, owner_a: str, owner_b: str) -> dict:
    owner_a_stats = _suite_stats_for_owner(compare_payload.get("rows", []), owner_a)
    owner_b_stats = _suite_stats_for_owner(compare_payload.get("rows", []), owner_b)

    shared_names = sorted(set(owner_a_stats) & set(owner_b_stats))
    owner_a_only = sorted(set(owner_a_stats) - set(owner_b_stats))
    owner_b_only = sorted(set(owner_b_stats) - set(owner_a_stats))

    shared = [
        {
            "suiteName": suite_name,
            "ownerATests": owner_a_stats[suite_name]["tests"],
            "ownerAFailing": owner_a_stats[suite_name]["failing"],
            "ownerBTests": owner_b_stats[suite_name]["tests"],
            "ownerBFailing": owner_b_stats[suite_name]["failing"],
        }
        for suite_name in shared_names
    ]

    def _owner_only_payload(names: list[str], stats: dict[str, dict[str, int | str]]) -> list[dict]:
        return [
            {
                "suiteName": suite_name,
                "tests": stats[suite_name]["tests"],
                "failing": stats[suite_name]["failing"],
                "newFailures": stats[suite_name]["newFailures"],
            }
            for suite_name in names
        ]

    metrics_a = compare_payload["metrics_a"]
    metrics_b = compare_payload["metrics_b"]

    return {
        "type": "owner_suite_comparison",
        "title": f"Suite differences between {owner_a} and {owner_b}",
        "subtitle": "Compared by current owner assignment. QA Lens can narrow this to a specific run window if you want recent health instead.",
        "owners": {
            "ownerA": owner_a,
            "ownerB": owner_b,
            "timeLabel": compare_payload.get("time_label", "Selected run window"),
            "runCount": compare_payload.get("run_count", 0),
        },
        "summary": {
            "sharedSuites": len(shared_names),
            "ownerAOnlySuites": len(owner_a_only),
            "ownerBOnlySuites": len(owner_b_only),
            "ownerAFailingSuites": sum(1 for item in owner_a_stats.values() if int(item["failing"]) > 0),
            "ownerBFailingSuites": sum(1 for item in owner_b_stats.values() if int(item["failing"]) > 0),
        },
        "metrics": {
            "ownerA": {
                "passRate": metrics_a.get("pass_rate", 0.0),
                "failed": metrics_a.get("failed", 0),
                "totalTests": metrics_a.get("total_tests", 0),
                "flakyCount": metrics_a.get("flaky_count", 0),
            },
            "ownerB": {
                "passRate": metrics_b.get("pass_rate", 0.0),
                "failed": metrics_b.get("failed", 0),
                "totalTests": metrics_b.get("total_tests", 0),
                "flakyCount": metrics_b.get("flaky_count", 0),
            },
        },
        "shared": shared,
        "ownerAOnly": _owner_only_payload(owner_a_only, owner_a_stats),
        "ownerBOnly": _owner_only_payload(owner_b_only, owner_b_stats),
    }


def _owner_suite_summary(result: dict) -> str:
    owner_a = result["owners"]["ownerA"]
    owner_b = result["owners"]["ownerB"]
    shared = result["shared"]
    shared_line = (
        ", ".join(item["suiteName"] for item in shared[:3])
        if shared else
        "no shared suites"
    )
    owner_a_only = result["ownerAOnly"]
    owner_b_only = result["ownerBOnly"]
    owner_a_line = ", ".join(item["suiteName"] for item in owner_a_only[:3]) if owner_a_only else "none"
    owner_b_line = ", ".join(item["suiteName"] for item in owner_b_only[:3]) if owner_b_only else "none"

    return "\n".join([
        f"I compared the current suite ownership for {owner_a} and {owner_b}.",
        "",
        f"Shared suites: {shared_line}",
        f"{owner_a}-only suites: {owner_a_line}",
        f"{owner_b}-only suites: {owner_b_line}",
        "",
        "The detailed suite comparison is shown in the Results workspace. If you want, I can also narrow this to a particular run window like the last 5 or 10 runs.",
    ])


def _top_failing_tests(compare_payload: dict, owner: str) -> list[dict]:
    rows = [
        row for row in compare_payload.get("rows", [])
        if row.get("owner") == owner
    ]
    items: list[dict] = []
    for row in rows:
        history = row.get("run_history", [])
        fail_count = sum(1 for point in history if point.get("status") in ("failed", "broken"))
        if fail_count <= 0:
            continue
        items.append({
            "testName": row.get("display_name") or row.get("canonical_name"),
            "suite": row.get("suite"),
            "failCount": fail_count,
        })
    items.sort(key=lambda item: (-item["failCount"], str(item["testName"])))
    return items[:5]


def _owner_rows(compare_payload: dict, owner: str) -> list[dict]:
    return [
        row for row in compare_payload.get("rows", [])
        if row.get("owner") == owner
    ]


def _owner_window_rates(rows: list[dict]) -> tuple[float, float]:
    passed = 0
    failed = 0
    total = 0
    for row in rows:
        for point in row.get("run_history", []):
            status = point.get("status")
            if status == "absent":
                continue
            total += 1
            if status == "passed":
                passed += 1
            elif status in ("failed", "broken"):
                failed += 1
    if total == 0:
        return 0.0, 0.0
    return passed / total, failed / total


def _owner_window_trend(rows: list[dict]) -> tuple[int, int]:
    improved = 0
    regressed = 0
    for row in rows:
        was_good = row.get("status_b") == "passed"
        is_good = row.get("status_a") == "passed"
        if not was_good and is_good:
            improved += 1
        if was_good and not is_good:
            regressed += 1
    return improved, regressed


def _owner_current_failing(rows: list[dict]) -> int:
    return sum(1 for row in rows if row.get("status_a") in ("failed", "broken"))


def _owner_window_score(
    *,
    pass_rate: float,
    fail_rate: float,
    new_failures: int,
    flaky_count: int,
    max_tests: int,
) -> float:
    return (
        pass_rate * 0.6
        - fail_rate * 0.2
        - (new_failures / max_tests) * 0.1
        - (flaky_count / max_tests) * 0.1
    )


def _history_state(status: str | None) -> str:
    if status == "passed":
        return "PASS"
    if status in ("failed", "broken"):
        return "FAIL"
    if status == "skipped":
        return "SKIP"
    return "UNKNOWN"


def _owner_test_gap_items(compare_payload: dict, owner: str) -> list[dict]:
    rows = _owner_rows(compare_payload, owner)
    items: list[dict] = []
    for row in rows:
        history = row.get("run_history", [])
        relevant_statuses = [point.get("status") for point in history if point.get("status") != "absent"]
        fail_count = sum(1 for status in relevant_statuses if status in ("failed", "broken"))
        pass_count = sum(1 for status in relevant_statuses if status == "passed")
        total = len(relevant_statuses)
        pass_rate = (pass_count / total) if total else 0.0
        latest_failed = row.get("status_a") in ("failed", "broken")
        regressed = row.get("status_b") == "passed" and latest_failed
        flaky = pass_count > 0 and fail_count > 0
        history_states = [_history_state(point.get("status")) for point in history]

        if latest_failed and regressed:
            primary_reason = f"Recently regressed and is failing now with {fail_count} failure{'s' if fail_count != 1 else ''} in the selected scope."
        elif latest_failed:
            primary_reason = f"Currently failing with {fail_count} failure{'s' if fail_count != 1 else ''} in the selected scope."
        elif flaky:
            primary_reason = f"Flaky across the selected scope with a {round(pass_rate * 100)}% pass rate."
        else:
            primary_reason = f"Lower pass-rate resilience at {round(pass_rate * 100)}% across the selected scope."

        severity = 0
        if latest_failed:
            severity += 100
        if regressed:
            severity += 40
        if flaky:
            severity += 20
        severity += fail_count * 4
        severity += max(0, 80 - round(pass_rate * 100))

        risk_tier = "LOW"
        if latest_failed and regressed:
            risk_tier = "HIGH"
        elif latest_failed or flaky:
            risk_tier = "MEDIUM"

        items.append({
            "testName": row.get("display_name") or row.get("canonical_name"),
            "canonicalName": row.get("canonical_name"),
            "suite": row.get("suite"),
            "passRate": pass_rate,
            "failCount": fail_count,
            "currentStatus": row.get("status_a") or "absent",
            "regressed": regressed,
            "flaky": flaky,
            "riskTier": risk_tier,
            "history": history_states,
            "primaryReason": primary_reason,
            "errorMessage": row.get("error_message"),
            "severity": severity,
        })

    items.sort(key=lambda item: (-item["severity"], str(item["testName"])))
    return [
        {
            "rank": index + 1,
            **item,
        }
        for index, item in enumerate(items)
    ]


def _build_owner_test_gap_result(compare_payload: dict, owner_focus: str, owner_peer: str | None) -> dict:
    metrics = compare_payload["metrics_a"] if compare_payload.get("label_a") == owner_focus else compare_payload["metrics_b"]
    items = _owner_test_gap_items(compare_payload, owner_focus)
    latest_failed = sum(1 for item in items if item["currentStatus"] in ("failed", "broken"))
    regressed = sum(1 for item in items if item["regressed"])
    flaky = metrics.get("flaky_count", 0)

    return {
        "type": "owner_test_gap",
        "title": f"{owner_focus}'s tests driving the current gap",
        "subtitle": (
            f"Focused test-level view for {owner_focus} compared with {owner_peer}."
            if owner_peer
            else f"Focused test-level view for {owner_focus}."
        ),
        "owner": owner_focus,
        "comparedAgainst": owner_peer,
        "mode": "gap",
        "scope": {
            "label": compare_payload.get("time_label", "Selected run window"),
            "runCount": compare_payload.get("run_count", 0),
            "totalTests": metrics.get("total_tests", len(items)),
        },
        "summary": {
            "currentlyFailing": latest_failed,
            "regressed": regressed,
            "flaky": flaky,
            "topSuite": items[0]["suite"] if items and items[0].get("suite") else None,
        },
        "tests": items[:8],
    }


def _build_owner_failing_tests_result(compare_payload: dict, owner_focus: str) -> dict:
    all_items = _owner_test_gap_items(compare_payload, owner_focus)
    items = [item for item in all_items if item["currentStatus"] in ("failed", "broken")]
    regressed = sum(1 for item in items if item["regressed"])
    flaky = sum(1 for item in items if item["flaky"])
    top_suite = items[0]["suite"] if items else None

    return {
        "type": "owner_test_gap",
        "title": f"Currently failing tests owned by {owner_focus}",
        "subtitle": f"Focused failing-test view for {owner_focus} across {compare_payload.get('time_label', 'the selected run window').lower()}.",
        "owner": owner_focus,
        "comparedAgainst": None,
        "mode": "failing_tests",
        "scope": {
            "label": compare_payload.get("time_label", "Selected run window"),
            "runCount": compare_payload.get("run_count", 0),
            "totalTests": len(items),
        },
        "summary": {
            "currentlyFailing": len(items),
            "regressed": regressed,
            "flaky": flaky,
            "topSuite": top_suite,
        },
        "tests": items[:8],
    }


def _owner_test_gap_summary(result: dict) -> str:
    owner = result["owner"]
    compared_against = result.get("comparedAgainst")
    mode = result.get("mode", "gap")
    scope = result["scope"]["label"].lower()
    tests = result["tests"][:3]
    bullet_lines = [
        f"{item['rank']}. {item['testName']} — {round(item['passRate'] * 100)}% pass rate · {item['primaryReason']}"
        for item in tests
    ] or ["No high-signal tests were found for this owner in the selected scope."]

    if mode == "failing_tests":
        header = f"I looked at which of {owner}'s tests are currently failing across {scope}."
    else:
        header = (
            f"I looked at which of {owner}'s tests are driving the current gap against {compared_against} across {scope}."
            if compared_against
            else f"I looked at which of {owner}'s tests are driving the current gap across {scope}."
        )
    return "\n".join([
        header,
        "",
        "Currently failing tests:" if mode == "failing_tests" else "Top drivers:",
        *bullet_lines,
        "",
        "The detailed ranked view is shown in the Results workspace.",
    ])


def _owner_suite_regression_items(compare_payload: dict, owner: str) -> list[dict]:
    rows = _owner_rows(compare_payload, owner)
    grouped: dict[str, dict] = {}
    for row in rows:
        suite_name = row.get("suite") or "Unknown suite"
        bucket = grouped.setdefault(
            suite_name,
            {
                "suiteName": suite_name,
                "tests": 0,
                "currentlyFailing": 0,
                "regressed": 0,
                "flaky": 0,
                "failuresInScope": 0,
                "lowestPassRate": 1.0,
                "topTests": [],
            },
        )
        history = row.get("run_history", [])
        relevant_statuses = [point.get("status") for point in history if point.get("status") != "absent"]
        fail_count = sum(1 for status in relevant_statuses if status in ("failed", "broken"))
        pass_count = sum(1 for status in relevant_statuses if status == "passed")
        total = len(relevant_statuses)
        pass_rate = (pass_count / total) if total else 0.0
        latest_failed = row.get("status_a") in ("failed", "broken")
        regressed = row.get("status_b") == "passed" and latest_failed
        flaky = pass_count > 0 and fail_count > 0

        bucket["tests"] += 1
        bucket["currentlyFailing"] += 1 if latest_failed else 0
        bucket["regressed"] += 1 if regressed else 0
        bucket["flaky"] += 1 if flaky else 0
        bucket["failuresInScope"] += fail_count
        bucket["lowestPassRate"] = min(bucket["lowestPassRate"], pass_rate)
        bucket["topTests"].append(
            {
                "testName": row.get("display_name") or row.get("canonical_name"),
                "canonicalName": row.get("canonical_name"),
                "passRate": pass_rate,
                "failCount": fail_count,
                "currentStatus": row.get("status_a") or "absent",
                "regressed": regressed,
                "flaky": flaky,
                "errorMessage": row.get("error_message"),
            }
        )

    items: list[dict] = []
    for suite_name, bucket in grouped.items():
        top_tests = sorted(
            bucket["topTests"],
            key=lambda item: (
                -(1 if item["currentStatus"] in ("failed", "broken") else 0),
                -(1 if item["regressed"] else 0),
                -item["failCount"],
                item["passRate"],
                str(item["testName"]),
            ),
        )[:4]
        severity = (
            bucket["regressed"] * 50
            + bucket["currentlyFailing"] * 25
            + bucket["flaky"] * 12
            + bucket["failuresInScope"] * 3
            + max(0, 80 - round(bucket["lowestPassRate"] * 100))
        )
        items.append(
            {
                "suiteName": suite_name,
                "tests": bucket["tests"],
                "currentlyFailing": bucket["currentlyFailing"],
                "regressed": bucket["regressed"],
                "flaky": bucket["flaky"],
                "failuresInScope": bucket["failuresInScope"],
                "lowestPassRate": bucket["lowestPassRate"],
                "topTests": top_tests,
                "severity": severity,
            }
        )

    items.sort(key=lambda item: (-item["severity"], str(item["suiteName"])))
    return [
        {
            "rank": index + 1,
            **item,
        }
        for index, item in enumerate(items)
    ]


def _build_owner_suite_regression_result(compare_payload: dict, owner_focus: str, owner_peer: str | None) -> dict:
    items = _owner_suite_regression_items(compare_payload, owner_focus)
    top_suite = items[0]["suiteName"] if items else None
    return {
        "type": "owner_suite_regressions",
        "title": f"Suites causing most of {owner_focus}'s regressions",
        "subtitle": (
            f"Suite-level regression view for {owner_focus} compared with {owner_peer}."
            if owner_peer
            else f"Suite-level regression view for {owner_focus}."
        ),
        "owner": owner_focus,
        "comparedAgainst": owner_peer,
        "scope": {
            "label": compare_payload.get("time_label", "Selected run window"),
            "runCount": compare_payload.get("run_count", 0),
            "totalSuites": len(items),
        },
        "summary": {
            "topSuite": top_suite,
            "regressedSuites": sum(1 for item in items if item["regressed"] > 0),
            "currentlyFailingSuites": sum(1 for item in items if item["currentlyFailing"] > 0),
            "flakySuites": sum(1 for item in items if item["flaky"] > 0),
        },
        "suites": items[:6],
    }


def _owner_suite_regression_summary(result: dict) -> str:
    owner = result["owner"]
    compared_against = result.get("comparedAgainst")
    scope = result["scope"]["label"].lower()
    suites = result["suites"][:3]
    bullet_lines = [
        f"{item['rank']}. {item['suiteName']} — {item['regressed']} regressed · {item['currentlyFailing']} currently failing · {item['flaky']} flaky tests"
        for item in suites
    ] or ["No suite-level regression hotspots were found for this owner in the selected scope."]

    header = (
        f"I looked at which suites are causing most of {owner}'s regressions against {compared_against} across {scope}."
        if compared_against
        else f"I looked at which suites are causing most of {owner}'s regressions across {scope}."
    )
    return "\n".join([
        header,
        "",
        "Top suite hotspots:",
        *bullet_lines,
        "",
        "The detailed suite breakdown is shown in the Results workspace.",
    ])


def _shared_suite_failure_items(compare_payload: dict, owner_a: str, owner_b: str) -> list[dict]:
    owner_a_rows = _owner_rows(compare_payload, owner_a)
    owner_b_rows = _owner_rows(compare_payload, owner_b)
    owner_a_suites = {row.get("suite") or "Unknown suite" for row in owner_a_rows}
    owner_b_suites = {row.get("suite") or "Unknown suite" for row in owner_b_rows}
    shared_names = sorted(owner_a_suites & owner_b_suites)
    items: list[dict] = []

    def _suite_test_payload(rows: list[dict], suite_name: str) -> tuple[list[dict], dict[str, int]]:
        suite_rows = [row for row in rows if (row.get("suite") or "Unknown suite") == suite_name]
        tests: list[dict] = []
        counts = {"currentlyFailing": 0, "regressed": 0, "failuresInScope": 0}
        for row in suite_rows:
            history = row.get("run_history", [])
            relevant_statuses = [point.get("status") for point in history if point.get("status") != "absent"]
            fail_count = sum(1 for status in relevant_statuses if status in ("failed", "broken"))
            pass_count = sum(1 for status in relevant_statuses if status == "passed")
            total = len(relevant_statuses)
            pass_rate = (pass_count / total) if total else 0.0
            latest_failed = row.get("status_a") in ("failed", "broken")
            regressed = row.get("status_b") == "passed" and latest_failed
            counts["currentlyFailing"] += 1 if latest_failed else 0
            counts["regressed"] += 1 if regressed else 0
            counts["failuresInScope"] += fail_count
            tests.append(
                {
                    "testName": row.get("display_name") or row.get("canonical_name"),
                    "canonicalName": row.get("canonical_name"),
                    "passRate": pass_rate,
                    "failCount": fail_count,
                    "currentStatus": row.get("status_a") or "absent",
                    "regressed": regressed,
                    "flaky": pass_count > 0 and fail_count > 0,
                    "errorMessage": row.get("error_message"),
                }
            )
        tests.sort(
            key=lambda item: (
                -(1 if item["currentStatus"] in ("failed", "broken") else 0),
                -(1 if item["regressed"] else 0),
                -item["failCount"],
                item["passRate"],
                str(item["testName"]),
            )
        )
        return tests[:3], counts

    for suite_name in shared_names:
        tests_a, counts_a = _suite_test_payload(owner_a_rows, suite_name)
        tests_b, counts_b = _suite_test_payload(owner_b_rows, suite_name)
        pressure = (
            counts_a["currentlyFailing"] + counts_b["currentlyFailing"]
        ) * 20 + (
            counts_a["regressed"] + counts_b["regressed"]
        ) * 40 + (
            counts_a["failuresInScope"] + counts_b["failuresInScope"]
        ) * 2
        items.append(
            {
                "suiteName": suite_name,
                "ownerA": {
                    "currentlyFailing": counts_a["currentlyFailing"],
                    "regressed": counts_a["regressed"],
                    "failuresInScope": counts_a["failuresInScope"],
                    "topTests": tests_a,
                },
                "ownerB": {
                    "currentlyFailing": counts_b["currentlyFailing"],
                    "regressed": counts_b["regressed"],
                    "failuresInScope": counts_b["failuresInScope"],
                    "topTests": tests_b,
                },
                "combinedPressure": pressure,
            }
        )

    items.sort(key=lambda item: (-item["combinedPressure"], str(item["suiteName"])))
    return [
        {
            "rank": index + 1,
            **item,
        }
        for index, item in enumerate(items)
    ]


def _build_shared_suite_failure_result(compare_payload: dict, owner_a: str, owner_b: str) -> dict:
    items = _shared_suite_failure_items(compare_payload, owner_a, owner_b)
    return {
        "type": "shared_suite_failures",
        "title": f"Shared suites failing most between {owner_a} and {owner_b}",
        "subtitle": f"Current shared-suite overlap ranked by failure pressure across {compare_payload.get('time_label', 'the selected run window').lower()}.",
        "owners": {
            "ownerA": owner_a,
            "ownerB": owner_b,
        },
        "scope": {
            "label": compare_payload.get("time_label", "Selected run window"),
            "runCount": compare_payload.get("run_count", 0),
            "sharedSuites": len(items),
        },
        "summary": {
            "topSuite": items[0]["suiteName"] if items else None,
            "sharedSuites": len(items),
        },
        "suites": items[:6],
    }


def _shared_suite_failure_summary(result: dict) -> str:
    owner_a = result["owners"]["ownerA"]
    owner_b = result["owners"]["ownerB"]
    scope = result["scope"]["label"].lower()
    suites = result["suites"][:3]
    bullet_lines = [
        f"{item['rank']}. {item['suiteName']} — {owner_a}: {item['ownerA']['currentlyFailing']} failing, {owner_b}: {item['ownerB']['currentlyFailing']} failing"
        for item in suites
    ] or ["No shared suites were found between these owners."]
    return "\n".join([
        f"I looked at which shared suites between {owner_a} and {owner_b} are failing most across {scope}.",
        "",
        "Top shared-suite hotspots:",
        *bullet_lines,
        "",
        "The detailed shared-suite breakdown is shown in the Results workspace.",
    ])


def _build_owner_window_result(compare_payload: dict, owner_a: str, owner_b: str) -> dict:
    metrics_a = compare_payload["metrics_a"]
    metrics_b = compare_payload["metrics_b"]
    rows_a = _owner_rows(compare_payload, owner_a)
    rows_b = _owner_rows(compare_payload, owner_b)

    pass_rate_a, fail_rate_a = _owner_window_rates(rows_a)
    pass_rate_b, fail_rate_b = _owner_window_rates(rows_b)
    recovered_a, regressed_a = _owner_window_trend(rows_a)
    recovered_b, regressed_b = _owner_window_trend(rows_b)
    failed_a = _owner_current_failing(rows_a)
    failed_b = _owner_current_failing(rows_b)

    max_tests = max(metrics_a.get("total_tests", 0), metrics_b.get("total_tests", 0), 1)
    score_a = _owner_window_score(
        pass_rate=pass_rate_a,
        fail_rate=fail_rate_a,
        new_failures=metrics_a.get("new_failures", 0),
        flaky_count=metrics_a.get("flaky_count", 0),
        max_tests=max_tests,
    )
    score_b = _owner_window_score(
        pass_rate=pass_rate_b,
        fail_rate=fail_rate_b,
        new_failures=metrics_b.get("new_failures", 0),
        flaky_count=metrics_b.get("flaky_count", 0),
        max_tests=max_tests,
    )
    leader = owner_a if score_a >= score_b else owner_b
    return {
        "type": "owner_window_comparison",
        "title": f"Comparing {owner_a} and {owner_b}",
        "subtitle": (
            "Latest-run owner comparison based on the most recent run snapshot."
            if compare_payload.get("run_count", 0) == 1
            else "Recent-window owner comparison based on pass rate, regressions, recoveries, and flakiness."
        ),
        "owners": {
            "ownerA": owner_a,
            "ownerB": owner_b,
            "timeLabel": compare_payload.get("time_label", "Selected run window"),
            "runCount": compare_payload.get("run_count", 0),
        },
        "metrics": {
            "ownerA": {
                "totalTests": metrics_a.get("total_tests", 0),
                "passRate": pass_rate_a,
                "failureRate": fail_rate_a,
                "failed": failed_a,
                "flakyCount": metrics_a.get("flaky_count", 0),
                "regressed": regressed_a,
                "recovered": recovered_a,
                "score": score_a,
            },
            "ownerB": {
                "totalTests": metrics_b.get("total_tests", 0),
                "passRate": pass_rate_b,
                "failureRate": fail_rate_b,
                "failed": failed_b,
                "flakyCount": metrics_b.get("flaky_count", 0),
                "regressed": regressed_b,
                "recovered": recovered_b,
                "score": score_b,
            },
        },
        "summary": {
            "leader": leader,
            "passRateGap": abs(pass_rate_a - pass_rate_b),
            "flakyGap": abs(metrics_a.get("flaky_count", 0) - metrics_b.get("flaky_count", 0)),
            "regressionGap": abs(regressed_a - regressed_b),
        },
        "topRisks": {
            "ownerA": _top_failing_tests(compare_payload, owner_a),
            "ownerB": _top_failing_tests(compare_payload, owner_b),
        },
    }


def _owner_window_summary(result: dict) -> str:
    owner_a = result["owners"]["ownerA"]
    owner_b = result["owners"]["ownerB"]
    metrics_a = result["metrics"]["ownerA"]
    metrics_b = result["metrics"]["ownerB"]
    leader = result["summary"]["leader"]
    run_count = result["owners"]["runCount"]
    scope_phrase = "the latest run" if run_count == 1 else result["owners"]["timeLabel"].lower()
    pass_rate_label = "latest-run pass rate" if run_count == 1 else "window pass rate"
    lead_phrase = "is leading in the latest run." if run_count == 1 else "is leading in this selected window."
    return "\n".join([
        f"I compared {owner_a} and {owner_b} across {scope_phrase}.",
        "",
        f"{owner_a}: {round(metrics_a['passRate'] * 100)}% {pass_rate_label} · {metrics_a['regressed']} regressed · {metrics_a['recovered']} recovered · {metrics_a['flakyCount']} flaky tests",
        f"{owner_b}: {round(metrics_b['passRate'] * 100)}% {pass_rate_label} · {metrics_b['regressed']} regressed · {metrics_b['recovered']} recovered · {metrics_b['flakyCount']} flaky tests",
        "",
        f"{leader} {lead_phrase} The detailed comparison is shown in the Results workspace.",
    ])


def make_llm_router(
    db_path: str | Path | None,
    cfg_path: str | Path | None,
) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with the LLM ask endpoint."""
    router = APIRouter()

    @router.post("/api/ask", tags=["llm"], response_model=AskResponse)
    async def ask(
        body: AskRequest,
        _rl: None = Depends(_ask_rate_limit),
    ) -> AskResponse:
        """Send a natural-language question to the configured LLM.

        Raises HTTP 503 if the LLM is unreachable, HTTP 400 if the question
        is empty.
        """
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="Question must not be empty.")

        if _is_off_topic_or_harmful(body.question):
            from qalens.security import redact_secrets
            logger.warning("Off-topic or harmful query blocked: %r", redact_secrets(body.question[:120]))
            return AskResponse(
                answer=_REFUSAL_MESSAGE,
                context_mode="none",
                sources=[],
                follow_ups=[
                    "Which tests failed in the latest run?",
                    "What are the flakiest tests?",
                    "Which tests are most likely to fail next?",
                ],
            )

        from qalens.llm.deterministic_answers import answer_test_fix_payload

        deterministic_payload = answer_test_fix_payload(
            body.question,
            project=body.project,
            db_path=db_path,
        )
        if deterministic_payload is not None:
            return AskResponse(
                answer=deterministic_payload["answer"],
                context_mode="project",
                sources=[],
                intent="deterministic",
                follow_ups=[
                    "Show the failure history for this test",
                    "Are other tests failing for the same root cause?",
                    "Which suite owns this failure?",
                ],
                result=deterministic_payload.get("result"),
                uiHints={"activeTab": "results", "openWorkspace": True},
            )

        from qalens.llm.answer_plan import AnswerIntent, RankingMetric, build_answer_plan, detect_answer_intent
        from qalens.llm.client import LLMClient, LLMError
        from qalens.llm.config import load_config
        from qalens.llm.context import (
            extract_test_from_history,
            gather_date_context,
            gather_project_context,
            gather_test_context,
        )
        from qalens.llm.context_history import extract_prior_context_from_history
        from qalens.llm.prompts import (
            build_narration_prompt,
            build_narration_system_prompt,
            build_prompt,
            build_system_prompt,
            infer_mode,
        )
        from qalens.llm.routing import (
            detect_signals,
            gather_context_for_signals,
            gather_risk_ranking_fact_bundle,
            normalize_query,
            parse_query_intent,
        )
        from qalens.server.routes_compare import _build_entity_comparison

        cfg = load_config(None if cfg_path is None else Path(cfg_path))
        mode = infer_mode(body.question)

        # Build prior context from conversation history so follow-up questions
        # can inherit intent, metric, and max_results from the previous turn.
        _prior_context = extract_prior_context_from_history(body.history or [])

        # Detect answer intent — drives prompt structure and context selection.
        _answer_intent = detect_answer_intent(body.question)
        _answer_plan = build_answer_plan(
            _answer_intent, question=body.question, prior_context=_prior_context
        )

        root_cause_kind = _root_cause_query_kind(body.question)
        if root_cause_kind is not None:
            from qalens.analyzers.categorizer import categorize_failure
            from qalens.analyzers.flaky import FlakyScorer
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if not available_runs:
                    return AskResponse(
                        answer="I could not find any runs in the available QA Lens data for this project.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label = _root_cause_scope(body.question, len(available_runs))
                selected_runs = available_runs[:limit]
                explicit_run_number = _extract_run_number(body.question)
                if explicit_run_number is not None:
                    run = repo.get_run_by_sequence(explicit_run_number, project=body.project)
                    if run is not None:
                        selected_runs = [run]
                        scope_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id
                latest = selected_runs[0] if selected_runs else None
                latest_run_label = (
                    f"Run #{latest.run_sequence}" if latest and latest.run_sequence else (latest.run_id if latest else None)
                )

                failures: list[dict] = []
                total_tests_evaluated = 0
                target_test = _root_cause_target_test(body.question)

                if root_cause_kind == "test_frequency" and target_test:
                    scorer = FlakyScorer(conn)
                    results = scorer.get_all(project=body.project, min_runs=1, limit_per_test=max(limit, 2))
                    matched = _match_test_result_by_name(results, target_test)
                    if matched is not None:
                        history = repo.get_test_history(matched.canonical_name, project=body.project, limit=max(limit, 2))
                        total_tests_evaluated = 1
                        for entry in history:
                            if entry.status not in ("failed", "broken"):
                                continue
                            category = categorize_failure(error_type=entry.error_type, message=entry.message)
                            failures.append({
                                "testName": matched.display_name,
                                "canonicalName": matched.canonical_name,
                                "runLabel": f"Run #{entry.run_sequence}" if entry.run_sequence else entry.run_id,
                                "category": category.value,
                                "message": (entry.message or "").split("\n")[0][:180] if entry.message else None,
                            })
                        target_test = matched.display_name
                elif root_cause_kind == "flaky_causes":
                    scorer = FlakyScorer(conn)
                    flaky_results = scorer.get_all_flaky(project=body.project, min_runs=2, limit_per_test=max(limit, 2))
                    total_tests_evaluated = len(flaky_results)
                    for flaky in flaky_results:
                        history = repo.get_test_history(flaky.canonical_name, project=body.project, limit=max(limit, 2))
                        for entry in history:
                            if entry.status not in ("failed", "broken"):
                                continue
                            category = categorize_failure(error_type=entry.error_type, message=entry.message)
                            failures.append({
                                "testName": flaky.display_name,
                                "canonicalName": flaky.canonical_name,
                                "runLabel": f"Run #{entry.run_sequence}" if entry.run_sequence else entry.run_id,
                                "category": category.value,
                                "message": (entry.message or "").split("\n")[0][:180] if entry.message else None,
                            })
                else:
                    selected_run_ids = {run.run_id for run in selected_runs}
                    for run in selected_runs:
                        test_cases = repo.get_test_cases_for_run(run.run_id)
                        total_tests_evaluated += len(test_cases)
                        run_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id
                        for tc in test_cases:
                            if tc.status not in ("failed", "broken"):
                                continue
                            category = categorize_failure(error_type=tc.error_type, message=tc.message)
                            failures.append({
                                "testName": tc.name,
                                "canonicalName": tc.canonical_name,
                                "runLabel": run_label,
                                "category": category.value,
                                "message": tc.message.split("\n")[0][:180] if tc.message else None,
                            })

                    if root_cause_kind == "cause_mix":
                        failures = [
                            item for item in failures
                            if _CAUSE_FAMILY_BY_CATEGORY.get(item["category"]) in {
                                "UI / test script issue",
                                "Product / backend defect",
                            }
                        ]
                    elif root_cause_kind == "common_patterns":
                        # keep all failures; the grouped causes act as the pattern summary
                        pass

                result = _root_cause_build_result(
                    kind=root_cause_kind,
                    scope_label=scope_label,
                    run_count=len(selected_runs) if root_cause_kind != "test_frequency" else max(limit, 1),
                    latest_run_label=latest_run_label,
                    target_test=target_test,
                    failures=failures,
                    total_tests_evaluated=total_tests_evaluated,
                )

                follow_ups = [
                    "Identify common failure patterns across runs",
                    "Are failures due to UI changes or backend issues?",
                    "What is causing most flaky failures?",
                ]
                if target_test:
                    follow_ups = [
                        f"Show the failure history for {target_test}",
                        "Are other tests failing for the same root cause?",
                        "Identify common failure patterns across runs",
                    ]

                normalized_question = _normalize_text(body.question)
                defaulted_scope = not (
                    any(
                        phrase in normalized_question
                        for phrase in (
                            "across all runs",
                            "all runs",
                            "across runs",
                            "latest run",
                            "last run",
                            "most recent run",
                            "current run",
                        )
                    )
                    or _extract_run_number(body.question) is not None
                    or re.search(r"\blast\s+\d+\s+runs?\b", normalized_question) is not None
                )
                fact_bundle = _root_cause_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "root_cause_insight",
                    fact_bundle,
                    defaulted_scope=defaulted_scope,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_root_cause_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "root_cause_insight",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _root_cause_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=follow_ups[:3],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _is_exception_retrieval_question(body.question):
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            query_term = _exception_query_term(body.question)
            extra_filter = _extract_exception_secondary_filter(body.question)
            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                run_number = _extract_run_number(body.question)
                selected_runs = []
                run_label = None

                if run_number is not None:
                    run = repo.get_run_by_sequence(run_number, project=body.project)
                    if run is not None:
                        selected_runs = [run]
                        run_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id
                elif _mentions_latest_run(body.question):
                    latest_runs = repo.list_runs(project=body.project, limit=1)
                    if latest_runs:
                        selected_runs = latest_runs
                        latest = latest_runs[0]
                        run_label = f"Run #{latest.run_sequence}" if latest.run_sequence else latest.run_id
                else:
                    selected_runs = repo.list_runs(project=body.project, limit=5000)

                if not selected_runs:
                    scope_text = f"Run #{run_number}" if run_number is not None else "the requested run scope"
                    return AskResponse(
                        answer=f"I could not find {scope_text} in the available QA Lens data.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                matched_rows: list[dict] = []
                for run in selected_runs:
                    run_tests = repo.get_test_cases_for_run(run.run_id)
                    scoped_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id
                    for tc in run_tests:
                        if tc.status not in ("failed", "broken"):
                            continue
                        matched, category = _failure_matches_query(
                            query_term=query_term or "",
                            error_type=tc.error_type,
                            message=tc.message,
                        )
                        if not matched:
                            continue
                        if not _matches_exception_secondary_filter(tc, extra_filter):
                            continue
                        matched_rows.append({
                            "testName": tc.name,
                            "canonicalName": tc.canonical_name,
                            "runLabel": scoped_label,
                            "status": tc.status,
                            "suite": tc.suite,
                            "owner": tc.owner,
                            "errorType": tc.error_type.split(".")[-1] if tc.error_type else None,
                            "message": tc.message.split("\n")[0][:180] if tc.message else None,
                            "category": category,
                        })

                matched_rows.sort(key=lambda item: (item["runLabel"], item["testName"].lower()))
                display_query = _exception_query_label(query_term or "exception filter", extra_filter)
                result = _build_exception_retrieval_result(
                    query_term=display_query,
                    scope_label=_exception_scope_label(body.question, run_label, len(selected_runs)),
                    runs=selected_runs,
                    matches=matched_rows,
                )
                follow_ups = [
                    f'List all tests that failed due to {result["scope"]["query"]} in {result["scope"]["label"]}',
                    f'Which tests failed in {result["scope"]["label"]}?',
                    "Show all failures caused by assertion errors across all runs",
                ]
                fact_bundle = _exception_retrieval_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "exception_retrieval",
                    fact_bundle,
                    defaulted_scope=False,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_exception_retrieval_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "exception_retrieval",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _exception_retrieval_summary(result)
                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=follow_ups[:3],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _new_failures_introduced_question(body.question):
            from qalens.analyzers.comparison import ComparisonService, comparison_to_dict
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                svc = ComparisonService(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if len(available_runs) < 2:
                    return AskResponse(
                        answer="I need at least two runs to identify newly introduced failures.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label, default_scoped, _has_window_phrase = _trend_scope(body.question, len(available_runs))
                run_number = _extract_run_number(body.question)
                if run_number is not None:
                    target_index = next((i for i, run in enumerate(available_runs) if run.run_sequence == run_number), None)
                    if target_index is None:
                        return AskResponse(
                            answer=f"I could not find Run #{run_number} in the available QA Lens data.",
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[],
                        )
                    selected_runs = available_runs[target_index: target_index + max(limit, 2)]
                    if len(selected_runs) < 2:
                        return AskResponse(
                            answer=f"I need a prior run before Run #{run_number} to identify newly introduced failures.",
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[],
                        )
                    comparison_result = svc.compare_custom(
                        project=body.project,
                        run_ids=[run["run_id"] for run in selected_runs],
                    )
                    scope_label = f"Run #{run_number} and prior context"
                else:
                    compare_limit = 2 if _mentions_latest_run(body.question) else max(limit, 2)
                    comparison_result = svc.compare_window(
                        project=body.project,
                        limit=compare_limit,
                    )

                comparison = comparison_to_dict(comparison_result)
                result = _build_new_failures_introduced_result(comparison, scope_label=scope_label)
                fact_bundle = _new_failures_introduced_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "new_failures_introduced",
                    fact_bundle,
                    defaulted_scope=default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_new_failures_introduced_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "new_failures_introduced",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _new_failures_introduced_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=[
                        "Which suite is contributing most new failures?",
                        "Show recovered tests in the same window",
                        "What changed between the last two runs?",
                    ],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        performance_query_kind = _performance_timing_kind(body.question)
        if performance_query_kind is not None:
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if not available_runs:
                    return AskResponse(
                        answer="I could not find any runs in the available QA Lens data for this project.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label, default_scoped, _has_window_phrase = _trend_scope(body.question, len(available_runs))
                run_number = _extract_run_number(body.question)
                selected_runs = available_runs[:limit]
                if run_number is not None:
                    run = repo.get_run_by_sequence(run_number, project=body.project)
                    if run is not None:
                        selected_runs = [run]
                        scope_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id
                elif _mentions_latest_run(body.question):
                    selected_runs = available_runs[:1]
                    latest_run = selected_runs[0]
                    scope_label = f"Run #{latest_run.run_sequence}" if latest_run.run_sequence else latest_run.run_id

                latest = selected_runs[0] if selected_runs else None
                latest_run_label = (
                    f"Run #{latest.run_sequence}" if latest and latest.run_sequence else (latest.run_id if latest else None)
                )
                threshold_ms = _performance_threshold_ms(body.question)
                items = _load_performance_items(conn, selected_runs)
                result = _build_performance_timing_result(
                    kind=performance_query_kind,
                    scope_label=scope_label,
                    run_count=len(selected_runs),
                    latest_run_label=latest_run_label,
                    threshold_ms=threshold_ms,
                    items=items,
                )
                follow_ups = [
                    "Which tests are taking more than 5 seconds?",
                    "Show slowest tests in the latest run",
                    "Which tests have performance regressions?",
                ]

                fact_bundle = _performance_timing_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "performance_timing",
                    fact_bundle,
                    defaulted_scope=default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_performance_timing_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "performance_timing",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _performance_timing_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=follow_ups[:3],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _owner_failure_rate_question(body.question):
            from qalens.llm.context import gather_owner_aggregate_context

            context, owner_sources = gather_owner_aggregate_context(
                project=body.project,
                db_path=db_path,
            )
            result = _build_owner_failure_rate_result_from_sources(owner_sources)
            return AskResponse(
                answer=_owner_failure_rate_summary(result),
                context_mode="project",
                sources=owner_sources,
                intent=_answer_intent.value,
                follow_ups=[
                    "Which engineer owns the most flaky tests?",
                    "Which engineer has the highest failure count?",
                    "Which suite is causing the most failures?",
                ],
                result=result,
                uiHints={"activeTab": "results", "openWorkspace": True},
            )

        if _owner_flaky_question(body.question):
            from qalens.analyzers.flaky import FlakyScorer
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if not available_runs:
                    return AskResponse(
                        answer="I could not find any runs in the available QA Lens data for this project.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label, default_scoped, _has_window_phrase = _trend_scope(body.question, len(available_runs))
                scorer = FlakyScorer(conn)
                results = scorer.get_all(
                    project=body.project,
                    min_runs=2,
                    limit_per_test=max(limit, 2),
                )
                actual_run_count = min(len(available_runs), max(limit, 1))
                result = _build_owner_flaky_result(
                    scope_label=scope_label,
                    run_count=actual_run_count,
                    results=results,
                )
                fact_bundle = _owner_flaky_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "owner_flaky_tests",
                    fact_bundle,
                    defaulted_scope=default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_owner_flaky_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "owner_flaky_tests",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _owner_flaky_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=[
                        "Which tests are flaky in the last 10 runs?",
                        "Compare failure rate per engineer",
                        "Which engineer has the highest failure count?",
                    ],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _suite_failure_ranking_question(body.question):
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if not available_runs:
                    return AskResponse(
                        answer="I could not find any runs in the available QA Lens data for this project.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label, _default_scoped, _has_window_phrase = _trend_scope(body.question, len(available_runs))
                if _mentions_latest_run(body.question):
                    selected_runs = available_runs[:1]
                    latest = selected_runs[0]
                    scope_label = f"Run #{latest.run_sequence}" if latest.run_sequence else latest.run_id
                else:
                    selected_runs = available_runs[:limit]

                test_cases = []
                for run in selected_runs:
                    test_cases.extend(repo.get_test_cases_for_run(run.run_id, include_details=False))

                result = _build_suite_failure_ranking_result(
                    scope_label=scope_label,
                    run_count=len(selected_runs),
                    test_cases=test_cases,
                )
                fact_bundle = _suite_failure_ranking_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "suite_failure_ranking",
                    fact_bundle,
                    defaulted_scope=_default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_suite_failure_ranking_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "suite_failure_ranking",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _suite_failure_ranking_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=[
                        "What is causing failures in the top suite?",
                        "Which engineer owns the most flaky tests?",
                        "What should I fix first?",
                    ],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        trend_query_kind = _trend_query_kind(body.question)
        if trend_query_kind is not None:
            from qalens.analyzers.flaky import FlakyScorer
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if not available_runs:
                    return AskResponse(
                        answer="I could not find any runs in the available QA Lens data for this project.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label, default_scoped, has_window_phrase = _trend_scope(body.question, len(available_runs))
                scorer = FlakyScorer(conn)
                suite_map = repo.get_latest_suite_per_canonical_name(project=body.project)
                owners = _load_known_owners(conn, project=body.project)
                explicit_owner = _explicit_owner_constraint(body.question)
                owner_focus = _extract_owner_from_question(body.question, owners)
                if explicit_owner and owner_focus is None:
                    return AskResponse(
                        answer=f'I could not find an owner named "{explicit_owner}" in the available QA Lens data for this project.',
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )
                results = scorer.get_all(
                    project=body.project,
                    min_runs=2,
                    limit_per_test=max(limit, 2),
                )
                for item in results:
                    setattr(item, "suite", suite_map.get(item.canonical_name, ""))
                if owner_focus is not None:
                    results = [item for item in results if _normalize_text(getattr(item, "owner", "") or "") == _normalize_text(owner_focus)]

                query_threshold = (
                    _trend_threshold(
                        body.question,
                        default_threshold=0.90 if trend_query_kind == "high_pass_rate" else 0.60,
                    )
                    if trend_query_kind in {"low_pass_rate", "low_pass_rate_and_failure_count", "high_pass_rate"}
                    else None
                )
                fail_count_threshold = (
                    _trend_fail_count_threshold(body.question)
                    if trend_query_kind == "low_pass_rate_and_failure_count"
                    else None
                )
                latest = available_runs[0]
                latest_run_label = f"Run #{latest.run_sequence}" if latest.run_sequence else latest.run_id
                actual_run_count = min(len(available_runs), max(limit, 1))
                result = _build_stability_trend_result(
                    kind=trend_query_kind,
                    scope_label=scope_label,
                    run_count=actual_run_count,
                    query_threshold=query_threshold,
                    fail_count_threshold=fail_count_threshold,
                    results=results,
                    total_evaluated=len(results),
                    latest_run_label=latest_run_label,
                )
                if owner_focus is not None:
                    result["subtitle"] = f"QA Lens stability analysis for {owner_focus} across {scope_label.lower()}."
                    result["query"]["label"] = f'{result["query"]["label"]} owned by {owner_focus}'
                follow_ups = [
                    "Which tests are flaky in the last 10 runs?",
                    "Show tests with pass rate below 60%",
                    "Which tests failed after previously passing?",
                ]
                if default_scoped and not has_window_phrase:
                    follow_ups = [
                        "Which tests are flaky in the last 10 runs?",
                        "Identify unstable tests across all runs",
                        "Which test has the highest failure frequency?",
                    ]

                fact_bundle = _stability_trend_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "stability_trend",
                    fact_bundle,
                    defaulted_scope=default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_stability_trend_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "stability_trend",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _stability_trend_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=follow_ups[:3],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _run_comparison_question(body.question):
            from qalens.analyzers.comparison import ComparisonService, comparison_to_dict
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                svc = ComparisonService(conn)
                run_numbers = _extract_run_numbers(body.question)

                if len(run_numbers) >= 2:
                    selected_runs = []
                    for run_number in run_numbers[:2]:
                        run = repo.get_run_by_sequence(run_number, project=body.project)
                        if run is not None:
                            selected_runs.append(run)
                    if len(selected_runs) < 2:
                        missing = [str(n) for n in run_numbers[:2] if repo.get_run_by_sequence(n, project=body.project) is None]
                        return AskResponse(
                            answer=f"I could not find Run #{missing[0]} in the available QA Lens data." if missing else "I could not find both runs in the available QA Lens data.",
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[],
                        )
                    comparison_result = svc.compare_custom(
                        project=body.project,
                        run_ids=[run.run_id for run in selected_runs],
                    )
                    scope_label = f"Run #{selected_runs[0].run_sequence} vs Run #{selected_runs[1].run_sequence}"
                    default_scoped = False
                else:
                    available_runs = repo.list_runs(project=body.project, limit=5000)
                    if len(available_runs) < 2:
                        return AskResponse(
                            answer="I need at least two runs to compare failure changes.",
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[],
                        )
                    comparison_result = svc.compare_window(project=body.project, limit=2)
                    scope_label = "Last 2 runs"
                    default_scoped = True

                comparison = comparison_to_dict(comparison_result)
                result = _build_run_comparison_result(comparison, scope_label=scope_label)
                fact_bundle = _run_comparison_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "run_comparison",
                    fact_bundle,
                    defaulted_scope=default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_run_comparison_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "run_comparison",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _run_comparison_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=[
                        "What new failures were introduced?",
                        "Show recovered tests between these runs",
                        "Which tests are still failing in both runs?",
                    ],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _failure_trend_question(body.question):
            from qalens.analyzers.comparison import ComparisonService, comparison_to_dict
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                available_runs = repo.list_runs(project=body.project, limit=5000)
                if len(available_runs) < 2:
                    return AskResponse(
                        answer="I need at least two runs to determine whether failures are increasing or decreasing.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                limit, scope_label, default_scoped, _has_window_phrase = _trend_scope(body.question, len(available_runs))
                if limit < 2:
                    limit = 2
                    scope_label = "Last 2 runs"
                svc = ComparisonService(conn)
                comparison_result = svc.compare_window(project=body.project, limit=limit)
                comparison = comparison_to_dict(comparison_result)
                result = _build_failure_trend_result(comparison, scope_label=scope_label)
                fact_bundle = _failure_trend_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "failure_trend",
                    fact_bundle,
                    defaulted_scope=default_scoped,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_failure_trend_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "failure_trend",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _failure_trend_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=[
                        "What new failures were introduced?",
                        "Compare the latest two runs",
                        "Which tests are still failing most often?",
                    ],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        run_retrieval_kind = _run_retrieval_kind(body.question)
        if run_retrieval_kind is not None:
            from qalens.db.repository import RunRepository
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                repo = RunRepository(conn)
                run_number = _extract_run_number(body.question)
                latest_runs = repo.list_runs(project=body.project, limit=1) if run_number is None else []
                run = (
                    repo.get_run_by_sequence(run_number, project=body.project)
                    if run_number is not None
                    else (latest_runs[0] if latest_runs else None)
                )
                if run is None:
                    run_scope = f"Run #{run_number}" if run_number is not None else "the latest run"
                    return AskResponse(
                        answer=f"I could not find {run_scope} in the available QA Lens data.",
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )

                test_cases = repo.get_test_cases_for_run(run.run_id)
                result = _build_run_retrieval_result(run, test_cases, body.question)
                follow_ups = [
                    f"Show passed vs failed count for {result['run']['label']}",
                    f"List all failed test cases in {result['run']['label']}",
                    f"List all skipped tests in {result['run']['label']}",
                ]
                if result["tests"]:
                    follow_ups.append(f"What is the status of {result['tests'][0]['name']} in {result['run']['label']}?")

                fact_bundle = _run_retrieval_fact_bundle(result)
                narration_prompt = build_narration_prompt(
                    body.question,
                    "run_retrieval",
                    fact_bundle,
                    defaulted_scope=False,
                )
                start = time.monotonic()
                try:
                    answer = LLMClient(cfg).chat(
                        narration_prompt,
                        system_prompt=build_narration_system_prompt(),
                    )
                    answer = _finalize_run_retrieval_narration(answer, fact_bundle)
                    logger.info(
                        "narration: %s latency=%.2fs",
                        "run_retrieval",
                        time.monotonic() - start,
                    )
                except LLMError:
                    answer = _run_retrieval_summary(result)

                return AskResponse(
                    answer=answer,
                    context_mode="project",
                    sources=[],
                    intent=_answer_intent.value,
                    follow_ups=follow_ups[:3],
                    result=result,
                    uiHints={"activeTab": "results", "openWorkspace": True},
                )
            finally:
                conn.close()

        if _shared_suite_failure_question(body.question):
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                owners = _load_known_owners(conn, project=body.project)
                owner_pair = _owner_pair_from_history(body.question, body.history or [], owners)
                if owner_pair is not None:
                    owner_a, owner_b = owner_pair
                    limit = _comparison_window_limit_from_history(body.question, body.history or [])
                    comparison = _build_entity_comparison(
                        conn,
                        column="owner",
                        entity_a=owner_a,
                        entity_b=owner_b,
                        entity_c=None,
                        limit=limit,
                        project=body.project,
                        run_ids=None,
                    )
                    if comparison.get("rows"):
                        result = _build_shared_suite_failure_result(comparison, owner_a, owner_b)
                        fact_bundle = _shared_suite_failure_fact_bundle(result)
                        narration_prompt = build_narration_prompt(
                            body.question,
                            "shared_suite_failures",
                            fact_bundle,
                            defaulted_scope=False,
                        )
                        start = time.monotonic()
                        try:
                            answer = LLMClient(cfg).chat(
                                narration_prompt,
                                system_prompt=build_narration_system_prompt(),
                            )
                            answer = _finalize_shared_suite_failure_narration(answer, fact_bundle)
                            logger.info(
                                "narration: %s latency=%.2fs",
                                "shared_suite_failures",
                                time.monotonic() - start,
                            )
                        except LLMError:
                            answer = _shared_suite_failure_summary(result)
                        return AskResponse(
                            answer=answer,
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[
                                f"Which of {owner_a}'s tests are driving the current gap?",
                                f"Which of {owner_b}'s tests are driving the current gap?",
                                f"Show me the difference between {owner_a} and {owner_b}'s suites",
                            ],
                            result=result,
                            uiHints={"activeTab": "results", "openWorkspace": True},
                        )
            finally:
                conn.close()

        if _owner_failing_tests_question(body.question):
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                owners = _load_known_owners(conn, project=body.project)
                owner_focus = _extract_owner_from_question(body.question, owners)
                explicit_owner = _explicit_owner_constraint(body.question)
                if explicit_owner and owner_focus is None:
                    return AskResponse(
                        answer=f'I could not find an owner named "{explicit_owner}" in the available QA Lens data for this project.',
                        context_mode="project",
                        sources=[],
                        intent=_answer_intent.value,
                        follow_ups=[],
                    )
                if owner_focus is not None:
                    limit = _comparison_window_limit_from_history(body.question, body.history or [])
                    comparison = _build_entity_comparison(
                        conn,
                        column="owner",
                        entity_a=owner_focus,
                        entity_b=owner_focus,
                        entity_c=None,
                        limit=limit,
                        project=body.project,
                        run_ids=None,
                    )
                    if comparison.get("rows"):
                        result = _build_owner_failing_tests_result(comparison, owner_focus)
                        fact_bundle = _owner_test_gap_fact_bundle(result)
                        narration_prompt = build_narration_prompt(
                            body.question,
                            "owner_test_gap",
                            fact_bundle,
                            defaulted_scope=False,
                        )
                        start = time.monotonic()
                        try:
                            answer = LLMClient(cfg).chat(
                                narration_prompt,
                                system_prompt=build_narration_system_prompt(),
                            )
                            answer = _finalize_owner_test_gap_narration(answer)
                            logger.info(
                                "narration: %s latency=%.2fs",
                                "owner_test_gap",
                                time.monotonic() - start,
                            )
                        except LLMError:
                            answer = _owner_test_gap_summary(result)
                        return AskResponse(
                            answer=answer,
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[
                                f"Show the failure history for {result['tests'][0]['testName']}" if result["tests"] else f"Show {owner_focus}'s recent failure history",
                                f"Which suite is causing most of {owner_focus}'s regressions?",
                                f"Show flaky tests owned by {owner_focus}",
                            ],
                            result=result,
                            uiHints={"activeTab": "results", "openWorkspace": True, "selectedEntity": owner_focus},
                        )
            finally:
                conn.close()

        if _owner_focus_question(body.question):
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                owners = _load_known_owners(conn, project=body.project)
                owner_focus = _extract_owner_from_question(body.question, owners)
                owner_pair = _owner_pair_from_history(body.question, body.history or [], owners)
                if owner_focus is not None:
                    owner_peer = None
                    if owner_pair is not None:
                        owner_peer = owner_pair[1] if owner_pair[0] == owner_focus else owner_pair[0]
                    entity_b = owner_peer if owner_peer is not None else owner_focus
                    limit = _comparison_window_limit_from_history(body.question, body.history or [])
                    comparison = _build_entity_comparison(
                        conn,
                        column="owner",
                        entity_a=owner_focus,
                        entity_b=entity_b,
                        entity_c=None,
                        limit=limit,
                        project=body.project,
                        run_ids=None,
                    )
                    if comparison.get("rows"):
                        is_suite_focus = _owner_suite_regression_question(body.question)
                        result = (
                            _build_owner_suite_regression_result(comparison, owner_focus, owner_peer)
                            if is_suite_focus
                            else _build_owner_test_gap_result(comparison, owner_focus, owner_peer)
                        )
                        if is_suite_focus:
                            fact_bundle = _owner_suite_regression_fact_bundle(result)
                            narration_prompt = build_narration_prompt(
                                body.question,
                                "owner_suite_regressions",
                                fact_bundle,
                                defaulted_scope=False,
                            )
                            start = time.monotonic()
                            try:
                                answer = LLMClient(cfg).chat(
                                    narration_prompt,
                                    system_prompt=build_narration_system_prompt(),
                                )
                                answer = _finalize_owner_suite_regression_narration(answer)
                                logger.info(
                                    "narration: %s latency=%.2fs",
                                    "owner_suite_regressions",
                                    time.monotonic() - start,
                                )
                            except LLMError:
                                answer = _owner_suite_regression_summary(result)
                        else:
                            fact_bundle = _owner_test_gap_fact_bundle(result)
                            narration_prompt = build_narration_prompt(
                                body.question,
                                "owner_test_gap",
                                fact_bundle,
                                defaulted_scope=False,
                            )
                            start = time.monotonic()
                            try:
                                answer = LLMClient(cfg).chat(
                                    narration_prompt,
                                    system_prompt=build_narration_system_prompt(),
                                )
                                answer = _finalize_owner_test_gap_narration(answer)
                                logger.info(
                                    "narration: %s latency=%.2fs",
                                    "owner_test_gap",
                                    time.monotonic() - start,
                                )
                            except LLMError:
                                answer = _owner_test_gap_summary(result)
                        return AskResponse(
                            answer=answer,
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[
                                *(
                                    (
                                        f"Show the failure history for {result['suites'][0]['topTests'][0]['testName']}"
                                        if result["suites"] and result["suites"][0]["topTests"]
                                        else f"Show {owner_focus}'s recent failure history",
                                        f"Which of {owner_focus}'s tests are driving the current gap?",
                                        f"Compare {owner_focus}'s failure rates with {owner_peer}" if owner_peer else f"Compare {owner_focus}'s suites with another owner",
                                    )
                                    if is_suite_focus
                                    else (
                                        f"Show the failure history for {result['tests'][0]['testName']}" if result["tests"] else f"Show {owner_focus}'s recent failure history",
                                        f"Which suite is causing most of {owner_focus}'s regressions?",
                                        f"Compare {owner_focus}'s failure rates with {owner_peer}" if owner_peer else f"Compare {owner_focus}'s suites with another owner",
                                    )
                                ),
                            ],
                            result=result,
                            uiHints={"activeTab": "results", "openWorkspace": True, "selectedEntity": owner_focus},
                        )
            finally:
                conn.close()

        if _owner_pair_compare_question(body.question):
            from qalens.db.schema import get_connection, init_db

            conn = get_connection(db_path)
            try:
                init_db(conn)
                owners = _load_known_owners(conn, project=body.project)
                owner_pair = _extract_owner_pair(body.question, owners)
                if owner_pair is not None:
                    owner_a, owner_b = owner_pair
                    limit = _comparison_window_limit(body.question)
                    comparison = _build_entity_comparison(
                        conn,
                        column="owner",
                        entity_a=owner_a,
                        entity_b=owner_b,
                        entity_c=None,
                        limit=limit,
                        project=body.project,
                        run_ids=None,
                    )
                    if comparison.get("rows"):
                        is_suite_question = _suite_comparison_question(body.question)
                        result = (
                            _build_owner_suite_result(comparison, owner_a, owner_b)
                            if is_suite_question
                            else _build_owner_window_result(comparison, owner_a, owner_b)
                        )
                        if is_suite_question:
                            fact_bundle = _owner_suite_fact_bundle(result)
                            narration_prompt = build_narration_prompt(
                                body.question,
                                "owner_suite_comparison",
                                fact_bundle,
                                defaulted_scope=False,
                            )
                            start = time.monotonic()
                            try:
                                answer = LLMClient(cfg).chat(
                                    narration_prompt,
                                    system_prompt=build_narration_system_prompt(),
                                )
                                answer = _finalize_owner_suite_narration(answer)
                                logger.info(
                                    "narration: %s latency=%.2fs",
                                    "owner_suite_comparison",
                                    time.monotonic() - start,
                                )
                            except LLMError:
                                answer = _owner_suite_summary(result)
                        else:
                            fact_bundle = _owner_window_fact_bundle(result)
                            narration_prompt = build_narration_prompt(
                                body.question,
                                "owner_window_comparison",
                                fact_bundle,
                                defaulted_scope=_comparison_window_limit(body.question) == 10
                                and "last" not in _normalize_text(body.question)
                                and "latest" not in _normalize_text(body.question)
                                and "current run" not in _normalize_text(body.question),
                            )
                            start = time.monotonic()
                            try:
                                answer = LLMClient(cfg).chat(
                                    narration_prompt,
                                    system_prompt=build_narration_system_prompt(),
                                )
                                answer = _finalize_owner_window_narration(answer, fact_bundle)
                                logger.info(
                                    "narration: %s latency=%.2fs",
                                    "owner_window_comparison",
                                    time.monotonic() - start,
                                )
                            except LLMError:
                                answer = _owner_window_summary(result)
                        return AskResponse(
                            answer=answer,
                            context_mode="project",
                            sources=[],
                            intent=_answer_intent.value,
                            follow_ups=[
                                *((
                                    f"Which shared suites between {owner_a} and {owner_b} are failing most?",
                                    f"Show me {owner_a}'s suite-level regressions",
                                    f"Compare failure rates between {owner_a} and {owner_b}",
                                ) if is_suite_question else (
                                    f"Which of {owner_a}'s tests are driving the current gap?",
                                    f"Which of {owner_b}'s tests are driving the current gap?",
                                    f"Show me the suite differences between {owner_a} and {owner_b}",
                                )),
                            ],
                            result=result,
                            uiHints={"activeTab": "results", "openWorkspace": True},
                        )
            finally:
                conn.close()

        # Mine conversation history for a test name so follow-up questions like
        # "Which suite does this belong to?" resolve "this" to the right test.
        history_test = extract_test_from_history(body.history or [])

        # LLM-powered intent + entity extraction. Falls back to keyword matching
        # when the LLM is unavailable, so latency is only added when needed.
        _intent = parse_query_intent(body.question, config=cfg)

        # Semantic signal detection: replaces the old _RISK_PHRASES exact-match
        # check with a multi-signal approach that handles duration/stability/trend
        # questions in addition to pure risk/prediction queries.
        _signals = detect_signals(normalize_query(body.question))
        _routed_ctx, _routed_facts, _routed_src, _routed_mode = gather_context_for_signals(
            _signals,
            body.question,
            project=body.project,
            db_path=db_path,
            intent=_intent,
            answer_plan=_answer_plan,
        )
        _structured_facts: str | None = _routed_facts if _routed_facts else None

        if _routed_ctx:
            # Signals routing fired (risk / duration / stability / trend)
            context, sources, mode = _routed_ctx, _routed_src, _routed_mode
        elif mode == "project":
            # Try date-filtered context first; fall back to generic project context
            date_result = gather_date_context(
                body.question, project=body.project, db_path=db_path
            )
            if date_result is not None:
                context, sources = date_result
            else:
                context, sources = gather_project_context(project=body.project, db_path=db_path)
        else:
            # Try the literal question first
            context, sources = gather_test_context(
                body.question, project=body.project, db_path=db_path
            )
            # If nothing matched (fix: actual return string is "No test matching")
            if not context.strip() or "No test matching" in context:
                # Before falling back to project, try the test name from history
                if history_test:
                    context, sources = gather_test_context(
                        history_test, project=body.project, db_path=db_path
                    )
            # Still nothing — fall back to project context
            if not context.strip() or "No test matching" in context:
                mode = "project"
                date_result = gather_date_context(
                    body.question, project=body.project, db_path=db_path
                )
                if date_result is not None:
                    context, sources = date_result
                else:
                    context, sources = gather_project_context(project=body.project, db_path=db_path)
                    # Prune sources: when we fell back from a test question,
                    # the generic flaky/broken/group cards are not relevant.
                    # Keep only run card(s) to give the LLM run-level context.
                    if history_test or mode == "project":
                        sources = [s for s in sources if s.get("type") == "run"][:2]

        if (
            _answer_plan.intent == AnswerIntent.RANKING_LIST
            and _answer_plan.ranking_metric == RankingMetric.RISK
        ):
            scope_label = (
                _answer_plan.default_scope.description
                if _answer_plan.default_scope is not None
                else "Selected run window"
            )
            fact_bundle = gather_risk_ranking_fact_bundle(
                project=body.project,
                db_path=db_path,
                top_n=_answer_plan.max_results or 20,
                min_runs=2,
                scope_label=scope_label,
            )
            narration_prompt = build_narration_prompt(
                body.question,
                "risk_ranking",
                fact_bundle,
                defaulted_scope=_answer_plan.default_scope is not None,
            )
            start = time.monotonic()
            try:
                answer = LLMClient(cfg).chat(
                    narration_prompt,
                    system_prompt=build_narration_system_prompt(),
                )
                answer = _finalize_risk_ranking_narration(answer, fact_bundle)
                logger.info(
                    "narration: %s latency=%.2fs",
                    "risk_ranking",
                    time.monotonic() - start,
                )
            except LLMError:
                answer = _risk_ranking_fallback_summary(fact_bundle)

            return AskResponse(
                answer=answer,
                context_mode=mode,
                sources=sources,
                intent=_answer_intent.value,
                follow_ups=_generate_chips(_answer_plan, sources, question=body.question),
                result=_risk_ranking_result_from_fact_bundle(fact_bundle),
                uiHints={"activeTab": "results", "openWorkspace": True},
            )

        if _answer_plan.intent == AnswerIntent.RECOMMENDATION_ACTION:
            scope_label = (
                _answer_plan.default_scope.description
                if _answer_plan.default_scope is not None
                else "Selected run window"
            )
            fact_bundle = gather_risk_ranking_fact_bundle(
                project=body.project,
                db_path=db_path,
                top_n=_answer_plan.max_results or 5,
                min_runs=2,
                scope_label=scope_label,
            )
            result = _risk_ranking_result_from_fact_bundle(
                fact_bundle,
                title="What to fix first",
                subtitle="Prioritized by predicted failure risk and historical stability signals",
            )
            narration_prompt = build_narration_prompt(
                body.question,
                "risk_ranking",
                fact_bundle,
                defaulted_scope=_answer_plan.default_scope is not None,
            )
            start = time.monotonic()
            try:
                answer = LLMClient(cfg).chat(
                    narration_prompt,
                    system_prompt=build_narration_system_prompt(),
                )
                answer = _finalize_risk_ranking_narration(answer, fact_bundle)
                answer = _strip_scope_refinement_footer(answer)
                logger.info(
                    "narration: %s latency=%.2fs",
                    "fix_first",
                    time.monotonic() - start,
                )
            except LLMError:
                answer = _fix_first_fallback_summary(fact_bundle)

            return AskResponse(
                answer=answer,
                context_mode=mode,
                sources=sources,
                intent=_answer_intent.value,
                follow_ups=[
                    "Which of these tests are flaky?",
                    "Which suite is causing the most failures?",
                    "What is the root cause of these failures?",
                ],
                result=result,
                uiHints={"activeTab": "results", "openWorkspace": True},
            )

        prompt = build_prompt(
            body.question,
            context,
            mode=mode,
            history=body.history or [],
            answer_plan=_answer_plan,
            structured_facts=_structured_facts,
        )
        try:
            answer = LLMClient(cfg).chat(
                prompt, system_prompt=build_system_prompt(_answer_plan)
            )
            answer = _strip_scope_refinement_footer(answer)
        except LLMError:
            answer = _deterministic_context_answer(
                question=body.question,
                context=context,
                mode=mode,
                structured_facts=_structured_facts,
            )
            answer = _strip_scope_refinement_footer(answer)

        return AskResponse(
            answer=answer,
            context_mode=mode,
            sources=sources,
            intent=_answer_intent.value,
            follow_ups=_generate_chips(_answer_plan, sources, question=body.question),
        )

    @router.get("/api/llm/info", tags=["llm"])
    async def llm_info() -> dict:
        """Return the active LLM provider and model name."""
        from qalens.llm.config import load_config
        cfg = load_config(None if cfg_path is None else Path(cfg_path))
        return {"provider": cfg.provider, "model": cfg.model}

    return router


def _generate_chips(answer_plan, sources, *, question: str = ""):
    from qalens.llm.followups import generate_follow_ups
    return generate_follow_ups(answer_plan, sources, question=question)


def _strip_scope_refinement_footer(answer: str) -> str:
    """Remove legacy scope/refinement footer sections from chat answers."""
    patterns = (
        r"\n+\s*#{1,6}\s*Scope used\b.*$",
        r"\n+\s*\*\*Scope used\*\*\s*.*$",
        r"\n+\s*Scope used\s*\n.*$",
        r"\n+\s*#{1,6}\s*Want something more specific\??\b.*$",
        r"\n+\s*\*\*Want something more specific\??\*\*\s*.*$",
        r"\n+\s*Want something more specific\??\s*\n.*$",
    )
    stripped = answer.strip()
    for pattern in patterns:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE | re.DOTALL).strip()
    return stripped
