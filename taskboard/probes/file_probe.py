"""File existence + age probe.

Kind: file.
Ref:  absolute path to a file. Tilde is expanded.

Facts:
    exists          (bool)
    size_bytes      (int | None)
    age_seconds     (int | None)   — wall-clock seconds since mtime
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from ..contract import Context, Status

KINDS = ["file"]
REF_SCHEMAS = {"file": "<absolute-path>"}
SCRUB: dict[str, list[str]] = {"file": []}


def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind != "file":
        raise ValueError(f"unknown kind: {kind}")
    path = Path(ref).expanduser()
    checked = datetime.now(timezone.utc)

    if not path.exists():
        return Status(
            facts={"exists": False, "size_bytes": None, "age_seconds": None},
            details={"path": str(path)},
            checked_at=checked,
        )
    try:
        stat = path.stat()
    except OSError as exc:
        return Status(
            facts={"exists": True},
            details={"path": str(path)},
            checked_at=checked,
            error=f"{type(exc).__name__}: {exc}",
        )
    return Status(
        facts={
            "exists":      True,
            "size_bytes":  stat.st_size,
            "age_seconds": int(time.time() - stat.st_mtime),
        },
        details={"path": str(path), "mtime": stat.st_mtime},
        checked_at=checked,
    )
