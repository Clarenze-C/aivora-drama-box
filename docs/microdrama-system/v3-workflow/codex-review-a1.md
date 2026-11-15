**Verdict: FIX-REQUIRED** for `eea2f79..57df5a9`.

1. **A1V-1 BLOCKING — REJECT/REVISE can authorize a gate transition.** [v3_require_gate_approval](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:547) accepts any latest `DECIDED` event without reading the approval’s action or verifying current content. After STORY_LOCK REJECT, `advance_planning(..., to="STORY_LOCKED", expected_revision=1)` passes. An in-memory SQL probe confirmed the rejected approval is returned. Require APPROVE, complete scope and current binding/revision authority; test rejection, revision and stale-content cases.

2. **A1V-2 BLOCKING — the implemented lock order contradicts §§8–9.** [_record_pod_id](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/rendering/leases.py:1080), `_activate` and `transfer` lock the lease before acquiring track locks. [supersede_gate](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_tracks.py:337) similarly locks the activation first. These invert track-first transactions, including decision inserts taking activation FK locks. Read immutable scope identifiers without locking, acquire ordered track locks, then lock/revalidate the leaf. Add actual competing-service tests for these paths.

3. **A1V-3 BLOCKING — lock approvals never advance the content fence.** [bump_scope_revision](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:261) updates only `revision`; the shipped test handler’s transition helper also leaves `content_revision` unchanged. STORY_LOCK/CAST_LOCK APPROVE therefore violate §6. The callback additionally writes the decision revision before the final revision writer. Centralize the single revision advance and required content-fence increment; keep callback transitions within that decision context.

4. **A1V-4 SHOULD-FIX — enqueue validation uses the wrong boundary.** [enqueue](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/jobs.py:473) requires the fence only when `track` is supplied: omitting it admits resolved V3 work with a closed V1 payload, no fence and no wait projection. Conversely, ancestry validation runs before workflow resolution/replay and newly rejects V1 replays whose explicit scope arguments differ. Both paths were reproduced with in-memory transaction doubles. Enforce V3 requirements from resolved workflow while preserving the V1 type/input-hash replay rule.

5. **A1V-5 SHOULD-FIX — GPU wait checks do not consistently cover their scope.** [extension activation](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_tracks.py:252) checks prior-lease resolution for only one episode (`LIMIT 1`); an unresolved stopped lease elsewhere in the range is missed. [heartbeat](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/rendering/leases.py:1229) checks only episode activations, missing season/extension waits. Meanwhile `season_open_activation_exists` treats extension waits as season-wide. Share a complete scope predicate across activation, admission, heartbeat and janitor; test multiple extension episodes and unaffected scopes.

6. **A1V-6 SHOULD-FIX — HTML Gate 2 cannot reach NOT_AVAILABLE.** [decide_form](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/review/v3_api.py:103) cannot carry `episode_id` or feedback. All three EPISODE_FINAL actions fail command validation with `SCHEMA_INVALID`; the HTML test covers only STORY_LOCK APPROVE. Support valid gate-specific command shapes and test every required gate × action on both surfaces.

7. **A1V-7 SHOULD-FIX — D2 does not preserve all legacy diagnostic precedence.** [approval_events_gate_rules](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/migrations/0029_v3_gate_rules.sql:103) sorts before `approval_events_human_session`. A V1 SEASON_CONCEPT REVISE with an expired session previously failed the human guard (`42501`); it now fails `approval_events_check1` (`23514`). The reproduced CHECK messages are correct individually, but precedence changed. Run the replacement after retained BEFORE guards and compare combined-invalid cases against 0027.

8. **A1V-8 SHOULD-FIX — track errors precede owner-scoped NotFound.** [_decide_action](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_gates.py:340) calls `lock_scope_track` before ownership validation. Missing/untracked scopes return `GateNotReady`, while foreign tracked scopes return `NotFound`, exposing track existence and violating §5/A-T2. Perform a nonlocking access check before exposing track errors, then retain the ordered locks and authoritative recheck.

9. **A1V-9 SHOULD-FIX — required decision events are absent.** [record_v3_decision](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_approvals.py:147) inserts the activation event but emits only `approval.recorded`. No path emits `gate.decided`; REVISE/REJECT also advance the track revision without `track.advanced`. Append the §6 event set transactionally and verify success, replay and rollback.

10. **A1V-10 SHOULD-FIX — unshipped planning edges are enabled.** [PLANNING_EDGES](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/core/v3_tracks.py:67) declares non-gate edges “phase-independent” and permits them immediately. §6 explicitly makes those edges unavailable until their phases ship. Add planning-edge availability control and require `NOT_AVAILABLE` with zero writes for inactive edges.

11. **A1V-11 SHOULD-FIX — direct legacy isolation remains incomplete.** [current_lock_row](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/references/identity_lock.py:277) returns `None` for V3 when no lock exists; [ProgressProjection.season_view](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/review/progress.py:582) produces a V1 projection for an empty V3 season. Both were reproduced. Add workflow refusal before empty-result/projection handling, preserving V1 and missing-row behavior.

The A1 acceptance rows are **not yet satisfied**:

| Row | Assessment |
|---|---|
| A-T1 | Vocabulary, schema publication and identity structure look consistent; V1 diagnostic precedence fails A1V-7. |
| A-T2 | Three-way stale comparisons and exact-activation checks are present. Gate authority, fence and owner handling fail A1V-1/3/8. Notes are stored and targets checked; targeted regeneration is unproven. |
| A-T3 | JSON refusal exists; required HTML matrix fails A1V-6. |
| A-T4 | Authority, availability, enqueue and event gaps: A1V-1/4/9/10. |
| A-T5 | Broad guard/filter coverage, but incomplete direct-read refusal: A1V-11. |
| A-T6 | Wait-view mappings look consistent; GPU scope/locking requirements fail A1V-2/5. |
| A-T16 | Allocation and additive DDL are consistent. Upgrade evidence is incomplete: no historical approvals are seeded, and existing jobs are compared only for `defer_reason` and new NULL columns. Seed approvals and compare every pre-existing column. |

The master rows must retain their superseded package boundaries:

| Master row | A1 conclusion |
|---|---|
| V3-AT-1 | Durable foundations only; complete stepper/status acceptance belongs to A5/A-T7. |
| V3-AT-2 | Fails the standalone transition authority check; stale-decision refusal exists. Note-only regeneration awaits handler evidence. |
| V3-AT-13 | Receipt/cost acceptance remains A2/A-T11; not established here. |
| V3-AT-16 | Bot dedupe, timeout and ambiguity recovery remain A6a/A-T13; no Telegram approval path was introduced. |
| V3-AT-20 | Provider crash/recovery acceptance remains A3/A-T18; not established here. |
| V3-AT-21 | Hierarchical concurrent-budget acceptance remains A2/A-T9–10; not established here. |

All eight recorded deviations were weighed:

| Deviation | Disposition |
|---|---|
| 1: fresh-intake guard | Reasonable: creation constructs V1. |
| 2: empty `current_lock` | Not acceptable under §7; A1V-11. |
| 3: 0008 package precedence | Correct for that case; does not resolve A1V-7. |
| 4: commit/package split | Reasonable; allocation remains intact. |
| 5: closed payload refusal | Safe refusal, insufficient implementation/evidence. The replay probe changes the input hash, so it does not isolate scope comparison. |
| 6: substituted GPU race | Insufficient: the holder locks an episode track while the season-gate opener locks only the season track; the unresolved lease can cause refusal without contention. |
| 7: extended V1 expectations | Reasonable additions, but broader acceptance claims exceed the assertions. |
| 8: annotation handling | Reasonable for the closure dependency. |

The repaired 429-interrupted WIP has disclosed provenance; its reconstructed red baseline is not pristine-base evidence. Independently, all 57 changed Python files parse, all 328 generated artifacts validate without drift, and V1/V2 generated bytes plus migrations 0001–0027 are unchanged. This review made no filesystem/database changes; PostgreSQL integration suites and the full gate were not rerun.

