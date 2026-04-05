"""QARA public Python library API.

``QARAClient`` is the primary entry point for programmatic use of ARI.
It orchestrates detection, extraction, analysis, and summarization.

Example::

    from qara.api.library import QARAClient

    client = QARAClient()
    run = client.extract_report("./reports/allure-report")
    analysis = client.analyze_report(run)
    summary_md = client.summarize_report(analysis, fmt="markdown")
    print(summary_md)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from qara.parsers.base import DetectionResult
from qara.parsers.detector import Detector

if TYPE_CHECKING:
    from qara.analyzers.flaky import FlakyResult
    from qara.artifacts.config import ArtifactConfig
    from qara.artifacts.models import ArtifactIngestStats
    from qara.db.repository import RunRepository
    from qara.llm.config import LLMConfig
    from qara.models.insight import AnalysisSummary, FailureCluster
    from qara.models.run import TestRun
    from qara.outputs.digest import DigestData
    from qara.parsers.base import BaseParser


class QARAClient:
    """High-level client for the QARA analysis pipeline.

    All public methods are designed to be used independently or chained.
    The client is stateless — repeated calls to the same method with the
    same input will produce the same result.

    Args:
        extra_parsers: Additional ``BaseParser`` instances to register with
            the detector, for custom report formats.
        extra_categorizer_rules: Additional categorization rule functions
            to run alongside the built-in heuristics.
        enable_fuzzy_clustering: When ``True``, enables TF-IDF-based fuzzy
            clustering after deterministic grouping. Requires ``scikit-learn``
            (``pip install ari-insights[ml]``).

    """

    def __init__(
        self,
        *,
        extra_parsers: list[BaseParser] | None = None,
        extra_categorizer_rules: list[object] | None = None,
        enable_fuzzy_clustering: bool = False,
    ) -> None:
        self._extra_rules = extra_categorizer_rules or []
        self._fuzzy = enable_fuzzy_clustering
        self._extra_parsers: list[BaseParser] = list(extra_parsers or [])
        self._detector: Detector = Detector()
        for parser in self._extra_parsers:
            self._detector.register(parser)

    def detect_report(self, report_path: str | Path) -> DetectionResult:
        """Detect the report format for the given path.

        Args:
            report_path: Path to a report directory or HTML file.

        Returns:
            A :class:`~ari.parsers.base.DetectionResult` with the
            parser key, confidence, and evidence reasons.  Check
            :attr:`~ari.parsers.base.DetectionResult.matched` to
            determine whether a supported format was found.

        """
        return self._detector.detect(Path(report_path))

    def get_parser_for_path(self, report_path: str | Path) -> BaseParser:
        """Detect the report format and return the corresponding parser.

        Args:
            report_path: Path to a report directory or HTML file.

        Returns:
            The :class:`~ari.parsers.base.BaseParser` with the highest
            detection confidence for the given path.

        Raises:
            ParserNotFoundError: If no registered parser matched.

        """
        return self._detector.get_parser_for_path(Path(report_path))

    def extract_report(
        self,
        report_path: str | Path,
        *,
        attachments_dir: Path | None = None,
    ) -> TestRun:
        """Parse a report and return a normalized ``TestRun``.

        Detects the report format automatically, selects the best-matched
        parser, and delegates to its :meth:`~ari.parsers.base.BaseParser.parse`
        method.

        Args:
            report_path: Path to a report directory or HTML file.
            attachments_dir: Directory where embedded base64 screenshots (Extent
                reports) will be extracted.  ``None`` skips extraction.

        Returns:
            A :class:`~ari.models.run.TestRun` containing all extracted
            test case results and run metadata.

        Raises:
            ParserNotFoundError: If no registered parser matched the path.
            ReportMalformedError: If the report is structurally invalid.

        """
        path = Path(report_path)
        if attachments_dir is not None:
            # Build a one-shot detector with the requested attachments_dir so
            # that ExtentHtmlParser can extract embedded screenshots.
            detector = Detector(attachments_dir=attachments_dir)
            for parser in self._extra_parsers:
                detector.register(parser)
        else:
            detector = self._detector
        matched_parser = detector.get_parser_for_path(path)
        return matched_parser.parse(path)

    def ingest_report(
        self,
        report_path: str | Path,
        *,
        db_path: str | Path | None = None,
        skip_if_exists: bool = True,
        attachments_dir: Path | None = None,
        artifact_config: "ArtifactConfig | None" = None,
    ) -> "tuple[TestRun, bool, ArtifactIngestStats | None]":
        """Parse a report, persist it to the database, and return the result.

        This is the primary entry point for the daily SDET workflow::

            client = QARAClient()
            run, inserted, stats = client.ingest_report(
                "./reports/ExtentReport.html",
                artifact_config=ArtifactConfig(mode=ArtifactMode.FULL),
            )

        The method is idempotent by default: if the same report (identified by
        its ``run_id``) has already been stored, it will not be written again
        and the second return value will be ``False``.

        Args:
            report_path: Path to a report directory or HTML file.
            db_path: Path to the SQLite database file.  When ``None``, the
                default ``~/.qara/ari.db`` is used.
            skip_if_exists: Passed through to
                :meth:`~ari.db.repository.RunRepository.save_run`.
            attachments_dir: Legacy parameter — directory where embedded base64
                screenshots are written by the parser directly.  Prefer
                passing an ``ArtifactConfig`` with ``mode=FULL`` instead.
            artifact_config: Artifact ingestion policy configuration.  When
                ``None``, no artifact records are created.

        Returns:
            A ``(TestRun, inserted, artifact_stats)`` triple.  *inserted* is
            ``True`` when the run was written to the database.
            *artifact_stats* is ``None`` when no ``artifact_config`` was
            provided.

        Raises:
            ParserNotFoundError: If no registered parser matched the path.
            ReportMalformedError: If the report is structurally invalid.

        """
        from qara.db.repository import RunRepository
        from qara.db.schema import default_db_path, get_connection

        run = self.extract_report(report_path, attachments_dir=attachments_dir)
        conn = get_connection(db_path)
        repo = RunRepository(conn)
        inserted = repo.save_run(run, skip_if_exists=skip_if_exists)

        artifact_stats: ArtifactIngestStats | None = None
        if inserted and artifact_config is not None:
            artifact_stats = self._run_artifact_policy(
                run=run,
                repo=repo,
                config=artifact_config,
                db_path=db_path,
            )

        conn.close()
        return run, inserted, artifact_stats

    def _run_artifact_policy(
        self,
        run: "TestRun",
        repo: "RunRepository",
        config: "ArtifactConfig",
        db_path: "str | Path | None",
    ) -> "ArtifactIngestStats":
        """Apply the artifact ingestion policy and persist artifact records."""
        from qara.artifacts.config import ArtifactMode
        from qara.artifacts.models import ArtifactIngestStats
        from qara.artifacts.policy import ArtifactIngestionPolicy
        from qara.artifacts.storage import LocalFilesystemStore
        from qara.db.schema import default_db_path

        total_stats = ArtifactIngestStats(artifact_mode=config.mode.value)

        if config.mode == ArtifactMode.TEXT_ONLY:
            # Count refs for summary even though we don't store them
            for tc in run.test_cases:
                total_stats.refs_found += len(tc.raw_artifact_refs)
            return total_stats

        store = None
        if config.mode == ArtifactMode.FULL:
            storage_dir = config.storage_dir
            if storage_dir is None:
                db_resolved = Path(db_path) if db_path else default_db_path()
                storage_dir = db_resolved.parent / "artifacts"
            store = LocalFilesystemStore(storage_dir)

        policy = ArtifactIngestionPolicy(config=config, store=store)
        tc_ids = repo.list_tc_ids_for_run(run.metadata.run_id)
        all_records = []

        for tc, stored_tc_id in zip(run.test_cases, tc_ids):
            if not tc.raw_artifact_refs:
                continue
            records, stats = policy.process(stored_tc_id, tc.raw_artifact_refs)
            all_records.extend(records)
            total_stats.merge(stats)

        if all_records:
            repo.save_artifacts(all_records)

        return total_stats

    def get_repository(
        self,
        db_path: str | Path | None = None,
    ) -> RunRepository:
        """Return an open :class:`~ari.db.repository.RunRepository`.

        The caller is responsible for closing the underlying connection when
        finished.  Prefer using this for batch query operations.

        Args:
            db_path: Path to the SQLite database, or ``None`` for the default.

        Returns:
            An initialised :class:`~ari.db.repository.RunRepository`.

        """
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        return RunRepository(conn)

    # ------------------------------------------------------------------
    # Phase 5 — Failure analysis
    # ------------------------------------------------------------------

    def score_flakiness(
        self,
        canonical_name: str,
        *,
        project: str | None = None,
        db_path: str | Path | None = None,
        limit: int = 30,
    ) -> FlakyResult:
        """Compute the flakiness profile for a single test by canonical name.

        Args:
            canonical_name: Normalised test name.  Use
                :func:`~ari.analyzers.canonical.to_canonical_name` to obtain
                this from a raw display name.
            project: Restrict history to this project.
            db_path: Path to the QARA SQLite database.
            limit: Maximum run history depth.

        Returns:
            A :class:`~ari.analyzers.flaky.FlakyResult` for the test.

        """
        from qara.analyzers.flaky import FlakyScorer
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return FlakyScorer(conn).score(
                canonical_name, project=project, limit=limit
            )
        finally:
            conn.close()

    def get_all_flaky(
        self,
        *,
        project: str | None = None,
        db_path: str | Path | None = None,
        min_runs: int = 2,
    ) -> list[FlakyResult]:
        """Return all tests classified as flaky in the database.

        Args:
            project: Project filter (``None`` = all projects).
            db_path: Path to the QARA SQLite database.
            min_runs: Minimum run appearances required.

        Returns:
            List of :class:`~ari.analyzers.flaky.FlakyResult` sorted by
            flip score descending.

        """
        from qara.analyzers.flaky import FlakyScorer
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return FlakyScorer(conn).get_all_flaky(
                project=project, min_runs=min_runs
            )
        finally:
            conn.close()

    def get_all_stability(
        self,
        *,
        project: str | None = None,
        db_path: str | Path | None = None,
        min_runs: int = 2,
    ) -> list[FlakyResult]:
        """Return stability profiles for all tests with sufficient history.

        Args:
            project: Project filter (``None`` = all projects).
            db_path: Path to the QARA SQLite database.
            min_runs: Minimum run appearances required.

        Returns:
            List of :class:`~ari.analyzers.flaky.FlakyResult` sorted by
            flip score descending.

        """
        from qara.analyzers.flaky import FlakyScorer
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return FlakyScorer(conn).get_all(
                project=project, min_runs=min_runs
            )
        finally:
            conn.close()

    def get_failure_groups(
        self,
        *,
        project: str | None = None,
        db_path: str | Path | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return failures grouped by fingerprint, ranked by occurrence count.

        Args:
            project: Project filter (``None`` = all).
            db_path: Path to the QARA SQLite database.
            limit: Maximum number of groups.

        Returns:
            List of dicts with keys: ``fingerprint``, ``occurrence_count``,
            ``affected_tests``, ``affected_runs``, ``error_type``,
            ``message``, ``first_seen_seq``, ``last_seen_seq``.

        """
        from qara.db.repository import RunRepository
        from qara.db.schema import get_connection

        conn = get_connection(db_path)
        try:
            return RunRepository(conn).get_failure_groups(
                project=project, limit=limit
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Phase 6 — In-run failure clustering
    # ------------------------------------------------------------------

    def cluster_report(
        self,
        run: TestRun,
    ) -> list[FailureCluster]:
        """Group failing tests in *run* by normalised failure signature.

        Runs the deterministic clustering algorithm on the test cases of a
        single ``TestRun``.  No database access is required — the engine
        operates entirely in memory.

        Args:
            run: A ``TestRun`` produced by :meth:`extract_report`.

        Returns:
            A list of :class:`~ari.models.insight.FailureCluster` objects
            ordered by cluster size descending.  Empty list when there are
            no failing tests.

        """
        from qara.analyzers.clustering import cluster_failures
        from qara.models.insight import FailureCluster  # noqa: F401 (re-export hint)

        return cluster_failures(run.test_cases)

    # ------------------------------------------------------------------
    # Phase 7 — LLM ask
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        *,
        project: str | None = None,
        db_path: str | Path | None = None,
        config_path: str | Path | None = None,
        llm_config: LLMConfig | None = None,
    ) -> str:
        """Ask a natural-language question about test failures.

        Builds a structured context from the QARA database, constructs a prompt,
        and sends it to the configured local LLM (or cloud provider).

        Args:
            question: Free-text question, e.g. ``"Why does testCreateOrder fail?"``
            project: Optional project filter for database queries.
            db_path: Path to the QARA SQLite database.
            config_path: Path to ``config.toml``.  ``None`` = default.
            llm_config: Pre-built :class:`~ari.llm.config.LLMConfig`.  When
                supplied, *config_path* is ignored.

        Returns:
            The LLM's plain-text answer.

        Raises:
            :exc:`ari.llm.client.LLMError`: On HTTP or provider errors.

        """
        from qara.llm.answer_plan import build_answer_plan, detect_answer_intent
        from qara.llm.client import LLMClient
        from qara.llm.config import load_config
        from qara.llm.context import gather_project_context, gather_test_context
        from qara.llm.prompts import build_prompt, build_system_prompt, infer_mode

        cfg = llm_config or load_config(
            None if config_path is None else Path(config_path)
        )
        mode = infer_mode(question)
        _answer_plan = build_answer_plan(detect_answer_intent(question), question=question)

        if mode == "project":
            context, _ = gather_project_context(
                project=project, db_path=db_path
            )
        else:
            context, _ = gather_test_context(
                question, project=project, db_path=db_path
            )

        prompt = build_prompt(question, context, mode=mode, answer_plan=_answer_plan)
        return LLMClient(cfg).chat(
            prompt, system_prompt=build_system_prompt(_answer_plan)
        )

    def build_digest(
        self,
        *,
        project: str | None = None,
        db_path: str | Path | None = None,
        min_runs: int = 2,
        max_failure_groups: int = 50,
    ) -> DigestData:
        """Build a :class:`~ari.outputs.digest.DigestData` from the database.

        Collects flakiness profiles and failure groups for the given project
        and returns a data object ready to be rendered as HTML, Markdown, or
        JSON via the functions in :mod:`ari.outputs.digest`.

        Args:
            project: Restrict to a specific project (``None`` = all).
            db_path: Path to the QARA SQLite database.
            min_runs: Minimum run count required for flaky classification.
            max_failure_groups: Maximum number of recurring failure groups.

        Returns:
            A :class:`~ari.outputs.digest.DigestData` instance.

        """
        from qara.outputs.digest import build_digest
        return build_digest(
            project=project,
            db_path=db_path,
            min_runs=min_runs,
            max_failure_groups=max_failure_groups,
        )

    def analyze_report(
        self,
        run: TestRun,
        *,
        history_dir: str | Path | None = None,  # noqa: ARG002 — reserved for v1.2 history
    ) -> AnalysisSummary:
        """Run the full analysis pipeline on a normalized ``TestRun``.

        The pipeline executes in order:

        1. :class:`~ari.analyzers.signatures.SignatureEngine` enriches every
           ``FailureInfo`` with ``normalized_message``, ``normalized_stack_trace``,
           and ``failure_signature``.
        2. :func:`~ari.analyzers.categorizer.categorize_failure` assigns a
           :class:`~ari.analyzers.categorizer.FailureCategory` to each failure.
        3. One :class:`~ari.models.insight.Insight` is built per failing test,
           including evidence strings, confidence, and related-test cross-links.
        4. :func:`~ari.analyzers.clustering.cluster_failures` groups failures by
           shared signature into :class:`~ari.models.insight.FailureCluster` objects.
        5. :class:`~ari.models.insight.StatusCounts` and
           :class:`~ari.models.insight.CategoryCounts` are aggregated.
        6. Recommended triage actions are derived from the category distribution.

        Args:
            run: A ``TestRun`` produced by :meth:`extract_report`.
            history_dir: Reserved for v1.2 historical comparison. Ignored in v1.

        Returns:
            An :class:`~ari.models.insight.AnalysisSummary` with all insights,
            clusters, status counts, and recommended actions.

        """
        from collections import defaultdict

        from qara.analyzers.categorizer import FailureCategory, categorize_failure
        from qara.analyzers.clustering import cluster_failures
        from qara.analyzers.signatures import SignatureEngine
        from qara.models.insight import (
            AnalysisSummary,
            CategoryCounts,
            Insight,
            InsightCategory,
            StatusCounts,
        )
        from qara.models.test_case import TestStatus
        from qara.version import __version__

        # FailureCategory → InsightCategory mapping
        _CAT_MAP: dict[FailureCategory, InsightCategory] = {
            FailureCategory.ELEMENT_NOT_FOUND: InsightCategory.LIKELY_TEST_SCRIPT_ISSUE,
            FailureCategory.STALE_ELEMENT: InsightCategory.LIKELY_TEST_SCRIPT_ISSUE,
            FailureCategory.TIMEOUT: InsightCategory.LIKELY_FLAKY,
            FailureCategory.ASSERTION: InsightCategory.LIKELY_PRODUCT_DEFECT,
            FailureCategory.NULL_POINTER: InsightCategory.LIKELY_PRODUCT_DEFECT,
            FailureCategory.NETWORK: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
            FailureCategory.AUTHENTICATION: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
            FailureCategory.INFRASTRUCTURE: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
            FailureCategory.TEST_DATA: InsightCategory.LIKELY_TEST_DATA_ISSUE,
            FailureCategory.PERMISSION: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
            FailureCategory.CONFIGURATION: InsightCategory.LIKELY_ENVIRONMENT_ISSUE,
            FailureCategory.UNKNOWN: InsightCategory.UNKNOWN,
        }

        # Base confidence per FailureCategory (reduced by 0.10 when no stack trace)
        _BASE_CONF: dict[FailureCategory, float] = {
            FailureCategory.ELEMENT_NOT_FOUND: 0.80,
            FailureCategory.STALE_ELEMENT: 0.82,
            FailureCategory.TIMEOUT: 0.65,
            FailureCategory.ASSERTION: 0.80,
            FailureCategory.NULL_POINTER: 0.75,
            FailureCategory.NETWORK: 0.80,
            FailureCategory.AUTHENTICATION: 0.80,
            FailureCategory.INFRASTRUCTURE: 0.82,
            FailureCategory.TEST_DATA: 0.75,
            FailureCategory.PERMISSION: 0.75,
            FailureCategory.CONFIGURATION: 0.75,
            FailureCategory.UNKNOWN: 0.30,
        }

        _EXPLANATION: dict[InsightCategory, str] = {
            InsightCategory.LIKELY_FLAKY: (
                "The failure pattern suggests intermittent instability — typically caused "
                "by timing dependencies, race conditions, or transient environment issues."
            ),
            InsightCategory.LIKELY_ENVIRONMENT_ISSUE: (
                "The error signature points to an infrastructure or environment setup "
                "problem unrelated to the application under test or the test script."
            ),
            InsightCategory.LIKELY_TEST_SCRIPT_ISSUE: (
                "The error originates in the test script itself — most commonly a stale "
                "locator, bad selector, or test harness error."
            ),
            InsightCategory.LIKELY_PRODUCT_DEFECT: (
                "A stable assertion failure indicates a reproducible product defect "
                "in the application under test."
            ),
            InsightCategory.LIKELY_TEST_DATA_ISSUE: (
                "The failure is consistent with missing, stale, or invalid test data — "
                "entities, accounts, or seed records the test depends on."
            ),
            InsightCategory.UNKNOWN: (
                "Insufficient signals to classify this failure confidently. "
                "Review the stack trace and error message manually."
            ),
        }

        # Step 1: Enrich all FailureInfo objects with signatures (idempotent)
        SignatureEngine().enrich(run)

        # Step 2: Build signature → [test_id] map for related_tests cross-links
        sig_to_ids: dict[str, list[str]] = defaultdict(list)
        for tc in run.test_cases:
            if tc.status.is_failing and tc.failure and tc.failure.failure_signature:
                sig_to_ids[tc.failure.failure_signature].append(tc.test_id)

        # Step 3: Status counts
        status_counts = StatusCounts(
            total=len(run.test_cases),
            passed=sum(1 for tc in run.test_cases if tc.status == TestStatus.PASSED),
            failed=sum(1 for tc in run.test_cases if tc.status.is_failing),
            skipped=sum(1 for tc in run.test_cases if tc.status == TestStatus.SKIPPED),
            pending=sum(1 for tc in run.test_cases if tc.status == TestStatus.PENDING),
        )

        # Step 4: Build one Insight per failing test
        insights: list[Insight] = []
        for tc in run.test_cases:
            if not tc.status.is_failing:
                continue
            f = tc.failure
            failure_cat = categorize_failure(
                error_type=f.error_type if f else None,
                message=f.message if f else None,
            )
            insight_cat = _CAT_MAP.get(failure_cat, InsightCategory.UNKNOWN)

            # Evidence strings
            evidence: list[str] = []
            if f:
                if f.error_type:
                    simple = f.error_type.split(".")[-1].split("$")[-1]
                    evidence.append(f"error type: {simple}")
                msg = f.normalized_message or (
                    f.message.splitlines()[0] if f.message else None
                )
                if msg:
                    evidence.append(f"message: {msg[:100]}")
                if f.failure_signature:
                    evidence.append(f"signature: {f.failure_signature}")
            if tc.retry_count > 0:
                evidence.append(f"retried {tc.retry_count} time(s)")
            if tc.passed_on_retry:
                evidence.append("passed on retry — strong flakiness signal")

            # Confidence: lower when no stack trace available
            confidence = _BASE_CONF.get(failure_cat, 0.30)
            if f and not f.has_stack_trace():
                confidence = max(0.30, confidence - 0.10)

            # Related tests: others sharing the same failure signature
            sig = f.failure_signature if f else None
            related = [
                tid
                for tid in sig_to_ids.get(sig or "", [])
                if tid != tc.test_id
            ]

            insights.append(
                Insight(
                    test_id=tc.test_id,
                    test_name=tc.name,
                    category=insight_cat,
                    confidence=round(confidence, 2),
                    explanation=_EXPLANATION[insight_cat],
                    evidence=evidence,
                    related_tests=related,
                    failure_signature=sig,
                    rule_name=f"rule:{failure_cat.value}",
                )
            )

        # Step 5: Cluster failures (enriched signatures already set)
        clusters = cluster_failures(run.test_cases)

        # Step 6: Category counts
        cat_tally: dict[InsightCategory, int] = defaultdict(int)
        for ins in insights:
            cat_tally[ins.category] += 1

        category_counts = CategoryCounts(
            likely_flaky=cat_tally[InsightCategory.LIKELY_FLAKY],
            likely_environment_issue=cat_tally[InsightCategory.LIKELY_ENVIRONMENT_ISSUE],
            likely_test_script_issue=cat_tally[InsightCategory.LIKELY_TEST_SCRIPT_ISSUE],
            likely_product_defect=cat_tally[InsightCategory.LIKELY_PRODUCT_DEFECT],
            likely_test_data_issue=cat_tally[InsightCategory.LIKELY_TEST_DATA_ISSUE],
            unknown=cat_tally[InsightCategory.UNKNOWN],
        )

        # Step 7: Recommended triage actions
        recommended_actions: list[str] = []
        cc = category_counts
        if cc.likely_product_defect > 0:
            recommended_actions.append(
                f"Investigate {cc.likely_product_defect} likely product defect(s) first "
                "— these are stable, reproducible failures."
            )
        if cc.likely_environment_issue > 0:
            recommended_actions.append(
                f"Check test environment/infrastructure — {cc.likely_environment_issue} "
                "failure(s) suggest setup issues."
            )
        if cc.likely_flaky > 0:
            recommended_actions.append(
                f"Review {cc.likely_flaky} flaky test(s) for timing dependencies or retry logic."
            )
        if cc.likely_test_script_issue > 0:
            recommended_actions.append(
                f"Update test scripts — {cc.likely_test_script_issue} failure(s) due to "
                "stale locators or script errors."
            )
        if cc.likely_test_data_issue > 0:
            recommended_actions.append(
                f"Refresh test data — {cc.likely_test_data_issue} failure(s) caused by "
                "missing or invalid data."
            )
        big_clusters = [c for c in clusters if c.size >= 3]
        if big_clusters:
            top = big_clusters[0]
            recommended_actions.append(
                f"{top.size} tests share the same root cause ({top.label}) — "
                "fixing once may resolve all."
            )

        # Step 8: Flaky test IDs (for quick lookup by callers)
        flaky_test_ids = [
            ins.test_id
            for ins in insights
            if ins.category == InsightCategory.LIKELY_FLAKY
        ]

        return AnalysisSummary(
            run_id=run.metadata.run_id,
            report_format=run.metadata.report_format,
            report_path=run.metadata.report_path,
            status_counts=status_counts,
            category_counts=category_counts,
            insights=insights,
            clusters=clusters,
            flaky_test_ids=flaky_test_ids,
            recommended_actions=recommended_actions,
            extraction_warning_count=len(run.warnings),
            analysis_engine_version=__version__,
        )

    def summarize_report(
        self,
        analysis: AnalysisSummary,
        *,
        fmt: Literal["markdown", "json", "console"] = "console",
    ) -> str:
        """Render an :class:`~ari.models.insight.AnalysisSummary` as a string.

        Args:
            analysis: The ``AnalysisSummary`` produced by :meth:`analyze_report`.
            fmt: Output format — ``"markdown"``, ``"json"``, or
                ``"console"`` (Rich markup).

        Returns:
            The formatted summary string.

        """
        import json as _json

        if fmt == "json":
            return _json.dumps(analysis.model_dump(mode="json"), indent=2, default=str)
        if fmt == "markdown":
            return _render_analysis_markdown(analysis)
        return _render_analysis_console(analysis)


# ---------------------------------------------------------------------------
# Private rendering helpers (extracted to ari.api._render)
# ---------------------------------------------------------------------------

from qara.api._render import (  # noqa: E402, F401
    _render_analysis_markdown,
    _render_analysis_console,
)
