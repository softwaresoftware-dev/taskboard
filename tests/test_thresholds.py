from datetime import datetime, timezone

from taskboard.contract import Status
from taskboard.thresholds import derive_state


def _s(facts=None, error=None):
    return Status(facts=facts or {}, details={}, checked_at=datetime.now(timezone.utc), error=error)


def test_no_rules_is_healthy():
    assert derive_state(_s({"x": 1}), None) == "healthy"
    assert derive_state(_s({"x": 1}), {}) == "healthy"


def test_error_trumps_thresholds():
    assert derive_state(_s(error="auth failed"), {"x": {"crit_gt": 0}}) == "error"


def test_numeric_gt_warn_and_crit():
    rules = {"pr_age": {"warn_gt": 7, "crit_gt": 30}}
    assert derive_state(_s({"pr_age": 5}),  rules) == "healthy"
    assert derive_state(_s({"pr_age": 10}), rules) == "warn"
    assert derive_state(_s({"pr_age": 60}), rules) == "crit"


def test_numeric_lt():
    rules = {"disk_gb_free": {"warn_lt": 50, "crit_lt": 10}}
    assert derive_state(_s({"disk_gb_free": 100}), rules) == "healthy"
    assert derive_state(_s({"disk_gb_free": 40}),  rules) == "warn"
    assert derive_state(_s({"disk_gb_free": 5}),   rules) == "crit"


def test_boolean_if():
    rules = {"archived": {"crit_if": True}}
    assert derive_state(_s({"archived": True}),  rules) == "crit"
    assert derive_state(_s({"archived": False}), rules) == "healthy"


def test_if_in_and_not_in():
    rules = {"status_code": {"crit_if_not_in": [200, 301]}}
    assert derive_state(_s({"status_code": 200}), rules) == "healthy"
    assert derive_state(_s({"status_code": 301}), rules) == "healthy"
    assert derive_state(_s({"status_code": 500}), rules) == "crit"


def test_worst_severity_wins():
    rules = {
        "a": {"warn_gt": 0},
        "b": {"crit_gt": 0},
    }
    assert derive_state(_s({"a": 5, "b": 5}), rules) == "crit"
    assert derive_state(_s({"a": 5, "b": 0}), rules) == "warn"


def test_missing_facts_are_ignored():
    rules = {"pr_age": {"crit_gt": 1}}
    assert derive_state(_s({"other": 99}), rules) == "healthy"


def test_none_values_skip_threshold():
    rules = {"latest_age": {"crit_gt": 30}}
    assert derive_state(_s({"latest_age": None}), rules) == "healthy"


def test_bools_not_treated_as_numbers():
    # True == 1, but we don't want "archived": True to trip a warn_gt: 0
    rules = {"archived": {"warn_gt": 0}}
    assert derive_state(_s({"archived": True}), rules) == "healthy"
