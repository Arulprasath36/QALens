"""Pydantic schemas for the owner-aware analytics layer.

These data contracts are the interface between the deterministic analytics
engine and the rest of QARA (e.g. the LLM wording layer).  All fields are
typed and validated so downstream code never has to guess the shape of a
resolution or metric result.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class OwnerResolutionResult(BaseModel):
    """Result of resolving a raw owner query string to a known canonical owner name.

    The ``match_type`` field encodes *how* the resolution was made, which is
    important for the LLM wording layer (e.g. "interpreted X as Y").

    Match-type semantics
    --------------------
    - ``exact``     – normalized strings are identical.
    - ``partial``   – every token in the query appears in the owner name.
    - ``fuzzy``     – rapidfuzz WRatio similarity exceeds the threshold.
    - ``ambiguous`` – multiple candidates are equally plausible; the caller
                      must ask the user to disambiguate.
    - ``none``      – no candidate met the threshold.
    """

    query: str = Field(description="The raw owner string supplied by the user.")
    matched_owner: Optional[str] = Field(
        default=None,
        description="The resolved canonical owner name, or None when unresolved.",
    )
    match_type: Literal["exact", "partial", "fuzzy", "ambiguous", "none"] = Field(
        description="How the match was made — see class docstring.",
    )
    candidates: list[str] = Field(
        default_factory=list,
        description=(
            "All plausible canonical names considered. "
            "Non-empty when match_type is 'ambiguous'."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in [0, 1].  "
            "1.0 for exact; scaled from fuzzy score for fuzzy/partial; "
            "0.0 when no match found."
        ),
    )
    explanation: str = Field(
        description="Human-readable sentence explaining how the resolution was made.",
    )
