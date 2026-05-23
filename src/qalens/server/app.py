"""QA Lens FastAPI web-server application.

Factory function ``create_app`` returns a configured :class:`fastapi.FastAPI`
instance.  Run it with *uvicorn*::

    uvicorn qalens.server.app:app --reload

Or via the QA Lens CLI::

    qalens serve --port 8080
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from qalens.server.auth import (
    AUTH_MODE_ENV,
    AUTH_TOKEN_ENV,
    github_callback_response,
    github_config_ready,
    github_start_response,
    is_admin_user,
    login_page,
    logout_response,
    request_is_authenticated,
    request_user,
    resolve_auth_config,
)
from qalens.server.models import (  # noqa: F401
    AskRequest,
    AskResponse,
    CompareRequest,
    _dc_to_dict,
)
from qalens.server.ui import _build_index_html
from qalens.version import __version__

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# Matches ANSI escape sequences (CSI codes, OSC, etc.) and bare control
# characters (except tab/newline which are legitimate in some log contexts).
# Stripping these prevents terminal log injection via crafted request paths.
_ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)


def _sl(value: str) -> str:
    """Sanitize a user-controlled string before writing it to a log line."""
    return _ANSI_RE.sub("?", value)

# ---------------------------------------------------------------------------
# Module-level logger — all QA Lens server messages go through this
# ---------------------------------------------------------------------------
logger = logging.getLogger("qalens.server")
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    db_path: str | Path | None = None,
    config_path: str | Path | None = None,
    default_project: str | None = None,
    auth_token: str | None = None,
) -> FastAPI:
    """Create and return the QA Lens FastAPI application.

    Args:
        db_path: Path to the QA Lens SQLite database.  Defaults to
            ``~/.qalens/qalens.db``.
        config_path: Path to the LLM ``config.toml``.  Defaults to
            ``~/.qalens/config.toml``.
        default_project: Pre-selected project name shown in the UI on load.
        auth_token: Optional admin bearer token. When omitted, QA Lens reads
            ``QALENS_AUTH_TOKEN``. If no token is configured, auth is disabled.

    Returns:
        A configured :class:`fastapi.FastAPI` instance ready to be served
        with *uvicorn*.

    """
    app = FastAPI(
        title="QA Lens — Quality Assurance + Lens",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )

    _db = db_path
    _cfg = config_path
    _auth_config = resolve_auth_config(auth_token)

    # ------------------------------------------------------------------
    # CSRF protection middleware
    # Mutating requests (POST/PUT/PATCH/DELETE) that carry an Origin header
    # must originate from the same host as the server.  Requests without an
    # Origin header (curl, CLI tools, Postman) are allowed through so that
    # the API remains usable outside the browser.
    # ------------------------------------------------------------------
    _MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
    _AUTH_PUBLIC_PATHS = frozenset({
        "/",
        "/api/health",
        "/api/auth/status",
        "/login",
        "/auth/github/start",
        "/auth/github/callback",
        "/auth/logout",
        "/favicon.ico",
        "/qalens-logo.svg",
        "/qalens-logo-dark.svg",
    })

    def _auth_required_for(request: Request) -> bool:
        if _auth_config.mode == "none":
            return False
        path = request.url.path
        if _auth_config.mode == "github" and path == "/":
            return True
        if path in _AUTH_PUBLIC_PATHS:
            return False
        if path.startswith("/static/"):
            return False
        return path.startswith("/api/")

    @app.middleware("http")
    async def _admin_token_check(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _auth_required_for(request) and not request_is_authenticated(request, _auth_config):
            if _auth_config.mode == "github" and request.url.path == "/":
                return RedirectResponse("/login", status_code=303)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    @app.middleware("http")
    async def _csrf_check(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in _MUTATING:
            origin = request.headers.get("origin")
            if origin is not None:
                host = request.headers.get("host", "")
                expected = f"{request.url.scheme}://{host}"
                if origin != expected:
                    logger.warning(
                        "CSRF check failed: Origin=%r expected=%r path=%s",
                        _sl(origin), _sl(expected), _sl(request.url.path),
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin request blocked."},
                    )
        return await call_next(request)

    # ------------------------------------------------------------------
    # Content-Security-Policy middleware
    # 'unsafe-inline' is required for script-src and style-src because the
    # frontend uses inline onclick handlers and inline style attributes
    # throughout its template strings.  The high-value directives here are
    # object-src 'none' (blocks plugins), base-uri 'self' (blocks <base>
    # injection), frame-ancestors 'none' (blocks clickjacking), and
    # connect-src 'self' (prevents JS from exfiltrating data to outside hosts).
    # ------------------------------------------------------------------
    _CSP = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://avatars.githubusercontent.com; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none';"
    )

    @app.middleware("http")
    async def _add_csp(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    # ------------------------------------------------------------------
    # Request / response logging middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def _log_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        logger.info("→ %s %s", _sl(request.method), _sl(request.url.path))
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("✗ %s %s raised %s", request.method, request.url.path, exc)
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "← %s %s  status=%s  %.1fms",
            _sl(request.method), _sl(request.url.path), response.status_code, elapsed_ms,
        )
        return response

    logger.info(
        "QA Lens server initialised  db=%s  config=%s  auth=%s",
        _db or "~/.qalens/qalens.db",
        _cfg or "~/.qalens/config.toml",
        _auth_config.mode
        if _auth_config.mode != "none"
        else f"disabled (set {AUTH_MODE_ENV}=github or {AUTH_TOKEN_ENV} to enable)",
    )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        """Serve the QA Lens single-page application."""
        return _build_index_html(default_project=default_project)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login(request: Request) -> HTMLResponse:
        """Serve the GitHub sign-in page."""
        if _auth_config.mode != "github":
            return HTMLResponse(
                "<!doctype html><title>QA Lens</title><p>Authentication is not enabled.</p>"
            )
        if request_is_authenticated(request, _auth_config):
            return HTMLResponse(
                '<!doctype html><title>QA Lens</title><meta http-equiv="refresh" content="0; url=/">'
            )
        return login_page(_auth_config, error=request.query_params.get("error"))

    @app.get("/auth/github/start", include_in_schema=False)
    async def github_start(request: Request) -> Response:
        """Redirect the browser to GitHub OAuth."""
        return github_start_response(request, _auth_config)

    @app.get("/auth/github/callback", include_in_schema=False, name="github_callback")
    async def github_callback(request: Request) -> Response:
        """Handle GitHub OAuth callback."""
        return await github_callback_response(request, _auth_config)

    @app.post("/auth/logout", include_in_schema=False)
    async def logout() -> Response:
        """Clear the current QA Lens session."""
        return logout_response()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe — always returns ``{"status": "ok"}``."""
        return {"status": "ok", "version": __version__}

    @app.get("/api/auth/status", tags=["meta"])
    async def auth_status(request: Request) -> dict[str, object]:
        """Return whether API authentication is required for this server."""
        return {
            "mode": _auth_config.mode,
            "required": _auth_config.mode != "none",
            "authenticated": request_is_authenticated(request, _auth_config),
            "github_configured": github_config_ready(_auth_config),
            "is_admin": is_admin_user(request, _auth_config),
        }

    @app.get("/api/auth/me", tags=["meta"])
    async def auth_me(request: Request) -> dict[str, object]:
        """Return current auth session details."""
        user = request_user(request, _auth_config)
        return {
            "mode": _auth_config.mode,
            "authenticated": request_is_authenticated(request, _auth_config),
            "user": None if user is None else {
                "login": user.login,
                "name": user.name,
                "avatar_url": user.avatar_url,
                "html_url": user.html_url,
            },
        }

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    @app.get("/api/projects", tags=["data"], response_model=list[str])
    async def list_projects() -> list[str]:
        """Return a sorted list of distinct project names stored in the DB."""
        from qalens.db.schema import get_connection, init_db

        logger.info("list_projects: connecting to db=%s", _db or "~/.qalens/qalens.db")
        conn = get_connection(_db)
        try:
            init_db(conn)  # ensure schema exists even on a fresh DB
            rows = conn.execute(
                "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL ORDER BY project"
            ).fetchall()
            projects = [r[0] for r in rows]
            logger.info("list_projects: returning %d project(s): %s", len(projects), projects)
            return projects
        except Exception as exc:
            logger.exception("list_projects: DB error: %s", exc)
            raise
        finally:
            conn.close()


    # ------------------------------------------------------------------
    # Route groups (extracted to dedicated router modules)
    # ------------------------------------------------------------------
    from qalens.server.routes_analysis import make_analysis_router
    from qalens.server.routes_compare import make_compare_router
    from qalens.server.routes_decision import make_decision_router
    from qalens.server.routes_evidence import make_evidence_router
    from qalens.server.routes_export import make_export_router
    from qalens.server.routes_homepage import make_homepage_router
    from qalens.server.routes_llm import make_llm_router
    from qalens.server.routes_report import make_report_router
    from qalens.server.routes_runs import make_runs_router
    from qalens.server.routes_settings import make_settings_router

    app.include_router(make_runs_router(_db))
    app.include_router(make_analysis_router(_db))
    app.include_router(make_decision_router(_db))
    app.include_router(make_compare_router(_db))
    app.include_router(make_evidence_router(_db))
    app.include_router(make_export_router())
    app.include_router(make_llm_router(_db, _cfg))
    app.include_router(make_homepage_router(_db))
    app.include_router(make_report_router(_db))
    app.include_router(make_settings_router(_db, _cfg, _auth_config))

    _static_dir = Path(__file__).parent / "static"
    if not (_static_dir / "index.html").exists():
        import warnings
        warnings.warn(
            "QA Lens frontend assets not found at "
            f"{_static_dir}. Run `hatch build` or `make build-ui` to compile the UI.",
            stacklevel=2,
        )
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    return app


# ---------------------------------------------------------------------------
# Fallback module-level app instance (for `uvicorn qalens.server.app:app`)
# ---------------------------------------------------------------------------

app = create_app()
