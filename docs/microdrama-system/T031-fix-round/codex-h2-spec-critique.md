The draft needs **REWORK before the build**. It addresses the round-3 defects, but its gate blocks healthy execution, its storage rules contradict §A, and its recovery guarantees leave crash and locking gaps.

I verified the checkout at `628fe5b40ab19c6d5d1befb8539f3b6a90c2204a`. This was a static, read-only review; I wrote no files and ran no database tests. Spec line references below refer to [T031-H2-recovery-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md).

**Contract conformance**

| Contract | Assessment |
|---|---|
| **§A** | Direct contradictions: unconditional storage release, replacement storage holds, and the requirement that unresolved holds remain `ACTIVE` despite canonical expiry. See SC-1 and SC-6. |
| **§C** | The RECOVERY policy is consistent with §C. The CLI and expired-reservation guards would still prevent that policy from working unless explicitly changed. See SC-6–8. |
| **§E** | U2 prevents the permitted active-acquisition → sample-claim transition. Late-contradiction handling can collide with the acquisition index and leave GPU time understated. See SC-2 and SC-10. |
| **§F** | No express reversal of reservation adoption, but the draft lacks recovery instructions for admitted intents with missing canonical links and for claimed samples without operations. Those are required intermediate states. See SC-3–4. |

**Closure of the round-3 findings**

| Finding | Does the spec close it? | Remaining failure |
|---|---|---|
| **CN3-1** | **Partial.** Explicit endpoint binding, durable store construction, and recovery before termination address the original composition defects. | Grace can outlive available compute, lose its deadline on restart, or encounter an expired hold that the request guard rejects. |
| **CN3-2** | **Partial.** Reconciling before execute and removing the status overwrite are correct. | U2 blocks healthy acquisitions; other canonical crash states are absent from the gate; E alone does not serialize canonical writers. |
| **CN3-3** | **No.** The single transaction closes the original check/use window only if every relevant writer follows compatible locking. | The standalone billing wrapper creates a deadlock cycle. Later adoption can leave protection released, collide with a newer acquisition, or block forever through U5. |
| **CN3-4** | **Partial.** Durable RECOVERY composition with no generation-eligibility check is correct. | CLI `resume`, ACTIVE-only request guards, and unreconstructible authorization-byte hashes remain obstacles. |
| **CN3-5** | **Partial.** Atomic audit/terminal transition and replay recognition are correct. | Reprojection alone does not retry settlement; terminal mappings and stale projections remain incomplete. |

**SC-1 — BLOCKING — §§2,6: Storage release and replacement protection contradict §A**

The relevant clauses are:

> “Storage protection is released only when no pod is bound…” — **L43–44**

> “write `NO_CREATE_PROVEN`, end the window and release the storage hold.” — **L153–154**

> “re-places a storage protective hold … same key with a `:contradiction` suffix” — **L158–159**

The first condition is also unimplementable for ordinary completed acquisitions: their historical `pod_id` remains bound after verified termination.

The resolution transaction does not establish storage deletion and disk invoice finality. A second reservation is neither restoration of the original hold nor permitted RECOVERY behavior under L65–66. Canonical reserve can also refuse it because the experiment needs reconciliation, the deadline has passed, or funds are exhausted.

**Replacement wording:**

> Each acquisition has one original STORAGE protective reservation. Create resolution does not release it. While storage finality remains pending, the acquisition continues occupying the acquisition slot. Only the sweep finalization transaction may release unused storage protection, after rechecking durable proof that no storage exists or verified deletion, canonical disk-allocation finality, and absence of unresolved contradiction. A historical `pod_id` does not prevent finalization. Recovery must not create a replacement STORAGE reservation.

A subsequently contradicted attestation must be reported as reopened liability; the system cannot claim uninterrupted financial protection after already releasing that protection.

**SC-2 — BLOCKING — §4: U2 classifies every healthy active acquisition as unresolved**

> “an acquisition not in `CLOSED`/`NO_CREATE_PROVEN` … whose cleanup or storage is not final” — **L88**

A running pod necessarily has unfinished cleanup and storage finality. Therefore, after acquisition creation, U2 exists and `_claim_sample` must refuse under L105–106. The ordinary happy path cannot render its first sample.

This also conflicts with §E’s permitted “Acquisition active, no sample → Claim next eligible fixed sample” transition.

**Replacement wording:**

> U2 is an acquisition for which shutdown has begun or cleanup is required, including `CLEANUP_PENDING`, or whose canonical lease is terminal without completed benchmark finalization. A healthy acquisition being used within its original execution window is not U2 merely because its future cleanup or storage invoice is unfinished. Storage-pending acquisitions that have finished execution continue blocking the next acquisition.

Add a positive test showing that a healthy ACTIVE acquisition admits its first and subsequent eligible samples.

**SC-3 — BLOCKING — §§4–5: U1–U5 miss canonical crash and upload states**

U1 depends on the acquisition label:

> “an acquisition in `UNKNOWN`” — **L87**

A crash can occur after canonical create intent commits but before the acquisition becomes `UNKNOWN`. Likewise, prompt acceptance may commit `SUBMITTED` before `_observe` writes `sample.operation_id`.

Other uncovered states include:

- Acquisition intent and holds committed, but job/lease linkage absent.
- Sample claimed with hold/request committed, but no job or operation.
- An occupied sample with a `SUBMITTED` or `RUNNING` operation.
- Upload `INTENT`/`UNKNOWN`, with no prompt operation at all.
- Terminal operations whose settlement remains unfinished.

The §5 assertion that prompt/poll ambiguity means “the operation is already `UNKNOWN`” does not classify upload ambiguity.

**Replacement wording:**

> Derive unresolved effects from canonical lease, reservation and operation records, using immutable linkage rather than acquisition/sample labels alone. Recover operations through the sample’s fixed reservation when `sample.operation_id` is absent. Include unfinished upload intents and unfinished financial finalization. Treat incomplete local materialization separately from uncertain external effects: replay the exact §F request and existing reservation without taking another hold. If an expired pre-effect intent cannot be materialized, close only positively unused liability through canonical handling.

> Reconcile existing upload intents by checksum-verified input readback only. Unverifiable input prevents prompt dispatch and permits cleanup; it does not permit another upload POST. An upload exception must not manufacture a nonexistent UNKNOWN prompt operation.

Also require no-effect recovery for an experiment with no acquisition; it must not need a fabricated acquisition quote.

**SC-4 — BLOCKING — §§4,5: `PENDING_SUBMIT` is listed but has no recovery transition**

> U3 includes `UNKNOWN` or `PENDING_SUBMIT` — **L89**

That blocks admission, but does not specify how the pending operation converges. Current `reconcile_unknown()` delegates a non-UNKNOWN operation to `poll()`, which can leave `PENDING_SUBMIT` unchanged until its deadline.

A crash immediately before POST and a crash immediately after POST can leave the same durable pending record. Neither `PENDING_SUBMIT` nor null `submitted_at` proves “never sent.”

**Replacement wording:**

> On recovery takeover, an existing `PENDING_SUBMIT` operation without durable proof of a pre-dispatch refusal is classified as uncertain submission and transitioned to `UNKNOWN` under the operation lock. Recover it by deterministic client identity or its recorded external ID. A missing queue/history match retains UNKNOWN and its canonical exposure. Recovery never POSTs that operation again.

> Only a durable refusal or dispatch fence that makes a subsequent send impossible qualifies as never-sent proof. The right to perform the first POST belongs exclusively to the original dispatch admission and is not transferred by operation replay.

Test both sides of the POST boundary with identical durable pending state.

**SC-5 — BLOCKING — §5: Grace lacks a durable budget, deadline and crash owner**

> “until `min(recovery_grace, hard_stop − shutdown_margin)`” — **L123–125**

This mixes a duration with an absolute timestamp. More substantially, the absolute hard stop may be later than the acquisition’s funded runtime or remaining aggregate GPU allowance.

The default prompt hold already covers 600,000 ms from its creation. Another 600 seconds after ambiguity is not automatically covered by that hold. Pod compute and storage continue billing throughout grace.

No persisted grace deadline, heartbeat policy, takeover rule or independent cleanup owner is specified. The existing janitor considers a heartbeat stale after 300 seconds; a 600-second grace without heartbeats can lose its pod halfway through.

**Replacement wording:**

> Before entering grace, persist `recovery_started_at` and a fixed `recovery_deadline` for the operation/acquisition. Set the deadline to the earliest of first ambiguity plus 600 seconds, hard stop minus shutdown margin, and the acquisition’s remaining funded work deadline, including aggregate GPU allowance. Restart and takeover reuse that deadline.

> During grace, accrue canonical lease usage and heartbeat the owned lease without extending its original expiry, reservation or GPU window. Every nested recovery HTTP request is bounded by the remaining grace deadline. Deadline exhaustion starts cleanup even if an intermediate call failed. Cleanup requests remain usable after that deadline.

> An independently invoked janitor/sweeper must consume the persisted deadline and finish cleanup after coordinator death. It must not grant a fresh grace period. A stale coordinator is fenced from later dispatch.

Specify that cleanup must **start** by the cutoff; provider failure may prevent verified termination by hard stop. Such overruns remain visible liability, rather than being declared impossible.

**SC-6 — BLOCKING — §§2–3,5: Canonical expiry breaks both the invariant and recovery**

> “holds … stay ACTIVE (or settle to actual cost) until … liability is final.” — **L41–42**

> “keep … its prompt hold ACTIVE” — **L129**

These contradict §A’s canonical expired-accrual policy. `BudgetService.expire_stale()` legitimately changes a hold to `EXPIRED` while retaining its exposure.

The existing [Comfy request guard](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/live_world.py:334) requires an ACTIVE reservation. Changing generation-eligibility validation alone therefore does not enable readback after hold expiry. `_settle_if_needed` also returns early for non-ACTIVE reservations.

**Replacement wording:**

> Unresolved liability retains canonical exposure through ACTIVE protection or canonical EXPIRED/accrued accounting until final settlement. Recovery never renews or reactivates an expired hold.

> Benchmark RECOVERY reads may use an expired reservation whose retained liability and exact experiment/job/operation/pod ownership are proven. This exception permits only the scoped recovery reads; it never authorizes upload, create or prompt dispatch. Terminal recovery must finalize ACTIVE and EXPIRED liability through canonical settlement.

Keep ordinary generation guards unchanged.

**SC-7 — BLOCKING — §§3–4: CLI `resume` can refuse before recovery runs**

> “`resume`: runs `reconcile` … first.” — **L95**

The CLI currently classifies ordinary `resume` as admitting work and requires paid flags, an authorization file/hash and a quote **before constructing the service**: [benchmark.py:115](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark.py:115).

The spec needs to change this ordering explicitly. It must also define the result when recovery finishes but current generation eligibility is unavailable.

**Replacement wording:**

> `resume` first performs identity-checked recovery using durable records, before validating new-generation arguments or flags. If unresolved items remain, return reconciliation status. If recovery completes but current authorization, flags, rights or quote do not permit new work, return the recovered durable status with an admission blocker and dispatch nothing. Only the subsequent execution stage requires execute-style admission.

This implements §C’s recovery-only resume after expiry.

**SC-8 — BLOCKING — §3: The recorded authorization’s byte SHA cannot currently be verified**

> “recorded authorization payload (verify its stored SHA256)” — **L62**

The stored hash is the SHA of the supplied file’s **bytes**. Persistence retains parsed JSONB, which loses whitespace and formatting. `_source_sha256` is a private model attribute and is absent from `document(authorization)`.

Consequently, reserializing JSONB cannot verify the original file SHA. Acquisitions also lack an explicit immutable reference selecting the authorization accepted for that acquisition; choosing the latest authorization is insufficient.

**Replacement wording:**

> At accepted execution, persist the exact validated authorization source bytes, their byte SHA256, and the parsed payload. Recovery verifies the source-byte SHA and equality of the parsed source with the recorded payload. Persist an immutable authorization-hash reference on each acquisition. Construct recovery clients using that acquisition’s authorization and recorded quote, never the latest records by timestamp.

> For legacy rows lacking source bytes, require the original matching authorization file or an explicitly defined legacy recovery rule; never label a hash recomputed from JSONB as verification of the original bytes.

These additions can live in migration 0026. Recovery across several acquisitions also needs separate clients/worlds where necessary: the current Comfy client refuses rebinding to another pod.

**SC-9 — BLOCKING — §§5–7: The proposed lock order has concrete deadlock cycles**

> “account → categories → E → all … A rows … → … L” — **L139–142**

> “the public wrapper keeps owning its own transaction for other callers.” — **L151–152**

The wrapper currently takes billing advisory lock → L, then calls `record_usage_in_transaction`, which takes account → categories → reservation.

A concrete cycle is:

1. New benchmark resolver owns **account**, waits for the billing advisory lock/L.
2. Existing billing resolver owns **advisory lock/L**, waits for **account**.

Factoring the body into `_in_tx` does not fix the wrapper’s order.

Two further existing inversions matter:

- Ambiguity handling writes **A then E**; admission locks **E then A**.
- `_observe` writes **S then D**; `_claim_sample` locks **D then S**.

The requested paths compare as follows:

| Path | Existing order / implication |
|---|---|
| Janitor adoption | L, then contradiction writes; accounting occurs after commit. No account inversion by itself, but any new benchmark coordination must occur before L. |
| Billing finality | Account → R; separate retry bookkeeping locks L in another transaction. These separate transactions do not themselves form L → account. |
| Benchmark sweep | Account → categories → E → A → storage R. Its earlier unlocked lease read must move into the protected finalization decision. |
| `_claim_sample` | Account → categories → E → A → D → S → R. Acquire relevant lease locks before D. |
| `reserve_linked` | Account → categories → E → A → D → optional S → R. It must not acquire an earlier-order lease lock after D/S/R. |
| `_observe` | S → D writes. Must change to D → S. |

**Replacement wording:**

> Apply a documented shared order to every modified benchmark transaction: account → categories → E → A rows by ID → required billing advisory/lease locks in deterministic lease order → D → S rows → reservation rows. The standalone billing-resolution wrapper also acquires account/categories before its advisory lock and L. Ambiguity classification locks E before updating A. Projection locks D before S.

> Gate decisions must serialize with the canonical rows/writers they inspect; merely querying them while holding E is insufficient. Update benchmark adoption/recording paths accordingly. No network operation occurs while these locks are held.

Require explicit transaction inventories and concurrent regression tests for all three cycles.

**SC-10 — BLOCKING — §§4,6: Late contradiction cannot converge as specified**

> U5 is “any … resolution … marked contradicted” — **L91**

> “`NO_CREATE_PROVEN` → `CLEANUP_PENDING` (re-occupying the partial unique index)” — **L156–158**

There are three failures:

1. `contradicted_at` is historical evidence. It remains populated after successful cleanup and billing, so U5 never disappears.
2. A newer acquisition may already occupy the partial unique index. Reopening the older acquisition then violates the index.
3. Locking prior leases during admission only serializes **known** adoption. A pod may become visible after admission commits.

GPU accounting also needs repair: current `gpu_ms()` excludes `NO_CREATE_PROVEN`, and its recorded window end may still reflect the disproved resolution.

**Replacement wording:**

> U5 means a contradicted acquisition whose discovered resource or reopened billing liability has not yet been safely finalized. Historical contradiction evidence remains immutable and does not alone block after finalization.

> Record the reopened cleanup obligation atomically with late binding, independently of acquisition-slot ownership. If a newer acquisition already owns the slot, do not reopen the old row into the partial index. Block further dispatch and safely reconcile the discovered resource and any current work.

> Restore conservative GPU accounting from the original acquisition intent through verified termination; do not retain the disproved no-create end or start a new allowance at discovery.

AT-7 must include adoption **after** a newer admission commits. No locking scheme can guarantee that a pod will never appear after an operator’s no-create attestation; specify the incident response instead of implying that guarantee.

**SC-11 — BLOCKING — §7: Reprojection does not complete financial or terminal recovery**

> “returns success and re-projects” — **L174–175**

> “call `_observe` … No … Comfy call.” — **L176–178**

Settlement is replay-safe, but these instructions do not require invoking it. A crash after operation terminal commit and before settlement can leave an ACTIVE or EXPIRED liability behind even after the slot is freed.

There are also incompatible terminal sets:

- Spec U4 includes `NOT_FOUND`.
- Current `_observe` does not clear the slot for `NOT_FOUND`.
- `TERMINAL_SAMPLES` excludes `CANCELLED`.
- `_observe` can overwrite terminal sample state with a stale nonterminal result.

**Replacement wording:**

> Terminal recovery first invokes an idempotent, network-free operation-finalization routine that completes settlement/release and loads existing durable assets. It then projects the sample and clears its matching dispatch slot. Replay repeats both stages.

> Map canonical `SUCCEEDED` to sample `SUCCEEDED`; map `FAILED`, `CANCELLED` and `NOT_FOUND` to sample `FAILED` with the original reason. NOT_FOUND never enables benchmark resubmission. Projection under D/S locking is monotonic: a stale nonterminal observation cannot overwrite a terminal sample.

A terminal operation without an operator audit must not acquire one merely because `resolve` was called. Resolve should conflict with the terminal provenance; reconcile should perform ordinary terminal replay.

**SC-12 — BLOCKING — §§5,7–8: Failed-sample continuation and experiment outcome are undefined**

> AT-2: resolution → FAILED, then “resume continues with the next sample” — **L203**

Ordinary execution currently marks the experiment FAILED after a failed sample. Operator recovery bypasses that branch. If recovery continues without recording failure, `_finish_phase` can later set experiment outcome `SUCCEEDED` despite a failed fixed sample.

The builder must not invent different experiment semantics depending on how the same sample failure was observed.

**Replacement wording:**

> Preserve the current fail-fast rule: any eligible fixed sample finalized as FAILED, CANCELLED or NOT_FOUND sets experiment outcome FAILED once and stops new generation. Reconcile and resolve still complete financial finalization, clear occupied slots and perform cleanup. Modify AT-2 to expect FAILED with eventual cleanup/billing closure, rather than next-sample dispatch.

If continued evidence collection after sample failure is intended, specify that policy separately, including the aggregate outcome; it is not currently defined here.

**SC-13 — SHOULD-FIX — §§3,7: Binding failure is not proof that recovery is impossible**

> resolution allowed when `bind_for_recovery` ≠ `BOUND` or force is supplied — **L179–181**

> “CLI refuses resolution while history is reachable.” — **L181–182**

These disagree about whether force overrides reachable history. `bind_for_recovery` also lacks an outcome for a running pod without an endpoint, or failed manager GET. Temporary unreachability is not durable source destruction.

**Replacement wording:**

> Binding returns BOUND, VERIFIED_SOURCE_GONE, or INDETERMINATE. Manager errors, missing endpoints and temporary unreachability are INDETERMINATE. Ordinary operator resolution requires VERIFIED_SOURCE_GONE. INDETERMINATE or reachable-but-unrecoverable cases require `--force-unrecoverable` plus the existing audited attestation. The force override is explicitly recorded. Identical attestation replay is accepted before any live-source check.

Also state that an empty but reachable history remains ambiguous. If client-ID lookup finds multiple prompt IDs, retain ambiguity and report the conflict rather than adopting the first match.

**SC-14 — BLOCKING — §8: AT-1–12 are useful, but insufficient as an invariant gate**

They are feasible **offline with local PostgreSQL, fake HTTP, controlled clocks and subprocesses**. An in-memory transaction model cannot prove PostgreSQL locking, and fresh service objects do not simulate process death or lost process-local state.

AT-6’s absolute “never bound pod plus released storage” assertion also cannot be promised across a later contradiction of an already-finalized operator attestation. Test correct retention before finality and correct incident handling afterward.

**Replacement wording:**

> Retain AT-1–12 after correcting their predicates and outcome expectations. Add the cases below. Use real PostgreSQL connections for lock/race tests and at least one actual subprocess-death/restart test for recovery. Inject failures around external-effect acceptance and object persistence as well as transaction commits. Crash injection must bypass ordinary exception cleanup.

Required additions:

| Test | Invariant proved |
|---|---|
| Healthy ACTIVE acquisition claims samples | U2 does not prevent ordinary execution. |
| Canonical create intent committed before A becomes UNKNOWN | U1 is independent of benchmark labels. |
| Claim/hold committed with no job/operation, before and after expiry | §F materialization and safe unused-liability closure. |
| Pending operation before POST and accepted POST before result commit | No absence-proof or resubmission. |
| SUBMITTED/RUNNING operation before sample operation linkage | Recovery uses canonical reservation linkage. |
| Upload ambiguity with no operation | No invented prompt state or repeated upload POST. |
| Grace near compute/GPU/hard-stop limits, including a slow nested request | Bounded exposure and cleanup initiation. |
| Process death during grace, janitor takeover, stale worker return | Durable deadline and dispatch fencing. |
| `expire_stale()` during UNKNOWN recovery | Expired liability remains protected, readable and finalizable. |
| Resolution races against billing wrapper, claim/projection, ambiguity/admission and sweep | No deadlock or unsafe release. |
| Late adoption after newer admission; subsequent cleanup and replay | No index collision, permanent U5 or lost GPU time. |
| Terminal commit before settlement, and output persistence before terminal commit | Financial and asset recovery converge. |
| Recovery-only CLI resume without generation arguments after expiry | §C works through the public CLI. |
| Noncanonical authorization file formatting and multiple acquisition authorizations | Correct source-byte hash and per-acquisition provenance. |

AT-12 must include linked unreserved usage exactly once and exercise canonical expiry, late adjustments, CREDIT behavior and §G raw-evidence deduplication. The abbreviated “accrued + settled + ACTIVE” assertion omits part of the actual exposure projection.

AT-10 deliberately calls private admission helpers; explicitly identify it as the exception to the otherwise-public-entry-point rule.

**Recommendations on §10**

1. **Q1 — Keep 600 seconds as a documented maximum constant for this build.** A new authorization field is unnecessary unless the operator needs to choose that policy per run. The effective grace must use the durable, shorter limits in SC-5. Neither a compute hold nor a hard-stop timestamp independently enforces shutdown.

2. **Q2 — Retain the original storage hold; release through finalization.** §A says:

   > “Create a separate canonical CPU_STORAGE_TRANSFER hold for each acquisition’s attested worst storage exposure, before create.”

   And:

   > “Release this unused protective hold only after verified storage deletion and the acquisition’s disk allocations reach invoice finality, in the same finalization transaction.”

   The proposed `:contradiction` reservation creates fresh exposure after protection was released, can be refused, and conflicts with RECOVERY’s reservation prohibition. Retaining the original hold is the contract-compatible default. It does not eliminate the need for the later-contradiction incident path.

3. **Q3 — Locking the handful of prior leases is acceptable.** It is useful for serializing admission against already-visible adoption. Apply deterministic ordering and coordinate all relevant writers. It does not prevent adoption after admission commits or resolve the partial-index collision by itself.

**Implementability**

The corrected design can be built without changing the contract package or migrations 0001–0025. The necessary changes are internal Python coordination/guards and additive persistence in 0026—for authorization provenance, fixed recovery deadlines and any explicit reopened-cleanup obligation.

As written, however, the builder must invent storage finality, pending-submit recovery, crash ownership, terminal mappings and failure outcomes. Those decisions need to be fixed in the spec first. The existing event and canonical settlement machinery can support the atomic audit and replay requirements; replay safety still needs explicit callers that finish every stage.

**REWORK**

