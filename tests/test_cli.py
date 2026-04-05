"""Tests for the QARA CLI (Phase 9)."""

from __future__ import annotations

from typer.testing import CliRunner

from qara.cli import app
from qara.version import __version__

runner = CliRunner()


class TestVersionFlag:
    def test_version_short(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_long(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestHelpText:
    def test_root_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "QARA" in result.output

    def test_detect_help(self) -> None:
        result = runner.invoke(app, ["detect", "--help"])
        assert result.exit_code == 0
        assert "report" in result.output.lower()

    def test_extract_help(self) -> None:
        result = runner.invoke(app, ["extract", "--help"])
        assert result.exit_code == 0

    def test_analyze_help(self) -> None:
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0

    def test_summarize_help(self) -> None:
        result = runner.invoke(app, ["summarize", "--help"])
        assert result.exit_code == 0

    def test_clusters_help(self) -> None:
        result = runner.invoke(app, ["clusters", "--help"])
        assert result.exit_code == 0
