---
name: create
description: Scaffold a new taskboard dashboard for the user's stack. Interview the user about what they want to watch, probe their environment for what tools are available, build a systems.json + dashboard.py in a sibling directory, seed the right packs, and boot a live dashboard. Use when asked to "create a dashboard", "build me a status page", "set up taskboard", or when the user describes infrastructure they want to monitor.
---

# Taskboard — Create

You are a dashboard creation agent. The user describes what they want to watch. You scaffold a dashboard repo, seed the right source packs, and boot it live.

This is a sequential workflow. Do not parallelize — later steps depend on fixtures and packs landed by earlier ones.

## What taskboard is

A framework for per-user infra dashboards. The user's repo contains **config, not plumbing**:

- `systems.json` — what to watch (systems → components → kind + ref + thresholds)
- `dashboard.py` — 4-line FastAPI entry point that calls `taskboard.serve(...)`
- `packs/` (optional) — source packs you generate for platforms the user uses

The taskboard plugin ships the server factory, built-in primitives (`http`, `tcp`, `cmd`, `file`), a threshold engine, and reference packs. You compose these into a dashboard tailored to the user.

## Core philosophy: inspect, don't guess

Never hallucinate an API shape. When you need a source pack, **capture a real response against the user's actual auth first**, then write the parser to match the fixture. Packs without fixtures are invalid by contract.

For primitives, this doesn't apply — they have no API shape to ground against. Use primitives whenever a `curl`, TCP connect, shell command, or file check is enough.

## View types

`Status` carries an optional `view` payload that controls how the framework renders the component. Without a view, the component renders as a flat `key=value` facts row — correct, but bare. Reach for a typed view whenever the data shape supports one. The four view types live in `taskboard/contract.py` and are exercised end-to-end in `examples/views/` — read that example before generating a pack.

Decision rule, by the dominant shape of what the probe returns:

| Probe returns | Use | Why |
|---|---|---|
| One number worth spotlighting (count, percent, total, latency, queue depth) | **Stat** | Big value + label + optional `trend` for an inline sparkline |
| A list of similar things (units, jobs, deployments, runs, PRs, containers) | **Table** | One component = one whole table, with rich cell renderers |
| A timeseries (events per day, requests per minute, errors per hour) | **Chart** | `chart_kind` is `bar` / `line` / `sparkline` |
| A sequence of timestamped events (activity log, deploys, alerts, commits) | **Feed** | Items with `ts`, `title`, `body`, optional `accent` |
| A single object with two-to-five flat facts | leave `view=None` | Facts row is fine; don't fake a view |

Two rules that catch out new packs:

- **One probe = one Status = one view.** If a system has a "list of agents" worth showing, that is a *single* component whose probe returns a single `Table`. Do not model each row as its own component just to get a list.
- **Pick the right cell kinds.** `Column.cell_kind` is the workhorse — `text`, `code`, `link`, `badge`, `tags`, `progress`, `sparkline`, `timestamp` (rendered as "Nh ago"), `actions`, `multiline`. Choosing well is most of the visual quality. `accent` values across views are `ok` / `warn` / `crit` / `info`.

## Action contract

If a `Table` view's `actions=[...]` list contains any `Action`, the pack **must** implement `act()` or the buttons return 501 to every click. Don't ship a table with action buttons that don't do anything — it's worse than no buttons.

Signature:

    def act(kind: str, ref: str, action: str, ctx: Context, row_id: str | None = None) -> dict:
        """Run the named action against `row_id` (the clicked row's primary value).
        Return a dict with at least {ok: bool, message: str}. The framework
        surfaces `message` in a toast — keep it under ~120 chars for short
        actions, multiline OK for `log`-style readouts."""

Rules:

- **Read-only first.** Implement `log` / `view` / `details` actions before any destructive operation. Read-only buttons are safe to click and verify.
- **Mark destructive actions with `confirm=True`** on the `Action`. The framework wires up a native browser confirm dialog before firing fetch. `restart`, `stop`, `kill`, `delete` should all carry `confirm=True`.
- **`row_id` identifies the clicked row.** It's the first text-y value of the row dict (or whatever you put in `row["id"]`). Look it up in your component's ref list before acting; reject unknown ids with `{"ok": False, "message": "..."}`.
- **Return shape.** Always include `ok` and `message`. Optional: `result`, `unit`, `lines` — anything you want surfaced in logs. Non-200 outcomes (failures from the underlying tool) should still return a dict with `ok=False, message=<short error>` rather than raising.
- **Timeouts and safety.** Use `subprocess.run(..., timeout=N, capture_output=True, text=True)` so a hung command doesn't block the dashboard.

Action buttons are pointless without `act()`. The framework wires the click → fetch → toast plumbing; the pack supplies the action.

## Workflow

### 1. Scope (≤3 questions)

Learn:
- **What do they want to watch?** (apps/sites they run, repos they care about, infra they depend on)
- **Where should the dashboard live?** Default: `~/projects/<name>-dashboard/`. Ask if ambiguous.
- **What name and port?** Default: derive name from their project, port `8080`.

If the user already gave enough context, skip straight to building.

### 2. Probe the environment

Check what's available on the user's machine. This informs which packs to seed and which to generate.

| Available | Seeds |
|---|---|
| `gh auth status` succeeds | `gh` reference pack (already shipped) |
| `docker` on PATH, containers running | suggest `cmd` primitive `docker ps` checks, or generate a `docker` pack |
| `kubectl` + reachable context | generate a `k8s` pack (next session, flag as follow-up) |
| `systemctl` works | generate a `systemd` pack |
| Public URLs the user named | `http` primitive, no pack needed |
| Local ports/processes | `tcp` / `cmd` primitives |

Do this with real shell probes (`command -v`, `gh auth status`, etc.) — don't assume.

### 3. Scaffold the repo

Create the dashboard directory as a sibling of the taskboard plugin, or wherever the user specified.

```
<name>-dashboard/
├── dashboard.py          # imports taskboard, calls serve()
├── systems.json          # the user's systems + components
├── requirements.txt      # taskboard + uvicorn
├── .gitignore
└── README.md             # how to run it
```

Git init the directory. Stage everything. Commit once the dashboard boots successfully — not before.

`dashboard.py` follows this shape — keep it tiny:

```python
from pathlib import Path
from taskboard import serve
# from taskboard.packs.github import pack as gh_pack
# import packs.stripe as stripe_pack

HERE = Path(__file__).parent

app = serve(
    systems_path=HERE / "systems.json",
    packs={
        # "gh": gh_pack,
        # "stripe": stripe_pack,
    },
    poll_interval=30,
    title="<Name> Dashboard",
)
```

Uncomment and import only the packs the user actually needs.

### 4. Seed systems.json

Build `systems.json` from what you learned in steps 1-2. Each system groups related components. Each component declares `kind`, `ref`, optional `config`, and optional `thresholds`.

Use primitives wherever possible — no pack generation required. Keep thresholds honest: don't invent numbers the user didn't ask for. Better to ship with no thresholds on a fact than guess one.

Decide *up front* whether a list of related items should be one component (single component returning a `Table` view from a custom pack) or many components (one each, facts-row). The single-table model is almost always better when the items are homogeneous — it gets you filter pills, row actions, sortable columns, and a much denser layout. See **View types** above.

Example shape (see `examples/minimal/systems.json` for a working reference):

```json
{
  "systems": {
    "my-app": {
      "description": "<short>",
      "url": "<optional public URL>",
      "components": {
        "site": {
          "kind": "http",
          "ref":  "https://my-app.example.com",
          "thresholds": {"status_code": {"crit_if_not_in": [200]}}
        }
      }
    }
  }
}
```

### 5. Generate source packs (only if primitives won't do)

If the user wants to monitor something that isn't a simple URL ping — e.g. "how many open PRs in this repo", "is this k8s deployment rolled out", "what's the Stripe webhook backlog" — you need a source pack.

For each new pack, pass control to `/taskboard:dev` or run its steps inline:

1. **Capture a real fixture** using the user's credentials (`gh api`, `kubectl get`, `curl -H "Authorization: Bearer …"`). Write to `packs/<platform>/fixtures/<label>.json` using `taskboard.fixtures.capture()`.
2. **Scrub sensitive fields** as part of capture (pass `scrub_paths=[...]`).
3. **Write the pack** — `KINDS`, `REF_SCHEMAS`, `SCRUB`, `probe()`. The parser must match the fixture. If the data is list-shaped, time-shaped, event-shaped, or spotlight-shaped, attach a `view` payload to the returned `Status` (see **View types** above). Pure facts-only is fine for single-object probes; don't invent a view that doesn't fit.
4. **Wire actions if the table has them** — if the `Table` view declares any `actions=[Action(id="...")]`, the pack must implement `def act(kind, ref, action, ctx, row_id=None) -> dict` to make the buttons functional. Without it, every click returns 501 "not implemented." See **Action contract** below.
5. **Validate** — run the pack against every fixture. `Status.error` must be `None` for all of them. If the parser disagrees with a fixture, **regenerate the parser, don't patch it to match**.
6. **Commit** the pack + fixtures + meta.

Wire the new pack into `dashboard.py`'s `packs={}` dict. Namespace matches the `KINDS` prefix (`packs={"stripe": stripe_pack}` routes `stripe/webhook` kinds to it).

### 6. Install + boot

Create a venv in the dashboard directory. Install taskboard as an editable dependency:

    python3 -m venv .venv
    .venv/bin/pip install -e <path-to-plugin>/taskboard

Start uvicorn on the chosen port. Hit `/healthz` and `/api/systems` to verify. If any component returns `state: "error"`, investigate before declaring success.

### 7. Verify in a browser

Open the dashboard URL (`http://localhost:<port>/`) and confirm the HTML renders and systems show live state. Use an available browser automation tool; if none is available, say so and leave the curl evidence in the summary.

### 8. Commit and hand back

    git -C <dashboard-dir> add -A
    git -C <dashboard-dir> commit -m "scaffold taskboard dashboard"

Show the user:
- The dashboard URL
- The file list of what was created
- Which packs were seeded vs generated vs left as follow-ups
- Command to restart: `<dashboard-dir>/.venv/bin/uvicorn dashboard:app --port <port>`

Hand off to `/taskboard:dev` for further iteration.

## Things not to do

- **Do not write `probe()` before capturing a fixture.** The fixture is the contract. Parser matches fixture, not the other way around.
- **Do not invent thresholds the user didn't specify.** Empty thresholds = healthy-by-default is a feature.
- **Do not add dependencies beyond taskboard and uvicorn** unless the user asked for them. Keep the scaffold minimal.
- **Do not register packs in `serve(packs=...)` that don't exist on disk.** Leave `packs={}` empty if no custom packs were generated.
- **Do not fake a view.** If the probe returns a single object with a few facts, ship `view=None`. The facts row is honest. Inventing a `Stat` from a number that isn't worth spotlighting, or a `Table` from a single record, makes the dashboard worse, not better.
- **Do not use `--no-verify` on commits.** If pre-commit hits, fix the issue.
