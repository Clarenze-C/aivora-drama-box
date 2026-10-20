# microdrama — Automated Thai Micro-Drama System (offline build, M0–M4)

This folder is an isolated Python module that implements the software described
in [`docs/microdrama-system/SPEC.md`](../docs/microdrama-system/SPEC.md),
following the task plan in
[`docs/microdrama-system/task_breakdown.md`](../docs/microdrama-system/task_breakdown.md).
Progress is tracked in
[`docs/microdrama-system/task_status.csv`](../docs/microdrama-system/task_status.csv).

> **Status honesty.** Everything here runs in **offline/mock mode**. Fake
> providers prove that the pieces are wired together correctly; they do **not**
> prove video quality, real cost, rights clearance, or that any real platform
> upload works. Those need the live tasks T031–T035, which are out of scope.

## What "offline/mock mode" means

The system has three kinds of dangerous effects, and all three are switched off
by default and *cannot* be switched on in `OFFLINE_MOCK` mode:

| Effect | Example | Default |
|---|---|---|
| `PAID_REQUEST` | calling a paid AI model | off |
| `CLOUD_RESOURCE` | renting a GPU pod | off |
| `PUBLIC_ACTION` | posting to TikTok/YouTube/Facebook/Instagram | off |

Code that could cause one of these must call `settings.require_effect(...)`
first, which raises `EffectDenied` in mock mode (see `src/microdrama/config.py`).

## Step-by-step: run the checks yourself

You only need a Linux machine with Python 3.13, PostgreSQL 16 server binaries,
Redis and FFmpeg installed. **Docker is not required.**

1. Open a terminal and go to this folder:
   ```bash
   cd microdrama
   ```
2. Create the Python virtual environment and install the exact pinned
   packages (this takes a minute the first time):
   ```bash
   make install
   ```
3. Run every offline check (contracts, lint, unit, contract and integration
   tests):
   ```bash
   make check
   ```
   The last line should read `make check: all offline checks passed`.

Individual targets: `make contracts`, `make contracts-check`, `make lint`,
`make test-unit`, `make test-contract`, `make test-integration`. Run
`make help` to list them.

## Test services (PostgreSQL and Redis without Docker)

The tests need a **real** PostgreSQL database, because the budget tests must
prove that two transactions racing to spend the same money are really
serialized by row locks (`SELECT ... FOR UPDATE`). A fake in-memory database
cannot prove that, so none is used.

How it works (`src/microdrama/testing/services.py`):

- When a test first asks for the database, the test suite runs `initdb` to
  create a brand-new throwaway PostgreSQL 16 cluster in a private temporary
  folder, starts it on a random free port bound to `127.0.0.1`, and deletes it
  when the tests finish. It never touches any existing AIVORA database.
- Because PostgreSQL refuses to run as `root`, when the tests run as root the
  server commands are executed as the `postgres` operating-system user via
  `runuser`.
- Only durability settings (`fsync`, `synchronous_commit`, `full_page_writes`)
  are turned off to make tests fast. Locking and transaction behaviour are
  unchanged.
- Redis is started the same way (`redis-server` on a random loopback port,
  persistence disabled).
- If the binaries are missing, database tests **fail** instead of being
  skipped, so missing evidence is never reported as a pass.

Optional overrides: set `MICRODRAMA_TEST_DATABASE_URL` / `MICRODRAMA_TEST_REDIS_URL`
to point at a disposable server, or `MICRODRAMA_PG_BINDIR` to the folder that
contains `initdb`. For manual exploration, `make services-up` starts a
longer-lived pair under `.local/` and prints their URLs; `make services-down`
stops them.

`deployment/compose.local.yaml` is an optional Docker alternative. Its image
tags could not be pulled or verified in the bootstrap sandbox (Docker Hub was
unreachable) and are marked as unverified in the file.

## Verified dependency versions

Installed and tested in the bootstrap sandbox (Ubuntu 24.04, 20 Oct 2026). The
full transitive freeze is in `requirements.lock`.

| Component | Version | Source |
|---|---|---|
| Python | 3.13.16 | system |
| PostgreSQL server/client | 16.15 | Ubuntu `postgresql-16` |
| Redis server | 7.0.15 | Ubuntu `redis-server` |
| FFmpeg / FFprobe | 6.1.1 | Ubuntu `ffmpeg` |
| Thai font for captions | TLWG Loma (`fonts-tlwg-loma-otf`) | system |
| fastapi | 0.150.0 | PyPI |
| pydantic | 2.14.1 | PyPI |
| psycopg[binary] / psycopg-pool | 3.3.6 / 3.3.3 | PyPI |
| redis (Python client) | 8.1.0 | PyPI |
| jinja2 | 3.1.6 | PyPI |
| python-multipart | 0.0.32 | PyPI |
| uvicorn | 0.54.0 | PyPI |
| httpx (tests) | 0.28.1 | PyPI |
| pytest / pytest-timeout | 9.1.1 / 2.4.0 | PyPI |
| ruff | 0.17.1 | PyPI |
| jsonschema (contract tests) | 4.26.0 | PyPI |

## Folder layout (SPEC §3)

```text
microdrama/
  pyproject.toml, Makefile, README.md, requirements.lock
  contracts/        generated JSON Schemas + valid/invalid examples (integrator-owned)
  migrations/       ordered SQL migrations (integrator-owned)
  src/microdrama/
    contracts/      Python source of truth for the contracts above
    config.py       execution mode and effect switches
    core/ persistence/ budget/ research/ story/ references/ rendering/
    editing/ qa/ review/ publishing/ community/ memberships/ analytics/
    api/ workers/   composition roots (integrator-owned registration)
    testing/        test-only helpers: isolated servers, fakes, fixtures
  workflows/n8n/    versioned n8n exports that call internal services
  tests/{unit,contract,integration,fixtures}/
  deployment/       local compose, configuration, runbooks
  evidence/         short redacted evidence notes per task (no secrets/media)
  tools/            developer tools (the AIVORA root .gitignore ignores scripts/)
```

**Documented layout equivalent:** the SPEC places versioned schemas in
`microdrama/contracts/`. Their Python source of truth (Pydantic models,
protocols, hashing) lives in `src/microdrama/contracts/` so it is importable;
`make contracts` generates the JSON Schemas/examples from it and
`make contracts-check` fails if they drift.

**Git note:** the AIVORA root `.gitignore` ignores every folder named `tests/`
or `scripts/` (legacy rules). `microdrama/.gitignore` re-includes `tests/`, and
developer tools live in `tools/` instead of `scripts/`.

## Task ledger convention

The orchestrator uses status `ACCEPTED` (as instructed for this build) for tasks
whose handoff was reviewed, whose tests were rerun by the orchestrator and whose
full suite passed. `task_breakdown.md` §7 lists `DONE` for the same meaning;
`ACCEPTED` is used here in its place.
