"""Exact, inspectable checks. Passing is not a general semantic correctness score."""

import json
import math

from prompttrial.models import Case


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonstandard JSON number: {value}")


def _equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _equal(a, e) for a, e in zip(actual, expected, strict=True)
        )
    if isinstance(actual, float) and not math.isfinite(actual):
        return False
    return actual == expected


def check(case: Case, output: str) -> tuple[bool, str]:
    if case.checker == "exact":
        passed = output.strip() == case.expected
        return passed, "Exact output matched" if passed else "Expected exact output differs"
    try:
        actual = json.loads(
            output, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, TypeError, RecursionError):
        return False, "Invalid strict JSON (fences, duplicate keys and NaN are rejected)"
    passed = _equal(actual, case.expected)
    return passed, "JSON fields and types matched" if passed else "JSON fields or types differ"
