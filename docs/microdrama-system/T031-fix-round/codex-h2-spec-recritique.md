**Verdict: REWORK.** V2 closes seven findings, partially closes seven, and introduces three blocking inconsistencies.

I verified the checkout at `628fe5b40ab19c6d5d1befb8539f3b6a90c2204a` against the contract, code map, round-1 critique, and [spec v2](/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md). This was a static, read-only review; no tests, writes, or provider calls.

**SC-1..SC-14 disposition**

Replacement references below point to exact proposed wording.

| Finding | Status | Reason |
|---|---|---|
| SC-1 | **PARTIAL** | Original STORAGE protection and finalization checks are corrected, but `NO_CREATE_PROVEN` can escape the acquisition index before finalization without an explicit U2 blocker. Apply R1. |
| SC-2 | **CLOSED** | U2 now excludes healthy ACTIVE acquisitions. Other predicates introduce separate happy-path blockers: SC2-1. |
| SC-3 | **PARTIAL** | Canonical linkage, uploads, and local materialization are covered; `SUBMITTED`/`RUNNING` work remains absent from the item list, and blocking scopes are incomplete. Apply R2. |
| SC-4 | **CLOSED** | Takeover explicitly converts uncertain pending submission to UNKNOWN and never transfers the first-send right. |
| SC-5 | **PARTIAL** | Persistence, heartbeat, and independent cleanup ownership are specified; aggregate GPU cutoff still mixes an allowance with timestamps, and deadline fencing lacks an explicit token-revocation transaction. Apply R3 and SC2-2. |
| SC-6 | **PARTIAL** | Expired exposure and settlement are corrected; requiring an operation for every recovery read excludes ambiguous input uploads that have no prompt operation. Apply R4. |
| SC-7 | **CLOSED** | CLI recovery precedes generation validation, returns admission blockers, and derives phase from durable screening state. |
| SC-8 | **CLOSED** | Exact source bytes, parsed-payload verification, and per-acquisition authorization/quote selection resolve the provenance defect. |
| SC-9 | **PARTIAL** | The identified inversions are corrected, but operation and upload locks have no position in the shared order despite being gate inputs. Apply R5. |
| SC-10 | **CLOSED** | Late contradiction stays outside the acquisition index, U5 can clear, and GPU accounting ignores the disproved no-create end. |
| SC-11 | **CLOSED** | Terminal recovery now includes financial finalization, complete terminal mappings, matching-slot clearing, and monotonic projection. |
| SC-12 | **PARTIAL** | Fail-fast is consistent across entry points, but outcome persistence is not made atomic with failed-sample projection and slot release. Apply R6. |
| SC-13 | **PARTIAL** | Binding outcomes are explicit, but the force rule still conflicts with the unconditional reachable-history refusal. Apply R7. |
| SC-14 | **PARTIAL** | The expanded gate is feasible offline, but its positive-path and crash assertions need the additions listed below, plus the AT-12 correction in R8. |

**Exact replacements for remaining round-1 gaps**

**R1 — §§4.1 U2, 6.2–6.3: pending finalization after no-create resolution**

The billing helper does not itself make the lease terminal. Consequently, after resolution, neither the acquisition index nor the listed concrete U2 conditions necessarily prevents another admission. The current sweep also [skips `NO_CREATE_PROVEN` rows](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:507).

> U2 also includes an acquisition in `NO_CREATE_PROVEN` whose sweep finalization is incomplete. Its exclusion from the partial unique index does not authorize the next acquisition: admission must reject this U2 under lock until the original STORAGE reservation has been canonically finalized. Sweep must process these rows for finalization, including rows whose resolution is subsequently contradicted.

**R2 — §4.1: complete the recovery inventory and blocking scopes**

AT-16 names `SUBMITTED`/`RUNNING`, but no U predicate selects those operations. “Blocks dispatch on that sample” also cannot describe acquisition-scoped upload rows, which contain no sample identity.

> Add U3p: a sample’s fixed reservation links to an operation in `SUBMITTED` or `RUNNING`, including when `sample.operation_id` is null. Recovery adopts the existing linkage and polls that operation before permitting another sample or acquisition; it never submits again.
>
> Upload items are acquisition-scoped and block every dependent sample. An upload item ceases blocking only after checksum verification, or after cleanup/audited resolution has durably fenced its send right and finalized the affected sample and its liability.
>
> U1, uncertain U3/U3u, and U5 block fresh acquisition admission and new generation throughout the experiment. U3p and U4 block fresh acquisition/sample admission until the existing work has been recovered/finalized. Local materialization, scoped recovery reads, settlement, and cleanup remain permitted.

This preserves contract §A’s requirement: “Provider uncertainty blocks new work.”

**R3 — §5.4: deadline composition and fencing**

“The remaining aggregate GPU allowance” is a duration, not an absolute deadline. The specification also does not say who invalidates a still-valid coordinator token before cleanup; the pinned implementation grants that token [one hour](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:277).

> Every operand of `recovery_deadline` is an absolute timestamp. Define the funded-work deadline with its shutdown allowance already excluded. Define the aggregate GPU deadline as the earliest timestamp at which the sum of all durable acquisition windows, including reopened windows, plus reserved shutdown GPU time reaches the effective GPU limit. Do not compare a remaining duration directly with timestamps.
>
> Persist the resulting deadline before grace. Restart and takeover reuse it and may shorten it when newly discovered liability exhausts the remaining allowance; they never extend it.
>
> At deadline exhaustion, sweep/janitor first commits a cleanup fence under the shared lock order: revoke the acquisition’s coordinator token and the matching dispatch-slot token, and prevent further execution on that acquisition. This deadline fence is an explicit exception to the rule against preempting an otherwise valid coordinator. Cleanup then runs outside the transaction.
>
> Every subsequent coordinator control write and first-send authorization checks the matching token in its transaction. Token revocation does not prove that an already-authorized external send never occurred; such effects remain subject to reconciliation and receive no replacement send right.

**R4 — §3.3: expired input readback without a prompt operation**

An ambiguous upload can precede operation creation. The current staging order demonstrates that boundary.

> For output/history recovery, prove the exact experiment, acquisition, reservation, job, operation, and pod linkage. For checksum input readback before a prompt operation exists, prove the exact experiment, acquisition, reservation, job, pod, and durable upload-intent linkage instead.
>
> This exception authorizes only scoped recovery GETs and durable output persistence. It never authorizes operation creation, pod creation, upload POST, or prompt POST, and it does not weaken the mode or transport guards.

**The exception does not inherently open a dispatch path:** the explicit three-layer mode prohibitions remain sufficient if implemented independently of reservation-state acceptance.

**R5 — §6.1: operation/upload locks and transaction boundaries**

I found **no remaining concrete cycle among the explicitly listed transactions**, provided the specified changes are applied and separate canonical transactions remain separate. Account-first billing resolution, E-before-A ambiguity handling, D-before-S projection, and L-before-D admission remove the identified cycles.

The order is nevertheless incomplete for the expanded gate:

> Extend the order after reservation rows to include the existing provider job/reservation advisory locks where needed, provider-operation rows ordered by ID, and upload rows ordered by their immutable key.
>
> Gate decisions lock the relevant existing operation/upload rows. Benchmark operation/upload insertion must also serialize through the corresponding locked reservation/acquisition ownership row, so an absent-row query cannot race a new intent into existence.
>
> Canonical operation-only result transactions may retain their suffix-only locking, but must not acquire earlier-order benchmark or budget locks afterward. Operator terminal-transition transactions commit before invoking financial finalization. The transaction inventory must distinguish these transactions explicitly.

**R6 — §§7.1, 7.4: atomic fail-fast projection**

Otherwise, a crash after writing FAILED and clearing D, but before recording the experiment outcome, leaves finalized evidence that no longer appears as U4.

> After canonical financial finalization, projection of an eligible failed fixed sample, setting `execution_outcome=FAILED` if unset, stopping generation, and clearing its matching dispatch slot commit in one transaction. Acquire E before D before S, with any required earlier locks taken first. Before projection completes, U4 blocks fresh work. Replay repairs the same failure outcome idempotently.

**R7 — §7.3: force-rule precedence**

“Reachable-but-unrecoverable requires force” and “BOUND with reachable history → refuse” overlap.

> `BOUND` with positively recoverable work or usable output requires reconciliation and refuses operator resolution, including force. Reachability alone is not recoverability: empty, missing, conflicting, or unusable history remains ambiguous. Such reachable-but-unrecoverable cases, and INDETERMINATE cases, require `--force-unrecoverable` plus the recorded attestation. Identical-attestation replay is accepted before any live-source check.

**R8 — AT-12: use the contract’s exact exposure formula**

Replace “ACTIVE/EXPIRED remainder” with:

> Exposure equals canonical accrued plus settled counters, plus `max(reserved − accrued, 0)` only for ACTIVE reservations, plus distinct linked unreserved non-CREDIT usage. EXPIRED reservations contribute their canonical accrued/settled counters and zero open remainder. Never add expired exposure a second time.

That matches contract §A’s explicit rule: “ACTIVE => max(original_reserved - accrued,0), otherwise0.”

**New v2 blocking issues**

**SC2-1 — BLOCKING — §§4.1–4.2: intent predicates block the original first send**

Re-running the SC-2 check across the whole table exposes three failures:

- **U3:** normal submission commits `PENDING_SUBMIT` [before the first prompt POST](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/rendering/comfy_jobs.py:657). The dispatch gate then sees its own blocking U3.
- **U3u:** staging commits INTENT and then UNKNOWN [before its first upload POST](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/experimental_world.py:585). The same problem occurs.
- **U6:** “without a job **or operation**” includes legitimate input staging after job materialization but before prompt-operation creation. Blocking every effect until the operation exists creates an ordering dead end.

U2’s original happy-path defect is fixed. U4 and U5 do not inherently classify healthy work. U1 needs the same original-owner distinction if consulted at the create transport boundary.

**Replacement wording:**

> For each effect, distinguish its original first-send invocation from recovery of a pre-existing intent. The original invocation may consume its exclusive first-send right once while its original ownership token remains valid; its own newly committed intent does not block that exact send. Every other blocking item still applies. Replay and takeover never acquire this right.
>
> U6 permits local materialization. Once canonical sample job/hold ownership exists, absence of a prompt operation alone does not prohibit original input staging; prompt POST still requires the canonical operation to have been begun. After ownership loss, existing intents are reconciliation-only.

**SC2-2 — BLOCKING — §§4.1 U2, 5.4: a successful grace remains a future cleanup trigger**

The deadline is stored on the acquisition. Grace success permits continued work, but U2 says “recovery-deadline passed” without requiring that recovery remain unresolved. Thus a recovered acquisition becomes blocked again when its historical grace expires, and the janitor can terminate healthy subsequent work.

**Replacement wording:**

> U2’s recovery-deadline condition and deadline-driven cleanup apply only while an ambiguity on that acquisition remains unresolved. Successful terminal recovery closes that recovery episode; its historical deadline alone does not block or terminate subsequent healthy work.
>
> Retain the persisted deadline. A later ambiguity on the same acquisition reuses it and starts cleanup immediately if it has already elapsed. Ordinary funded-runtime, aggregate-GPU, and hard-stop limits remain independently enforceable.

This preserves Q1 and the no-fresh-grace rule.

**SC2-3 — BLOCKING — §6.2: successful create resolution cannot replay**

After the first commit, A is `NO_CREATE_PROVEN` and U1 is false. A retry therefore fails §6.2’s first precondition, including after a crash immediately following the successful commit. V2 removed the old replay escape without replacing it.

**Replacement wording:**

> Under the same locks, before unresolved-state preconditions, recognize an existing uncontradicted no-create resolution with identical actor, reason, and evidence SHA. Return successful replay without another audit or settlement, and permit the pending sweep finalization to complete. Different attestation data, a bound pod, or a contradicted resolution produces Conflict. Apply the unresolved-state preconditions only to a first resolution.

**Acceptance gate: feasible offline, insufficient as currently worded**

Local PostgreSQL, controlled clocks, durable fake HTTP state, and subprocesses can prove these software invariants. No live provider is needed. The missing assertions are:

| Extend | Missing invariant proof |
|---|---|
| AT-0 / AT-10 | Drive the real first create/upload/prompt sequence through all guards; prove original sends succeed once while replay/takeover sends fail. Claiming samples alone cannot catch SC2-1. |
| AT-6 / AT-9 | Resolve no-create without adoption; verify admission remains blocked until STORAGE finalization; replay identical/different attestations before and after sweep. |
| AT-16 / AT-17 / AT-20 | Cover known in-flight operations through missing sample linkage, acquisition-scoped upload blockers, and EXPIRED input readback with no prompt operation. Include wrong-owner/mode and POST refusals. |
| AT-18 / AT-19 | Recover successfully, continue beyond the historical grace deadline, then encounter another ambiguity. Also fence a still-valid coordinator token and assert stale control writes fail—not only stale dispatch. |
| AT-9 / AT-22 | Crash between failed operation settlement and failed-sample/outcome/slot projection; exercise FAILED, CANCELLED, and NOT_FOUND. |
| AT-21 | Race gate evaluation with operation transitions and upload-intent insertion, including initially absent rows. |
| AT-8 / AT-25 | Exercise the binding/recoverability/force matrix and identical replay before live checks. |

For the death harness, a `BaseException` subclass alone does **not** bypass the pinned handler: `_advance_owned` [catches `BaseException`](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:364). Use SIGKILL/`os._exit`, or demonstrate that each alternative injection escapes cleanup. Fake provider state and send counters must survive the killed process.

Q1–Q3 and fail-fast remain accepted. The unresolved edits above go to the operator after this final critique round.

