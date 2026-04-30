"""GitHub source pack.

Fixture-only for now. Live mode (via `gh` CLI or REST with a PAT) is the
next layer and will consume Context more richly.

Kinds supported: gh/repo, gh/pull-requests, gh/releases.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from taskboard.contract import Column, Context, Status, Table


KINDS = ["gh/repo", "gh/pull-requests", "gh/releases"]

REF_SCHEMAS = {
    "gh/repo":          "{owner}/{repo}",
    "gh/pull-requests": "{owner}/{repo}",
    "gh/releases":      "{owner}/{repo}",
}

# Sensitivity varies by endpoint. Driven per-kind.
SCRUB = {
    "gh/repo":          ["permissions", "temp_clone_token"],
    "gh/pull-requests": [],
    "gh/releases":      [],
}

_FIXTURE_FILE = {
    "gh/repo":          "repo.json",
    "gh/pull-requests": "prs-open.json",
    "gh/releases":      "releases.json",
}


def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if ctx.fixtures_dir is None:
        raise NotImplementedError("live mode not yet implemented; pass ctx.fixtures_dir")

    data = _load_fixture(ctx.fixtures_dir, kind)
    checked = datetime.now(timezone.utc)

    if kind == "gh/repo":
        return _parse_repo(data, checked)
    if kind == "gh/pull-requests":
        return _parse_prs(data, checked)
    if kind == "gh/releases":
        return _parse_releases(data, checked)
    raise AssertionError("unreachable")


def _load_fixture(dir_path: str, kind: str) -> Any:
    path = Path(dir_path) / _FIXTURE_FILE[kind]
    return json.loads(path.read_text())


def _parse_repo(data: dict, checked: datetime) -> Status:
    pushed = _parse_ts(data["pushed_at"])
    return Status(
        facts={
            "pushed_days_ago": (checked - pushed).days,
            "open_issues":     data["open_issues_count"],
            "archived":        data["archived"],
            "disabled":        data["disabled"],
            "private":         data["private"],
        },
        details={
            "name":           data["full_name"],
            "description":    data["description"],
            "default_branch": data["default_branch"],
            "pushed_at":      data["pushed_at"],
            "html_url":       data["html_url"],
            "topics":         data.get("topics", []),
        },
        checked_at=checked,
    )


def _parse_prs(data: list, checked: datetime) -> Status:
    oldest_age_days: int | None = None
    if data:
        oldest = min(_parse_ts(pr["created_at"]) for pr in data)
        oldest_age_days = (checked - oldest).days
    table = Table(
        columns=[
            Column(key="number",  label="#",       cell_kind="code"),
            Column(key="title",   label="Title",   cell_kind="link"),
            Column(key="author",  label="Author",  cell_kind="text"),
            Column(key="age",     label="Age",     cell_kind="timestamp"),
        ],
        rows=[
            {
                "number": f"#{pr['number']}",
                "title":  {"href": pr["html_url"], "text": pr["title"]},
                "author": (pr.get("user") or {}).get("login") or "—",
                "age":    pr["created_at"],
            }
            for pr in data
        ],
    )
    return Status(
        facts={
            "count":           len(data),
            "oldest_age_days": oldest_age_days,
        },
        details={
            "prs": [
                {"number": pr["number"], "title": pr["title"], "url": pr["html_url"]}
                for pr in data
            ],
        },
        checked_at=checked,
        view=table,
    )


def _parse_releases(data: list, checked: datetime) -> Status:
    latest_age_days: int | None = None
    latest_tag: str | None = None
    if data:
        published = [_parse_ts(r["published_at"]) for r in data if r.get("published_at")]
        if published:
            latest_age_days = (checked - max(published)).days
        latest_tag = data[0].get("tag_name")
    return Status(
        facts={
            "count":           len(data),
            "latest_age_days": latest_age_days,
        },
        details={"latest_tag": latest_tag},
        checked_at=checked,
    )


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
