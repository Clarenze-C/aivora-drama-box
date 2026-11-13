# A6b note critique round 1 — GLM rulings (13 Nov 2026)

Input: `codex-a6b-note-critique.md` (verdict REWORK; N6-1..6 BLOCKING, N6-7..11 SHOULD-FIX) against
`A6b-design-note.md` v1.0. Every ruling is a **GLM ruling, Opus re-check Mon**. The try-lock /
atomic-period approach is confirmed sound. **All 11 ACCEPTED**; no operator decision; no V1 test is
adapted (N6-4 explicitly preserves V1 assertions unchanged).

| ID | Ruling (one line) |
|---|---|
| N6-1 | ACCEPT — ownership checked before each independently started action in a sweep (each lease/pod action, each shot dispatch); loss stops subsequent actions; started operations finish via canonical recovery; recovered dispatch reuses the original operation/attempt identity (kills the double-paid-attempt window at `scheduling/service.py:758-765`). |
| N6-2 | ACCEPT — every INTENTS effect gets a canonical recovery identity + path at each interruption boundary; unresolved obligations recovered independently of period claims; supersession only when a successor durably covers; retryable vs terminal failures defined; coalesced recovery allowed without replaying every missed period; aggregate identity ≠ effect deduplication (event_id added). |
| N6-3 | ACCEPT — raw durable period token separated from the enqueue-key prefix; V1 job keys preserved exactly (`sched:{schedule_id}:{bucket}:…`); every new key carries its trigger namespace. |
| N6-4 | ACCEPT — V1 elapsed-interval eligibility preserved via durable firing timestamps; bucket/calendar eligibility only for new schedules; one-time provenance-preserving cutover from `schedule_state` (retains last eligible firing + semantic keys); V1 timing assertions unchanged. |
| N6-5 | ACCEPT — integer-only payloads: counts, integer durations, explicitly scaled/rational rates (`required_numerator`/`required_denominator`, cross-multiplied comparison); decimals display-only; A6a schemas aligned before build. |
| N6-6 | ACCEPT — two-minute LLM reconciliation trigger added with an explicit execution/recovery contract, preserving A0's own-worker RESUME authority, UNKNOWN/operator boundary, no requeue of in-flight operations, and A3's fence on adoption. |
| N6-7 | ACCEPT — complete lock inventory registered (incl. provider-op + first-boot seed locks); scheduler key reserved in the two-integer namespace; `TickOwnership` yields a handle with `still_held()`; key form/objsubid/granted-mode/backend matched; connection always closed. |
| N6-8 | ACCEPT — key derived from the candidate's scheduled local date; injected aware timestamps throughout; SQL `now()` replaced by the injected clock in period selection + metric queries; bounded measurement windows; execution time distinct from claimed summary date; candidates older than the durable watermark rejected; midnight/09:00/rollback/first-run tested. |
| N6-9 | ACCEPT — distinct episodes counted via A4's effective approval authority; reporting scope + cancellation policy defined and applied; buffer counts current approved full-episode obligations only (no superseded authority, no unrelated slot kinds); reapproval/supersession/cancellation/multi-season tested. |
| N6-10 | ACCEPT — command/effect rows completed (actor, scope/revision owner, states/prerequisites, transaction+locks, events, jobs, replay); caller transaction through atomic handlers; V3 enqueue/adoption routed through A3's fence before job locks; V1 cadence inserts no V3 tracks; A6a payload schemas pinned; only transactional event emission. |
| N6-11 | ACCEPT — skips neither refresh nor override health; successful completion defined; trigger + sweep-item failures propagate into tick errors; health requires a non-future successful timestamp within three configured intervals; orphaned RUNNING tick recovery defined. |

**Apply:** fold all 11 into `A6b-design-note.md` **v1.1** (job `dramabox:a6b-note-rev1`, docs only, queued
last in the docs queue). Codex round 2 follows the revision.
