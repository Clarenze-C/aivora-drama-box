# Pilot runbook — the offline two-gate mock path (T029)

One command reproduces the whole system offline, from season proposal to
managed fake post:

```bash
cd microdrama
make pilot            # or: PYTHONPATH=src .venv/bin/python -m microdrama.pipeline.demo
```

Outputs land in `out/pilot-demo/`:

- `run-report.json` — every stage (W01–W12), both gate approvals, post ids,
  cost view and the explicit `mock_run: true` label;
- `media/` — the REAL FFmpeg exports (master, burned-caption master, variants,
  hooks, covers, subtitle files), playable with any player;
- `pilot.log` — the same stage lines on stdout.

## What the demo proves (and what it deliberately does not)

| Proven offline | Not claimed (live evidence pending) |
|---|---|
| W01–W12 fire in order through the durable job queue | Real provider quality/rights (T031) |
| Exactly two human gates: Gate 1 scope, Gate 2 package | Real account capability (T032) |
| Episode-one identity lock created by the Gate 2 approval | Real Thai ASR/voice quality |
| Real FFmpeg assembly; playable exports | Real GPU cost/speed |
| Budget ledger: every fake dispatch priced, settled under the cap | Real platform posting |
| Fake posts visibly `*.fake.invalid`, verified via readback | Real comment/DM handling |
| GPU released before the human wait; janitors leave no orphans | Ten-episode qualification |

Every provider is a T007 fake; the offline network guard blocks any
non-loopback connection. Nothing in this path can spend money or act publicly.

## The trigger layer (replaces n8n — operator decision 2026-10-23)

- **Schedules**: `src/microdrama/scheduling/registry.py` holds the W01–W12
  cadence. `python -m microdrama.scheduling` (run by a systemd timer each
  minute) fires due schedules: job schedules enqueue frozen job types with
  period-bucketed semantic keys; the W12 janitors and the W05 render-reconcile
  poll run directly — never queued behind a blocked queue.
- **Webhooks**: `POST /webhooks/membership/{provider}` goes through the T026
  verify→dedupe→interpret path; `POST /webhooks/community/{platform}` records
  the untrusted event in `webhook_events` (deduplicated) and acts on nothing
  until T032 wires verified inbound push.

## Looping the pilot (W03 cadence, W10 social, W11 windows)

The demo is a single linear pass. To exercise the recurring surfaces:

1. Leave the world running (see `make services-up` for PostgreSQL/Redis).
2. Fire the scheduler: `PYTHONPATH=src .venv/bin/python -m microdrama.scheduling`
   (needs `MICRODRAMA_DATABASE_URL`); it discovers due work from durable state.
3. Platform events: `curl -X POST $API/webhooks/community/youtube \
   -H 'x-provider-event-id: <provider-event-id>' -d '{"event":"comment.created"}'`
   — recorded only; community ingest stays provider-pulled.

## Live-readiness blockers (do not skip)

T031 (rights/presets/GPU) and T032 (accounts/publishing/DM) are the gates to
any real effect. The registries only contain clearly-fake records; live routes
refuse first (`EffectDenied` / `PolicyDenied` by design). Do not "help" a
refusal past its gate — qualify the route instead.
