"""QA Lens — Quality Assurance + Lens.

QA Lens reads existing automation test HTML reports (Extent Reports, Allure Reports),
extracts structured execution data, analyzes failures locally using explainable
heuristics, and generates meaningful root-cause insights for QA and engineering teams.

QA Lens is NOT a test reporting framework. It is an intelligence layer on top of
your existing reports.

Quickstart::

    from qalens.api.library import QALensClient

    client = QALensClient()
    run = client.extract_report("./reports/allure-report")
    analysis = client.analyze_report(run)
    print(client.summarize_report(analysis, fmt="markdown"))

CLI::

    qalens detect ./reports/allure-report
    qalens ingest ./reports/allure-report --db ./qalens.db
    qalens analyze --db ./qalens.db --out analysis.json
    qalens summarize --db ./qalens.db --format markdown
"""

from qalens.version import __version__

__all__ = ["__version__"]
