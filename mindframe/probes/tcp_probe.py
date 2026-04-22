"""TCP reachability probe.

Kind: tcp.
Ref:  "host:port".

Facts:
    reachable    (bool)
    latency_ms   (int)
"""
from __future__ import annotations

import socket
import time
from datetime import datetime, timezone

from ..contract import Context, Status

KINDS = ["tcp"]
REF_SCHEMAS = {"tcp": "<host>:<port>"}
SCRUB: dict[str, list[str]] = {"tcp": []}

_DEFAULT_TIMEOUT = 3.0


def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind != "tcp":
        raise ValueError(f"unknown kind: {kind}")
    host, port = _parse(ref)
    timeout = float(ctx.config.get("timeout", _DEFAULT_TIMEOUT))
    checked = datetime.now(timezone.utc)
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={"reachable": True, "latency_ms": elapsed_ms},
            details={"host": host, "port": port},
            checked_at=checked,
        )
    except OSError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={"reachable": False, "latency_ms": elapsed_ms},
            details={"host": host, "port": port},
            checked_at=checked,
            error=f"{type(exc).__name__}: {exc}",
        )


def _parse(ref: str) -> tuple[str, int]:
    if ":" not in ref:
        raise ValueError(f"tcp ref must be host:port, got: {ref!r}")
    host, _, port_str = ref.rpartition(":")
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"tcp ref port not an int: {ref!r}") from exc
    return host, port
