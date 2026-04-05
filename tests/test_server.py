"""Tests for Phase 8 — Web UI (server/app.py).

Uses FastAPI's synchronous TestClient (backed by httpx) so no async
event loop is needed in the test process.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qara.db.repository import RunRepository
from qara.db.schema import get_connection
from qara.models.failure import FailureInfo
from qara.models.run import RunMetadata, TestRun
from qara.models.test_case import TestCaseResult, TestStatus
from qara.server.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str,
    tests: list[TestCaseResult],
    *,
    seq: int = 1,
    project: str = "ServerProject",
) -> TestRun:
    meta = RunMetadata(
        run_id=run_id,
        report_format="allure",
        report_path=f"/tmp/server_{run_id}.html",
        project=project,
        started_at=datetime(2026, 3, seq, 10, 0, 0, tzinfo=timezone.utc),
    )
    return TestRun(metadata=meta, test_cases=tests)


def _tc(
    name: str,
    status: TestStatus,
    *,
    idx: int = 1,
    error_type: str | None = None,
) -> TestCaseResult:
    failure = None
    if status in (TestStatus.FAILED, TestStatus.BROKEN) and error_type:
        failure = FailureInfo(
            error_type=error_type,
            message=f"{name} failed with {error_type}",
            stack_trace="   at com.example.Test.run(Test.java:42)",
        )
    return TestCaseResult(
        test_id=f"{name}-{idx}",
        name=name,
        status=status,
        failure=failure,
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Populate a fresh SQLite DB with two runs of three tests each."""
    db = tmp_path / "server_test.db"
    conn = get_connection(str(db))
    repo = RunRepository(conn)

    # Run 1: login passes, search fails, create fails
    run1 = _make_run(
        "run-001",
        [
            _tc("testLogin", TestStatus.PASSED, idx=1),
            _tc("testSearch", TestStatus.FAILED, idx=1,
                error_type="org.openqa.selenium.NoSuchElementException"),
            _tc("testCreate", TestStatus.FAILED, idx=1,
                error_type="java.lang.AssertionError"),
        ],
        seq=1,
    )
    # Run 2: login fails, search passes, create fails
    run2 = _make_run(
        "run-002",
        [
            _tc("testLogin", TestStatus.FAILED, idx=2,
                error_type="org.openqa.selenium.NoSuchElementException"),
            _tc("testSearch", TestStatus.PASSED, idx=2),
            _tc("testCreate", TestStatus.FAILED, idx=2,
                error_type="java.lang.AssertionError"),
        ],
        seq=2,
    )

    repo.save_run(run1)
    repo.save_run(run2)
    conn.close()
    return db


@pytest.fixture()
def client(db_path: Path) -> TestClient:
    """Return a TestClient wired to the temp database."""
    appl = create_app(db_path=str(db_path), default_project="ServerProject")
    return TestClient(appl, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "version" in data


# ---------------------------------------------------------------------------
# SPA index
# ---------------------------------------------------------------------------


def test_index_returns_html(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "<title>QARA" in body
    assert "chat-messages" in body  # Chat panel present
    assert "panel-runs" in body     # Runs panel present


def test_index_includes_default_project(db_path: Path) -> None:
    appl = create_app(db_path=str(db_path), default_project="MyProject")
    c = TestClient(appl)
    res = c.get("/")
    assert "MyProject" in res.text


def test_index_no_default_project(db_path: Path) -> None:
    appl = create_app(db_path=str(db_path))
    c = TestClient(appl)
    res = c.get("/")
    assert res.status_code == 200
    # Empty default project should render as empty string via injection shim
    assert 'window._QARA_DEFAULT_PROJECT = ""' in res.text


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------


def test_static_css_served(client: TestClient) -> None:
    res = client.get("/static/app.css")
    assert res.status_code == 200
    assert "text/css" in res.headers["content-type"]


def test_static_js_served(client: TestClient) -> None:
    res = client.get("/static/app.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def test_list_projects_returns_project(client: TestClient) -> None:
    res = client.get("/api/projects")
    assert res.status_code == 200
    projects = res.json()
    assert "ServerProject" in projects


def test_list_projects_is_sorted(db_path: Path) -> None:
    """Multiple projects should be returned in sorted order."""
    conn = get_connection(str(db_path))
    repo = RunRepository(conn)
    run_z = _make_run(
        "run-z", [_tc("t", TestStatus.PASSED)], seq=1, project="ZProject"
    )
    run_a = _make_run(
        "run-a", [_tc("t", TestStatus.PASSED)], seq=1, project="AProject"
    )
    repo.save_run(run_z)
    repo.save_run(run_a)
    conn.close()

    appl = create_app(db_path=str(db_path))
    c = TestClient(appl)
    projects = c.get("/api/projects").json()
    assert projects == sorted(projects)


def test_list_projects_empty_db(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty.db"
    # Use RunRepository to initialize the schema, then close.
    from qara.db.repository import RunRepository
    from qara.db.schema import get_connection
    conn = get_connection(str(empty_db))
    RunRepository(conn)  # triggers init_db
    conn.close()

    appl = create_app(db_path=str(empty_db))
    c = TestClient(appl)
    res = c.get("/api/projects")
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_two(client: TestClient) -> None:
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.json()
    assert len(runs) == 2


def test_list_runs_project_filter(client: TestClient) -> None:
    res = client.get("/api/runs?project=ServerProject")
    assert res.status_code == 200
    runs = res.json()
    assert all(r["project"] == "ServerProject" for r in runs)


def test_list_runs_unknown_project_returns_empty(client: TestClient) -> None:
    res = client.get("/api/runs?project=DoesNotExist")
    assert res.status_code == 200
    assert res.json() == []


def test_get_run_returns_correct_run(client: TestClient) -> None:
    runs = client.get("/api/runs").json()
    run_id = runs[0]["run_id"]
    res = client.get(f"/api/runs/{run_id}")
    assert res.status_code == 200
    assert res.json()["run_id"] == run_id


def test_get_run_not_found(client: TestClient) -> None:
    res = client.get("/api/runs/no-such-run")
    assert res.status_code == 404


def test_get_run_tests_returns_tests(client: TestClient) -> None:
    runs = client.get("/api/runs").json()
    run_id = runs[0]["run_id"]
    res = client.get(f"/api/runs/{run_id}/tests")
    assert res.status_code == 200
    tests = res.json()
    assert len(tests) == 3


def test_get_run_tests_status_filter(client: TestClient) -> None:
    runs = client.get("/api/runs").json()
    run_id = runs[0]["run_id"]
    res = client.get(f"/api/runs/{run_id}/tests?status=failed")
    assert res.status_code == 200
    tests = res.json()
    assert all(t["status"] == "failed" for t in tests)


def test_get_run_tests_not_found(client: TestClient) -> None:
    res = client.get("/api/runs/no-such/tests")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Stability / flakiness
# ---------------------------------------------------------------------------


def test_stability_returns_results(client: TestClient) -> None:
    res = client.get("/api/stability?project=ServerProject")
    assert res.status_code == 200
    data = res.json()
    # With 2 runs each test should have a result
    assert len(data) >= 2
    assert all("classification" in r for r in data)
    assert all("sparkline" in r for r in data)


def test_stability_flaky_endpoint(client: TestClient) -> None:
    """The /api/stability/flaky endpoint should only return FLAKY items."""
    res = client.get("/api/stability/flaky?project=ServerProject")
    assert res.status_code == 200
    data = res.json()
    assert all(r["classification"] == "FLAKY" for r in data)


def test_stability_no_results_empty_db(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty2.db"
    from qara.db.repository import RunRepository
    from qara.db.schema import get_connection
    conn = get_connection(str(empty_db))
    RunRepository(conn)  # triggers init_db
    conn.close()

    appl = create_app(db_path=str(empty_db))
    c = TestClient(appl)
    res = c.get("/api/stability")
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Failure groups
# ---------------------------------------------------------------------------


def test_failure_groups_returns_groups(client: TestClient) -> None:
    res = client.get("/api/failure-groups?project=ServerProject")
    assert res.status_code == 200
    groups = res.json()
    assert isinstance(groups, list)
    assert len(groups) >= 1
    assert "fingerprint" in groups[0]
    assert "occurrence_count" in groups[0]


def test_failure_groups_limit(client: TestClient) -> None:
    res = client.get("/api/failure-groups?limit=1")
    assert res.status_code == 200
    groups = res.json()
    assert len(groups) <= 1


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Ask  (LLM — mocked)
# ---------------------------------------------------------------------------


def test_ask_empty_question(client: TestClient) -> None:
    res = client.post("/api/ask", json={"question": "   ", "project": "ServerProject"})
    assert res.status_code == 400


def test_ask_llm_error_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """When LLMClient.chat raises LLMError the endpoint should return 503."""
    from qara.llm.client import LLMError

    class _BrokenClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def chat(self, _prompt: str, **_kw: object) -> str:
            raise LLMError("connection refused")

    class _FakeCfg:
        pass

    monkeypatch.setattr("qara.llm.config.load_config", lambda *_a, **_kw: _FakeCfg())
    monkeypatch.setattr("qara.llm.client.LLMClient", _BrokenClient)

    res = client.post("/api/ask", json={"question": "What failed?", "project": "ServerProject"})
    assert res.status_code == 503


def test_ask_returns_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the LLM chain and verify the response shape."""

    class _MockClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def chat(self, _prompt: str, **_kw: object) -> str:
            return "testCreate is consistently broken."

    class _MockCfg:
        pass

    monkeypatch.setattr("qara.llm.config.load_config", lambda *_a, **_kw: _MockCfg())
    monkeypatch.setattr("qara.llm.client.LLMClient", _MockClient)

    res = client.post(
        "/api/ask",
        json={"question": "Which test is always failing?", "project": "ServerProject"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert "context_mode" in data
    assert "sources" in data
    assert isinstance(data["sources"], list)
    assert data["answer"] == "testCreate is consistently broken."


def test_ask_surrogate_chars_in_llm_answer_do_not_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM answers OR source records containing lone surrogates must not crash.

    Lone surrogates (U+D800–U+DFFF) can appear in:
    - LLM output when multi-byte characters are split at a streaming boundary
    - Database content (test names, error messages with emoji stored as
      surrogate pairs in SQLite)

    Both must be stripped before JSON serialisation.
    """

    class _MockClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def chat(self, _prompt: str, **_kw: object) -> str:
            # Embed a lone high surrogate between normal text
            return "Answer with \ud83d surrogate \udc00 chars."

    class _MockCfg:
        pass

    monkeypatch.setattr("qara.llm.config.load_config", lambda *_a, **_kw: _MockCfg())
    monkeypatch.setattr("qara.llm.client.LLMClient", _MockClient)

    res = client.post(
        "/api/ask",
        json={"question": "Any question?", "project": "ServerProject"},
    )
    assert res.status_code == 200
    data = res.json()
    # Surrogates stripped — no crash, remaining text intact
    assert "Answer with" in data["answer"]
    assert "chars." in data["answer"]
    # Confirm no surrogate code points survive in the serialised answer
    for ch in data["answer"]:
        assert not (0xD800 <= ord(ch) <= 0xDFFF), f"Surrogate found in answer: {ch!r}"


def test_ask_response_model_sanitizes_sources_surrogates() -> None:
    """AskResponse.sources validator strips surrogates from nested DB content."""
    from qara.server.models import AskResponse

    dirty_sources = [
        {
            "type": "run",
            "test_name": "testLogin\ud83d\udc00",
            "error_message": "Expected \ud83d but got \udc00 instead",
            "nested": {"stack": "line 1\ud83d\nline 2"},
        }
    ]
    resp = AskResponse(answer="ok", context_mode="project", sources=dirty_sources)
    for src in resp.sources:
        for val in src.values():
            flat = str(val)
            for ch in flat:
                assert not (0xD800 <= ord(ch) <= 0xDFFF), f"Surrogate in sources: {ch!r}"


# ---------------------------------------------------------------------------
# OpenAPI / docs
# ---------------------------------------------------------------------------


def test_openapi_docs_available(client: TestClient) -> None:
    res = client.get("/api/docs")
    assert res.status_code == 200
    assert "swagger" in res.text.lower() or "openapi" in res.text.lower()


def test_openapi_schema_has_routes(client: TestClient) -> None:
    res = client.get("/openapi.json")
    assert res.status_code == 200
    paths = res.json()["paths"]
    assert "/api/health" in paths
    assert "/api/runs" in paths
    assert "/api/stability" in paths
    assert "/api/ask" in paths


# ---------------------------------------------------------------------------
# Evidence Drawer — test endpoint
# ---------------------------------------------------------------------------

# canonical names produced by to_canonical_name() for the fixture:
#   "testCreate" → "testcreate"  (fails in both runs → BROKEN)
#   "testLogin"  → "testlogin"   (passes run-001, fails run-002 → FLAKY)
#   "testSearch" → "testsearch"  (fails run-001, passes run-002 → FLAKY)

_EVIDENCE_TEST_KEYS = (
    "type", "canonical_name", "title", "classification",
    "pass_rate", "flip_score", "run_count", "sparkline",
    "why_relevant", "recent_runs", "most_frequent_error",
    "owner", "actions",
)

_EVIDENCE_RUN_KEYS = (
    "type", "run_id", "title", "project",
    "total_tests", "passed_count", "failed_count", "skipped_count",
    "top_failed", "recurring_pattern", "actions",
)


class TestEvidenceTestEndpoint:
    def test_returns_200_for_known_test(self, client: TestClient) -> None:
        res = client.get("/api/evidence/test/testcreate?project=ServerProject")
        assert res.status_code == 200

    def test_payload_has_all_expected_keys(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        for key in _EVIDENCE_TEST_KEYS:
            assert key in data, f"Missing evidence key: {key!r}"

    def test_type_field_is_test(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert data["type"] == "test"

    def test_canonical_name_is_normalised(self, client: TestClient) -> None:
        """URL with mixed-case and URL-decoded form should normalise the same."""
        res_lower = client.get("/api/evidence/test/testcreate?project=ServerProject")
        res_mixed = client.get("/api/evidence/test/testCreate?project=ServerProject")
        assert res_lower.status_code == 200
        assert res_mixed.status_code == 200
        assert res_lower.json()["canonical_name"] == res_mixed.json()["canonical_name"]

    def test_run_count_matches_fixture(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert data["run_count"] == 2

    def test_classification_is_present_and_non_empty(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert data["classification"] and len(data["classification"]) > 0

    def test_always_failing_test_has_zero_pass_rate(self, client: TestClient) -> None:
        """testCreate fails in both runs — pass_rate must be 0."""
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert data["pass_rate"] == 0.0

    def test_why_relevant_is_non_empty_list(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert isinstance(data["why_relevant"], list)
        assert len(data["why_relevant"]) >= 1

    def test_why_relevant_entries_are_strings(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert all(isinstance(b, str) and len(b) > 0 for b in data["why_relevant"])

    def test_recent_runs_is_list(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert isinstance(data["recent_runs"], list)
        assert len(data["recent_runs"]) >= 1

    def test_recent_runs_entries_have_required_fields(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        for entry in data["recent_runs"]:
            assert "run_id" in entry
            assert "run_label" in entry
            assert "status" in entry

    def test_most_frequent_error_populated_for_always_failing_test(
        self, client: TestClient
    ) -> None:
        """testCreate always fails with AssertionError — most_frequent_error must reflect this."""
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        err = data["most_frequent_error"]
        assert err is not None
        assert "java.lang.AssertionError" in err["category"]
        assert "message" in err

    def test_actions_has_history_and_risk_urls(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        actions = data["actions"]
        assert "history_url" in actions
        assert "risk_url" in actions

    def test_flaky_test_returns_200(self, client: TestClient) -> None:
        """testLogin flips — it should also resolve successfully."""
        res = client.get("/api/evidence/test/testlogin?project=ServerProject")
        assert res.status_code == 200

    def test_flaky_test_has_why_relevant(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testlogin?project=ServerProject"
        ).json()
        assert len(data["why_relevant"]) >= 1

    def test_project_filter_isolates_data(self, client: TestClient) -> None:
        """Filtering by a non-existent project returns 404 (no history)."""
        res = client.get("/api/evidence/test/testcreate?project=NoSuchProject")
        assert res.status_code == 404

    def test_returns_404_for_unknown_canonical_name(self, client: TestClient) -> None:
        res = client.get("/api/evidence/test/absolutely-no-such-test-xyz")
        assert res.status_code == 404

    def test_sparkline_is_string(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testcreate?project=ServerProject"
        ).json()
        assert isinstance(data["sparkline"], str)

    def test_pass_rate_is_float_in_range(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testlogin?project=ServerProject"
        ).json()
        assert 0.0 <= data["pass_rate"] <= 1.0

    def test_flip_score_is_float_in_range(self, client: TestClient) -> None:
        data = client.get(
            "/api/evidence/test/testlogin?project=ServerProject"
        ).json()
        assert 0.0 <= data["flip_score"] <= 1.0


# ---------------------------------------------------------------------------
# Evidence Drawer — run endpoint
# ---------------------------------------------------------------------------


class TestEvidenceRunEndpoint:
    """Tests for GET /api/evidence/run/{run_id}."""

    def _run_id(self, client: TestClient, label: str = "run-001") -> str:
        """Return a real run ID from the fixture DB."""
        runs = client.get("/api/runs?project=ServerProject").json()
        match = next((r for r in runs if r["run_id"] == label), None)
        return match["run_id"] if match else runs[0]["run_id"]

    def test_returns_200_for_known_run(self, client: TestClient) -> None:
        res = client.get(f"/api/evidence/run/{self._run_id(client)}")
        assert res.status_code == 200

    def test_payload_has_all_expected_keys(self, client: TestClient) -> None:
        data = client.get(f"/api/evidence/run/{self._run_id(client)}").json()
        for key in _EVIDENCE_RUN_KEYS:
            assert key in data, f"Missing run-evidence key: {key!r}"

    def test_type_field_is_run(self, client: TestClient) -> None:
        data = client.get(f"/api/evidence/run/{self._run_id(client)}").json()
        assert data["type"] == "run"

    def test_run_id_echoed_in_response(self, client: TestClient) -> None:
        run_id = self._run_id(client)
        data = client.get(f"/api/evidence/run/{run_id}").json()
        assert data["run_id"] == run_id

    def test_project_echoed_in_response(self, client: TestClient) -> None:
        data = client.get(f"/api/evidence/run/{self._run_id(client)}").json()
        assert data["project"] == "ServerProject"

    def test_total_tests_is_three(self, client: TestClient) -> None:
        """Each fixture run has exactly 3 test cases."""
        data = client.get("/api/evidence/run/run-001").json()
        assert data["total_tests"] == 3

    def test_failed_count_for_run_001(self, client: TestClient) -> None:
        """run-001: testSearch and testCreate are FAILED → failed_count == 2."""
        data = client.get("/api/evidence/run/run-001").json()
        assert data["failed_count"] == 2

    def test_passed_count_for_run_001(self, client: TestClient) -> None:
        """run-001: only testLogin passes."""
        data = client.get("/api/evidence/run/run-001").json()
        assert data["passed_count"] == 1

    def test_top_failed_is_list(self, client: TestClient) -> None:
        data = client.get("/api/evidence/run/run-001").json()
        assert isinstance(data["top_failed"], list)
        assert len(data["top_failed"]) >= 1

    def test_top_failed_entries_have_required_fields(self, client: TestClient) -> None:
        data = client.get("/api/evidence/run/run-001").json()
        for entry in data["top_failed"]:
            assert "name" in entry
            assert "status" in entry

    def test_top_failed_limited_to_five(self, client: TestClient) -> None:
        data = client.get(f"/api/evidence/run/{self._run_id(client)}").json()
        assert len(data["top_failed"]) <= 5

    def test_top_failed_only_contains_failed_or_broken_tests(
        self, client: TestClient
    ) -> None:
        data = client.get("/api/evidence/run/run-001").json()
        names = {e["name"] for e in data["top_failed"]}
        # testLogin passed in run-001 — must not appear in top_failed
        assert "testLogin" not in names

    def test_title_is_non_empty_string(self, client: TestClient) -> None:
        data = client.get(f"/api/evidence/run/{self._run_id(client)}").json()
        assert isinstance(data["title"], str) and len(data["title"]) > 0

    def test_actions_has_run_url(self, client: TestClient) -> None:
        run_id = self._run_id(client)
        data = client.get(f"/api/evidence/run/{run_id}").json()
        assert "run_url" in data["actions"]
        assert run_id in data["actions"]["run_url"]

    def test_recurring_pattern_is_none_or_valid_dict(
        self, client: TestClient
    ) -> None:
        """recurring_pattern is either None or a properly shaped dict."""
        data = client.get("/api/evidence/run/run-001").json()
        pattern = data["recurring_pattern"]
        # None when no fingerprint repeats; dict with required keys when it does.
        if pattern is not None:
            assert "count" in pattern
            assert "error_type" in pattern
            assert "message" in pattern
            assert pattern["count"] >= 2

    def test_returns_404_for_unknown_run(self, client: TestClient) -> None:
        res = client.get("/api/evidence/run/no-such-run-xyz-99999")
        assert res.status_code == 404

    def test_evidence_routes_in_openapi_schema(self, client: TestClient) -> None:
        """Both evidence routes should be listed in the OpenAPI schema."""
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/evidence/test/{canonical_name}" in paths
        assert "/api/evidence/run/{run_id}" in paths
