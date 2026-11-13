**Verdict: REWORK.** The try-lock and atomic-period approach is sound, but ownership loss, recovery, V1 compatibility and event serialization need correction before code.

Reviewed A6b v1.0 against Phase A v0.3, A0 v0.4, A1 v1.2 and master v0.4.6; inspected current code at `1c62bb6` and scratch migrations 0026/0027. No writes or database tests. Small in-memory checks confirmed the cadence counterexample and float rejection.

References: **N** = [A6b-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md); **S/** = `microdrama/src/microdrama/`; **X/** = `microdrama/tests/`.

**N6-1 — BLOCKING — Ownership checks permit new actions after ownership loss.**  
`N:176–183`, `N:408`. A sweep contains multiple actions, transactions and external calls. Checking only before entering it lets the former owner continue dispatching shots or cleaning additional leases after another scheduler acquires ownership. In particular, `S/scheduling/service.py:758–765` recalculates `attempts_used + 1`: overlapping dispatchers can turn the same pending shot into another paid attempt.

**Replace:** “Check ownership before each independently started action within a sweep, including each lease/pod action and shot dispatch. Loss stops subsequent actions; only already-started operations may finish through their canonical recovery path. Recovered dispatch uses the original operation/attempt identity.”

**N6-2 — BLOCKING — Intent supersession does not establish recoverability or exactly-once effects.**  
`N:211–244`. An existing firing proves only that its **intent** committed. Pending intents are discarded at the next period, failed intents have no retry policy, and recovery depends on an unproven assertion about existing handlers. The cited deterministic janitor **aggregate** does not deduplicate events: `S/rendering/janitor.py:169–179` omits `event_id`, so `append_event` generates a fresh UUID (`S/core/events.py:87`).

**Replace:** “For every INTENTS effect, specify its canonical recovery identity and recovery path at every interruption boundary. Recover unresolved obligations independently of whether their period is already claimed. Supersede only when a successor durably covers the unfinished work; define retryable versus terminal failures. A recurring sweep may coalesce recovery without replaying every missed period. Aggregate identity alone is not effect deduplication.”

**N6-3 — BLOCKING — Raw period tokens can collide across triggers’ job keys.**  
`N:255–257`, `N:280–283`. Today `ScheduleCatalog.period_key()` returns `sched:{schedule_id}:{bucket}`. Replacing that return value with a raw bucket removes the trigger namespace from existing callers. Publish-submit and publish-poll then both produce `{bucket}:{post_id}` (`S/scheduling/service.py:624`, `:667`), causing `IdempotencyConflict` between different job types.

**Replace:** “Separate the raw durable period token from the enqueue-key prefix. Preserve existing V1 job keys exactly: `sched:{schedule_id}:{bucket}:…`. Every new key includes its trigger namespace.”

**N6-4 — BLOCKING — Bucket eligibility changes V1 cadence, and retirement lacks a cutover protocol.**  
`N:117–119`, `N:263–289`, `N:403`. A daily trigger fired at 23:59 becomes eligible at 00:00 under the new rule—one minute later. Current V1 requires an elapsed day; `X/unit/pipeline/test_scheduling_registry.py:34–41` explicitly pins elapsed eligibility and refusal of backward-clock firing. Adapting those assertions would weaken V1 tests, contrary to Phase A §1. Ignoring existing `schedule_state` also permits immediate replay at upgrade, including another cadence episode insertion.

**Replace:** “Preserve V1 elapsed-interval eligibility using durable firing timestamps. Introduce explicit bucket/calendar eligibility for new schedules. Define a one-time, provenance-preserving cutover from `schedule_state` that retains the last eligible firing and existing semantic keys. Keep V1 timing assertions unchanged.”

**N6-5 — BLOCKING — Proposed event payloads violate integer-only serialization.**  
`N:277–279`, `N:309–312`. `count / 7.0` and `required_per_day=1.25` cannot pass canonical JSON or persistence guards (`S/contracts/hashing.py:44–45`, `S/persistence/db.py:65–74`). Summary/alert emission therefore rolls back.

**Replace:** “Persist counts, integer durations and explicitly scaled or rational rates. For example: `approved_count`, `window_days`, `required_numerator=5`, `required_denominator=4`; compare `4 × approved_count` with `5 × window_days`. Render decimal rates only for display. Align A6a schemas with these representations before build.”

**N6-6 — BLOCKING — A0’s required two-minute reconciler is absent.**  
`N:218–226`, `N:284`, `N:355–357`. A0 v0.4 §5.3 explicitly assigns Phase A the automatic LLM reconciliation schedule. Neither the trigger table nor catalog adds it. Scratch A0 provides `llm/reconciler.py:LlmReconciler.reconcile_due`, but a CLI entry point does not supply automatic scheduling.

**Replace:** “Add a two-minute LLM reconciliation trigger with an explicit execution/recovery contract. Preserve A0’s own-worker RESUME authority, UNKNOWN/operator boundary and prohibition on requeueing in-flight operations. Preserve A3’s fence when adopting results; cleanup and accounting remain recoverable for stale work.”

**N6-7 — SHOULD-FIX — The advisory-lock namespace claim and ownership API are incomplete.**  
`N:129–146`, `N:167–176`. Full-width hashes can equal a fixed bigint; different hash seeds do not make disjoint namespaces. The audit also omits provider-operation locks and the first-boot seed lock. Separately, `Iterator[bool]` supplies no connection handle for `TickOwnership`.

**Replace:** “Register the complete lock inventory and reserve a scheduler key in the two-integer namespace, separate from existing bigint callers. Yield an ownership handle exposing acquisition state and `still_held()`. Match the key form, `objsubid`, granted exclusive mode and backend in ownership checks; always close the connection even if unlock fails.” PostgreSQL documents the [separate key spaces](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS) and [lock-view encoding](https://www.postgresql.org/docs/18/view-pg-locks.html).

**N6-8 — SHOULD-FIX — Clock injection and calendar-period semantics remain inconsistent.**  
`N:255–270`, `N:306`, `N:328`, `N:394`. Before 09:00, the candidate is yesterday, contradicting “local date of now.” The **date** changes at midnight; the latest-due summary period advances at 09:00. SQL `now()` ignores the injected clock. Checking only for an absent firing also allows clock rollback to resurrect older periods supposedly skipped forever.

**Replace:** “Derive the key from the candidate’s scheduled local date. Use injected, aware timestamps throughout period selection and parameterized metric queries; define bounded measurement windows. Keep execution time distinct from the claimed summary date and its reporting day. Reject candidates older than the durable scheduling watermark. Test midnight, 09:00, rollback and first-run boundaries.”

**N6-9 — SHOULD-FIX — Metrics count decisions and slots without sufficient authority checks.**  
`N:297–335`. Reapproving one episode can count it twice toward throughput. Superseded approvals remain included. Buffer dates can be inflated by promo/hook slots, cancelled work, or inventory outside the intended reporting scope.

**Replace:** “Count distinct episodes using A4’s effective approval authority. Define and consistently apply the reporting scope and cancellation policy. Buffer counts current approved full-episode obligations on the current calendar, excluding superseded authority and unrelated slot kinds. Test reapproval, supersession, cancellation and multiple seasons.”

**N6-10 — SHOULD-FIX — Finish the command/effect contract and fence/outbox audit.**  
`N:218–226`, `N:275–279`, `N:371–374`. Atomic summary emission through `append_event` is correct, but payload field lists leave types, aggregate/scope identity and deep-link inputs unsettled. The lock audit’s “no track locks” cannot cover added V3 enqueue/adoption paths. Its V1 cadence row also unexpectedly includes `episode_tracks` creation.

**Replace:** “Add command/effect rows covering actor, scope/revision owner, allowed states/prerequisites, transaction and locks, events, jobs and replay result. Pass the caller transaction through atomic handlers. Route V3 enqueue/adoption through A3’s fence before job locks; preserve STORY/CAST authority. V1 cadence inserts no V3 tracks. Pin A6a payload schemas and use only transactional event emission followed by its dispatcher/sender.”

**N6-11 — SHOULD-FIX — A skipped tick does not prove health.**  
`N:152–154`, `N:196–198`, `N:337–342`, `N:405`. A lock holder may be hung or repeatedly failing. The proposed status also calls a tick successful when every trigger fails; janitor item failures can remain buried in action summaries.

**Replace:** “Skips neither refresh nor override health. Define successful completion explicitly, propagate trigger and sweep-item failures into tick errors, and require a non-future successful timestamp within three configured timer intervals. Define recovery of orphaned RUNNING tick records.”

**N6-12 — SHOULD-FIX — Expand A-T14 beyond interruption before effects begin.**  
`N:391–397`. The real SIGKILL cases are valuable, but killing after intent visibility does not prove recovery after a partially completed effect. The completed-dispatch replay case misses takeover during dispatch.

**Replace:** “Add real holder-backend termination while the scheduler process remains alive; assert no subsequent sweep item starts. Kill before/after canonical effects and before intent completion, then recover both within the same period and after rollover. Assert stable operation identities using counters/evidence surviving subprocess death. Add semantic-key collision, V1 cutover, backward-clock, fence-race and A6a fan-out/rollback cases.”

The seven open questions:

| Question | Answer |
|---|---|
| **OQ-1** | **Yes**, retire ongoing `schedule_state` reads/writes after the explicit compatibility cutover in N6-4. Retain its historical rows and guards. |
| **OQ-2** | **Yes**, use a positive composition parameter for the host timer cadence, default 60 seconds; inject it into health queries now. |
| **OQ-3** | **No tick row is necessary for skips.** Report them separately; they confer no freshness or health. |
| **OQ-4** | **Accept the proposed activation gating:** buffer during LAUNCH_APPROVED/RELEASING, throughput during RELEASING; otherwise report unavailable. Define scope consistently. |
| **OQ-5** | **Resolve before A6b code**, against accepted A6a schemas, including integer representations, scope, timestamps and deep links. |
| **OQ-6** | **Reject the recommendation.** Check before individual newly started actions inside sweeps; retain canonical recovery for in-flight operations. |
| **OQ-7** | **One lock and catalog is appropriate**, with bounded actions. V1 and V3 do not need separate singleton namespaces. |

Calendar coverage: **09:00 Bangkok = 02:00 UTC; 19:00 Bangkok = 12:00 UTC.** Release slots and teaser scheduling remain Phase F obligations: teaser date is the premiere’s Bangkok date minus three days, under approved calendar/content authority. A6b catch-up must not become permission to publish missed or held slots.

The symbolic **A6b-1** allocation and deferral of production composition to **A6c** are appropriate. Resolve its numeric migration filename after the accepted upstream tail; preserve A1’s 0028–0031 allocation and all applied bytes.