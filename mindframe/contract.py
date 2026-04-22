"""The Mindframe contract.

Packs implement Source. The framework calls probe() and applies thresholds
from systems.json to derive state.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class Status:
    """What a probe returns. Facts, not judgments."""
    facts:      dict[str, Any] = field(default_factory=dict)
    details:    dict[str, Any] = field(default_factory=dict)
    checked_at: datetime | None = None
    error:      str | None = None


@dataclass
class Context:
    """Passed to probe(). Config from systems.json plus runtime plumbing.

    fixtures_dir: when set, probe() should read fixture files instead of
    calling live APIs. Used in tests and for the fixtures-as-contract
    validation loop.
    """
    config:       dict[str, Any] = field(default_factory=dict)
    fixtures_dir: str | None = None


class Source(Protocol):
    """The contract every pack implements."""
    KINDS:       list[str]
    REF_SCHEMAS: dict[str, str]
    SCRUB:       dict[str, list[str]]

    def probe(self, kind: str, ref: str, ctx: Context) -> Status: ...
