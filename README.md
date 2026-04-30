# taskboard

LLM-in-the-loop infra dashboard framework. Describe what you watch; Claude inspects your stack, writes source packs against real API responses, and serves a live status page.

Bundled into the `mindframe` agentic-framework plugin as one of its components. Standalone install also works for users who only want a dashboard.

See [CLAUDE.md](CLAUDE.md) for the architecture and [docs/contract.md](docs/contract.md) for design decisions.

## Commands

- `/taskboard:create` — scaffold a new dashboard for the user's stack
- `/taskboard:dev` — iterate: add system, generate pack, capture fixtures, verify

## Run tests

    make test
