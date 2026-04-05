"""One-off script: extract the ARI frontend f-string into static files.

Reads src/ari/server/ui.py, pulls out the giant f-string, converts
all {{ / }} escaping back to real JS braces, and writes three files:

  src/ari/server/static/index.html
  src/ari/server/static/app.css
  src/ari/server/static/app.js

Run once from the repo root:
  python scripts/extract_frontend.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
UI_PY     = REPO_ROOT / "src/ari/server/ui.py"
STATIC    = REPO_ROOT / "src/ari/server/static"


# ---------------------------------------------------------------------------
# Step 1 — read ui.py and extract the raw f-string body
# ---------------------------------------------------------------------------

def extract_fstring_body(src: str) -> str:
    """Return everything between `return f\"\"\"` and the closing `\"\"\"`."""
    # Find the opening of the f-string
    open_marker = 'return f"""'
    start = src.index(open_marker) + len(open_marker)
    # The closing triple-quote is the last occurrence of `"""` in the file
    close_marker = '"""'
    end = src.rindex(close_marker)
    return src[start:end]


# ---------------------------------------------------------------------------
# Step 2 — handle the one Python injection point
# ---------------------------------------------------------------------------

def patch_default_project(body: str) -> str:
    """Replace the single Python f-string injection with a static placeholder.

    Original (in the f-string):
        const DEFAULT_PROJECT = {default_proj_js};

    After this function the JS variable is removed from app.js entirely and
    instead set via a tiny inline <script> in index.html (see build_index_html).
    """
    # The line looks like:   const DEFAULT_PROJECT = {default_proj_js};
    # We remove it from the JS block so app.js is fully static.
    body = re.sub(
        r'const DEFAULT_PROJECT\s*=\s*\{default_proj_js\};',
        r'const DEFAULT_PROJECT = window._QARA_DEFAULT_PROJECT ?? "";',
        body,
    )
    return body


# ---------------------------------------------------------------------------
# Step 3 — unescape Python f-string braces  {{ → {  and  }} → }
# ---------------------------------------------------------------------------

def unescape_braces(text: str) -> str:
    return text.replace("{{", "{").replace("}}", "}")


# ---------------------------------------------------------------------------
# Step 4 — split into HTML / CSS / JS
# ---------------------------------------------------------------------------

def split_html_css_js(html: str) -> tuple[str, str, str]:
    """Split the document into (html_without_style_script, css, js)."""

    # ── Extract CSS from <style> ... </style> ──────────────────────────────
    style_pattern = re.compile(
        r'<style>(.*?)</style>', re.DOTALL | re.IGNORECASE
    )
    css_match = style_pattern.search(html)
    if not css_match:
        sys.exit("ERROR: could not find <style> block")
    css_raw = css_match.group(1)

    # ── Build the HTML shell — Step 1: replace <style> with external ref ────
    html_shell = style_pattern.sub(
        '<link rel="stylesheet" href="/static/app.css">',
        html,
        count=1,
    )

    # ── Extract JS and build HTML shell — Step 2 ───────────────────────────
    # JS template literals can contain literal "</script>" text which fools
    # non-greedy regex.  Locate via rfind on html_shell (after CSS swap) so
    # the indices remain correct: the last </script> is the end of the main
    # SPA block; walk backwards to find the matching bare <script> open tag.
    close_tag = "</script>"
    open_tag  = "<script>"
    html_lower = html_shell.lower()
    script_end = html_lower.rfind(close_tag)
    if script_end == -1:
        sys.exit("ERROR: could not find closing </script> tag")
    script_start = html_lower.rfind(open_tag, 0, script_end)
    if script_start == -1:
        sys.exit("ERROR: could not find opening <script> tag")

    js_raw = html_shell[script_start + len(open_tag) : script_end]

    # Replace the main inline <script> block with the injection shim +
    # the external app.js reference.
    inject_shim = (
        '<script>window._QARA_DEFAULT_PROJECT = __DEFAULT_PROJECT__;</script>\n'
        '    <script src="/static/app.js"></script>'
    )
    html_shell = (
        html_shell[:script_start]
        + inject_shim
        + html_shell[script_end + len(close_tag):]
    )

    return html_shell.strip(), css_raw.strip(), js_raw.strip()


# ---------------------------------------------------------------------------
# Step 5 — write output files
# ---------------------------------------------------------------------------

def write_files(html_shell: str, css: str, js: str) -> None:
    STATIC.mkdir(parents=True, exist_ok=True)

    # index.html — wrap in a proper doctype comment
    index_path = STATIC / "index.html"
    index_path.write_text(html_shell, encoding="utf-8")
    print(f"  wrote {index_path.relative_to(REPO_ROOT)}  ({len(html_shell):,} chars)")

    # app.css
    css_path = STATIC / "app.css"
    css_path.write_text(css, encoding="utf-8")
    print(f"  wrote {css_path.relative_to(REPO_ROOT)}  ({len(css):,} chars)")

    # app.js
    js_path = STATIC / "app.js"
    js_path.write_text(js, encoding="utf-8")
    print(f"  wrote {js_path.relative_to(REPO_ROOT)}  ({len(js):,} chars)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Reading {UI_PY.relative_to(REPO_ROOT)} ...")
    src = UI_PY.read_text(encoding="utf-8")

    print("Extracting f-string body ...")
    body = extract_fstring_body(src)

    print("Patching DEFAULT_PROJECT injection ...")
    body = patch_default_project(body)

    print("Unescaping {{ / }} braces ...")
    body = unescape_braces(body)

    print("Splitting HTML / CSS / JS ...")
    html_shell, css, js = split_html_css_js(body)

    print(f"Writing static files to {STATIC.relative_to(REPO_ROOT)}/ ...")
    write_files(html_shell, css, js)

    print("\nDone. Verify the output files before replacing ui.py.")
    print("Quick checks:")
    print(f"  HTML lines : {html_shell.count(chr(10)):,}")
    print(f"  CSS  lines : {css.count(chr(10)):,}")
    print(f"  JS   lines : {js.count(chr(10)):,}")


if __name__ == "__main__":
    main()
