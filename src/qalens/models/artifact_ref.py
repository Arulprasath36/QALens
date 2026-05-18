"""ArtifactRef — parser-side raw reference to a test artifact.

Parsers emit ``ArtifactRef`` objects instead of making storage decisions.
The :class:`~qalens.artifacts.policy.ArtifactIngestionPolicy` consumes these
and decides whether to ignore, store metadata, or persist bytes — based on
the configured :class:`~qalens.artifacts.config.ArtifactMode`.

This module lives in ``qalens.models`` (not ``qalens.artifacts``) so that parser
modules can import it without creating a circular dependency on the artifacts
sub-package.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArtifactRef(BaseModel):
    """A raw artifact reference extracted by a parser.

    Parsers produce these objects; the artifact ingestion policy layer decides
    what to do with them (ignore / metadata-only / store full bytes).

    Attributes:
        source_uri: Raw reference — a ``data:image/...;base64,...`` URI or an
            absolute / relative file path pointing to the artifact on disk.
        kind: Artifact type hint (``"screenshot"``, ``"log"``, etc.).
        name: Optional human-readable label for the artifact.
        step_name: Name of the test step this artifact was attached to.
        sequence_no: Zero-based position index within the test case.
        is_from_failed_step: ``True`` when the artifact was produced by a step
            whose status is ``failed`` or ``broken``.  Used by the screenshot
            selector to prioritise failure-adjacent screenshots.
        mime_type: MIME type if determinable from context (e.g. the prefix of a
            data URI).  ``None`` when unknown.
    """

    source_uri: str = Field(
        ...,
        description="data: URI or file path pointing to the raw artifact.",
    )
    kind: str = Field(
        default="screenshot",
        description="Artifact type hint: 'screenshot', 'log', etc.",
    )
    name: str | None = Field(
        default=None,
        description="Human-readable label for the artifact.",
    )
    step_name: str | None = Field(
        default=None,
        description="Name of the step that produced this artifact.",
    )
    sequence_no: int = Field(
        default=0,
        ge=0,
        description="Zero-based index within the test case.",
    )
    is_from_failed_step: bool = Field(
        default=False,
        description="True when the owning step has a failing status.",
    )
    mime_type: str | None = Field(
        default=None,
        description="MIME type if known from context.",
    )

    model_config = {"frozen": True}
