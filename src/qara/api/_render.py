"""Private rendering helpers for :class:`~ari.models.insight.AnalysisSummary`.

Extracted from :mod:`ari.api.library` for cohesion.
"""

from __future__ import annotations


def _render_analysis_markdown(analysis: "AnalysisSummary") -> str:  # noqa: F821
    """Render an ``AnalysisSummary`` as a Markdown string."""
    from qara.models.insight import AnalysisSummary  # noqa: F401 (type annotation)

    sc = analysis.status_counts
    cc = analysis.category_counts

    lines: list[str] = [
        "# QARA Analysis Summary",
        "",
        f"**Report:** `{analysis.report_path}`  ",
        f"**Run ID:** `{analysis.run_id}`  ",
        f"**Format:** {analysis.report_format}  ",
        f"**Engine:** ari v{analysis.analysis_engine_version}",
        "",
        "## Status Overview",
        "",
        "| Total | Passed | Failed | Skipped | Pending | Pass Rate |",
        "|------:|-------:|-------:|--------:|--------:|----------:|",
        (
            f"| {sc.total} | {sc.passed} | {sc.failed} "
            f"| {sc.skipped} | {sc.pending} | {sc.pass_rate_pct:.1f}% |"
        ),
        "",
    ]

    if cc.likely_product_defect + cc.likely_flaky + cc.likely_environment_issue \
            + cc.likely_test_script_issue + cc.likely_test_data_issue + cc.unknown > 0:
        lines += [
            "## Category Breakdown",
            "",
            "| Category | Count |",
            "|----------|------:|",
        ]
        rows = [
            ("Likely Product Defect", cc.likely_product_defect),
            ("Likely Flaky", cc.likely_flaky),
            ("Likely Environment Issue", cc.likely_environment_issue),
            ("Likely Test Script Issue", cc.likely_test_script_issue),
            ("Likely Test Data Issue", cc.likely_test_data_issue),
            ("Unknown", cc.unknown),
        ]
        for label, count in rows:
            if count > 0:
                lines.append(f"| {label} | {count} |")
        lines.append("")

    if analysis.recommended_actions:
        lines += ["## Recommended Actions", ""]
        for i, action in enumerate(analysis.recommended_actions, 1):
            lines.append(f"{i}. {action}")
        lines.append("")

    if analysis.insights:
        lines += [
            "## Failure Insights",
            "",
            "| Test | Category | Confidence | Explanation |",
            "|------|----------|:----------:|-------------|",
        ]
        for ins in analysis.insights:
            conf_pct = f"{ins.confidence:.0%}"
            explanation_short = ins.explanation[:80].rstrip()
            lines.append(
                f"| {ins.test_name} | {ins.category.display_name} "
                f"| {conf_pct} | {explanation_short}… |"
            )
        lines.append("")

    if analysis.clusters:
        lines += [
            "## Failure Clusters",
            "",
            "| Cluster | Size | Category | Confidence |",
            "|---------|-----:|----------|:----------:|",
        ]
        for c in analysis.clusters:
            lines.append(
                f"| {c.label} | {c.size} | {c.category.display_name} "
                f"| {c.confidence:.0%} |"
            )
        lines.append("")

    if analysis.extraction_warning_count > 0:
        lines += [
            f"> **Note:** {analysis.extraction_warning_count} extraction "
            "warning(s) were recorded during parsing.",
            "",
        ]

    return "\n".join(lines)


def _render_analysis_console(analysis: "AnalysisSummary") -> str:  # noqa: F821
    """Render an ``AnalysisSummary`` as a Rich-markup string for console output."""
    sc = analysis.status_counts
    cc = analysis.category_counts

    parts: list[str] = []

    # Header
    parts.append(
        f"[bold]ARI Analysis Summary[/bold] — "
        f"[dim]{analysis.report_path}[/dim]"
    )
    parts.append(
        f"Run [cyan]{analysis.run_id}[/cyan]  "
        f"Format [cyan]{analysis.report_format}[/cyan]  "
        f"Engine [dim]ari v{analysis.analysis_engine_version}[/dim]"
    )
    parts.append("")

    # Status bar
    pass_colour = "green" if sc.pass_rate >= 0.9 else ("yellow" if sc.pass_rate >= 0.7 else "red")
    parts.append(
        f"[bold]Status:[/bold]  "
        f"Total [white]{sc.total}[/white]  "
        f"Passed [{pass_colour}]{sc.passed}[/{pass_colour}]  "
        f"Failed [red]{sc.failed}[/red]  "
        f"Skipped [yellow]{sc.skipped}[/yellow]  "
        f"Pass rate [{pass_colour}]{sc.pass_rate_pct:.1f}%[/{pass_colour}]"
    )
    parts.append("")

    if analysis.recommended_actions:
        parts.append("[bold]Recommended Actions:[/bold]")
        for i, action in enumerate(analysis.recommended_actions, 1):
            parts.append(f"  {i}. {action}")
        parts.append("")

    if analysis.insights:
        total_f = len(analysis.insights)
        parts.append(f"[bold]Insights[/bold] — {total_f} failing test(s) analysed")
        cat_rows = [
            ("Likely Product Defect", cc.likely_product_defect, "red"),
            ("Likely Environment Issue", cc.likely_environment_issue, "yellow"),
            ("Likely Test Script Issue", cc.likely_test_script_issue, "cyan"),
            ("Likely Flaky", cc.likely_flaky, "magenta"),
            ("Likely Test Data Issue", cc.likely_test_data_issue, "blue"),
            ("Unknown", cc.unknown, "dim"),
        ]
        for label, count, colour in cat_rows:
            if count > 0:
                parts.append(f"  [{colour}]{label}[/{colour}]: {count}")
        parts.append("")

        for ins in analysis.insights[:10]:
            conf_label = ins.confidence_label
            colour_map = {"high": "green", "medium": "yellow", "low": "red", "very low": "dim"}
            c = colour_map.get(conf_label, "white")
            parts.append(
                f"  [bold]{ins.test_name}[/bold]  "
                f"[{c}]{ins.category.display_name} ({ins.confidence:.0%})[/{c}]"
            )
        if len(analysis.insights) > 10:
            parts.append(f"  [dim]… and {len(analysis.insights) - 10} more[/dim]")
        parts.append("")

    if analysis.clusters:
        parts.append(f"[bold]Clusters[/bold] — {len(analysis.clusters)} group(s)")
        for c in analysis.clusters[:5]:
            parts.append(f"  [cyan]{c.label}[/cyan] × {c.size} tests")
        if len(analysis.clusters) > 5:
            parts.append(f"  [dim]… and {len(analysis.clusters) - 5} more[/dim]")
        parts.append("")

    if analysis.extraction_warning_count > 0:
        parts.append(
            f"[yellow]⚠  {analysis.extraction_warning_count} extraction "
            "warning(s) during parsing[/yellow]"
        )

    return "\n".join(parts)
