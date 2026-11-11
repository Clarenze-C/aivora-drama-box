**Verdict: REWORK.** The note has build-breaking SQL, a Gate 2 feedback regression, incomplete isolation, and an unclosed GPU admission race.

Reviewed read-only against Phase A v0.3, master v0.4.4, A0 v0.4 and the binding critiques, applying §12’s rulings. Branch: `feat/microdrama-m0-m4`, HEAD `39e5319`. No files or databases changed; no database tests run.

References: **N** = [A1-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md); **S/** = `microdrama/src/microdrama/`; **X/** = `microdrama/tests/`.

The intended V1 branch reproduces the five dropped 0002 predicates, and retaining the 0007–0021 guards is appropriate. That does **not** establish executable DDL, unchanged V1 contracts, or correct V3 Gate 2 behavior.

**N1-1 — BLOCKING — The literal SQL will not compile.**  
`N:64` declares two parameters named `p_entity`, with different types. `N:286` exports `j.id AS job_id`, but `N:304–323` repeatedly references nonexistent `j.id`, `f.id` and `r.id` from that CTE.  
**Replace:** “Use `p_entity_type text, p_entity_id uuid` throughout the resolver. Reference `job_id` consistently in every `v3_jobs` consumer. Install the deferred notes trigger in 0030 after its referenced table exists, so an intermediate 0029 deployment remains writable.”

**N1-2 — BLOCKING — V3 Gate 2 Revise loses its required timecoded feedback.**  
`N:96–100` forbids nonempty feedback for **every** V3 Revise. `N:393–405,463` also supplies only season notes and always records empty feedback. This contradicts Phase A §2.3 and the claim at `N:125` that Gate 2 rules are identical. OQ-6 does not waive this requirement.  
**Replace:** “Branch feedback validation by gate: `EPISODE_FINAL` retains timecoded feedback and its existing persistence; V3 season-gate Revise requires empty feedback plus matching season revision notes. Preserve all Gate 2 package/media/policy/scope/caption/manifest guards. Command availability remains deferred until F.”

**N1-3 — BLOCKING — Generated V1 byte-equality cannot hold with the proposed contract changes.**  
`N:367–409`; `S/contracts/season.py:272,290`; `S/contracts/build.py:41,103,139`. Expanding shared `GateType` changes `ApprovalCommand.schema.json`; its unchanged validator indexes the two-key `GATE_ACTIONS` and raises `KeyError` for new gates. The generator also classifies `.contracts.v3` models as V1 and processes only V1/V2 manifests.  
**Replace:** “Define explicit V3 schema/example registration and generation. Preserve the original V1 gate schema and typed rejection behavior despite the expanded internal enum. Freeze existing V1 artifacts against the accepted prerequisite baseline.”  
An in-memory probe confirmed all three problems.

**N1-4 — BLOCKING — `alert_dismissals` lacks the required catalog guards.**  
`N:254–276` attaches UPDATE/DELETE protection only. The five-table loop at `N:234` excludes this sixth table. `X/integration/persistence/test_schema_catalog.py:57,65` will reject missing TRUNCATE and integer-number guards.  
**Replace:** “Attach statement-level TRUNCATE refusal and INSERT/UPDATE integer-number guards to `alert_dismissals`; retain its append-only trigger. Verify all six new tables through the live catalog.”

**N1-5 — BLOCKING — Superseding an undecided gate violates the proposed CHECK.**  
`N:202,478`: `supersede_gate` sets `closed_at`, but the CHECK requires `closed_by_approval_event`; superseding an undecided activation has no approval. Moreover, lifecycle fields can currently be cleared or rebound, despite Phase A §2.5 calling activations append-only.  
**Replace:** “Keep activation records immutable and append decision/supersession facts, deriving openness from them. Alternatively, explicitly amend the spec to permit guarded, set-once lifecycle fields. Supersession requires no fabricated approval; closure and supersession cannot be undone or rebound.”

**N1-6 — BLOCKING — The resolver does not fully bind the decision to its activation.**  
`N:428–433,458–463` compares the command with recomputed content/current tracks, without explicitly comparing those values with the activation’s stored hash, content revision and decision revision. Independent season/episode FKs also do not prove that an episode belongs to the named season. Workflow validation precedes ownership, potentially producing different errors for foreign scopes.  
**Replace:** “Resolve owner access before exposing workflow/state errors; prove episode/extension ancestry. Under the scope locks, require the activation’s scope, stored binding and revisions to match current authority, then compare the command. Changed authority requires a fresh activation.”

**N1-7 — BLOCKING — Revision advancement conflicts with gate-edge advancement.**  
`N:463` closes the activation and bumps revision **before** the callback. `N:471,476,480` then requires an approval recorded at the current revision. An event recorded at revision *r* cannot satisfy that check after the recorder advances to *r+1*. Both recorder and transition commands also claim revision bumps.  
**Replace:** “Define one transaction-owned revision plan: validate at revision r, record approval at r, apply authorized handler transitions using that decision context, then advance the decision revision exactly once. Do not revalidate the event against r+1 or independently bump it twice.”

**N1-8 — BLOCKING — GPU safety has no common-lock admission protocol.**  
`N:535–560` locks tracks during activation but specifies only predicate checks elsewhere. `S/rendering/leases.py:671` reserves and inserts in separate transactions; `_insert_claim:789`, `ensure_pod:876` and transfer’s final transaction at `:1361` need concrete serialization points. A plain check before these transactions races gate activation. Picks and season/extension-owned GPU work remain unspecified.  
The heartbeat claim is also inaccurate: `S/rendering/leases.py:1031–1039` checks human wait only for a **non-ACTIVE** lease; ACTIVE heartbeats continue.  
**Replace:** “Use common scope locks for activation and every lease insertion/admission/adoption/transfer mutation, acquired before lease/job/budget locks. Refuse ACTIVE V3 heartbeats during waits. Name pod acquisition/reactivation and actual Comfy dispatch/adoption attachment points. Require verified shutdown before exposing a gate/pick wait; define later season-work ownership.”

**N1-9 — BLOCKING — Work-scope plumbing and current-authority derivation are incomplete.**  
`N:239–248,285–323,346`: the view ignores extension fences, compares replacements globally by `logical_work_id`, and allows a stale successful replacement to clear a current failure. Its reader has no `extension_id` argument. Existing `JobService.enqueue` (`S/core/jobs.py:353,389`) neither accepts nor persists the new fields, and may persist an episode job without `season_id`, which this view silently excludes.  
**Replace:** “Allocate typed enqueue/Job/work-scope changes explicitly. Require consistent V3 scope, track and logical-work identity; resolve episode ancestry and protect scope identity. Use the extension’s fence for extension jobs. Match successful replacements within the same scope, track and applicable authority, using validated replacement links. Add extension identity to the reader.”

**N1-10 — BLOCKING — §12’s quota mapping is not implemented, and a view has no such CHECK.**  
`N:302–303` recognizes `QUOTA`, while ruling `N:607` names `QUOTA_5H`, `PACE_WEEK`, `QUOTA_UNREADABLE` and `CONCURRENCY`; all currently fall through to provider waits. An ordinary view cannot enforce the promised read-time CHECK; PostgreSQL’s `CHECK OPTION` concerns writes through eligible updatable views. [PostgreSQL 16 documentation](https://www.postgresql.org/docs/16/sql-createview.html).  
**Replace:** “Map every agreed enum value explicitly. Enforce the closed persisted vocabulary at the owning table/write boundary, with a defined policy for ordinary retries and NULL. Unknown values cannot silently become provider waits. Coordinate this with A0 without editing applied migrations.”

**N1-11 — BLOCKING — Operation alerts cannot be dismissed under the proposed subject constraint.**  
`N:269,311,342–343`: operation wait rows contain **both** job and operation IDs, while the CHECK permits exactly one. OQ-4’s allowance for neither does not solve that case. Dismissal identity also omits extensions.  
**Replace:** “Choose one consistent subject representation: operation alerts use operation identity with optional validated job context; job alerts use job identity; scope alerts use neither. Match projection and dismissal keys exactly, including extension scope. Dismissal changes visibility only.”

**N1-12 — SHOULD-FIX — `NOT_AVAILABLE` is not literally before any write.**  
`N:456–459`; `S/core/idempotency.py:90–96`: `execute` inserts an idempotency record before invoking the action that checks availability. An exception rolls it back, but the claimed ordering remains false.  
**Replace:** “After replay lookup, check availability before the first INSERT/UPDATE, through an explicit transaction-owned preflight seam. Preserve replay-before-fresh-validation and atomic response storage. Test unavailable commands for idempotency writes as well as approval/job/event writes.”

**N1-13 — SHOULD-FIX — Production exclusion relies on the caller correctly labeling a test handler.**  
`N:446–452,583`: `register(test_handler)` defaults to `test_only=False`; testing rejection of `register(test_only=True)` proves only the flag path. Production composition is deferred to A6.  
**Replace:** “Give test handlers intrinsic provenance or a test-world registration capability. Production rejects test handlers and test-enabled registries regardless of the caller’s flag. Test attempted injection of the actual test handler/registry at the production boundary.”

**N1-14 — BLOCKING — The legacy inventory is incomplete.**  
`N:488–521`. The listed research/story claim/persist sites and scheduler selectors generally match the source. The critique checklist additionally requires these missing boundaries:

| Missing boundary | Actual source |
|---|---|
| Direct approval recorder and legacy state/approval authority | `S/core/approvals.py:50`; `S/core/state_machine.py:93,153,233,322,395` |
| Review summaries, listings, season/episode views, page enablement and decidability | `S/review/service.py:330,348,363,547,582,621,1228`; corresponding JSON/HTML routes and templates |
| Progress and V1 listing selection | `S/review/service.py:710,717`; `S/review/progress.py:527,580`; V1 callers of `S/review/scope.py:136` |
| Metadata preparation and package decision writers | `S/review/service.py:731,955,992,1014`; `S/review/packages.py:62,97,309` |
| Identity authority, review marking and attachment | `S/references/identity_lock.py:82,275,309`; `S/references/service.py:212,240,266,285,310` |
| Approved publication metadata and independent post recovery/mutations | `S/publishing/metadata.py:173` (`approved_live_binding`, the current equivalent of the critique’s older name); `S/publishing/service.py:793,947,1045,1060` |
| Membership approval authority | `S/memberships/catalog.py:397,413`, covering its public mutation paths |
| Repair paths bypassing the listed methods | `S/qa/repairs.py:444,1149`; `S/editing/service.py:226`; story recovery at `S/story/service.py:911` |
| Fixture/mock assumptions and direct episode creation | `S/pipeline/runner.py:290` and its V1-only workflow contract |

**Replace:** “Carry every checklist boundary explicitly. Guard direct callers as well as routed jobs; filter V1 listings at their callers while preserving shared owner-access helpers. Until versioned adapters exist, unsupported V3 execution refuses before effects. A4’s future effective-approval reader does not substitute for A1 isolation.”

**N1-15 — SHOULD-FIX — The command table remains incomplete.**  
`N:473–486`: production/release transition commands are absent; Reject describes only CAST_LOCK/LAUNCH; extension advancement cites `season_tracks.revision` instead of the extension revision. Activation replay identity `(gate,scope,hash)` also conflicts with allowing another decision through a fresh activation over unchanged content.  
**Replace:** “List every track’s command family, exact edges, revision owner and activation phase, including unavailable production/release edges. Specify every gate’s Reject result. Use activation/decision identity so retries replay while a deliberate new activation can reuse unchanged content.”  
A2 creation and A3 cancellation allocation are correct. CAST_LOCK/LAUNCH Reject destinations match AR-3.

**N1-16 — SHOULD-FIX — Extension eligibility contradicts the master.**  
`N:484`: `STORY_LOCKED+` is insufficient. Master §4.3 permits extension from release `RELEASING` or `COMPLETE`, with a continued/resumed calendar. Gate activations, decision commands and bindings also lack extension identity.  
**Replace:** “Keep B activation per OQ-1, but enforce the master’s eligibility. Carry extension identity through planning commands, activations, decisions, bindings, waits and dismissals, preserving prior season authority.”

**N1-17 — SHOULD-FIX — The lock audit cannot claim that A1 introduces no inversion.**  
`N:559–572`: the creation row literally lists `2 → 4 → 3`; GPU transactions touched by A1 are omitted. Worker job→track is a prospective A3 conflict once track locking is added; child→parent settlement belongs to A2. Cadence’s missing season lock is a pre-existing V1 serialization gap, not itself a demonstrated inversion.  
**Replace:** “Audit every touched GPU/activation/decision transaction, including provider advisory locks and transfer admission. Correct or justify new-row insertion exceptions explicitly. Keep worker fencing with A3 and hierarchy settlement with A2; record cadence separately. Add competing tests for A1’s own races.”

**N1-18 — SHOULD-FIX — The test plan needs additional discriminating cases.**  
`N:582–588` names the right acceptance IDs and a populated-V1 upgrade, but does not prove the defects above absent. Four negative V1 inserts do not establish every old rule, and custom trigger exceptions cannot simply be assumed byte-identical to CHECK diagnostics.  
**Replace:** “Add the complete V1 acceptance/rejection matrix and retained approval-guard cases; frozen V1 schema/example bytes; direct new-gate rejection without `KeyError`; activation supersession/reopening/binding tests; extension and stale-replacement isolation; operation dismissals; every quota reason; unavailable-command write tracing; real test-handler injection; and two-connection activation-versus-claim/adoption/transfer tests. Assert callback rollback includes enqueued jobs and idempotency state. Upgrade a populated accepted-0027 database, comparing existing rows and migration checksums. Retain `make check` and V1 `make pilot` at acceptance.”

