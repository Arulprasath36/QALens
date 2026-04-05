"""Serve the QARA single-page application from static files.

The full HTML/CSS/JS lives in src/ari/server/static/.  At request time only
one substitution is made: the __DEFAULT_PROJECT__ placeholder in index.html is
replaced with the JSON-encoded default project name so the JS SPA can
pre-select it on load.
"""

from __future__ import annotations

import json
from pathlib import Path

_STATIC = Path(__file__).parent / "static"


def _build_index_html(*, default_project: str | None = None) -> str:
    """Return the QARA web UI HTML with DEFAULT_PROJECT injected."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    default_proj_js = json.dumps(default_project or "")
    return html.replace("__DEFAULT_PROJECT__", default_proj_js)
