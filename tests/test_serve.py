"""Tests for the serve() factory.

Uses FastAPI's TestClient and a fake pack so the suite never touches the network.
Startup polling is exercised; the test pack records every call.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mindframe.contract import Context, Status
from mindframe.serve import serve


class _FakePack:
    """Source-protocol-compatible pack, configurable per-kind return."""
    KINDS = ["fake/ok", "fake/down", "fake/error"]
    REF_SCHEMAS = {k: "<ref>" for k in KINDS}
    SCRUB: dict = {k: [] for k in KINDS}

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def probe(self, kind: str, ref: str, ctx: Context) -> Status:
        self.calls.append((kind, ref))
        now = datetime.now(timezone.utc)
        if kind == "fake/ok":
            return Status(facts={"ok": True, "n": 1}, details={"note": "fine"}, checked_at=now)
        if kind == "fake/down":
            return Status(facts={"ok": False, "n": 99}, details={}, checked_at=now)
        if kind == "fake/error":
            return Status(facts={}, details={}, checked_at=now, error="boom")
        raise ValueError(kind)


def _write_systems(path: Path) -> None:
    path.write_text(json.dumps({
        "systems": {
            "alpha": {
                "description": "first",
                "components": {
                    "happy": {
                        "kind": "fake/ok",
                        "ref": "a",
                        "thresholds": {"ok": {"crit_if": False}},
                    },
                    "sad": {
                        "kind": "fake/down",
                        "ref": "b",
                        "thresholds": {"ok": {"crit_if": False}, "n": {"warn_gt": 10}},
                    },
                },
            },
            "beta": {
                "description": "second",
                "components": {
                    "busted": {"kind": "fake/error", "ref": "c"},
                },
            },
        },
    }))


def test_healthz_and_systems_endpoints(tmp_path: Path):
    sys_path = tmp_path / "systems.json"
    _write_systems(sys_path)
    pack = _FakePack()
    app = serve(systems_path=sys_path, packs={"fake": pack}, poll_interval=3600)

    with TestClient(app) as client:
        # Startup triggers an initial poll; give it time to complete.
        # TestClient's context manager runs startup synchronously via the event loop.
        health = client.get("/healthz").json()
        assert health == {"ok": True, "systems": 2}

        snap = client.get("/api/systems").json()
        assert set(snap["systems"]) == {"alpha", "beta"}

        # Force a refresh so results are populated deterministically.
        client.post("/api/systems/alpha/refresh")
        client.post("/api/systems/beta/refresh")

        alpha = client.get("/api/systems/alpha").json()
        assert alpha["components"]["happy"]["state"] == "healthy"
        assert alpha["components"]["sad"]["state"] == "crit"
        # System-level state is the worst of its components
        assert alpha["state"] == "crit"

        beta = client.get("/api/systems/beta").json()
        assert beta["components"]["busted"]["state"] == "error"
        assert beta["components"]["busted"]["error"] == "boom"


def test_unknown_system_404s(tmp_path: Path):
    sys_path = tmp_path / "systems.json"
    _write_systems(sys_path)
    app = serve(systems_path=sys_path, packs={"fake": _FakePack()}, poll_interval=3600)

    with TestClient(app) as client:
        resp = client.get("/api/systems/does-not-exist")
        assert resp.status_code == 404


def test_missing_pack_becomes_error_state(tmp_path: Path):
    sys_path = tmp_path / "systems.json"
    sys_path.write_text(json.dumps({
        "systems": {"orphan": {"components": {"x": {"kind": "no-such/thing", "ref": "y"}}}}
    }))
    app = serve(systems_path=sys_path, packs={}, poll_interval=3600)

    with TestClient(app) as client:
        client.post("/api/systems/orphan/refresh")
        data = client.get("/api/systems/orphan").json()
        assert data["components"]["x"]["state"] == "error"
        assert "no pack registered" in data["components"]["x"]["error"]


def test_index_renders_html(tmp_path: Path):
    sys_path = tmp_path / "systems.json"
    _write_systems(sys_path)
    app = serve(systems_path=sys_path, packs={"fake": _FakePack()}, poll_interval=3600)

    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "alpha" in resp.text
        assert "beta" in resp.text


def test_missing_systems_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        serve(systems_path=tmp_path / "nope.json", packs={}, poll_interval=3600)


def test_builtins_registered_by_default(tmp_path: Path):
    sys_path = tmp_path / "systems.json"
    sys_path.write_text(json.dumps({"systems": {}}))
    app = serve(systems_path=sys_path, packs={}, poll_interval=3600)
    state = app.state.mindframe
    for name in ("http", "tcp", "cmd", "file"):
        assert name in state.packs
