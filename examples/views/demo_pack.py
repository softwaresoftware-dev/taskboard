"""Synthetic pack that returns each view type.

Demonstrates how a pack constructs Stat / Table / Chart / Feed views.
Used by the views example dashboard.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from taskboard.contract import (
    Action,
    Chart,
    Column,
    Context,
    Feed,
    Filter,
    Group,
    Stat,
    Status,
    Table,
)


KINDS = ["demo/stat", "demo/table", "demo/chart", "demo/feed", "demo/health"]
REF_SCHEMAS = {k: "<ignored>" for k in KINDS}
SCRUB: dict[str, list[str]] = {k: [] for k in KINDS}


def probe(kind: str, ref: str, ctx: Context) -> Status:
    now = datetime.now(timezone.utc)
    if kind == "demo/stat":
        return Status(
            facts={"count": 565},
            checked_at=now,
            view=Stat(
                value="565",
                label="Total Sessions",
                detail="since 2026-01-05",
                accent="ok",
                trend=[3, 4, 6, 8, 5, 7, 11, 14, 12, 18, 22, 19, 24, 28, 31],
            ),
        )
    if kind == "demo/table":
        return Status(
            facts={"running": 3, "total": 4},
            checked_at=now,
            view=Table(
                columns=[
                    Column(key="name",   label="Name",     cell_kind="text"),
                    Column(key="tags",   label="Tags",     cell_kind="tags"),
                    Column(key="status", label="Status",   cell_kind="badge"),
                    Column(key="cpu",    label="CPU",      cell_kind="progress"),
                    Column(key="age",    label="Age",      cell_kind="timestamp"),
                    Column(key="acts",   label="Actions",  cell_kind="actions"),
                ],
                rows=[
                    {"name": "dispatcher",  "tags": ["systemd", "project"], "status": {"text": "running", "accent": "ok"},
                     "cpu": {"value": 23, "max": 100, "label": "23%"},
                     "age": (now - timedelta(hours=19)).isoformat(),  "acts": ["log", "restart", "stop"]},
                    {"name": "librarian",   "tags": ["systemd", "project"], "status": {"text": "running", "accent": "ok"},
                     "cpu": {"value": 67, "max": 100, "label": "67%"},
                     "age": (now - timedelta(hours=19)).isoformat(),  "acts": ["log", "restart", "stop"]},
                    {"name": "beats-dj",    "tags": ["systemd", "project"], "status": {"text": "running", "accent": "ok"},
                     "cpu": {"value": 91, "max": 100, "label": "91%"},
                     "age": (now - timedelta(hours=19)).isoformat(),  "acts": ["log", "restart", "stop"]},
                    {"name": "email-triage", "tags": ["haiku"],             "status": {"text": "warn", "accent": "warn"},
                     "cpu": {"value": 12, "max": 100, "label": "12%"},
                     "age": (now - timedelta(hours=19)).isoformat(),  "acts": ["log", "kill"]},
                ],
                actions=[
                    Action(id="log",     label="log"),
                    Action(id="restart", label="restart"),
                    Action(id="stop",    label="stop"),
                    Action(id="kill",    label="kill", confirm=True),
                ],
                filters=[
                    Filter(id="status", label="status", kind="pill", options=[
                        {"label": "active",  "value": "active"},
                        {"label": "running", "value": "running"},
                        {"label": "all",     "value": "all"},
                        {"label": "killed",  "value": "killed"},
                    ]),
                    Filter(id="search", label="filter agents", kind="text"),
                ],
            ),
        )
    if kind == "demo/chart":
        return Status(
            facts={"events": 1150},
            checked_at=now,
            view=Chart(
                chart_kind="bar",
                period="30 days",
                points=[
                    {"x": "d1", "y": 79},  {"x": "d2", "y": 484}, {"x": "d3", "y": 2017},
                    {"x": "d4", "y": 99},  {"x": "d5", "y": 184}, {"x": "d6", "y": 1585},
                    {"x": "d7", "y": 1560}, {"x": "d8", "y": 262}, {"x": "d9", "y": 25},
                    {"x": "d10", "y": 802}, {"x": "d11", "y": 1234}, {"x": "d12", "y": 945},
                    {"x": "d13", "y": 670}, {"x": "d14", "y": 1322},
                ],
            ),
        )
    if kind == "demo/feed":
        return Status(
            facts={"events": 5},
            checked_at=now,
            view=Feed(items=[
                {"ts": (now - timedelta(minutes=2)).isoformat(),
                 "title": "deploy succeeded", "body": "softwaresoftware-marketplace v0.4.2", "accent": "ok"},
                {"ts": (now - timedelta(minutes=14)).isoformat(),
                 "title": "PR opened",        "body": "extend taskboard contract with view types", "accent": "info"},
                {"ts": (now - timedelta(hours=1)).isoformat(),
                 "title": "container restarted", "body": "gummymine-django (oom)", "accent": "warn"},
                {"ts": (now - timedelta(hours=3)).isoformat(),
                 "title": "alert fired",       "body": "disk usage > 90% on /", "accent": "crit"},
                {"ts": (now - timedelta(hours=6)).isoformat(),
                 "title": "site deployed",     "body": "taskboard.softwaresoftware.dev"},
            ]),
        )
    if kind == "demo/health":
        return Status(
            facts={"status_code": 200, "latency_ms": 138, "reachable": True},
            checked_at=now,
        )
    raise ValueError(f"unknown kind: {kind}")
