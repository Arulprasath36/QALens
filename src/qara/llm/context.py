"""Database context fetcher for QARA LLM queries.

Pulls structured data from the QARA SQLite database and formats it as a
plain-text context block that can be injected into an LLM prompt.

Usage::

    from qara.llm.context import gather_test_context, gather_project_context

    ctx, sources = gather_test_context("testcreateorder", project="Allure Report")
    # ctx  → multi-line string describing the test's history and failures
    # sources → list of source dicts for the UI evidence cards
"""

from __future__ import annotations

import re
from pathlib import Path

# Sub-module re-exports (backward compatibility)
from qara.analyzers.canonical import to_canonical_name
from qara.llm.context_date import _MONTH_MAP, _extract_date, gather_date_context  # noqa: F401
from qara.llm.context_risk import (
    _RISK_PHRASES,
    _has_slowing_chip,
    gather_risk_context,
    is_risk_question,
)  # noqa: F401
from qara.llm.context_history import _TEST_NAME_RE, extract_test_from_history  # noqa: F401


# ---------------------------------------------------------------------------
# Test-level context
# ---------------------------------------------------------------------------


def gather_test_context(
    query: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
    limit: int = 30,
) -> tuple[str, list[dict]]:
    """Build a text context block for a specific test query.

    Returns:
        A tuple of (context_text, sources) where sources is a list of
        structured source dicts for UI evidence cards.
    """
    from qara.analyzers.canonical import to_canonical_name
    from qara.analyzers.categorizer import categorize_failure
    from qara.analyzers.flaky import FlakyScorer
    from qara.db.repository import RunRepository
    from qara.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        scorer = FlakyScorer(conn)

        # Find matching canonical names
        all_names = repo.get_all_canonical_names(project=project, min_runs=1)
        query_canonical = to_canonical_name(query)
        matches = [
            n for n in all_names
            if query_canonical in n["canonical_name"]
            or to_canonical_name(n["display_name"]) == query_canonical
        ]

        if not matches:
            # Fuzzy fallback — any token overlap
            tokens = set(query_canonical.split())
            matches = [
                n for n in all_names
                if tokens & set(n["canonical_name"].split())
            ]
            matches = matches[:3]  # cap at 3

        if not matches:
            return (
                f"No test matching '{query}' was found in the database"
                + (f" for project '{project}'" if project else "")
                + ".",
                [],
            )

        parts: list[str] = []
        sources: list[dict] = []

        for nm in matches[:5]:  # cap context size
            cname = nm["canonical_name"]
            result = scorer.score(cname, project=project, limit=limit)

            parts.append(f"=== Test: {result.display_name} ===")
            parts.append(f"Canonical name  : {result.canonical_name}")
            if project:
                parts.append(f"Project         : {project}")
            parts.append(f"Run history     : {result.run_count} run(s) (most recent {limit})")
            parts.append(f"Pass rate       : {result.pass_rate:.0%}")
            parts.append(f"Flip score      : {result.flip_score:.2f}")
            parts.append(f"Classification  : {result.classification.label}")
            parts.append(f"History (oldest→newest): {result.sparkline}  ({', '.join(result.history)})")
            if result.current_streak > 0:
                parts.append(f"Current streak  : {result.current_streak} consecutive pass(es)")
            elif result.current_streak < 0:
                parts.append(f"Current streak  : {abs(result.current_streak)} consecutive failure(s)")

            # Source card for this test
            sources.append({
                "type": "test",
                "icon": "🧪",
                "label": result.display_name,
                "meta": f"{result.classification.label} · {result.pass_rate:.0%} pass · {result.run_count} runs",
                "sparkline": result.sparkline,
                "canonical_name": result.canonical_name,
            })

            # Failure details
            history_entries = repo.get_test_history(cname, project=project, limit=limit)
            failure_entries = [e for e in history_entries if e.status in ("failed", "broken")]
            if failure_entries:
                failed_runs = ", ".join(f"#{e.run_sequence}" for e in failure_entries)
                parts.append(
                    f"\nIn the past {limit} runs, this test failed {len(failure_entries)} time(s)"
                    f" (run(s): {failed_runs}):"
                )
                seen_msgs: set[str] = set()
                for entry in failure_entries[:5]:
                    if entry.error_type or entry.message:
                        msg_key = f"{entry.error_type}:{(entry.message or '')[:60]}"
                        if msg_key in seen_msgs:
                            continue
                        seen_msgs.add(msg_key)
                        cat = categorize_failure(
                            error_type=entry.error_type,
                            message=entry.message,
                        )
                        parts.append(f"  Category  : {cat.label}")
                        if entry.error_type:
                            short_type = entry.error_type.split(".")[-1]
                            parts.append(f"  Error type: {short_type} ({entry.error_type})")
                        if entry.message:
                            first_line = entry.message.split("\n")[0][:200]
                            parts.append(f"  Message   : {first_line}")
                        if entry.stack_trace:
                            top = "\n".join(entry.stack_trace.strip().splitlines()[:5])
                            parts.append(f"  Stack (top):\n    {top.strip()}")
                        parts.append("")
            else:
                parts.append("No failure details recorded.")

            parts.append("")

    finally:
        conn.close()

    return "\n".join(parts).strip(), sources


# ---------------------------------------------------------------------------
# Project-level context
# ---------------------------------------------------------------------------


def gather_project_context(
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
    min_runs: int = 2,
    max_groups: int = 10,
) -> tuple[str, list[dict]]:
    """Build a project-wide context block for summary queries.

    Returns:
        A tuple of (context_text, sources) where sources is a list of
        structured source dicts for UI evidence cards.
    """
    from qara.analyzers.categorizer import categorize_failure
    from qara.analyzers.flaky import FlakyClassification, FlakyScorer
    from qara.db.repository import RunRepository
    from qara.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        scorer = FlakyScorer(conn)

        runs = repo.list_runs(project=project, limit=10_000)
        all_results = scorer.get_all(project=project, min_runs=min_runs)
        groups = repo.get_failure_groups(project=project, limit=max_groups)
        # Always include raw test results from the latest run so the LLM
        # can answer questions even when there is only one run (min_runs not met)
        latest_tests: list = []
        prev_tests: list = []
        if runs:
            latest_tests = repo.get_test_cases_for_run(runs[0].run_id)
        if len(runs) >= 2:
            prev_tests = repo.get_test_cases_for_run(runs[1].run_id)

    finally:
        conn.close()

    flaky = [r for r in all_results if r.classification == FlakyClassification.FLAKY]
    broken = [r for r in all_results if r.classification == FlakyClassification.CONSISTENTLY_BROKEN]
    stable = [r for r in all_results if r.classification == FlakyClassification.STABLE]

    parts: list[str] = []
    sources: list[dict] = []

    proj_label = project or "(all projects)"

    # ── Latest run results FIRST so the LLM uses them for status questions ──
    if latest_tests:
        latest_run = runs[0]
        run_label = f"Run #{latest_run.run_sequence}" if latest_run.run_sequence else latest_run.run_id
        parts.append(f"=== Latest Run Test Results ({run_label} · {latest_run.report_format}) ===")
        parts.append(f"Project: {proj_label}")
        failed_in_run = [tc for tc in latest_tests if tc.status in ("failed", "broken")]
        passed_in_run = [tc for tc in latest_tests if tc.status == "passed"]
        skipped_in_run = [tc for tc in latest_tests if tc.status not in ("failed", "broken", "passed")]
        parts.append(f"Total: {len(latest_tests)}  Passed: {len(passed_in_run)}  "
                     f"Failed: {len(failed_in_run)}  Skipped: {len(skipped_in_run)}")
        parts.append("")
        for tc in latest_tests:
            status_sym = "✓" if tc.status == "passed" else "✗" if tc.status in ("failed", "broken") else "–"
            line = f"  {status_sym} [{tc.status.upper()}]  {tc.name}"
            if tc.suite:
                line += f"  (suite: {tc.suite})"
            if tc.status in ("failed", "broken") and tc.message:
                first_line = tc.message.split("\n")[0][:120]
                line += f"\n      → {first_line}"
            parts.append(line)
        parts.append("")

        # Source card: run (links to run detail view)
        sources.append({
            "type": "run",
            "icon": "📋",
            "label": f"{run_label} · {latest_run.report_format}",
            "meta": f"{len(latest_tests)} tests · {len(failed_in_run)} failed",
            "run_id": latest_run.run_id,
        })

        # Source cards: one card per failed test in the latest run
        from qara.analyzers.categorizer import categorize_failure as _cat_fail
        for tc in failed_in_run:
            cat_label = ""
            if tc.error_type or tc.message:
                cat_label = _cat_fail(error_type=tc.error_type, message=tc.message).label
            sources.append({
                "type": "test",
                "icon": "🔴",
                "label": tc.name,
                "meta": (
                    f"{tc.status.capitalize()} · {run_label}"
                    + (f" · {cat_label}" if cat_label else "")
                    + (f" · suite: {tc.suite}" if tc.suite else "")
                ),
                "run_id": latest_run.run_id,
                "canonical_name": to_canonical_name(tc.name),
            })
    elif runs:
        # No test cases fetched but runs exist — add a bare run card
        latest_run = runs[0]
        run_label = f"Run #{latest_run.run_sequence}" if latest_run.run_sequence else latest_run.run_id
        sources.append({
            "type": "run",
            "icon": "📋",
            "label": f"{run_label} · {latest_run.report_format}",
            "meta": f"{latest_run.total_tests or '?'} tests · {latest_run.failed_count or 0} failed",
            "run_id": latest_run.run_id,
        })

    # ── Project health summary (used for trend/classification questions) ──
    parts.append(f"=== Project Health Summary: {proj_label} ===")
    parts.append(f"Total runs analysed : {len(runs)}")
    parts.append(f"Tests classified    : {len(all_results)} (min {min_runs} runs)")
    parts.append(f"  Flaky             : {len(flaky)}")
    parts.append(f"  Consistently broken: {len(broken)}")
    parts.append(f"  Stable            : {len(stable)}")
    parts.append("")

    # ── Per-run pass rate history (oldest → newest, last 5 runs) ──
    trend_runs = list(reversed(runs[:5]))  # runs is newest-first; reverse to oldest-first
    if len(trend_runs) >= 2:
        parts.append("--- Run-by-run Pass Rate History (oldest → newest) ---")
        for r in trend_runs:
            total = r.total_tests or 0
            passed = r.passed_count or 0
            failed = r.failed_count or 0
            pct = f"{passed / total:.0%}" if total else "N/A"
            label = f"Run #{r.run_sequence}" if r.run_sequence else r.run_id[:8]
            parts.append(f"  {label}: {pct} ({passed} passed, {failed} failed of {total} total)")
        parts.append("")

    # ── Delta: what changed between the previous run and the latest run ──
    # This gives the LLM precise "fixed" and "new failure" lists so it does
    # not have to guess from classification labels.
    _FAILING_STATES = {"failed", "broken"}
    if prev_tests and latest_tests:
        latest_label = f"Run #{runs[0].run_sequence}" if runs[0].run_sequence else runs[0].run_id[:8]
        prev_label = f"Run #{runs[1].run_sequence}" if runs[1].run_sequence else runs[1].run_id[:8]

        latest_by_c = {tc.canonical_name: tc for tc in latest_tests}
        prev_by_c = {tc.canonical_name: tc for tc in prev_tests}

        fixed_tests = [
            tc for cname, tc in latest_by_c.items()
            if tc.status == "passed"
            and cname in prev_by_c
            and prev_by_c[cname].status in _FAILING_STATES
        ]
        new_failures = [
            tc for cname, tc in latest_by_c.items()
            if tc.status in _FAILING_STATES
            and cname in prev_by_c
            and prev_by_c[cname].status == "passed"
        ]

        parts.append(
            f"--- Changes: {prev_label} → {latest_label} "
            f"(FIXED={len(fixed_tests)}  NEW FAILURES={len(new_failures)}) ---"
        )
        if fixed_tests:
            parts.append(f"  Tests FIXED in {latest_label} (were failing in {prev_label}):")
            for tc in fixed_tests:
                prev_tc = prev_by_c[tc.canonical_name]
                prev_err = (prev_tc.error_type or "").split(".")[-1] if prev_tc.error_type else ""
                parts.append(
                    f"    ✓ {tc.name}"
                    + (f"  [was: {prev_err}]" if prev_err else "")
                )
        else:
            parts.append(f"  No tests were fixed in {latest_label}.")
        if new_failures:
            parts.append(f"  Tests that NEWLY FAILED in {latest_label} (were passing in {prev_label}):")
            for tc in new_failures:
                err = (tc.error_type or "").split(".")[-1] if tc.error_type else ""
                parts.append(
                    f"    ✗ {tc.name}"
                    + (f"  [{err}]" if err else "")
                )
        else:
            parts.append(f"  No new failures in {latest_label}.")
            parts.append("")

    if flaky:
        parts.append("--- Flaky Tests (multi-run classification) ---")
        for r in flaky:
            parts.append(
                f"  {r.display_name}  "
                f"[pass={r.pass_rate:.0%} flip={r.flip_score:.2f} "
                f"history={r.sparkline}]"
            )
        parts.append("")

    if broken:
        parts.append("--- Consistently Broken Tests (multi-run classification) ---")
        for r in broken:
            parts.append(
                f"  {r.display_name}  "
                f"[{r.run_count} runs, always failing, history={r.sparkline}]"
            )
        parts.append("")

    if groups:
        parts.append(f"--- Recurring Failure Groups (top {len(groups)}) ---")
        for g in groups:
            cat = categorize_failure(
                error_type=g.get("error_type"),
                message=g.get("message"),
            )
            short_type = (g.get("error_type") or "").split(".")[-1] or "Unknown"
            first_line = (g.get("message") or "").split("\n")[0][:120]
            parts.append(
                f"  Fingerprint: {g['fingerprint']}  "
                f"category={cat.label}  "
                f"occurrences={g['occurrence_count']}  "
                f"tests={g['affected_tests']}  "
                f"runs={g['affected_runs']}"
            )
            if short_type:
                parts.append(f"    Error: {short_type}")
            if first_line:
                parts.append(f"    Message: {first_line}")
        parts.append("")

    return "\n".join(parts).strip(), sources


# ---------------------------------------------------------------------------
# Owner-filtered context
# ---------------------------------------------------------------------------


def gather_owner_context(
    owner_name: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[str, list[dict]]:
    """Build a context block for all tests owned by a specific person or team.

    Queries the database for test_cases whose owner matches *owner_name*
    (case-insensitive partial match), groups results by canonical test name,
    and returns aggregated status history plus the most recent status per test.
    Each test is enriched with FlakyScorer classification, sparkline, and
    flip score so stability-related questions can be answered accurately.

    Args:
        owner_name: Name (or partial name) of the owner to look up.
        project:    Optional project filter.
        db_path:    Path to the QARA SQLite database.

    Returns:
        A tuple of ``(context_text, sources)``.
    """
    from qara.analyzers.flaky import FlakyScorer
    from qara.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        pattern = f"%{owner_name}%"
        project_join = "JOIN runs r ON tc.run_id = r.run_id" if project else ""
        project_clause = "AND r.project = ?" if project else ""
        base_params: list = [pattern] + ([project] if project else [])

        cur.execute(
            f"""
            SELECT
                tc.canonical_name,
                MAX(tc.name)                AS display_name,
                MAX(tc.owner)               AS owner,
                MAX(tc.suite)               AS suite,
                COUNT(*)                    AS total_runs,
                SUM(CASE WHEN tc.status = 'passed'             THEN 1 ELSE 0 END) AS passes,
                SUM(CASE WHEN tc.status IN ('failed','broken') THEN 1 ELSE 0 END) AS failures,
                (
                    SELECT tc2.status
                    FROM   test_cases tc2
                    JOIN   runs r2 ON tc2.run_id = r2.run_id
                    WHERE  tc2.canonical_name = tc.canonical_name
                    AND    LOWER(tc2.owner)   LIKE LOWER(?)
                    ORDER BY r2.run_sequence DESC
                    LIMIT 1
                )                           AS latest_status
            FROM test_cases tc
            {project_join}
            WHERE LOWER(tc.owner) LIKE LOWER(?)
            {project_clause}
            GROUP BY tc.canonical_name
            ORDER BY failures DESC, tc.canonical_name
            """,
            [pattern] + base_params,
        )
        rows = cur.fetchall()

        # Enrich with FlakyScorer (classification, sparkline, flip score)
        scorer = FlakyScorer(conn)
        scored: dict[str, object] = {}
        for row in rows:
            canonical_name = row[0]
            try:
                result = scorer.score(canonical_name, project=project)
                scored[canonical_name] = result
            except Exception:  # noqa: BLE001
                pass
    finally:
        conn.close()

    if not rows:
        ctx = (
            f"=== Owner: {owner_name} ===\n"
            f"No tests found owned by '{owner_name}' in the database"
            + (f" for project '{project}'" if project else "")
            + "."
        )
        return ctx, []

    actual_owner = rows[0][2] if rows else owner_name
    proj_label = project or "(all projects)"

    parts: list[str] = []
    sources: list[dict] = []

    parts.append(f"=== Tests owned by {actual_owner} ({proj_label}) ===")
    parts.append(f"Total distinct tests: {len(rows)}")
    parts.append("")

    for (canonical_name, display_name, owner, suite,
         total_runs, passes, failures, latest_status) in rows:
        pass_rate = passes / total_runs if total_runs else 0.0
        status_sym = (
            "\u2713" if latest_status == "passed"
            else "\u2717" if latest_status in ("failed", "broken")
            else "\u2013"
        )

        result = scored.get(canonical_name)
        if result is not None:
            classification = result.classification.label
            sparkline = result.sparkline
            flip = result.flip_score
            streak = result.current_streak
            line = (
                f"  {status_sym} {display_name}"
                f"  [classification={classification}"
                f" \u00b7 latest={latest_status or 'unknown'}"
                f" \u00b7 pass={pass_rate:.0%}"
                f" \u00b7 flip={flip:.2f}"
                f" \u00b7 runs={total_runs}"
                f" \u00b7 history={sparkline}]"
            )
            if streak > 0:
                line += f"  streak={streak} consecutive pass(es)"
            elif streak < 0:
                line += f"  streak={abs(streak)} consecutive failure(s)"
        else:
            line = (
                f"  {status_sym} {display_name}"
                f"  [latest={latest_status or 'unknown'}"
                f" \u00b7 pass={pass_rate:.0%}"
                f" \u00b7 runs={total_runs}"
                f" \u00b7 failures={failures}]"
            )

        if suite:
            line += f"  (suite: {suite})"
        parts.append(line)

        sources.append({
            "type": "test",
            "icon": "🟢" if latest_status == "passed" else "🔴",
            "label": display_name,
            "meta": (
                f"{(result.classification.label if result else (latest_status or 'unknown').capitalize())} \u00b7 "
                f"{pass_rate:.0%} pass \u00b7 {total_runs} runs"
                + (f" \u00b7 suite: {suite}" if suite else "")
                + f" \u00b7 owner: {owner}"
            ),
            "canonical_name": canonical_name,
        })

    parts.append("")
    return "\n".join(parts).strip(), sources  # type: ignore[name-defined]
