"""Owner mapping support for parsed QaLens test runs.

Reports do not always carry owner metadata.  This module lets teams provide
an explicit ownership file and applies it before a run is persisted.
"""

from __future__ import annotations

import fnmatch
import importlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from qalens.analyzers.canonical import to_canonical_name

if TYPE_CHECKING:
    from qalens.models.run import TestRun
    from qalens.models.test_case import TestCaseResult


@dataclass(frozen=True)
class OwnerMappingRule:
    """One ownership rule from an owner mapping file."""

    owner: str
    tests: tuple[str, ...] = ()
    canonical_tests: tuple[str, ...] = ()
    test_regex: tuple[str, ...] = ()
    suites: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    stories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class OwnerMapping:
    """Normalized owner mapping configuration."""

    rules: tuple[OwnerMappingRule, ...]


@dataclass
class OwnerMappingStats:
    """Counts describing the result of applying an owner mapping."""

    matched: int = 0
    assigned: int = 0
    overwritten: int = 0
    unmatched: int = 0
    by_owner: dict[str, int] = field(default_factory=dict)


def load_owner_mapping(path: str | Path) -> OwnerMapping:
    """Load owner mapping rules from a JSON or TOML file."""
    mapping_path = Path(path)
    suffix = mapping_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    elif suffix == ".toml":
        module_name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
        toml = importlib.import_module(module_name)
        payload = toml.loads(mapping_path.read_text(encoding="utf-8"))
    else:
        raise ValueError("Owner mapping file must be .json or .toml.")

    return OwnerMapping(rules=tuple(_parse_rules(payload)))


def apply_owner_mapping(
    run: TestRun,
    mapping: OwnerMapping,
    *,
    override_existing: bool = False,
) -> OwnerMappingStats:
    """Apply owner rules to a parsed run in-place.

    Existing owner labels from the report are preserved by default.  Pass
    ``override_existing=True`` when the mapping file should be authoritative.
    """
    stats = OwnerMappingStats()

    for test in run.test_cases:
        rule = _find_rule(test, mapping.rules)
        if rule is None:
            stats.unmatched += 1
            continue

        stats.matched += 1
        if test.owner and not override_existing:
            continue

        if test.owner and test.owner != rule.owner:
            stats.overwritten += 1
        elif not test.owner:
            stats.assigned += 1

        test.owner = rule.owner
        stats.by_owner[rule.owner] = stats.by_owner.get(rule.owner, 0) + 1

    return stats


def _parse_rules(payload: object) -> list[OwnerMappingRule]:
    if isinstance(payload, dict):
        payload_dict = cast("dict[str, object]", payload)
        raw_rules = payload_dict.get("owners", payload_dict.get("rules"))
    else:
        raw_rules = payload

    if isinstance(raw_rules, dict):
        items = []
        for owner, rule_body in raw_rules.items():
            body = {"owner": owner}
            if isinstance(rule_body, dict):
                body.update(rule_body)
            elif isinstance(rule_body, list):
                body["tests"] = rule_body
            else:
                raise ValueError(f"Invalid owner rule for {owner!r}.")
            items.append(body)
        raw_rules = items

    if not isinstance(raw_rules, list):
        raise ValueError("Owner mapping must contain an 'owners' list or object.")

    rules: list[OwnerMappingRule] = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise ValueError("Each owner mapping rule must be an object.")
        owner = _clean_text(raw.get("owner"))
        if not owner:
            raise ValueError("Each owner mapping rule requires a non-empty owner.")

        rules.append(
            OwnerMappingRule(
                owner=owner,
                tests=_clean_tuple(raw.get("tests")),
                canonical_tests=tuple(
                    to_canonical_name(value) for value in _clean_tuple(raw.get("canonical_tests"))
                ),
                test_regex=_clean_tuple(raw.get("test_regex")),
                suites=_clean_tuple(raw.get("suites")),
                features=_clean_tuple(raw.get("features")),
                stories=_clean_tuple(raw.get("stories")),
                tags=_clean_tuple(raw.get("tags")),
            )
        )

    return rules


def _find_rule(
    test: TestCaseResult,
    rules: tuple[OwnerMappingRule, ...],
) -> OwnerMappingRule | None:
    for rule in rules:
        if _matches_rule(test, rule):
            return rule
    return None


def _matches_rule(test: TestCaseResult, rule: OwnerMappingRule) -> bool:
    canonical = to_canonical_name(test.name)
    test_values = [test.name, test.full_name, test.test_id, canonical]

    if rule.canonical_tests and canonical in rule.canonical_tests:
        return True
    if rule.tests and any(_matches_any_pattern(value, rule.tests) for value in test_values):
        return True
    if rule.test_regex and any(_matches_any_regex(value, rule.test_regex) for value in test_values):
        return True
    if test.suite and _matches_any_pattern(test.suite, rule.suites):
        return True
    if test.feature and _matches_any_pattern(test.feature, rule.features):
        return True
    if test.story and _matches_any_pattern(test.story, rule.stories):
        return True
    return any(_matches_any_pattern(tag, rule.tags) for tag in test.tags)


def _matches_any_pattern(value: str | None, patterns: tuple[str, ...]) -> bool:
    if not value or not patterns:
        return False
    value_lower = value.lower()
    return any(fnmatch.fnmatchcase(value_lower, pattern.lower()) for pattern in patterns)


def _matches_any_regex(value: str | None, patterns: tuple[str, ...]) -> bool:
    if not value or not patterns:
        return False
    return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)


def _clean_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _clean_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, list):
        raise ValueError("Owner mapping fields must be strings or lists of strings.")
    return tuple(item for item in (_clean_text(item) for item in value) if item)
