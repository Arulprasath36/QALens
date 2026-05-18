"""Serve the QA Lens single-page application from static files.

The full HTML/CSS/JS lives in src/qalens/server/static/.  At request time only
one substitution is made: the __DEFAULT_PROJECT__ placeholder in index.html is
replaced with the JSON-encoded default project name so the JS SPA can
pre-select it on load.

If the static directory has not been built yet (i.e. ``npm run build`` has not
been run), a helpful fallback page is returned instead of crashing.
"""

from __future__ import annotations

import json
from pathlib import Path

_STATIC = Path(__file__).parent / "static"

_FALLBACK_HTML = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>QA Lens \u2014 UI not built</title>
    <style>
      body { font-family: system-ui, sans-serif; background: #09090b; color: #e4e4e7;
             display: flex; align-items: center; justify-content: center;
             min-height: 100vh; margin: 0; }
      .card { background: #18181b; border: 1px solid #3f3f46; border-radius: 12px;
              padding: 2rem 2.5rem; max-width: 480px; text-align: center; }
      h1 { color: #f4f4f5; margin: 0 0 0.5rem; font-size: 1.4rem; }
      p  { color: #a1a1aa; margin: 0 0 1.25rem; line-height: 1.6; }
      code { background: #27272a; border: 1px solid #52525b; border-radius: 6px;
             padding: 0.6rem 1rem; display: block; font-size: 0.875rem;
             color: #a5f3fc; text-align: left; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>QA Lens UI not built</h1>
      <p>The React frontend has not been compiled yet.<br>
         Run the following command from the project root:</p>
      <code>make build-ui</code>
    </div>
  </body>
</html>
"""


def _build_index_html(*, default_project: str | None = None) -> str:
    """Return the QA Lens web UI HTML with DEFAULT_PROJECT injected.

    Falls back to a helpful error page when the static build is absent.
    """
    index = _STATIC / "index.html"
    if not index.exists():
        return _FALLBACK_HTML
    html = index.read_text(encoding="utf-8")
    default_proj_js = json.dumps(default_project or "")
    return html.replace("__DEFAULT_PROJECT__", default_proj_js)
