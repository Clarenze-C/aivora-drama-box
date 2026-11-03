# Review: T045-B (R9/R10/R11) - commits 1a60fc5..7f857eb, reviewed at 7f857eb

Reviewer: Claude Sonnet 5.5 standing in for Codex (code written by GLM-5.3). Review only; nothing fixed, no commits.
Scratch repro tests (untracked, review worktree only, not for merge):
`microdrama/tests/integration/pipeline/test_zz_review_probe{,2,4}.py`,
`microdrama/tests/unit/rendering/test_zz_review_transfer.py`, `microdrama/tests/unit/pipeline/test_zz_review_budgetless.py`.
(`..._probe3.py` is a harmless print-only probe; I could not delete it, the sandbox held `rm`.)

## Tests run (worktree, CPUQuota=45%, no network)
- Focused unit set (test_t045_live_world, test_t045_canary_runner, test_live_world, test_t045_billing_ingestion, test_t045_quote_attestation, test_runpod_transport): **65 passed**.
- `tests/integration/pipeline/test_t045_canary_composed.py` (real ephemeral PG): **6 passed**.
- My probes (all intentionally red where they show a finding): see each finding.

## Summary of verdict (details below)
NEEDS CHANGES. 2 BLOCKING, 10 SHOULD-FIX, 7 NIT.

## BLOCKING

### B-B1 - Double count: the canary books the same GPU time twice (Comfy prompt settlement + Pod invoice)
- `pipeline/canary.py:190-191` (`canary_render_config` prices the Comfy render at the hourly GPU-second rate) together with `pipeline/canary.py:493` (a `comfy.queue_prompt` hold per prompt) and the Pod lease hold. Test that should have caught it: `tests/integration/pipeline/test_t045_canary_composed.py:~455-462` asserts only `reservation["settled_micro_usd"] == GPU_BUCKET` on the *pod.lease* reservation.
- Scenario: composed canary, one prompt, invoice = GPU 50,000 + CPU 10,000 + disk 10,000 = 70,000 micro-USD, matched and BILLED. Final ledger:
  - `pod.lease` SETTLED 50,000 (GPU bucket), CPU 10,000 + disk 10,000 as `CPU_STORAGE_TRANSFER` ADJUSTMENTs;
  - **plus** `comfy.queue_prompt` reservation SETTLED 140 (measured execution seconds x 140 micro-USD/s) as a separate `GPU_GENERATION` SETTLEMENT charge.
  - `budget_accounts.settled_micro_usd = 70,140` against a provider invoice of 70,000. The Pod's GPU time is in the invoice bucket *and* in the prompt settlement.
  - With a real 5-minute prompt on a 504,000 micro-USD/h GPU the overstatement is ~42,000 micro-USD, i.e. the whole execution portion of the GPU bucket counted twice. It shrinks the episode's headroom and makes the books disagree with the invoice (the bar says no double count).
- Reproduced: `test_zz_review_probe.py::test_probe_money` (printed output): `RESERVATIONS ... comfy.queue_prompt SETTLED reserved 84000 settled 140` and `ACCOUNT {... 'settled_micro_usd': 70140}` vs invoice 70000. The composed test's own assertion (`settled == GPU_BUCKET`, comment "exactly the GPU bucket settled") passes with the defect present because it looks at one reservation, not the account total or the charge sum.
- Fix direction: decide the canonical GPU cost source for a Runpod canary. Either price the render at 0 / mark prompt settlement non-cost for Runpod-leased renders (the Pod bill is the only GPU cost), or have the prompt charge reconcile against, not add to, the bucket allocation. Then assert `sum(charges) == invoice total` and `account.settled == invoice total` in the composed test (and the replay step).

### B-B2 - `canary execute` cannot work against a real provider: Comfy endpoint and Pod image cannot be supplied
- `pipeline/canary.py:850` (`--comfy-endpoint`, default `https://comfy.invalid`), `canary.py:456-468` (world, and so `ComfyHttpClient`, composed with that fixed endpoint *before* the Pod exists), `canary.py:93-94` (`canary_image_ref` = `microdrama-canary@sha256:<digest>`), runbook lines 151, 163.
- Endpoint: the runbook tells the operator to pass `https://<pod>-8188.proxy.runpod.net`, but the Pod id exists only after `ensure_pod` inside `execute`. The provider already computes the right URL (`runpod_transport.py` `_comfy_endpoint` -> `PodInfo.endpoint_url`), the runner never uses it. As written the operator cannot give a correct value; a wrong/placeholder value means `/object_info` goes to `comfy.invalid` (or, if mistyped, to an arbitrary host - see B-N2).
- Image: the authorization pins only the digest, and the runner invents the repository `microdrama-canary`. A real `create` would send `image: "microdrama-canary@sha256:..."`, which resolves to `docker.io/library/microdrama-canary` (does not exist). The attested image is fictional by construction, so the "pinned image" gate is satisfied by a name no registry serves. The fixtures hide this by echoing the same string back.
- Spec R11 says the resolver is T031's job; this finding is independent of the resolver. Without a fix, T031 cannot execute the runbook as written.
- Fix direction: take the full image reference (registry/repo@sha256:digest) in the authorization and pin it; derive the Comfy base URL from the created Pod's `endpoint_url` (assert it equals `https://<pod_id>-8188.proxy.runpod.net`) and drop the free `--comfy-endpoint` flag (or make the client's endpoint late-bound from the lease handle).

## SHOULD-FIX

### B-S1 - CLI `execute` is wired to the refusing resolver, a no-op sleep and no usable janitor backstop
- `canary.py:898` (`credential_resolver=_refusing_resolver`, hard-coded in `main`), `canary.py:423` (`sleep` default `lambda _s: None`, `main` never passes one), `rendering/janitor.py:704-745` (standalone janitor `main`: `resolve_pod_provider` "structurally disabled until T031", `SyntheticUsageFinality`, `allowed_gpu_types=frozenset()`).
- Operability answer to your question: there is **no path** to resolve `credref:runpod-drama-box-canary` (or any credref) from a FILE store. `main execute` always raises `EffectDenied` at the first credential use (`ensure_pod`). Only tests inject a lambda. The spec defers the real resolver to T031, so I rate it SHOULD-FIX, but the runbook presents the three commands as runnable "exactly as T031's packet must state them".
- Worse, if a resolver were bolted on: the poll loop (`canary.py:576-581`) would call `world.comfy.poll` with **no delay** until the deadline (hot loop against the Pod's ComfyUI and the DB).
- The "janitor is the backstop" claim is empty for a real run: after `execute` exits (crash, SIGTERM - default SIGTERM skips `finally` - or SSH drop) nothing an operator can run stops/terminates the live Pod or ingests billing; the stand-alone janitor cannot compose the live provider, and the in-process janitor dies with `execute`. No `canary sweep`/`janitor` subcommand exists. The post-run billing ingest and "next sweep settles BILLED" in the runbook (line ~184) likewise have no runnable entry.
- Fix direction: a documented resolver (file store under an operator-owned path, names only in args), a real `time.sleep` default with a floor, a `canary sweep` command composing the same attested world, and SIGTERM -> run `shutdown`.

### B-S2 - `max_wall_seconds` and `max_spend_micro_usd` are not tied to the quote; the spend cap is never enforced
- `canary_authorization.py:155-177` (validators), `canary.py:176-187` (`lease_ttl_ms = max_wall_seconds*1000`), `live_world.py:119-129` (exposure ceiling computed from `quote.maximum_runtime_ms` only).
- Scenario: quote `maximum_runtime_ms=600_000`, `maximum_exposure=2,000,000`; authorization `max_wall_seconds=86_400`. Preflight and execute accept it; the lease hold and storage run for 24 h, i.e. far past the runtime the exposure ceiling was proven for. The composed fixture itself does this (1,800 s wall vs 600 s quoted runtime; lease hold 260,400 vs the 84,000 the quote bounds).
- `caps.max_spend_micro_usd` is compared only to the quote's exposure and the episode cap (`canary.py:293`); nothing compares the actual holds (lease + prompts + storage + shutdown reserve) to it, despite the spec text "spend ... including storage and the shutdown reserve".
- Reproduced (acceptance of the inconsistent document): `test_zz_review_probe2.py::test_wall_vs_quoted_runtime` prints `lease_ttl_ms 86400000 quoted runtime ms 600000` and passes the validators.
- Fix direction: require `max_wall_seconds*1000 <= quote.maximum_runtime_ms`, and at execute require total reserved (lease + prompt holds + storage ceiling + shutdown margin) `<= caps.max_spend_micro_usd`.

### B-S3 - A shutdown/provider failure (or any non-MicrodramaError) leaves no canary record and reports "refused"
- `canary.py:683-725` (`finally` runs shutdown, then janitor, then record write; an exception in `shutdown` or `sweep` skips `_write_canary_record`), `canary.py:938-940` (`main` prints "refused" for any MicrodramaError).
- Scenario: stop succeeds, DELETE returns 503 (`NeedsReconciliation`). Pod left stopped-but-billing (storage), exception propagates out of `run_execute`, no record file (no pod id, lease id, client token), CLI prints `canary execute refused: ...` and exits 2 although a Pod was created. A non-Microdrama exception (`ValueError`/`KeyError` from a malformed ComfyUI body) also skips the record (shutdown still runs via `finally`).
- Reproduced: `test_zz_review_probe2.py::test_shutdown_failure_leaves_no_record` - output `EXC NeedsReconciliation Runpod effect response is ambiguous / records: [] pod state EXITED`.
- Fix direction: write the record (pod id, tokens, reservation ids, "shutdown failed") in a nested `try/finally` before re-raising, catch broad exceptions around post-run steps, and print a distinct "STARTED, NOT CLEAN" outcome.

### B-S4 - Janitor billing ingestion has no backoff for in-flight Pods or failures, reports "INGESTED" for skipped-open buckets, and makes A-B1 reachable on the main path (interacts with A-B1, A-S2)
- `janitor.py:540-632`. The "backoff" it relies on is `pod_leases.next_finality_check_at`, which only the *settlement* path writes (`rendering/finality.py:164-179`). For a running Pod (no terminal lease yet), and for any ingestion that fails (`MicrodramaError`/`ValueError` branches, 580-602), nothing paces the next call.
- Reproduced (running Pod, 4 sweeps 20 s apart): `test_zz_review_probe2.py::test_ingest_each_sweep_for_running_pod` -> `billing calls 4 query rows 4` (one provider call and one UNKNOWN query row per sweep).
- The action is labelled `INGESTED` with `detail "1 bucket(s) stored"` (`janitor.py:612-617`) using `len(mapped.buckets)`, although `BillingRepository._classify` skipped every open bucket (nothing stored). The canary record's `janitor_summary.billing_ingests` therefore overstates.
- Interacts with **A-B1**: the composed test hides it because shutdown stamps a 5-minute backoff. Any janitor sweep >5 min after terminate but before the bucket is `settle_lag` past its end writes skipped-open rows, and the later invoice is refused forever. Reproduced: `test_zz_review_probe4.py::test_early_sweep_then_invoice` (sweep 10 min after the run, another 2 h later) -> `Conflict: the period still contains skipped-open buckets; retry once they settle` at `billing.py:563`. A canary 12:00-12:31 swept at 12:40 is the ordinary schedule.
- Also failures are only appended to the in-memory `JanitorReport`; no evidence row or backoff is persisted ("state recorded" is not true for the `ValueError` path). The hold is kept (fail-closed), but the endpoint is re-hit every sweep.
- Fix direction: persist an ingest-attempt backoff per pod (success, replay and failure), skip pods whose newest bucket end is within `settle_lag` of now, and report stored vs skipped-open separately.

### B-S5 - A `RunpodInvoiceFinality` with no budget service is accepted by `live_world`, and `canary invoice` runs without one: ledger side of ingest/verification is skipped
- `live_world.py:428-432` (`billing if isinstance(billing, RunpodInvoiceFinality)` is used as-is, no check that `billing.budget_service` is the world's `budget`), `canary.py:809` (`run_invoice` builds `RunpodInvoiceFinality(db)`).
- Effect: `BillingRepository.ingest` calls `budget_service.reconcile_provider_allocation_in_transaction` only `if self.budget_service is not None` (`billing.py:375`), and invoice verification calls `record_provider_invoice_verification_in_transaction` only likewise (`billing.py:436, 732`). A world composed with a budget-less finality ingests allocations that never reach the ledger (lost charge); the CLI `invoice` writes INVOICE_VERIFIED rows but no `runpod_billing_budget_finalizations` row, and the replay path returns early so it can never be added later. (`runpod_billing_budget_finalizations` count after the composed flow was 0 in my probe.)
- Reproduced (world side): `test_zz_review_budgetless.py` -> `janitor finality budget_service: None`.
- Fix direction: refuse a finality whose `budget_service` is None or differs from `budget`; pass a `BudgetService` into `run_invoice`.

### B-S6 - The lease transfer insert does not copy `provider_account_ref`, so a transferred chain cannot be billed once the Pod is gone (R10 gap)
- `rendering/leases.py:1304-1327` (transfer receiver `INSERT` omits `provider_account_ref`; only the claim insert at `leases.py:765-783` was updated). Probe `runpod_billing.py:67-77` needs ONE row with pod id + owned tag + account ref + `terminate_verified_at`; `terminate_verified_at` is stamped on the *final* (receiver) lease, which has a NULL ref.
- Scenario: lease A (ref set) warm-transfers to B, B shuts down and terminates. The absent-Pod probe finds no qualifying row -> `billing_history` raises `PolicyDenied` forever; the hold is kept but the cost is unreadable. The queries that treat NULL as "any account" (`%s::text IS NULL OR ...`) also become unscoped for B (A-N3 adjacency). The probe correctly refuses rows lacking any of the three (good), but a legitimate chain fails it.
- Reproduced: `test_zz_review_transfer.py::test_transfer_receiver_keeps_account_ref` -> `root ref acct:runpod-review receiver ref None`.
- Fix direction: copy `provider_account_ref` (and any other claim-time identity) on transfer; have the probe accept any lease of the chain.

### B-S7 - `canary invoice --amount-micro-usd 0` is rejected, so MATCHED_ZERO cannot be recorded from the CLI
- `canary.py:904-915` (`if not value` treats `0` as missing).
- Reproduced: `test_zz_review_probe2.py::test_cli_invoice_zero_amount` -> stderr `canary invoice requires --amount-micro-usd`, rc 2. A billed-zero period (an R5 case) is unreachable by the operator entrypoint.
- Fix: `value is None` for the integer.

### B-S8 - The canary ledger lives in a throwaway cluster with `fsync=off`, `synchronous_commit=off`, `full_page_writes=off` under `/tmp`
- `tools/canary_db.py:~150-168` -> `microdrama/testing/services.py:118-122` (`EphemeralPostgres`, `keep=True`, `mkdtemp(prefix="microdrama-pg-")`, auth `trust`).
- The reservation is committed before the Pod create (the "durable before effect" invariant). With `synchronous_commit=off` a postgres crash loses recently committed rows (reservation, lease claim) while the Pod exists and bills; with `fsync=off` an OS crash can corrupt the cluster; `/tmp` can be cleaned on reboot, destroying the only ledger of a paid run. `down` stops with `-m immediate`.
- Fix direction: for the canary use durable settings (fsync/synchronous_commit on), a stable non-`/tmp` data dir, and keep the DSN out of world-readable state if it ever gains a password.

### B-S9 - `execute` charges "the oldest episode with a budget account" of whatever DB it is pointed at
- `canary.py:230-242` (`resolve_canary_episode`: `ORDER BY e.created_at LIMIT 1`), `canary.py:865` (DSN from `MICRODRAMA_DATABASE_URL`).
- If the operator's shell has the staging/production DSN exported (the usual case), the canary reserves and settles against the oldest real episode. Nothing asserts the DB is the canary DB (no marker row, no "exactly one episode" check); the runbook only says it "must not be shared".
- Fix direction: refuse unless exactly one episode with an EPISODE account exists, or require a canary-DB marker written by `canary_db.py up`.

### B-S10 - Test gaps that let B-B1/B-S1/B-S5 through
- The composed test drives `run_execute`, not `main()` / the `canary execute` entry point (`grep main(` in both test files: none); the CLI wiring (resolver, endpoint, sleep) is untested.
- It never asserts the account total or sum of charges against the invoice (B-B1), nor `runpod_billing_budget_finalizations` (B-S5).
- `test_preflight_validates_...` does not inject transports or assert zero calls / no resolver use (only the construction test in `test_t045_live_world.py` does); the sha/hard-stop/quote/mode refusals use a failing transport, good, but only on paths that raise before any world exists.
- No failed-attempt, retry (>1 attempt per prompt, hold reuse) or ambiguity (`NeedsReconciliation` during submit) canary test, although `submit_prompt` (`canary.py:556-616`) reuses one prompt hold across attempts.
- Stubs do not echo auth headers (checked; they ignore `headers`) - fine.

## NIT

- **B-N1** `budget/billing.py:147-149` `_ceil_seconds` uses `int(delta.total_seconds() * 1_000_000)` (float). A sub-microsecond float error truncates (e.g. 2.000001 s can read 2000000 -> 2 s instead of 3). Weight-only (conservation holds), but use `delta // timedelta(microseconds=1)`. Same in `janitor.py:571-575`: `until.timestamp() % 3600` and `timedelta(seconds=float)` can land 1 microsecond off the hour boundary and request an extra open bucket; use integer arithmetic.
- **B-N2** `comfy_transport.py:93,155` / `canary.py:850`: the Comfy bearer token is sent to whatever `--comfy-endpoint` says (no https or host check); `--database-url` puts the DSN in argv. Validate the host against the created Pod (see B-B2).
- **B-N3** `canary.py:451-454`: the deadline is `min(hard_stop, start+max_wall)` and ignores `quote.expires_at` and `rights.eligible_until`; a run that starts just before either expires keeps spending past them.
- **B-N4** `canary.py:259-267, 650`: the "`/object_info` digest check" compares the locally computed digest of the mapped template to the pin (already enforced in `live_world.validate_registry_evidence`); the Pod contributes only class presence. This is the documented R10 limitation, but the record/runbook should not call it a digest of the Pod's schema.
- **B-N5** `tools/canary_db.py:~190`: `down` trusts `root`/`port` from the state file (kill via `pg_ctl -m immediate` of whatever cluster it names) and the docstring says "discard the cluster" while the code keeps the data. It never touched 8091/8093 or any container (OK), and it does not delete anything else (OK).
- **B-N6** `live_world.py:455-460` dropped `reservation["job_id"] != authorization.job_id`; the operation row (`reservation_id` + `job_id` match) still binds it, and the `/object_info` branch adds the episode check. The comment at `live_world.py:462-464` says "one prompt hold shared by its bounded prompt jobs" but the runner reserves one hold per prompt index (`canary.py:490-499`); align the comment.
- **B-N7** `caps.max_attempts` is enforced as a *global* attempt cap (`canary.py:565`), docs say "per prompt". Stricter, so safe; make the wording match.

## Answers to the focus list

1. **live_world (R9): OK.** Every earlier gate is still present and ordered (mode, PAID/CLOUD effects, public actions, credref names, then new `BillingRepository` isinstance gate, then attestation currency, quote cross-check, ceiling, namespace, **account label**, image, GPU, registry evidence). `SyntheticUsageFinality` is not a `BillingRepository` and is refused (`test_a_world_built_with_a_synthetic_finality_is_refused`); `billing` is a required kwarg; construction makes zero transport/credential calls (tested with failing transports and a throwing resolver). The Comfy guard changes do not loosen a gate: the key-equality check still covers `/prompt`, `/history*`, `/queue` (the only paths the client sends with a key besides `/view`, whose key is `node:filename` and previously could never equal a prompt id), and the `/object_info` read now also requires the job's episode to equal the reservation's. Exception: B-S5 (budget-less finality accepted).
2. **`derive_allocations`: conservation holds.** Weights are now strictly positive (`_ceil_seconds` min 1; zero-second ownership rows dropped), `largest_remainder` splits any signed delta exactly, so GPU/CPU/disk allocations sum to the bucket component per bucket. A dropped zero-second owner's share goes to the other owners, or to `recovery_pool` when existence is uncovered / no weights remain (blocks paid dispatch, fail-closed). Per-lease ceilings can make `covered` exceed `existence_seconds`; that only shifts weights, never the total. See B-N1.
3. **janitor:** the `ValueError` catch fails closed (nothing is advanced, skipped or settled; hold kept) but records only in-memory state and does not back off (B-S4). Effect-gating is at the provider (`billing_history` now `require_effect(CLOUD_RESOURCE)`), only the configured owned tag, only pods with reservation `ACTIVE/EXPIRED`, window = chain start to the later of window end / terminate, rounded up to the hour; EMPTY/UNKNOWN are recorded as UNKNOWN queries (`runpod_billing.py:95-115`), never as zero. Rounding up only widens the request; it cannot exclude charged time (the start is not rounded down and relies on the provider snapping). A stopped-not-terminated Pod's post-stop disk time is fetched on the next pass because `window_end` uses the later of stop/terminate and ingestion repeats until settled.
4. **Absent-Pod `billing_history`: tight but incomplete.** A row must match pod id + owned tag (namespace) + attested account + `terminate_verified_at` (`runpod_billing.py:67-77`); a row missing any, or for another namespace/account, does not unlock; no probe -> refused (tests exist). Gap: transfer receivers (B-S6).
5. **`runpod_billing.py` mapping: exact.** Amounts come from `Decimal(str(value))` via `json.loads(parse_float=Decimal)` (`runpod_transport.py:249,566`), no float; component/total mismatch -> DISPUTED bucket with reason; replay (same record hash as the stored latest revision) adds nothing; changed amount -> revision N+1 with prior links so only the delta posts (tested). Negative or sub-micro amounts raise and fail closed. (The test fixture builds amount strings with float formatting, harmless.)
6. **R10 attestation: OK.** quote id, USD-only currency, persistent volume, storage exposure and account label are cross-checked both ways (`live_world.py:84-93`, tested per field), each mismatch denies in `build_live_benchmark_world` before any transport; the create-time volume bound is enforced (`runpod_transport.py` `request.volume_gb > persistent_volume_gb`); the account ref is written at claim (but not at transfer: B-S6).
7. **R11 canary runner:** preflight resolves nothing and prints the plan + `authorization_sha256` (OK, weakly tested - B-S10). Execute refusals are ordered before any world/transport (OK). Deadline and ambiguity paths stop and terminate (tested; but a failing shutdown loses the record - B-S3). Prompts bounded by `max_prompts` (file length) and `max_attempts`. The `/object_info` check precedes the first prompt (B-N4). Operability: **no path** to resolve credrefs from a file store, and the Comfy endpoint/image cannot be supplied correctly (B-S1, B-B2). `canary invoice` passes only the evidence sha256 and allows `INVOICE|CONSOLE`; it omits the budget service (B-S5) and cannot take amount 0 (B-S7). Nothing prints credential values, Authorization headers or env (checked output sites).
8. **`canary_db.py`:** never uses 8091/8093 or a container, `down` removes only its own state file, no destructive action on an existing database; durability and identity concerns in B-S8/B-S9. I did not run it.
9. **Tests:** meaningful in structure (real PG, exact amounts per reservation), but they miss the account-level double count (B-B1) and the CLI entry point (B-S10).
10. **T045-A regression:** none found in the `billing.py`/`leases.py` edits beyond B-S6; the `largest_remainder`/zero-weight change is conservation-safe. Interactions with the known list: **A-B1** now reachable on the ordinary janitor schedule (B-S4); **A-S2** (backoff never grows) compounds B-S4; **A-N3** (account-scoped covering query) is worsened by NULL-ref transfer receivers (B-S6); **A-S4/A-S1** not made worse.

## Good practices observed
- Fail-closed construction order preserved; explicit `isinstance(BillingRepository)` rather than duck typing.
- Exact integer micro-USD with `Decimal` end to end; DISPUTED recorded instead of hidden.
- The absent-Pod ownership proof is a narrow, three-column durable check with negative tests.
- Authorization sha pin, prompt content-hash pins, credref-names-only, refusal ordering before any transport.
- Composed test drives real PG and scripted transports with no auth echo; deadline, mismatch, create-timeout and crash cases covered.
- `canary_db.py` binds loopback on a free port and explicitly avoids the staging ports.

## Verdict
**NEEDS CHANGES.** Not REJECT: gate ordering, R10 cross-checks, exact mapping and conservation are sound. The two blockers are a real double count in the canary's own books and a runner that cannot address a real Pod/image.
Counts: BLOCKING 2 (B-B1, B-B2); SHOULD-FIX 10 (B-S1..B-S10); NIT 7 (B-N1..B-N7).
