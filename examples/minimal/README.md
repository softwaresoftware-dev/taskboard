# Minimal Example

Smallest mindframe dashboard. Uses only built-in primitive probes — no source packs.

## Run

From the plugin root:

    pip install -e .
    cd examples/minimal
    uvicorn dashboard:app --port 8080

Open http://localhost:8080/.

## What it shows

Two "systems":

- **public-web** — pings `https://example.com` and `https://httpbin.org/status/200` over HTTP. Thresholds trip on non-200 or slow responses.
- **local-host** — a TCP check against `1.1.1.1:53`, plus a `hostname` shell command.

Edit `systems.json`, save, hit the page — next poll cycle picks it up.

## Why this is the baseline

This example uses zero custom packs — everything runs against the built-ins (`http`, `tcp`, `cmd`, `file`). The point is to prove the runtime shape works before layering on source packs. A real deployment adds packs for GitHub, k8s, Stripe, etc., each under their own namespace.
