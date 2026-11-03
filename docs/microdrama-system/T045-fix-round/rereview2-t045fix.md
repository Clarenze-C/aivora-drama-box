# T045-FIX round-2 scoped re-review (9720a90..7faef9e)

Reviewer: Claude Sonnet 5.5 standing in for Codex. Worktree detached at 7faef9e, left clean (no stash, only the untracked `.venv` symlink).
Scratch probes (not in repo): `docs/microdrama-system/T045-fix-round/rr2-probes/` (saved with a `.txt` suffix).

## Verdict table

| ID | Verdict | One-line evidence |
|----|---------|-------------------|
| RR-S4 | FIXED (one retry gap, F-1) | late Pod attached, terminated, resolution contradicted, ADJUSTMENT 400000, account total = invoice 500000; red proof 3 fail without janitor change; 3 concurrent sweeps yield exactly one ADJUSTMENT |
| RR-N1 | FIXED | budget service checked first (billing.py ~806), settlement in same tx, `update_with_revision` for window end |
| RR-S1 | FIXED vs ruling; 1 gap beyond ruling (F-5) | all listed forms behave; red proof "DID NOT RAISE EffectDenied" |
| B-S1 | PARTIAL | resolver, floor, sha check, SIGTERM all work; sweep no longer composes the "same attested world" (F-3) and SIGTERM handler is dropped before shutdown (F-2) |
| RR-N5 | FIXED | polls read-back, 2 s floor, deadline stop, zero Comfy calls |
| B-S10 | FIXED with caveats | via main(argv); seam unreachable from CLI; retry/NeedsReconciliation tests OK; red proof; two behaviour changes judged (F-4) |
| B-N7 | FIXED | description, validator message, docstring, test asserting "GLOBAL"/"across ALL prompts" |
| RR-S2 | FIXED | real PG test passed (fsync/synchronous_commit/full_page_writes on, data dir 0700 postgres-owned) |
| RR-S3 | FIXED | up/down/up one episode; seed failure stops server |
| RR-N2 | FIXED | state records data_root; tampered root refused |

## Per-ID evidence

### RR-S4 (money)
- `rendering/janitor.py` `_terminal_podless_lease` (~472) matches a RUNNING owned Pod with no live lease to a terminal lease with `pod_id IS NULL AND create_requested_at IS NOT NULL` by client_token or pod name. `_adopt_late_pod` (~496): FOR UPDATE, re-checks `pod_id` (race guard), `update_with_revision` attach, activation event, sets `contradicted_at/pod_id` only `WHERE contradicted_at IS NULL`, emits contradiction event, opens storage ownership, then stop, terminate, `record_terminate_verified`, `close_storage_ownership`. Called from `_sweep_provider_orphans` ~612.
- `billing.py` `_lease_readiness_in_transaction` ~1059: resolution only short-circuits to BILLED 0 when `contradicted_at IS NULL`. Ingest SQL ~733 includes SETTLED reservations that have a contradicted resolution.
- 0025: update guard trigger allows only NULL->value contradiction columns (set once, must name pod), all attestation columns immutable, DELETE/TRUNCATE still forbidden. Migrations 0001-0024 untouched (only 0025 in diff).
- Tests: `test_a_late_pod_after_a_podless_resolution_is_adopted_terminated_and_billed` (asserts pod_id, terminate_verified_at, DELETE call, ADJUSTMENT 400000, invoice MATCHED, account total == 500000), `..._no_longer_reads_billed_zero`, `..._second_sweep_..._adds_nothing`. All use the real janitor, real BillingRepository/BudgetService; only the HTTP transport is a fixture.
- RED (janitor.py reverted to 9720a90, migration kept):
  `E assert False where False = any(<generator ... adopt_late_pod ...>)`, `E assert None is not None`, `E assert 0 >= 1`; `3 failed, 11 deselected`. GREEN restored: `14 passed in 13.09s`.
- Extra probes (my own):
  - no resolution + sent create: Pod adopted, ADJUSTMENT 400000 posted on ACTIVE hold: OK.
  - 3 concurrent sweeps: no errors, exactly one GPU ADJUSTMENT of 400000: OK.
  - lease with pod_id AND resolution: cannot arise (`resolve_podless_create` refuses once a Pod is attached; adoption needs pod_id NULL).
- Readiness note: after the first ingest, a SETTLED lease reads BILLED reopened=True before invoice match (existing REOPENED semantics, billing.py ~1150). Matches the ruling's "REOPENED".
- Gap F-1 below (failed terminate never retried).

### RR-N1
Budget check precedes any write; resolution + window end + SETTLEMENT in one transaction; replay byte-identical via stored `resolved_at`. Test `test_a_budgetless_repository_refuses_a_podless_resolution_without_writing_it` asserts zero resolution rows, zero SETTLEMENT, window end None.

### RR-S1 (probe results, `rr2-scratch/dsn_probe.py`)
Refused: `postgres://u@prod...`, `host=prod`, `?host=prod` over 127.0.0.1, `hostaddr=10.0.0.5`, `host=prod hostaddr=127.0.0.1`, `[2001:db8::1]`, `localhost.`, relative socket `run/pg`, `host=` (empty), `service=` in URL, `PGHOST=a.example.com,127.0.0.1`, `PGHOST=127.0.0.1,b.example.com`, hostless + `PGHOSTADDR` remote, hostless + PGSERVICE, junk, `127.1`, `LOCALHOST`, `::ffff:127.0.0.1`, `@abstract`.
Pass (correct): `[::1]`, `hostaddr=127.0.0.1`, `/var/run/postgresql`, percent-encoded `%31%32%37.0.0.1` (libpq decodes to 127.0.0.1), `PGHOST=127.0.0.1`, empty DSN with clean env.
Wrongly pass: `host=' 127.0.0.1'` (leading space, stripped; libpq would fail to resolve it, harmless). `host=localhost` with `PGHOSTADDR=10.1.1.1` set, and `host=localhost` with `PGSERVICE=prod` set: PASS (F-5).
RED (canary.py at 9831b2d~1): `Failed: DID NOT RAISE EffectDenied`, `1 failed, 26 deselected`. GREEN: `1 passed`.
Tests call the guard function directly (same function `run_execute`/`run_sweep` call at canary.py ~677/~1179).

### B-S1
- Resolver `_canary_credential_resolver` (canary.py ~100): refuses non-FILE (ENV/VAULT/NONE, test regex "only from a FILE store"), mode not in {0600, 0400} (tested 0644/0640/0604/0666/0777 refused), unregistered/revoked/unreadable as CapabilityUnavailable. Messages carry ref, kind, path, mode only; no value logged. Weakness: `os.stat` follows symlinks and ownership is not checked; the check and `store.resolve` read the path separately (TOCTOU). NIT.
- Poll floor: `poll_sleep` always calls `sleep(2.0)` (~660); default `time.sleep` in `run_execute` and `main` (`injection.get("sleep", time.sleep)`). Test asserts every recorded wait >= 2.0. Fine.
- `sweep`: sha compared immediately after loading the authorization, before any DB query or transport call; missing sha returns 2.
- SIGTERM test passes (Pod GONE, record NOT_CLEAN, "SIGTERM" in reason); SIGINT installed too but untested. Gap F-2.
- Sweep composition changed in dbb29f7 (F-3).
- Verdict PARTIAL because of F-2/F-3.

### RR-N5
canary.py ~751: loop on `world.manager.get`, `poll_sleep` between reads, deadline raises Conflict, then the normal finally runs shutdown + record NOT_CLEAN. Tests: late ports (get_reads>=3, run COMPLETE) and never ports (zero Comfy calls, Pod GONE, DELETE seen, outcome NOT_CLEAN, deadline_hit True). Real path.

### B-S10
- `test_the_full_composed_flow_runs_through_main_argv` drives execute, sweep, invoice, sweep, sweep through `main(argv)`; asserts account `settled == invoice_total`, provider-reported (ACCRUAL/ADJUSTMENT) sum == invoice, `runpod_billing_budget_finalizations >= 1`, reservation SETTLED, replay adds no charge. The raw all-kinds charge sum is not compared (test comments say it double-counts by ledger design). Acceptable.
- Seam: `_injection` is a keyword-only parameter of `main`; `__main__` calls `main()` with none; argparse has no flag and no env path. Not reachable from the CLI.
- Preflight test: transports `calls == []`, `resolver_calls == []`.
- Retry test: 2 submits, one `comfy.queue_prompt` hold, SETTLED at 0, one SETTLEMENT row, 1 FAILED + 1 SUCCEEDED operation. It does not assert a charge on the failed attempt; "stays charged" is reduced to the operation row staying FAILED (lease-covered, so GPU cost is the lease invoice). Weaker than the ruling's wording. SHOULD.
- NeedsReconciliation test: submit_calls == 1, attempts_used 1, ambiguous recorded, Pod GONE + DELETE, terminate_verified_at set. Matches ruling.
- RED (comfy_jobs.py reverted to 9720a90): `assert 1 == 2 where 1 = ...submit_calls` for both retry and global-cap tests; `2 failed, 25 deselected`. GREEN: passes in full suite.
- Behaviour change 1, per-attempt token for attempt_number > 1 (comfy_jobs.py ~449): correct for the canary (retry dispatches). Safe for canary crash recovery (attempt 1 token unchanged; each attempt token deterministic). Caveats: production routing already puts `attemptN` in semantic_key, so tokens for attempt >= 2 change form; any durable attempt-2 row created before this change would no longer be found by token (duplicate dispatch). Fine while nothing live exists. V2 submit (~519) still uses the base token, so V2 retries remain impossible. NIT.
- Behaviour change 2, FAILED lease-covered attempt returns 0 without settling (comfy_jobs.py ~988): needed for hold reuse, but the hold is then never settled when no retry follows. Probe `test_rr2_hold.py` (max_attempts=1, attempt fails): prompt hold left `ACTIVE`, 84000 reserved, past its 10-minute `expires_at`, account outstanding 176400 after the run and sweep; the janitor's unbound-hold sweep only handles lease/stop kinds. In production routing (one hold per attempt) FAILED lease-covered holds previously released at once. SHOULD (F-4).

### B-N7
`canary_authorization.py` field description, validator message, `submit_prompt` docstring, runbook text. Test `test_max_attempts_is_a_global_cap_across_all_prompts`: prompt 2 never submitted, "attempt cap reached". Code already enforced it globally.

### RR-S2 / RR-S3 / RR-N2
- RR-S2: default `/var/lib/microdrama/canary-pg`; `_prepare_durable_root` used by `up` for default and override. Real test run alone (no basetemp): `2 passed in 2.96s` (durable cluster + traversable-parent test). Server is real loopback PG, not 8091/8093.
- RR-S3: `_seed` verifies episode+account, preset, rights on kept data and writes nothing; `up` stops the server on any BaseException after start. Tests use a fake server pointing at the fixture DB, which is acceptable for the seed logic, but they do not restart a real cluster. NIT: a partial first seed (preset/rights recorded, episode transaction failed) makes the next `up` call `record()` again; not tested.
- RR-N2: `down` requires `state.root == --data-root == state.data_root`; tampered test refused with nothing stopped; accept test passes.

## New findings

- F-1 SHOULD. `janitor.py` `_adopt_late_pod`: attach commits before stop/terminate. If terminate fails, the next sweep no longer matches `_terminal_podless_lease` (pod_id set) and falls to the plain orphan path, which only stops. Probe (`test_terminate_failure_then_retry`): first sweep DELETE 503 -> failure `NEEDS_RECONCILIATION`; second sweep `stop_orphan STOPPED`; `terminate_verified_at` stays NULL and the Pod stays EXITED. Storage ownership stays open, so readiness stays PENDING and volume cost keeps accruing. Fix: in the orphan path, if the Pod belongs to a terminal lease with `terminate_verified_at IS NULL`, run the same stop/terminate/verify tail.
- F-2 SHOULD. `canary.py` ~925: `restore_handlers()` is the first statement of the `finally`, before the shutdown, and its comment ("shutdown path has run") is wrong. A second SIGTERM during shutdown kills the process with the default action, possibly mid-terminate with the Pod up. Also the handlers are installed before `_refuse_execute` and not restored if it raises (leaks into the pytest process). Fix: restore after the record is written; ignore repeats during shutdown; install inside the try.
- F-3 SHOULD. `run_sweep` (dbb29f7) builds the provider with `cleanup_guard=lambda ...: None` and skips the live_world gates, where `cleanup_guard` requires a durable owned lease. Ruling asked for the same attested world. The reason (evidence-freshness gate refuses after the run) is valid, but the guard should be shared (extract from `live_world.py` ~412) rather than dropped.
- F-4 SHOULD. FAILED lease-covered hold left ACTIVE (see B-S10). Fix: settle at 0 (or release) when no retry will reuse it, e.g. at prompt end in `submit_prompt`, or keep settling in the non-canary caller.
- F-5 SHOULD (beyond ruling). Guard does not check `PGHOSTADDR`/`PGSERVICE` when `host` is present; libpq lets `PGHOSTADDR` override the connect address. Check them whenever `hostaddr` is absent from the DSN.
- F-6 NIT. `tests/unit/pipeline/test_t045_canary_db.py` now has a module-wide `pytestmark = pytest.mark.db`, so pure unit tests are skipped under `-m "not db"`; one test ends with a dead `monkeypatch.setattr`.
- F-7 NIT. `main` builds `Database(database_url)` twice for preflight; `_terminal_podless_lease` scans all terminal podless leases per Pod (no LIMIT).
- No BLOCKING findings.

## Regression check
- Tests deleted/loosened: none. Removed lines are fixture refactors (`_pod_json`, history body, a `sleep=` default now in `_execute`). No assertion removed.
- SQL changes: janitor ingest WHERE widened (SETTLED + contradicted only); readiness resolution lookup adds `contradicted_at IS NULL`; new adoption queries. Ledger semantics: ADJUSTMENT on a SETTLED reservation (allowed); FAILED lease-covered no longer settles (F-4).
- 0025: only 0025 edited (update trigger replaced by contradict-once guard; delete/truncate triggers kept). 0001-0024 untouched.
- Known O-1/O-2 not re-reported.

## Test runs
- `tests/unit/rendering tests/unit/budget tests/unit/pipeline tests/integration/pipeline tests/integration/persistence` with the two mandated `--deselect`s: `719 passed, 2 deselected, 1 warning in 1325.35s (0:22:05)`.
- The two deselected, run alone without basetemp: `2 passed in 2.96s`.
- Billing ingestion file alone: `14 passed in 13.09s`.
- Red/green runs as quoted above.
- Worktree restored: `git stash list` empty; `git status` shows only the untracked `microdrama/.venv` symlink.
