**Verdict: REWORK.** v0.2 resolves most round-1 findings. Two budget decisions still conflict with the master or leave admission unsafe. The remaining changes are scoped below; the overall design need not be reopened.

Reviewed read-only against `feat/microdrama-m0-m4`, HEAD `0851374`. No writes or tests. A0 advanced from v0.3 to v0.4 during inspection; refresh its dependency pin before building.

References: **A** = [Phase A v0.2](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A-spec.md); **M** = [master v0.4.2](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md). “Resolved” means adequately specified for the required note/diff gates, **not implemented or verified**.

| Finding | Status | Evidence |
|---|---|---|
| AC-1 | PARTIAL | A §1/§2 preserves V1 and restores all V3 actions; CAST_LOCK/LAUNCH Reject destinations remain defective (AR-3). |
| AC-2 | RESOLVED | §2.3–4 specifies separate season notes, typed targets, deferred note validation and unchanged Gate 2 feedback. |
| AC-3 | RESOLVED | §2.6 puts ownership, binding, authoritative revision, callback and idempotent response in one transaction. |
| AC-4 | RESOLVED | §2.7 excludes unavailable handlers, production test injection and V1 fallback; tests cover JSON/HTML actions. |
| AC-5 | RESOLVED | §1 requires immutable version, reparenting protection and guards across the inherited entry-point inventory. |
| AC-6 | RESOLVED | §3 adds creation, cancellation, rewind and extension commands; A1’s reviewed note must supply their complete contracts. |
| AC-7 | PARTIAL | §3 derives concurrent waits and failures, but loses track/operation distinctions and uses an impossible replacement-success test (AR-4). |
| AC-8 | RESOLVED | §6 supplies an order; §5.3 requires ancestor acquisition before existing helpers; pre-code audits/tests are mandatory. |
| AC-9 | RESOLVED | Binding round-1 wording plus A-T6 requires activation, admission, heartbeat, adoption/transfer and janitor enforcement. |
| AC-10 | PARTIAL | Explicit lookup and aggregate-only accounts are settled; the absent-parent interval conflicts with hierarchy locking (AR-2). |
| AC-11 | RESOLVED | §5.4 defines immutable bases, guarded amendments, shared effective-cap calculation, authorization and durable wakeup. |
| AC-12 | PARTIAL | §5.3 correctly separates admission from truthful billing overruns; pre-parent serialization remains unspecified (AR-2). |
| AC-13 | PARTIAL | Setup approval, step caps and forecasts are explicit, but §5.1 changes the master’s season-cap basis (AR-1). |
| AC-14 | RESOLVED | §5.6 separates cash/accrual/exposure/attribution and tests canonical multi-receipt posting. |
| AC-15 | RESOLVED | §7.1 fences enqueue, admission and every canonical mutation, including collectors and reconciliation adoption. |
| AC-16 | RESOLVED | §7 defines effective supersession, transactional cancellation, submission invalidation and impact-bound confirmation. |
| AC-17 | RESOLVED | §8.1 chooses shared transactional fan-out, durable event/channel intents and explicit no-backfill semantics. |
| AC-18 | RESOLVED | §8.2–3 persists attempts before sending, treats crash windows as ambiguous and bounds duplicate-risk retries. |
| AC-19 | RESOLVED | §8.4 replaces invalid threshold names and requires registered payload schemas. |
| AC-20 | PARTIAL | §9.1 adds calendar periods and dedicated ownership, but blocking acquisition contradicts skipping; effect atomicity needs correction (AR-5). |
| AC-21 | RESOLVED | §9.2 selects every production role, separates dependencies and requires expiring qualifications plus dispatch checks. |
| AC-22 | RESOLVED | §0 incorporates the concrete UI requirements; §2.5 supplies activation authority and A-T7 covers route/template behavior. |
| AC-23 | RESOLVED | §10 requires pinned prerequisites, allocated immutable migrations, generated-contract checks and preserved V1 gates. |

**AR-1 — BLOCKING — The season cap now exceeds the master’s authorized envelope.**

A §5.1 sets `SEASON = episodes × episode cap + setup`. M §12.3 explicitly includes setup **inside** `episodes × US$10`. For ten episodes and $30 setup, A permits $130 where M permits $100. This is a policy change, not a DDL detail.

**Replacement:** “The base SEASON cap is episode count × the approved per-episode base cap. Setup consumes that envelope; it is never added to it. Any increase requires a separately recorded season-cap amendment. Forecasts subtract setup commitment from the capacity available for episode production.”

**AR-2 — BLOCKING — Pre-STORY LOCK admission has no valid ancestor-lock protocol.**

A §5.1 permits setup spending without a parent, while §5.3 requires every V3 commitment mutation to lock that parent first. Merely attaching the parent at LOCK permits a setup mutation that observed ‘no parent’ to race later episode admission.

**Replacement:** “Before parent existence is resolved, all setup commitment mutations and STORY LOCK acquire the same stable season mutex in §6 order. STORY LOCK atomically creates the SEASON account, attaches existing setup exposure and creates episode accounts, validating current commitments. After attachment, every mutation takes parent then child. Admission before STORY LOCK checks approved setup/step limits; parent absence afterward is an error.”

**AR-3 — SHOULD-FIX — ‘Previous planning state’ is wrong for LAUNCH and insufficient for repeat decisions.**

A §2.2 invents a meaning absent from M §2.1. LAUNCH belongs to the **release** track. `reject_to(previous)` also leaves activation closure, retained authority and re-decision identity unclear.

**Replacement:** “Reject CAST_LOCK leaves planning at CASTING without cast authority. Reject LAUNCH leaves release at CALENDAR_PROPOSED without launch authority and preserves planning. Close the decided activation and advance its decision revision; another decision requires a new activation. Changes affecting prior authority use scoped amendment invalidation and preserve unrelated approved releases.”

**AR-4 — SHOULD-FIX — Derived waits need work identity, track identity and operation facts.**

A §3 uses scope-only job links despite separate tracks and extensions. Its ‘later success for the same semantic key’ cannot occur across jobs: `jobs.semantic_key` is UNIQUE (`0001:78`). Cancelled jobs can also retain unresolved external operations (`core/jobs.py:864–870`), which the proposed derivation omits.

**Replacement:** “Derive waits by explicit scope and affected track, including extension identity. Use current content authority for ordinary waits; retain unresolved operation/cancellation blockers until reconciliation settles them, even for cancelled or stale jobs. Link replacement jobs through a logical-work/replacement identity distinct from the unique enqueue key. Acknowledgement dismisses an alert; it never establishes completion or approval.”

**AR-5 — SHOULD-FIX — Scheduler ownership and period recording need precise boundaries.**

`pg_advisory_lock` blocks; it does not implement ‘concurrent caller skips’. Existing direct handlers include multi-transaction GPU/worker sweeps (`scheduling/service.py:822–835`), so a separately recorded firing cannot make their effects atomic.

**Replacement:** “Use `pg_try_advisory_lock` on a dedicated connection; skip on false, release in `finally`, and stop starting actions if ownership is lost. Commit each period identity with its database effects or durable effect intents. External actions retain canonical operation/recovery identities; unfinished effects remain recoverable independently of the firing marker.”

**AR-6 — SHOULD-FIX — Package gates currently depend on later packages.**

A1 creation commands require A2 account factories; cancellation requires A3’s `cancel_in`. A1 nevertheless promises to validate every command. A6 combines delivery recovery, scheduler changes and production deployment wiring.

**Replacement:** “Activate commands only when their dependencies ship: account-backed creation in A2, cancellation/fencing integration in A3. Earlier compositions return NOT_AVAILABLE for those commands; their behavioral gates move with activation. Split A6 into notification delivery, scheduler behavior, and production composition/final shell pilot, each independently reviewed and accepted.”

The overall package sequence is sound after AR-6. A1–A3 note-first gates are sufficient for their intended contracts, money and fencing work, provided the notes finish the required caller audits—including provider-operation advisory locks and caller-owned billing transactions. A4/A5 notes with their diffs are reasonable. The scheduler slice should receive a pre-code note settling AR-5.

Keeping V3 legacy states at `PROPOSED`/`PLANNED` is workable under the specified guards and versioned janitor adapters. Transactional dispatcher fan-out is also workable; its handler API must receive the caller transaction, and every production dispatcher must register the required consumers, including A0 cancellation.

