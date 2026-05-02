"""Tests for the View contract and HTML rendering of view payloads."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from taskboard.contract import (
    Action,
    Chart,
    Column,
    Context,
    Feed,
    Stat,
    Status,
    Table,
)
from taskboard.render import render_html
from taskboard.serve import serve


class _ViewPack:
    KINDS = ["v/stat", "v/table", "v/chart", "v/feed"]
    REF_SCHEMAS = {k: "<ref>" for k in KINDS}
    SCRUB: dict = {k: [] for k in KINDS}

    def probe(self, kind: str, ref: str, ctx: Context) -> Status:
        now = datetime.now(timezone.utc)
        if kind == "v/stat":
            return Status(facts={"n": 7}, checked_at=now,
                          view=Stat(value=7, label="Count", detail="last 24h", accent="ok"))
        if kind == "v/table":
            return Status(facts={"rows": 2}, checked_at=now, view=Table(
                columns=[Column(key="name", label="Name"),
                         Column(key="state", label="State", cell_kind="badge"),
                         Column(key="acts", label="Actions", cell_kind="actions")],
                rows=[
                    {"name": "alpha", "state": {"text": "running", "accent": "ok"},   "acts": ["log"]},
                    {"name": "beta",  "state": {"text": "warn",    "accent": "warn"}, "acts": ["log", "kill"]},
                ],
                actions=[Action(id="log", label="log"), Action(id="kill", label="kill", confirm=True)],
            ))
        if kind == "v/chart":
            return Status(facts={"events": 100}, checked_at=now, view=Chart(
                chart_kind="bar",
                points=[{"x": "a", "y": 5}, {"x": "b", "y": 12}, {"x": "c", "y": 8}],
                period="7d",
            ))
        if kind == "v/feed":
            return Status(facts={"events": 1}, checked_at=now, view=Feed(items=[
                {"ts": now.isoformat(), "title": "deployed", "body": "v1.2.3", "accent": "ok"},
            ]))
        raise ValueError(kind)


def _systems(tmp_path: Path) -> Path:
    p = tmp_path / "systems.json"
    p.write_text(json.dumps({
        "systems": {
            s: {"description": s, "components": {"x": {"kind": k, "ref": "—"}}}
            for s, k in [("S", "v/stat"), ("T", "v/table"), ("C", "v/chart"), ("F", "v/feed")]
        }
    }))
    return p


def test_view_payload_survives_serialization(tmp_path: Path):
    sys_path = _systems(tmp_path)
    app = serve(systems_path=sys_path, packs={"v": _ViewPack()}, poll_interval=3600)

    with TestClient(app) as client:
        for s in ("S", "T", "C", "F"):
            client.post(f"/api/systems/{s}/refresh")

        snap = client.get("/api/systems").json()
        stat = snap["systems"]["S"]["components"]["x"]["view"]
        assert stat["kind"] == "stat"
        assert stat["value"] == 7
        assert stat["accent"] == "ok"

        table = snap["systems"]["T"]["components"]["x"]["view"]
        assert table["kind"] == "table"
        assert len(table["rows"]) == 2
        assert table["columns"][0]["key"] == "name"
        assert {a["id"] for a in table["actions"]} == {"log", "kill"}

        chart = snap["systems"]["C"]["components"]["x"]["view"]
        assert chart["kind"] == "chart"
        assert chart["chart_kind"] == "bar"
        assert len(chart["points"]) == 3

        feed = snap["systems"]["F"]["components"]["x"]["view"]
        assert feed["kind"] == "feed"
        assert feed["items"][0]["accent"] == "ok"


def test_html_renders_every_view_kind(tmp_path: Path):
    sys_path = _systems(tmp_path)
    app = serve(systems_path=sys_path, packs={"v": _ViewPack()}, poll_interval=3600,
                title="View Smoke Test")

    with TestClient(app) as client:
        for s in ("S", "T", "C", "F"):
            client.post(f"/api/systems/{s}/refresh")
        html = client.get("/").text

    assert "View Smoke Test" in html
    assert "stat-card" in html
    assert "view-table" in html
    assert "chart" in html
    assert "feed" in html


def test_renderer_falls_back_for_status_without_view():
    snap = {
        "snapshot_at": "2026-04-28T00:00:00Z",
        "systems": {
            "alpha": {
                "name": "alpha", "description": "no view", "url": None, "state": "healthy",
                "components": {
                    "ping": {"state": "healthy", "facts": {"ok": True, "latency_ms": 42},
                             "details": {}, "error": None, "checked_at": None,
                             "kind": "http", "ref": "—", "view": None},
                },
            },
        },
    }
    html = render_html("Smoke", snap)
    body = html.split("</style>", 1)[1]
    assert "latency_ms" in body
    assert "<div class='facts'>" in body
    assert "class='stat-card" not in body
    assert "<table class='view-table'" not in body


def test_renderer_handles_table_with_filters_and_progress(tmp_path: Path):
    snap = {
        "snapshot_at": "2026-04-28T00:00:00Z",
        "systems": {
            "alpha": {
                "name": "alpha", "description": "", "url": None, "state": "healthy",
                "components": {
                    "agents": {
                        "state": "healthy", "facts": {}, "details": {}, "error": None,
                        "checked_at": None, "kind": "demo/table", "ref": "—",
                        "view": {
                            "kind": "table",
                            "columns": [{"key": "name", "label": "Name", "cell_kind": "text"},
                                        {"key": "cpu", "label": "CPU", "cell_kind": "progress"}],
                            "rows": [{"name": "a", "cpu": {"value": 95, "max": 100, "label": "95%"}}],
                            "actions": [],
                            "groups": [],
                            "filters": [{"id": "search", "label": "search", "kind": "text"}],
                        },
                    },
                },
            },
        },
    }
    html = render_html("Smoke", snap)
    assert "filter-text" in html
    assert "progress" in html
    assert "fill crit" in html  # 95% should hit crit accent
