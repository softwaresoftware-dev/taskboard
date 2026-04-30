# Taskboard Contract

Design decisions for the Source contract, as landed in the first design session. Findings from running `gh api` live against real repos are noted inline — design was revised by contact with reality, not argued on paper.

## Status

```python
@dataclass
class Status:
    facts:      dict[str, Any]       # numeric/enum thresholdable values
    details:    dict[str, Any]       # human-readable projection for UI
    checked_at: datetime
    error:      str | None = None    # probe-level failure (auth, network, rate limit)
```

**No `state` field.** Empty results (0 PRs, 0 releases) are healthy for one user and degraded for another. The pack can't know — it reports facts; the framework applies thresholds from `systems.json`.

**facts vs details.** Facts are threshold inputs; details are UI renderables. Overlap is fine.

**error vs facts.** `error` means "this probe could not execute." A broken component is a fact, not an error.

## Source protocol

```python
class Source(Protocol):
    KINDS:        list[str]
    REF_SCHEMAS:  dict[str, str]     # kind -> ref format
    SCRUB:        dict[str, list[str]]   # kind -> json paths to redact in fixtures
    def probe(self, kind: str, ref: str, ctx: Context) -> Status: ...
```

`detect`, `list_candidates`, `CONFIG_SCHEMA`, `PERMISSIONS` are lazy-materialized — the framework asks Claude to regenerate the pack with them when a feature needs them. Pack size stays minimal by default.

## Refs

Plain strings. Each kind declares a format (`"{owner}/{repo}"`, `"{owner}/{repo}#{number}"`). The pack parses; the framework stays ignorant.

## Fixtures

- Stored raw (full API response JSON, no pre-digestion).
- Required. A pack without fixtures is not a pack.
- Name: `<kind-label>-<state-label>.json` (`repo-public.json`, `prs-empty.json`).
- Scrubbing is per-kind (`SCRUB` dict). Driven by the pack, because sensitivity varies by endpoint (a public-repo response has no PII; a `/user` response has email and 2FA state).
- An accompanying `.meta.json` records the capture command, timestamp, and API/CLI version. Team asset — first engineer captures, teammates reuse.

## Validation

A pack is valid when `probe()` on every fixture produces a well-formed `Status`. Broken output → regenerate the pack, don't patch the parser. The parser only exists to match fixtures; a parser that disagrees with its fixtures is ill-formed by construction.

## Findings from the first capture

Running `gh api` against the user's real repos surfaced things specs wouldn't have:

- **No CI in any softwaresoftware-dev repo.** Kills `gh/workflow-run` as a first kind. Shifts the GitHub pack toward `repo`, `pull-requests`, `releases`, and `check-runs-on-head`.
- **Empty arrays everywhere** (`prs: []`, `releases: []`). Confirmed the state-vocabulary decision above — empty is data, not error, and the user decides what it means.
- **Raw fixture is ~8KB / ~80 fields, ~90% URLs.** Signal fields are ~10%. Confirms: store raw, project thin subsets at probe time.
- **One pack needs multiple ref shapes** — repos, PRs, workflows all have different identifiers. Motivated per-kind `REF_SCHEMAS`.

## Open questions

- **Live mode transport.** `Context` needs to carry an auth/transport object. For `gh/` it's the `gh` CLI or an HTTP client with PAT; for `k8s/` it's `kubectl` or the API directly. What's the right abstraction?
- **Regeneration inputs.** When the framework asks Claude to add `list_candidates`, what does it pass — the existing pack source, the fixtures, the contract doc, or all three?
- **Threshold DSL in systems.json.** `{warn_gt, crit_gt}` covers count thresholds. Need enum thresholds (`warn_if_in: ["action_required"]`), duration thresholds (`warn_if_age_gt: "7d"`), and maybe boolean thresholds (`crit_if: archived`). Design before the first real dashboard consumer.
- **Pack provenance.** Pack version + model id + fixture hashes + contract version all matter. What's the stored recipe shape?
- **Sandbox / permissions.** Generated packs run with user credentials. Static analysis floor, runtime interception ceiling — where's the line?
