"""QALens — Quality Assurance + Lens.

QALens reads existing automation test HTML reports (Extent Reports, Allure Reports),
extracts structured execution data, analyzes failures locally using explainable
heuristics, and generates meaningful root-cause insights for QA and engineering teams.

QALens is NOT a test reporting framework. It is an intelligence layer on top of
your existing reports.

Quickstart::

    from qalens.api.library import QALensClient

    client = QALensClient()
    run = client.extract_report("./reports/allure-report")
    analysis = client.analyze_report(run)
    print(client.summarize_report(analysis, fmt="markdown"))

CLI::

    qalens detect ./reports/allure-report
    qalens analyze ./reports/allure-report --out analysis.json
    qalens summarize ./reports/extent-report --format markdown
"""

from qalens.version import __version__

__all__ = ["__version__"]
