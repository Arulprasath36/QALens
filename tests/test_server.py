"""Tests for Phase 8 — Web UI (server/app.py).

Uses FastAPI's synchronous TestClient (backed by httpx) so no async
event loop is needed in the test process.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from qalens.db.repository import RunRepository
from qalens.db.schema import get_connection
from qalens.models.failure import FailureInfo
from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.server.app import create_app

if TYPE_CHECKING:
    from pathlib import Path


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


def test_security_headers_present(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
    assert "camera=()" in res.headers["permissions-policy"]


# ---------------------------------------------------------------------------
# SPA index
# ---------------------------------------------------------------------------


def test_index_returns_html(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "<title>QA Lens" in body
    assert '<div id="root"' in body   # React root present


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
    assert 'window._QALENS_DEFAULT_PROJECT = ""' in res.text


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------


def test_static_assets_served(client: TestClient) -> None:
    """Assets referenced by the Vite-built index.html must all return 200.

    The asset filenames are content-hashed (e.g. index-DoZ8iY13.js), so we
    extract the paths from the served HTML rather than hardcoding them.
    """
    body = client.get("/").text
    js_paths  = re.findall(r'src="(/static/assets/[^"]+\.js)"', body)
    css_paths = re.findall(r'href="(/static/assets/[^"]+\.css)"', body)
    assert js_paths,  "No JS asset found in index.html — run make build-ui"
    assert css_paths, "No CSS asset found in index.html — run make build-ui"
    for url in js_paths + css_paths:
        res = client.get(url)
        assert res.status_code == 200, f"Asset not served: {url}"


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
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection
    conn = get_connection(str(empty_db))
    RunRepository(conn)  # triggers init_db
    conn.close()

    appl = create_app(db_path=str(empty_db))
    c = TestClient(appl)
    res = c.get("/api/projects")
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Decision intelligence
# ---------------------------------------------------------------------------


def test_decision_summary_latest_run(client: TestClient) -> None:
    res = client.get("/api/decision-summary?project=ServerProject")

    assert res.status_code == 200
    data = res.json()
    assert data["scope"]["run_sequence"] == 2
    assert data["executive_summary"]
    assert data["trend_intelligence"]
    assert data["fix_first"]
    assert data["fix_first"][0]["category"] in {"regression", "incident", "risk"}


def test_decision_summary_project_scope(db_path: Path) -> None:
    conn = get_connection(str(db_path))
    repo = RunRepository(conn)
    repo.save_run(
        _make_run(
            "other-run",
            [_tc("other", TestStatus.PASSED)],
            seq=1,
            project="OtherProject",
        )
    )
    conn.close()

    appl = create_app(db_path=str(db_path))
    c = TestClient(appl)
    data = c.get("/api/decision-summary?project=OtherProject").json()

    assert data["scope"]["project"] == "OtherProject"
    assert data["scope"]["run_id"] == "other-run"


def test_decision_summary_empty_database(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty-decision.db"
    conn = get_connection(str(empty_db))
    RunRepository(conn)
    conn.close()

    appl = create_app(db_path=str(empty_db))
    c = TestClient(appl)
    res = c.get("/api/decision-summary")

    assert res.status_code == 200
    data = res.json()
    assert data["scope"]["run_id"] is None
    assert data["fix_first"] == []
    assert "No QA Lens runs" in data["executive_summary"][0]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_returns_runtime_and_llm_config(db_path: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    appl = create_app(db_path=str(db_path), config_path=str(config))
    c = TestClient(appl)

    res = c.get("/api/settings")

    assert res.status_code == 200
    data = res.json()
    assert data["runtime"]["database_path"] == str(db_path)
    assert data["runtime"]["config_path"] == str(config)
    assert data["llm"]["provider"] == "ollama"
    assert data["llm"]["enabled"] is True
    assert data["llm"]["api_key_configured"] is False
    assert data["artifacts"]["svg_enabled"] is False
    assert data["security"]["redaction_enabled"] is True


def test_settings_updates_llm_config(db_path: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    appl = create_app(db_path=str(db_path), config_path=str(config))
    c = TestClient(appl)

    res = c.patch(
        "/api/settings/llm",
        json={
            "provider": "lmstudio",
            "enabled": False,
            "model": "google/gemma-4-e4b",
            "base_url": "http://localhost:1234/v1",
            "max_tokens": 4096,
            "timeout": 90,
            "temperature": 0.1,
            "allow_external": False,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["llm"]["provider"] == "lmstudio"
    assert body["llm"]["enabled"] is False
    assert body["llm"]["model"] == "google/gemma-4-e4b"
    assert "enabled = false" in config.read_text(encoding="utf-8")
    assert "allow_external = false" in config.read_text(encoding="utf-8")


def test_settings_can_reenable_llm_assistance(
    db_path: Path,
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    appl = create_app(db_path=str(db_path), config_path=str(config))
    c = TestClient(appl)

    disabled = c.patch("/api/settings/llm", json={"enabled": False})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["llm"]["enabled"] is False

    enabled = c.patch("/api/settings/llm", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["llm"]["enabled"] is True

    reloaded = c.get("/api/settings")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["llm"]["enabled"] is True
    assert "enabled = true" in config.read_text(encoding="utf-8")


def test_settings_treats_local_openai_compatible_endpoint_as_local(
    db_path: Path,
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    appl = create_app(db_path=str(db_path), config_path=str(config))
    c = TestClient(appl)

    res = c.patch(
        "/api/settings/llm",
        json={
            "provider": "openai",
            "model": "gemma-4-e4b",
            "base_url": "http://localhost:11434/v1",
            "allow_external": False,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["llm"]["endpoint_is_local"] is True
    assert body["llm"]["external_llm_allowed"] is True


def test_settings_rejects_unknown_llm_provider(
    db_path: Path,
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    appl = create_app(db_path=str(db_path), config_path=str(config))
    c = TestClient(appl)

    res = c.patch("/api/settings/llm", json={"provider": "not-real"})

    assert res.status_code == 422
    assert "Unsupported provider" in res.text


def test_auth_status_reports_disabled_by_default(db_path: Path) -> None:
    appl = create_app(db_path=str(db_path), auth_token="")
    c = TestClient(appl)

    res = c.get("/api/auth/status")

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "none"
    assert body["required"] is False
    assert body["authenticated"] is True


def test_auth_token_protects_api_routes(db_path: Path) -> None:
    appl = create_app(db_path=str(db_path), auth_token="secret-token")
    c = TestClient(appl)

    assert c.get("/api/health").status_code == 200
    status = c.get("/api/auth/status").json()
    assert status["mode"] == "token"
    assert status["required"] is True
    assert status["authenticated"] is False

    unauthorized = c.get("/api/projects")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"

    authorized = c.get(
        "/api/projects",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert authorized.status_code == 200


def test_auth_status_accepts_valid_bearer_token(db_path: Path) -> None:
    appl = create_app(db_path=str(db_path), auth_token="secret-token")
    c = TestClient(appl)

    res = c.get(
        "/api/auth/status",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "token"
    assert body["required"] is True
    assert body["authenticated"] is True


def test_github_auth_redirects_home_to_login(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QALENS_AUTH_MODE", "github")
    monkeypatch.setenv("QALENS_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("QALENS_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("QALENS_SESSION_SECRET", "session-secret")
    appl = create_app(db_path=str(db_path))
    c = TestClient(appl, follow_redirects=False)

    res = c.get("/")

    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_github_login_page_is_available(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QALENS_AUTH_MODE", "github")
    monkeypatch.setenv("QALENS_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("QALENS_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("QALENS_SESSION_SECRET", "session-secret")
    appl = create_app(db_path=str(db_path))
    c = TestClient(appl)

    res = c.get("/login")

    assert res.status_code == 200
    assert "Continue with GitHub" in res.text
    assert "/auth/github/start" in res.text


def test_github_oauth_callback_sets_session_cookie(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qalens.server.auth import GitHubUser
    import qalens.server.auth as auth_module

    monkeypatch.setenv("QALENS_AUTH_MODE", "github")
    monkeypatch.setenv("QALENS_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("QALENS_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("QALENS_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("QALENS_ALLOWED_GITHUB_USERS", "octocat")

    async def fake_fetch_github_identity(**kwargs):
        return (
            GitHubUser(
                login="octocat",
                name="The Octocat",
                avatar_url="https://github.com/images/error/octocat_happy.gif",
                html_url="https://github.com/octocat",
            ),
            frozenset(),
        )

    monkeypatch.setattr(auth_module, "_fetch_github_identity", fake_fetch_github_identity)
    appl = create_app(db_path=str(db_path))
    c = TestClient(appl, follow_redirects=False)

    start = c.get("/auth/github/start")
    assert start.status_code == 303
    # State is now stored server-side; read it from the GitHub redirect URL
    from urllib.parse import urlparse, parse_qs
    location = start.headers["location"]
    state = parse_qs(urlparse(location).query).get("state", [None])[0]
    assert state

    callback = c.get(f"/auth/github/callback?code=fake-code&state={state}")
    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    assert c.cookies.get("qalens_session")

    me = c.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["authenticated"] is True
    assert body["user"]["login"] == "octocat"


def test_ask_fix_test_returns_deterministic_playbook(db_path: Path) -> None:
    conn = get_connection(str(db_path))
    repo = RunRepository(conn)
    for idx in range(3, 6):
        status = TestStatus.FAILED if idx in {3, 5} else TestStatus.PASSED
        failure = None
        if status == TestStatus.FAILED:
            failure = FailureInfo(
                error_type="com.shopnow.db.ConnectionPoolException",
                message=(
                    "No connections available in pool "
                    "(pool_size=10, active=10, waiting=0)"
                ),
                stack_trace="at com.shopnow.CartRepository.add(CartRepository.java:42)",
            )
        repo.save_run(
            _make_run(
                f"run-cart-{idx}",
                [
                    TestCaseResult(
                        test_id=f"cart-{idx}",
                        name="testAddItemToCart()",
                        status=status,
                        failure=failure,
                    )
                ],
                seq=idx,
            )
        )
    conn.close()

    appl = create_app(db_path=str(db_path))
    c = TestClient(appl)
    res = c.post(
        "/api/ask",
        json={"question": "How can I fix testAddItemToCart()?", "project": "ServerProject"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "deterministic"
    assert "database connection pool exhaustion" in data["answer"]
    assert "Open the workspace" in data["answer"]
    assert "Verification steps" not in data["answer"]
    assert data["uiHints"]["activeTab"] == "results"
    assert data["uiHints"]["openWorkspace"] is True
    assert data["result"]["type"] == "test_fix_playbook"
    assert data["result"]["testName"] == "testAddItemToCart()"
    assert data["result"]["diagnosis"] == "database connection pool exhaustion"
    assert data["result"]["checks"]
    assert data["result"]["verification"]


def test_ask_run_pass_rate_extremes_are_deterministic(db_path: Path) -> None:
    conn = get_connection(str(db_path))
    repo = RunRepository(conn)
    repo.save_run(
        _make_run(
            "run-003",
            [
                _tc("testLogin", TestStatus.PASSED, idx=3),
                _tc("testSearch", TestStatus.PASSED, idx=3),
                _tc("testCreate", TestStatus.PASSED, idx=3),
                _tc("testCheckout", TestStatus.PASSED, idx=3),
            ],
            seq=3,
        )
    )
    repo.save_run(
        _make_run(
            "run-004",
            [
                _tc("testLogin", TestStatus.FAILED, idx=4, error_type="java.lang.AssertionError"),
                _tc("testSearch", TestStatus.FAILED, idx=4, error_type="java.lang.AssertionError"),
                _tc("testCreate", TestStatus.PASSED, idx=4),
                _tc("testCheckout", TestStatus.PASSED, idx=4),
            ],
            seq=4,
        )
    )
    conn.close()

    appl = create_app(db_path=str(db_path))
    c = TestClient(appl)
    res = c.post(
        "/api/ask",
        json={
            "question": "In the last 20 runs which run has the highest and lowest pass percentage?",
            "project": "ServerProject",
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert "Highest pass percentage: Run #3 at 100%" in data["answer"]
    assert "Lowest pass percentage: Run #2, Run #1 tied at 33.3%" in data["answer"]
    assert data["result"]["type"] == "run_pass_rate_extrema"
    assert data["result"]["highest"][0]["runSequence"] == 3
    assert data["result"]["lowest"][0]["runSequence"] == 2
    assert data["sources"]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_two(client: TestClient) -> None:
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.json()
    assert len(runs) == 2


def test_list_runs_allows_ui_catalogue_limit(client: TestClient) -> None:
    res = client.get("/api/runs?limit=500")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


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


def test_get_run_tests_invalid_status_rejected(client: TestClient) -> None:
    runs = client.get("/api/runs").json()
    run_id = runs[0]["run_id"]
    res = client.get(f"/api/runs/{run_id}/tests?status=failed' OR 1=1 --")
    assert res.status_code == 422


def test_compare_custom_rejects_invalid_status_filter(client: TestClient) -> None:
    res = client.post(
        "/api/compare/custom",
        json={
            "run_ids": ["run-001", "run-002"],
            "filters": {"status": "failed' OR 1=1 --"},
        },
    )
    assert res.status_code == 422


def test_compare_custom_rejects_invalid_category_filter(client: TestClient) -> None:
    res = client.post(
        "/api/compare/custom",
        json={
            "run_ids": ["run-001", "run-002"],
            "filters": {"category": "xss<script>"},
        },
    )
    assert res.status_code == 422


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
    from qalens.db.repository import RunRepository
    from qalens.db.schema import get_connection
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


def test_failure_groups_rejects_too_many_run_ids(client: TestClient) -> None:
    run_ids = ",".join(f"run-{i}" for i in range(51))
    res = client.get(f"/api/failure-groups?run_ids={run_ids}")
    assert res.status_code == 422


def test_risk_rejects_invalid_tier(client: TestClient) -> None:
    res = client.get("/api/risk?tier=HIGH' OR 1=1 --")
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Ask  (LLM — mocked)
# ---------------------------------------------------------------------------


def test_ask_empty_question(client: TestClient) -> None:
    res = client.post("/api/ask", json={"question": "   ", "project": "ServerProject"})
    assert res.status_code == 400


def test_ask_rejects_oversized_question(client: TestClient) -> None:
    res = client.post("/api/ask", json={"question": "x" * 4001, "project": "ServerProject"})
    assert res.status_code == 422


def test_ask_llm_error_returns_deterministic_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When LLMClient.chat raises LLMError the endpoint should fall back locally."""
    from qalens.llm.client import LLMError

    class _BrokenClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def chat(self, _prompt: str, **_kw: object) -> str:
            raise LLMError("connection refused")

    class _FakeCfg:
        pass

    monkeypatch.setattr("qalens.llm.config.load_config", lambda *_a, **_kw: _FakeCfg())
    monkeypatch.setattr("qalens.llm.client.LLMClient", _BrokenClient)

    res = client.post("/api/ask", json={"question": "What failed?", "project": "ServerProject"})
    assert res.status_code == 200
    assert "could not reach the configured LLM" in res.json()["answer"]


def test_ask_returns_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the LLM chain and verify the response shape."""

    class _MockClient:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def chat(self, _prompt: str, **_kw: object) -> str:
            return "testCreate is consistently broken."

    class _MockCfg:
        pass

    monkeypatch.setattr("qalens.llm.config.load_config", lambda *_a, **_kw: _MockCfg())
    monkeypatch.setattr("qalens.llm.client.LLMClient", _MockClient)

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
    assert data["answer"].startswith("testCreate is consistently broken.")


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

    monkeypatch.setattr("qalens.llm.config.load_config", lambda *_a, **_kw: _MockCfg())
    monkeypatch.setattr("qalens.llm.client.LLMClient", _MockClient)

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
    from qalens.server.models import AskResponse

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
