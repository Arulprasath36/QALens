"""Tests for qalens.analyzers.fingerprint."""

from __future__ import annotations

import pytest

from qalens.analyzers.fingerprint import compute_fingerprint, normalize_stack_trace


# ---------------------------------------------------------------------------
# normalize_stack_trace
# ---------------------------------------------------------------------------


JAVA_TRACE = """\
org.openqa.selenium.NoSuchElementException: no such element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:342)
    at com.orangehrm.LoginTest.verifyLogin(LoginTest.java:87)
    at com.orangehrm.LoginTest.testLoginWithInvalidPassword(LoginTest.java:54)
    at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
"""

JAVA_TRACE_DIFFERENT_LINES = """\
org.openqa.selenium.NoSuchElementException: no such element
    at org.openqa.selenium.remote.RemoteWebDriver.findElement(RemoteWebDriver.java:399)
    at com.orangehrm.LoginTest.verifyLogin(LoginTest.java:91)
    at com.orangehrm.LoginTest.testLoginWithInvalidPassword(LoginTest.java:58)
    at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
"""

PYTHON_TRACE = """\
Traceback (most recent call last):
  File "/home/runner/work/project/tests/test_login.py", line 42, in test_valid_login
    driver.find_element(By.ID, "loginBtn")
selenium.common.exceptions.NoSuchElementException: Message: no such element
"""


def test_normalize_strips_line_numbers():
    result = normalize_stack_trace(JAVA_TRACE)
    assert ":87" not in result
    assert ":LINE" in result


def test_normalize_strips_absolute_paths():
    result = normalize_stack_trace(PYTHON_TRACE)
    assert "/home/runner/work/project/tests/" not in result


def test_same_bug_different_line_numbers_produces_same_normalised_form():
    n1 = normalize_stack_trace(JAVA_TRACE)
    n2 = normalize_stack_trace(JAVA_TRACE_DIFFERENT_LINES)
    assert n1 == n2


def test_normalize_empty_returns_empty():
    assert normalize_stack_trace("") == ""
    assert normalize_stack_trace("   ") == ""


def test_normalize_limits_to_ten_frames():
    big_trace = "SomeException: boom\n" + "\n".join(
        f"    at com.example.Foo.method{i}(Foo.java:{i})" for i in range(20)
    )
    result = normalize_stack_trace(big_trace)
    lines = [l for l in result.splitlines() if l.strip()]
    # 1 headline + up to 10 frames = 11 max
    assert len(lines) <= 11


# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_is_16_chars():
    fp = compute_fingerprint(error_type="NullPointerException", stack_trace=None)
    assert len(fp) == 16


def test_fingerprint_is_hex():
    fp = compute_fingerprint(error_type="NullPointerException", stack_trace=None)
    int(fp, 16)  # should not raise


def test_same_trace_always_same_fingerprint():
    fp1 = compute_fingerprint(error_type="NoSuchElementException", stack_trace=JAVA_TRACE)
    fp2 = compute_fingerprint(error_type="NoSuchElementException", stack_trace=JAVA_TRACE)
    assert fp1 == fp2


def test_different_line_numbers_same_fingerprint():
    fp1 = compute_fingerprint(error_type="NoSuchElementException", stack_trace=JAVA_TRACE)
    fp2 = compute_fingerprint(
        error_type="NoSuchElementException", stack_trace=JAVA_TRACE_DIFFERENT_LINES
    )
    assert fp1 == fp2


def test_different_exception_types_different_fingerprint():
    fp1 = compute_fingerprint(error_type="NullPointerException", stack_trace=None, message="boom")
    fp2 = compute_fingerprint(error_type="TimeoutException", stack_trace=None, message="boom")
    assert fp1 != fp2


def test_completely_different_trace_different_fingerprint():
    trace_a = "ExceptionA: msg\n    at com.a.Foo.bar(Foo.java:1)"
    trace_b = "ExceptionB: msg\n    at com.b.Baz.qux(Baz.java:1)"
    fp1 = compute_fingerprint(error_type="ExceptionA", stack_trace=trace_a)
    fp2 = compute_fingerprint(error_type="ExceptionB", stack_trace=trace_b)
    assert fp1 != fp2


def test_fallback_uses_error_type_and_message():
    fp = compute_fingerprint(
        error_type="AssertionError",
        stack_trace=None,
        message="Expected 200 but was 404",
    )
    assert len(fp) == 16


def test_all_none_returns_unknown_fingerprint():
    fp = compute_fingerprint(error_type=None, stack_trace=None, message=None)
    assert len(fp) == 16  # "unknown" hashed
