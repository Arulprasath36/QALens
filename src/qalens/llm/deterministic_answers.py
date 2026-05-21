"""Deterministic natural-language answers backed directly by QA Lens SQLite data.

These handlers cover factual aggregate questions where the database is the
source of truth and an LLM would only add latency or risk misrouting.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict, cast

from qalens.analyzers.canonical import to_canonical_name
from qalens.analyzers.categorizer import FailureCategory, categorize_failure
from qalens.db.schema import get_connection, init_db

if TYPE_CHECKING:
    from pathlib import Path


AnswerHandler = Callable[[sqlite3.Connection, str, str | None], str | None]


class FailurePattern(TypedDict):
    """Dominant failure signature extracted from recent test history."""

    error_type: str | None
    message: str | None
    count: int


class FixPlaybook(TypedDict):
    """Structured remediation guidance for a failure category."""

    diagnosis: str
    causes: list[str]
    checks: list[str]
    fix: str
    verification: list[str]


def answer_question(
    question: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> str | None:
    """Return a deterministic answer for supported factual questions."""
    normalized = _normalize(question)
    handlers: tuple[AnswerHandler, ...] = (
        _test_fix_playbook_answer,
        _latest_failures_answer,
        _new_failures_answer,
        _module_failure_ranking_answer,
        _owner_flaky_tests_answer,
        _owner_failure_ranking_answer,
        _flaky_tests_answer,
        _slowest_tests_answer,
        _recurring_failures_answer,
        _run_pass_rate_extrema_answer,
        _summary_answer,
    )

    conn = get_connection(db_path)
    try:
        init_db(conn)
        for handler in handlers:
            answer = handler(conn, normalized, project)
            if answer is not None:
                return answer
    finally:
        conn.close()
    return None


def answer_test_fix_question(
    question: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> str | None:
    """Return a deterministic test-fix playbook when the question asks for one."""
    normalized = _normalize(question)
    if not _is_test_fix_question(normalized):
        return None
    conn = get_connection(db_path)
    try:
        init_db(conn)
        return _test_fix_playbook_answer(conn, normalized, project)
    finally:
        conn.close()


def answer_test_fix_payload(
    question: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return a concise answer plus workspace payload for a test-fix question."""
    normalized = _normalize(question)
    if not _is_test_fix_question(normalized):
        return None
    conn = get_connection(db_path)
    try:
        init_db(conn)
        payload = _test_fix_playbook_payload(conn, normalized, project)
        if payload is None:
            return None
        if payload.get("hasActiveFailure") is False:
            return {
                "answer": payload["summary"],
                "result": payload,
            }
        return {
            "answer": (
                f"I found a likely fix path for `{payload['testName']}`: "
                f"{payload['diagnosis']}. Open the workspace for the checklist, "
                "recommended fix, and verification steps."
            ),
            "result": payload,
        }
    finally:
        conn.close()


def _normalize(question: str) -> str:
    return " ".join(question.casefold().strip().split())


def _project_filter(
    alias: str,
    project: str | None,
    *,
    prefix: str = "WHERE",
) -> tuple[str, list[str]]:
    if not project:
        return "", []
    return f"{prefix} {alias}.project = ?", [project]


def _latest_run(conn: sqlite3.Connection, project: str | None) -> sqlite3.Row | None:
    where, params = _project_filter("r", project)
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            f"""
            SELECT r.*
            FROM runs r
            {where}
            ORDER BY r.run_sequence DESC, r.ingested_at DESC, r.id DESC
            LIMIT 1
            """,
            params,
        ).fetchone(),
    )


def _previous_run(
    conn: sqlite3.Connection,
    project: str | None,
    latest: sqlite3.Row,
) -> sqlite3.Row | None:
    where = "WHERE r.run_sequence < ?"
    params: list[object] = [latest["run_sequence"]]
    if project:
        where += " AND r.project = ?"
        params.append(project)
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            f"""
            SELECT r.*
            FROM runs r
            {where}
            ORDER BY r.run_sequence DESC, r.ingested_at DESC, r.id DESC
            LIMIT 1
            """,
            params,
        ).fetchone(),
    )


def _run_label(run: sqlite3.Row) -> str:
    seq = run["run_sequence"]
    return f"Run #{seq}" if seq else str(run["run_id"])


def _test_fix_playbook_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    payload = _test_fix_playbook_payload(conn, question, project)
    if payload is None:
        return None
    if payload.get("hasActiveFailure") is False:
        return str(payload["summary"])

    lines = [
        f"Likely fix for `{payload['testName']}`",
        "",
        "Diagnosis",
        str(payload["summary"]),
    ]
    if payload.get("errorType"):
        lines.append(f"Error type: `{payload['errorType']}`")
    if payload.get("evidence"):
        lines.append(f"Evidence: {payload['evidence']}")
    lines.extend(
        [
            f"Observed in: {', '.join(payload['observedRuns'])}",
            "",
            "Most likely causes",
            *[f"- {item}" for item in payload["causes"]],
            "",
            "What to check first",
            *[f"- {item}" for item in payload["checks"]],
            "",
            "Recommended fix",
            str(payload["recommendedFix"]),
            "",
            "Verification steps",
            *[f"- {item}" for item in payload["verification"]],
            "",
            "Confidence / limits",
            str(payload["confidenceText"]),
        ]
    )
    return "\n".join(lines)


def _test_fix_playbook_payload(
    conn: sqlite3.Connection, question: str, project: str | None
) -> dict[str, Any] | None:
    if not _is_test_fix_question(question):
        return None

    target = _extract_test_name_from_question(question)
    if target is None:
        target = _infer_test_name_from_db(conn, question, project)
    if target is None:
        return None

    match = _resolve_test_match(conn, target, project)
    if match is None:
        return {
            "type": "test_fix_playbook",
            "title": "No matching test found",
            "testName": target,
            "hasActiveFailure": False,
            "summary": f"I could not find `{target}` in the QA Lens database.",
        }

    window = 10
    rows = _test_history_rows(conn, match["canonical_name"], project, window=window)
    if not rows:
        return {
            "type": "test_fix_playbook",
            "title": f"Likely fix for {match['display_name']}",
            "testName": match["display_name"],
            "hasActiveFailure": False,
            "summary": f"I could not find recent history for `{match['display_name']}`.",
        }

    failures = [row for row in rows if row["status"] in ("failed", "broken")]
    display_name = match["display_name"]
    if not failures:
        return {
            "type": "test_fix_playbook",
            "title": f"Likely fix for {display_name}",
            "testName": display_name,
            "hasActiveFailure": False,
            "summary": (
                f"`{display_name}` has no failed or broken executions in the last "
                f"{len(rows)} run(s). There is no active failure pattern for QA Lens to triage."
            ),
            "scope": {"windowRuns": len(rows), "failedRuns": 0},
        }

    primary = _dominant_failure_pattern(failures)
    category = categorize_failure(
        error_type=primary["error_type"],
        message=primary["message"],
    )
    playbook = _playbook_for_failure(
        category=category,
        error_type=primary["error_type"],
        message=primary["message"],
    )
    failed_runs = ", ".join(
        _format_run_sequence(row["run_sequence"], row["run_id"]) for row in failures[:8]
    )
    confidence = _confidence(len(failures), len(rows), primary["count"])

    confidence_text = (
        f"{confidence}: QA Lens is using the last {len(rows)} run(s), "
        f"{len(failures)} failure occurrence(s), and stored error details. "
        "It cannot inspect your application source code from this database, "
        "so treat file-level fixes as checklists rather than exact patches."
    )
    return {
        "type": "test_fix_playbook",
        "title": f"Likely fix for {display_name}",
        "subtitle": "Evidence-backed triage checklist from recent QA Lens runs",
        "testName": display_name,
        "hasActiveFailure": True,
        "diagnosis": playbook["diagnosis"],
        "summary": (
            f"`{display_name}` failed {len(failures)} time(s) across the last "
            f"{len(rows)} recorded run(s). The dominant failure pattern is "
            f"{playbook['diagnosis']}."
        ),
        "errorType": primary["error_type"],
        "evidence": primary["message"],
        "observedRuns": [part.strip() for part in failed_runs.split(",") if part.strip()],
        "causes": playbook["causes"],
        "checks": playbook["checks"],
        "recommendedFix": playbook["fix"],
        "verification": playbook["verification"],
        "confidence": confidence.replace(" confidence", ""),
        "confidenceText": confidence_text,
        "scope": {
            "windowRuns": len(rows),
            "failedRuns": len(failures),
            "dominantOccurrences": primary["count"],
        },
    }


def _is_test_fix_question(question: str) -> bool:
    return (
        re.search(r"\b(fix|repair|resolve|debug|triage|investigate)\b", question) is not None
        and (
            _extract_test_name_from_question(question) is not None
            or re.search(r"\b(test|spec|scenario)\b", question) is not None
        )
    )


def _extract_test_name_from_question(question: str) -> str | None:
    paren_match = re.search(r"\b([a-zA-Z_][\w.$#]*test[\w.$#]*\(\))\b", question)
    if paren_match:
        return paren_match.group(1)
    camel_match = re.search(r"\b(test[A-Za-z0-9_.$#]+)\b", question, re.IGNORECASE)
    if camel_match:
        candidate = camel_match.group(1)
        if candidate.lower() not in {"test", "tests"}:
            return candidate
    return None


def _infer_test_name_from_db(
    conn: sqlite3.Connection,
    question: str,
    project: str | None,
) -> str | None:
    query_tokens = {
        token
        for token in to_canonical_name(question).split()
        if len(token) >= 3
        and token
        not in {
            "can",
            "could",
            "debug",
            "fix",
            "help",
            "how",
            "investigate",
            "please",
            "repair",
            "resolve",
            "scenario",
            "should",
            "spec",
            "test",
            "triage",
            "what",
        }
    }
    if not query_tokens:
        return None

    where = ""
    params: list[object] = []
    if project:
        where = "WHERE r.project = ?"
        params.append(project)
    rows = conn.execute(
        f"""
        SELECT tc.name, tc.canonical_name, COUNT(*) AS runs
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        {where}
        GROUP BY tc.canonical_name
        ORDER BY runs DESC
        LIMIT 500
        """,
        params,
    ).fetchall()

    best_name: str | None = None
    best_score = 0
    for row in rows:
        name = str(row["name"])
        canonical = str(row["canonical_name"])
        haystack = f"{canonical} {to_canonical_name(name)}"
        score = sum(1 for token in query_tokens if token in haystack)
        if score > best_score:
            best_score = score
            best_name = name

    return best_name if best_score >= 2 else None


def _resolve_test_match(
    conn: sqlite3.Connection,
    target: str,
    project: str | None,
) -> sqlite3.Row | None:
    target_canonical = to_canonical_name(target)
    where = "WHERE tc.canonical_name = ?"
    params: list[object] = [target_canonical]
    if project:
        where += " AND r.project = ?"
        params.append(project)
    row = conn.execute(
        f"""
        SELECT tc.canonical_name, MAX(tc.name) AS display_name, COUNT(*) AS runs
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        {where}
        GROUP BY tc.canonical_name
        ORDER BY runs DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is not None:
        return cast("sqlite3.Row", row)

    where = "WHERE tc.canonical_name LIKE ?"
    params = [f"%{target_canonical}%"]
    if project:
        where += " AND r.project = ?"
        params.append(project)
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            f"""
            SELECT tc.canonical_name, MAX(tc.name) AS display_name, COUNT(*) AS runs
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            {where}
            GROUP BY tc.canonical_name
            ORDER BY runs DESC
            LIMIT 1
            """,
            params,
        ).fetchone(),
    )


def _test_history_rows(
    conn: sqlite3.Connection,
    canonical_name: str,
    project: str | None,
    *,
    window: int,
) -> list[sqlite3.Row]:
    where = "WHERE tc.canonical_name = ?"
    params: list[object] = [canonical_name]
    if project:
        where += " AND r.project = ?"
        params.append(project)
    return conn.execute(
        f"""
        SELECT
            tc.name,
            tc.status,
            tc.suite,
            tc.owner,
            r.run_id,
            r.run_sequence,
            f.error_type,
            f.message,
            f.stack_trace
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        LEFT JOIN failures f ON f.tc_id = tc.tc_id
        {where}
        ORDER BY r.run_sequence DESC, r.ingested_at DESC, r.id DESC
        LIMIT ?
        """,
        [*params, window],
    ).fetchall()


def _dominant_failure_pattern(failures: list[sqlite3.Row]) -> FailurePattern:
    grouped: dict[tuple[str, str], FailurePattern] = {}
    for row in failures:
        error_type = str(row["error_type"]) if row["error_type"] else None
        message = str(row["message"]).splitlines()[0][:240] if row["message"] else None
        key_error = error_type or ""
        key_message = message or ""
        key = (key_error, key_message)
        if key not in grouped:
            grouped[key] = {
                "error_type": error_type,
                "message": message,
                "count": 0,
            }
        grouped[key]["count"] += 1
    return max(
        grouped.values(),
        key=lambda item: (item["count"], str(item["error_type"]), str(item["message"])),
    )


def _format_run_sequence(run_sequence: int | None, run_id: str) -> str:
    return f"#{run_sequence}" if run_sequence else run_id


def _confidence(failure_count: int, run_count: int, dominant_count: int) -> str:
    if failure_count >= 3 and dominant_count >= 2:
        return "High confidence"
    if failure_count >= 2 or (run_count >= 5 and dominant_count >= 1):
        return "Medium confidence"
    return "Low confidence"


def _playbook_for_failure(
    *,
    category: FailureCategory,
    error_type: object,
    message: object,
) -> FixPlaybook:
    error_text = f"{error_type or ''} {message or ''}".lower()
    if "connectionpool" in error_text or "connection pool" in error_text or "pool_size" in error_text:
        return {
            "diagnosis": "database connection pool exhaustion",
            "causes": [
                "The add-to-cart path may be leaking database connections or sessions.",
                "Test parallelism may exceed the configured pool size.",
                "A failing code path may skip cleanup and leave a connection checked out.",
                "The test environment pool size may be too small for current concurrency.",
            ],
            "checks": [
                "Inspect the add-to-cart service/repository code for connection/session cleanup.",
                "Check test setup and teardown for unclosed DB sessions after failures.",
                "Compare CI worker count against the database pool size.",
                "Check DB pool metrics before, during, and after the cart suite.",
            ],
            "fix": (
                "Fix connection lifecycle first: use context managers/finally blocks, close sessions "
                "on every success and failure path, and clean up test fixtures. Increase pool_size only "
                "after confirming connections are released correctly and concurrency legitimately needs it."
            ),
            "verification": [
                "Run the test alone and confirm it passes.",
                "Run the full cart suite in parallel and watch active DB connections.",
                "Repeat the suite several times and confirm active connections return to baseline.",
                "Re-ingest the new run and confirm this failure signature no longer appears.",
            ],
        }
    if category == FailureCategory.ELEMENT_NOT_FOUND:
        return {
            "diagnosis": "UI locator or page-state mismatch",
            "causes": [
                "The element selector may be stale or too brittle.",
                "The page may not have reached the expected state before the assertion/action.",
                "The add-to-cart UI may render differently for this browser, device, or data state.",
            ],
            "checks": [
                "Inspect the selector used by this test and prefer stable data-test IDs.",
                "Check whether the product/cart page finished loading before the click/assertion.",
                "Open screenshots or HTML logs from the failing run if available.",
                "Compare the failing run environment against passing runs.",
            ],
            "fix": (
                "Use a stable locator and wait for the user-visible cart state that proves the page is ready. "
                "Avoid fixed sleeps; wait on the specific button, cart badge, or network completion signal."
            ),
            "verification": [
                "Run the test against the same browser/environment as the failed run.",
                "Run the full suite to ensure the selector is not order-dependent.",
                "Confirm screenshots/logs show the cart item present after the fix.",
            ],
        }
    if category == FailureCategory.TIMEOUT:
        return {
            "diagnosis": "timeout or performance wait failure",
            "causes": [
                "The cart flow may be slower than the current wait budget.",
                "A backend/API dependency may be delayed.",
                "The test may wait on a broad condition instead of the exact cart-ready signal.",
            ],
            "checks": [
                "Check duration trends for this test and related cart/API calls.",
                "Inspect logs for slow product, inventory, or cart endpoints.",
                "Review waits in the test for fixed sleeps or overly broad conditions.",
            ],
            "fix": (
                "Wait on the precise readiness signal and investigate backend latency before increasing "
                "timeouts. Increase timeout only when the slower behavior is expected and acceptable."
            ),
            "verification": [
                "Run with timing logs enabled.",
                "Confirm the awaited condition is reached consistently.",
                "Re-run under normal CI parallelism.",
            ],
        }
    if category == FailureCategory.ASSERTION:
        return {
            "diagnosis": "product behavior or test expectation mismatch",
            "causes": [
                "The cart behavior may have changed while the assertion still expects the old result.",
                "The test data may not satisfy the expectation.",
                "The assertion may run before the cart state is fully updated.",
            ],
            "checks": [
                "Compare expected vs actual values in the failure message.",
                "Check whether the cart API/UI changed recently.",
                "Verify product inventory, pricing, and promotion test data.",
            ],
            "fix": (
                "Update the product behavior or the test expectation after confirming which one is wrong. "
                "If the assertion is racing the UI, wait for the final cart state before asserting."
            ),
            "verification": [
                "Run the test with known-good cart data.",
                "Validate the cart state through UI and API if both are available.",
                "Re-run the affected suite after the expectation/code change.",
            ],
        }
    if category == FailureCategory.TEST_DATA:
        return {
            "diagnosis": "test data or database state problem",
            "causes": [
                "The product/cart fixture may be missing, duplicated, or already consumed.",
                "Database state may not be reset between runs.",
                "The test may depend on shared mutable data.",
            ],
            "checks": [
                "Inspect product, inventory, user, and cart fixture setup.",
                "Verify cleanup resets cart/database state after every run.",
                "Check whether parallel tests share the same user or product data.",
            ],
            "fix": (
                "Make the test data isolated and repeatable: unique users/carts per test, deterministic "
                "fixtures, and teardown that resets database state."
            ),
            "verification": [
                "Run the test repeatedly with fresh data.",
                "Run it in parallel with related cart tests.",
                "Confirm no fixture rows are reused unexpectedly.",
            ],
        }
    return {
        "diagnosis": category.label.lower() if category != FailureCategory.UNKNOWN else "the recorded failure pattern",
        "causes": [
            "The same failure details are recurring for this test.",
            "The root cause may be in the application path, test setup, or environment.",
        ],
        "checks": [
            "Inspect the top error message and stack trace from the failing runs.",
            "Compare failing runs with passing runs for environment, branch, and data differences.",
            "Check test setup/teardown for state leakage.",
        ],
        "fix": (
            "Start with the code path named by the stack trace and the setup data for this test. "
            "Make the smallest fix that removes the repeated failure signature, then re-run the target test and suite."
        ),
        "verification": [
            "Run the individual test.",
            "Run the owning suite.",
            "Re-ingest the run and confirm this failure pattern is gone.",
        ],
    }


def _latest_failures_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        ("latest run" in question or "last run" in question or "most recent run" in question)
        and re.search(r"\b(broke|broken|fail|failed|failing|failures)\b", question)
    ):
        return None

    latest = _latest_run(conn, project)
    if latest is None:
        return "I could not find any runs in the QA Lens database."

    rows = conn.execute(
        """
        SELECT name, suite, owner, status
        FROM test_cases
        WHERE run_id = ? AND status IN ('failed', 'broken')
        ORDER BY suite, name
        LIMIT 20
        """,
        (latest["run_id"],),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM test_cases WHERE run_id = ?",
        (latest["run_id"],),
    ).fetchone()[0]
    if not rows:
        return f"{_run_label(latest)} has no failed or broken tests ({total} total tests)."

    lines = [
        f"{_run_label(latest)} has {len(rows)} failed or broken tests out of {total} total tests."
    ]
    lines.append("")
    lines.append("Failures in the latest run:")
    for row in rows:
        owner = f", owner {row['owner']}" if row["owner"] else ""
        suite = f" [{row['suite']}]" if row["suite"] else ""
        lines.append(f"- {row['name']}{suite}: {row['status']}{owner}")
    return "\n".join(lines)


def _new_failures_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        ("new" in question or "newly" in question or "introduced" in question or "regression" in question)
        and re.search(r"\b(fail|failed|failing|failures?|regressions?)\b", question)
    ):
        return None

    latest = _latest_run(conn, project)
    if latest is None:
        return "I could not find any runs in the QA Lens database."
    previous = _previous_run(conn, project, latest)
    if previous is None:
        return "I need at least two runs to identify newly failing tests."

    rows = conn.execute(
        """
        SELECT cur.name, cur.suite, cur.owner, cur.status AS current_status, prev.status AS previous_status
        FROM test_cases cur
        LEFT JOIN test_cases prev
          ON prev.run_id = ?
         AND prev.canonical_name = cur.canonical_name
        WHERE cur.run_id = ?
          AND cur.status IN ('failed', 'broken')
          AND COALESCE(prev.status, '') NOT IN ('failed', 'broken')
        ORDER BY cur.suite, cur.name
        LIMIT 20
        """,
        (previous["run_id"], latest["run_id"]),
    ).fetchall()
    if not rows:
        return f"No newly failing tests were introduced in {_run_label(latest)} versus {_run_label(previous)}."

    lines = [
        f"{len(rows)} tests newly failed in {_run_label(latest)} versus {_run_label(previous)}.",
        "",
        "New failures:",
    ]
    for row in rows:
        suite = f" [{row['suite']}]" if row["suite"] else ""
        previous_status = row["previous_status"] or "not present"
        lines.append(f"- {row['name']}{suite}: {previous_status} -> {row['current_status']}")
    return "\n".join(lines)


def _module_failure_ranking_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        ("module" in question or "suite" in question)
        and re.search(r"\b(failure|failures|failed|fail|rate|percentage|percent)\b", question)
        and re.search(r"\b(highest|higher|most|top|worst)\b", question)
    ):
        return None

    where = "WHERE tc.suite IS NOT NULL AND TRIM(tc.suite) != ''"
    params: list[str] = []
    if project:
        where += " AND r.project = ?"
        params.append(project)
    order_metric = "failure_pct" if re.search(r"\b(percent|percentage|rate|higher|highest)\b", question) else "failures"
    rows = conn.execute(
        f"""
        SELECT
            tc.suite AS module,
            COUNT(*) AS total,
            SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failures,
            ROUND(100.0 * SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) / COUNT(*), 1) AS failure_pct
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        {where}
        GROUP BY tc.suite
        ORDER BY {order_metric} DESC, failures DESC, total DESC, module ASC
        LIMIT 5
        """,
        params,
    ).fetchall()
    if not rows:
        return None

    top = rows[0]
    metric_text = (
        f"highest failure percentage: {top['failure_pct']:.1f}%"
        if order_metric == "failure_pct"
        else f"most failures: {top['failures']}"
    )
    lines = [
        f"{top['module']} has the {metric_text} ({top['failures']} failures out of {top['total']} test results).",
        "",
        "Top modules:",
    ]
    for row in rows:
        lines.append(f"- {row['module']}: {row['failure_pct']:.1f}% ({row['failures']}/{row['total']})")
    return "\n".join(lines)


def _owner_flaky_tests_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        re.search(r"\b(who|owner|owns|owned|engineer)\b", question)
        and "flaky" in question
        and re.search(r"\b(most|highest|top|worst)\b", question)
    ):
        return None

    where = "WHERE tc.owner IS NOT NULL AND TRIM(tc.owner) != ''"
    params: list[str] = []
    if project:
        where += " AND r.project = ?"
        params.append(project)
    rows = conn.execute(
        f"""
        WITH owner_tests AS (
            SELECT
                tc.owner AS owner,
                tc.name AS name,
                COUNT(*) AS runs,
                SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failures,
                SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS passes
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            {where}
            GROUP BY tc.owner, tc.name
        ),
        flaky AS (
            SELECT * FROM owner_tests WHERE failures > 0 AND passes > 0
        )
        SELECT
            owner,
            COUNT(*) AS flaky_tests,
            SUM(failures) AS failures,
            SUM(runs) AS total_results,
            ROUND(100.0 * SUM(failures) / SUM(runs), 1) AS failure_pct
        FROM flaky
        GROUP BY owner
        ORDER BY flaky_tests DESC, failures DESC, failure_pct DESC, owner ASC
        LIMIT 5
        """,
        params,
    ).fetchall()
    if not rows:
        return None

    top = rows[0]
    lines = [
        (
            f"{top['owner']} owns the most flaky tests: {top['flaky_tests']} tests "
            f"with mixed pass/fail history ({top['failures']} failures across {top['total_results']} results)."
        ),
        "",
        "Top owners by flaky test count:",
    ]
    for row in rows:
        lines.append(
            f"- {row['owner']}: {row['flaky_tests']} flaky tests, "
            f"{row['failure_pct']:.1f}% failure rate ({row['failures']}/{row['total_results']})"
        )
    return "\n".join(lines)


def _owner_failure_ranking_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        re.search(r"\b(who|owner|owns|owned|engineer)\b", question)
        and re.search(r"\b(failure|failures|failed|fail|rate|percentage|percent)\b", question)
        and re.search(r"\b(most|highest|top|worst)\b", question)
    ):
        return None

    where = "WHERE tc.owner IS NOT NULL AND TRIM(tc.owner) != ''"
    params: list[str] = []
    if project:
        where += " AND r.project = ?"
        params.append(project)
    order_metric = "failure_pct" if re.search(r"\b(percent|percentage|rate|highest)\b", question) else "failures"
    rows = conn.execute(
        f"""
        SELECT
            tc.owner AS owner,
            COUNT(*) AS total,
            SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failures,
            ROUND(100.0 * SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) / COUNT(*), 1) AS failure_pct
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        {where}
        GROUP BY tc.owner
        ORDER BY {order_metric} DESC, failures DESC, total DESC, owner ASC
        LIMIT 5
        """,
        params,
    ).fetchall()
    if not rows:
        return None

    top = rows[0]
    lines = [
        f"{top['owner']} is highest by owner failure ranking: {top['failure_pct']:.1f}% ({top['failures']}/{top['total']}).",
        "",
        "Top owners:",
    ]
    for row in rows:
        lines.append(f"- {row['owner']}: {row['failure_pct']:.1f}% ({row['failures']}/{row['total']})")
    return "\n".join(lines)


def _flaky_tests_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        "flaky" in question
        and re.search(r"\b(test|tests)\b", question)
        and re.search(r"\b(most|top|highest|worst|which)\b", question)
    ):
        return None

    where, params = _project_filter("r", project, prefix="WHERE")
    rows = conn.execute(
        f"""
        WITH ordered AS (
            SELECT
                tc.name,
                tc.canonical_name,
                tc.status,
                r.run_sequence,
                LAG(tc.status) OVER (
                    PARTITION BY tc.canonical_name
                    ORDER BY r.run_sequence
                ) AS prev_status
            FROM test_cases tc
            JOIN runs r ON r.run_id = tc.run_id
            {where}
        ),
        agg AS (
            SELECT
                name,
                canonical_name,
                COUNT(*) AS runs,
                SUM(CASE WHEN status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failures,
                SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END) AS passes,
                SUM(CASE WHEN prev_status IS NOT NULL AND prev_status != status THEN 1 ELSE 0 END) AS flips
            FROM ordered
            GROUP BY canonical_name
        )
        SELECT
            name,
            runs,
            failures,
            flips,
            ROUND(100.0 * failures / runs, 1) AS failure_pct
        FROM agg
        WHERE failures > 0 AND passes > 0
        ORDER BY flips DESC, failure_pct DESC, failures DESC, name ASC
        LIMIT 10
        """,
        params,
    ).fetchall()
    if not rows:
        return None

    lines = [f"{rows[0]['name']} is the flakiest test by status flips ({rows[0]['flips']} flips).", "", "Top flaky tests:"]
    for row in rows[:5]:
        lines.append(
            f"- {row['name']}: {row['flips']} flips, {row['failure_pct']:.1f}% failure rate ({row['failures']}/{row['runs']})"
        )
    return "\n".join(lines)


def _slowest_tests_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        re.search(r"\b(slowest|slow|duration|longest|performance)\b", question)
        and re.search(r"\b(test|tests)\b", question)
    ):
        return None

    where = "WHERE tc.duration_ms IS NOT NULL"
    params: list[str] = []
    if project:
        where += " AND r.project = ?"
        params.append(project)
    rows = conn.execute(
        f"""
        SELECT
            tc.name,
            COUNT(*) AS runs,
            ROUND(AVG(tc.duration_ms), 0) AS avg_ms,
            MAX(tc.duration_ms) AS max_ms
        FROM test_cases tc
        JOIN runs r ON r.run_id = tc.run_id
        {where}
        GROUP BY tc.canonical_name
        ORDER BY avg_ms DESC, max_ms DESC, tc.name ASC
        LIMIT 5
        """,
        params,
    ).fetchall()
    if not rows:
        return None

    top = rows[0]
    lines = [f"{top['name']} is the slowest test on average ({top['avg_ms'] / 1000:.2f}s).", "", "Top slowest tests:"]
    for row in rows:
        lines.append(f"- {row['name']}: avg {row['avg_ms'] / 1000:.2f}s, max {row['max_ms'] / 1000:.2f}s over {row['runs']} runs")
    return "\n".join(lines)


def _recurring_failures_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not (
        re.search(r"\b(recurring|repeat|repeated|common)\b", question)
        and re.search(r"\b(failure|failures|error|errors)\b", question)
    ):
        return None

    where = "WHERE tc.status IN ('failed', 'broken')"
    params: list[str] = []
    if project:
        where += " AND r.project = ?"
        params.append(project)
    rows = conn.execute(
        f"""
        SELECT
            f.fingerprint,
            COALESCE(f.error_type, 'Unknown error') AS error_type,
            COUNT(*) AS occurrences,
            COUNT(DISTINCT r.run_id) AS affected_runs,
            COUNT(DISTINCT tc.canonical_name) AS affected_tests,
            MIN(tc.name) AS example_test
        FROM failures f
        JOIN test_cases tc ON tc.tc_id = f.tc_id
        JOIN runs r ON r.run_id = tc.run_id
        {where}
        GROUP BY f.fingerprint, f.error_type
        ORDER BY occurrences DESC, affected_runs DESC, affected_tests DESC
        LIMIT 5
        """,
        params,
    ).fetchall()
    if not rows:
        return None

    top = rows[0]
    lines = [
        (
            f"The most recurring failure is {top['error_type']} "
            f"({top['occurrences']} occurrences across {top['affected_runs']} runs)."
        ),
        "",
        "Top recurring failures:",
    ]
    for row in rows:
        lines.append(
            f"- {row['error_type']}: {row['occurrences']} occurrences, "
            f"{row['affected_tests']} tests; example `{row['example_test']}`"
        )
    return "\n".join(lines)


def _run_pass_rate_extrema_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not _is_run_pass_rate_extrema_question(question):
        return None

    limit = _run_window_limit(question)
    where, params = _project_filter("r", project, prefix="WHERE")
    rows = conn.execute(
        f"""
        WITH selected_runs AS (
            SELECT r.*
            FROM runs r
            {where}
            ORDER BY r.run_sequence DESC, r.ingested_at DESC, r.id DESC
            LIMIT ?
        )
        SELECT
            sr.run_id,
            sr.run_sequence,
            COUNT(tc.id) AS total_tests,
            SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS passed_count,
            SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failed_count
        FROM selected_runs sr
        LEFT JOIN test_cases tc ON tc.run_id = sr.run_id
        GROUP BY sr.run_id, sr.run_sequence
        ORDER BY sr.run_sequence DESC
        """,
        [*params, limit],
    ).fetchall()
    rows = [row for row in rows if int(row["total_tests"] or 0) > 0]
    if not rows:
        return "I could not find runs with test counts to calculate pass percentage."

    scored = [
        {
            "label": _format_run_sequence(row["run_sequence"], row["run_id"]),
            "rate": int(row["passed_count"] or 0) / int(row["total_tests"] or 1),
            "passed": int(row["passed_count"] or 0),
            "total": int(row["total_tests"] or 0),
        }
        for row in rows
    ]
    highest_rate = max(item["rate"] for item in scored)
    lowest_rate = min(item["rate"] for item in scored)
    highest = [item for item in scored if item["rate"] == highest_rate]
    lowest = [item for item in scored if item["rate"] == lowest_rate]

    is_failure_framing = any(
        phrase in question
        for phrase in (
            "failure rate", "fail rate", "failing rate",
            "failure percentage", "fail percentage",
            "fewest failures", "most failures", "fewest failed", "most failed",
        )
    )
    wants_highest = any(word in question for word in ("highest", "best", "maximum", "max", "fewest"))
    wants_lowest = any(word in question for word in ("lowest", "worst", "minimum", "min", "most"))
    if is_failure_framing:
        wants_highest, wants_lowest = wants_lowest, wants_highest
    if not wants_highest and not wants_lowest:
        wants_highest = wants_lowest = True

    metric = "failure percentage" if is_failure_framing else "pass percentage"
    lines = [f"I checked {metric} across the last {min(limit, len(scored))} run(s)."]
    if wants_highest:
        label = "Lowest failure percentage" if is_failure_framing else "Highest pass percentage"
        lines.append(f"{label}: {_format_extrema_items(highest)}.")
    if wants_lowest:
        label = "Highest failure percentage" if is_failure_framing else "Lowest pass percentage"
        lines.append(f"{label}: {_format_extrema_items(lowest)}.")
    lines.append("Pass percentage is passed tests divided by total tests in that run.")
    return "\n".join(lines)


def _is_run_pass_rate_extrema_question(question: str) -> bool:
    has_run_scope = "run" in question or "runs" in question
    has_pass_rate = any(
        phrase in question
        for phrase in (
            "pass rate", "pass percentage", "pass percent",
            "passing rate", "passing percentage", "passing percent", "pass %",
            "failure rate", "fail rate", "failing rate",
            "failure percentage", "fail percentage", "fail %",
            "fewest failures", "most failures", "fewest failed", "most failed",
            "performed best", "performed worst", "best performing", "worst performing",
            "best run", "worst run",
        )
    )
    has_extrema = any(
        word in question
        for word in (
            "highest", "lowest", "best", "worst",
            "maximum", "minimum", "max", "min",
            "fewest", "most",
        )
    )
    return has_run_scope and has_pass_rate and has_extrema


def _run_window_limit(question: str) -> int:
    match = re.search(r"\blast\s+(\d+)\s+runs?\b", question)
    if not match:
        return 10
    try:
        return max(1, int(match.group(1)))
    except ValueError:
        return 10


def _format_extrema_items(items: list[dict[str, Any]]) -> str:
    if len(items) == 1:
        item = items[0]
        return (
            f"Run {item['label']} at {_format_rate(item['rate'])} "
            f"({item['passed']}/{item['total']} passed)"
        )
    labels = ", ".join(f"Run {item['label']}" for item in items[:4])
    suffix = f", and {len(items) - 4} more" if len(items) > 4 else ""
    first = items[0]
    return (
        f"{labels}{suffix} tied at {_format_rate(first['rate'])} "
        f"({first['passed']}/{first['total']} passed)"
    )


def _format_rate(rate: float) -> str:
    value = round(rate * 100, 1)
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def _summary_answer(
    conn: sqlite3.Connection, question: str, project: str | None
) -> str | None:
    if not re.search(r"\b(summary|summarize|overview|health|status)\b", question):
        return None

    where, params = _project_filter("r", project, prefix="WHERE")
    totals = conn.execute(
        f"""
        SELECT
            COUNT(DISTINCT r.run_id) AS runs,
            COUNT(tc.id) AS total_results,
            SUM(CASE WHEN tc.status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failures,
            SUM(CASE WHEN tc.status = 'passed' THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN tc.status = 'skipped' THEN 1 ELSE 0 END) AS skipped
        FROM runs r
        LEFT JOIN test_cases tc ON tc.run_id = r.run_id
        {where}
        """,
        params,
    ).fetchone()
    if not totals or not totals["runs"]:
        return "I could not find any runs in the QA Lens database."

    latest = _latest_run(conn, project)
    latest_text = ""
    if latest is not None:
        latest_counts = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status IN ('failed', 'broken') THEN 1 ELSE 0 END) AS failures
            FROM test_cases
            WHERE run_id = ?
            """,
            (latest["run_id"],),
        ).fetchone()
        latest_text = (
            f"\nLatest run: {_run_label(latest)} had {latest_counts['failures']} "
            f"failures out of {latest_counts['total']} tests."
        )

    failure_pct = 100.0 * (totals["failures"] or 0) / max(totals["total_results"] or 1, 1)
    return (
        f"QA Lens has {totals['runs']} runs and {totals['total_results']} test results in this database. "
        f"Overall failures: {totals['failures']} ({failure_pct:.1f}%), "
        f"passed: {totals['passed']}, skipped: {totals['skipped']}."
        f"{latest_text}"
    )
