"""Canonical test-name normalisation for QaLens.

A *canonical name* is a stable, normalised version of a test's display name
used to link the same test across multiple runs even when its exact string
representation differs slightly (different parameterization suffixes,
capitalisation, or trailing whitespace).

Usage::

    from qalens.analyzers.canonical import to_canonical_name

    name = to_canonical_name("VerifyAdminUserSearch [data-set-3]")
    # → "verifyadminusersearch"
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns stripped from the raw name before normalisation
# ---------------------------------------------------------------------------

# Parameterized suffixes: [data-set-3], [0], [admin, pwd123], etc.
_BRACKET_PARAM_RE = re.compile(r"\s*\[[^\]]*\]\s*$")

# JUnit/TestNG style method-arguments: testLogin(String, int) or testLogin()
_PAREN_PARAM_RE = re.compile(r"\s*\([^)]*\)\s*$")

# Numeric index suffix sometimes appended by runners: testFoo #2, testFoo_3
_NUMERIC_SUFFIX_RE = re.compile(r"[\s_#-]+\d+\s*$")

# Collapse any run of non-alphanumeric characters to a single space for
# comparison purposes (applied *after* the above strips)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def to_canonical_name(name: str) -> str:
    """Return the canonical form of a test name.

    Transformations applied in order:

    1. Strip leading/trailing whitespace.
    2. Remove parameterized bracket suffixes: ``[data-set-3]``, ``[0]``.
    3. Remove parenthesised argument lists: ``(String, int)``, ``()``.
    4. Remove trailing numeric indices: ``#2``, ``_3``, ``- 2``.
    5. Convert to lowercase.
    6. Collapse runs of non-alphanumeric characters to a single space, then
       strip again.

    The result is intentionally aggressive: two names that differ only by
    whitespace, punctuation, capitalisation, or parameter suffixes will
    produce the same canonical name, enabling reliable cross-run matching.

    Args:
        name: The raw test name as extracted from a report.

    Returns:
        Normalised lowercase string. Returns ``"unknown"`` for blank input.

    Examples::

        to_canonical_name("VerifyAdminUserSearch [data-set-3]")
        # → "verifyadminusersearch"

        to_canonical_name("testValidLogin(String)")
        # → "testvalidlogin"

        to_canonical_name("Login With Valid Credentials")
        # → "login with valid credentials"

        to_canonical_name("Verify Dashboard #2")
        # → "verify dashboard"
    """
    if not name or not name.strip():
        return "unknown"

    result = name.strip()

    # Alternate between stripping bracket and paren suffixes until stable
    # so that e.g. "[data][extra](String)" is fully cleaned regardless of order.
    prev = None
    while prev != result:
        prev = result
        result = _BRACKET_PARAM_RE.sub("", result).strip()
        result = _PAREN_PARAM_RE.sub("", result).strip()

    # Strip trailing numeric index
    result = _NUMERIC_SUFFIX_RE.sub("", result).strip()

    # Lowercase
    result = result.lower()

    # Collapse non-alphanumeric runs to a single space, then strip
    result = _NON_ALNUM_RE.sub(" ", result).strip()

    return result if result else "unknown"


def names_match(a: str, b: str) -> bool:
    """Return ``True`` if two test names refer to the same test.

    Compares their canonical forms, so parameterisation and capitalisation
    differences are ignored.

    Args:
        a: First test name (raw or already canonical).
        b: Second test name (raw or already canonical).

    Returns:
        ``True`` when ``to_canonical_name(a) == to_canonical_name(b)``.
    """
    return to_canonical_name(a) == to_canonical_name(b)
