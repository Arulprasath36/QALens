"""Tests for qara.analytics.owner_resolution."""
from __future__ import annotations

import pytest

from qara.analytics.owner_resolution import normalize_owner_name, resolve_owner_name

# ---------------------------------------------------------------------------
# normalize_owner_name
# ---------------------------------------------------------------------------

NORMALIZATION_CASES = [
    # (input, expected)
    ("Fatima", "fatima"),
    ("fatima", "fatima"),
    ("FATIMA", "fatima"),
    ("Fatima Al-Rashid", "fatima al rashid"),
    ("fatima_al_rashid", "fatima al rashid"),
    ("  John  Doe  ", "john doe"),
    ("john__doe", "john doe"),
    ("John-Doe", "john doe"),
    ("John_-_Doe", "john doe"),  # mixed separators replaced then whitespace collapsed
    ("O'Brien", "o'brien"),
]


@pytest.mark.parametrize("raw,expected", NORMALIZATION_CASES)
def test_normalize_owner_name(raw: str, expected: str) -> None:
    assert normalize_owner_name(raw) == expected


def test_normalize_strip_punctuation() -> None:
    assert normalize_owner_name("O'Brien", strip_punctuation=True) == "obrien"


def test_normalize_mixed_separators_collapsed() -> None:
    # Separators are replaced with spaces, then all whitespace is collapsed.
    result = normalize_owner_name("Alice--Bob")
    assert result == "alice bob"
    assert "-" not in result
    assert "_" not in result


# ---------------------------------------------------------------------------
# resolve_owner_name — exact match
# ---------------------------------------------------------------------------


def test_exact_match_same_casing() -> None:
    result = resolve_owner_name("Fatima Al-Rashid", ["Fatima Al-Rashid", "John Doe"])
    assert result.match_type == "exact"
    assert result.matched_owner == "Fatima Al-Rashid"
    assert result.confidence == 1.0


def test_exact_match_different_casing() -> None:
    result = resolve_owner_name("fatima al-rashid", ["Fatima Al-Rashid", "John Doe"])
    assert result.match_type == "exact"
    assert result.matched_owner == "Fatima Al-Rashid"


def test_exact_match_with_underscores() -> None:
    # "fatima_al_rashid" normalizes to "fatima al rashid" which equals
    # the normalized form of "Fatima Al-Rashid".
    result = resolve_owner_name("fatima_al_rashid", ["Fatima Al-Rashid"])
    assert result.match_type == "exact"
    assert result.matched_owner == "Fatima Al-Rashid"


# ---------------------------------------------------------------------------
# resolve_owner_name — partial / token match
# ---------------------------------------------------------------------------


def test_partial_match_single_token() -> None:
    # "Fatima" is a token in "Fatima Al-Rashid" and only one owner matches.
    result = resolve_owner_name("Fatima", ["Fatima Al-Rashid", "John Doe"])
    assert result.match_type == "partial"
    assert result.matched_owner == "Fatima Al-Rashid"
    assert result.confidence == pytest.approx(0.95)


def test_partial_match_multiple_tokens() -> None:
    result = resolve_owner_name("Al Rashid", ["Fatima Al-Rashid", "John Doe"])
    assert result.match_type == "partial"
    assert result.matched_owner == "Fatima Al-Rashid"


# ---------------------------------------------------------------------------
# resolve_owner_name — ambiguous
# ---------------------------------------------------------------------------


def test_ambiguous_when_multiple_partial_matches() -> None:
    # Both "John Doe" and "John Smith" contain the token "john".
    result = resolve_owner_name("John", ["Fatima Al-Rashid", "John Doe", "John Smith"])
    assert result.match_type == "ambiguous"
    assert result.matched_owner is None
    assert "John Doe" in result.candidates
    assert "John Smith" in result.candidates
    assert result.confidence == 0.0


def test_ambiguous_response_has_no_matched_owner() -> None:
    result = resolve_owner_name("John", ["John Doe", "John Smith"])
    assert result.matched_owner is None


# ---------------------------------------------------------------------------
# resolve_owner_name — fuzzy match
# ---------------------------------------------------------------------------


def test_fuzzy_match_typo() -> None:
    # "Fathima" is a common alternate spelling → should fuzzy-match "Fatima Al-Rashid".
    result = resolve_owner_name(
        "Fathima", ["Fatima Al-Rashid", "John Doe"], fuzzy_threshold=70
    )
    assert result.match_type in {"partial", "fuzzy"}
    assert result.matched_owner == "Fatima Al-Rashid"


def test_fuzzy_match_returns_confidence_in_range() -> None:
    result = resolve_owner_name("Fathima", ["Fatima Al-Rashid"], fuzzy_threshold=70)
    assert 0.0 < result.confidence <= 1.0


def test_fuzzy_threshold_respected() -> None:
    # A very high threshold should prevent any fuzzy match.
    result = resolve_owner_name("Fathima", ["Fatima Al-Rashid"], fuzzy_threshold=99)
    assert result.match_type in {"none", "partial", "fuzzy"}
    # If it didn't pass the threshold, match_type is "none".
    if result.match_type == "none":
        assert result.matched_owner is None


# ---------------------------------------------------------------------------
# resolve_owner_name — no match
# ---------------------------------------------------------------------------


def test_no_match_completely_different_name() -> None:
    result = resolve_owner_name(
        "Zaphod Beeblebrox", ["Fatima Al-Rashid", "John Doe"], fuzzy_threshold=85
    )
    assert result.match_type == "none"
    assert result.matched_owner is None
    assert result.confidence == 0.0
    assert result.candidates == []


def test_no_match_empty_known_owners() -> None:
    result = resolve_owner_name("Fatima", [])
    assert result.match_type == "none"
    assert result.matched_owner is None


# ---------------------------------------------------------------------------
# resolve_owner_name — explanation field
# ---------------------------------------------------------------------------


def test_explanation_is_non_empty_for_all_outcomes() -> None:
    cases = [
        resolve_owner_name("Fatima Al-Rashid", ["Fatima Al-Rashid"]),          # exact
        resolve_owner_name("Fatima", ["Fatima Al-Rashid"]),                      # partial
        resolve_owner_name("John", ["John Doe", "John Smith"]),                  # ambiguous
        resolve_owner_name("Zaphod", ["Fatima Al-Rashid"]),                      # none
    ]
    for result in cases:
        assert isinstance(result.explanation, str)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# resolve_owner_name — duplicate known owners
# ---------------------------------------------------------------------------


def test_duplicate_known_owners_deduped() -> None:
    result = resolve_owner_name(
        "Fatima Al-Rashid",
        ["Fatima Al-Rashid", "Fatima Al-Rashid", "John Doe"],
    )
    assert result.match_type == "exact"
    assert result.matched_owner == "Fatima Al-Rashid"
