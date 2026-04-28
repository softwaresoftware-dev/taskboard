"""The Mindframe contract.

Packs implement Source. The framework calls probe() and applies thresholds
from systems.json to derive state.

A probe returns a Status. Status carries facts (for thresholding) and an
optional View (for rich rendering). Health-only packs return Status without
a view; data-rich packs (tables, feeds, charts, stat tiles) attach one of
the View types below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Union


# ---------- View payloads ----------


@dataclass
class Stat:
    """A single metric tile: big value + label + optional detail/trend."""
    value:  Any
    label:  str
    detail: str | None = None
    accent: str | None = None
    trend:  list[float] | None = None
    kind:   Literal["stat"] = "stat"


@dataclass
class Column:
    """One column in a Table view.

    cell_kind drives how each row's value in this column is rendered:
        text       — plain string
        code       — monospace string
        link       — {href, text}
        badge      — string (or {text, accent})
        tags       — list of strings
        progress   — {value, max, label?}
        sparkline  — list of numbers
        timestamp  — ISO datetime, rendered as "Nh ago"
        actions    — list of action ids enabled for this row
        multiline  — {title, lines}
    """
    key:       str
    label:     str
    cell_kind: str = "text"
    align:     str | None = None


@dataclass
class Action:
    """A row-level action button.

    Framework renders a button. Wiring POST endpoints to pack-side handlers
    is a follow-up; for now the button posts to a generic endpoint that
    returns 501 unless the pack implements act().
    """
    id:      str
    label:   str
    confirm: bool = False
    style:   str | None = None


@dataclass
class Group:
    """Optional row grouping for a Table view."""
    key:   str
    label: str
    badge: str | None = None


@dataclass
class Filter:
    """Optional filter pill or text-search box for a Table view."""
    id:      str
    label:   str
    kind:    Literal["pill", "text"] = "pill"
    options: list[dict[str, Any]] | None = None


@dataclass
class Table:
    """A tabular view with typed columns and rich cell renderers."""
    columns: list[Column]
    rows:    list[dict[str, Any]] = field(default_factory=list)
    actions: list[Action] | None = None
    groups:  list[Group]  | None = None
    filters: list[Filter] | None = None
    kind:    Literal["table"] = "table"


@dataclass
class Chart:
    """A timeseries chart — line, bar, or inline sparkline."""
    chart_kind: Literal["bar", "line", "sparkline"]
    points:     list[dict[str, Any]] = field(default_factory=list)
    period:     str | None = None
    windows:    list[str] | None = None
    kind:       Literal["chart"] = "chart"


@dataclass
class Feed:
    """A sequential list of timestamped events."""
    items: list[dict[str, Any]] = field(default_factory=list)
    kind:  Literal["feed"] = "feed"


View = Union[Stat, Table, Chart, Feed]


# ---------- Probe return + context ----------


@dataclass
class Status:
    """What a probe returns. Facts, not judgments — plus optional rich view."""
    facts:      dict[str, Any] = field(default_factory=dict)
    details:   dict[str, Any] = field(default_factory=dict)
    checked_at: datetime | None = None
    error:      str | None = None
    view:       View | None = None


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


__all__ = [
    "Action",
    "Chart",
    "Column",
    "Context",
    "Feed",
    "Filter",
    "Group",
    "Source",
    "Stat",
    "Status",
    "Table",
    "View",
]
