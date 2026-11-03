# T045-FIX scoped re-review (stand-in for Codex; code by GLM-5.3)

Range `7f857eb..9720a90` (16 commits), read via git; tests run in the isolated worktree at 9720a90.
Reviewer: Claude Sonnet 5.5. Review only; no fixes, no commits, main checkout untouched.

## 1. Verdict: NEEDS CHANGES (narrow)

32 in-scope IDs: 29 FIXED, 3 PARTIAL (B-S8, B-S9, B-N1), 0 NOT FIXED, 0 REGRESSION.
All 29 FIXED items have the ruled fix in the code and a test that goes red on the unfixed behaviour.
There are 4 new SHOULD-FIX findings (RR-S1..S4) and 5 nits. None of them breaks the money path in the
composed flow. RR-S1/S2/S3 are in the canary DB and DSN guards (B-S8/B-S9); RR-S4 is a late-Pod gap
behind A-S1. No assertion was weakened (section 4).

## 2. ID table

Red proofs I ran myself (worktree mutation, then restored with `git checkout 9720a90 -- <file>`; worktree clean
afterwards except the untracked `.venv` symlink) are marked [RED-mine]. Others are the evidence file's own red lines
(section "T045-FIX (2 Nov)" of `microdrama/evidence/T045.md`), or code reading where I say so.

### A (T045-A)
| ID | Status | Evidence |
|----|--------|----------|
| A-B1 | FIXED | `budget/billing.py:565-582` refuses only a skip with no stored same-identity bucket observed at/after the skip. Tests `test_a_skip_closed_by_a_later_observation_no_longer_blocks_verification`, `test_a_skip_with_no_later_closed_observation_still_refuses` (`test_t045_invoice_period.py`). [RED-mine] with the `observed_at >=` clause forced false: `Conflict: the period still contains skipped-open buckets` (billing.py:590). Both the unit test and the e2e `test_sweep_soon_then_later_then_invoice_reaches_billed` go red. |
| A-S1 | FIXED | `billing.py` `resolve_podless_create` (audited row in 0025 `runpod_podless_create_resolutions`, actor/reason/sha checked, `pod_id` set -> Conflict, per-lease unique so replay writes nothing, settles BILLED 0 via fixed receipt id). `leases.py:1167-1186` and `janitor.py:373-387` set `compute_window_end_at` at close when `create_requested_at` is set. Readiness: sent+podless without resolution is PENDING (`billing.py` readiness top). Tests in `test_t045_finality.py`: `test_podless_create_resolution_bills_zero_and_releases`, `..._refused_once_a_pod_is_attached`, `..._requires_actor_and_reason`, `test_replaying_a_podless_resolution_is_a_noop`, `test_a_pod_appearing_after_a_resolution_does_not_double_settle`; `test_t045_timing.py::test_shutdown_of_an_ambiguous_create_records_the_window_end`. Caveats: RR-N1, RR-S4. |
| A-S2 | FIXED | `finality.py` `_schedule_retry` uses persisted `finality_attempts` (0025): 5,10,20..cap 60 min; `_reset_retry_count` after BILLED. `test_finality_backoff_doubles_each_pending_sweep_and_caps_at_one_hour`, `test_finality_attempt_count_resets_once_billed`. Evidence red: `datetime(..0:10) == (..0:5 + 600s)`. |
| A-S3 | FIXED | `settle_billed_lease` is one `db.transaction()` that locks account then reservation, re-reads state, recomputes readiness and sum, and posts through the new `BudgetService.record_usage_in_transaction`. `test_a_concurrent_adjustment_is_never_dropped_by_the_settlement` really races: a second connection holds the account and reservation locks with an uncommitted ADJUSTMENT, the settlement runs in a thread, and the commit lands after 1 s. [RED-mine] with the two `FOR UPDATE` lines removed: `assert 900000 == (900000 + 137000)` (test:872). |
| A-S4 | FIXED | Readiness returns PENDING when `window_start IS NULL AND pod_id IS NOT NULL`. `test_a_pod_without_a_window_start_is_pending_not_billed_zero`. |
| A-S5 | FIXED | Pod-level evidence: distinct MATCHED periods summed across all leases of the Pod vs the total posted across them; event carries `scope: "pod"`. `test_overstatement_evidence_is_pod_level_across_leases_and_periods` (two periods, one with a warm transfer). Evidence red: `KeyError: 'scope'`. |
| A-S6 | FIXED | `record_terminate_verified` writes first (set-once, returns the stored value) and the ownership close reads it back (`leases.py:1119-1126`, `janitor.py:318-324`); ensure path opens ownership idempotently (`leases.py:890-893`); janitor `_sweep_open_ownership` closes at the persisted instant. Tests `test_a_crash_before_the_ownership_write_is_healed_by_a_re_ensure`, `test_a_crash_after_the_terminate_write_is_closed_by_the_janitor_at_the_persisted_instant`. Evidence red: `assert 0 == 1`, `assert None == datetime(..)`. |
| A-S7 | FIXED | `test_billing_repository.py` now asserts RECOVERY allocation + `RECOVERY_PENDING` posting row, a new Runpod reservation blocked (`BudgetExhausted`, match "recovery"), and the provider-reported sum exactly. Passes (1 passed, run by me). Evidence mutation red at :71. |
| A-S8 | FIXED | `SeparateConnectionCreatePods.create_pod` reads `create_requested_at` over a new psycopg connection (`test_create_request_is_committed_before_the_create_call_is_sent`); the old test is renamed `test_release_guard_keeps_the_runpod_hold_for_an_ambiguous_create` and a real-shutdown test was added. |
| A-N1 | FIXED | `ingest(self, query, buckets, allocations=None)` has no `_verified_finality`; `test_public_ingest_has_no_verified_finality_escape_hatch` expects `TypeError`. |
| A-N2 | FIXED | `verify_invoice` -> `_verify_invoice`; `test_per_bucket_verification_is_private` (`not hasattr(BillingRepository, "verify_invoice")`); callers updated. |
| A-N3 | FIXED | Covering query and the readiness gap query both require the BUCKETS query to contain this Pod's bucket and no other Pod's. `test_an_account_scoped_covering_query_is_not_coverage`. Note: an EMPTY query stays valid coverage because the query contract has no pod field (documented in the code); acceptable. |
| A-N4 | FIXED | Straddling bucket raises `SchemaInvalid` (billing.py:599-610). `test_a_bucket_straddling_the_period_edge_is_refused`. |
| A-N6 | FIXED | 0025 backfills `bucket_identity_sha256` from the bucket row (append-only trigger disabled and re-enabled around it), drops the `''` default, adds `CHECK (outcome <> 'MATCHED_ZERO' OR amount_micro_usd = 0)`. `test_migration_0025_backfills_verification_identity_and_drops_the_default`, `test_matched_zero_period_evidence_must_carry_a_zero_amount`. |
| A-N7 | FIXED | `FOR UPDATE OF r` at both sites (`service.py` ~1047, 1063). `test_a_gpu_billing_post_does_not_lock_the_lease_rows` (evidence red: heartbeat UPDATE blocked). |
| A-N8 | FIXED | `finality.py` re-reads reservation state after Conflict and reports RELEASED / SETTLED / pending. `test_a_refused_release_reports_the_truth_not_released`. |
| A-N9 | FIXED | `settle_reservation_for_lease` reads the lease provider and calls `check_finality_pairing`. `test_settle_reservation_for_lease_checks_the_provider_pairing`. |

### B (T045-B)
| ID | Status | Evidence |
|----|--------|----------|
| B-B1 | FIXED | `comfy_jobs.py` `ComfyRenderConfig.lease_covered`; `_settle_if_needed` settles a covered attempt at amount 0 (same receipt id). `canary_render_config` sets `lease_covered=True` (canary.py:184-188). `live_world.py:363-371` raises `PolicyDenied("... must be lease-covered ...")` for any other config; the positive-price gate before it is kept (the hold still reserves at the quote). Pilot untouched: default `lease_covered=False`, pilot/fake paths do not pass through `build_live_benchmark_world`. Tests: composed `test_full_canary_bills_and_releases_the_exact_remainder` asserts account settled == 70,000, accrued == 0, ACCRUAL+ADJUSTMENT sum == invoice, prompt reservation SETTLED with `settled_micro_usd == 0`, again after replay; `test_a_charging_render_config_is_refused_for_a_leased_runpod_pod`. [RED-mine] with the covered branch disabled: `assert 70140 == 70000` (composed test :524). Deviation (documented in evidence): the ruling asked for "sum of all charges"; the test sums ACCRUAL+ADJUSTMENT because the lease SETTLEMENT row is the final amount of those accruals (raw sum 120,000 vs 70,000 by ledger design). I accept this: the account counters are asserted exactly. |
| B-B2 | FIXED | `canary_authorization.py` `pins.image_ref` with `_IMAGE_REF_RE` (explicit registry host + path + `@sha256:<64 hex>`); the invented repo constant and `canary_image_ref` are deleted; the same string goes to `PodLeaseConfig.container_image` and the attestation. `--comfy-endpoint` and `comfy_endpoint=` are gone from `main`, `run_execute`, `compose_canary_world`, `build_live_benchmark_world`. `ComfyHttpClient` is built with no endpoint, emits nothing while unbound, and `bind_pod_endpoint(pod_id, endpoint_url)` requires `== https://<pod_id>-8188.proxy.runpod.net` and rejects rebinding to another Pod (`comfy_transport.py:104-130`); canary binds right after `ensure_pod` and before `/object_info` (canary.py:709-714). All `live_world` gates are still in place (diff shows only additions plus the removed kwarg). Tests: `runpod_transport.created_image == IMAGE_REF`; `test_a_pod_whose_comfy_endpoint_is_not_its_own_refuses_before_object_info` (zero Comfy calls, NOT_CLEAN record); `test_the_comfy_calls_go_to_the_pods_own_proxy_url`; `test_no_cli_flag_can_set_the_comfy_endpoint`; `test_the_comfy_client_binds_only_its_own_pods_proxy_url`. Evidence red lines recorded. See RR-N5 for a real-provider timing risk. |
| B-S2 | FIXED | Validator `max_wall_seconds*1000 <= quote.maximum_runtime_ms` (authorization.py); `_refuse_unaffordable` sums lease hold + prompt holds + storage ceiling + shutdown margin in integers and raises `PolicyDenied("... spend cap")` before the DSN/episode/world steps. Tests `test_a_wall_clock_longer_than_the_quoted_runtime_is_refused_at_load`, `test_holds_above_the_spend_cap_refuse_before_any_reservation_or_transport` (zero transport calls, zero reservations). Composed fixture is now self-consistent (600 s, 92,400 hold). |
| B-S3 | FIXED | Nested try/finally in `run_execute` writes the record even when shutdown or sweep raises; `outcome` COMPLETE/NOT_CLEAN, `not_clean_reason`; `CanaryRunNotClean` -> CLI prints `canary execute STARTED, NOT CLEAN: <reason>; record: <path>`, exit 3 (refusal stays 2). Tests `test_a_failed_shutdown_still_writes_the_record_with_the_pod` (DELETE 503, pod id in record), `test_a_malformed_comfy_body_still_leaves_a_record` (shutdown still ran: Pod GONE). |
| B-S4 | FIXED | 0025 `runpod_billing_ingest_backoff`; janitor skips on `next_ingest_at`, skips a window end inside `settle_lag` except one post-terminate ingest, persists SKIPPED_OPEN/STORED/REPLAYED/FAILED with doubling backoff, reports INGESTED / SKIPPED_OPEN / REPLAYED separately. Tests `test_four_sweeps_on_a_running_pod_make_one_provider_call`, `test_an_ingest_failure_is_persisted_and_backed_off`, `test_sweep_soon_then_later_then_invoice_reaches_billed` (10 min sweep -> 110 min later sweep -> invoice MATCHED -> settle 50,000 -> reservation SETTLED). [RED-mine] with A-B1 reverted the e2e test fails with the skipped-open Conflict. The e2e test discards the first sweep's report (`del first`) and does not assert that a skip row was written, so it relies on the A-B1 mutation to prove it exercises the path; it does (red above). |
| B-S5 | FIXED | `RunpodInvoiceFinality.__init__(db, budget_service, ...)` has no default and raises `SchemaInvalid` on None; `live_world.py:447-452` raises `PolicyDenied` unless `finality.budget_service is budget`; `run_invoice` builds a real `BudgetService`. Tests `test_the_invoice_finality_requires_a_budget_service`, `test_a_finality_with_a_foreign_budget_service_is_refused_by_the_world`, `test_invoice_entrypoint_stores_only_the_evidence_hash` (finalization rows >= 1; replay says "replayed" and adds none). |
| B-S6 | FIXED | Transfer INSERT copies `provider_account_ref` (leases.py:1356-1382). `test_a_transfer_receiver_carries_the_chain_account_ref`. The strict absent-Pod probe is unchanged. (The ruled "warm transfer -> receiver terminates -> Pod gone -> billing_history allowed and ingests" end-to-end test was not written; the receiver-copy test covers the cause, so I count the fix as present.) |
| B-S7 | FIXED | `if value is None` (canary.py ~1033). `test_a_zero_amount_is_not_a_missing_amount` (reaches `run_invoice` with `amount_micro_usd == 0`). |
| B-S8 | PARTIAL | Durable settings are right: `postgres_server_opts(durable=True)` = fsync/synchronous_commit/full_page_writes on; `canary_db up` passes `durable=True, root=data_root`; default `/root/.local/share/microdrama/canary-pg`, root chmod 0700; `down` is `-m fast` and keeps data; fixtures keep the fast settings (default `durable=False`). Tests `test_durable_mode_turns_on_...`, `test_down_uses_a_fast_shutdown_and_keeps_the_data`, `test_up_composes_the_durable_server`. Missing: the default directory cannot be started by the Postgres OS user on this host (RR-S2), and `up` after `down` is not re-runnable (RR-S3). |
| B-S9 | PARTIAL | Exactly-one-episode and `episode_id` match are in `resolve_canary_episode(db, expected=...)` (NotFound on 0, >1, or mismatch); `episode_id` in the authorization; canary DB seeds the deterministic `CANARY_EPISODE_ID`. Order: unaffordable -> loopback -> references -> episode, all before the world is composed, so zero transport calls (tests assert `runpod_transport.calls == []` and zero reservations). The loopback guard has holes (RR-S1). |
| B-N1 | PARTIAL | `_ceil_seconds` and `runpod_billing.map_billing_history` use integer microseconds. But `janitor.py:673-676` (the hourly window rounding the finding named) still uses `until.timestamp() % 3600` and `timedelta(seconds=float)`, and `billing.py:928` still uses `int((end - start).total_seconds())`. My random check (200,000 timestamps) found no off-boundary result, so the impact is nil in practice, but the ruling said no float. |
| B-N2 | FIXED | `--database-url` removed (argparse refuses it, test), DSN only from `MICRODRAMA_DATABASE_URL`; the endpoint part is B-B2. |
| B-N3 | FIXED | `deadline = min(hard_stop, start+max_wall, rights.eligible_until)`; `test_the_rights_eligible_until_bounds_the_deadline` (deadline_utc == eligible_until). |
| B-N5 | FIXED | `down` resolves the state root and refuses unless under `DEFAULT_DATA_ROOT`; docstring fixed. `test_down_refuses_a_state_file_pointing_outside_the_data_root`. Side effect: RR-N2. |
| B-N6 | FIXED | `job_id` equality restored (live_world.py ~481-486) with a corrected comment. `test_a_reservation_bound_to_one_job_cannot_be_spent_under_another`. The guard permits an unbound (`job_id` NULL) reservation, which the canary relies on; that is consistent with the old behaviour. |

### Other checks asked for
- 0025: one file, edited in place; `git diff 7f857eb..9720a90 --stat -- microdrama/migrations` shows only `0025_t045_billing_finality.sql` (+68). 0001-0024 untouched. Migration + schema-catalog tests pass (section 5). New objects (`finality_attempts`, `runpod_podless_create_resolutions`, `runpod_billing_ingest_backoff`, MATCHED_ZERO CHECK, identity backfill) are consistent with the code that uses them.
- A-S3 locking order: account then reservation, the same order `record_usage` uses, so no inversion with concurrent usage posts.
- Pilot: no change to pilot semantics found (defaults `lease_covered=False`, `durable=False`; `build_live_benchmark_world` is the only gate).

## 3. New findings

### RR-S1 (should-fix): the loopback DSN guard is bypassable (B-S9)
`pipeline/canary.py` `refuse_non_loopback_dsn` returns early unless `scheme == "postgresql"`, and only checks `parsed.hostname`.
I ran the pure function (no network) at 9720a90. Accepted: `postgres://u@prod.example.com/db` (valid libpq scheme),
`host=prod.example.com dbname=x` (key/value DSN), `postgresql://127.0.0.1/db?host=prod.example.com` (query `host` overrides),
`postgresql:///db?host=prod.example.com`. Only `postgresql://prod.example.com/db` is refused. Scenario: the operator's shell has the
staging DSN exported as `postgres://...` (a common form); `execute` passes the guard. The remaining protection is the exactly-one-episode and
pinned-episode check, which is real, but the ruling made the loopback check a separate gate. Fix: parse with `psycopg.conninfo.conninfo_to_dict`, refuse any
host/hostaddr that is not loopback or a unix-socket path, refuse an empty/unknown form, and test those four inputs.

### RR-S2 (should-fix): the default canary data root cannot be used by the Postgres OS user (B-S8)
`DEFAULT_DATA_ROOT=/root/.local/share/microdrama/canary-pg`. As root, `EphemeralPostgres.start` creates it and runs `initdb`/`pg_ctl`
through `runuser -u postgres`. On this host `/root/.local` is mode 700 root, and `runuser -u postgres -- test -x /root/.local/share` prints NOT-traversable
(I ran that harmless check). `initdb -D /root/.local/share/microdrama/canary-pg/data` would therefore fail with permission denied. The tests mock `EphemeralPostgres`, so
this was never exercised. Fix: choose a root the postgres user can traverse (for example `/var/lib/microdrama/canary-pg`, chowned to postgres), or
run the server as the invoking user, and add a check in `up` that fails early with a clear message.

### RR-S3 (should-fix): `canary_db up` is not re-runnable on the data it now keeps (B-S8)
`down` deletes the state file but keeps the data (by design). The next `up` reuses the cluster (`PG_VERSION` exists, no initdb), starts it, then runs `_seed` again, which
creates a new season/episode and does `UPDATE episodes SET id=<CANARY_EPISODE_ID>`. The fixed UUID already exists, so this should hit a unique violation after
the server is already started, leaving a running cluster with no state file. If it did not collide it would create a second budget episode, and B-S9 would refuse
every run. Not executed (hard limit); this is from reading `_seed`/`up`. Fix: make `_seed` idempotent (skip when the canary episode exists) or have `up` detect the existing data.

### RR-S4 (should-fix, low blast radius): a Pod that appears after a podless resolution is never billed
After `resolve_podless_create`, the reservation is SETTLED and readiness returns BILLED 0 before any `pod_id` check (`billing.py` readiness top). The janitor's ingest query only takes
reservations in `ACTIVE`/`EXPIRED` (`janitor.py` `_sweep_billing_ingestion`), so a stray Pod attached later is never ingested and its cost is never posted. The ruling says the late Pod
"goes through the existing stray-adoption path"; the test (`test_a_pod_appearing_after_a_resolution_does_not_double_settle`) only proves a second resolution is refused and `settled == 0`. Hold-keeping
reading: when a Pod is attached to a lease that has a resolution, readiness should drop back to PENDING (or ingest should include such leases) so the later bill posts as an ADJUSTMENT. Flag for the owner; at minimum record it as a SPEC-GAP.

### RR-N1 (nit): `resolve_podless_create` commits before it checks the budget service
The resolution row and window end commit in the first transaction; `if self.budget_service is None: raise Conflict` comes after. A budget-less repository leaves a durable resolution and a BILLED-0 readiness
with no SETTLEMENT posted (a replay with a budget service would post it). Check the budget service first. Also the window-end UPDATE bypasses `update_with_revision` (no revision bump).

### RR-N2 (nit): `canary_db up --data-root X` then `down` refuses
`down` compares the state root to the constant `DEFAULT_DATA_ROOT`, not to the root `up` was given, so an overridden root can never be stopped by the tool. Record the allowed root in the state file or accept a `--data-root` on `down`.

### RR-N3 (nit): B-S4 e2e test does not assert the early sweep wrote a skip
`test_sweep_soon_then_later_then_invoice_reaches_billed` does `del first`. Add `assert skipped_rows >= 1` after the first sweep so the test names its own precondition (my A-B1 mutation shows it does go red, so this is hardening only).

### RR-N4 (nit): evidence file is partial
`microdrama/evidence/T045.md` T045-FIX section covers A-* and B-B1/B-B2 only; B-S2..B-N6 rows are missing (expected by the brief; a later session should add red/green lines, and A-N6, A-B1/N3/N4, A-S1/S4 are recorded as "NOT RECORDED").

### RR-N5 (nit, unverified against a real provider): the Comfy bind has no wait for the port
`canary.py:709-714` calls `world.manager.get(pod_id)` right after `ensure_pod` and binds once. `_comfy_endpoint` returns `None` until the Pod's `runtime.ports` shows 8188. If a real Pod reports RUNNING before the
runtime block is populated, the canary ends NOT CLEAN with a billable Pod stopped by the shutdown path. Safe (fail-closed, record written), but it wastes a run; consider a bounded re-read loop within the deadline.

## 4. Weakened or deleted assertions (diff of every changed pre-existing test file)
No assertion was weakened or deleted without an equal-or-stronger replacement. Every removed line:
- `test_t045_canary_composed.py`: removed `assert reservation["reserved_micro_usd"] == 260_400  # 140*1860s` and its comment -> `== 92_400  # 140*(600+60)` (fixture wall clock cut from 1800 to 600 s by B-S2; same arithmetic). Also removed the `comfy_endpoint=` kwargs, `IMAGE_REPO`, the `prompt_pin` import (moved), and the `image_digest` default. Added: account total, ACCRUAL+ADJUSTMENT sum, prompt reservation == 0, and replay re-checks.
- `test_t045_canary_runner.py`: `image_digest` -> `image_ref`, `max_wall_seconds` 1800 -> 600, `RunpodInvoiceFinality(db)` -> with a budget service. Strengthened (finalization rows, replay).
- `test_t045_live_world.py`: `_live_render_config()` gained `lease_covered=True`; `comfy_endpoint=` removed; render config became a parameter.
- `test_live_world.py`: two `comfy_endpoint=` kwargs removed. `test_runpod_transport.py`: `RunpodInvoiceFinality(db)` -> with budget service.
- `test_budget_billing_reconciliation.py`: `verify_invoice` -> `_verify_invoice` (A-N2 rename).
- `test_t045_billing_ingestion.py`: outcome string `REPLAY` -> `REPLAYED` (B-S4 report wording), comment edit; a `DELETE` branch was added to the scripted transport.
- `test_t045_timing.py`: `test_shutdown_of_an_ambiguous_create_keeps_the_runpod_hold` renamed to `test_release_guard_keeps_the_runpod_hold_for_an_ambiguous_create` (A-S8 asked for exactly this); body unchanged.
- `test_billing_repository.py`: additions only (A-S7).

## 5. Test runs (worktree `.../wt-t045fix-rereview`, HEAD 9720a90, from `microdrama/`)
Prefix: `systemd-run --scope --quiet -p CPUQuota=45% env PYTHONPATH=src .venv/bin/pytest -q --tb=short`
1. `$(ls tests/unit/*/test_t045_*.py tests/integration/*/test_t045_*.py) tests/unit/pipeline/test_live_world.py tests/unit/rendering/test_runpod_transport.py tests/unit/budget tests/unit/rendering tests/integration/persistence/test_schema_catalog.py` -> **544 passed, 0 failed**, 1 warning (pydantic serializer warning in `test_billed_zero_matches_an_empty_query_after_the_lag`), 264.78 s.
   This covered the composed canary and the 0025 migration tests.
2. `tests/integration/persistence/test_billing_repository.py` -> 1 passed (A-S7).
3. Red proofs (single tests, `-x --tb=line`): B-B1 1 failed (`assert 70140 == 70000`); A-B1 unit 1 failed and B-S4 e2e 1 failed (skipped-open Conflict); A-S3 1 failed (`900000 == 900000 + 137000`). All mutations were reverted with `git checkout 9720a90 --`; `git status` in the worktree showed only the untracked `microdrama/.venv`.
Not run, by instruction: `make check`, `make pilot`, `canary execute|sweep`, `canary_db`.
Scratch files left: `redproof.sh`, `redproof.log`, `t045-run.log` in the scratchpad.

## 6. Verdict
NEEDS CHANGES (narrow). The money fixes (A-B1, A-S1..S6, B-B1, B-B2, B-S4, B-S5) are in and proven red/green. Before this round ships: fix RR-S1 (DSN guard), RR-S2 and RR-S3 (canary DB can't start / can't restart), and decide RR-S4; finish B-N1 in the janitor. The out-of-scope items (B-S1, B-S10, B-N7, runbook) remain for the later session.
