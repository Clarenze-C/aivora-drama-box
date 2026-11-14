**Verdict: REWORK.** Seven findings are closed at design level; five remain partial, including two blocking recovery gaps.

Reviewed v1.1 at `8cd4453` against the binding specs and current code. Read-only; no writes or database tests.

References: **N** = [A6b-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A6b-design-note.md); **S/** = `microdrama/src/microdrama/`.

| Finding | Status | Evidence |
|---|---|---|
| N6-1 | **CLOSED** | §3, `N:218–229`: checks each independently started action; recovered dispatch must reuse its original attempt rather than recalculate `attempts_used + 1`. This explicitly requires changing the unsafe behavior at `S/scheduling/service.py:758–765`. |
| N6-2 | **PARTIAL** | §4, `N:284–308`: recovery identities and failure classes added, but deduplication and same-period recovery remain incorrect/incomplete. **N6R2-1/2**. |
| N6-3 | **CLOSED** | §5, `N:340–345`: raw firing tokens separated from byte-preserved V1 enqueue prefixes. |
| N6-4 | **CLOSED** | §5, `N:373–396`: elapsed eligibility retained; cutover copies `last_fired_at` verbatim and preserves semantic keys and timing assertions. |
| N6-5 | **CLOSED** | §6, `N:437–444`: integer counts and rational thresholds replace persisted floats. Schema pinning remains under N6-10. |
| N6-6 | **CLOSED** | §4/§5, `N:281`, `N:303`, `N:407–409`: explicit 120-second trigger, own-worker RESUME, UNKNOWN boundary, and A3 adoption fence. |
| N6-7 | **CLOSED** | §3, `N:142–215`: separate two-integer namespace, expanded inventory, ownership handle, precise lock check, unconditional connection close. |
| N6-8 | **PARTIAL** | §5’s algorithm is corrected, but its catch-up example and S4 boundary expectations contradict it. **N6R2-5**. |
| N6-9 | **PARTIAL** | §6, `N:425–434`, `N:454–469`: query predicates still disagree with effective authority and cancellation policy. **N6R2-3**. |
| N6-10 | **PARTIAL** | §4/§8 add effect and lock contracts, but event schemas, aggregate identities and deep-link inputs remain deferred. **N6R2-4**. |
| N6-11 | **CLOSED** | §3/§6, `N:236–252`, `N:482–493`: explicit success, propagated failures, orphan recovery, and non-future freshness; skips confer nothing. |
| N6-12 | **PARTIAL** | §9 substantially expands coverage, but several proposed tests cannot establish their stated guarantees. **N6R2-5**, plus recovery corrections below. |

**N6R2-1 — BLOCKING — A deterministic event ID does not make `append_event` replay a no-op.**

§4 `N:302` and S3 `N:550` rely on a PK collision succeeding harmlessly. `S/core/events.py:101–144` increments the sequence and performs a plain INSERT; a duplicate ID raises and aborts the transaction. Also, actual lease-clean events use `_lease_event` (`S/rendering/janitor.py:153–164`, `:333–357`), so changing `_evidence` alone does not deduplicate them.

**Replacement:** “Provide a transaction-safe append-once path for each canonical event occurrence. Matching replay returns the stored event without another sequence increment or transaction failure; conflicting reuse fails explicitly. Cover the actual lease-clean events as well as `_evidence`. Replay tests assert successful recovery, unchanged sequence and exactly one canonical event.”

**N6R2-2 — BLOCKING — The tick algorithm cannot perform the promised same-period recovery.**

§3 `N:240–243` runs only due triggers; §4 `N:266–269` skips claimed periods. After an INTENTS claim commits and its process dies, an elapsed schedule is not due again until its interval passes. There is no independent recovery step, despite S2 requiring recovery within the same period (`N:549`).

**Replacement:** “Each owned tick runs a bounded recovery pass for unresolved PENDING and FAILED/RETRYABLE obligations independently of new-period eligibility and firing claims. Reuse canonical identities without reclaiming the firing. Complete the original intent, or supersede it only after durable successor coverage. TERMINAL obligations remain operator-owned.”

**N6R2-3 — SHOULD-FIX — The metric SQL still misreads approval and cancellation authority.**

§6 `N:467–469` excludes an episode if **any historical approval** was superseded: supersede A, approve B, and the valid episode remains excluded forever. It also never verifies that `p.approval_event_id` matches current authority. Both metric queries omit cancellation predicates, although cancellation is independently stored in `season_tracks.cancelled_at` and `episode_tracks.cancelled_at` (A1 §2.3).

**Replacement:** “Resolve EPISODE_FINAL authority through A4’s `effective_approval`; count distinct episodes using that effective approval’s timestamp. Buffer posts must bind to that effective approval. Both metrics exclude cancelled episode scopes and cancelled season ancestors. Test supersede → reapprove → valid replacement post, stale-bound posts, and cancellation without a production-state change.”

**N6R2-4 — SHOULD-FIX — OQ-5 is labelled resolved without a pinned event contract.**

§4 `N:326–329`, §5 `N:400–401`, and OQ-5 `N:564` promise later schema alignment. They do not identify accepted schema versions, typed complete payloads, aggregate/correlation identities, or deep-link inputs. This leaves part of N6-10 unresolved.

**Replacement:** “Record the accepted A6a schema identifier/version and complete field types for `summary.daily`, `buffer.low` and `slo.below`, including unavailable metrics, reporting scope/date, execution timestamps, aggregate/correlation identity and deep-link inputs. Until supplied, OQ-5 remains open and blocks A6b code.”

**N6R2-5 — SHOULD-FIX — Correct the test oracles and exercise actual dispatch takeover.**

§5 `N:355–359` and S4 `N:551` describe Wednesday 10:00 claiming Tuesday, although the latest-due rule selects Wednesday. S4 also says midnight creates a new candidate date; the summary candidate advances at 09:00. S2’s GPU-janitor fixture cannot itself exercise the render-dispatch interruption also listed there.

**Replacement:** “Use Wednesday 08:00 for Tuesday catch-up; Wednesday 10:00 claims Wednesday. Assert that midnight leaves the latest-due summary candidate unchanged and 09:00 advances it. Add a separate real `w05-render-dispatch` subprocess scenario: terminate A’s lock backend while A remains alive, let B recover during A’s in-flight dispatch, then assert one original attempt/provider operation and no later action by A. Test same-period recovery through the scheduler entry point and successful duplicate-event replay.”