"""Validate the mcp-health pack against its fixtures.

Mirrors the github-pack pattern: a pack is valid iff probe() produces a
well-formed Status for every fixture. We add a few state-classification
tests because the value of this pack is its judgments, not just shape.
"""
from pathlib import Path

import pytest

from taskboard.contract import Context, Status, Table
from taskboard.packs.mcp_health import pack


FIXTURES = Path(__file__).parent.parent / "taskboard" / "packs" / "mcp_health" / "fixtures"


def _ctx():
    return Context(fixtures_dir=str(FIXTURES))


def _rows_by_name(status: Status) -> dict:
    assert isinstance(status.view, Table)
    return {r["name"]: r for r in status.view.rows}


def test_probe_returns_status_with_table():
    status = pack.probe("mcp/health", "default", _ctx())
    assert isinstance(status, Status)
    assert isinstance(status.view, Table)
    assert status.facts["total"] == 4


def test_google_calendar_classified_ok_with_valid_expiry():
    rows = _rows_by_name(pack.probe("mcp/health", "default", _ctx()))
    row = rows["google-calendar"]
    assert row["family"] == "google_oauth"
    assert row["state"] == "ok"
    assert "valid for" in row["detail"]


def test_gmail_organizer_classified_broken_when_no_refresh_token():
    rows = _rows_by_name(pack.probe("mcp/health", "default", _ctx()))
    row = rows["gmail-organizer"]
    assert row["family"] == "google_oauth"
    assert row["state"] == "broken"
    assert "refresh_token" in row["detail"]


def test_slack_classified_unknown_when_token_present():
    rows = _rows_by_name(pack.probe("mcp/health", "default", _ctx()))
    row = rows["slack"]
    assert row["family"] == "slack"
    assert row["state"] == "unknown"


def test_unknown_family_passed_through_as_unknown():
    rows = _rows_by_name(pack.probe("mcp/health", "default", _ctx()))
    row = rows["osrs-wiki"]
    assert row["family"] == "unknown"
    assert row["state"] == "unknown"


def test_facts_sum_matches_total():
    status = pack.probe("mcp/health", "default", _ctx())
    f = status.facts
    assert f["ok"] + f["broken"] + f["unknown"] == f["total"]


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        pack.probe("mcp/nonexistent", "default", _ctx())


def test_expired_and_stale_token_promoted_to_broken(tmp_path):
    """v1.5 heuristic: expired access token + token.json untouched for >=7d
    should be promoted from 'unknown' to 'broken' on the assumption that
    the refresh token has been revoked (or the MCP simply hasn't been
    used — the detail message says both)."""
    import json
    import os
    import time

    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(json.dumps({
        "mcpServers": {
            "google-calendar": {
                "command": "node",
                "args": ["/x/google-calendar-mcp/build/index.js"],
            }
        }
    }))
    tokens = tmp_path / "tokens"
    tokens.mkdir()
    token_file = tokens / "google-calendar.json"
    token_file.write_text(json.dumps({
        "access_token": "fake",
        "refresh_token": "fake",
        "expiry_date": 1700000000000,  # 2023-11-14, well in the past
    }))
    # Push mtime back 30 days so the staleness threshold triggers.
    thirty_days_ago = time.time() - 30 * 24 * 3600
    os.utime(token_file, (thirty_days_ago, thirty_days_ago))

    rows = _rows_by_name(pack.probe("mcp/health", "default", Context(fixtures_dir=str(tmp_path))))
    row = rows["google-calendar"]
    assert row["state"] == "broken"
    assert "refresh likely revoked" in row["detail"]


def test_expired_but_recently_touched_stays_unknown(tmp_path):
    """If expiry has passed but mtime is fresh, keep 'unknown' — refresh
    may have just succeeded and the next read could equally well succeed
    or fail. Don't claim broken without evidence."""
    import json
    import time

    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(json.dumps({
        "mcpServers": {
            "google-calendar": {
                "command": "node",
                "args": ["/x/google-calendar-mcp/build/index.js"],
            }
        }
    }))
    (tmp_path / "tokens").mkdir()
    token_file = tmp_path / "tokens" / "google-calendar.json"
    token_file.write_text(json.dumps({
        "access_token": "fake",
        "refresh_token": "fake",
        "expiry_date": int((time.time() - 60) * 1000),  # expired 1m ago
    }))
    # mtime stays at "now" (just-written file)

    rows = _rows_by_name(pack.probe("mcp/health", "default", Context(fixtures_dir=str(tmp_path))))
    assert rows["google-calendar"]["state"] == "unknown"


def test_missing_token_file_in_fixtures_marked_broken(tmp_path):
    """A google MCP whose token.json is absent should be reported broken."""
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(
        '{"mcpServers": {"google-calendar": {"command": "node", '
        '"args": ["/x/google-calendar-mcp/build/index.js"]}}}'
    )
    (tmp_path / "tokens").mkdir()
    # Deliberately do NOT create tokens/google-calendar.json
    ctx = Context(fixtures_dir=str(tmp_path))
    rows = _rows_by_name(pack.probe("mcp/health", "default", ctx))
    assert rows["google-calendar"]["state"] == "broken"
    assert "missing" in rows["google-calendar"]["detail"]


def test_missing_config_file_returns_status_with_error():
    """Live mode pointed at a non-existent config returns a graceful error."""
    ctx = Context(fixtures_dir=None)
    status = pack.probe("mcp/health", "/nonexistent/path/.claude.json", ctx)
    assert status.facts["total"] == 0
    assert status.error is not None
    assert "not found" in status.error
