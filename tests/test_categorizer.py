"""Tests for ari.analyzers.categorizer."""

from __future__ import annotations

import pytest

from qara.analyzers.categorizer import FailureCategory, categorize_failure


# ---------------------------------------------------------------------------
# Element not found
# ---------------------------------------------------------------------------


def test_nosuchelement_exception_maps_to_element_not_found():
    cat = categorize_failure(
        error_type="org.openqa.selenium.NoSuchElementException",
        message="no such element: Unable to locate element",
    )
    assert cat == FailureCategory.ELEMENT_NOT_FOUND


def test_element_not_found_message_without_type():
    cat = categorize_failure(
        error_type=None,
        message="Unable to locate element with id 'submitBtn'",
    )
    assert cat == FailureCategory.ELEMENT_NOT_FOUND


# ---------------------------------------------------------------------------
# Stale element (higher priority than element_not_found)
# ---------------------------------------------------------------------------


def test_stale_element_reference():
    cat = categorize_failure(
        error_type="org.openqa.selenium.StaleElementReferenceException",
        message="stale element reference: element is not attached to the page document",
    )
    assert cat == FailureCategory.STALE_ELEMENT


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout_exception():
    cat = categorize_failure(
        error_type="org.openqa.selenium.TimeoutException",
        message="Expected condition failed: waiting for visibility",
    )
    assert cat == FailureCategory.TIMEOUT


def test_timed_out_message():
    cat = categorize_failure(error_type=None, message="Script timed out after 30 seconds")
    assert cat == FailureCategory.TIMEOUT


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------


def test_assertion_error_type():
    cat = categorize_failure(
        error_type="java.lang.AssertionError",
        message="Expected: <200> but was: <404>",
    )
    assert cat == FailureCategory.ASSERTION


def test_testng_assertion():
    cat = categorize_failure(
        error_type="org.testng.AssertJUnit",
        message="expected:<true> but was:<false>",
    )
    assert cat == FailureCategory.ASSERTION


# ---------------------------------------------------------------------------
# Null pointer
# ---------------------------------------------------------------------------


def test_null_pointer_exception():
    cat = categorize_failure(
        error_type="java.lang.NullPointerException",
        message="Cannot invoke method getText() on null object",
    )
    assert cat == FailureCategory.NULL_POINTER


def test_none_type_attribute_error():
    cat = categorize_failure(
        error_type="AttributeError",
        message="'NoneType' object has no attribute 'click'",
    )
    assert cat == FailureCategory.NULL_POINTER


# ---------------------------------------------------------------------------
# Network / connectivity
# ---------------------------------------------------------------------------


def test_connection_refused():
    cat = categorize_failure(
        error_type="java.net.ConnectException",
        message="Connection refused: connect",
    )
    assert cat == FailureCategory.NETWORK


def test_unreachable_browser():
    cat = categorize_failure(
        error_type="org.openqa.selenium.remote.UnreachableBrowserException",
        message="Could not start a new session",
    )
    assert cat == FailureCategory.NETWORK


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


def test_session_not_created():
    cat = categorize_failure(
        error_type="org.openqa.selenium.SessionNotCreatedException",
        message="Session not created: ChromeDriver version mismatch",
    )
    assert cat == FailureCategory.INFRASTRUCTURE


def test_chromedriver_message():
    cat = categorize_failure(
        error_type=None,
        message="chromedriver executable needs to be in PATH",
    )
    assert cat == FailureCategory.INFRASTRUCTURE


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_401_in_message():
    cat = categorize_failure(
        error_type="AssertionError",
        message="Expected status 200 but got 401",
    )
    assert cat == FailureCategory.AUTHENTICATION


def test_unauthorized_error():
    cat = categorize_failure(
        error_type="UnauthorizedException",
        message="User is not authorized",
    )
    assert cat == FailureCategory.AUTHENTICATION


# ---------------------------------------------------------------------------
# Unknown fallback
# ---------------------------------------------------------------------------


def test_unknown_when_no_match():
    cat = categorize_failure(error_type=None, message=None)
    assert cat == FailureCategory.UNKNOWN


def test_unknown_error_type_no_pattern():
    cat = categorize_failure(
        error_type="com.example.CustomBusinessException",
        message="Some business rule violation",
    )
    assert cat == FailureCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Label helper
# ---------------------------------------------------------------------------


def test_label_title_case():
    assert FailureCategory.ELEMENT_NOT_FOUND.label == "Element Not Found"
    assert FailureCategory.NULL_POINTER.label == "Null Pointer"
    assert FailureCategory.INFRASTRUCTURE.label == "Infrastructure"
