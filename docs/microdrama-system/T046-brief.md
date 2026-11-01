# T046 brief — private staging/deployment and proposed domain readiness

Owner: operations, in-session (GLM), 2026-11-01. Dependencies T044/T047 DONE.

## Scope (SPEC §110 + V2-F10/F11)

Authenticated, durable, PRIVATE deployment of the owner app + independent
worker/janitor, with restart/backup/restore/cleanup drills producing evidence.
The proposed `dramabox.aivora.agency` binding (DNS/TLS/public exposure) is
explicitly separate operator work — prepared as a runbook, NOT executed.

## Build pieces

- `src/microdrama/api/serve.py` — `python -m microdrama.api.serve`:
  env-driven (MICRODRAMA_DATABASE_URL/OBJECT_STORE_ROOT), migrates on boot,
  builds the composed world on the WALL clock (`SystemClock`), refuses any
  non-OFFLINE_MOCK mode (staging cannot serve a live composition until
  T045/T031), serves uvicorn loopback-by-default. Subcommands: `create-owner`
  (one-time generated password, 0600 optional file), `health` (compose
  healthcheck + drills).
- `src/microdrama/api/worker.py` — `python -m microdrama.api.worker`: the
  same durable world; runs the composed lane deployments (T028 semantics)
  independently with a janitor sweep cadence; `--once`/`--janitor-only` for
  drills and timers.
- `pipeline/world.py` — registry seeding made restart-idempotent (T046's own
  find: a durable second boot re-recorded version-1 mock presets and
  Conflict-crashed; seeding now only runs when the mock preset catalog is
  absent; regression-pinned in `tests/unit/api/test_serve_entries.py`).
- `microdrama/Dockerfile` — digest-pinned python:3.13-slim + ffmpeg, locked
  requirements, non-root user.
- `deployment/compose.staging.yaml` — app+worker+postgres:16 (digest-pinned),
  named volumes (pg + objects), ports on the host LOOPBACK only, compose
  healthcheck via the serve health command, restart policies.
- `deployment/staging.env.example` (+ gitignored `staging.env`).
- `deployment/staging/drill.sh` — the evidence drill: up → owner bootstrap +
  login → three-step intake over HTTP → FULL restart (postgres included) with
  session + row durability asserts → independent worker drain + janitor sweep
  → pg_dump + object-store tar → restore into a scratch compose project →
  login + season readback on the restored stack → teardown.
- `deployment/staging/DOMAIN-RUNBOOK.md` — operator-only DNS/TLS/Traefik/
  secure-cookie/backup-coverage steps.

## Non-goals

No public exposure, no DNS/TLS changes, no live composition, no real provider,
no paid/public effects (guarded twice: settings mode + effect flags), no
Coolify integration (loopback compose is enough for private staging evidence).
