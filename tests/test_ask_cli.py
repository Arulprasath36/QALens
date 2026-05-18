"""Tests for the ``qalens ask`` and ``qalens llm-config`` CLI commands (Phase 7)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qalens.cli import app
from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run(run_id: str, tests: list, seq: int = 1) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/ask_{run_id}.html",
        project="AskProject",
        started_at=datetime(2026, 3, seq, 10, 0, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _tc(
    name: str,
    status: TestStatus,
    *,
    idx: int = 1,
    error_type: str | None = None,
    message: str | None = None,
) -> TestCaseResult:
    failure = None
    if status in (TestStatus.FAILED, TestStatus.BROKEN):
        failure = FailureInfo(
            error_type=error_type or "org.openqa.selenium.NoSuchElementException",
            message=message or "no such element: Unable to locate element",
            stack_trace="    at com.example.TestPage.click(TestPage.java:42)",
        )
    return TestCaseResult(test_id=f"{name}-{idx}", name=name, status=status, failure=failure)


@pytest.fixture()
def ask_db(tmp_path) -> Path:
    db = tmp_path / "ask.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)
    for i in range(1, 4):
        repo.save_run(_make_run(f"run-{i:03d}", [
            _tc("testLogin", TestStatus.PASSED if i % 2 == 0 else TestStatus.FAILED, idx=i),
            _tc("testSearch", TestStatus.PASSED, idx=i),
        ], seq=i))
    conn.close()
    return db


@pytest.fixture()
def fix_db(tmp_path) -> Path:
    db = tmp_path / "fix.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)
    for i in range(1, 5):
        status = TestStatus.FAILED if i in {2, 4} else TestStatus.PASSED
        repo.save_run(
            _make_run(
                f"run-{i:03d}",
                [
                    _tc(
                        "testAddItemToCart()",
                        status,
                        idx=i,
                        error_type="com.shopnow.db.ConnectionPoolException",
                        message=(
                            "No connections available in pool "
                            "(pool_size=10, active=10, waiting=0)"
                        ),
                    ),
                    _tc("testSearch", TestStatus.PASSED, idx=i),
                ],
                seq=i,
            )
        )
    conn.close()
    return db


@pytest.fixture()
def mock_config(tmp_path) -> Path:
    """Write a config.toml pointing to a fake local Ollama."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[llm]\n"
        'provider = "ollama"\n'
        'base_url = "http://localhost:11434/v1"\n'
        'model = "llama3.2"\n'
        'api_key = ""\n'
        "timeout = 10\n",
        encoding="utf-8",
    )
    return cfg_path


# ---------------------------------------------------------------------------
# qalens llm-config --show
# ---------------------------------------------------------------------------


def test_llm_config_show(mock_config):
    result = runner.invoke(app, ["llm-config", "--show", "--config", str(mock_config)])
    assert result.exit_code == 0, result.output
    assert "ollama" in result.output.lower()


def test_llm_config_init_creates_file(tmp_path):
    """--init should write a default config without error."""
    cfg_path = tmp_path / "newconfig.toml"
    result = runner.invoke(app, ["llm-config", "--init", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output
    assert cfg_path.exists()
    assert "[llm]" in cfg_path.read_text()


def test_llm_config_shows_provider(mock_config):
    result = runner.invoke(app, ["llm-config", "--show", "--config", str(mock_config)])
    assert "Ollama" in result.output or "ollama" in result.output.lower()


def test_llm_config_shows_model(mock_config):
    result = runner.invoke(app, ["llm-config", "--show", "--config", str(mock_config)])
    assert "llama3.2" in result.output


# ---------------------------------------------------------------------------
# qalens ask — with mocked LLM via httpx_mock
# ---------------------------------------------------------------------------


def _intent_response(intents: list[str] | None = None) -> dict:
    """Return a mocked LLM response for ``parse_query_intent``."""
    payload = json.dumps({
        "intents": intents or ["general"],
        "owner_name": None,
        "test_name": None,
    })
    return {
        "choices": [{"message": {"role": "assistant", "content": payload}}]
    }


def test_ask_exits_nonzero_when_no_db_data_and_llm_fails(ask_db, mock_config, httpx_mock):
    """When LLM returns 500, qalens ask exits non-zero."""
    # First call: intent parse — return a valid intent so routing proceeds
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_intent_response(["root_cause"]),
    )
    # Second call: actual answer — return 500 to trigger the error path
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        status_code=500,
        text="Server Error",
    )
    result = runner.invoke(
        app,
        [
            "ask", "why does testLogin keep failing?",
            "--db", str(ask_db),
            "--project", "AskProject",
            "--config", str(mock_config),
        ],
    )
    assert result.exit_code != 0


def test_ask_exits_zero_with_valid_llm_response(ask_db, mock_config, httpx_mock):
    """When LLM returns a valid response, qalens ask exits 0 and prints the answer."""
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_intent_response(["root_cause"]),
    )
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json={
            "choices": [
                {"message": {"role": "assistant", "content": "The test is flaky due to timing issues."}}
            ]
        },
    )
    result = runner.invoke(
        app,
        [
            "ask", "why does testLogin keep failing?",
            "--db", str(ask_db),
            "--project", "AskProject",
            "--config", str(mock_config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "flaky" in result.output.lower() or "timing" in result.output.lower()


def test_ask_show_context_prints_context(ask_db, mock_config, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_intent_response(),
    )
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
    )
    result = runner.invoke(
        app,
        [
            "ask", "why does testLogin fail?",
            "--db", str(ask_db),
            "--project", "AskProject",
            "--config", str(mock_config),
            "--show-context",
        ],
    )
    assert result.exit_code == 0
    assert "testLogin" in result.output or "testlogin" in result.output.lower()


def test_ask_project_mode_on_summary_question(ask_db, mock_config):
    """Summary questions use the deterministic project-level answer path."""
    result = runner.invoke(
        app,
        [
            "ask", "summarize all failures",
            "--db", str(ask_db),
            "--project", "AskProject",
            "--config", str(mock_config),
        ],
    )
    assert result.exit_code == 0
    assert "QALens has" in result.output
    assert "Latest run" in result.output


def test_ask_fix_test_uses_deterministic_playbook(fix_db, mock_config):
    result = runner.invoke(
        app,
        [
            "ask", "how can I fix testAddItemToCart()?",
            "--db", str(fix_db),
            "--project", "AskProject",
            "--config", str(mock_config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Likely fix for" in result.output
    assert "database connection pool exhaustion" in result.output
    assert "What to check first" in result.output
    assert "Verification steps" in result.output


def test_ask_no_matching_test_falls_back_to_project_context(ask_db, mock_config, httpx_mock):
    """When no test matches by name, falls back to project context and calls LLM."""
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_intent_response(),
    )
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json={"choices": [{"message": {"role": "assistant", "content": "Fallback project answer."}}]},
    )
    result = runner.invoke(
        app,
        [
            "ask", "why does testXyzNonExistent fail?",
            "--db", str(ask_db),
            "--project", "AskProject",
            "--config", str(mock_config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "project context" in result.output.lower() or "Fallback" in result.output


# ---------------------------------------------------------------------------
# Context helpers (unit tests without CLI)
# ---------------------------------------------------------------------------


def test_gather_test_context_returns_string(ask_db):
    from qalens.llm.context import gather_test_context
    ctx, sources = gather_test_context("testLogin", project="AskProject", db_path=str(ask_db))
    assert isinstance(ctx, str)
    assert len(ctx) > 0
    assert isinstance(sources, list)


def test_gather_test_context_contains_test_name(ask_db):
    from qalens.llm.context import gather_test_context
    ctx, _ = gather_test_context("testLogin", project="AskProject", db_path=str(ask_db))
    assert "testLogin" in ctx or "testlogin" in ctx.lower()


def test_gather_test_context_contains_history(ask_db):
    from qalens.llm.context import gather_test_context
    ctx, _ = gather_test_context("testLogin", project="AskProject", db_path=str(ask_db))
    assert "history" in ctx.lower() or "✓" in ctx or "✗" in ctx


def test_gather_test_context_no_match_returns_message(ask_db):
    from qalens.llm.context import gather_test_context
    ctx, _ = gather_test_context("testNonExistent999", project="AskProject", db_path=str(ask_db))
    assert "not found" in ctx.lower() or "no test" in ctx.lower()


def test_gather_project_context_returns_string(ask_db):
    from qalens.llm.context import gather_project_context
    ctx, sources = gather_project_context(project="AskProject", db_path=str(ask_db))
    assert isinstance(ctx, str)
    assert "AskProject" in ctx
    assert isinstance(sources, list)


def test_gather_project_context_contains_counts(ask_db):
    from qalens.llm.context import gather_project_context
    ctx, _ = gather_project_context(project="AskProject", db_path=str(ask_db))
    assert "run" in ctx.lower()


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def test_build_prompt_test_mode():
    from qalens.llm.prompts import build_prompt
    prompt = build_prompt("Why does testLogin fail?", "context block", mode="test")
    assert "context block" in prompt
    assert "Why does testLogin fail?" in prompt
    assert "root-cause" in prompt.lower() or "hypothesis" in prompt.lower()


def test_build_prompt_project_mode():
    from qalens.llm.prompts import build_prompt
    prompt = build_prompt("Summarize failures", "project context", mode="project")
    assert "project context" in prompt
    assert "Summarize failures" in prompt


def test_infer_mode_test():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("why does testLogin keep failing?") == "test"


def test_infer_mode_project_summarize():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("summarize all failures") == "project"


def test_infer_mode_project_overview():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("give me an overview of the test health") == "project"


def test_infer_mode_project_which_tests():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("which tests are failing the most?") == "project"


def test_infer_mode_project_which_test_singular():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("which test has less than 50% pass percentage?") == "project"


def test_infer_mode_project_less_than():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("which tests have less than 50 percent pass rate?") == "project"


def test_infer_mode_project_percentage():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("what is the pass percentage of all tests?") == "project"


def test_infer_mode_project_worst():
    from qalens.llm.prompts import infer_mode
    assert infer_mode("which test has the worst pass rate?") == "project"
