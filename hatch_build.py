"""Hatch build hook — compiles the React frontend before packaging.

Running ``hatch build`` (or ``make build``) will automatically invoke this hook,
which runs ``npm ci && npm run build`` inside the ``frontend/`` directory to
produce the pre-built static assets that ship inside the wheel.

Node/npm are *build-time* dependencies only.  End users do ``pip install
qara-insights`` and never need Node installed.

Set ``QARA_SKIP_FRONTEND_BUILD=1`` to skip the npm step when you have already
run ``make build-ui`` manually and don't want a redundant rebuild.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Run the React frontend build before hatch packages the wheel."""

    def initialize(self, version: str, build_data: dict) -> None:  # type: ignore[override]
        frontend = Path(__file__).parent / "frontend"
        static_out = Path(__file__).parent / "src" / "qara" / "server" / "static"

        # Opt-out: maintainers who pre-built via `make build-ui` can skip.
        # Default is always rebuild to avoid stale hashed assets in the wheel.
        if os.getenv("QARA_SKIP_FRONTEND_BUILD") == "1" and (static_out / "index.html").exists():
            print("QARA build hook: QARA_SKIP_FRONTEND_BUILD=1 — skipping npm build.")
            return

        if shutil.which("npm") is None:
            raise RuntimeError(
                "npm not found. Install Node.js ≥18 to build the frontend "
                "(https://nodejs.org), or set QARA_SKIP_FRONTEND_BUILD=1 "
                "after running `make build-ui` manually."
            )

        # Clean first — prevents stale hashed JS/CSS files from a previous
        # build accidentally shipping in the wheel.
        if static_out.exists():
            print(f"QARA build hook: cleaning previous build at {static_out}")
            shutil.rmtree(static_out)

        print("QARA build hook: running npm ci...")
        subprocess.run(["npm", "ci"], cwd=frontend, check=True)

        print("QARA build hook: running npm run build...")
        subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)

        # Validate — catches a silent Vite misconfiguration (wrong outDir etc.)
        if not (static_out / "index.html").exists():
            raise RuntimeError(
                "Frontend build completed but static/index.html was not created. "
                "Check vite.config.ts outDir and base settings."
            )

        # Restore .gitkeep so the directory stays tracked in VCS.
        (static_out / ".gitkeep").touch()

        print(f"QARA build hook: frontend built successfully → {static_out}")
