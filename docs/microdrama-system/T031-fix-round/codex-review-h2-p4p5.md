**Verdict: FIX-REQUIRED.**

Reviewed `45e4f2a...0e34630`: 20 commits, 23 files, +6,304/−540. HEAD is `0e3463081acabb8001188dede82d30cdadee9449`. There are no tracked changes against HEAD, so I used the explicit commit range.

This was read-only. I ran no tests, database calls, provider calls or systemd commands. `git diff --check` passed. Small in-memory probes confirmed the terminal-replay, R7, receipt-replay, CLI-validation and fixture failures described below. The running full gate was untouched; its result is not independently verified here.

**Findings**

**HC-1 — BLOCKING — STORAGE exposure can close before financial finality.**  
[benchmark_service.py:1604](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:1604), `:1621`, `:1638`; `benchmark_experiments.py:216`.

The `NO_CREATE_PROVEN` sweep branch zero-settles EXPIRED STORAGE holds **before** its finalization transaction, including contradicted acquisitions. The later transaction locks A, but not L, and does not check invoice finality.

U5’s new billing predicate is also insufficient: it treats the compute reservation’s `SETTLED` state as billing finality, although `resolve_create` already settled that reservation at zero **before the contradiction**.

Concrete failure: a late pod contradicts the attestation, termination completes, but its disk invoice remains pending. U5 clears using the old settlement, and sweep releases STORAGE. With EXPIRED STORAGE, sweep can close exposure even while termination remains unverified.

**Fix:** perform ACTIVE release and EXPIRED financial closure inside the same correctly locked finalization decision. Require canonical billing readiness for the discovered resource, verified deletion or uncontradicted no-create proof, and no remaining U5.

---

**HC-2 — BLOCKING — the additional canonical billing edits break replay and can double-count late cost.**  
[leases.py:618](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/rendering/leases.py:618); [service.py:940](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/budget/service.py:940), `:957`.

Two related problems:

- `settle_from_recorded_usage` changes the deterministic receipt from SETTLEMENT to ADJUSTMENT when the reservation becomes closed. An ordinary replay therefore reuses the same receipt identity with different content. The probe produced precisely that change; canonical `_replay` rejects it at `service.py:1123`.
- On an already closed reservation, `_settlement_totals` includes existing ADJUSTMENT charges. Posting that entire total as another ADJUSTMENT charges it again. A previously posted late adjustment of 100 becomes 200.
- `_record_gpu_interval` converts ACCRUAL to ADJUSTMENT **after** its replay check. A crash after posting but before advancing `accrued_until` causes the original ACCRUAL payload to conflict with its stored ADJUSTMENT.

These are shared canonical changes beyond the explicitly permitted edits. The builder’s “amounts unchanged” justification does not establish accounting correctness.

**Fix:** preserve immutable receipt content and identity across replay. Reuse an existing settlement, and post only genuinely new deltas on closed reservations. Normalize any interval receipt before its replay comparison.

---

**HC-3 — BLOCKING — R7 force can discard positively recoverable work.**  
[benchmark_service.py:2622](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:2622); `comfy_jobs.py:912`.

The BOUND-source probe calls `poll`, rather than client-ID reconciliation. For UNKNOWN without `external_id`, `poll` raises immediately without querying the server. `--force-unrecoverable` then permits operator failure even when the accepted prompt is recoverable by deterministic client ID.

The in-memory probe followed: `poll → OPERATOR-FAILED → finalize`; the recovery lookup was never called.

There is a second exposure to this mistake: the default resolver composes CLEANUP, while the EXPIRED reservation read exception permits RECOVERY only. A recoverable expired operation can therefore appear unreadable to this probe.

**Fix:** determine recoverability through the appropriate RECOVERY path, including client-ID discovery when necessary. Positively recoverable work must refuse resolution even with force.

---

**HC-4 — BLOCKING — terminal replay does not repair every unfinished finalization stage.**  
[benchmark_service.py:2521](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:2521); `benchmark_experiments.py:300`.

`finalize_terminal` returns immediately when the sample is already SUCCEEDED or FAILED. It consequently skips matching-slot cleanup, missing output/linkage repair and failed-outcome repair.

A terminal sample with its slot still occupied remains U4 forever. The probe confirmed that settlement runs, followed by **zero projection, slot or outcome writes**. A failed sample with a cleared slot but missing experiment outcome is worse: U4 does not include that missing fail-fast outcome.

Success finalization also trusts `last_result.outputs` without loading the existing durable assets; empty outputs can still project SUCCEEDED.

**Fix:** make every replay independently complete all required stages. Preserve terminal state while repairing linkage/output, clearing the matching slot and restoring fail-fast atomically. Include incomplete failed-outcome projection in U4, and require durable success assets.

---

**HC-5 — BLOCKING — stale-coordinator protection remains incomplete.**  
[benchmark_service.py:878](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:878), `:861`, `:1119`; `comfy_jobs.py:694`.

Submit-grace writes gained token checks, but create/upload ambiguity handlers still receive no coordinator token. `_claim_sample` checks only the slot token value, and the ACTIVE write checks only A.

A stalled original create can return after takeover and operator resolution, then rewrite the old acquisition to UNKNOWN. If a newer acquisition now occupies the partial-index slot, this can cause an index collision and fail the newer run.

The prompt claim now prevents overlapping callers from both sending, but its transaction does not validate the coordinator ownership that authorizes consuming the first-send right.

**Fix:** carry and validate the expected live ownership through every coordinator control write and intent/send authorization. Retain uncertainty for effects authorized before fencing; deny stale callers new authority.

---

**HC-6 — BLOCKING — the shared gate does not lock the canonical lease state it evaluates.**  
[benchmark_service.py:362](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:362), `:940`, `:2362`.

`_lock_gate_rows` locks A → D → R → O → uploads, omitting L and S. A canonical L-only janitor adoption can therefore introduce a contradiction while a gate transaction proceeds to its running-state or claim write.

Other order discrepancies remain:

- acquisition coordination locks D before updating A;
- `_claim_sample` locks S before calling a helper that takes A;
- `resolve_create` locks L before entering the billing-advisory core;
- sweep upload finalization takes upload locks before later D/S/R writes.

The inventory does not accurately describe these transactions.

**Fix:** implement the complete ordered lock acquisition once, including the canonical rows being evaluated, and use it consistently. Correct the inventory to match actual SQL.

The billing wrapper itself now takes account/categories first. I found no remaining wrapper-versus-canonical-settlement inversion in that corrected prefix.

---

**HC-7 — BLOCKING — RECOVERY/CLEANUP still expose an unrestricted reservation entry point.**  
[benchmark_experiments.py:521](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/rendering/benchmark_experiments.py:521); `budget/service.py:350`.

The mode check exists in `reserve_linked`. `ExperimentBudgetService` does **not** override inherited public `reserve_in_transaction`.

A composed recovery world’s budget can therefore create an ordinary reservation through that entry point, bypassing both the mode refusal and benchmark linkage/sub-limit checks. The HB-11 test exercises only `reserve`.

**Fix:** enforce the mode restriction at every public reservation entry point, including the transaction-owning composition’s canonical core, while preserving cleanup grants.

---

**HC-8 — BLOCKING — failed binding can bypass durable ambiguity entry.**  
[benchmark_service.py:2213](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:2213).

A non-BOUND result returns before the grace-persistence handlers. This affects an operation already UNKNOWN when the original worker died before its handler, or known in-flight work whose pod temporarily cannot be bound.

With no persisted deadline, repeated public recovery leaves the item blocked without establishing the bounded episode or deadline cleanup. HB-5’s new test covers a PENDING takeover with successful binding, which misses this exit.

**Fix:** establish or reuse the durable ambiguity episode before these exits, then route exhausted episodes through fenced cleanup.

---

**HC-9 — BLOCKING — effective recovery deadlines are not consistently recomputed before recovery reads.**  
[benchmark_service.py:779](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:779), `:1444`, `:2122`.

The shortening calculation runs in the sweep fence, while ordinary recovery requests use the previously stored deadline. Newly discovered liability can exhaust the allowance before the old deadline produces U2 and invokes sweep.

The aggregate candidate also assumes one consuming GPU window and reserves one shutdown margin. The explicitly supported late-contradiction scenario can have multiple open windows consuming the allowance simultaneously.

**Fix:** recompute under the required locks before bounded recovery work, persist only shortening, and fence immediately when exhausted. Calculate aggregate exhaustion from all open-window consumption and required shutdown allowances.

---

**HC-10 — BLOCKING — required race/crash proofs are incomplete, and some assertions cannot detect their claimed failures.**  
[test_t031_h2b_p4_resolution.py:537](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/tests/unit/rendering/test_t031_h2b_p4_resolution.py:537), `:623`, `:671`; `test_t031_h2b_p5_terminal.py:348`.

Specific problems:

- “billing wrapper vs resolve_create” never calls the billing wrapper; it manually holds an account lock.
- The admission/sweep/reconcile race catches and discards every ordinary exception, including deadlocks.
- The absent-row R5 test runs handwritten SQL and inserts only an upload, despite claiming operation/upload coverage.
- AT-9’s five cases mainly seed states or replay completed calls; they do not inject crashes at every inventoried boundary.
- LF’s costume test binds screening shots, then calls only `manifest()` for S08. It never binds the changed costume.
- HB-13’s cleanup fixture still returns `storage_final=True` when termination is verified but billing is pending. The probe confirmed this exact receipt.

**Fix:** exercise the named public implementations with fresh worlds, actual boundary injection and precise exceptions/counts. Apply lock timeouts to the participating worker connections. Require canonical financial finality and actually bind S08.

---

**HC-11 — SHOULD-FIX — CLI resume still validates generation arguments before recovery.**  
[benchmark.py:151](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark.py:151), `:168`, `:231`.

Softening selected errors does not implement the required ordering: files and SHA arguments are processed before service construction.

For example, a non-ASCII `--authorization-sha256` raises `TypeError` in `hmac.compare_digest` before recovery. The outer handler does not catch it. The standard-library probe confirmed that failure.

**Fix:** complete durable recovery first, then load and validate optional generation documents and report admission blockers.

---

**HC-12 — SHOULD-FIX — the required contradiction incident is absent from status/export.**  
[benchmark_service.py:2658](/root/AIVORA/drama-box/.scratch/t031-gate-h2/microdrama/src/microdrama/pipeline/benchmark_service.py:2658); `benchmark_experiments.py:810`.

The actor/evidence detail exists only in a transient U5 description. `status()` and `export()` do not return it, and U5 disappears after finalization.

Consequently, the operator-facing result can lose the distinction between uninterrupted protection and liability reopened after an attestation.

**Fix:** expose a persistent or durably derived incident record containing the attestation, actor, contradiction and reopened-liability status, including after closure.

**HB-1..HB-14 re-review**

Red assessments below compare the reported red lines with the code and assertions. I did not rerun red baselines or mutants.

| Finding | Status | Evidence and counterfactual assessment |
|---|---|---|
| HB-1 | **CLOSED** | `comfy_jobs.py:1271`; `test_comfy_recover.py:264`. ACTIVE/EXPIRED share the measured calculation. The exact 604-second/151,000-µUSD assertion would fail against the old zero branch. |
| HB-2 | **CLOSED** | `benchmark_service.py:2213`; `experimental_world.py:230`; P3 tests `:2275`, `:2413`, `:2488`. Fresh real-client recovery binds first; STOPPED refuses BOUND. Reported reds match the old defects. |
| HB-3 | **CLOSED** | `experimental_world.py:1089`; `benchmark_service.py:1487`, `:1933`. Acquisition-owned provenance is loaded, and production recovery/sweep name the acquisition. P3 `:2536` meaningfully rejects the wrong supplied authorization. |
| HB-4 | **CLOSED** | `benchmark_service.py:2228`; P3 `:2617`. Historical grace no longer bounds healthy known-ID polling; the transport-aware regression targets the original stall. |
| HB-5 | **PARTIAL** | `benchmark_service.py:2184`, `:2218`. Takeover and exception paths persist grace, but failed-binding exits remain uncovered. HC-8. |
| HB-6 | **PARTIAL** | `benchmark_service.py:713`, `:1444`. Tighter authorization and shutdown reserve were added; recomputation timing and overlapping windows remain wrong. HC-9. New tests isolate selected operands, not the full invariant. |
| HB-7 | **PARTIAL** | `comfy_jobs.py:707`; `benchmark_service.py:428`. Atomic prompt claiming and expired-token refusal are substantive; their reported reds are credible. Ownership at intent authorization remains incomplete. HC-5. |
| HB-8 | **PARTIAL** | `benchmark_service.py:940`, `:878`. The common account/E prefix removes the original benchmark fence cycle, but literal order and control predicates remain incomplete. The new stale test covers submit ambiguity only. HC-5/6. |
| HB-9 | **PARTIAL** | `benchmark_service.py:1993`; P4 `:737`. The common unresolved predicate replaces the old separate checks, but complete canonical serialization is still missing. HC-6. |
| HB-10 | **PARTIAL** | `benchmark.py:151`; `benchmark_service.py:1356`. Cleanup-only and selected eligibility failures are repaired; actual recovery-first ordering is not. HC-11. |
| HB-11 | **PARTIAL** | `benchmark_experiments.py:553`; `experimental_world.py:162`. Ordinary wrappers and podless `acquire` refuse correctly. Inherited transaction-core reservation remains unrestricted. HC-7. |
| HB-12 | **PARTIAL** | `benchmark_experiments.py:158`, `:216`; `benchmark_service.py:1741`. EXPIRED debt, U6 and upload fencing improved. Billing finality is still inferred from the pre-contradiction settlement. P4 `:897` never proves invoice-pending U5 retention. HC-1. |
| HB-13 | **PARTIAL** | `test_benchmark_experiments.py:296`, `:304`; P1 `:166`. Pod lifetime and isolated mode-denial tests improved, but financial finality remains synthetic and broad tests reuse adapters/clients. HC-10. |
| HB-14 | **CLOSED** | `benchmark_service.py:2260`; P3 `:374`. Public reconcile records the bounded conflict diagnostic while preserving UNKNOWN. The new event assertion fails against the old swallowing path. |

**L-1..L-7 review**

| Finding | Status | Evidence |
|---|---|---|
| L-1 — BLOCKING ruling | **PARTIAL** | `experimental_world.py:898` fixes ordinal ordering. LF test `:392` exercises screening binds, but S08 at `:449` is manifest-only. Required changed-costume bind proof is missing. |
| L-2 — BLOCKING ruling | **PARTIAL** | `experimental_world.py:843`, `:860` fixes receipt collapse using byte/media/role/subject identity. Same missing S08 bind proof; the combined reported red stops at L-1 and does not independently demonstrate L-2. |
| L-3 | **CLOSED** | `test_benchmark_world_composition.py:265`, `:291`. The accepting control proves readiness before policy rejection. The reported pre-Luna red is consistent with this corrected test. |
| L-4 | **CLOSED** | `benchmark_service.py:172`, `:178`; authorization tests `:310`, `:342`, `:356` assert the three added refusals. |
| L-5 | **CLOSED** | `runbooks/t031-benchmark.md:16` documents the attestation source and authorization re-issue. |
| L-6 | **CLOSED** | LF test `:468` exercises five real registry/policy refusal cases with branch-specific messages. |
| L-7 | **CLOSED** | LF test `:570` exercises the actual evidence lookup/INSERT against PostgreSQL, including replay, restatement and foreign-pod rejection. It calls the evidence writer directly, rather than proving the complete ingestion route. |

**P4/P5 conformance**

| Requirement | Status | Evidence |
|---|---|---|
| §6.1 billing-wrapper account/category prefix | **DONE** | `billing.py:812`. Corrected ahead of advisory/L acquisition. |
| §6.1 one shared order, R5 serialization and accurate inventory | **PARTIAL** | `benchmark_service.py:362`, `:940`, `:2362`; HC-6. |
| §6.2 atomic `resolve_create` and SC2-3 replay | **DONE** | `benchmark_service.py:2349`, `:2377`, `:2425`. Audit/compute settlement/acquisition transition share one transaction. Identical replay precedes unresolved-state checks and performs no create. |
| §6.3/R1 STORAGE finalization | **PARTIAL** | `benchmark_service.py:1604`, `:1729`; HC-1. Resolver retains STORAGE, but sweep’s finality conditions are insufficient. |
| §6.4 contradiction adoption and original GPU window | **PARTIAL** | `janitor.py:467`; `benchmark_experiments.py:465`. Binding/contradiction and GPU inclusion improved; financial finality and incident visibility remain incomplete. |
| §7.1 network-free terminal finalization | **PARTIAL** | `benchmark_service.py:2448`; HC-4. |
| §7.2 terminal mapping and stale nonterminal protection | **DONE** | `benchmark_service.py:1199`, `:1233`. FAILED/CANCELLED/NOT_FOUND map to FAILED; stale nonterminal projections cannot overwrite terminal samples. |
| R6 atomic fail-fast | **PARTIAL** | `benchmark_service.py:1255`, `:2543`. New projection writes are atomic; replay does not repair every previously incomplete state. HC-4. |
| §7.3 atomic operator audit/transition and attestation replay | **DONE** | `comfy_jobs.py:1118`, `:1154`. Financial finalization follows the terminal-transition commit. |
| R7 live-source precedence | **PARTIAL** | `benchmark_service.py:2622`; HC-3. |
| R8 exposure formula | **DONE structurally** | `benchmark_experiments.py:435`. Formula uses canonical counters, ACTIVE remainder and distinct unreserved charges. End-to-end money correctness remains blocked by HC-1/2. |

**Acceptance-test assessment**

| Test | Assessment |
|---|---|
| AT-6 | **PARTIAL.** Public resolution, retention and attestation replay are useful. Adoption “boundaries” are sequential before/after cases, not races at every boundary. EXPIRED/contradicted invoice-pending release is unproved. |
| AT-7 | **PARTIAL.** Public flows cover a newer generation and no index reopening. GPU assertion at P4 `:472` is a lower bound; billing amounts and canonical invoice finality are not established. |
| AT-8 | **PARTIAL.** Public replay works after a canonical resolution call. The R7 tests omit missing prompt ID, EXPIRED recovery and INDETERMINATE cases; they do not assert the forced audit field. |
| AT-9 | **PARTIAL.** Five seeded/replayed states do not cover every inventoried transaction boundary. P5 `:390` allows arbitrary charge-count growth with `>=`, which cannot prove deduplication. |
| AT-12 | **PARTIAL.** ACTIVE→EXPIRED→settled and adjustment replay have useful assertions. The arithmetic identity partly repeats returned components; no distinct unreserved-charge projection case or full §G ingestion replay is demonstrated. |
| AT-21 | **PARTIAL.** Real PostgreSQL is used, but HC-10 prevents the suite from proving the named races. The helper’s `lock_timeout` is not applied to the worker service transactions. Claim-vs-observe and operation-transition races are absent. |
| AT-22 | **PARTIAL.** Terminal recovery is driven publicly, but the success fixture seeds an output reference without a corresponding durable asset. “Output persisted before terminal” does not inject death at that persistence boundary. |
| AT-26 | **Reported green, unverified here.** The report lists canonical/canary regressions. I did not rerun them or verify the current full-gate receipt. |

The §9.3 extensions are likewise incomplete: native recovery and upload-readback coverage improved, but ownership-at-first-send, complete deadline shortening, actual R6 crash boundaries, operation insertion/transitions and the full R7 matrix remain unproved.

The DB fixtures and race helpers use **real PostgreSQL** (`tests/conftest.py:90`, P4 `:522`). There are real subprocess deaths using **`os._exit(86)`**, with durable fake-server state/counters, at P2 `:822` and P3 `:1094`. That satisfies the requested death-mechanism minimum. It does not establish the stricter killed-and-restarted CLI subprocess scenario: AT-3’s parent invokes `main()` inside pytest.

I found no newly added skip/xfail annotations. The important weakened evidence is exception swallowing, lower-bound/count assertions and fabricated storage finality. New H2 AT files avoid direct `_advance`, but retained composed regressions still call it—for example `test_benchmark_experiments.py:397`—and cannot substitute for public-entry-point proof.

No additional secret disclosure was established in this range. The bounded multi-match diagnostic currently receives the deterministic client-ID conflict; this was not a separate exhaustive security audit.

