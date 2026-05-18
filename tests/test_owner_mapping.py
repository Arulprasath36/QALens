"""Tests for explicit owner mapping files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qalens.models.run import RunMetadata, TestRun
from qalens.models.test_case import TestCaseResult, TestStatus
from qalens.ownership import apply_owner_mapping, load_owner_mapping

if TYPE_CHECKING:
    from pathlib import Path


def _run() -> TestRun:
    return TestRun(
        metadata=RunMetadata(report_format="allure", report_path="/tmp/report"),
        test_cases=[
            TestCaseResult(
                test_id="auth-1",
                name="testValidUserLogin()",
                status=TestStatus.PASSED,
                suite="Authentication Tests",
                tags=["smoke"],
            ),
            TestCaseResult(
                test_id="checkout-1",
                name="testCreditCardPayment()",
                status=TestStatus.FAILED,
                suite="Payments",
                feature="Checkout",
                owner="Report Owner",
            ),
            TestCaseResult(
                test_id="search-1",
                name="testSearchWithFilter()",
                status=TestStatus.PASSED,
                suite="Search",
            ),
        ],
    )


def test_owner_mapping_assigns_from_toml_rules(tmp_path: Path) -> None:
    path = tmp_path / "owners.toml"
    path.write_text(
        """
[[owners]]
owner = "Auth Team"
suites = ["Authentication*"]

[[owners]]
owner = "Checkout Team"
features = ["Checkout"]

[[owners]]
owner = "Search Team"
test_regex = ["SearchWithFilter"]
""".strip(),
        encoding="utf-8",
    )

    run = _run()
    stats = apply_owner_mapping(run, load_owner_mapping(path))

    assert run.test_cases[0].owner == "Auth Team"
    assert run.test_cases[1].owner == "Report Owner"
    assert run.test_cases[2].owner == "Search Team"
    assert stats.assigned == 2
    assert stats.matched == 3


def test_owner_mapping_can_override_existing_report_owner(tmp_path: Path) -> None:
    path = tmp_path / "owners.json"
    path.write_text(
        """
{
  "owners": [
    {
      "owner": "Checkout Team",
      "features": ["Checkout"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    run = _run()
    stats = apply_owner_mapping(
        run,
        load_owner_mapping(path),
        override_existing=True,
    )

    assert run.test_cases[1].owner == "Checkout Team"
    assert stats.overwritten == 1


def test_owner_mapping_accepts_owner_object_shorthand(tmp_path: Path) -> None:
    path = tmp_path / "owners.json"
    path.write_text(
        """
{
  "owners": {
    "Auth Team": {
      "canonical_tests": ["testvaliduserlogin"]
    }
  }
}
""".strip(),
        encoding="utf-8",
    )

    run = _run()
    apply_owner_mapping(run, load_owner_mapping(path))

    assert run.test_cases[0].owner == "Auth Team"
