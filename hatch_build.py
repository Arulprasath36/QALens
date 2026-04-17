"""Hatch build hook — compiles the React frontend before packaging.

Running ``hatch build`` (or ``make build``) will automatically invoke this hook,
which runs ``npm ci && npm run build`` inside the ``frontend/`` directory to
produce the pre-built static assets that ship inside the wheel.

Node/npm are *build-time* dependencies only.  End users do ``pip install
qara-insights`` and never need Node installed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Run the React frontend build before hatch packages the wheel."""

    def initialize(self, version: str, build_data: dict) -> None:  # type: ignore[override]
        frontend = Path(__file__).parent / "frontend"
        subprocess.run(["npm", "ci"], cwd=frontend, check=True)
        subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)
