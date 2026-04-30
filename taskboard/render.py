"""HTML rendering for taskboard snapshots.

A component snapshot may carry a `view` payload (one of: stat, table, chart,
feed). When present, the framework renders the rich view. When absent, falls
back to a compact facts-row.

Cell renderers for tables:
    text | code | link | badge | tags | progress | sparkline | timestamp |
    actions | multiline
"""
from __future__ import annotations

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
    )


# ---------- system + dispatch ----------


def _render_system(name: str, sys_: dict[str, Any]) -> str:
    components = sys_.get("components", {})
    parts: list[str] = []
    for cname, comp in components.items():
        parts.append(_render_component(cname, comp))
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


def _render_component(cname: str, comp: dict[str, Any]) -> str:
    view = comp.get("view")
    head = (
        f"<div class='component-head'>"
        f"<div class='cname'>{_esc(cname)}</div>"
        f"{_badge(comp.get('state', 'unknown'))}"
        f"<div class='kind'>{_esc(comp.get('kind') or '')}</div>"
        f"</div>"
    )
    if comp.get("error"):
        body = f"<div class='err'>{_esc(comp['error'])}</div>"
    elif view is None:
        body = _render_facts(comp.get("facts") or {})
    else:
        body = _render_view(view)
    return f"<div class='component'>{head}{body}</div>"


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
    trend_html = _sparkline(trend) if trend else ""
    detail = v.get("detail")
    detail_html = f"<div class='detail'>{_esc(detail)}</div>" if detail else ""
    return (
        f"<div class='stat-card {accent}'>"
        f"<div class='label'>{_esc(v.get('label') or '')}</div>"
        f"<div class='value'>{_esc(v.get('value'))}</div>"
        f"{detail_html}"
        f"{trend_html}"
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
        return filter_html + _render_grouped_table(columns, rows, actions, groups)

    head = "<tr>" + "".join(
        f"<th class='col-{_esc(c.get('cell_kind') or 'text')}'>{_esc(c.get('label') or c.get('key'))}</th>"
        for c in columns
    ) + "</tr>"
    body_rows = "".join(_render_row(columns, r, actions) for r in rows)
    return (
        f"{filter_html}"
        f"<table class='view-table'>"
        f"<thead>{head}</thead>"
        f"<tbody>{body_rows}</tbody>"
        f"</table>"
    )


def _render_grouped_table(columns, rows, actions, groups) -> str:
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
        body = "".join(_render_row(columns, r, actions) for r in items)
        parts.append(
            f"<div class='group'>"
            f"<div class='group-head'>{_esc(gtitle)} {gbadge}</div>"
            f"<table class='view-table'><thead>{head}</thead><tbody>{body}</tbody></table>"
            f"</div>"
        )
    return "".join(parts)


def _render_row(columns, row, actions) -> str:
    cells: list[str] = []
    for col in columns:
        key = col["key"]
        kind = col.get("cell_kind") or "text"
        cells.append(_render_cell(kind, row.get(key), row, actions))
    return "<tr>" + "".join(cells) + "</tr>"


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
        return f"<td><a href='{_esc(href)}' target='_blank'>{_esc(text)}</a></td>"
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
        btns: list[str] = []
        for aid in ids:
            a = by_id.get(aid)
            if not a:
                continue
            btns.append(f"<button class='act' data-action='{_esc(aid)}'>{_esc(a.get('label') or aid)}</button>")
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
    period_html = f"<div class='detail'>{_esc(period)}</div>" if period else ""
    if chart_kind == "sparkline":
        ys = [float(p.get("y") or 0) for p in points]
        return f"<div class='chart'>{period_html}{_sparkline(ys)}</div>"
    if not points:
        return "<div class='chart facts empty'>no data</div>"
    ys = [float(p.get("y") or 0) for p in points]
    mx = max(ys) or 1.0
    bars = "".join(
        f"<div class='bar-item' title='{_esc(p.get('label') or p.get('x'))}: {_esc(p.get('y'))}' "
        f"style='height:{(float(p.get('y') or 0) / mx * 100):.1f}%'></div>"
        for p in points
    )
    return f"<div class='chart bars'>{period_html}<div class='bars-row'>{bars}</div></div>"


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


def _sparkline(ys: list[float]) -> str:
    if not ys:
        return ""
    mx = max(ys) or 1.0
    bars = "".join(
        f"<div class='spark-bar' style='height:{(float(y) / mx * 100):.0f}%' title='{_esc(y)}'></div>"
        for y in ys
    )
    return f"<div class='spark'>{bars}</div>"


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
<style>{css}</style></head>
<body>
<header class='top'>
  <h1>{title}</h1>
  <p class='muted'>snapshot: {snapshot_at}</p>
</header>
{body}
</body></html>"""


_CSS = """
:root {
  --bg: #0b0d10; --bg2: #14181d; --surface: #1a1f25;
  --text: #e6e6e6; --text3: #9aa4af; --border: #22272d;
  --ok: #6bd99b; --warn: #f6c14b; --crit: #f19a9a; --info: #c5b3ff; --accent: #d6b46f;
  --ok-bg: #124a2b; --warn-bg: #5b4412; --crit-bg: #631d1d; --info-bg: #3a2b63; --muted-bg: #2a2f35;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 2rem; background: var(--bg); color: var(--text); }
.top h1 { font-weight: 500; margin: 0 0 .25rem; }
.top .muted { color: var(--text3); font-size: .85rem; margin: 0 0 1.5rem; }
section.system { margin-bottom: 1.5rem; background: var(--bg2); padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid var(--border); }
section.system header h2 { margin: 0; font-size: 1.1rem; }
section.system header h2 a { color: var(--text); text-decoration: none; border-bottom: 1px dotted var(--text3); }
section.system header p { margin: .25rem 0 .75rem; color: var(--text3); font-size: .85rem; }
.components { display: flex; flex-direction: column; gap: .75rem; }
.component { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: .75rem 1rem; }
.component-head { display: flex; align-items: center; gap: .5rem; margin-bottom: .5rem; }
.component-head .cname { font-weight: 600; font-size: .9rem; }
.component-head .kind { color: var(--text3); font-family: ui-monospace, Menlo, monospace; font-size: .75rem; margin-left: auto; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: .65rem; text-transform: uppercase; letter-spacing: .04em; }
.badge.healthy { background: var(--ok-bg);   color: var(--ok); }
.badge.warn    { background: var(--warn-bg); color: var(--warn); }
.badge.crit    { background: var(--crit-bg); color: var(--crit); }
.badge.error   { background: var(--info-bg); color: var(--info); }
.badge.unknown { background: var(--muted-bg); color: var(--text3); }
.facts { display: flex; flex-wrap: wrap; gap: .5rem; font-family: ui-monospace, Menlo, monospace; font-size: .8rem; color: var(--text); }
.facts.empty { color: var(--text3); }
.fact .k { color: var(--text3); margin-right: .25rem; }
.fact .v { color: var(--text); }
.err { color: var(--crit); font-family: ui-monospace, Menlo, monospace; font-size: .8rem; }

/* stat */
.stat-card { display: inline-block; min-width: 140px; padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg2); margin-right: .5rem; }
.stat-card .label { font-size: .65rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text3); }
.stat-card .value { font-size: 1.75rem; font-weight: 600; line-height: 1.1; margin-top: .15rem; }
.stat-card .detail { font-size: .7rem; color: var(--text3); margin-top: .15rem; }
.stat-card.ok .value   { color: var(--ok); }
.stat-card.warn .value { color: var(--warn); }
.stat-card.crit .value { color: var(--crit); }
.stat-card.info .value { color: var(--info); }

/* table */
.filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; }
.filters .pill, .filters .filter-text { font: inherit; background: var(--bg2); color: var(--text); border: 1px solid var(--border); padding: .25rem .6rem; border-radius: 4px; font-size: .75rem; cursor: pointer; }
.filters .filter-text { cursor: text; min-width: 12rem; }
.view-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.view-table th { text-align: left; color: var(--text3); font-weight: 500; font-size: .65rem; text-transform: uppercase; letter-spacing: .05em; padding: .35rem .5rem; border-bottom: 1px solid var(--border); }
.view-table td { padding: .4rem .5rem; border-top: 1px solid var(--border); vertical-align: top; }
.view-table td.code, .view-table td.ts { font-family: ui-monospace, Menlo, monospace; font-size: .75rem; color: var(--text3); }
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
.multiline .ml-title { font-weight: 600; color: var(--accent); font-size: .8rem; }
.multiline .ml-line { color: var(--text3); font-size: .75rem; margin-top: .15rem; }
.group { margin-bottom: .75rem; }
.group-head { font-size: .75rem; color: var(--text3); margin-bottom: .25rem; }
.gbadge { background: var(--muted-bg); color: var(--text); padding: 1px 6px; border-radius: 999px; font-size: .65rem; margin-left: .25rem; }

/* chart + sparkline */
.spark { display: inline-flex; align-items: flex-end; gap: 2px; height: 24px; vertical-align: middle; }
.spark-bar { width: 3px; background: var(--accent); border-radius: 1px 1px 0 0; min-height: 1px; }
.chart { padding: .5rem 0; }
.chart .detail { font-size: .65rem; color: var(--text3); text-transform: uppercase; letter-spacing: .05em; margin-bottom: .35rem; }
.chart.bars .bars-row { display: flex; align-items: flex-end; gap: 2px; height: 60px; }
.chart .bar-item { flex: 1; min-height: 2px; background: var(--accent); border-radius: 2px 2px 0 0; }

/* feed */
.feed { list-style: none; margin: 0; padding: 0; }
.feed-item { display: flex; gap: .75rem; padding: .35rem 0; border-top: 1px solid var(--border); }
.feed-item:first-child { border-top: 0; }
.feed-ts { color: var(--text3); font-family: ui-monospace, Menlo, monospace; font-size: .7rem; min-width: 5rem; padding-top: .15rem; }
.feed-title { font-size: .85rem; }
.feed-body { color: var(--text3); font-size: .75rem; margin-top: .15rem; }
.feed-item.ok .feed-title   { color: var(--ok); }
.feed-item.warn .feed-title { color: var(--warn); }
.feed-item.crit .feed-title { color: var(--crit); }
"""


__all__ = ["render_html"]
