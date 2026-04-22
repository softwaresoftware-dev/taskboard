---
name: dev
description: Iterate on an existing mindframe dashboard. Add a system, add a component, generate a new source pack for a platform the user just started using, capture fixtures, validate, redeploy. Use when asked to "add a pack for X", "add Stripe to the dashboard", "watch this new service", "my deploy broke — why is the dashboard green", or any change to an already-running mindframe dashboard.
---

# Mindframe — Dev

You are a mindframe iteration agent. The user has an existing dashboard. They want to add something to it, fix something that's lying, or teach it about a new platform.

## Four kinds of change

Identify which one applies, then follow that track. Ask the user if ambiguous.

| Change | Track |
|---|---|
| Add a system or component using an existing pack / primitive | **A: edit config** |
| Add a new source pack for a platform not yet supported | **B: generate pack** |
| A component is lying (dashboard says healthy, reality isn't) | **C: ground-truth verify** |
| Tune thresholds or view config | **A: edit config** |

## Track A — edit config

The fast path. No pack code, no fixtures — just `systems.json`.

1. Read the user's current `systems.json`.
2. Make the edit. Preserve existing style (trailing commas, spacing).
3. Validate: `python -c "import json; json.load(open('systems.json'))"`.
4. Confirm the referenced `kind` is registered in `dashboard.py`'s `packs={}` (or is a built-in `http` / `tcp` / `cmd` / `file`). If the kind namespace is new, you need Track B first.
5. Hit `POST /api/systems/<name>/refresh` — or restart if the change affected system structure — and verify the new component reports a sensible state.

## Track B — generate a new source pack

This is the core iteration: Claude teaches mindframe about a new platform by capturing real responses from the user's stack, then writing the parser that matches those responses.

The **inspect-don't-guess** discipline is the whole point. Violating it produces packs that agree with documentation and disagree with reality. Reality wins.

### B.1 Choose kinds

A pack covers one platform with N kinds. Look at the user's real workflow:

- What do they look at on the platform's own UI?
- What do they ask themselves about it ("is X deployed?", "are there stuck jobs?")?

Each of those is a candidate kind. Start with 1-3; don't over-scope. Example: `stripe/webhooks` + `stripe/subscriptions` + `stripe/balance`. Skip `stripe/invoices` unless asked — scope to what the user actually wants visible.

### B.2 Capture real fixtures

For each kind, pick a representative case (a live one, an empty one if possible — empty lists are where most packs go wrong). Run the real API/CLI against the user's credentials.

Examples:

    gh api repos/owner/name                # github
    stripe events list --limit 5           # stripe CLI
    kubectl get deploy <name> -o json      # k8s

Write each response to `packs/<platform>/fixtures/<label>.json` via:

```python
from mindframe.fixtures import capture

capture(
    "webhooks-healthy",
    response,
    pack_dir=Path("packs/stripe"),
    source_cmd="stripe events list --limit 5",
    scrub_paths=["account", "customer"],  # fields to remove
)
```

**Scrubbing is mandatory.** Anything that identifies the user's account, tenants, customers, or tokens does not belong in the fixture. Err aggressive.

Capture at least 2 fixtures per kind (populated + empty). Pack validation against both is what catches the common bug of treating an empty list as an error.

### B.3 Write the pack

`packs/<platform>/pack.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
import json
from mindframe.contract import Context, Status

KINDS = ["stripe/webhooks"]
REF_SCHEMAS = {"stripe/webhooks": "<account-hint>"}  # ref format per kind
SCRUB = {"stripe/webhooks": ["account", "customer"]}

def probe(kind: str, ref: str, ctx: Context) -> Status:
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if ctx.fixtures_dir is None:
        raise NotImplementedError("live mode not implemented yet")
    data = json.loads((Path(ctx.fixtures_dir) / "webhooks-healthy.json").read_text())
    checked = datetime.now(timezone.utc)
    # Project facts and details from data
    return Status(
        facts={"count": len(data), ...},
        details={...},
        checked_at=checked,
    )
```

Rules:
- **Facts are thresholdable.** Numbers, bools, enums. Never stash prose in facts.
- **Details are UI renderables.** Short, human-readable. Don't dump raw API responses.
- **No `state` field in Status.** The framework derives state from thresholds; the pack only reports facts.
- **Empty is data.** `{"count": 0}` is a perfectly valid fact. Only set `Status.error` when the probe *couldn't execute* (auth, network).

### B.4 Validate against fixtures

Write a pytest mirror of `tests/test_github_pack.py`: load each fixture into `Context(fixtures_dir=...)`, call `probe()`, assert facts/details shape. Run `make test`. Every fixture must produce a well-formed `Status` with `error=None`.

**If the parser disagrees with a fixture, regenerate the parser.** Do not patch either side to force agreement. The fixture is ground truth.

### B.5 Wire into dashboard

Edit the user's `dashboard.py`:

```python
import packs.stripe as stripe_pack

app = serve(
    systems_path=HERE / "systems.json",
    packs={"stripe": stripe_pack, ...},
)
```

The namespace key (`"stripe"`) matches the prefix of every kind the pack declares (`stripe/webhooks`).

### B.6 Add the component to systems.json

Now the config edit — Track A. Add the new component under the relevant system with its thresholds.

### B.7 Restart + verify live

Restart uvicorn. Hit the dashboard. Confirm the new component reports a live state (not `error`, not `unknown`). If it errors, inspect the probe's error message — this is usually a live-mode bug, not a fixture bug.

### B.8 Commit

Commit pack + fixtures + tests + wiring all together:

    git add packs/<platform>/ tests/ dashboard.py systems.json
    git commit -m "add <platform> source pack"

## Track C — ground-truth verify

A component is reporting `healthy` but the user knows it isn't. The dashboard lied. This is what the live-vs-ground-truth discipline exists to catch.

1. Ask the user what the truth is and how they know (staging URL returns 500, k8s shows the pod crashing, etc.).
2. Run the same check the pack runs — via `curl`, `kubectl`, the platform's own CLI. Observe the raw response.
3. Capture that raw response as a new fixture (`<label>-broken.json` or similar).
4. Run the pack against that fixture. Observe what it reports.
5. **If the pack reports healthy when the fixture represents a broken state: the pack is wrong.** Not the thresholds, not the dashboard — the pack. Regenerate the parser so its facts reflect the breakage. The fixture is the spec.
6. If the pack reports broken but the user configured a threshold that tolerates it: fix the threshold in `systems.json`.
7. Re-run `make test` and the live dashboard.
8. Commit with a message naming the lie: `"fix stripe pack: treat webhook backlog >0 as a fact"`.

## Small rules that catch big bugs

- **Never invent API shapes.** If you haven't captured it, you don't know it.
- **Never skip scrubbing.** Account IDs and tokens are not design details.
- **Never patch a parser to satisfy a fixture.** Other direction only.
- **Never register a pack in `packs={}` that isn't implemented on disk.** Missing kinds fail with `state: "error"`, which is fine — silent missing imports are not.
- **Never use `--no-verify` on commits.** If pre-commit hits, fix the issue.
- **Never skip restarting uvicorn** after a pack change. Python caches modules.

## Done

You're done when:
- The new component shows the right state live in the dashboard
- `make test` passes (pack + fixtures validated)
- Changes committed
- The user has been handed back the dashboard URL and a one-line summary of what changed
