"""HTML rendering for taskboard snapshots.

A component snapshot may carry a `view` payload (one of: stat, table, chart,
feed). When present, the framework renders the rich view. When absent, falls
back to a compact facts-row.

Cell renderers for tables:
    text | code | link | badge | tags | progress | sparkline | timestamp |
    actions | multiline
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


_STATE_CLASSES = ("healthy", "warn", "crit", "error", "unknown")
_ACCENTS = ("ok", "warn", "crit", "info", "muted")


def render_html(title: str, snap: dict[str, Any]) -> str:
    systems = snap.get("systems", {})
    blocks: list[str] = []
    for name, sys_ in systems.items():
        blocks.append(_render_system(name, sys_))
    body = "".join(blocks) if blocks else "<p class='empty'>No systems configured.</p>"
    return _PAGE.format(
        title=_esc(title),
        snapshot_at=_esc(snap.get("snapshot_at") or ""),
        body=body,
        css=_CSS,
        init_js=_INIT_JS,
    )


# ---------- system + dispatch ----------


def _render_system(name: str, sys_: dict[str, Any]) -> str:
    components = sys_.get("components", {})
    single = len(components) == 1
    parts: list[str] = []
    for cname, comp in components.items():
        parts.append(_render_component(cname, comp, hide_head=single, system=name))
    desc = sys_.get("description") or ""
    url = sys_.get("url")
    title = f"<a href='{_esc(url)}' target='_blank'>{_esc(name)}</a>" if url else _esc(name)
    return (
        f"<section class='system'>"
        f"<header><h2>{title} {_badge(sys_.get('state', 'unknown'))}</h2>"
        f"<p>{_esc(desc)}</p></header>"
        f"<div class='components'>{''.join(parts)}</div>"
        f"</section>"
    )


def _render_component(cname: str, comp: dict[str, Any], hide_head: bool = False, system: str = "") -> str:
    view = comp.get("view")
    view_kind = (view or {}).get("kind") if view else "facts"
    head = "" if hide_head else (
        f"<div class='component-head' title='{_esc(comp.get('kind') or '')}'>"
        f"<div class='cname'>{_esc(cname)}</div>"
        f"{_badge(comp.get('state', 'unknown'))}"
        f"</div>"
    )
    if comp.get("error"):
        body = f"<div class='err'>{_esc(comp['error'])}</div>"
    elif view is None:
        body = _render_facts(comp.get("facts") or {})
    else:
        body = _render_view(view)
    return (
        f"<div class='component' data-view='{_esc(view_kind)}' "
        f"data-system='{_esc(system)}' data-component='{_esc(cname)}'>"
        f"{head}{body}</div>"
    )


def _render_view(view: dict[str, Any]) -> str:
    kind = view.get("kind")
    if kind == "stat":
        return _render_stat(view)
    if kind == "table":
        return _render_table(view)
    if kind == "chart":
        return _render_chart(view)
    if kind == "feed":
        return _render_feed(view)
    return f"<div class='err'>unknown view kind: {_esc(kind)}</div>"


# ---------- facts (default fallback) ----------


def _render_facts(facts: dict[str, Any]) -> str:
    if not facts:
        return "<div class='facts empty'>—</div>"
    items = "".join(
        f"<span class='fact'><span class='k'>{_esc(k)}</span>"
        f"<span class='v'>{_esc(v)}</span></span>"
        for k, v in facts.items()
    )
    return f"<div class='facts'>{items}</div>"


# ---------- stat ----------


def _render_stat(v: dict[str, Any]) -> str:
    accent = _accent(v.get("accent"))
    trend = v.get("trend") or []
    detail = v.get("detail")
    detail_html = f"<div class='detail'>{_esc(detail)}</div>" if detail else ""
    spark_html = ""
    if trend:
        floats = [float(y) for y in trend]
        mx = max(floats) or 1.0
        spark_html = (
            f"<div class='spark-meta'><span class='spark-peak'>peak {_esc(_fmt_num(mx))}</span></div>"
            f"{_sparkline(floats)}"
        )
    return (
        f"<div class='stat-card {accent}'>"
        f"<div class='label'>{_esc(v.get('label') or '')}</div>"
        f"<div class='value'>{_esc(v.get('value'))}</div>"
        f"{detail_html}"
        f"{spark_html}"
        f"</div>"
    )


# ---------- table ----------


def _render_table(v: dict[str, Any]) -> str:
    columns = v.get("columns") or []
    rows = v.get("rows") or []
    actions = v.get("actions") or []
    filters = v.get("filters") or []
    groups = v.get("groups") or []

    filter_html = _render_filters(filters) if filters else ""
    if not rows:
        return f"{filter_html}<div class='facts empty'>no data</div>"

    if groups:
        return filter_html + _render_grouped_table(columns, rows, actions, groups, filters)

    head = "<tr>" + "".join(
        f"<th class='col-{_esc(c.get('cell_kind') or 'text')}'>{_esc(c.get('label') or c.get('key'))}</th>"
        for c in columns
    ) + "</tr>"
    body_rows = "".join(_render_row(columns, r, actions, filters) for r in rows)
    return (
        f"{filter_html}"
        f"<table class='view-table' data-filterable='1'>"
        f"<thead>{head}</thead>"
        f"<tbody>{body_rows}</tbody>"
        f"</table>"
    )


def _render_grouped_table(columns, rows, actions, groups, filters=None) -> str:
    filters = filters or []
    by_key = {g["key"]: g for g in groups}
    grouped: dict[str, list[dict[str, Any]]] = {g["key"]: [] for g in groups}
    grouped["__other__"] = []
    for row in rows:
        gk = row.get("__group__") or "__other__"
        grouped.setdefault(gk, []).append(row)
    parts: list[str] = []
    head = "<tr>" + "".join(
        f"<th class='col-{_esc(c.get('cell_kind') or 'text')}'>{_esc(c.get('label') or c.get('key'))}</th>"
        for c in columns
    ) + "</tr>"
    for gk, items in grouped.items():
        if not items:
            continue
        meta = by_key.get(gk)
        gtitle = meta["label"] if meta else gk
        gbadge = f"<span class='gbadge'>{_esc(meta['badge'])}</span>" if meta and meta.get("badge") else ""
        body = "".join(_render_row(columns, r, actions, filters) for r in items)
        parts.append(
            f"<div class='group'>"
            f"<div class='group-head'>{_esc(gtitle)} {gbadge}</div>"
            f"<table class='view-table' data-filterable='1'><thead>{head}</thead><tbody>{body}</tbody></table>"
            f"</div>"
        )
    return "".join(parts)


def _render_row(columns, row, actions, filters=None) -> str:
    cells: list[str] = []
    for col in columns:
        key = col["key"]
        kind = col.get("cell_kind") or "text"
        cells.append(_render_cell(kind, row.get(key), row, actions))
    # Emit data-{filter_id} attributes so JS can filter without re-fetching.
    filter_attrs = ""
    if filters:
        for f in filters:
            fid = f.get("id")
            if not fid or f.get("kind") == "text":
                continue
            val = row.get(fid)
            if isinstance(val, dict):
                val = val.get("text") or val.get("value") or ""
            if val is None:
                val = ""
            filter_attrs += f" data-{_esc(fid)}='{_esc(val)}'"
    return f"<tr{filter_attrs}>" + "".join(cells) + "</tr>"


def _render_cell(kind: str, value: Any, row: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    if kind == "text":
        return f"<td>{_esc(value)}</td>"
    if kind == "code":
        return f"<td class='code'>{_esc(value)}</td>"
    if kind == "link":
        if isinstance(value, dict):
            href = value.get("href") or value.get("url") or ""
            text = value.get("text") or value.get("label") or href
        else:
            href = text = value or ""
        return f"<td class='link'><a href='{_esc(href)}' target='_blank'>{_esc(text)}</a></td>"
    if kind == "badge":
        if isinstance(value, dict):
            text = value.get("text") or ""
            accent = _accent(value.get("accent"))
        else:
            text = value or ""
            accent = _accent(None)
        return f"<td><span class='cell-badge {accent}'>{_esc(text)}</span></td>"
    if kind == "tags":
        items = value or []
        if not isinstance(items, list):
            items = [items]
        tags = "".join(f"<span class='cell-tag'>{_esc(t)}</span>" for t in items)
        return f"<td class='tags'>{tags}</td>"
    if kind == "progress":
        if isinstance(value, dict):
            cur = float(value.get("value") or 0)
            mx = float(value.get("max") or 100)
            label = value.get("label")
        else:
            cur = float(value or 0)
            mx = 100.0
            label = None
        pct = max(0.0, min(100.0, (cur / mx * 100.0) if mx else 0.0))
        accent = "ok" if pct < 70 else ("warn" if pct < 90 else "crit")
        label_html = f"<span class='progress-label'>{_esc(label)}</span>" if label else ""
        return (
            f"<td class='progress'>"
            f"<div class='bar'><div class='fill {accent}' style='width:{pct:.1f}%'></div></div>"
            f"{label_html}"
            f"</td>"
        )
    if kind == "sparkline":
        return f"<td>{_sparkline(value or [])}</td>"
    if kind == "timestamp":
        return f"<td class='ts'>{_esc(_ago(value))}</td>"
    if kind == "actions":
        ids = value or []
        if not isinstance(ids, list):
            ids = [ids]
        by_id = {a["id"]: a for a in actions}
        # Use the row's `id` field if present, else the first non-dict cell value
        # (typically the row's name/service/repo column). This is the row_id
        # the pack's act() receives.
        row_id = row.get("id")
        if row_id is None:
            for v in row.values():
                if isinstance(v, (str, int, float)) and v != "":
                    row_id = v
                    break
        row_attr = f" data-row-id='{_esc(row_id)}'" if row_id is not None else ""
        btns: list[str] = []
        for aid in ids:
            a = by_id.get(aid)
            if not a:
                continue
            confirm_attr = " data-confirm='1'" if a.get("confirm") else ""
            style_attr = f" data-style='{_esc(a['style'])}'" if a.get("style") else ""
            btns.append(
                f"<button class='act{' destructive' if a.get('confirm') else ''}' "
                f"data-action='{_esc(aid)}'{row_attr}{confirm_attr}{style_attr}>"
                f"{_esc(a.get('label') or aid)}</button>"
            )
        return f"<td class='actions'>{''.join(btns)}</td>"
    if kind == "multiline":
        if not isinstance(value, dict):
            return f"<td>{_esc(value)}</td>"
        title = value.get("title") or ""
        lines = value.get("lines") or []
        body = "".join(f"<div class='ml-line'>{_esc(line)}</div>" for line in lines)
        return f"<td class='multiline'><div class='ml-title'>{_esc(title)}</div>{body}</td>"
    return f"<td>{_esc(value)}</td>"


def _render_filters(filters: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for f in filters:
        if f.get("kind") == "text":
            parts.append(f"<input class='filter-text' placeholder='{_esc(f.get('label') or '')}…' />")
        else:
            opts = f.get("options") or []
            pills = "".join(
                f"<button class='pill' data-filter='{_esc(f['id'])}' "
                f"data-value='{_esc(o.get('value'))}'>{_esc(o.get('label') or o.get('value'))}</button>"
                for o in opts
            )
            parts.append(f"<div class='pills'>{pills}</div>")
    return f"<div class='filters'>{''.join(parts)}</div>"


# ---------- chart ----------


def _render_chart(v: dict[str, Any]) -> str:
    chart_kind = v.get("chart_kind") or "bar"
    points = v.get("points") or []
    period = v.get("period")
    if chart_kind == "sparkline":
        ys = [float(p.get("y") or 0) for p in points]
        period_html = f"<div class='label'>{_esc(period)}</div>" if period else ""
        return f"<div class='chart'>{period_html}{_sparkline(ys)}</div>"
    if not points:
        return "<div class='chart facts empty'>no data</div>"
    ys = [float(p.get("y") or 0) for p in points]
    mx = max(ys) or 1.0
    total = sum(ys)
    label_html = f"<div class='label'>Σ {_fmt_num(total)}</div>"
    value_html = f"<div class='value'>{_esc(_fmt_num(mx))}<span class='value-suffix'>peak</span></div>"
    detail_html = f"<div class='detail'>{_esc(period)}</div>" if period else ""

    # Data payload for uPlot — JSON-encoded into a data-* attribute.
    # Also serialize for the <noscript> fallback (no JS = current CSS bars).
    payload = {
        "kind":   chart_kind,
        "points": [{"x": p.get("label") or p.get("x"), "y": float(p.get("y") or 0)} for p in points],
    }
    payload_json = _esc(json.dumps(payload, default=str))

    bars = "".join(
        f"<div class='bar-item' "
        f"data-x='{_esc(p.get('label') or p.get('x'))}' "
        f"data-y='{_esc(p.get('y'))}' "
        f"style='height:{(float(p.get('y') or 0) / mx * 100):.1f}%'></div>"
        for p in points
    )
    first_x = _esc(points[0].get("label") or points[0].get("x") or "")
    last_x = _esc(points[-1].get("label") or points[-1].get("x") or "")
    fallback = (
        f"<noscript>"
        f"<div class='chart-plot'>"
        f"<div class='chart-yaxis'><span>{_fmt_num(mx)}</span><span>0</span></div>"
        f"<div class='bars-row'>{bars}</div>"
        f"</div>"
        f"<div class='chart-xaxis'><span>{first_x}</span><span>{last_x}</span></div>"
        f"</noscript>"
    )

    return (
        f"<div class='chart bars'>{label_html}{value_html}{detail_html}"
        f"<div class='uplot-host' data-points='{payload_json}'></div>"
        f"{fallback}"
        f"</div>"
    )


def _fmt_num(n: float) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k".replace(".0k", "k")
    if n == int(n):
        return str(int(n))
    return f"{n:.1f}"


# ---------- feed ----------


def _render_feed(v: dict[str, Any]) -> str:
    items = v.get("items") or []
    if not items:
        return "<div class='facts empty'>no events</div>"
    rows = []
    for it in items:
        accent = _accent(it.get("accent"))
        ts = _ago(it.get("ts"))
        title = it.get("title") or ""
        body = it.get("body")
        body_html = f"<div class='feed-body'>{_esc(body)}</div>" if body else ""
        rows.append(
            f"<li class='feed-item {accent}'>"
            f"<span class='feed-ts'>{_esc(ts)}</span>"
            f"<span class='feed-stripe' aria-hidden='true'></span>"
            f"<div class='feed-main'>"
            f"<div class='feed-title'>{_esc(title)}</div>"
            f"{body_html}"
            f"</div></li>"
        )
    return f"<ul class='feed'>{''.join(rows)}</ul>"


# ---------- helpers ----------


def _badge(state: str) -> str:
    cls = state if state in _STATE_CLASSES else "unknown"
    return f"<span class='badge {cls}'>{cls}</span>"


def _accent(a: Any) -> str:
    if a in _ACCENTS:
        return a
    return "muted"


def _sparkline(ys: list[float], xs: list[Any] | None = None) -> str:
    """Mini uPlot chart for stat tiles. Same visual language as main charts."""
    if not ys:
        return ""
    points = []
    for i, y in enumerate(ys):
        x = xs[i] if xs and i < len(xs) else i
        points.append({"x": x, "y": float(y)})
    payload = {"kind": "spark", "points": points}
    return (
        f"<div class='uplot-host spark' data-points='{_esc(json.dumps(payload, default=str))}'></div>"
    )


def _ago(iso: Any) -> str:
    if not iso:
        return ""
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    now = datetime.now(timezone.utc) if ts.tzinfo else datetime.now()
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;")
              .replace(">", "&gt;").replace('"', "&quot;")
    )


# ---------- styles + page shell ----------


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<link rel="stylesheet" href="/static/uPlot.min.css">
<style>{css}</style></head>
<body>
<header class='top'>
  <h1>{title}</h1>
  <p class='muted'>snapshot: {snapshot_at}</p>
</header>
{body}
<script src="/static/uPlot.iife.min.js"></script>
<script>{init_js}</script>
</body></html>"""


_CSS = """
:root {
  --bg: #0b0d10; --bg2: #14181d; --surface: #1a1f25;
  --text: #e6e6e6; --text3: #9aa4af; --border: #22272d;
  --ok: #6bd99b; --warn: #f6c14b; --crit: #f19a9a; --info: #c5b3ff; --accent: #d6b46f;
  --ok-bg: #124a2b; --warn-bg: #5b4412; --crit-bg: #631d1d; --info-bg: #3a2b63; --muted-bg: #2a2f35;
}
* { box-sizing: border-box; }
html, body { background: var(--bg); }
body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 1.75rem clamp(1rem, 4vw, 2.5rem) 3rem; color: var(--text); max-width: 1600px; margin-inline: auto; }
.top { margin-bottom: 1.75rem; }
.top h1 { font-weight: 700; font-size: 1.85rem; letter-spacing: -.02em; margin: 0 0 .4rem; }
.top .muted { color: var(--text3); font-family: ui-monospace, Menlo, monospace; font-size: .68rem; margin: 0; letter-spacing: .04em; text-transform: uppercase; }
section.system { margin-bottom: 1.25rem; background: var(--bg2); padding: 1.1rem 1.25rem 1.25rem; border-radius: 10px; border: 1px solid var(--border); }
section.system header { display: flex; align-items: baseline; flex-wrap: wrap; gap: .65rem; margin-bottom: .9rem; }
section.system header h2 { margin: 0; font-size: 1.05rem; font-weight: 600; letter-spacing: -.005em; }
section.system header h2 a { color: var(--text); text-decoration: none; border-bottom: 1px dotted var(--text3); }
section.system header p { margin: 0; color: var(--text3); font-size: .82rem; }
.components { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); grid-auto-flow: dense; gap: .75rem; align-items: stretch; }
.component { background: var(--surface); border-radius: 8px; padding: .85rem 1rem; display: flex; flex-direction: column; min-width: 0; box-shadow: inset 0 0 0 1px rgba(255,255,255,.02); }
.component[data-view="table"], .component[data-view="feed"], .component[data-view="facts"] { align-self: start; }
.component[data-view="table"] { padding: .85rem 1.1rem 1rem; }
.component[data-view="table"] { grid-column: 1 / -1; }
.component[data-view="chart"] { grid-column: span 3; }
.component[data-view="feed"]  { grid-column: 1 / -1; }
@media (max-width: 720px) {
  .component[data-view="chart"], .component[data-view="feed"] { grid-column: 1 / -1; }
}
.component-head { display: flex; align-items: center; gap: .5rem; margin-bottom: .55rem; }
.component-head .cname { font-weight: 600; font-size: .88rem; letter-spacing: -.005em; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: .62rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }
.badge.healthy { background: var(--ok-bg);   color: var(--ok); }
.badge.warn    { background: var(--warn-bg); color: var(--warn); }
.badge.crit    { background: var(--crit-bg); color: var(--crit); }
.badge.error   { background: var(--info-bg); color: var(--info); }
.badge.unknown { background: var(--muted-bg); color: var(--text3); }
.facts { display: flex; flex-wrap: wrap; gap: .4rem .75rem; font-family: ui-monospace, Menlo, monospace; font-size: .78rem; color: var(--text); }
.facts.empty { color: var(--text3); }
.fact .k { color: var(--text3); margin-right: .3rem; }
.fact .v { color: var(--text); }
.err { color: var(--crit); font-family: ui-monospace, Menlo, monospace; font-size: .78rem; }

/* stat */
.stat-card { display: flex; flex-direction: column; gap: .25rem; flex: 1; }
.stat-card .label { font-size: .62rem; font-weight: 600; text-transform: uppercase; letter-spacing: .07em; color: var(--text3); }
.stat-card .value { font-size: 2.5rem; font-weight: 600; line-height: 1; letter-spacing: -.02em; margin-top: .1rem; }
.stat-card .detail { font-size: .72rem; color: var(--text3); margin-top: .1rem; }
.stat-card .spark-meta { display: flex; justify-content: flex-end; font-family: ui-monospace, Menlo, monospace; font-size: .58rem; color: var(--text3); margin-top: .9rem; opacity: .55; letter-spacing: .03em; text-transform: uppercase; }
.stat-card .uplot-host.spark { flex: 1 1 60px; min-height: 60px; max-height: 140px; min-width: 0; margin-top: .15rem; }
.stat-card .uplot-host.spark .u-wrap { height: 100% !important; }
.stat-card .spark-bar { flex: 1 1 0; min-width: 2px; border-radius: 1px; }
.stat-card.ok .value   { color: var(--ok); }
.stat-card.warn .value { color: var(--warn); }
.stat-card.crit .value { color: var(--crit); }
.stat-card.info .value { color: var(--info); }
.stat-card.ok   .spark .spark-bar { background: var(--ok); }
.stat-card.warn .spark .spark-bar { background: var(--warn); }
.stat-card.crit .spark .spark-bar { background: var(--crit); }
.stat-card.info .spark .spark-bar { background: var(--info); }
.stat-card .spark .spark-bar { opacity: .8; }

/* table */
.filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; }
.filters .pill, .filters .filter-text { font: inherit; background: var(--bg2); color: var(--text); border: 1px solid var(--border); padding: .25rem .6rem; border-radius: 4px; font-size: .75rem; cursor: pointer; transition: border-color .1s, background .1s; }
.filters .pill:hover { border-color: var(--text3); }
.filters .pill[aria-pressed="true"] { border-color: var(--accent); background: rgba(214, 180, 111, 0.12); color: var(--text); }
.filters .filter-text { cursor: text; min-width: 12rem; }
.filters .filter-text:focus { outline: none; border-color: var(--accent); }
.view-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.view-table th { text-align: left; color: var(--text3); font-weight: 500; font-size: .65rem; text-transform: uppercase; letter-spacing: .05em; padding: .35rem .5rem; border-bottom: 1px solid var(--border); }
.view-table td { padding: .4rem .5rem; border-top: 1px solid var(--border); vertical-align: top; }
.view-table td.code, .view-table td.ts { font-family: ui-monospace, Menlo, monospace; font-size: .75rem; color: var(--text3); }
.view-table td.link a { color: var(--text); text-decoration: none; border-bottom: 1px dotted var(--border); }
.view-table td.link a:hover { color: var(--accent); border-bottom-color: var(--accent); }
.cell-badge { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: .65rem; }
.cell-badge.ok { background: var(--ok-bg); color: var(--ok); }
.cell-badge.warn { background: var(--warn-bg); color: var(--warn); }
.cell-badge.crit { background: var(--crit-bg); color: var(--crit); }
.cell-badge.info { background: var(--info-bg); color: var(--info); }
.cell-badge.muted { background: var(--muted-bg); color: var(--text3); }
.cell-tag { display: inline-block; background: var(--muted-bg); color: var(--text3); padding: 1px 6px; border-radius: 3px; font-size: .65rem; margin-right: .25rem; font-family: ui-monospace, Menlo, monospace; }
.progress .bar { background: var(--bg2); border-radius: 3px; height: 8px; width: 100%; max-width: 200px; overflow: hidden; }
.progress .fill { height: 100%; }
.progress .fill.ok { background: var(--ok); }
.progress .fill.warn { background: var(--warn); }
.progress .fill.crit { background: var(--crit); }
.progress-label { font-size: .7rem; color: var(--text3); margin-left: .35rem; }
.actions .act { font: inherit; background: var(--bg2); color: var(--text); border: 1px solid var(--border); padding: .15rem .5rem; margin-right: .25rem; border-radius: 3px; font-size: .7rem; cursor: pointer; }
.actions .act:hover { border-color: var(--accent); }
.actions .act.destructive { color: var(--text3); }
.actions .act.destructive:hover { border-color: var(--crit); color: var(--crit); }
.actions .act:disabled { opacity: .5; cursor: progress; }

/* toast */
#tb-toast { position: fixed; right: 1rem; bottom: 1rem; display: flex; flex-direction: column; gap: .5rem; z-index: 1000; pointer-events: none; }
.tb-toast-item { background: var(--bg2); color: var(--text); border: 1px solid var(--border); padding: .55rem .85rem; border-radius: 6px; font-size: .8rem; max-width: 28rem; box-shadow: 0 4px 14px rgba(0,0,0,.5); opacity: 0; transform: translateY(6px); transition: opacity .2s, transform .2s; pointer-events: auto; font-family: ui-monospace, Menlo, monospace; }
.tb-toast-item.visible { opacity: 1; transform: translateY(0); }
.tb-toast-item.ok   { border-left: 3px solid var(--ok); }
.tb-toast-item.warn { border-left: 3px solid var(--warn); }
.tb-toast-item.crit { border-left: 3px solid var(--crit); }
.tb-toast-item.info { border-left: 3px solid var(--info); }
.multiline .ml-title { font-weight: 600; color: var(--accent); font-size: .8rem; }
.multiline .ml-line { color: var(--text3); font-size: .75rem; margin-top: .15rem; }
.group { margin-bottom: .75rem; }
.group-head { font-size: .75rem; color: var(--text3); margin-bottom: .25rem; }
.gbadge { background: var(--muted-bg); color: var(--text); padding: 1px 6px; border-radius: 999px; font-size: .65rem; margin-left: .25rem; }

/* sparkline (used inline by Stat tiles) */
.spark { display: flex; align-items: flex-end; gap: 2px; height: 28px; vertical-align: middle; }
.spark-bar { position: relative; flex: 1 1 0; min-width: 2px; background: var(--accent); border-radius: 1px 1px 0 0; min-height: 1px; opacity: .8; transition: opacity .1s; }
.spark-bar:hover { opacity: 1; }
.spark-bar:hover::after {
  content: attr(data-y);
  position: absolute; bottom: calc(100% + 4px); left: 50%; transform: translateX(-50%);
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  padding: .2rem .45rem; border-radius: 3px; font-family: ui-monospace, Menlo, monospace;
  font-size: .65rem; white-space: nowrap; pointer-events: none; z-index: 50;
  box-shadow: 0 2px 8px rgba(0,0,0,.4);
}

/* feed — chronological, single column. Accent shows as a left-border stripe,
   not by recoloring the title — keeps severity legible without overloading it onto
   semantic message text. */
.feed { list-style: none; margin: 0; padding: 0; }
.feed-item { display: grid; grid-template-columns: 4.5rem 3px 1fr; gap: .75rem; padding: .45rem 0; border-top: 1px solid var(--border); }
.feed-item:first-child { border-top: 0; padding-top: 0; }
.feed-ts { color: var(--text3); font-family: ui-monospace, Menlo, monospace; font-size: .68rem; padding-top: .2rem; text-align: right; opacity: .85; }
.feed-stripe { width: 3px; border-radius: 2px; background: transparent; }
.feed-title { font-size: .82rem; font-weight: 500; line-height: 1.25; color: var(--text); }
.feed-body { color: var(--text3); font-size: .75rem; margin-top: .1rem; line-height: 1.4; }
.feed-item.ok   .feed-stripe { background: var(--ok); }
.feed-item.warn .feed-stripe { background: var(--warn); }
.feed-item.crit .feed-stripe { background: var(--crit); }
.feed-item.info .feed-stripe { background: var(--info); }

/* chart — same vertical rhythm as stat-card: label, big value, detail, plot pinned bottom */
.chart { display: flex; flex-direction: column; gap: .25rem; flex: 1; }
.chart .chart-plot { margin-top: auto; }
.chart .uplot-host { flex: 1; min-height: 180px; min-width: 0; }
.chart .uplot-host .u-wrap { height: 100% !important; }
/* uPlot dark-mode overrides — uPlot's own CSS has no background, so we don't fight it */
/* Hide the live legend's idle "y: --" placeholder; reveal on chart hover. */
.uplot-host .u-legend { opacity: 0; transition: opacity .15s; pointer-events: none; }
.uplot-host:hover .u-legend { opacity: 1; }
.u-legend { font-family: ui-monospace, Menlo, monospace; font-size: .68rem; padding-top: .35rem; color: var(--text3); }
.u-legend .u-marker { width: 8px; height: 8px; border-radius: 2px; }
.u-legend th, .u-legend td { color: var(--text3); }
.u-cursor-x, .u-cursor-y { background: var(--text3); }
.u-select { background: rgba(214, 180, 111, 0.10); }
.u-axis { color: var(--text3); }
.chart .label   { font-size: .62rem; font-weight: 600; text-transform: uppercase; letter-spacing: .07em; color: var(--text3); }
.chart .value   { font-size: 2.5rem; font-weight: 600; line-height: 1; letter-spacing: -.02em; margin-top: .1rem; color: var(--text); display: flex; align-items: baseline; gap: .5rem; }
.chart .value-suffix { font-size: .65rem; font-weight: 500; color: var(--text3); text-transform: uppercase; letter-spacing: .07em; }
.chart .detail  { font-size: .72rem; color: var(--text3); margin-top: .1rem; }
.chart-plot { display: grid; grid-template-columns: 2.5rem 1fr; gap: .5rem; height: 96px; margin-top: .5rem; }
.chart-yaxis { display: flex; flex-direction: column; justify-content: space-between; align-items: flex-end; font-family: ui-monospace, Menlo, monospace; font-size: .65rem; color: var(--text3); padding: .1rem 0; }
.chart-yaxis .y-max { opacity: .85; }
.chart-yaxis .y-zero { opacity: .5; }
.chart.bars .bars-row { display: flex; align-items: flex-end; gap: 2px; height: 100%; border-left: 1px solid var(--border); border-bottom: 1px solid var(--border); padding-left: 2px; }
.chart .bar-item { position: relative; flex: 1; min-height: 2px; background: var(--accent); border-radius: 2px 2px 0 0; opacity: .85; transition: opacity .1s; }
.chart .bar-item:hover { opacity: 1; }
.chart .bar-item:hover::after {
  content: attr(data-x) ' · ' attr(data-y);
  position: absolute; bottom: calc(100% + 4px); left: 50%; transform: translateX(-50%);
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  padding: .3rem .55rem; border-radius: 4px; font-family: ui-monospace, Menlo, monospace;
  font-size: .7rem; white-space: nowrap; pointer-events: none; z-index: 50;
  box-shadow: 0 2px 8px rgba(0,0,0,.4);
}
.chart-xaxis { display: flex; justify-content: space-between; font-family: ui-monospace, Menlo, monospace; font-size: .65rem; color: var(--text3); margin-top: .25rem; padding-left: 3rem; }
.chart-xaxis .x-total { opacity: .9; color: var(--text); }
"""


_INIT_JS = r"""
(function () {
  if (typeof uPlot === 'undefined') return;
  var DARK = {
    grid: '#22272d', text: '#9aa4af', accent: '#d6b46f',
    fontFamily: 'ui-monospace, Menlo, monospace',
  };
  // Track instances so we can destroy() before any later replacement to prevent
  // listener/handle leaks in long-lived polling dashboards.
  var INSTANCES = new WeakMap();

  function getAccentColor(host) {
    var el = host;
    for (var i = 0; i < 5 && el; i++, el = el.parentElement) {
      if (el.classList && el.classList.contains('stat-card')) {
        if (el.classList.contains('crit')) return ['#f19a9a', 'rgba(241, 154, 154, 0.85)'];
        if (el.classList.contains('warn')) return ['#f6c14b', 'rgba(246, 193, 75, 0.85)'];
        if (el.classList.contains('ok'))   return ['#6bd99b', 'rgba(107, 217, 155, 0.85)'];
        if (el.classList.contains('info')) return ['#c5b3ff', 'rgba(197, 179, 255, 0.85)'];
      }
    }
    return [DARK.accent, 'rgba(214, 180, 111, 0.85)'];
  }
  function tryDate(s) { var t = Date.parse(s); return isFinite(t) ? t / 1000 : null; }

  function build(host) {
    // Tear down any previous instance bound to this host.
    var prev = INSTANCES.get(host);
    if (prev) { try { prev.destroy(); } catch (_) {} INSTANCES.delete(host); host.innerHTML = ''; }

    var raw;
    try { raw = JSON.parse(host.dataset.points); } catch (e) { return; }
    var pts = raw.points || [];
    if (!pts.length) return;
    var isSpark = host.classList.contains('spark');
    var xsTime = pts.map(function (p) { return tryDate(p.x); });
    var isTime = xsTime.every(function (t) { return t !== null; });
    var xs = isTime ? xsTime : pts.map(function (_, i) { return i; });
    var ys = pts.map(function (p) { return Number(p.y) || 0; });
    var data = [xs, ys];
    var bars = uPlot.paths.bars({size: [0.85, 100]});
    var color = getAccentColor(host);
    var W = host.clientWidth || 600;
    var opts;
    if (isSpark) {
      // Sparkline: hide axes entirely (canonical idiom), no cursor, no legend.
      opts = {
        width: W, height: 60,
        scales: {x: {time: isTime}, y: {range: [0, Math.max.apply(null, ys) * 1.1 || 1]}},
        axes: [{show: false}, {show: false}],
        series: [
          {label: 'x'},
          {label: 'y', stroke: color[0], fill: color[1], paths: bars, points: {show: false}},
        ],
        cursor: {show: false},
        select: {show: false},
        legend: {show: false},
      };
    } else {
      opts = {
        width: W, height: 200,
        scales: {x: {time: isTime}, y: {range: [0, Math.max.apply(null, ys) * 1.1 || 1]}},
        axes: [
          {stroke: DARK.text, grid: {stroke: DARK.grid, width: 1}, ticks: {stroke: DARK.grid},
           font: '11px ' + DARK.fontFamily,
           values: isTime ? null : (function (_, vs) { return vs.map(function (i) { return pts[Math.round(i)] ? pts[Math.round(i)].x : ''; }); })},
          {stroke: DARK.text, grid: {stroke: DARK.grid, width: 1}, ticks: {stroke: DARK.grid},
           font: '11px ' + DARK.fontFamily, size: 38},
        ],
        series: [
          {label: 'x'},
          {label: 'count', stroke: color[0], fill: color[1], paths: bars, points: {show: false}},
        ],
        cursor: {points: {show: false}, drag: {x: true, y: false}},
        legend: {show: true, live: true},
      };
    }
    var u = new uPlot(opts, data, host);
    INSTANCES.set(host, u);
    // Default the live legend to the latest point so it never renders "y: --".
    // setLegend must run after the first paint to actually populate the DOM.
    if (!isSpark) {
      var lastIdx = data[0].length - 1;
      requestAnimationFrame(function () {
        try { u.setLegend({idx: lastIdx}); } catch (_) {}
      });
    }

    // ResizeObserver picks up CSS-driven container changes that window.resize misses.
    var ro = new ResizeObserver(function () {
      var h = isSpark ? Math.max(48, host.clientHeight || 60) : Math.max(180, host.clientHeight || 200);
      u.setSize({width: host.clientWidth || W, height: h});
    });
    ro.observe(host);
  }
  document.querySelectorAll('.uplot-host').forEach(build);
  // Expose for later poll-driven updates.
  window.__taskboardCharts = {INSTANCES: INSTANCES, build: build};

  // ──────────── Filter pills + text search ────────────
  // Each .filters block sits above one .view-table. Pills set a single dimension
  // filter (by row's data-<id> attribute); .filter-text does a substring match
  // across visible cells. State is local to the filter block — no fetch.
  function tableFor(filters) {
    var sib = filters.nextElementSibling;
    while (sib && !(sib.classList && sib.classList.contains('view-table')) && !sib.querySelector) sib = sib.nextElementSibling;
    if (!sib) return null;
    if (sib.classList && sib.classList.contains('view-table')) return sib;
    return sib.querySelector ? sib.querySelector('table.view-table') : null;
  }
  function applyFilters(filtersEl, table) {
    if (!table) return;
    var pillState = {}; // {filter_id: value or null}
    filtersEl.querySelectorAll('.pill[aria-pressed="true"]').forEach(function (p) {
      pillState[p.dataset.filter] = p.dataset.value;
    });
    var searchInput = filtersEl.querySelector('.filter-text');
    var q = searchInput ? searchInput.value.trim().toLowerCase() : '';
    table.querySelectorAll('tbody tr').forEach(function (tr) {
      var keep = true;
      for (var fid in pillState) {
        var want = pillState[fid];
        if (want === 'all' || want == null) continue;
        var have = tr.dataset[fid] || '';
        if (have !== want) { keep = false; break; }
      }
      if (keep && q) keep = (tr.textContent || '').toLowerCase().indexOf(q) !== -1;
      tr.style.display = keep ? '' : 'none';
    });
  }
  document.querySelectorAll('.filters').forEach(function (filtersEl) {
    var table = tableFor(filtersEl);
    if (!table) return;
    filtersEl.querySelectorAll('.pill').forEach(function (pill) {
      pill.setAttribute('aria-pressed', 'false');
      pill.addEventListener('click', function () {
        // Toggle: if already pressed, unset. Otherwise pressed (and unpress siblings).
        var was = pill.getAttribute('aria-pressed') === 'true';
        filtersEl.querySelectorAll('.pill[data-filter="' + pill.dataset.filter + '"]').forEach(function (p) {
          p.setAttribute('aria-pressed', 'false');
        });
        if (!was) pill.setAttribute('aria-pressed', 'true');
        applyFilters(filtersEl, table);
      });
    });
    var search = filtersEl.querySelector('.filter-text');
    if (search) {
      search.addEventListener('input', function () { applyFilters(filtersEl, table); });
    }
  });

  // ──────────── Action buttons → POST → toast ────────────
  // Each .act button climbs to the nearest [data-system][data-component] component
  // and POSTs to /api/systems/{sys}/components/{cmp}/actions/{id}. Result lands
  // in a toast in the bottom-right corner. 501 from server → "not implemented".
  function ensureToastHost() {
    var t = document.getElementById('tb-toast');
    if (t) return t;
    t = document.createElement('div');
    t.id = 'tb-toast';
    document.body.appendChild(t);
    return t;
  }
  function toast(msg, accent) {
    var host = ensureToastHost();
    var el = document.createElement('div');
    el.className = 'tb-toast-item ' + (accent || 'info');
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(function () { el.classList.add('visible'); }, 10);
    setTimeout(function () {
      el.classList.remove('visible');
      setTimeout(function () { el.remove(); }, 250);
    }, 4500);
  }
  document.addEventListener('click', function (evt) {
    var btn = evt.target.closest && evt.target.closest('button.act');
    if (!btn) return;
    var comp = btn.closest('.component');
    if (!comp) return;
    var sys = comp.dataset.system, cmp = comp.dataset.component, action = btn.dataset.action;
    var rowId = btn.dataset.rowId || '';
    if (!sys || !cmp || !action) return;
    var target = rowId || cmp;
    if (btn.dataset.confirm === '1') {
      var ok = window.confirm(action + ' ' + target + '? This action is destructive.');
      if (!ok) return;
    }
    btn.disabled = true;
    var url = '/api/systems/' + encodeURIComponent(sys) + '/components/' +
              encodeURIComponent(cmp) + '/actions/' + encodeURIComponent(action);
    if (rowId) url += '?row_id=' + encodeURIComponent(rowId);
    fetch(url, {method: 'POST'})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
      .then(function (sj) {
        var status = sj[0], j = sj[1] || {};
        var accent = (status >= 200 && status < 300 && j.ok) ? 'ok'
                   : (status === 501) ? 'warn' : 'crit';
        var msg = (j.message || '') + (msg ? ' — ' : '');
        msg = (j.message || j.result || (status === 501 ? 'not implemented by pack' : 'action ' + action))
            + ' [' + cmp + ']';
        toast(msg, accent);
      })
      .catch(function (e) { toast('error: ' + e.message + ' [' + cmp + ']', 'crit'); })
      .finally(function () { btn.disabled = false; });
  });
})();
"""

__all__ = ["render_html"]
