"""Server factory.

Usage in a user's dashboard repo:

    from mindframe import serve
    from mindframe.packs.github import pack as gh_pack

    app = serve(
        systems_path="systems.json",
        packs={"gh": gh_pack, **BUILTIN_PACKS},
        poll_interval=30,
    )

`serve` returns a FastAPI app. Run with uvicorn:

    uvicorn dashboard:app --port 42069

Endpoints:
    GET  /                      — minimal HTML dashboard
    GET  /api/systems           — current state of all systems
    GET  /api/systems/{name}    — single system
    POST /api/systems/{name}/refresh  — force re-probe of one system
    GET  /healthz               — liveness

systems.json shape:
    {
      "systems": {
        "<name>": {
          "description": str,
          "url":         str (optional),
          "components": {
            "<cname>": {
              "kind":       str,               # e.g. "http", "gh/repo"
              "ref":        str,
              "config":     dict (optional),   # passed into Context.config
              "thresholds": dict (optional)    # per-fact rules
            }
          }
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .contract import Context, Status
from .probes import BUILTIN_PACKS
from .thresholds import derive_state

logger = logging.getLogger("mindframe")

DEFAULT_POLL_INTERVAL = 30


def serve(
    systems_path: str | Path,
    packs: dict[str, Any] | None = None,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    fixtures_dir: str | Path | None = None,
    include_builtins: bool = True,
    title: str = "Mindframe",
) -> FastAPI:
    """Build a FastAPI app that polls all components and serves their state.

    `packs` is a map from namespace -> module. A kind string "gh/repo" is routed
    to packs["gh"]. Built-in primitives (http/tcp/cmd/file) are registered by
    default when include_builtins is True — they use kind strings without a
    namespace prefix (e.g. kind="http").
    """
    systems_path = Path(systems_path)
    packs = dict(packs or {})
    if include_builtins:
        for name, mod in BUILTIN_PACKS.items():
            packs.setdefault(name, mod)

    state = _State(systems_path=systems_path, packs=packs, fixtures_dir=fixtures_dir)
    state.load_config()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        state.poll_task = asyncio.create_task(_poll_loop(state, poll_interval))
        try:
            yield
        finally:
            if state.poll_task:
                state.poll_task.cancel()
                try:
                    await state.poll_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "systems": len(state.config.get("systems", {}))}

    @app.get("/api/systems")
    async def api_systems() -> JSONResponse:
        return JSONResponse(_snapshot(state))

    @app.get("/api/systems/{name}")
    async def api_system(name: str) -> JSONResponse:
        snap = _snapshot(state)
        if name not in snap["systems"]:
            raise HTTPException(404, f"unknown system: {name}")
        return JSONResponse(snap["systems"][name])

    @app.post("/api/systems/{name}/refresh")
    async def api_refresh(name: str) -> JSONResponse:
        if name not in state.config.get("systems", {}):
            raise HTTPException(404, f"unknown system: {name}")
        await _probe_system(state, name, state.config["systems"][name])
        return JSONResponse(_system_snapshot(state, name))

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _render_html(title, _snapshot(state))

    app.state.mindframe = state
    return app


# ---------- internals ----------


class _State:
    def __init__(
        self,
        systems_path: Path,
        packs: dict[str, Any],
        fixtures_dir: str | Path | None,
    ) -> None:
        self.systems_path = systems_path
        self.packs = packs
        self.fixtures_dir = str(fixtures_dir) if fixtures_dir else None
        self.config: dict[str, Any] = {"systems": {}}
        self.results: dict[str, dict[str, dict[str, Any]]] = {}
        self.poll_task: asyncio.Task | None = None

    def load_config(self) -> None:
        if not self.systems_path.exists():
            raise FileNotFoundError(f"systems file not found: {self.systems_path}")
        self.config = json.loads(self.systems_path.read_text())
        if "systems" not in self.config:
            raise ValueError("systems.json must have a top-level 'systems' key")


async def _poll_loop(state: _State, interval: int) -> None:
    while True:
        try:
            await _probe_all(state)
        except Exception:
            logger.exception("probe cycle failed")
        await asyncio.sleep(interval)


async def _probe_all(state: _State) -> None:
    systems = state.config.get("systems", {})
    await asyncio.gather(*(
        _probe_system(state, name, cfg) for name, cfg in systems.items()
    ))


async def _probe_system(state: _State, name: str, cfg: dict[str, Any]) -> None:
    components = cfg.get("components", {})
    results = state.results.setdefault(name, {})

    async def run(cname: str, ccfg: dict[str, Any]) -> None:
        results[cname] = await asyncio.to_thread(
            _probe_one, state, ccfg,
        )

    await asyncio.gather(*(run(c, cfg_) for c, cfg_ in components.items()))


def _probe_one(state: _State, component_cfg: dict[str, Any]) -> dict[str, Any]:
    kind = component_cfg.get("kind")
    ref = component_cfg.get("ref", "")
    if not kind:
        return _error_result("component missing 'kind'")

    pack = _resolve_pack(state.packs, kind)
    if pack is None:
        return _error_result(f"no pack registered for kind: {kind}")

    ctx = Context(
        config=component_cfg.get("config", {}),
        fixtures_dir=state.fixtures_dir,
    )
    try:
        status: Status = pack.probe(kind, ref, ctx)
    except Exception as exc:
        return _error_result(f"{type(exc).__name__}: {exc}")

    state_label = derive_state(status, component_cfg.get("thresholds"))
    return {
        "state":      state_label,
        "facts":      status.facts,
        "details":    status.details,
        "error":      status.error,
        "checked_at": status.checked_at.isoformat() if status.checked_at else None,
        "kind":       kind,
        "ref":        ref,
    }


def _resolve_pack(packs: dict[str, Any], kind: str) -> Any | None:
    if "/" in kind:
        namespace = kind.split("/", 1)[0]
        return packs.get(namespace)
    return packs.get(kind)


def _error_result(msg: str) -> dict[str, Any]:
    return {
        "state":      "error",
        "facts":      {},
        "details":    {},
        "error":      msg,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "kind":       None,
        "ref":        None,
    }


def _snapshot(state: _State) -> dict[str, Any]:
    systems_out: dict[str, Any] = {}
    for name, cfg in state.config.get("systems", {}).items():
        systems_out[name] = _system_snapshot(state, name, cfg)
    return {"systems": systems_out, "snapshot_at": datetime.now(timezone.utc).isoformat()}


def _system_snapshot(
    state: _State,
    name: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg if cfg is not None else state.config["systems"][name]
    components_out = state.results.get(name, {})
    worst = _worst_state(components_out.values())
    return {
        "name":        name,
        "description": cfg.get("description"),
        "url":         cfg.get("url"),
        "state":       worst,
        "components":  components_out,
    }


def _worst_state(components: Any) -> str:
    order = {"healthy": 0, "warn": 1, "crit": 2, "error": 3}
    worst = "healthy"
    any_seen = False
    for comp in components:
        any_seen = True
        s = comp.get("state", "healthy")
        if order.get(s, 0) > order.get(worst, 0):
            worst = s
    return worst if any_seen else "unknown"


def _render_html(title: str, snap: dict[str, Any]) -> str:
    systems = snap.get("systems", {})
    rows = []
    for name, sys_ in systems.items():
        comp_rows = []
        for cname, comp in sys_.get("components", {}).items():
            badge = _badge(comp.get("state", "unknown"))
            error = comp.get("error")
            facts = comp.get("facts") or {}
            fact_snips = ", ".join(f"{k}={v}" for k, v in list(facts.items())[:4])
            extra = f" <span class='err'>{_escape(error)}</span>" if error else ""
            comp_rows.append(
                f"<tr><td>{_escape(cname)}</td><td>{badge}</td>"
                f"<td class='kind'>{_escape(comp.get('kind') or '')}</td>"
                f"<td class='facts'>{_escape(fact_snips)}{extra}</td></tr>"
            )
        rows.append(f"""
          <section class="system">
            <header>
              <h2>{_escape(name)} {_badge(sys_.get('state', 'unknown'))}</h2>
              <p>{_escape(sys_.get('description') or '')}</p>
            </header>
            <table>{''.join(comp_rows)}</table>
          </section>
        """)
    body = "".join(rows) if rows else "<p>No systems configured.</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_escape(title)}</title>
<style>
 body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem; background:#0b0d10; color:#e6e6e6; }}
 h1 {{ font-weight: 500; }}
 section.system {{ margin-bottom: 2rem; background:#14181d; padding:1rem 1.25rem; border-radius:6px; }}
 section.system header h2 {{ margin: 0; font-size: 1.2rem; }}
 section.system header p {{ margin: .25rem 0 .75rem; color:#9aa4af; font-size:.9rem; }}
 table {{ width: 100%; border-collapse: collapse; }}
 td {{ padding: .35rem .5rem; border-top: 1px solid #22272d; font-size: .9rem; vertical-align: top; }}
 .kind {{ color:#9aa4af; font-family: JetBrains Mono, Menlo, monospace; font-size:.8rem; }}
 .facts {{ color:#c5cdd5; font-family: JetBrains Mono, Menlo, monospace; font-size:.8rem; }}
 .badge {{ display:inline-block; padding: 1px 8px; border-radius:999px; font-size:.7rem; margin-left:.5rem; text-transform:uppercase; letter-spacing:.04em; }}
 .badge.healthy {{ background:#124a2b; color:#6bd99b; }}
 .badge.warn    {{ background:#5b4412; color:#f6c14b; }}
 .badge.crit    {{ background:#631d1d; color:#f19a9a; }}
 .badge.error   {{ background:#3a2b63; color:#c5b3ff; }}
 .badge.unknown {{ background:#2a2f35; color:#9aa4af; }}
 .err {{ color:#f19a9a; }}
</style></head>
<body>
<h1>{_escape(title)}</h1>
<p style="color:#9aa4af; font-size:.85rem">snapshot: {_escape(snap.get('snapshot_at') or '')}</p>
{body}
</body></html>"""


def _badge(state: str) -> str:
    cls = state if state in ("healthy", "warn", "crit", "error", "unknown") else "unknown"
    return f"<span class='badge {cls}'>{cls}</span>"


def _escape(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;")
              .replace(">", "&gt;").replace('"', "&quot;")
    )


__all__ = ["serve", "Status", "Context"]
