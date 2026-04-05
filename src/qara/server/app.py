"""QARA FastAPI web-server application.

Factory function ``create_app`` returns a configured :class:`fastapi.FastAPI`
instance.  Run it with *uvicorn*::

    uvicorn ari.server.app:app --reload

Or via the QARA CLI::

    ari serve --port 8080
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

# Matches ANSI escape sequences (CSI codes, OSC, etc.) and bare control
# characters (except tab/newline which are legitimate in some log contexts).
# Stripping these prevents terminal log injection via crafted request paths.
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sl(value: str) -> str:
    """Sanitize a user-controlled string before writing it to a log line."""
    return _ANSI_RE.sub("?", value)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from qara.version import __version__
from qara.server.models import (  # noqa: F401
    AskRequest,
    AskResponse,
    CompareRequest,
    _dc_to_dict,
)

# ---------------------------------------------------------------------------
# Module-level logger — all QARA server messages go through this
# ---------------------------------------------------------------------------
logger = logging.getLogger("qara.server")
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
) -> FastAPI:
    """Create and return the QARA FastAPI application.

    Args:
        db_path: Path to the QARA SQLite database.  Defaults to
            ``~/.qara/ari.db``.
        config_path: Path to the LLM ``config.toml``.  Defaults to
            ``~/.qara/config.toml``.
        default_project: Pre-selected project name shown in the UI on load.

    Returns:
        A configured :class:`fastapi.FastAPI` instance ready to be served
        with *uvicorn*.
    """
    app = FastAPI(
        title="QARA — Automated Root-cause Insights",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    _db = db_path
    _cfg = config_path

    # ------------------------------------------------------------------
    # CSRF protection middleware
    # Mutating requests (POST/PUT/PATCH/DELETE) that carry an Origin header
    # must originate from the same host as the server.  Requests without an
    # Origin header (curl, CLI tools, Postman) are allowed through so that
    # the API remains usable outside the browser.
    # ------------------------------------------------------------------
    _MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    @app.middleware("http")
    async def _csrf_check(request: Request, call_next):
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
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none';"
    )

    @app.middleware("http")
    async def _add_csp(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        return response

    # ------------------------------------------------------------------
    # Request / response logging middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
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

    logger.info("ARI server initialised  db=%s  config=%s", _db or "~/.qara/ari.db", _cfg or "~/.qara/config.toml")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        """Serve the QARA single-page application."""
        return _build_index_html(default_project=default_project)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe — always returns ``{"status": "ok"}``."""
        return {"status": "ok", "version": __version__}

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    @app.get("/api/projects", tags=["data"], response_model=list[str])
    async def list_projects() -> list[str]:
        """Return a sorted list of distinct project names stored in the DB."""
        from qara.db.schema import get_connection, init_db

        logger.info("list_projects: connecting to db=%s", _db or "~/.qara/ari.db")
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
    from qara.server.routes_runs import make_runs_router
    from qara.server.routes_analysis import make_analysis_router
    from qara.server.routes_compare import make_compare_router
    from qara.server.routes_evidence import make_evidence_router
    from qara.server.routes_llm import make_llm_router
    from qara.server.routes_homepage import make_homepage_router

    app.include_router(make_runs_router(_db))
    app.include_router(make_analysis_router(_db))
    app.include_router(make_compare_router(_db))
    app.include_router(make_evidence_router(_db))
    app.include_router(make_llm_router(_db, _cfg))
    app.include_router(make_homepage_router(_db))

    _static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    return app


# ---------------------------------------------------------------------------
# Fallback module-level app instance (for `uvicorn ari.server.app:app`)
# ---------------------------------------------------------------------------

app = create_app()



from qara.server.ui import _build_index_html  # noqa: F401  # re-exported for callers
