"""MCP health source pack.

Reports credential health for configured MCP servers. v1 is artifact-only:
inspects token files / env presence without calling upstream APIs, so
"state=ok" here means "stored credentials look usable", not "verified
against the live service". Live verification (a refresh-token round-trip
to Google, an auth.test call to Slack) is a follow-up.

Why bother without live verification? When something breaks, the dashboard
needs to make the broken state legible. "gmail-organizer: token last
touched 6 days ago, refresh_token present" is enough signal for the user
to know whether to re-auth, even if the artifact doesn't tell us
definitively that Google has revoked the refresh token.

Kinds: mcp/health
Ref:   "default" (read ~/.claude.json) | path to a JSON with mcpServers shape
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from taskboard.contract import Column, Context, Status, Table


KINDS = ["mcp/health"]

REF_SCHEMAS = {
    "mcp/health": "default | <path-to-mcp-config-json>",
}

# `env` may contain bot tokens, API keys, etc. — never echo it to the UI.
SCRUB = {
    "mcp/health": ["env", "command_path", "args"],
}


_GOOGLE_PATTERNS = ("gmail-mcp", "google-calendar", "google-drive", "gmail-organizer")

# How long an OAuth token can stay expired-and-untouched before we promote
# from "unknown" to "broken". The token.json mtime tracks the last
# successful refresh: googleapis writes it after a refresh round-trip
# succeeds. If the access token is past expiry AND the file hasn't been
# rewritten in this many days, the most likely explanation is the refresh
# token was revoked (or the user hasn't invoked this MCP in a long time —
# we tell them so in the detail string).
_STALE_DAYS_FOR_BROKEN = 7


def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")

    checked = datetime.now(timezone.utc)
    config_path = _resolve_config_path(ref, ctx)

    if not config_path.exists():
        return Status(
            facts={"total": 0, "ok": 0, "broken": 0, "unknown": 0},
            checked_at=checked,
            error=f"mcp config not found at {config_path}",
        )

    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return Status(
            facts={"total": 0, "ok": 0, "broken": 0, "unknown": 0},
            checked_at=checked,
            error=f"mcp config unreadable: {e}",
        )

    servers = config.get("mcpServers", {})
    rows: list[dict[str, Any]] = []
    counts = {"ok": 0, "broken": 0, "unknown": 0}

    for name, spec in sorted(servers.items()):
        result = _classify_and_probe(name, spec, checked, ctx)
        counts[result["state"]] = counts.get(result["state"], 0) + 1
        rows.append({
            "name":      name,
            "family":    result["family"],
            "state":     result["state"],
            "detail":    result["detail"],
            "last_seen": result["last_seen"] or "—",
        })

    table = Table(
        columns=[
            Column(key="name",      label="MCP"),
            Column(key="family",    label="Family"),
            Column(key="state",     label="State",      cell_kind="badge"),
            Column(key="detail",    label="Detail"),
            Column(key="last_seen", label="Token touched"),
        ],
        rows=rows,
    )

    return Status(
        facts={
            "total":   len(servers),
            "ok":      counts["ok"],
            "broken":  counts["broken"],
            "unknown": counts["unknown"],
        },
        details={"servers": [r["name"] for r in rows]},
        checked_at=checked,
        view=table,
    )


# --- helpers ---


def _resolve_config_path(ref: str, ctx: Context) -> Path:
    if ctx.fixtures_dir:
        return Path(ctx.fixtures_dir) / "mcp_config.json"
    if ref in ("", "default"):
        return Path.home() / ".claude.json"
    return Path(ref).expanduser()


def _classify_and_probe(name: str, spec: dict, now: datetime, ctx: Context) -> dict:
    cmd_parts = [spec.get("command") or ""] + (spec.get("args") or [])
    cmd = " ".join(cmd_parts)
    lname = name.lower()

    if any(p in lname or p in cmd for p in _GOOGLE_PATTERNS):
        return _probe_google(name, cmd, now, ctx)

    if "slack" in lname:
        return _probe_slack(spec)

    return {
        "family":    "unknown",
        "state":     "unknown",
        "detail":    "no probe registered for this MCP family",
        "last_seen": None,
    }


def _probe_google(name: str, cmd: str, now: datetime, ctx: Context) -> dict:
    """Inspect the OAuth token.json that the Google MCPs persist."""
    token_path = _find_google_token(name, cmd, ctx)
    if token_path is None:
        return {
            "family": "google_oauth", "state": "unknown",
            "detail": "could not locate token.json from MCP command",
            "last_seen": None,
        }
    if not token_path.exists():
        return {
            "family": "google_oauth", "state": "broken",
            "detail": f"token.json missing at {token_path} — run `npm run auth`",
            "last_seen": None,
        }

    try:
        token = json.loads(token_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {
            "family": "google_oauth", "state": "broken",
            "detail": f"token.json unreadable: {e}",
            "last_seen": None,
        }

    last_seen = _ts(token_path.stat().st_mtime)

    if not token.get("refresh_token"):
        return {
            "family": "google_oauth", "state": "broken",
            "detail": "no refresh_token in token.json — re-auth required",
            "last_seen": last_seen,
        }

    expiry_raw = token.get("expiry_date") or token.get("expiry")
    if expiry_raw is None:
        return {
            "family": "google_oauth", "state": "unknown",
            "detail": "no expiry recorded; cannot judge from artifact alone",
            "last_seen": last_seen,
        }

    expiry = _parse_expiry(expiry_raw)
    mtime = datetime.fromtimestamp(token_path.stat().st_mtime, tz=timezone.utc)
    age_days = (now - mtime).days

    if now > expiry:
        if age_days >= _STALE_DAYS_FOR_BROKEN:
            return {
                "family": "google_oauth", "state": "broken",
                "detail": (
                    f"expired {(now - expiry).days}d ago and token file untouched "
                    f"for {age_days}d — refresh likely revoked. Re-auth required, "
                    f"unless this MCP just hasn't been used recently."
                ),
                "last_seen": last_seen,
            }
        return {
            "family": "google_oauth", "state": "unknown",
            "detail": f"access token expired {(now - expiry).days}d ago — refresh may or may not still work",
            "last_seen": last_seen,
        }

    hours_left = (expiry - now).total_seconds() / 3600
    return {
        "family": "google_oauth", "state": "ok",
        "detail": f"access token valid for {hours_left:.1f}h",
        "last_seen": last_seen,
    }


def _find_google_token(name: str, cmd: str, ctx: Context) -> Path | None:
    if ctx.fixtures_dir:
        return Path(ctx.fixtures_dir) / "tokens" / f"{name}.json"
    # Live mode: token.json sits next to the MCP entry script. Match the
    # MCP directory from the command path: .../<name>-mcp/build/index.js
    m = re.search(r"(/[^\s]+?-mcp(?:-organizer)?)/", cmd)
    if not m:
        return None
    return Path(m.group(1)) / "token.json"


def _probe_slack(spec: dict) -> dict:
    env = spec.get("env") or {}
    token = env.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return {
            "family": "slack", "state": "broken",
            "detail": "no SLACK_BOT_TOKEN in mcpServers env or process env",
            "last_seen": None,
        }
    return {
        "family": "slack", "state": "unknown",
        "detail": "token present; live verification requires API call (v2)",
        "last_seen": None,
    }


def _parse_expiry(raw: Any) -> datetime:
    """Google MCPs store expiry in two shapes; accept either.

    google-calendar-mcp uses ms-since-epoch under `expiry_date`; some
    other libraries use ISO strings under `expiry`.
    """
    if isinstance(raw, (int, float)):
        secs = raw / 1000 if raw > 1e12 else raw
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    raise ValueError(f"unrecognized expiry shape: {type(raw).__name__}")


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")
