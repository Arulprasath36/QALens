"""Owner name normalization and fuzzy resolution.

Design principles
-----------------
- All matching is **deterministic and reproducible**: same inputs always
  produce the same output regardless of call order.
- Resolution is ordered: **exact → partial/token → fuzzy → ambiguous/none**.
  Each step is only attempted if the previous step produced no unique winner.
- The caller receives a structured :class:`~qara.analytics.schemas.OwnerResolutionResult`,
  not a bare string, so downstream code can inspect confidence, warn on
  ambiguity, or handle ``none`` cleanly without exception handling.

Normalization contract
----------------------
``normalize_owner_name`` guarantees:
1. Leading/trailing whitespace stripped.
2. Hyphens and underscores replaced with spaces.
3. Runs of whitespace collapsed to a single space.
4. Lowercased.
5. Optionally: all punctuation removed (for fuzzy pre-processing).

This means ``"Fatima"``, ``"fatima"``, ``"FATIMA"`` all normalize to
``"fatima"`` and will exact-match each other.

Fuzzy matching
--------------
``rapidfuzz.fuzz.WRatio`` is used because it automatically selects the best
strategy (full ratio, partial ratio, token sort, token set) per pair. The
default threshold of 85 / 100 rejects weak associations while allowing
reasonable typos and abbreviations.
"""
from __future__ import annotations

import re
import string

from rapidfuzz import fuzz, process

from qara.analytics.schemas import OwnerResolutionResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default minimum rapidfuzz WRatio score (0–100) to accept a fuzzy match.
DEFAULT_FUZZY_THRESHOLD: int = 85

#: Score gap below the top fuzzy score within which a candidate is still
#: considered a "co-equal" match.  If two fuzzy candidates are within this
#: gap of each other, the result is ambiguous rather than a clear winner.
_FUZZY_TIE_GAP: int = 5

_WHITESPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"[-_]+")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_owner_name(name: str, *, strip_punctuation: bool = False) -> str:
    """Return a canonical lowercase form of an owner name.

    Transformations applied in order:

    1. Strip leading/trailing whitespace.
    2. Replace hyphens and underscores with spaces.
    3. Collapse runs of whitespace to a single space.
    4. Lowercase everything.
    5. Optionally strip all remaining punctuation.

    Args:
        name: The raw owner name string.
        strip_punctuation: When ``True``, remove all remaining punctuation
            characters after the other transforms.  Useful as a pre-processing
            step for fuzzy matching.

    Returns:
        The normalized name string.

    Examples::

        >>> normalize_owner_name("Fatima Al-Rashid")
        'fatima al rashid'
        >>> normalize_owner_name("  John__Doe  ")
        'john doe'
        >>> normalize_owner_name("O'Brien", strip_punctuation=True)
        'obrien'
    """
    result = name.strip()
    result = _SEPARATOR_RE.sub(" ", result)
    result = _WHITESPACE_RE.sub(" ", result)
    result = result.lower()
    if strip_punctuation:
        result = result.translate(str.maketrans("", "", string.punctuation))
    return result


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_owner_name(
    query_owner: str,
    known_owners: list[str],
    *,
    fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD,
) -> OwnerResolutionResult:
    """Resolve a raw owner query string to a known canonical owner name.

    Resolution order
    ----------------
    1. **Exact** – normalized query equals normalized known owner.
    2. **Partial / token** – every token in the normalized query appears as
       a token in the normalized known-owner name.  E.g. ``"Fatima"`` matches
       ``"Fatima Al-Rashid"`` if she is the only Fatima.
    3. **Fuzzy** – ``rapidfuzz.fuzz.WRatio`` score ≥ *fuzzy_threshold*.
       If one candidate is clearly dominant (gap > :data:`_FUZZY_TIE_GAP`
       from the next best), it is returned as a fuzzy match.
    4. **Ambiguous** – multiple candidates are within the tie gap of each
       other after partial or fuzzy steps.
    5. **None** – nothing passes the threshold.

    Args:
        query_owner: The raw owner string from the user's question.
        known_owners: The exhaustive list of canonical owner names from the
            data.  Duplicates are silently ignored.
        fuzzy_threshold: Minimum rapidfuzz WRatio score (0–100) to accept a
            candidate.  Defaults to :data:`DEFAULT_FUZZY_THRESHOLD` (85).

    Returns:
        An :class:`~qara.analytics.schemas.OwnerResolutionResult` describing
        the outcome.  ``matched_owner`` is set only when ``match_type`` is
        one of ``"exact"``, ``"partial"``, or ``"fuzzy"``.

    Examples::

        # "Fatima" → "Fatima Al-Rashid" if she is the only Fatima
        resolve_owner_name("Fatima", ["Fatima Al-Rashid", "John Doe"])

        # "John" → ambiguous when both John Doe and John Smith exist
        resolve_owner_name("John", ["John Doe", "John Smith"])

        # "Fathima" → fuzzy match to "Fatima Al-Rashid" at ≥85 score
        resolve_owner_name("Fathima", ["Fatima Al-Rashid", "John Doe"])
    """
    if not known_owners:
        return OwnerResolutionResult(
            query=query_owner,
            matched_owner=None,
            match_type="none",
            candidates=[],
            confidence=0.0,
            explanation="No known owners provided.",
        )

    # Deduplicate while preserving canonical casing.
    unique_owners: list[str] = list(dict.fromkeys(known_owners))
    norm_query = normalize_owner_name(query_owner)

    # Build a lookup: normalized form → original canonical name.
    # When two owners normalize identically (unlikely but possible), the first
    # one wins.  This mirrors the behaviour of `dict.fromkeys`.
    norm_map: dict[str, str] = {}
    for owner in unique_owners:
        key = normalize_owner_name(owner)
        norm_map.setdefault(key, owner)

    norm_known = list(norm_map.keys())

    # ── 1. Exact match ────────────────────────────────────────────────────
    if norm_query in norm_map:
        canonical = norm_map[norm_query]
        return OwnerResolutionResult(
            query=query_owner,
            matched_owner=canonical,
            match_type="exact",
            candidates=[canonical],
            confidence=1.0,
            explanation=f"Exact normalized match: '{query_owner}' → '{canonical}'.",
        )

    # ── 2. Partial / token containment ───────────────────────────────────
    query_tokens = set(norm_query.split())
    partial_matches: list[str] = []
    for norm_name, canonical in norm_map.items():
        known_tokens = set(norm_name.split())
        if query_tokens.issubset(known_tokens):
            partial_matches.append(canonical)

    if len(partial_matches) == 1:
        canonical = partial_matches[0]
        return OwnerResolutionResult(
            query=query_owner,
            matched_owner=canonical,
            match_type="partial",
            candidates=[canonical],
            confidence=0.95,
            explanation=(
                f"Token containment: all tokens of '{query_owner}' "
                f"appear in '{canonical}'."
            ),
        )

    if len(partial_matches) > 1:
        return OwnerResolutionResult(
            query=query_owner,
            matched_owner=None,
            match_type="ambiguous",
            candidates=partial_matches,
            confidence=0.0,
            explanation=(
                f"'{query_owner}' is ambiguous — tokens match multiple owners: "
                f"{partial_matches}."
            ),
        )

    # ── 3. Fuzzy matching ─────────────────────────────────────────────────
    # Use strip_punctuation normalization for the fuzzy step to handle
    # apostrophes and other punctuation gracefully.
    norm_query_fuzzy = normalize_owner_name(query_owner, strip_punctuation=True)
    norm_known_fuzzy = [
        normalize_owner_name(o, strip_punctuation=True) for o in unique_owners
    ]
    # Map fuzzy-normalized → canonical for recovery after matching.
    fuzzy_map: dict[str, str] = dict(zip(norm_known_fuzzy, unique_owners))

    results = process.extract(
        norm_query_fuzzy,
        norm_known_fuzzy,
        scorer=fuzz.WRatio,
        limit=len(norm_known_fuzzy),
    )
    # results: list[tuple[str, int, int]] — (match_str, score, index)
    above: list[tuple[str, int]] = [
        (fuzzy_map[m], score) for m, score, _ in results if score >= fuzzy_threshold
    ]

    if not above:
        return OwnerResolutionResult(
            query=query_owner,
            matched_owner=None,
            match_type="none",
            candidates=[],
            confidence=0.0,
            explanation=(
                f"No owner matched '{query_owner}' "
                f"(fuzzy threshold: {fuzzy_threshold})."
            ),
        )

    top_score = above[0][1]

    # Candidates within _FUZZY_TIE_GAP of the top score are co-equal.
    dominant = [canonical for canonical, score in above if score >= top_score - _FUZZY_TIE_GAP]

    if len(dominant) == 1:
        canonical = dominant[0]
        return OwnerResolutionResult(
            query=query_owner,
            matched_owner=canonical,
            match_type="fuzzy",
            candidates=[canonical],
            confidence=round(top_score / 100.0, 4),
            explanation=(
                f"Fuzzy match (score {top_score}/100): "
                f"'{query_owner}' → '{canonical}'."
            ),
        )

    # Multiple candidates within the tie gap → ambiguous.
    return OwnerResolutionResult(
        query=query_owner,
        matched_owner=None,
        match_type="ambiguous",
        candidates=dominant,
        confidence=0.0,
        explanation=(
            f"'{query_owner}' is ambiguous — multiple fuzzy candidates "
            f"within {_FUZZY_TIE_GAP} points of each other: {dominant}."
        ),
    )
