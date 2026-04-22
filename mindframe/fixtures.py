"""Fixture capture helpers.

A fixture is a raw API/CLI response stored next to a pack. The pack's probe()
is validated by running it against every fixture — if the parse succeeds and
produces well-formed Status, the pack matches reality.

Usage during pack development:

    from mindframe.fixtures import capture

    response = run_live_api_call(...)
    capture("repo-public", response, pack_dir=Path(__file__).parent,
            source_cmd="gh api repos/owner/name")

The capture writes two files:
    fixtures/<label>.json          — the raw response
    fixtures/<label>.meta.json     — capture timestamp, source command, scrub info
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def capture(
    label: str,
    response: Any,
    pack_dir: Path,
    source_cmd: str | None = None,
    api_version: str | None = None,
    scrub_paths: list[str] | None = None,
) -> Path:
    """Write response + metadata to <pack_dir>/fixtures/<label>.json.

    Returns the path to the fixture file.
    """
    fixtures_dir = pack_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    scrubbed = _scrub(response, scrub_paths or [])
    fixture_path = fixtures_dir / f"{label}.json"
    meta_path = fixtures_dir / f"{label}.meta.json"

    fixture_path.write_text(json.dumps(scrubbed, indent=2, sort_keys=True))
    meta_path.write_text(json.dumps({
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_cmd":  source_cmd,
        "api_version": api_version,
        "scrub_paths": scrub_paths or [],
    }, indent=2))
    return fixture_path


def _scrub(data: Any, paths: list[str]) -> Any:
    """Remove fields at top-level keys named in `paths`. Dotted paths not yet supported.

    Extend to handle nested paths once a pack needs it.
    """
    if not paths or not isinstance(data, (dict, list)):
        return data
    if isinstance(data, list):
        return [_scrub(item, paths) for item in data]
    scrubbed = {k: v for k, v in data.items() if k not in paths}
    return scrubbed
