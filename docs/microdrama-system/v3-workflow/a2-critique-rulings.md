# A2 note critique round 1 — GLM rulings (13 Nov 2026)

Input: `codex-a2-note-critique.md` (verdict REWORK; N2-1..9 BLOCKING, N2-10..15 SHOULD-FIX) against
`A2-design-note.md`. Every ruling is a **GLM ruling, Opus re-check Mon**. Migration allocation and
setup-inside-season arithmetic were confirmed correct; all 15 findings are technical conformance fixes
with replacement wording. **All ACCEPTED**; no operator decision involved; no acceptance test weakened
(N2-15 strengthens).

| ID | Ruling (one line) |
|---|---|
| N2-1 | ACCEPT — mutex-first re-read: immutable season identity → season mutex → re-read attachment + lock parent before child; parent absence after attachment is an error in every later planning state; locked parent returned for admission/mirroring. |
| N2-2 | ACCEPT — INSERT fallback derives from `NEW.cap_micro_usd`, never selects the not-yet-inserted account; original committed-cap rejection preserved on INSERT and UPDATE. |
| N2-3 | ACCEPT — exact DDL: BEFORE guards stamp/validate human authority; AFTER ROW constraint trigger validates final transaction state; category/step deltas applied once. |
| N2-4 | ACCEPT — SQL amendment insert takes hierarchy locks, validates predecessor/revision/floor/ancestor limits, advances account revision atomically, unique lineage per account; timestamps audit-only. |
| N2-5 | ACCEPT — full outer-transaction lock audit (ingestion, invoice verification, podless-create); deterministic order for all billing/provider locks before the budget chain; cross-season ordering defined; competing-ingestion deadlock test added. |
| N2-6 | ACCEPT — authorized-V3-cleanup exemptions from exhausted step/category/child/aggregate checks; overrun increments recorded before flush (NULL charge ref allowed for reservation exposure); stop/terminate + truthful accounting preserved; V1 unchanged. |
| N2-7 | ACCEPT — steps 5–9 keep their real master-step identities and approved caps; the `episode_production` envelope's relation to those caps defined; no cross-step borrowing without amendment. |
| N2-8 | ACCEPT — step-cap changes only via amendment; reservation step identity immutable; charge/reservation step agreement validated; unreserved-receipt step contract added to `UsageReceipt` + every posting path; DELETE/TRUNCATE/integer guards supplied and tested via direct SQL. |
| N2-9 | ACCEPT — resolve account → season and require `season_owners` access before any workflow/revision/financial exposure; foreign scopes NotFound; amendment actor/session bound to season owner in the SQL guard; season creation writes the creator ownership link. |
| N2-10 | ACCEPT — only external human commands enter `IdempotencyService.execute`; internal LOCK helpers inherit the decision transaction + replay identity; exact events/responses/mismatched-replay specified; episode count must match the approved binding. |
| N2-11 | ACCEPT — inventory every `AccountRow` constructor/query for the effective-cap field; explicit version guards preserve V1 semantics; analytics/qualification callers audited (account kind ≠ workflow version). |
| N2-12 | ACCEPT — non-overlapping committed/remaining definitions incl. partial-production; plan-estimate source/version pinned; pre-LOCK forecast availability specified; revalidation at CAST LOCK + rendering checkpoints. |
| N2-13 | ACCEPT — separate subscription-allocation / estimate / quota fields; unknowns preserved (no COALESCE-to-zero); expired exposure shown in its real bucket + unresolved-exposure listing; accrual→settlement replacement respected. |
| N2-14 | ACCEPT — compute category/spill feasibility without mutation; all admission checks before any write; transfers + reservation + counters applied atomically. |
| N2-15 | ACCEPT (strengthens) — independent-connection barrier tests for sibling/same-child admitters (only affordable admissions succeed); stale-parent + outer-billing cycle cases; child-only vs aggregate overrun separately; amendment rollback/replay; all direct-SQL guard negatives. |

**Apply:** fold all 15 into `A2-design-note.md` **v1.1** (job `dramabox:a2-note-rev1`, docs only, queued
behind b-spec-v05 / f-spec-v02). Codex round 2 follows the revision.
