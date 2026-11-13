**Verdict: REWORK.** v1.2 resolves several substantive findings, but executable DDL, V1 artifact preservation, and decision identity still need correction before building.

Reviewed read-only against master v0.4.6, Phase A v0.3, A0 v0.4, current code at `1c62bb6`, and the supplied A0-D migrations. An in-memory Pydantic probe confirmed the schema defect below. No files or databases changed; no database tests run.

**N** = [A1-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md); **S/** = `microdrama/src/microdrama/`.

| Finding | Status | Section and evidence |
|---|---|---|
| N1-1 | PARTIAL | §2.2/§2.4: parameter names and job aliases are corrected, but the revised view still cannot compile; N1R-1. |
| N1-2 | CLOSED | §2.2, §4, §5: Gate 2 Revise retains timecoded feedback and its persistence; existing approval guards remain. |
| N1-3 | PARTIAL | §4: typed rejection and V3 registration are specified, but the proposed schema pin changes frozen V1 bytes; N1R-2. |
| N1-4 | CLOSED | §2.4: `alert_dismissals` explicitly receives TRUNCATE and integer-number guards. |
| N1-5 | CLOSED | §2.3: immutable activations plus unique, append-only terminal events implement the ruling without fabricated approvals. |
| N1-6 | CLOSED | §5: ownership precedes workflow/state validation; ancestry and the three-way hash/revision comparisons are explicit. |
| N1-7 | CLOSED | §5: the ruling is explicit—validate/record at r, transition in context, advance exactly once. |
| N1-8 | PARTIAL | §8–§9: attachment points and ACTIVE heartbeat refusal are named; lock ownership and shutdown predicates remain problematic; N1R-8/9. |
| N1-9 | PARTIAL | §2.4: enqueue fields, extension fences and scoped replacements are specified; scope immutability and typed Job plumbing remain incomplete; N1R-5. |
| N1-10 | CLOSED | §2.4/§3/§12: all eight reasons map explicitly; NULL projects no wait. Actual A0-D 0027 contains the matching write-boundary CHECK. |
| N1-11 | PARTIAL | §2.4: operation subjects are admitted, but optional job context still participates in dismissal identity; N1R-6. |
| N1-12 | CLOSED | §5 step 1: explicit preflight runs after replay lookup and before the first INSERT. |
| N1-13 | PARTIAL | §5: intrinsic provenance replaces the registration flag, but the production rejection boundary remains assigned to A6; N1R-12. |
| N1-14 | PARTIAL | §7: all missing boundaries are listed, but point reads are assigned listing filters instead of explicit refusal; N1R-10. |
| N1-15 | PARTIAL | §6: command families and revision owners are added; Reject feedback and activation identity remain inconsistent; N1R-4/7. |
| N1-16 | PARTIAL | §2.3/§6: eligibility follows the master and extension identity propagates, but approval uniqueness still conflates independent scopes; N1R-3. |
| N1-17 | PARTIAL | §9: creation inserts and deferred work are distinguished correctly; the provider-advisory claim is false and Comfy transactions remain unaudited; N1R-8. |
| N1-18 | PARTIAL | §10: the requested cases are substantially added; diagnostic equality is impossible as specified, and A1’s production-boundary test lacks its boundary; N1R-11/12. |

**N1R-1 — BLOCKING — Revised view still cannot compile.**  
`N:332`, `N:349`, `N:400`: `repl` references itself without `WITH RECURSIVE`. The episode-cancellation UNION branch returns eight columns; the other branches return nine because `extension_id` was omitted.  
**Replace:** “Use `WITH RECURSIVE v3_jobs AS (...)`. The episode-cancellation branch begins `SELECT e.season_id, et.episode_id, NULL::uuid, t.track, ...`, preserving the same nine-column order throughout.”

**N1R-2 — BLOCKING — The V1 schema pin does not preserve bytes.**  
`N:447`: the proposed `Field(json_schema_extra=...)` adds an inline `enum` while leaving `$defs.GateType` expanded to six values. The in-memory probe confirmed both differences from the committed schema.  
**Replace:** “Provide an explicit V1 schema adapter preserving the original two-value `$defs.GateType` and original field `$ref` exactly; retain the runtime membership guard. Extend V3 generation **and validation** manifest discovery. Keep new V1 rejection probes outside frozen generated examples.”

**N1R-3 — BLOCKING — Extension approvals collide with prior season approvals.**  
`N:50`, `N:482`, `N:552`: independent extension revisions are recorded against the same season entity, while the retained unique index keys only `(gate_type, entity_id, expected_revision)` (`microdrama/migrations/0002_story_and_approvals.sql:208`). An extension repeating a gate at a previously used revision conflicts with preserved history.  
**Replace:** “Persist immutable activation and extension identity on V3 approval rows and validate their scope linkage. Preserve legacy uniqueness for V1; define V3 uniqueness by full scope/revision and one decision per activation. Allocate the supporting DDL explicitly.”

**N1R-4 — SHOULD-FIX — Commands cannot identify a superseded activation.**  
`N:476`, `N:552`, `N:570`: commands contain no `activation_id`. Superseding and reopening unchanged content without a revision bump lets an old page match the replacement activation, contrary to A-T2’s superseded-activation refusal.  
**Replace:** “Include `activation_id` in `V3DecisionCommand`, displayed forms and command hashing. Resolve that exact activation and require it to remain open and match the complete scope before the three-way comparison.”

**N1R-5 — SHOULD-FIX — Work-scope identity is still mutable and incompletely plumbed.**  
`N:280`, `N:289`: neither the new trigger nor existing `jobs_identity_immutable` protects `season_id` or `episode_id`. The plan also omits `Job`/`_job` hydration and enqueue replay comparison; current replay checks only job type and input hash (`S/core/jobs.py:429`).  
**Replace:** “For V3 jobs, guard season/episode scope against mutation; add all work-scope fields to `Job` and `_job`; and compare the complete work scope on semantic-key replay. Validate the resolved season’s workflow version rather than treating `track` alone as its discriminator.”

**N1R-6 — SHOULD-FIX — Optional operation job context prevents dismissal matching.**  
`N:309`, `N:318`, `N:377`, `N:413`: an operation dismissal may store its job ID, but the projected operation row always has NULL `job_id`. The join then misses it; the unique index also permits duplicate operation dismissals with different context.  
**Replace:** “Canonical operation dismissals always store NULL `subject_job_id`; derive job display context through `provider_operations`. Enforce that representation in the CHECK, unique identity and writer.”

**N1R-7 — SHOULD-FIX — Gate 2 Reject has contradictory feedback requirements.**  
`N:490`, `N:579`, `N:588`: the validator forbids feedback outside Revise, but Reject says feedback is required. A-T4 cannot satisfy both. Existing V1 Reject uses `reason` (`S/review/service.py:1364`).  
**Replace:** “Reject carries empty timecoded feedback and records its explanation in `reason`; only Revise requires feedback or revision notes. Preserve the listed Reject state consequences.”

**N1R-8 — SHOULD-FIX — GPU transaction ownership and the lock audit remain incomplete.**  
`N:649`, `N:651`, `N:685`, `N:693`: “already-held scope lock” does not identify its owning transaction across separately committed operations. Comfy’s actual begin/dispatch boundary is `S/rendering/comfy_jobs.py:600`; its provider-operation advisory locks exist at `S/core/provider_ops.py:121`, contradicting §9.  
**Replace:** “Specify the owning transaction, lock mode and ancestor-before-leaf order at every final admission mutation, including reservation/lease insertion, `begin`, dispatch and transfer. Audit the actual reservation/advisory ordering and commit boundaries. Add season-gate-versus-episode-admission coverage alongside same-scope races.”

**N1R-9 — SHOULD-FIX — Requiring shutdown proof on every historical lease permanently blocks valid waits.**  
`N:648`: transferred-away leases intentionally lack their own `terminate_verified_at`; the final holder owns termination (`S/rendering/leases.py:1376`). Even after that pod shuts down, the proposed “every prior lease” predicate cannot pass.  
**Replace:** “Require zero live exposure and verified resolution of any potentially created pod, following transfer ownership chains to their final holder. Distinguish transferred history and durably proven no-create outcomes from unverified shutdown. Test transfer followed by verified stop and gate opening.”

**N1R-10 — SHOULD-FIX — Point reads need explicit workflow refusal.**  
`N:629`, `N:630`: candidate filters fit listings, but direct `season_view`, `episode_review`, `episode_page` and progress calls do not necessarily enumerate candidates. A caller filter leaves direct callers unguarded; filtering their query instead yields NotFound rather than the specified `WORKFLOW_MISMATCH`.  
**Replace:** “Apply listing filters only to enumeration. After owner access, call `require_workflow(..., expected='v1')` at every direct legacy read/decidability boundary, before projection or package interpretation.”

**N1R-11 — SHOULD-FIX — The upgrade test demands diagnostics the DDL changes.**  
`N:75`, `N:82`, `N:714`: custom trigger messages cannot equal the former CHECK messages, and the raises omit constraint names. Those fields are exposed by `S/persistence/db.py:77`.  
**Replace:** “Define the preserved V1 diagnostic contract explicitly. Where exact compatibility is required, emit the original SQLSTATE, constraint name and primary message; compare those stable fields in the upgrade matrix. Do not assert old messages against the current custom raises.”

**N1R-12 — SHOULD-FIX — A1’s production-injection test depends on an A6 boundary.**  
`N:544`, `N:709`: `build_production_world` is deferred to A6 and does not exist in current code. Registry registration alone does not reject a test-enabled registry supplied to normal composition.  
**Replace:** “Ship an A1 normal-composition registry validation boundary that rejects test-enabled registries and intrinsically test handlers. Exercise actual injection through that boundary in A-T2; A6 must reuse it.”

**Build readiness: no.** The decision revision plan and immutable activation lifecycle are sufficiently settled. DDL, decision identity, GPU transaction ownership, direct-read guards and acceptance expectations still require specification corrections. The command table also needs its promised per-command writes/jobs/events made explicit. These are material gaps for the orchestrator’s final decision.