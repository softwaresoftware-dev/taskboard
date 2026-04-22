"""Command execution probe.

Kind: cmd.
Ref:  the command to run. Executed with shell=False; split on whitespace.
      Use ctx.config["shell"] = True to run via the user's shell (dangerous;
      escape-hatch only).

Facts:
    exit_code    (int)
    ok           (bool)  — True when exit_code == 0
    duration_ms  (int)
"""
from __future__ import annotations

import shlex
import subprocess
import time
from datetime import datetime, timezone

from ..contract import Context, Status

KINDS = ["cmd"]
REF_SCHEMAS = {"cmd": "<command with args>"}
SCRUB: dict[str, list[str]] = {"cmd": []}

_DEFAULT_TIMEOUT = 10.0
_MAX_OUTPUT = 8 * 1024


def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind != "cmd":
        raise ValueError(f"unknown kind: {kind}")
    use_shell = bool(ctx.config.get("shell", False))
    timeout = float(ctx.config.get("timeout", _DEFAULT_TIMEOUT))
    argv: list[str] | str = ref if use_shell else shlex.split(ref)

    checked = datetime.now(timezone.utc)
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv, shell=use_shell, capture_output=True, text=True, timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={
                "exit_code":   result.returncode,
                "ok":          result.returncode == 0,
                "duration_ms": elapsed_ms,
            },
            details={
                "stdout": _truncate(result.stdout),
                "stderr": _truncate(result.stderr),
            },
            checked_at=checked,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={"ok": False, "duration_ms": elapsed_ms},
            details={},
            checked_at=checked,
            error=f"timeout after {timeout}s",
        )
    except (OSError, ValueError) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={"ok": False, "duration_ms": elapsed_ms},
            details={},
            checked_at=checked,
            error=f"{type(exc).__name__}: {exc}",
        )


def _truncate(s: str) -> str:
    if len(s) <= _MAX_OUTPUT:
        return s
    return s[:_MAX_OUTPUT] + f"... [truncated, {len(s) - _MAX_OUTPUT} more bytes]"
