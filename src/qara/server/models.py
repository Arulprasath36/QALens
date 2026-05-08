"""Pydantic request/response models and JSON serialisation helpers.

Extracted from :mod:`qara.server.app` so that route modules can import them
without creating circular dependencies.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from qara.security import (
    ALLOWED_FAILURE_CATEGORIES,
    ALLOWED_TEST_STATUSES,
    MAX_ASK_HISTORY_ITEMS,
    MAX_ASK_QUESTION_CHARS,
    MAX_COMPARE_ENTITY_CHARS,
    MAX_COMPARE_PROJECT_CHARS,
    MAX_COMPARE_RUN_IDS,
    MAX_COMPARE_SEARCH_CHARS,
)


MAX_HISTORY_MESSAGE_CHARS = 8_000

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

    question: str = Field(..., min_length=1, max_length=MAX_ASK_QUESTION_CHARS)
    project: str | None = Field(default=None, max_length=200)
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=MAX_ASK_HISTORY_ITEMS,
    )

    @field_validator("history")
    @classmethod
    def _validate_history(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        allowed_roles = {"user", "assistant"}
        for item in v:
            role = item.get("role")
            content = item.get("content")
            if role not in allowed_roles:
                raise ValueError("History role must be 'user' or 'assistant'.")
            if not isinstance(content, str) or len(content) > MAX_HISTORY_MESSAGE_CHARS:
                raise ValueError("History content must be a bounded string.")
        return v


class AskResponse(BaseModel):
    """Response body for the /api/ask endpoint."""

    answer: str
    context_mode: str
    sources: list[dict] = []
    intent: str = ""
    follow_ups: list[str] = []
    result: dict[str, Any] | None = None
    uiHints: dict[str, Any] | None = None

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

    @field_validator("result", "uiHints", mode="before")
    @classmethod
    def _sanitize_optional_objects(cls, v: Any) -> Any:
        """Drop lone Unicode surrogates from structured payloads."""
        return _clean_obj(v)


class CompareRequest(BaseModel):
    """Request body for POST /api/compare/custom."""

    run_ids: list[str] = Field(..., min_length=1, max_length=MAX_COMPARE_RUN_IDS)
    filters: dict[str, Any] = Field(default_factory=dict, max_length=12)

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, v: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "suite",
            "owner",
            "feature",
            "search",
            "status",
            "category",
            "flaky_only",
            "broken_only",
            "changed_only",
            "latest_failed_only",
        }
        unknown = set(v) - allowed_keys
        if unknown:
            raise ValueError(f"Unsupported filter keys: {', '.join(sorted(unknown))}.")

        for key in ("suite", "owner", "feature", "search"):
            value = v.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 500):
                raise ValueError(f"Filter {key!r} must be a bounded string.")

        status = v.get("status")
        if status is not None and str(status).lower() not in ALLOWED_TEST_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_TEST_STATUSES))
            raise ValueError(f"Invalid status filter. Allowed: {allowed}.")

        category = v.get("category")
        if category is not None and str(category).lower() not in ALLOWED_FAILURE_CATEGORIES:
            allowed = ", ".join(sorted(ALLOWED_FAILURE_CATEGORIES))
            raise ValueError(f"Invalid category filter. Allowed: {allowed}.")

        for key in ("flaky_only", "broken_only", "changed_only", "latest_failed_only"):
            value = v.get(key)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"Filter {key!r} must be boolean.")
        return v


class EntityCompareRequest(BaseModel):
    """Request body for owner/suite entity comparison endpoints."""

    owner_a: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COMPARE_ENTITY_CHARS,
    )
    owner_b: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COMPARE_ENTITY_CHARS,
    )
    owner_c: str | None = Field(default=None, max_length=MAX_COMPARE_ENTITY_CHARS)
    suite_a: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COMPARE_ENTITY_CHARS,
    )
    suite_b: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COMPARE_ENTITY_CHARS,
    )
    suite_c: str | None = Field(default=None, max_length=MAX_COMPARE_ENTITY_CHARS)
    limit: int = Field(default=10, ge=1, le=50)
    run_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COMPARE_RUN_IDS,
    )
    project: str | None = Field(default=None, max_length=MAX_COMPARE_PROJECT_CHARS)


class BreakdownRequestParams(BaseModel):
    """Validated filters used by comparison breakdown-style APIs."""

    group_by: Literal["owner", "suite"] = "owner"
    search: str | None = Field(default=None, max_length=MAX_COMPARE_SEARCH_CHARS)


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
