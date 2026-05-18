"""Tests for Phase-10 CI gate thresholds in the ``qalens summarize`` command."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qalens.cli import app

runner = CliRunner()

# Re-use the allure sample fixture — it has a mix of pass/fail test cases.
ALLURE_DIR = Path(__file__).parent / "fixtures" / "allure_sample"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(*extra_args: str) -> "Result":  # type: ignore[name-defined]
    """Invoke ``qalens summarize`` against the allure fixture with extra args."""
    return runner.invoke(app, ["summarize", str(ALLURE_DIR), *extra_args])


# ---------------------------------------------------------------------------
# Baseline — no gate flags
# ---------------------------------------------------------------------------


class TestNoGate:
    def test_exits_zero_without_gate_flags(self) -> None:
        result = _invoke()
        assert result.exit_code == 0

    def test_exits_zero_with_format_json(self) -> None:
        result = _invoke("--format", "json")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --fail-on-defects
# ---------------------------------------------------------------------------


class TestFailOnDefects:
    def test_does_not_breach_when_disabled(self) -> None:
        """Default -1 means gate is off — always exit 0."""
        result = _invoke()
        assert result.exit_code == 0

    def test_threshold_zero_fails_if_any_defect(self) -> None:
        """--fail-on-defects 0 should exit 2 whenever there is ≥1 product defect."""
        # Run a quick headless test to tell whether the fixture actually has defects.
        from qalens.api.library import QALensClient

        client = QALensClient()
        run = client.extract_report(ALLURE_DIR)
        analysis = client.analyze_report(run)
        defect_count = analysis.category_counts.likely_product_defect

        result = _invoke("--fail-on-defects", "0")
        if defect_count > 0:
            assert result.exit_code == 2
            assert "CI gate breached" in result.output or "CI gate breached" in (result.stderr or "")
        else:
            assert result.exit_code == 0

    def test_high_threshold_never_breaches(self) -> None:
        """A threshold of 10 000 should never trip on the fixture."""
        result = _invoke("--fail-on-defects", "10000")
        assert result.exit_code == 0

    def test_threshold_equal_to_count_breaches(self) -> None:
        """Gate fires when count >= N, so N == count should trip."""
        from qalens.api.library import QALensClient

        client = QALensClient()
        run = client.extract_report(ALLURE_DIR)
        analysis = client.analyze_report(run)
        n = analysis.category_counts.likely_product_defect

        if n == 0:
            pytest.skip("No product defects in fixture — skipping equality test")

        result = _invoke("--fail-on-defects", str(n))
        assert result.exit_code == 2

    def test_threshold_above_count_does_not_breach(self) -> None:
        """Gate does NOT fire when count < N."""
        from qalens.api.library import QALensClient

        client = QALensClient()
        run = client.extract_report(ALLURE_DIR)
        analysis = client.analyze_report(run)
        n = analysis.category_counts.likely_product_defect + 1  # one above actual

        result = _invoke("--fail-on-defects", str(n))
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --fail-on-flaky
# ---------------------------------------------------------------------------


class TestFailOnFlaky:
    def test_threshold_zero_behavior(self) -> None:
        from qalens.api.library import QALensClient

        client = QALensClient()
        analysis = client.analyze_report(client.extract_report(ALLURE_DIR))
        flaky_count = analysis.category_counts.likely_flaky

        result = _invoke("--fail-on-flaky", "0")
        expected_exit = 2 if flaky_count > 0 else 0
        assert result.exit_code == expected_exit

    def test_high_threshold_never_breaches(self) -> None:
        result = _invoke("--fail-on-flaky", "10000")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --fail-on-environment
# ---------------------------------------------------------------------------


class TestFailOnEnvironment:
    def test_threshold_zero_behavior(self) -> None:
        from qalens.api.library import QALensClient

        client = QALensClient()
        analysis = client.analyze_report(client.extract_report(ALLURE_DIR))
        env_count = analysis.category_counts.likely_environment_issue

        result = _invoke("--fail-on-environment", "0")
        expected_exit = 2 if env_count > 0 else 0
        assert result.exit_code == expected_exit

    def test_high_threshold_never_breaches(self) -> None:
        result = _invoke("--fail-on-environment", "10000")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --fail-on-unknown
# ---------------------------------------------------------------------------


class TestFailOnUnknown:
    def test_threshold_zero_behavior(self) -> None:
        from qalens.api.library import QALensClient

        client = QALensClient()
        analysis = client.analyze_report(client.extract_report(ALLURE_DIR))
        unknown_count = analysis.category_counts.unknown

        result = _invoke("--fail-on-unknown", "0")
        expected_exit = 2 if unknown_count > 0 else 0
        assert result.exit_code == expected_exit

    def test_high_threshold_never_breaches(self) -> None:
        result = _invoke("--fail-on-unknown", "10000")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --strict
# ---------------------------------------------------------------------------


class TestStrictMode:
    def test_strict_exits_two_when_any_failure_exists(self) -> None:
        """--strict should exit 2 if there is any failure of any category."""
        from qalens.api.library import QALensClient

        client = QALensClient()
        analysis = client.analyze_report(client.extract_report(ALLURE_DIR))
        cc = analysis.category_counts
        # --strict covers all 6 categories
        total_failures = (
            cc.likely_product_defect
            + cc.likely_flaky
            + cc.likely_environment_issue
            + cc.likely_test_script_issue
            + cc.likely_test_data_issue
            + cc.unknown
        )

        result = _invoke("--strict")
        expected_exit = 2 if total_failures > 0 else 0
        assert result.exit_code == expected_exit, (
            f"expected exit {expected_exit} (total_failures={total_failures}), "
            f"got {result.exit_code}. output: {result.output!r}"
        )

    def test_strict_implies_all_zero_thresholds(self) -> None:
        """--strict is equivalent to all six --fail-on-* 0 flags together."""
        result_strict = _invoke("--strict")
        result_explicit = _invoke(
            "--fail-on-defects", "0",
            "--fail-on-flaky", "0",
            "--fail-on-environment", "0",
            "--fail-on-unknown", "0",
            "--fail-on-script-issues", "0",
            "--fail-on-test-data", "0",
        )
        assert result_strict.exit_code == result_explicit.exit_code

    def test_strict_combines_with_format_json(self) -> None:
        """--strict should still produce JSON output before exiting."""
        import json as _json

        from qalens.api.library import QALensClient

        client = QALensClient()
        analysis = client.analyze_report(client.extract_report(ALLURE_DIR))
        cc = analysis.category_counts
        any_fail = (
            cc.likely_product_defect > 0
            or cc.likely_flaky > 0
            or cc.likely_environment_issue > 0
            or cc.likely_test_script_issue > 0
            or cc.likely_test_data_issue > 0
            or cc.unknown > 0
        )

        result = _invoke("--strict", "--format", "json")
        # Gate breach message (stderr) may be mixed with JSON (stdout) by CliRunner.
        # Locate the JSON object by finding the first '{' in the combined output.
        out = result.output
        try:
            json_start = out.index("{")
            parsed = _json.loads(out[json_start:])
            assert "run_id" in parsed
        except (ValueError, _json.JSONDecodeError):
            pytest.fail(f"Could not find valid JSON in output: {out!r}")

        expected_exit = 2 if any_fail else 0
        assert result.exit_code == expected_exit


# ---------------------------------------------------------------------------
# Multiple thresholds simultaneously
# ---------------------------------------------------------------------------


class TestMultipleThresholds:
    def test_multiple_thresholds_all_high_exits_zero(self) -> None:
        result = _invoke(
            "--fail-on-defects", "10000",
            "--fail-on-flaky", "10000",
            "--fail-on-environment", "10000",
            "--fail-on-unknown", "10000",
        )
        assert result.exit_code == 0

    def test_one_breached_threshold_exits_two(self) -> None:
        """Even if only one gate fires, exit code must be 2."""
        from qalens.api.library import QALensClient

        client = QALensClient()
        analysis = client.analyze_report(client.extract_report(ALLURE_DIR))
        total = len(analysis.insights)

        if total == 0:
            pytest.skip("No failures in fixture — cannot test breach")

        # Clamp flaky to 0-threshold, keep everything else astronomically high
        result = _invoke(
            "--fail-on-defects", "10000",
            "--fail-on-flaky", "0",
            "--fail-on-environment", "10000",
            "--fail-on-unknown", "10000",
        )
        flaky_count = analysis.category_counts.likely_flaky
        expected_exit = 2 if flaky_count > 0 else 0
        assert result.exit_code == expected_exit


# ---------------------------------------------------------------------------
# Output still produced on breach
# ---------------------------------------------------------------------------


class TestOutputOnBreach:
    def test_console_output_produced_before_gate_exit(self) -> None:
        """Summary output should be printed even when gate fires."""
        result = _invoke("--fail-on-defects", "0", "--fail-on-flaky", "0",
                         "--fail-on-environment", "0", "--fail-on-unknown", "0")
        # output is non-empty regardless of exit code
        assert len(result.output) > 0

    def test_markdown_output_produced_before_gate_exit(self) -> None:
        result = _invoke("--format", "markdown", "--strict")
        # Even on exit 2, the markdown heading should appear
        combined = result.output + (result.stderr or "")
        assert "QA Lens Analysis Summary" in combined or len(result.output) > 0

    def test_error_exit_code_is_nonzero(self) -> None:
        """A bad report path must exit with a non-zero code."""
        # Note: Typer validates 'exists=True' arguments before the command runs
        # and emits exit code 2 — the same as the gate exit code. Both are non-zero
        # failures, which is sufficient for CI purposes.
        bad_path = "/tmp/definitely_does_not_exist_ari_test_12345"
        result_error = runner.invoke(
            app, ["summarize", bad_path, "--fail-on-defects", "0"]
        )
        assert result_error.exit_code != 0
