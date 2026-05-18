"""Render deterministic QA Lens reports as Markdown, HTML, or JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qalens.reports.model import (
        FailureGroupSummary,
        ImpactSummary,
        RunSummary,
        ShareableReport,
        StabilitySummary,
        TestSummary,
    )


def render_json(report: ShareableReport) -> str:
    """Render *report* as stable, indented JSON."""
    return json.dumps(asdict(report), indent=2, sort_keys=True, default=str)


def render_markdown(report: ShareableReport) -> str:
    """Render *report* as a deterministic Markdown document."""
    lines: list[str] = [
        "# QA Lens Report",
        "",
        f"Generated: {_md(report.generated_at)}",
        f"Scope: {_md(report.scope_label)}",
        "",
        "## Executive Summary",
        "",
        *[f"- {_md(item)}" for item in (report.executive_summary or report.recommendations)],
        "",
        "## Fix First",
        "",
        *_fix_first_markdown(report.fix_first),
        "",
        "## Trend Intelligence",
        "",
        *_trend_markdown(report.trend_intelligence),
        "",
        "## Latest Run",
        "",
        *_run_markdown(report.latest_run),
    ]

    if report.comparison:
        lines.extend([
            "",
            "## Latest vs Previous",
            "",
            f"Baseline: Run #{report.comparison.baseline.run_sequence}",
            f"Target: Run #{report.comparison.target.run_sequence}",
            "",
            "| Metric | Count |",
            "|---|---:|",
            f"| New failures | {len(report.comparison.new_failures)} |",
            f"| Recovered | {len(report.comparison.recovered)} |",
            f"| Persistent failures | {len(report.comparison.persistent_failures)} |",
            f"| Newly skipped | {len(report.comparison.newly_skipped)} |",
        ])
        lines.extend(_test_table("New Failures", report.comparison.new_failures))
        lines.extend(_test_table("Recovered Tests", report.comparison.recovered))

    lines.extend(_failure_groups_markdown(report.failure_groups))
    lines.extend(_stability_markdown("Flaky Tests", report.flaky_tests))
    lines.extend(_stability_markdown("Highest Risk Tests", report.risk_tests))
    lines.extend(_impact_markdown("Suite Impact", report.suite_impacts))
    lines.extend(_impact_markdown("Owner Impact", report.owner_impacts))
    lines.append("")
    return "\n".join(lines)


def render_html(report: ShareableReport) -> str:
    """Render *report* as a standalone, no-network HTML file."""
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>QA Lens Report - {escape(report.scope_label)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        '<main class="report">',
        '<section class="hero">',
        "<p>QA Lens Report</p>",
        f"<h1>{escape(report.scope_label)}</h1>",
        f"<span>Generated {escape(_format_timestamp(report.generated_at))}</span>",
        "</section>",
        _summary_cards(report),
        _section("Executive Summary", _bullet_list(report.executive_summary or report.recommendations)),
        _section("Fix First", _fix_first_html(report.fix_first)),
        _section("Trend Intelligence", _trend_html(report.trend_intelligence)),
        _section("Latest Run", _run_html(report.latest_run)),
    ]

    if report.comparison:
        parts.append(_section("Latest vs Previous", _comparison_html(report)))
    parts.extend([
        _section("Failure Groups", _failure_groups_html(report.failure_groups)),
        _section("Flaky Tests", _stability_html(report.flaky_tests)),
        _section("Highest Risk Tests", _stability_html(report.risk_tests)),
        _section("Suite Impact", _impact_html(report.suite_impacts)),
        _section("Owner Impact", _impact_html(report.owner_impacts)),
        "</main>",
        "</body>",
        "</html>",
    ])
    return "\n".join(parts)


def _run_markdown(run: RunSummary) -> list[str]:
    return [
        "| Field | Value |",
        "|---|---|",
        f"| Run | #{run.run_sequence} |",
        f"| Project | {_md(run.project or 'Unknown')} |",
        f"| Format | {_md(run.report_format)} |",
        f"| Branch | {_md(run.branch or '-')} |",
        f"| Environment | {_md(run.environment or '-')} |",
        f"| Build | {_md(run.build_number or '-')} |",
        f"| Tests | {run.total_tests} |",
        f"| Passed | {run.passed} |",
        f"| Failed | {run.failed} |",
        f"| Skipped | {run.skipped} |",
        f"| Pass rate | {_pct(run.pass_rate)} |",
    ]


def _fix_first_markdown(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return ["- No immediate fix-first action detected."]
    lines = ["| Rank | Action | Reason | Impact |", "|---:|---|---|---|"]
    for item in items:
        lines.append(
            f"| {item.get('rank', '')} | {_md(str(item.get('title', '')))} | "
            f"{_md(str(item.get('reason', '')))} | {_md(str(item.get('impact', '')))} |"
        )
    return lines


def _trend_markdown(items: list[dict[str, object]]) -> list[str]:
    if not items:
        return ["- No trend intelligence available."]
    lines = ["| Metric | Direction | Detail |", "|---|---|---|"]
    for item in items:
        lines.append(
            f"| {_md(str(item.get('metric', '')))} | {_md(str(item.get('direction', '')))} | "
            f"{_md(str(item.get('detail', '')))} |"
        )
    return lines


def _test_table(title: str, tests: list[TestSummary]) -> list[str]:
    lines = ["", f"### {title}", ""]
    if not tests:
        return [*lines, "_None._"]
    lines.extend([
        "| Test | Suite | Owner | Status | Message |",
        "|---|---|---|---|---|",
    ])
    for test in tests[:10]:
        lines.append(
            f"| {_md(test.name)} | {_md(test.suite or '-')} | {_md(test.owner or '-')} | "
            f"{_md(test.status)} | {_md(_truncate(test.message, 120) or '-')} |"
        )
    return lines


def _failure_groups_markdown(groups: list[FailureGroupSummary]) -> list[str]:
    lines = ["", "## Failure Groups", ""]
    if not groups:
        return [*lines, "_No recurring failure groups found._"]
    lines.extend([
        "| Fingerprint | Category | Occurrences | Tests | Runs | Message |",
        "|---|---|---:|---:|---:|---|",
    ])
    for group in groups:
        lines.append(
            f"| `{_md(group.fingerprint[:12])}` | {_md(group.category)} | "
            f"{group.occurrence_count} | {group.affected_tests} | {group.affected_runs} | "
            f"{_md(_truncate(group.message, 120) or '-')} |"
        )
    return lines


def _stability_markdown(title: str, rows: list[StabilitySummary]) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not rows:
        return [*lines, "_No matching tests found._"]
    lines.extend([
        "| Test | Owner | Runs | Pass Rate | Flip Score | Classification | History |",
        "|---|---|---:|---:|---:|---|---|",
    ])
    for row in rows:
        lines.append(
            f"| {_md(row.name)} | {_md(row.owner or '-')} | {row.run_count} | "
            f"{_pct(row.pass_rate)} | {row.flip_score:.2f} | "
            f"{_md(row.classification)} | `{_md(row.sparkline)}` |"
        )
    return lines


def _impact_markdown(title: str, rows: list[ImpactSummary]) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not rows:
        return [*lines, "_No data available._"]
    lines.extend([
        "| Name | Total | Failed | Skipped | Pass Rate |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in rows:
        lines.append(
            f"| {_md(row.name)} | {row.total} | {row.failed} | {row.skipped} | "
            f"{_pct(row.pass_rate)} |"
        )
    return lines


def _summary_cards(report: ShareableReport) -> str:
    latest = report.latest_run
    new_failures = len(report.comparison.new_failures) if report.comparison else 0
    cards = [
        ("Pass Rate", _pct(latest.pass_rate)),
        ("Failed", str(latest.failed)),
        ("New Failures", str(new_failures)),
        ("Failure Groups", str(len(report.failure_groups))),
    ]
    return '<section class="cards">' + "".join(
        f'<div class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in cards
    ) + "</section>"


def _section(title: str, body: str) -> str:
    return f'<section class="section"><h2>{escape(title)}</h2>{body}</section>'


def _bullet_list(items: list[str]) -> str:
    if not items:
        return '<p class="empty">No recommendations.</p>'
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _fix_first_html(items: list[dict[str, object]]) -> str:
    if not items:
        return '<p class="empty">No immediate fix-first action detected.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('rank', '')))}</td>"
        f"<td>{escape(str(item.get('title', '')))}</td>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        f"<td>{escape(str(item.get('impact', '')))}</td>"
        "</tr>"
        for item in items
    )
    return (
        "<table><thead><tr><th>Rank</th><th>Action</th><th>Reason</th>"
        f"<th>Impact</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _trend_html(items: list[dict[str, object]]) -> str:
    if not items:
        return '<p class="empty">No trend intelligence available.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('metric', '')))}</td>"
        f"<td>{escape(str(item.get('direction', '')))}</td>"
        f"<td>{escape(str(item.get('detail', '')))}</td>"
        "</tr>"
        for item in items
    )
    return (
        "<table><thead><tr><th>Metric</th><th>Direction</th><th>Detail</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _run_html(run: RunSummary) -> str:
    rows = [
        ("Run", f"#{run.run_sequence}"),
        ("Project", run.project or "Unknown"),
        ("Format", run.report_format),
        ("Branch", run.branch or "-"),
        ("Environment", run.environment or "-"),
        ("Build", run.build_number or "-"),
        ("Tests", str(run.total_tests)),
        ("Passed", str(run.passed)),
        ("Failed", str(run.failed)),
        ("Skipped", str(run.skipped)),
        ("Pass rate", _pct(run.pass_rate)),
    ]
    return _key_value_table(rows)


def _comparison_html(report: ShareableReport) -> str:
    comparison = report.comparison
    if comparison is None:
        return '<p class="empty">No previous comparable run found.</p>'
    rows = [
        ("Baseline", f"Run #{comparison.baseline.run_sequence}"),
        ("Target", f"Run #{comparison.target.run_sequence}"),
        ("New failures", str(len(comparison.new_failures))),
        ("Recovered", str(len(comparison.recovered))),
        ("Persistent failures", str(len(comparison.persistent_failures))),
        ("Newly skipped", str(len(comparison.newly_skipped))),
    ]
    body = _key_value_table(rows)
    body += "<h3>New Failures</h3>" + _tests_html(comparison.new_failures)
    body += "<h3>Recovered Tests</h3>" + _tests_html(comparison.recovered)
    return body


def _tests_html(tests: list[TestSummary]) -> str:
    if not tests:
        return '<p class="empty">None.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(test.name)}</td>"
        f"<td>{escape(test.suite or '-')}</td>"
        f"<td>{escape(test.owner or '-')}</td>"
        f"<td>{escape(test.status)}</td>"
        f"<td>{escape(_truncate(test.message, 120) or '-')}</td>"
        "</tr>"
        for test in tests[:10]
    )
    return (
        '<table><thead><tr><th>Test</th><th>Suite</th><th>Owner</th>'
        '<th>Status</th><th>Message</th></tr></thead><tbody>'
        f"{rows}</tbody></table>"
    )


def _failure_groups_html(groups: list[FailureGroupSummary]) -> str:
    if not groups:
        return '<p class="empty">No recurring failure groups found.</p>'
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(group.fingerprint[:12])}</code></td>"
        f"<td>{escape(group.category)}</td>"
        f"<td>{group.occurrence_count}</td>"
        f"<td>{group.affected_tests}</td>"
        f"<td>{group.affected_runs}</td>"
        f"<td>{escape(_truncate(group.message, 120) or '-')}</td>"
        "</tr>"
        for group in groups
    )
    return (
        '<table><thead><tr><th>Fingerprint</th><th>Category</th>'
        '<th>Occurrences</th><th>Tests</th><th>Runs</th><th>Message</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _stability_html(rows: list[StabilitySummary]) -> str:
    if not rows:
        return '<p class="empty">No matching tests found.</p>'
    body = "".join(
        "<tr>"
        f"<td>{escape(row.name)}</td>"
        f"<td>{escape(row.owner or '-')}</td>"
        f"<td>{row.run_count}</td>"
        f"<td>{escape(_pct(row.pass_rate))}</td>"
        f"<td>{row.flip_score:.2f}</td>"
        f"<td>{escape(row.classification)}</td>"
        f"<td><code>{escape(row.sparkline)}</code></td>"
        "</tr>"
        for row in rows
    )
    return (
        '<table><thead><tr><th>Test</th><th>Owner</th><th>Runs</th>'
        '<th>Pass Rate</th><th>Flip Score</th><th>Classification</th><th>History</th>'
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def _impact_html(rows: list[ImpactSummary]) -> str:
    if not rows:
        return '<p class="empty">No data available.</p>'
    body = "".join(
        "<tr>"
        f"<td>{escape(row.name)}</td>"
        f"<td>{row.total}</td>"
        f"<td>{row.failed}</td>"
        f"<td>{row.skipped}</td>"
        f"<td>{escape(_pct(row.pass_rate))}</td>"
        "</tr>"
        for row in rows
    )
    return (
        '<table><thead><tr><th>Name</th><th>Total</th><th>Failed</th>'
        f"<th>Skipped</th><th>Pass Rate</th></tr></thead><tbody>{body}</tbody></table>"
    )


def _key_value_table(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>"
        for key, value in rows
    )
    return f'<table class="kv"><tbody>{body}</tbody></table>'


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


_CSS = """
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  background: #f8fafc;
  color: #0f172a;
}
body { margin: 0; background: #f8fafc; }
.report { max-width: 1120px; margin: 0 auto; padding: 32px 20px 48px; }
.hero {
  border: 1px solid #dbe3ef;
  background: #fff;
  border-radius: 14px;
  padding: 24px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, .06);
}
.hero p {
  margin: 0 0 8px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: .12em;
  font-size: 12px;
  font-weight: 700;
}
.hero h1 { margin: 0; font-size: clamp(28px, 4vw, 44px); letter-spacing: 0; }
.hero span {
  display: inline-block;
  margin-top: 12px;
  color: #64748b;
  font-size: 14px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0;
}
.card, .section {
  border: 1px solid #dbe3ef;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 26px rgba(15, 23, 42, .04);
}
.card { padding: 16px; }
.card span {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .1em;
}
.card strong { display: block; margin-top: 8px; font-size: 28px; }
.section { margin-top: 18px; padding: 20px; overflow-x: auto; }
h2 { margin: 0 0 14px; font-size: 20px; }
h3 { margin: 18px 0 10px; font-size: 15px; }
ul { margin: 0; padding-left: 20px; }
li { margin: 7px 0; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td {
  border-bottom: 1px solid #e2e8f0;
  padding: 10px 8px;
  text-align: left;
  vertical-align: top;
}
thead th {
  color: #475569;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.kv th { width: 180px; color: #475569; }
code {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  background: #f1f5f9;
  padding: 2px 5px;
  border-radius: 5px;
}
.empty { color: #64748b; margin: 0; }
@media (max-width: 760px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report { padding: 18px 12px 32px; }
}
""".strip()

_CHAT_EXTRA_CSS = """
.scope-chips{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
.chip{display:inline-flex;align-items:center;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;padding:3px 10px;font-size:12px;color:#475569}
.badge{display:inline-block;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.badge-critical{background:#fce7f3;color:#9d174d}
.badge-high{background:#fee2e2;color:#b91c1c}
.badge-medium{background:#fef3c7;color:#92400e}
.badge-low{background:#dcfce7;color:#15803d}
.badge-info{background:#dbeafe;color:#1d4ed8}
.rank-col{font-size:13px;font-weight:700;color:#94a3b8;width:32px}
td.good{color:#16a34a;font-weight:600}
td.warn{color:#d97706;font-weight:600}
td.bad{color:#dc2626;font-weight:600}
td.mono{font-family:"SFMono-Regular",Consolas,monospace;font-size:12px}
.answer p{margin:6px 0;line-height:1.65}
.answer ul{margin:6px 0}
@media print{body{background:#fff!important}.hero,.section,.card{box-shadow:none!important;border-color:#e2e8f0!important}}
""".strip()


# ── Public chat-result renderer ────────────────────────────────────────────

def render_chat_result_html(
    question: str,
    answer: str,
    result: "dict | None",
    *,
    autoprint: bool = False,
) -> str:
    """Return a standalone HTML document for a single chat Q&A result."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    r = result or {}
    title = str(r.get("title") or "QA Lens Analysis")
    subtitle = str(r.get("subtitle") or "")

    parts: list[str] = []

    # Hero
    hero_inner = (
        f'<p>QA Lens — Quality Assurance Risk Analyzer</p>'
        f'<h1>{escape(title)}</h1>'
        + (f'<p style="font-size:15px;color:#475569;margin:4px 0 0">{escape(subtitle)}</p>' if subtitle else "")
        + f'<span>Generated {now}</span>'
    )
    parts.append(f'<section class="hero">{hero_inner}</section>')

    # Scope chips
    scope = r.get("scope")
    if isinstance(scope, dict):
        chips = [escape(str(scope["label"]))] if scope.get("label") else []
        for k in ("runCount", "eligibleTests", "totalSuites", "totalEvaluated", "owners"):
            v = scope.get(k)
            if v and k != "label":
                chips.append(f'{_camel_to_label(k)}: {escape(str(v))}')
        if chips:
            chip_html = "".join(f'<span class="chip">{c}</span>' for c in chips)
            parts.append(f'<div class="scope-chips">{chip_html}</div>')

    # Stat cards from summary
    summary = r.get("summary")
    if isinstance(summary, dict) and summary:
        cards_html = "".join(
            f'<div class="card"><span>{escape(_camel_to_label(k))}</span>'
            f'<strong>{escape(_fmt_summary_val(v))}</strong></div>'
            for k, v in summary.items()
        )
        parts.append(f'<div class="cards">{cards_html}</div>')

    # Question
    if question:
        parts.append(_section("Question", f'<p class="answer" style="font-style:italic;color:#475569">{escape(question)}</p>'))

    # Answer
    if answer:
        parts.append(_section("Analysis", f'<div class="answer">{_plain_answer(answer)}</div>'))

    # Main data
    data_html = _chat_result_data(r)
    if data_html:
        parts.append(data_html)

    autoprint_tag = "<script>window.onload=function(){window.print();}</script>" if autoprint else ""
    css = f"{_CSS}\n{_CHAT_EXTRA_CSS}"
    return (
        f'<!doctype html><html lang="en"><head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title>'
        f'<style>{css}</style>'
        f'{autoprint_tag}'
        f'</head><body><main class="report">{"".join(parts)}</main></body></html>'
    )


# ── Chat result data renderer ──────────────────────────────────────────────

def _chat_result_data(r: dict) -> str:  # noqa: PLR0911
    kind = str(r.get("type", ""))

    if kind == "generic_answer":
        body = str(r.get("body") or "")
        return _section("Result", f'<div class="answer">{_plain_answer(body)}</div>') if body else ""

    if kind == "test_fix_playbook":
        return _chat_playbook(r)

    if kind == "failure_trend":
        runs = r.get("runs") or []
        return _section("Run History", _chat_table(
            ["Run", "Passed", "Failed", "Pass Rate"],
            [[_e(x, "runLabel"), _e(x, "passed"), _e(x, "failed"), _pct_val(x.get("passRate"))]
             for x in runs],
        )) if runs else ""

    # Types with owners + metrics (comparison)
    if kind in ("owner_suite_comparison", "owner_window_comparison"):
        return _chat_owner_comparison(r)

    if kind == "shared_suite_failures":
        suites = r.get("suites") or []
        return _section("Shared Suite Failures", _chat_table(
            ["#", "Suite", "Owner A", "Owner B"],
            [[str(i + 1), _e(x, "suiteName"),
              _pct_val(x.get("ownerA", {}).get("failureRate")),
              _pct_val(x.get("ownerB", {}).get("failureRate"))]
             for i, x in enumerate(suites)],
        )) if suites else ""

    if kind == "root_cause_insight":
        causes = r.get("causes") or []
        return _section("Root Causes", _chat_table(
            ["#", "Category", "Failures", "Probable Cause", "Recommended Action"],
            [[str(x.get("rank", i + 1)), _e(x, "category"),
              str(x.get("count", "")), _e(x, "probableCause"), _e(x, "recommendedAction")]
             for i, x in enumerate(causes)],
        )) if causes else ""

    if kind == "exception_retrieval":
        matches = r.get("matches") or []
        return _section("Matching Tests", _chat_table(
            ["Test", "Run", "Status", "Category"],
            [[_e(x, "testName"), _e(x, "runLabel"), _e(x, "status"), _e(x, "category")]
             for x in matches],
        )) if matches else ""

    if kind == "run_retrieval":
        tests = r.get("tests") or []
        return _section("Tests", _chat_table(
            ["Test", "Status", "Suite", "Owner", "Error"],
            [[_e(x, "name"), _e(x, "status"), _e(x, "suite"), _e(x, "owner"), _truncate(_e(x, "message"), 80)]
             for x in tests],
        )) if tests else ""

    # Types with ranking array
    ranking = r.get("ranking")
    if isinstance(ranking, list) and ranking:
        return _chat_ranking_section(kind, ranking)

    # Types with tests array (stability, gaps, comparisons)
    tests = r.get("tests")
    if isinstance(tests, list) and tests:
        return _chat_tests_section(kind, tests)

    # Types with suites array
    suites = r.get("suites")
    if isinstance(suites, list) and suites:
        return _section("Suites", _chat_table(
            ["#", "Suite", "Tests", "Failing", "Pass Rate"],
            [[str(x.get("rank", i + 1)), _e(x, "suiteName"),
              str(x.get("tests") or x.get("totalTests", "")),
              str(x.get("failing") or x.get("currentlyFailing", "")),
              _pct_val(x.get("lowestPassRate") or x.get("passRate"))]
             for i, x in enumerate(suites)],
        ))

    return ""


def _chat_ranking_section(kind: str, ranking: list) -> str:
    first = ranking[0] if ranking else {}
    if "ownerName" in first:
        label = "Owner Ranking"
        rows = [[str(x.get("rank", "")), _e(x, "ownerName"),
                 _pct_val(x.get("failureRate") or x.get("avgFlipScore")),
                 _e(x, "primaryReason")]
                for x in ranking]
        return _section(label, _chat_table(["#", "Owner", "Rate", "Reason"], rows))
    if "suiteName" in first:
        rows = [[str(x.get("rank", "")), _e(x, "suiteName"),
                 _pct_val(x.get("failureRate")), _e(x, "primaryReason")]
                for x in ranking]
        return _section("Suite Ranking", _chat_table(["#", "Suite", "Failure Rate", "Reason"], rows))
    # Default: test ranking (risk_ranking)
    rows = [[str(x.get("rank", "")), _e(x, "testName"),
             str(x.get("riskTier") or ""), _pct_val(x.get("passRate")), _e(x, "primaryReason")]
            for x in ranking]
    return _section("Test Ranking", _chat_table(["#", "Test", "Risk", "Pass Rate", "Reason"], rows))


def _chat_tests_section(kind: str, tests: list) -> str:
    first = tests[0] if tests else {}
    if "baselineStatus" in first:
        rows = [[str(x.get("rank", i + 1)), _e(x, "testName"), _e(x, "classification"),
                 _e(x, "baselineStatus"), _e(x, "latestStatus"), _e(x, "primaryReason")]
                for i, x in enumerate(tests)]
        return _section("Test Changes", _chat_table(["#", "Test", "Change", "Baseline", "Latest", "Reason"], rows))
    rows = [[str(x.get("rank", i + 1)), _e(x, "testName"),
             _pct_val(x.get("passRate")), _e(x, "classification") or _e(x, "currentStatus"),
             _e(x, "primaryReason")]
            for i, x in enumerate(tests)]
    return _section("Tests", _chat_table(["#", "Test", "Pass Rate", "Status", "Reason"], rows))


def _chat_owner_comparison(r: dict) -> str:
    owners = r.get("owners") or {}
    metrics = r.get("metrics") or {}
    if not isinstance(owners, dict) or not isinstance(metrics, dict):
        return ""
    owner_a = str(owners.get("ownerA", "Owner A"))
    owner_b = str(owners.get("ownerB", "Owner B"))
    ma = metrics.get("ownerA") or {}
    mb = metrics.get("ownerB") or {}
    keys = [k for k in ma if k in mb]
    rows = [[escape(_camel_to_label(k)), escape(_fmt_summary_val(ma[k])), escape(_fmt_summary_val(mb[k]))]
            for k in keys]
    return _section("Owner Comparison", _chat_table([
        "Metric", escape(owner_a), escape(owner_b)
    ], rows))


def _chat_playbook(r: dict) -> str:
    parts: list[str] = []
    for field, label in [
        ("diagnosis", "Diagnosis"), ("summary", "Summary"),
        ("probableCause", "Probable Cause"), ("recommendedFix", "Recommended Fix"),
        ("verification", "How to Verify"),
    ]:
        val = r.get(field)
        if val and isinstance(val, str):
            parts.append(f'<h3>{escape(label)}</h3><p>{escape(val)}</p>')
    checks = r.get("checks")
    if isinstance(checks, list) and checks:
        items = "".join(f'<li>{escape(str(c))}</li>' for c in checks)
        parts.append(f'<h3>Checks</h3><ul>{items}</ul>')
    return _section("Fix Playbook", "".join(parts)) if parts else ""


def _chat_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="empty">No data.</p>'
    thead = "".join(f'<th>{escape(h)}</th>' for h in headers)
    tbody = "".join(
        "<tr>" + "".join(f'<td>{escape(str(c))}</td>' for c in row) + "</tr>"
        for row in rows
    )
    return f'<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'


def _e(d: dict, key: str) -> str:
    return str(d.get(key) or "")


def _pct_val(v: object) -> str:
    if v is None or v == "":
        return ""
    try:
        f = float(v)  # type: ignore[arg-type]
        return f"{f:.0%}"
    except (TypeError, ValueError):
        return str(v)


def _camel_to_label(key: str) -> str:
    import re
    spaced = re.sub(r"([A-Z])", r" \1", key).strip()
    return spaced.capitalize()


def _fmt_summary_val(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.0%}" if 0 < v <= 1 else f"{v:.1f}"
    return str(v) if v is not None else ""


def _plain_answer(text: str) -> str:
    """Convert markdown-ish answer text to simple HTML paragraphs."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            out.append(f'<li>{escape(stripped[2:])}</li>')
        elif stripped.startswith("## "):
            out.append(f'<h3>{escape(stripped[3:])}</h3>')
        elif stripped.startswith("# "):
            out.append(f'<h3>{escape(stripped[2:])}</h3>')
        else:
            out.append(f'<p>{escape(stripped)}</p>')
    return "".join(out)
