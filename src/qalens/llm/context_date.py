"""Date-filtered context builder for QA Lens LLM queries.

Extracted from :mod:`qalens.llm.context` for cohesion.
All public names are re-exported from :mod:`qalens.llm.context` for backward
compatibility.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _extract_date(text: str) -> date | None:
    """Extract the first recognisable date from *text*.

    Supports:
    - ``M/D/YYYY`` or ``MM/DD/YYYY``
    - ``YYYY-MM-DD``
    - ``Month DD YYYY`` / ``Month DD, YYYY`` (abbreviated or full month name)
    """
    # M/D/YYYY
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    # YYYY-MM-DD
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # "March 7 2026" / "Mar 7, 2026" / "March 7th, 2026"
    m = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
        r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?"
        r"|dec(?:ember)?)\w*\s+(\d{1,2})(?:st|nd|rd|th)?[\s,]+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if m:
        month_num = _MONTH_MAP.get(m.group(1)[:3].lower())
        if month_num:
            try:
                return date(int(m.group(3)), month_num, int(m.group(2)))
            except ValueError:
                pass

    return None


def gather_date_context(
    question: str,
    *,
    project: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[str, list[dict]] | None:
    """Build a context block scoped to a specific date extracted from *question*.

    Returns ``None`` when no recognisable date is found in *question*, so the
    caller can fall back to :func:`~qalens.llm.context.gather_project_context`.

    When a date is found, returns a tuple of ``(context_text, sources)`` where:
    - ``context_text`` lists the run(s) from that date and their failed tests.
    - ``sources`` contains run cards and failed-test cards for the UI.
    """
    target_date = _extract_date(question)
    if target_date is None:
        return None

    from qalens.analyzers.categorizer import categorize_failure
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        all_runs = repo.list_runs(project=project, limit=10_000)
        matched_runs = [
            r for r in all_runs
            if r.started_at is not None
            and datetime.fromtimestamp(r.started_at).date() == target_date
        ]
    finally:
        conn.close()

    date_label = target_date.strftime("%B %-d, %Y")

    if not matched_runs:
        ctx = (
            f"=== No runs found for {date_label} ===\n"
            f"The database contains no test runs with started_at on {date_label}."
        )
        return ctx, []

    parts: list[str] = []
    sources: list[dict] = []

    parts.append(f"=== Test Runs on {date_label} ===")
    parts.append(f"Runs found on this date: {len(matched_runs)}")
    if project:
        parts.append(f"Project: {project}")
    parts.append("")

    conn = get_connection(db_path)
    try:
        repo = RunRepository(conn)
        for run in matched_runs:
            run_label = f"Run #{run.run_sequence}" if run.run_sequence else run.run_id
            parts.append(f"--- {run_label} ({run.report_format}) ---")
            parts.append(
                f"  Total: {run.total_tests or '?'}  "
                f"Passed: {run.passed_count or 0}  "
                f"Failed: {run.failed_count or 0}  "
                f"Skipped: {run.skipped_count or 0}"
            )

            sources.append({
                "type": "run",
                "icon": "📋",
                "label": f"{run_label} · {run.report_format} · {date_label}",
                "meta": (
                    f"{run.total_tests or '?'} tests · "
                    f"{run.failed_count or 0} failed"
                ),
                "run_id": run.run_id,
            })

            tests = repo.get_test_cases_for_run(run.run_id)
            failed = [t for t in tests if t.status in ("failed", "broken")]
            passed = [t for t in tests if t.status == "passed"]
            skipped = [t for t in tests if t.status not in ("failed", "broken", "passed")]

            if failed:
                parts.append(f"\n  Failed tests ({len(failed)}):")
                for tc in failed:
                    cat_label = ""
                    if tc.error_type or tc.message:
                        cat = categorize_failure(
                            error_type=tc.error_type, message=tc.message
                        )
                        cat_label = f"  [{cat.label}]"
                    suite_label = f"  (suite: {tc.suite})" if tc.suite else ""
                    parts.append(f"    \u2717 {tc.name}{suite_label}{cat_label}")
                    if tc.error_type:
                        short_type = tc.error_type.split(".")[-1]
                        parts.append(f"        Error type : {short_type}")
                    if tc.message:
                        first_line = tc.message.split("\n")[0][:150]
                        parts.append(f"        Message    : {first_line}")

                    sources.append({
                        "type": "test",
                        "icon": "\u2717",
                        "label": tc.name,
                        "meta": (
                            f"Failed \u00b7 {run_label} \u00b7 {date_label}"
                            + (f" \u00b7 {tc.error_type.split('.')[-1]}" if tc.error_type else "")
                        ),
                        "run_id": run.run_id,
                    })
            else:
                parts.append("  No failures in this run.")

            if passed:
                parts.append(
                    f"\n  Passed tests ({len(passed)}): "
                    + ", ".join(t.name for t in passed[:10])
                    + ("\u2026" if len(passed) > 10 else "")
                )
            if skipped:
                parts.append(f"  Skipped: {len(skipped)}")
            parts.append("")
    finally:
        conn.close()

    return "\n".join(parts).strip(), sources
