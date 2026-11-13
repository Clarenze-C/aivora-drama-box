**Verdict: REWORK.** Five findings are closed; nine remain partial; one regressed.

Reviewed v1.1 at `b454832` against the binding documents and current source on `feat/microdrama-m0-m4`. Read-only; no writes. Verification comprised source inspection and an in-memory exercise of the displayed hierarchy helper, **not PostgreSQL execution**. Migration allocation and setup-inside-season arithmetic remain settled.

References below use **A2** for [A2-design-note.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md).

| Finding | Status | Evidence / remaining issue |
|---|---|---|
| N2-1 | **PARTIAL** | §3.2, A2:487–499: attachment is re-read after the mutex, but SEASON accounts fail and mutex existence is unverified. N2R2-1. |
| N2-2 | **CLOSED** | §2.1/§2.3, A2:115–125, :312–325: INSERT fallback uses `NEW.cap_micro_usd`; migration dependency is ordered. |
| N2-3 | **PARTIAL** | §2.3, A2:347–365: AFTER ROW classification corrected; lineage and allocation validation remain contradictory/incomplete. N2R2-2. |
| N2-4 | **PARTIAL** | §2.3, A2:370–406: function serializes sanctioned calls; direct INSERT backstop does not enforce equivalent locks/revision advancement. N2R2-3. |
| N2-5 | **PARTIAL** | §8, A2:849–873: bucket pre-acquisition fixes one loop, but the complete outer transactions still violate the claimed order. N2R2-4. |
| N2-6 | **PARTIAL** | §3.3, A2:543–560, :596–609: exemptions and pre-flush overrun added; spill can still refuse cleanup. N2R2-5. |
| N2-7 | **CLOSED** | §2.2, A2:254–282: real steps 5–9 retained, separate caps enforced, envelope relationship stated. |
| N2-8 | **REGRESSED** | §2.2/§2.3, A2:179–180, :395–400: invalid TRUNCATE trigger added; step-cap guard accepts unapproved values. N2R2-6. |
| N2-9 | **PARTIAL** | §5/§6, A2:685–693, :777–782: new authorization specified; unchanged Costs endpoint remains a V3 bypass. N2R2-7. |
| N2-10 | **PARTIAL** | §7, A2:816–832: transaction inheritance/replay corrected; season-creation event/response still unspecified. N2R2-8. |
| N2-11 | **CLOSED** | §2.3/§9, A2:408–422, :912–921: constructor/query aliases and explicit analytics version guards addressed. |
| N2-12 | **PARTIAL** | §6, A2:746–769: residuals, provenance and pre-LOCK behavior added; DIRECTED episodes still double-count. N2R2-9. |
| N2-13 | **CLOSED** | §6, A2:788–797: allocation/estimate/quota separated, unknowns retained, expiry bucket and replacement semantics corrected. |
| N2-14 | **CLOSED** | §3.3, A2:543–566: pure feasibility precedes checks; transfer/reservation/counters follow atomically. |
| N2-15 | **PARTIAL** | §10, A2:930–937: coverage strengthened; barrier placement remains incompatible with serialization. N2R2-10. |

**N2R2-1 — BLOCKING — Hierarchy helper rejects the aggregate account.**  
§3.2, [A2:487](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:487). A SEASON account has no parent; the attachment probe finds that same account and raises `Conflict("budget hierarchy detached")`. §5 calls this helper for SEASON amendments, making the operator’s aggregate-cap remedy fail. The displayed helper reproduced this with a transaction stub. A missing mutex row also passes silently.

**Replacement:** “Fetch and verify the mutex row. Under it, re-read account kind and attachment. A SEASON account returns no parent; only pre-LOCK SEASON_SETUP may otherwise lack one. Attached children require their current parent. Use this protocol in SQL amendment paths too.”

**N2R2-2 — BLOCKING — Deferred consistency checks the wrong tip and cannot prove delta application.**  
§2.3, [A2:347](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:347). At deferred execution, the inserted amendment is already the current tip. Testing its predecessor against that tip, and its revision against `tip.revision + 1`, rejects valid inserts unless the queried lineage explicitly excludes it. Separately, final allocation **sum** cannot detect skipped or doubled zero-net category redistributions.

**Replacement:** “Validate the prior tip before insertion under locks. At deferred validation, verify the stored predecessor/revision relationship and the final account tip. Validate each category’s final allocation against its locked baseline plus approved delta. Specify whether multiple amendments to one account in one transaction are supported or refused.”

**N2R2-3 — BLOCKING — Direct amendment insertion remains outside serialization.**  
§2.3, [A2:370](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:370). Locks and `amendment_revision` advancement exist only in `md_apply_cap_amendment`. The listed INSERT triggers authenticate and validate final state; they do not require that function, acquire its hierarchy locks, or synchronize the account revision. Calling the function “sanctioned” does not enforce that boundary.

**Replacement:** “Every amendment INSERT must acquire the verified hierarchy chain, re-read attachment and prior tip, validate revision/floor/ancestor limits, and advance the account’s amendment revision atomically. Enforce this in INSERT triggers, or make direct table INSERT unavailable through an explicitly enforced function-only write boundary.”

**N2R2-4 — BLOCKING — The outer billing cycle is still present.**  
§8, [A2:849](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:849). Two omissions defeat the “all advisory locks before budget” claim:

- Reconciliation takes an allocation advisory per call at [budget/service.py:611](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/service.py:611); another allocation follows after earlier budget locks.
- Invoice verification loops at [budget/billing.py:666](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/billing.py:666), invoking ingestion separately at [:753](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/billing.py:753). Pre-acquiring each single-bucket call’s locks leaves the outer `#6 → #7 → #6` sequence intact.

An invoice transaction can hold the season mutex and request its next bucket while an ingester holds that bucket and waits for the mutex. Expiry’s account-order loop also contradicts the new all-season-mutex pre-acquisition rule.

**Replacement:** “Build the complete lock plan at the outermost transaction. Declare one ordered sequence for all seven advisory families, sorting keys within each family; acquire those locks and required evidence/provider/lease locks before budget entry. Then acquire every required season mutex by season_id. Inner helpers only reuse that plan. Apply this to invoice verification, ingestion and multi-season expiry.”

**N2R2-5 — BLOCKING — Cleanup still depends on available recovery allocation.**  
§3.3, [A2:543](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:543). Exempting the category refusal does not exempt spill feasibility. The atomic tail still applies a positive shortfall, while the preserved feasibility calculation refuses insufficient recovery headroom ([ledger.py:428](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/ledger.py:428)). With no recovery allocation, the transfer itself cannot succeed either.

**Replacement:** “Authorized V3 cleanup bypasses category/spill feasibility and performs no unfunded allocation transfer. Record its actual category counters and required child/parent overruns, setting blocked flags before flush. Restrict the ‘admission never creates overrun’ assertion to ordinary paid admission; cleanup is the documented exception.”

**N2R2-6 — BLOCKING — New step DDL is invalid; amendment matching is too weak.**  
§2.2, [A2:179](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:179) defines a TRUNCATE trigger `FOR EACH ROW`; TRUNCATE requires a statement trigger. At [A2:395](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:395), merely finding a same-transaction amendment naming the step permits updating its cap to a different, unapproved amount. The enumerated deferred checks supply no final step-value comparison.

**Replacement:** “Use `BEFORE TRUNCATE … FOR EACH STATEMENT`. Server-stamp amendment transaction identity. A step-cap update must match the approved value exactly, belong to the amendment’s permitted step scope, and pass final setup/production-envelope bounds. Direct SQL tests must reject a named step updated to the wrong value.”

**N2R2-7 — BLOCKING — The legacy Costs route exposes V3 accounts without ownership checks.**  
§6/§9, [A2:779](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:779). The supposedly untouched endpoint accepts a principal but discards it ([budget/api.py:24](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/api.py:24)); its reader resolves EPISODE accounts without workflow filtering. V3 accounts therefore remain readable through this route regardless of the new route’s `season_owners` check.

**Replacement:** “For V3 episode IDs, the legacy Costs endpoint requires episode-owner access or returns NotFound before financial reads. Preserve V1 behavior. On the new season route, require season access before exposing workflow mismatch or financial details. Test both endpoints with another season’s owner and service credentials.”

**N2R2-8 — SHOULD-FIX — Season-creation contracts still point to nonexistent detail.**  
§7, [A2:816](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:816) inherits “A1 §6’s season-creation event set,” but that table defines no event set or response. The internal LOCK transaction and count-binding portions are closed.

**Replacement:** “Define the creation response and event set explicitly here—for example, `{season_id, replayed}` and one `season.created {season_id, workflow_version}` event on first success, with none on replay—and register the chosen payload contract.”

**N2R2-9 — SHOULD-FIX — Production state does not establish zero commitment.**  
§6, [A2:748](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:748) labels DIRECTED episodes unstarted with no spend, although directing is episode-attributable spend under master §12.3. With 2M already committed and a 10M estimate, the formula produces 12M instead of 10M.

**Replacement:** “For every unfinished episode, add only `max(0, per_episode_estimate − committed_e)` to season commitment, including PLANNED/DIRECTED episodes. Add a full estimate only when that episode’s commitment is zero. Define unfinished membership explicitly.”

**N2R2-10 — SHOULD-FIX — Barrier instructions can deadlock a correct implementation.**  
§10, [A2:936](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:936) requires both contenders to read the same committed state. Those authoritative reads occur after the shared mutex; a rendezvous there prevents the first transaction from releasing the mutex needed by the second.

**Replacement:** “Place the start barrier before mutex acquisition. Pause A after acquiring the mutex; confirm B is blocked on that mutex, then let A commit and B re-read. Use 15 units of remaining capacity and two 10-unit requests: exactly one succeeds. Repeat with only the child limit binding. Add invoice-versus-ingestion and multi-season-expiry cases. Any raw or translated deadlock/timeout fails; ordinary admissions create no overrun, while authorized cleanup is tested separately.”