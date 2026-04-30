"""Thresholds: map probe facts to healthy|warn|crit.

The pack reports facts. The user writes threshold rules in systems.json.
This module joins the two. Severity escalates: crit beats warn beats healthy.

Threshold DSL (per-fact):
    warn_gt / crit_gt / warn_lt / crit_lt          numeric
    warn_eq / crit_eq                              exact match (any type)
    warn_if / crit_if                              boolean equality (true/false)
    warn_if_in / crit_if_in                        value in list
    warn_if_not_in / crit_if_not_in                value not in list

Probe-level errors (Status.error set) always resolve to "error".
"""
from __future__ import annotations

from typing import Any

from .contract import Status

SEVERITY_ORDER = {"healthy": 0, "warn": 1, "crit": 2, "error": 3}


def derive_state(status: Status, rules: dict[str, dict[str, Any]] | None) -> str:
    """Return one of: healthy, warn, crit, error.

    rules is the per-component threshold dict from systems.json, keyed by fact name.
    """
    if status.error:
        return "error"
    if not rules:
        return "healthy"

    worst = "healthy"
    for fact_name, fact_rules in rules.items():
        if fact_name not in status.facts:
            continue
        value = status.facts[fact_name]
        if value is None:
            continue
        severity = _apply(value, fact_rules)
        if SEVERITY_ORDER[severity] > SEVERITY_ORDER[worst]:
            worst = severity
    return worst


def _apply(value: Any, rules: dict[str, Any]) -> str:
    crit = _matches(value, rules, "crit")
    if crit:
        return "crit"
    warn = _matches(value, rules, "warn")
    if warn:
        return "warn"
    return "healthy"


def _matches(value: Any, rules: dict[str, Any], level: str) -> bool:
    gt = rules.get(f"{level}_gt")
    if gt is not None and _num(value) is not None and _num(value) > gt:
        return True
    lt = rules.get(f"{level}_lt")
    if lt is not None and _num(value) is not None and _num(value) < lt:
        return True
    eq = rules.get(f"{level}_eq")
    if eq is not None and value == eq:
        return True
    if_val = rules.get(f"{level}_if")
    if if_val is not None and value == if_val:
        return True
    in_list = rules.get(f"{level}_if_in")
    if in_list is not None and value in in_list:
        return True
    not_in_list = rules.get(f"{level}_if_not_in")
    if not_in_list is not None and value not in not_in_list:
        return True
    return False


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
