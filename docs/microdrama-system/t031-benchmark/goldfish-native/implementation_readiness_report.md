# Implementation-readiness report — native Codex Stage9 round1

Target spec detailed99–399. Fresh contexts `/root/goldfish_implementation`,
`/root/goldfish_codebase`, `/root/goldfish_style_detail`; all completed.
**Changes required before offline implementation.** Hardware/paid proof is not
an offline prerequisite. Findings retain reviewers' original severities.

| ID | Lens/severity | Complete actionable finding |
|---|---|---|
| I1 | Implementation/Blocker | Define disjoint canonical per-reservation accrued/settled/remaining exposure projection, credit policy and worked examples. Name transaction-capable reserve API preserving every old guard; fix account/category/experiment/sample/acquisition lock order and atomic links. |
| I2 | Implementation/Major | Per-job leases do not serialize different samples or acquisitions. Add database-enforced experiment acquisition/dispatch slots; UNKNOWN create occupies its slot; samples reuse one acquisition; race ample-budget workers and pre-ID resumes. |
| I3 | Implementation/Major | Immutable plan with unresolved references cannot become executable. Separate logical prepare from one-time immutable seal; explicit UUID/hash replay/conflict and intentional-repeat key. |
| I4 | Implementation/Major | “Signed authorization” and refreshed quotes undefined. Choose existing operator-file/hash convention, freeze envelope schema separate from per-acquisition quotes, state expiry rules for resume/sweep and cleanup. |
| I5 | Implementation/Major | State lists do not define ownership/recovery. Add transition table with durable prerequisites/effects, preserve failed execution outcome separately from cleanup/billing closure, define conservative durable GPU-ms windows. |
| I6 | Implementation/Major | New graph/uploads have no concrete entry through submit_v2. Define binder/verifier, immutable role/upload receipts, request hash and benchmark-only profile resolution. |
| K1 | Codebase/Blocker | V2 ReferenceRole has no audio role; ShotReferenceBinding lacks explicit ordered speaker/port mapping; reference resolver sorts by role/subject; RenderRequest audio is singular. Propose additive voice role plus hashed ordered module map; define multiplicity. |
| K2 | Codebase/Blocker | Existing V2 binder/verifier assumes graph sampler and LoadImage asset/UUID locators; submit_v2 always invokes it; unregistered family fails. Define family dispatch for build and verify, preserving legacy behavior; new config/hash binds actual topology/uploads. |
| K3 | Codebase/Major | object_info discards input types/options and canonical ComfyNodeInfo cannot represent full schema. Add module-local raw schema retrieval/normalization and exact fields/hash; keep old interface unchanged. |
| K4 | Codebase/Major | Existing JSON-only _request cannot upload multipart. Define scoped binary method, deterministic acquisition/asset key, typed durable receipt, checksum/readback, UNKNOWN reconciliation and new-pod invalidation. |
| K5 | Codebase/Major | reserve owns transaction; reserve_attempt invokes it. Name reserve_in_transaction plus existing wrapper and full guard preservation, exact locks and caller reservation adoption, concrete SQL columns/unique constraints. |
| K6 | Codebase/Major | Canary/production resolvers require enabled/measured preset, incompatible with experimental unmeasured Thai route. Define allowlisted benchmark-only profile policy and shared guarded world assembly without enabling production or inventing measurements. |
| W1 | Style/Major | “Reserves one shared allowance” conflicts with no parent hold. State canonical per-effect reservations under a shared sub-limit. |
| W2 | Style/Major | Authorization rules ambiguous for resume/sweep; distinguish any new dispatch from cleanup-only work after expiry. |
| W3 | Style/Major | Sample allocations equality conflicts with unallocated overhead. Reconcile samples plus explicit overhead to canonical usage. |

## Read evidence and limits

Implementation reviewer read persona/standard, entire spec and packet; source
reserve290–500, canary authorization56–218, runner698–850, submit_v2499–590 and
scoped transport/jobs searches. Initial incorrect-path reads failed then corrected.

Codebase reviewer read persona/standard, spec1–399, routing/handoff. AST symbol
then scoped bodies: V2 roles/bindings, reference preflight, RenderRequest,
binder/verifier, submit_v2, templates/hash, transport/schema, graph validation,
reserve/reserve_attempt, preset/catalog/canary/production resolvers. Not every
lease/billing/janitor body, authorization implementation, migration or helper was
read. No Serena tool exposed; AST fallback used.

Style reviewer read persona and entire target; detailed200–399 numbered reread.
No linked docs/implementation/prior revisions inspected. No reviewer used memory,
changed files, ran tests, downloaded models or called providers.
