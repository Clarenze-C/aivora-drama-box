**Note written:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md` (409 lines, v1.0)

Summary:
1. **One migration `A6b-1`** (number assigned at build): guarded `scheduler_ticks`, `scheduler_firings` with `UNIQUE(trigger_id, period_key)`, `scheduler_effect_intents` — full DDL in the note; `schedule_state` (0017) retired as firing source of truth, table kept as history.
2. **Singleton per AR-5:** `pg_try_advisory_lock(0x6D645F7363686564 "md_sched")` on a dedicated per-tick connection via a new `Database.try_advisory_lock` beside the existing `advisory_lock` (`db.py:228-258`); false → skip with zero writes, release-if-acquired in `finally`, crash = session end = release.
3. **Lost ownership** detected by a `pg_locks` check executed on the dedicated connection (proves liveness + ownership); checked per trigger and per sweep → tick ends `ABORTED_LOST_OWNERSHIP`, no new actions start.
4. **Per-trigger effect table:** enqueue schedules and `w03`-cadence are **ATOMIC** (claim + all effects in one transaction); the four multi-transaction direct actions (`w05` dispatch/poll, `w12` sweeps at `service.py:821–834`) are **INTENTS** (claim + PENDING intent committed first; sweep unchanged; intents COMPLETED/FAILED/SUPERSEDED, never deleted).
5. **Recoverability is independent of any marker:** canonical identities (job semantic keys, pod-lease key `:750`, provider operations, janitor uuid5 evidence `:169`) make crash replay a no-op; intents are the record, not the recovery mechanism.
6. **Calendar:** `CalendarTrigger(local_time, tz='Asia/Bangkok')`, `period_key` = local date, 09:00 ICT = 02:00 UTC, DST-free; uniform due rule fires **at most the latest missed period** — no backlog storm; `v3-daily-summary` emits `summary.daily` (+ `buffer.low`/`slo.below` when breaching) atomically with the firing claim.
7. **§6 as SQL:** SLO = V3 `EPISODE_FINAL` APPROVEs in a rolling 7 days vs 1.25/day while `RELEASING`; buffer = distinct future Bangkok dates of approved-unpublished-scheduled episodes (alert < 2); health = last `SUCCEEDED` tick ≤ 3 × interval + errors per tick.
8. **V1 coexistence:** every selector listed with its A1 §7 `workflow_version='v1'` filter/adapter; no V3 production selector exists in phase A, so nothing can bypass STORY/CAST LOCK.
9. **Lock audit + test plan:** 7 audited transaction rows; A-T14 mapped to 4 new test files incl. real SIGKILL of a lock holder and a mid-tick death, plus migration/contract extensions; `make check` + V1 pilot stay green.
10. **7 open questions with recommendations** (schedule_state retirement, health interval source, skip recording, buffer/SLO gating pre-release, A6a payload schemas, heartbeat granularity, single lock namespace).

Ready for the Codex pre-code critique (spec §10, AR-5).
