# Fix round 2 report: DBR-1..3 + T046 drill re-run (2026-11-02)

Per-task report for the brief "Fix round 2 (small): Drama Box re-review
follow-ups DBR-1..3 + T046 drill". Binding rulings: the "Re-review 1 of the
fix round" section of
[T044b2-T046-T047-claude-review-2026-11-02.md](T044b2-T046-T047-claude-review-2026-11-02.md).

**Commits** (branch `feat/microdrama-m0-m4`, NOT pushed):

- `95fef89` — `fix(microdrama): DBR-1/DBR-2/DBR-3 …` (7 files: 4 src + 3 test)
- docs commit (this file + evidence + ledger + HANDOFF) — recorded below in
  the repo history as the follow-up docs commit on the same day.

All work is inside `/root/AIVORA/drama-box`. No network beyond the drill's
digest-pinned base-image pulls (see DBR-6). No live models, no paid calls, no
publishing. Pilot semantics unchanged (the reader this round touches is
unwired from the pilot — verified by re-review 1).

## DBR-1 — create-owner reserves the password file before the owner row

Production (`microdrama/src/microdrama/api/serve.py`):

- `_open_secret_file` at `serve.py:97` — the DB-11 primitive (`O_CREAT|O_EXCL`,
  0600), renamed from `_write_secret_file` because the open and the write now
  happen at different times.
- `_create_owner` at `serve.py:109-150` — new order: reserve the target
  BEFORE `world.auth.create_owner`; an existing target is exit 4 with ZERO
  owner rows and the file untouched; a failed creation closes and unlinks the
  empty reservation (best-effort `contextlib.suppress(OSError)`) and
  re-raises; the password is written into the already-open fd only after the
  row exists.

Tests (`microdrama/tests/unit/api/test_serve_entries.py`, real Postgres):

- `test_create_owner_refuses_an_existing_password_file_and_creates_no_owner`
  (`:177`) — **RED** on the old code: `AssertionError: an existing target
  must leave no owner row / assert 1 == 0` (the owner was committed first);
  **GREEN** after (exit 4, 0 owners, file content unchanged).
- `test_create_owner_writes_password_0600_to_a_fresh_target` (`:197`) — green
  pin before and after (owner row + 0600 file + password with newline).
- `test_create_owner_failure_after_the_reservation_leaves_no_file_and_no_owner`
  (`:215`) — green pin of the new cleanup path (forced
  `AuthService.create_owner` failure → no file, no owner).
- The DB-11 unit `test_secret_file_is_created_0600_and_never_overwritten`
  (`:148`) now exercises the renamed `_open_secret_file`; same semantics
  (0600 from the first instant, never overwritten).

## DBR-2 — the reader's overlap check mirrors the EDL crossfade rule

Production:

- `microdrama/src/microdrama/contracts/media.py:119` — new shared helper
  `video_overlap_allowed_ms(nxt)` (crossfade → `transition_ms`, else 0);
  `EditDecisionList._timeline` (`:152`) now uses it — one rule, no
  duplication.
- `microdrama/src/microdrama/qa/continuity_sources.py:164-184` — the DB-3
  check drops a window only when the overlap exceeds that allowance. Because
  `EpisodeContinuityExpectations` pins NON-overlapping ordered windows
  (`qa/continuity.py:483-490`), an allowed crossfade clamps the incoming
  window's start to the previous window's end (the crossfade interval stays
  with the outgoing shot); a clip entirely inside the crossfade
  (`transition_ms` may equal the clip duration) has no window of its own →
  None (dropped evidence, never silently skipped).

Test (`microdrama/tests/integration/validation/
test_t047_v2_composed_acceptance.py`):

- `test_reader_yields_full_expectations_for_a_crossfade_edl` (`:866`) — a
  contract-valid EDL (200 ms CROSSFADE starting 200 ms inside the previous
  window) — **RED** on the old code: `AssertionError: a contract-valid
  crossfade EDL must compose expectations / assert None is not None`;
  **GREEN** after: full expectations, windows `[(0, 3800), (3800, 4800)]`.
- The false "overlap is unconstructible" comment in
  `test_reader_fails_closed_on_unmapped_or_dropped_video_clips` (~`:840`) is
  corrected: overlap IS constructible through the contract (exactly
  `transition_ms` on a CROSSFADE); only beyond-allowance overlap is
  defense-in-depth.
- Doc note corrected in `microdrama/evidence/T047.md` (the DB-3 note now
  states the real constructible overlap shape).

Note for the re-reviewer: the clamp is forced by the expectations contract —
the ruling's "allowed overlap" defines when NOT to return None; with overlap
allowed, non-overlapping ordered windows leave only "incoming window starts
at previous end" as a representable shape. Documented in code and evidence.

## DBR-3 — advisory_lock wait is bounded and fails typed

Production (`microdrama/src/microdrama/persistence/db.py:221-250`):
`advisory_lock(key, timeout_s=120.0)` runs `SET lock_timeout = '<n>ms'` on
the lock connection before `pg_advisory_lock` (int validated positive and
finite locally; SET takes no bind parameters over the extended protocol);
`LockNotAvailable`/`QueryCanceled` map to a typed retryable
`ServiceUnavailable` naming the key: `advisory lock <key> not acquired
within <n>ms`. The only caller (`pipeline/world.py:509`, DB-10 first-boot
seeding) is unchanged and now bounded by the 120 s default.

Test (`microdrama/tests/integration/persistence/test_migrations.py:356`):
`test_advisory_lock_times_out_with_a_typed_error` — another session holds the
key; the caller asks for 0.5 s — **RED** on the old code: `TypeError:
Database.advisory_lock() got an unexpected keyword argument 'timeout_s'`
(the unbounded wait itself cannot be shown red without hanging a runner);
**GREEN** after: `ServiceUnavailable` matching `advisory lock 4972026112`,
wait measured within `[0.4, 5.0]` s.

## DBR-6 — T046 drill re-run after DB-10

`bash deployment/staging/drill.sh` (no `--keep-up`), under CPUQuota45%,
2026-11-02T09:29Z. Local Docker was allowed for this drill only: loopback
compose on 8093, OFFLINE_MOCK, $0; the app image had been pruned since
2026-11-01, so the digest-pinned bases were pulled again (pinned digests —
no drift). Ports 8091/8092 untouched by anything left running; the
`arisa-sfw-*` containers were never touched.

**7/7 PASS, exit 0** — transcript
`microdrama/deployment/staging/drill-logs/20261102T092941Z.log`:

1. `PASS: stack up, /health OK on 127.0.0.1:8093`
2. `PASS: owner login 303, session cookie durable-side issued`
3. `PASS: intake submitted over HTTP; status + workbench render (season 6d8ace7c-…)`
4. `PASS: full restart — session survives, season+intake rows identical`
5. `PASS: worker drained + janitor swept` (cycles 1, sweeps 1, failures 0)
6. `PASS: backup written (356K sql + 12K objects)`
7. `PASS: restored stack — health OK, owner login OK, season 6d8ace7c-… readable`

Teardown verified: no `microdrama-*` containers or compose projects remain;
named volumes `microdrama-staging_staging-pg` / `_staging-objects` kept. No
step FAILed; the script was not modified.

## Gates (under `systemd-run --scope -p CPUQuota=45%`)

- `make check` — last line: `make check: all offline checks passed`, exit 0.
  Counts: **2,611 unit** (45:51), **462 contract** (4:51), **221
  integration** (37:24, part of the same `make check` run). Unit/contract
  counts re-run standalone after the check's tail truncated their summary
  lines; the integration summary and final line are from the check itself.
- `make pilot` — exit 0: W01–W12, exactly two HUMAN gates, 16 local exports,
  `settled micro-usd: 303000 (fake providers; no real money)`.

Focused receipts along the way: `test_serve_entries.py` 11/11 (3 new),
`test_t047_v2_composed_acceptance.py` 11/11 (1 new), `test_migrations.py`
10/10 (1 new); initial red run `3 failed, 2 passed` (one red per finding).

## Ledger and handoff

- `docs/microdrama-system/task_status.csv` — T046 and T047 rows: evidence
  columns extended with this round (commit `95fef89`, drill receipt, suite
  counts); caveat columns now read "ONE scoped re-review of DBR-1..3 only
  remains (second and last round, then operator push decision)".
- `docs/microdrama-system/HANDOFF.md` — "Independent reviews" and "What
  remains, in order" point at commit `95fef89` and the single remaining
  scoped re-review; the "last full green" receipt updated (2,611/462/221).
- Evidence appended: `microdrama/evidence/T046.md` (DBR-1, DBR-3, drill
  section headed as the re-run after DB-10) and
  `microdrama/evidence/T047.md` (DBR-2 + the DB-3 note correction).

## Not done, with reasons

- Nothing in the brief's work list was skipped. Two judgment calls to flag:
  - The DB-11 unit test was moved onto the renamed `_open_secret_file`
    (same assertions) because the prod helper it used no longer exists in
    that form; DB-11 semantics are additionally pinned by the new
    `_create_owner` tests.
  - The DBR-2 "beyond the allowance still returns None" branch is NOT
    test-seeded: `EditDecisionList` rejects beyond-allowance overlap at
    validation, so such a row cannot come from a model-validated manifest;
    the branch stays fail-closed defense-in-depth (comment in the test).
- The report's `--out` file was not named in the brief, so it lives here at
  `docs/microdrama-system/T046-T047-dbr-fixes-report-2026-11-02.md`.
