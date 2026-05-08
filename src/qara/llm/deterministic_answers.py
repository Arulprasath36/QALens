"""Deterministic natural-language answers backed directly by QARA SQLite data.

These handlers cover factual aggregate questions where the database is the
source of truth and an LLM would only add latency or risk misrouting.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Callable

from qara.db.schema import get_connection, init_db


AnswerHandler = Callable[[sqlite3.Connection, str, str | None], str | None]


def answer_question(
    question: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> str | None:
    """Return a deterministic answer for supported factual questions."""
    normalized = _normalize(question)
    handlers: tuple[AnswerHandler, ...] = (
        _latest_failures_answer,
        _new_failures_answer,
        _module_failure_ranking_answer,
        _owner_flaky_tests_answer,
        _owner_failure_ranking_answer,
        _flaky_tests_answer,
        _slowest_tests_answer,
        _recurring_failures_answer,
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


def _normalize(question: str) -> str:
    return " ".join(question.casefold().strip().split())


def _project_filter(alias: str, project: str | None, *, prefix: str = "WHERE") -> tuple[str, list[str]]:
    if not project:
        return "", []
    return f"{prefix} {alias}.project = ?", [project]


def _latest_run(conn: sqlite3.Connection, project: str | None) -> sqlite3.Row | None:
    where, params = _project_filter("r", project)
    return conn.execute(
        f"""
        SELECT r.*
        FROM runs r
        {where}
        ORDER BY r.run_sequence DESC, r.ingested_at DESC, r.id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()


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
    return conn.execute(
        f"""
        SELECT r.*
        FROM runs r
        {where}
        ORDER BY r.run_sequence DESC, r.ingested_at DESC, r.id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()


def _run_label(run: sqlite3.Row) -> str:
    seq = run["run_sequence"]
    return f"Run #{seq}" if seq else str(run["run_id"])


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
        return "I could not find any runs in the QARA database."

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
        return "I could not find any runs in the QARA database."
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
        return "I could not find any runs in the QARA database."

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
        f"QARA has {totals['runs']} runs and {totals['total_results']} test results in this database. "
        f"Overall failures: {totals['failures']} ({failure_pct:.1f}%), "
        f"passed: {totals['passed']}, skipped: {totals['skipped']}."
        f"{latest_text}"
    )
