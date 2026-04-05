"""Screenshot selection: apply priority ranking and per-failure cap.

Given an unbounded list of :class:`~ari.models.artifact_ref.ArtifactRef`
objects for a single test case, :func:`select_screenshots` returns the best
``max_count`` entries using this priority order:

1. Screenshots from a **failed step** (``is_from_failed_step=True``) —
   these are the most likely to capture the root cause.
2. Screenshots with the **highest sequence number** — nearer to the
   exception, so more context-relevant.
3. **First and last** screenshot as a last-resort fallback when the above
   rules leave the selection under-filled.

All other artifact kinds (logs, videos, etc.) are passed through unchanged up
to the cap.
"""

from __future__ import annotations

from qara.models.artifact_ref import ArtifactRef


def select_screenshots(
    refs: list[ArtifactRef],
    max_count: int = 2,
) -> list[ArtifactRef]:
    """Return the best ``max_count`` screenshot refs from *refs*.

    Non-screenshot refs are returned as-is after applying the count cap
    (screenshots are selected first, then any remaining budget is filled
    from other kinds in their original order).

    Args:
        refs: All artifact refs for a single test case.
        max_count: Maximum number of artifacts to retain.  ``0`` or negative
            returns an empty list.

    Returns:
        Ordered list of up to *max_count* :class:`~ari.models.artifact_ref.ArtifactRef`
        objects.  Screenshot priority order is applied; relative order within
        each priority tier is preserved.
    """
    if not refs or max_count <= 0:
        return []

    screenshots = [r for r in refs if r.kind == "screenshot"]
    others = [r for r in refs if r.kind != "screenshot"]

    selected_screenshots = _pick_screenshots(screenshots, max_count)

    # Fill remaining budget with non-screenshot artifacts
    remaining_budget = max_count - len(selected_screenshots)
    selected_others = others[:remaining_budget] if remaining_budget > 0 else []

    return selected_screenshots + selected_others


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pick_screenshots(
    screenshots: list[ArtifactRef],
    max_count: int,
) -> list[ArtifactRef]:
    """Select up to *max_count* screenshot refs using the priority rules."""
    if not screenshots:
        return []
    if len(screenshots) <= max_count:
        return list(screenshots)

    selected: list[ArtifactRef] = []

    # Priority 1: from failed steps, highest sequence first (nearest to failure)
    from_failed = sorted(
        [r for r in screenshots if r.is_from_failed_step],
        key=lambda r: r.sequence_no,
        reverse=True,
    )
    for ref in from_failed:
        if len(selected) >= max_count:
            break
        selected.append(ref)

    if len(selected) >= max_count:
        return selected

    # Priority 2: remaining screenshots, highest sequence first
    already = set(id(r) for r in selected)
    remaining = sorted(
        [r for r in screenshots if id(r) not in already],
        key=lambda r: r.sequence_no,
        reverse=True,
    )
    for ref in remaining:
        if len(selected) >= max_count:
            break
        selected.append(ref)

    # Fallback: should never reach here given the early-exit above, but guard anyway
    if not selected and screenshots:
        selected = [screenshots[0]]
        if len(screenshots) > 1 and len(selected) < max_count:
            selected.append(screenshots[-1])

    return selected[:max_count]
