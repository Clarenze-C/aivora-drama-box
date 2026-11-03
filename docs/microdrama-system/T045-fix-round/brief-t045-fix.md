# Build T045-FIX: Drama Box billing finality, review fix round (money path)

**Repo:** `/root/AIVORA/drama-box`. **Branch:** `feat/microdrama-m0-m4` at `7f857eb` (clean). It builds on the T045-A
(`65fae0b..1a60fc5`) and T045-B (`1a60fc5..7f857eb`) commits. Run Python from `microdrama/`.

**What this is:** the one fix round after the independent reviews of T045-A and T045-B. Claude Sonnet reviewed
in place of Codex, and Opus ruled. Every ruling below is **binding** unless it is marked otherwise. Fix exactly
what each ruling says; don't redesign around it. The binding spec is still
`docs/microdrama-system/T045-finality-spec.md` (revision 1). Where a ruling below differs from the spec, the
ruling wins; record that in the evidence.

**How to read code:** read Python through the Serena tools (`mcp__serena-drama-box__*`, deferred; load them with
ToolSearch). Use get_symbols_overview → find_symbol include_body=true, and find_referencing_symbols for callers.
Read only the lines you edit.

**Migration 0025 may be edited in place.** It is unpushed. The parent verified that no persistent database has it:
- the staging PG volume holds 0024's tables and no 0025 objects;
- the host PostgreSQL has no Drama Box schema;
- no canary DB state exists.

So put the A rulings' schema changes **into `0025_t045_billing_finality.sql` itself**. Don't add a 0026. Leave
0001–0024 untouched.

## Rule for every item: test first

Write the named test and run it to show it failing. Record the failure line. Then fix and record the passing
line. If a test passes before the fix, the defect isn't reproduced: say so and strengthen the test until it fails.

## A. T045-A review rulings

| ID | Defect | Fix + test |
|----|--------|------------|
| A-B1 | A period with a bucket that was once skipped as open can never be verified. The skipped table is append-only, and the check ignores later closed observations (`budget/billing.py` ~551-558). | Refuse only when a skipped row has **no stored closed bucket of the same identity observed at or after the skip**. Test: open poll → closed poll of the same bucket → `verify_invoice_period` → MATCHED → BILLED, and the remainder is released. Keep the refusal when no closed observation follows. |
| A-S1 | A create that was sent but never produced a Pod never settles: `compute_window_end_at` is never set, so readiness stays PENDING forever. | (1) When a lease closes without a Pod after a create was sent, set `compute_window_end_at` to the close time. (2) Add an audited operator resolution `resolve_podless_create(lease_id, actor_ref, reason, evidence_sha256)` on the billing repository. The operator attests that the console shows no Pod and no charge for the owned name and period. Record it durably (actor, reason, evidence sha, time); its schema goes in 0025. It posts the BILLED 0 SETTLEMENT and releases the hold. Refuse it once a Pod is attached to the lease, and when actor or reason is empty. Once it is recorded, a Pod that appears later goes through the existing stray-adoption path and must not double-settle. Tests: ambiguous create → no Pod → resolution → BILLED 0 and released; resolution refused when `pod_id` is set; empty actor or reason refused; replaying the same resolution is a no-op. |
| A-S2 | Finality backoff never grows; it is always 5 min (`rendering/finality.py` ~160-176). | Store an attempt count (a 0025 column on `pod_leases`). Double the delay from 5 min up to a 1 h cap. Reset the count once BILLED. Test three consecutive sweeps: 5, 10, 20 min. A test at the cap: still 60 min. |
| A-S3 | `settle_billed_lease` reads readiness and the GPU sum outside the settlement transaction, so a concurrent ADJUSTMENT can be overwritten by a stale SETTLEMENT (`billing.py` ~1032-1090). | Recompute readiness and the sum and post the SETTLEMENT in **one** transaction, holding the reservation row lock, with an in-transaction ledger post. Concurrency test on real PG: an ADJUSTMENT committed between the old read and the settlement leaves settled equal to the full posted sum, or settlement refuses and retries. It never silently drops the ADJUSTMENT. |
| A-S4 | Readiness returns BILLED 0 when `compute_window_start_at` is NULL, without checking `pod_id` (`billing.py` ~883). | Return PENDING_PROVIDER_FINALITY when `compute_window_start_at IS NULL AND pod_id IS NOT NULL`. Test. |
| A-S5 | The overstatement evidence uses `max()` over periods and compares one lease with the whole Pod (`billing.py` ~1069). | Make it Pod-level: compare the sum of distinct non-superseded MATCHED periods with the total posted for all leases on that Pod over those periods. Evidence only, so no money moves. Test with two periods, one of them containing a warm transfer. |
| A-S6 | Storage ownership opens only on CLAIMED→ACTIVE or attach. A crash in between leaves no row, and disk charges go to recovery. The close runs before the lease-row terminate write, which can leave a gap (`rendering/leases.py` ~850, 410, 1076; `rendering/janitor.py` ~263). | Open ownership idempotently from the ensure/ACTIVE path too. Write `terminate_verified_at` first, then close ownership **from the persisted value**, never from a fresh clock read. Tests: crash after activation and before the ownership write, after which a re-ensure opens it once; crash between the terminate write and the close, after which the janitor closes at exactly `terminate_verified_at`. |
| A-S7 | The rewrite of `tests/.../test_billing_repository.py` ~35-45 dropped assertions. | Restore equivalent strength: the RECOVERY allocation and the pending posting row exist, a new Runpod reservation is blocked, and the provider-reported sum is asserted exactly. |
| A-S8 | The ordering test doesn't prove the commit happens before create, and the "shutdown" test never calls shutdown (`tests/.../test_t045_timing.py` ~112). | The fake `create_pod` reads `create_requested_at` **over a separate connection** and asserts that it is visible. The shutdown test calls the real shutdown path, or is renamed to what it actually tests. |
| A-N1 | `_verified_finality` is a public `ingest` keyword (`billing.py` ~204). | Move it into a private method that no public `ingest` call can reach. |
| A-N2 | The per-bucket `verify_invoice` is still public (`billing.py` ~401). | Make it private. Under R5 the only public verification is `verify_invoice_period`. Update its callers and tests. |
| A-N3 | The covering query is account-scoped, not Pod-scoped (`billing.py` ~545). | Require a Pod-scoped covering query. Test: an account-scoped query does not count as coverage. |
| A-N4 | The boundary check doesn't require buckets to lie inside the period (`billing.py` ~565). | Every counted bucket must lie fully inside the period, and the period edges must fall on bucket boundaries. Contiguity stays R7(b)'s job. Test: a bucket that straddles the period edge is refused. |
| A-N5 | The unresolved-RECOVERY check is Pod-wide, which is stricter than R7(d). | **Accepted as is.** It is conservative. Record it in the evidence; no code change. |
| A-N6 | 0025's identity column defaults to `''` and is not backfilled, and `MATCHED_ZERO` has no amount CHECK. | In 0025: backfill the column from the bucket row, and add `CHECK (outcome <> 'MATCHED_ZERO' OR amount_micro_usd = 0)`. Migration test: a MATCHED_ZERO row with an amount ≠ 0 is rejected. |
| A-N7 | `FOR UPDATE` on a join locks the lease rows (`budget/service.py` ~1027). | Use `FOR UPDATE OF r`. |
| A-N8 | `except Conflict: pass` reports `released=True` after a release was refused (`finality.py` ~150). | After the Conflict, re-read the reservation state and report the truth. Test. |
| A-N9 | `settle_reservation_for_lease` doesn't check the finality/mode pairing. | Check it there too, in addition to the constructors. Test: a wrong pairing raises at settle time. |

## B. T045-B review rulings

The full review is at `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/review-t045b.md`;
read each finding's section there before you fix it. The reviewer's probe tests sit **only** in a separate
review worktree and are not in your tree. Write your own tests.

| ID | Defect | Fix + test |
|----|--------|------------|
| B-B1 | **Double count.** `canary_render_config` prices the Comfy render at the GPU-second rate (`pipeline/canary.py` ~190). The `comfy.queue_prompt` hold then settles a GPU_GENERATION charge on top of the Pod lease's invoiced GPU bucket. Composed run: invoice 70,000, account settled 70,140. | **For a render on a leased Runpod Pod, the Pod lease's BILLED settlement is the only GPU cost.** The prompt reservation must end with **zero charge**: either the prompt hold reserves 0, or it settles at 0 / is released at prompt end. Use whichever the existing budget API allows without a contract change; if none does, stop and write a proposal. Enforce this in `live_world`, not only in the canary: a world whose Comfy endpoint is on a leased Runpod Pod refuses a render config with a non-zero price. The pilot (fake providers) is unchanged. Tests, in the composed canary: the account's `settled_micro_usd` equals the invoice total, and the sum of all charges equals the invoice total, both after the run and after the full replay. The prompt reservation's settled amount is 0. |
| B-B2 | **`execute` cannot address a real provider.** The Comfy endpoint is a free flag fixed before the Pod exists (`canary.py` ~850, 456). The image reference is invented as `microdrama-canary@sha256:<digest>` (`canary.py` ~93). | (1) The authorization carries the **full image reference** `<registry>/<repo>@sha256:<64 hex>` in `pins` (update the schema and the example file). It is validated as exactly that shape and sent as-is on create; delete the invented repository constant. (2) **Remove `--comfy-endpoint`.** The Comfy base URL is late-bound from the created Pod's `PodInfo.endpoint_url` (the transport already computes it, `runpod_transport.py` `_comfy_endpoint`). Before any Comfy call, assert it equals `https://<pod_id>-8188.proxy.runpod.net` for the leased `pod_id`. Bind the Comfy client after `ensure_pod`, or give it a late-bound endpoint provider; keep every `live_world` gate. Tests: a create request carries the full image ref; a Pod whose `endpoint_url` doesn't match its id refuses before `/object_info`; no CLI flag can set the endpoint. |
| B-S1 | **The CLI isn't runnable:** `main` hard-codes the refusing resolver; `sleep` defaults to a no-op, so the poll loop would hot-loop; nothing can stop, terminate or ingest after `execute` exits. | (1) `main` resolves credentials through the existing `core/registry/credentials.py` `CredentialStore(db, settings).resolve`, **restricted to FILE refs** for the canary: refuse ENV/VAULT/NONE kinds, and refuse a secret file that is group- or other-readable (mode must be 0600 or 0400). Error messages name the ref and the path, never the value. (2) The real `time.sleep` is the default, with a poll interval floor of ≥ 2 s from the authorization or a constant. (3) Add `canary sweep --authorization <file> --authorization-sha256 <hex>`. It composes the same attested world and runs one janitor sweep: stop/terminate an owned stray Pod, ingest billing, run finality. (4) In `execute`, SIGTERM/SIGINT run the shutdown path before exit. Tests: each refused credential kind and file mode; the sleep floor; `canary sweep` against fixtures terminates an orphaned owned Pod and keeps the hold; SIGTERM during polling runs shutdown. |
| B-S2 | `max_wall_seconds` isn't bounded by the quote's `maximum_runtime_ms`, and `caps.max_spend_micro_usd` is never compared with the real holds. | Validation requires `max_wall_seconds * 1000 <= quote.maximum_runtime_ms`. At `execute`, before the first reservation, the computed total (lease hold + prompt holds + storage ceiling + shutdown margin) must be `<= caps.max_spend_micro_usd`, or it refuses before any transport call. Tests: both refusals, with zero transport calls. Fix the composed fixture so it is self-consistent. |
| B-S3 | A shutdown or provider failure, or any non-Microdrama exception, leaves no canary record, and the CLI prints "refused" although a Pod was created. | Write the record (pod id, lease id, client token, reservation ids, `outcome`) in a nested `try/finally` that runs even when shutdown or sweep raises; then re-raise. Once any effect has been sent, the CLI prints `canary execute STARTED, NOT CLEAN: <reason>; record: <path>` and exits with a code distinct from a pre-effect refusal. Tests: DELETE → 503 leaves a record with `outcome` NOT_CLEAN and the Pod id; a `ValueError` from a malformed Comfy body leaves a record. |
| B-S4 | Janitor billing ingestion has no persisted backoff for in-flight Pods or failures, and reports INGESTED for skipped-open buckets. Together with A-B1, an ordinary sweep shortly after the run makes the later invoice fail. | Persist a per-Pod ingest backoff (a 0025 column or table), applied on success, replay and failure. Skip a Pod whose lease window end is within `settle_lag` of now, except for one post-terminate ingest. Report stored, skipped-open and replayed counts separately. Record ingest failures durably, kept as hold-keeping evidence. Tests: 4 sweeps 20 s apart on a running Pod make one provider call; a failure is persisted and backed off; the composed flow "sweep 10 min after the run → sweep 2 h later → invoice → MATCHED → BILLED" passes (this is the A-B1 end-to-end proof). |
| B-S5 | A `RunpodInvoiceFinality` with no budget service is accepted, and `canary invoice` builds one without it, so the ledger side of ingest and verification is skipped. | `RunpodInvoiceFinality` **requires** a `budget_service`; no `None` default. `live_world` refuses a finality whose `budget_service` is not the world's `budget`. `run_invoice` passes a real `BudgetService`. Every Runpod live path builds `BillingRepository` with a budget service, and the fake/pilot path keeps its current construction. Tests: construction refusals; after `canary invoice` the `runpod_billing_budget_finalizations` row exists; replaying `canary invoice` is a no-op. |
| B-S6 | The transfer receiver's INSERT doesn't copy `provider_account_ref` (`rendering/leases.py` ~1304), so the absent-Pod billing proof fails for a transferred chain. | Copy `provider_account_ref` (and any other claim-time identity column) on transfer. Keep the absent-Pod proof strict: one row with all of its fields. Test: a warm transfer → receiver terminates → Pod gone → `billing_history` is allowed and ingests. |
| B-S7 | `canary invoice --amount-micro-usd 0` is rejected as missing. | Treat only `None` as missing for the amount. Test: a zero amount reaches `verify_invoice_period` and records MATCHED_ZERO. |
| B-S8 | The canary ledger runs with `fsync=off`, `synchronous_commit=off` and `full_page_writes=off`, in a `/tmp` data directory, and `down` uses `-m immediate`. | Give `EphemeralPostgres` (or `canary_db.py`) a **durable mode** used only by `canary-db`: fsync, synchronous_commit and full_page_writes on. The data directory is stable and outside `/tmp`, by default `/root/.local/share/microdrama/canary-pg` (overridable by flag), created 0700. `down` uses a fast shutdown and keeps the data. Test fixtures keep their fast settings. Test: a canary-db durable-mode config check (no real server start is needed if the settings are checked from the generated config). |
| B-S9 | `execute` charges "the oldest episode with a budget account" in whatever DB the DSN points at. | The authorization names `episode_id`. `execute` refuses unless the DB has **exactly one** episode with an EPISODE budget account and it equals `episode_id`, and unless the DSN host is loopback. Tests: two episodes refused; mismatched id refused; non-loopback DSN refused; all before any transport call. |
| B-S10 | Test gaps let B-B1, B-S1 and B-S5 through. | (1) The full composed flow runs through `main(argv)`, with a test-only injection seam for fixture transports and resolver. (2) Assert the account total and charge sum against the invoice, plus the finalization rows. (3) Preflight asserts zero transport calls and zero resolver calls. (4) Add a retry test: a failed attempt, then success, reusing the prompt hold within `max_attempts`; the failed attempt stays charged per R1. (5) Add a test where submit raises `NeedsReconciliation`: it stops for a human, never retries blind, and shutdown runs. |
| B-N1 | Float arithmetic in `_ceil_seconds` and the hourly window rounding. | Money and time math in integers (ms/µs) or `Decimal`. No float. |
| B-N2 | The Comfy bearer token goes to an unvalidated endpoint, and the DSN appears in argv. | The endpoint part is covered by B-B2. The canary CLI reads the DSN only from `MICRODRAMA_DATABASE_URL`, never from argv, and never prints it with a password. |
| B-N3 | The deadline ignores the rights record's `eligible_until`. | Deadline = min(`hard_stop_utc`, start + `max_wall_seconds`, rights `eligible_until`). Quote expiry gates only the start, which already holds. Test. |
| B-N4 | The `/object_info` "digest" is a local tautology plus a class-presence check. | **Accepted as the documented R10 limitation.** No code change; keep it in the runbook. |
| B-N5 | `canary_db.py down` trusts the state file, and the docstring says "discard" while the data is kept. | `down` refuses unless the state file's data dir is under the canary-db root. Fix the docstring. |
| B-N6 | The Comfy guard dropped the `reservation.job_id` equality check, and a comment is wrong about holds per prompt. | Restore the `job_id` equality and fix the comment. Test: a mismatched job id is refused. |
| B-N7 | The `max_attempts` wording doesn't match how it is enforced (globally). | Make the docs, the authorization field description and the code agree: `max_attempts` is a global cap across all prompts. |

**Order:** A-N6 + 0025 edits first, then A-B1/N3/N4, then the B-B1/B-B2 runner changes, then the rest. The
B-S4 end-to-end test depends on A-B1. After all fixes, rerun the T045-A and T045-B suites and confirm that every
earlier test still passes with unchanged assertions; list any test you changed and why.

**Update the docs:** the runbook's canary command lines, authorization schema and example file must match the
final CLI (no `--comfy-endpoint`; the `sweep` subcommand; the full image ref; `episode_id`). Report the final
command lines exactly.

## Gates

Run the focused suites under `systemd-run --scope --quiet -p CPUQuota=45%`. When they are green, run under the
same quota from `microdrama/`:
- `make check`: the last line must be `make check: all offline checks passed`;
- `make pilot`: exit 0, with W01–W12, exactly two gates, 16 exports and 303,000 synthetic micro-USD, unchanged.

Ruff check and format must be clean; `git diff --check` must be clean. Report the real tails and the
unit/contract/integration counts.

## Commits

Layered commits on the branch with conventional messages, grouped by ruling (for example: migration + A-N6,
A-B1/N3/N4, A-S1, …). **Never push.** Append a section "T045-FIX (2 Nov)" to `microdrama/evidence/T045.md`
with, per ruling ID, the test names plus the red line and the green line. Leave `task_status.csv` and HANDOFF
alone.

## Hard limits

- **No provider calls, no network, no paid runs, no Pod, no publishing.** Fixture transports only. Never run
  `canary execute` or `make canary-db` outside pytest.
- **Never print env vars or `.env` contents.** Never read `~/.claude/.env`, `/root/.secrets` or any secrets file.
- Stubs must never echo `Authorization` or bearer arguments; log only the argument count. Test credential
  resolvers are fakes that return a constant dummy value and never read the env.
- No live key exists for this work. If anything asks for one, stop and report.
- Migrations: edit 0025 in place, and touch nothing in 0001–0024. Don't edit guardian-owned contracts or
  generated schemas. If a ruling truly needs a contract change, stop that item and write a proposal.
- Don't change the pilot semantics. Don't touch anything outside `/root/AIVORA/drama-box`.
- If a ruling is wrong against the real code, don't improvise money semantics. Take the hold-keeping reading,
  flag it `SPEC-GAP` in the report, and continue.

## Report (write to the --out file)

- Per ruling ID: files and lines changed, test names, red/green lines.
- What changed in 0025.
- Every `SPEC-GAP` or contract proposal.
- Real gate tails and counts.
- Commit hashes.
- Anything not done, with the reason.
