"""Tests for qara.analyzers.canonical."""

from __future__ import annotations

import pytest

from qara.analyzers.canonical import names_match, to_canonical_name


# ---------------------------------------------------------------------------
# to_canonical_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Basic lowercase
        ("LoginTest", "logintest"),
        # Spaces preserved as single space
        ("Login With Valid Credentials", "login with valid credentials"),
        # Bracket parameterization stripped
        ("VerifyAdminUserSearch [data-set-3]", "verifyadminusersearch"),
        ("testLogin [0]", "testlogin"),
        ("testLogin [admin, pwd123]", "testlogin"),
        # Multiple bracket groups
        ("testLogin [admin][pass]", "testlogin"),
        # Parenthesised argument list stripped
        ("testValidLogin(String)", "testvalidlogin"),
        ("testValidLogin()", "testvalidlogin"),
        # Numeric suffix stripped
        ("Verify Dashboard #2", "verify dashboard"),
        ("testFoo_3", "testfoo"),
        ("testFoo - 2", "testfoo"),
        # Mixed punctuation collapsed
        ("my-test_name.case", "my test name case"),
        # Whitespace edge cases
        ("  spaces around  ", "spaces around"),
        # Blank → unknown
        ("", "unknown"),
        ("   ", "unknown"),
        # Already canonical
        ("verifyadminusersearch", "verifyadminusersearch"),
    ],
)
def test_canonical_name_parametrized(raw, expected):
    assert to_canonical_name(raw) == expected


def test_canonical_preserves_internal_spaces():
    result = to_canonical_name("Login With Valid Credentials")
    assert "login with valid credentials" == result


def test_canonical_strips_bracket_and_paren():
    assert to_canonical_name("myTest[data][extra](String)") == "mytest"


def test_canonical_none_like_handled():
    # Not None (type signature is str), but empty string
    assert to_canonical_name("") == "unknown"


# ---------------------------------------------------------------------------
# names_match
# ---------------------------------------------------------------------------


def test_names_match_same_case():
    assert names_match("LoginTest", "logintest") is True


def test_names_match_with_parameters():
    assert names_match("testLogin [data-1]", "testLogin [data-2]") is True


def test_names_match_different_tests():
    assert names_match("testLogin", "testLogout") is False


def test_names_match_trailing_numeric():
    assert names_match("VerifyDashboard #1", "VerifyDashboard #2") is True


def test_names_do_not_match_different_content():
    assert names_match("verifyUserSearch", "verifyAdminSearch") is False
