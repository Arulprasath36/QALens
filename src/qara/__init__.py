"""QARA — Automated Root-cause Insights.

QARA reads existing automation test HTML reports (Extent Reports, Allure Reports),
extracts structured execution data, analyzes failures locally using explainable
heuristics, and generates meaningful root-cause insights for QA and engineering teams.

QARA is NOT a test reporting framework. It is an intelligence layer on top of
your existing reports.

Quickstart::

    from qara.api.library import QARAClient

    client = QARAClient()
    run = client.extract_report("./reports/allure-report")
    analysis = client.analyze_report(run)
    print(client.summarize_report(analysis, fmt="markdown"))

CLI::

    qara detect ./reports/allure-report
    qara analyze ./reports/allure-report --out analysis.json
    qara summarize ./reports/extent-report --format markdown
"""

from qara.version import __version__

__all__ = ["__version__"]
