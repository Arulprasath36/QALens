"""Rule-based failure categorizer for ARI.

Maps an error type + message pair to a human-readable :class:`FailureCategory`
using ordered regex rules.  No ML or external dependencies required.

Usage::

    from qara.analyzers.categorizer import categorize_failure

    category = categorize_failure(
        error_type="org.openqa.selenium.NoSuchElementException",
        message="no such element: Unable to locate element",
    )
    # → FailureCategory.ELEMENT_NOT_FOUND
"""

from __future__ import annotations

import re
from enum import Enum


class FailureCategory(str, Enum):
    """Human-readable failure categories used across QARA outputs.

    Values are lowercase-hyphenated for JSON serialisation consistency.
    """

    ELEMENT_NOT_FOUND = "element_not_found"
    STALE_ELEMENT = "stale_element"
    TIMEOUT = "timeout"
    ASSERTION = "assertion"
    NULL_POINTER = "null_pointer"
    NETWORK = "network"
    AUTHENTICATION = "authentication"
    INFRASTRUCTURE = "infrastructure"
    TEST_DATA = "test_data"
    PERMISSION = "permission"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """Return a title-cased display label for this category."""
        return self.value.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Rule table — (category, pattern_strings_that_match_error_type_OR_message)
# Rules are evaluated in order; the first match wins.
# ---------------------------------------------------------------------------

# Each rule is: (FailureCategory, list_of_regex_patterns)
# Patterns are tested case-insensitively against the combined
# "<error_type>: <message>" string.

_RULES: list[tuple[FailureCategory, list[str]]] = [
    # --- Selenium / WebDriver element issues ---
    (
        FailureCategory.STALE_ELEMENT,
        [
            r"StaleElementReferenceException",
            r"stale element reference",
        ],
    ),
    (
        FailureCategory.ELEMENT_NOT_FOUND,
        [
            r"NoSuchElementException",
            r"ElementNotFound",
            r"ElementNotFoundException",
            r"no such element",
            r"Unable to locate element",
            r"element not found",
            r"Element not found",
        ],
    ),
    # --- Timeouts / performance ---
    (
        FailureCategory.TIMEOUT,
        [
            r"TimeoutException",
            r"WaitException",
            r"FluentWait",
            r"timed?\s*out",
            r"wait.*exceeded",
            r"SocketTimeoutException",
            r"ReadTimeoutError",
            r"ConnectTimeoutError",
            r"TimeoutError",
        ],
    ),
    # --- Infrastructure / WebDriver setup ---
    (
        FailureCategory.INFRASTRUCTURE,
        [
            r"SessionNotCreatedException",
            r"WebDriverException",
            r"chromedriver",
            r"geckodriver",
            r"EdgeDriver",
            r"safari.*driver",
            r"unable to connect to.*driver",
            r"Could not start.*server",
            r"BrowserStackException",
            r"SauceException",
        ],
    ),
    # --- Network / connectivity ---
    (
        FailureCategory.NETWORK,
        [
            r"ConnectionRefusedError",
            r"UnreachableBrowserException",
            r"ERR_CONNECTION",
            r"Connection refused",
            r"Network.*unreachable",
            r"java\.net\.Connect",
            r"requests\.exceptions\.Connection",
            r"ProtocolError",
            r"RemoteDisconnected",
        ],
    ),
    # --- Null / None pointer ---
    (
        FailureCategory.NULL_POINTER,
        [
            r"NullPointerException",
            r"NullReferenceException",
            r"AttributeError.*NoneType",
            r"NoneType.*has no attribute",
            r"object is None",
            r"Cannot.*null",
        ],
    ),
    # --- Authentication / authorisation (checked before ASSERTION so HTTP 401/403 wins) ---
    (
        FailureCategory.AUTHENTICATION,
        [
            r"\b401\b",
            r"\b403\b",
            r"Unauthorized",
            r"Forbidden",
            r"AuthenticationException",
            r"AuthorizationException",
            r"InvalidCredentials",
            r"login.*fail",
            r"Invalid.*token",
        ],
    ),
    # --- Assertions ---
    (
        FailureCategory.ASSERTION,
        [
            r"AssertionError",
            r"AssertionException",
            r"AssertError",
            r"Expected\b.*\bbut\s+(was|got|found)",
            r"expected:.*but was:",
            r"junit\.framework\.Assert",
            r"org\.testng\.Assert",
            r"assert\s+.*==",
        ],
    ),
    # --- Permissions / access ---
    (
        FailureCategory.PERMISSION,
        [
            r"PermissionDenied",
            r"AccessDenied",
            r"Permission denied",
            r"Access denied",
            r"\b404\b.*resource",
        ],
    ),
    # --- Test data / providers ---
    (
        FailureCategory.TEST_DATA,
        [
            r"DataProviderException",
            r"DataProvider",
            r"FileNotFoundException.*\.csv",
            r"FileNotFoundException.*\.xls",
            r"SQLException",
            r"DataAccessException",
            r"test.*data.*not.*found",
            r"No test data",
        ],
    ),
    # --- Configuration / environment ---
    (
        FailureCategory.CONFIGURATION,
        [
            r"ConfigurationException",
            r"PropertyNotFoundException",
            r"MissingResourceException",
            r"environment variable",
            r"config.*not.*set",
            r"Invalid.*configuration",
        ],
    ),
]

# Pre-compile all patterns once at import time
_COMPILED_RULES: list[tuple[FailureCategory, list[re.Pattern[str]]]] = [
    (category, [re.compile(p, re.IGNORECASE) for p in patterns])
    for category, patterns in _RULES
]


def categorize_failure(
    *,
    error_type: str | None,
    message: str | None = None,
) -> FailureCategory:
    """Classify a failure into a :class:`FailureCategory`.

    Combines *error_type* and *message* into a single target string and
    evaluates each rule in priority order, returning the category of the
    first matching rule.

    Args:
        error_type: The exception class or error type string extracted from
            the report (e.g. ``"org.openqa.selenium.NoSuchElementException"``).
            May be ``None``.
        message: The error message string.  May be ``None``.

    Returns:
        The best-matching :class:`FailureCategory`, or
        :attr:`FailureCategory.UNKNOWN` if no rule matches.
    """
    parts: list[str] = []
    if error_type:
        parts.append(error_type.strip())
    if message:
        # Use only the first line of the message to avoid matching
        # incidental words in long stack-embedded messages.
        parts.append(message.splitlines()[0].strip())

    if not parts:
        return FailureCategory.UNKNOWN

    target = ": ".join(parts)

    for category, patterns in _COMPILED_RULES:
        for pattern in patterns:
            if pattern.search(target):
                return category

    return FailureCategory.UNKNOWN


def category_display(category: FailureCategory) -> str:
    """Return a short display string for *category* suitable for tables.

    Args:
        category: A :class:`FailureCategory` value.

    Returns:
        Title-cased label string, e.g. ``"Element Not Found"``.
    """
    return category.label
