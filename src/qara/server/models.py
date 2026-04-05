"""Pydantic request/response models and JSON serialisation helpers.

Extracted from :mod:`ari.server.app` so that route modules can import them
without creating circular dependencies.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Surrogate-sanitisation helpers
# ---------------------------------------------------------------------------

def _clean_str(s: str) -> str:
    """Drop lone Unicode surrogates that cannot be encoded as UTF-8.

    Uses encode/decode round-trip with ``errors='ignore'``, which is the
    most reliable approach across Python versions (avoids raw-string vs
    non-raw-string regex-escape ambiguity and handles any edge-case
    surrogate pairing that a character-class pattern might miss).
    """
    return s.encode("utf-8", errors="ignore").decode("utf-8")


def _clean_obj(obj: Any) -> Any:
    """Recursively strip lone surrogates from any str / dict / list structure."""
    if isinstance(obj, str):
        return _clean_str(obj)
    if isinstance(obj, dict):
        return {_clean_str(k) if isinstance(k, str) else k: _clean_obj(v)
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        cleaned = [_clean_obj(item) for item in obj]
        return type(obj)(cleaned)
    return obj


# ---------------------------------------------------------------------------
# Request / response models (must be at module level for Pydantic v2)
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """Request body for the /api/ask endpoint."""

    question: str
    project: str | None = None
    history: list[dict[str, str]] = []


class AskResponse(BaseModel):
    """Response body for the /api/ask endpoint."""

    answer: str
    context_mode: str
    sources: list[dict] = []
    intent: str = ""
    follow_ups: list[str] = []

    @field_validator("answer", mode="before")
    @classmethod
    def _sanitize_answer(cls, v: str) -> str:
        """Drop lone Unicode surrogates from the LLM answer string."""
        return _clean_str(v)

    @field_validator("sources", mode="before")
    @classmethod
    def _sanitize_sources(cls, v: list) -> list:
        """Drop lone Unicode surrogates from all strings in the sources list.

        Sources come directly from database content (test names, error
        messages, stack traces) which may contain emoji stored as surrogate
        pairs in SQLite.  Any surrogate code point in a nested field would
        cause ``UnicodeEncodeError`` during JSON serialisation.
        """
        return _clean_obj(v)


class CompareRequest(BaseModel):
    """Request body for POST /api/compare/custom."""

    run_ids: list[str]
    filters: dict[str, Any] = {}


class HomepageCard(BaseModel):
    """A single dynamic insight card on the chat home screen."""

    id: str
    icon: str
    title: str
    metric: str
    question: str
    available: bool = True


class HomepageCardsResponse(BaseModel):
    """Response body for GET /api/homepage-cards."""

    cards: list[HomepageCard]


# ---------------------------------------------------------------------------
# JSON serialisation helper
# ---------------------------------------------------------------------------


def _dc_to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses (and nested types) to JSON-safe dicts.

    Handles:
    - Nested dataclasses → dicts
    - ``enum.Enum`` members → their ``.name`` string
    - ``set`` / ``frozenset`` → sorted list
    - Computed ``@property`` attributes ``sparkline`` and ``flakiness_score``
      that are declared on dataclass types but not in ``fields()``
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, Any] = {}
        for f in dataclasses.fields(obj):
            result[f.name] = _dc_to_dict(getattr(obj, f.name))
        # Expose computed @property attributes used by the UI
        for attr in ("sparkline", "flakiness_score"):
            prop = getattr(type(obj), attr, None)
            if isinstance(prop, property):
                result[attr] = _dc_to_dict(getattr(obj, attr))
        return result
    if isinstance(obj, enum.Enum):
        return obj.name
    if isinstance(obj, (set, frozenset)):
        return sorted(_dc_to_dict(i) for i in obj)
    if isinstance(obj, list):
        return [_dc_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _dc_to_dict(v) for k, v in obj.items()}
    return obj
