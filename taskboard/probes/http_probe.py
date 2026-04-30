"""HTTP/HTTPS reachability probe.

Kind: http.
Ref:  any valid URL. A method prefix is allowed: "GET https://example.com".

Facts:
    status_code       (int)
    reachable         (bool)
    latency_ms        (int)
    content_length    (int | None)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from ..contract import Context, Status

KINDS = ["http"]
REF_SCHEMAS = {"http": "[METHOD ]<url>"}
SCRUB: dict[str, list[str]] = {"http": []}

_DEFAULT_TIMEOUT = 5.0


def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind != "http":
        raise ValueError(f"unknown kind: {kind}")

    method, url = _split(ref)
    timeout = float(ctx.config.get("timeout", _DEFAULT_TIMEOUT))
    checked = datetime.now(timezone.utc)
    started = time.monotonic()

    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            resp = client.request(method, url)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={
                "status_code":    resp.status_code,
                "reachable":      True,
                "latency_ms":     elapsed_ms,
                "content_length": _content_length(resp),
            },
            details={
                "url":            str(resp.request.url),
                "method":         method,
                "server":         resp.headers.get("server"),
                "content_type":   resp.headers.get("content-type"),
            },
            checked_at=checked,
        )
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Status(
            facts={"reachable": False, "latency_ms": elapsed_ms},
            details={"url": url, "method": method},
            checked_at=checked,
            error=f"{type(exc).__name__}: {exc}",
        )


def _split(ref: str) -> tuple[str, str]:
    parts = ref.split(None, 1)
    if len(parts) == 2 and parts[0].isalpha() and parts[0].upper() in _METHODS:
        return parts[0].upper(), parts[1]
    return "GET", ref


def _content_length(resp: httpx.Response) -> int | None:
    raw = resp.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


_METHODS = {"GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"}
