**Verdict: REWORK.**

Reviewed read-only on `feat/microdrama-m0-m4` at `1c62bb6`, against the specified requirements and master v0.4.6. Migration allocation and setup-inside-season arithmetic are correct. The enforcement and concurrency design needs the changes below. No PostgreSQL tests were run; the N2-1 helper was exercised with a controlled transaction stub.

**N2-1 — BLOCKING — Parent lookup happens before the mutex.**  
[A2-design-note.md:304](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:304)  
A setup mutation can read `parent_account_id=NULL`, wait behind STORY LOCK, then acquire the mutex and skip the now-existing parent. The stub reproduced this. Set-once identity does not make the initial NULL read stable. Checking only `planning_state=STORY_LOCKED` also misses later states.  
**Replacement:** “Read immutable season identity, acquire and verify the season mutex, then re-read attachment and lock the current parent before the child. Once hierarchy attachment has occurred, parent absence is an error in every later planning state. Return the locked parent for admission and mirroring.”

**N2-2 — BLOCKING — The replacement cap guard weakens V1 INSERT protection.**  
[A2-design-note.md:79](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:79)  
In a BEFORE INSERT trigger, the new account does not yet exist for `md_effective_cap(NEW.id)`. Its fallback SELECT returns NULL; the comparison becomes NULL and raises nothing. An overcommitted V1 account INSERT previously rejected by the CHECK can therefore pass.  
**Replacement:** “Make the effective-cap dependency available before enabling the trigger. For INSERT, derive the fallback from `NEW.cap_micro_usd`; never obtain it by selecting the not-yet-inserted account. Preserve the original committed-cap rejection on both INSERT and UPDATE.”

**N2-3 — BLOCKING — Amendment-trigger definitions are contradictory.**  
[A2-design-note.md:225](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:225)  
The note calls all three guards BEFORE INSERT triggers, then calls consistency a DEFERRABLE constraint trigger. PostgreSQL constraint triggers must be AFTER ROW. The category test also leaves unclear whether “current allocated + delta” describes the pre-change or final state.  
**Replacement:** “Provide exact DDL: BEFORE guards stamp and validate human authority; an AFTER ROW constraint trigger validates the amendment’s final transaction state. Explicitly apply category and step changes once, and validate final allocation totals without adding deltas twice.”

**N2-4 — BLOCKING — SQL amendment validation does not enforce the claimed money backstop.**  
[A2-design-note.md:234](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:234)  
The committed floor is Python-only. A direct INSERT carrying a valid session can change the effective cap without firing `budget_accounts_rules`. SQL-side hierarchy serialization and revision advancement are unspecified. Timestamp/UUID ordering also does not guarantee that the last serialized amendment wins.  
**Replacement:** “SQL amendment insertion takes the hierarchy locks, validates predecessor, revision, commitment floor and ancestor limits, and advances an account revision atomically. Enforce unique amendment lineage per account. Derive the effective cap from that serialized lineage; timestamps are audit metadata.”

**N2-5 — BLOCKING — The lock audit stops inside shared helpers.**  
[A2-design-note.md:575](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:575)  
The claim that there are only three advisory sites omits caller-owned billing transactions. [Billing ingestion](/root/AIVORA/drama-box/microdrama/src/microdrama/budget/billing.py:295) takes a bucket advisory lock, posts through the budget helper, then continues to another bucket. Adding the mutex produces `#6 → #7 → #6`. One ingester can hold the season mutex while waiting for a bucket lock held by another ingester waiting for that mutex.  
**Replacement:** “Audit complete outer transactions, including ingestion, invoice verification and podless-create resolution. Acquire all required billing/provider locks in a deterministic order before entering the budget chain. Define ordering across multiple seasons. Add a competing ingestion test reproducing this cycle.”

**N2-6 — BLOCKING — Cleanup can still be refused or fail during flush.**  
[A2-design-note.md:343](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:343)  
The step check has no cleanup exemption, category/spill checks remain unchanged, and reservation admission calls `move` then `flush` without recording overrun first. Consequently, the promised cleanup path can fail at a step/category check or the committed-cap trigger.  
**Replacement:** “For authorized V3 cleanup, define exemptions from exhausted step, category, child and aggregate limits. Record required child/parent overrun increments before flushing, allowing a NULL charge reference for reservation exposure. Preserve stop/terminate execution and truthful accounting even if reservation admission fails. Keep V1 behavior unchanged.”

**N2-7 — BLOCKING — Steps 5–9 lose independent budgets and attribution.**  
[A2-design-note.md:182](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:182)  
All production steps become `episode_production`; the SQL guard rejects `step_05`–`step_09` on EPISODE accounts. Unused capacity from one production step can therefore fund another without an amendment, and Costs cannot report their actual step identity.  
**Replacement:** “Persist actual master-step identity for steps 5–9 and enforce their approved caps. Define precisely how the additional `episode_production` envelope relates to those caps. Distinct step budgets cannot borrow from each other without approval.”

**N2-8 — BLOCKING — Step DDL and receipt contracts are incomplete.**  
[A2-design-note.md:153](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:153)  
`budget_steps.cap_micro_usd` can be updated without an amendment. Reservation `step_key` is absent from the immutable identity guard. No charge linkage guard is supplied, and the existing `UsageReceipt` has no field for the promised unreserved-receipt step. The shown step-table DDL also omits its DELETE guard.  
**Replacement:** “Guard step-cap changes through approved amendments; make reservation step identity immutable; validate charge/reservation step agreement. Add the unreserved-receipt step contract and update every posting path. Supply DELETE/TRUNCATE/integer guards explicitly and test them through direct SQL.”

**N2-9 — BLOCKING — Human authentication is not account-scope authorization.**  
[A2-design-note.md:453](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:453)  
A live session matching `actor_owner_id` does not prove ownership of the account’s season. Neither amendment authorization nor the new Costs route explicitly applies the existing `season_owners` access rule.  
**Replacement:** “Resolve account → season and require season access before exposing workflow, revision or financial details. Foreign scopes return NotFound. Bind amendment actor/session to the season owner in the SQL authority guard. Season creation writes its creator ownership link.”

**N2-10 — SHOULD-FIX — Command wrapping contradicts the caller-owned LOCK transaction.**  
[A2-design-note.md:547](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:547)  
“Every row” running through `IdempotencyService.execute` includes internal LOCK helpers; the existing service opens its own transaction. This conflicts with §4 and can introduce a nested transaction waiting on its caller. Events and replay results also remain placeholders.  
**Replacement:** “Only external human commands enter `execute`. `create_v3_episodes_in(tx, decision_context, …)` and budget attachment inherit the decision transaction and replay identity. Specify exact events, responses and mismatched replay behavior. Episode count must match the approved binding.”

**N2-11 — SHOULD-FIX — Effective-cap loading conflicts with the unchanged-reader claim.**  
[A2-design-note.md:245](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:245)  
The note requires a computed effective-cap field in `account_from_row`, but later leaves reports unchanged; their `SELECT *` queries provide no such alias. Also, `analytics/cost.py` is not inherently V1-only: its EPISODE queries match V3 accounts too.  
**Replacement:** “Inventory every `AccountRow` constructor/query and provide its effective-cap field consistently. Preserve V1 response semantics through explicit version guards. Audit analytics and qualification callers; account kind alone does not discriminate workflow version.”

**N2-12 — SHOULD-FIX — Forecast inputs overlap and pre-LOCK behavior is undefined.**  
[A2-design-note.md:492](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:492)  
`remaining` includes episodes already rendering/editing, whose holds and spend are already in `committed`; adding a full episode estimate counts covered work again. The Costs route is available before the SEASON account exists, but its forecast requires that account.  
**Replacement:** “Define non-overlapping committed and remaining work, including partial-production handling and the source/version of the plan estimate. Specify pre-LOCK forecast availability. Revalidate at the required CAST LOCK and rendering checkpoints after relevant budget or scope changes.”

**N2-13 — SHOULD-FIX — Subscription allocation and API-equivalent estimates remain mixed.**  
[A2-design-note.md:521](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:521)  
One `SUM(cost_estimate_microusd)` cannot represent both quantities. COALESCE also hides unavailable estimates as zero. Expired exposure moves to accrued, so the reserved-counter query does not itself include expired holds as claimed.  
**Replacement:** “Return separate subscription-allocation, estimate and quota fields. Define an allocation source/basis or report it unavailable. Preserve unknown estimate counts and quota uncertainty. Show expired exposure in its actual ledger bucket plus the unresolved-exposure listing. Provider totals must respect accrual-to-settlement replacement.”

**N2-14 — SHOULD-FIX — Admission can write before the aggregate check.**  
[A2-design-note.md:349](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:349)  
Keeping category/spill rules unchanged invokes `spill_from_recovery`, which inserts a `budget_transfers` row before the new season-cap refusal. Rollback prevents durable residue, but this does not satisfy the requested before-any-write ordering.  
**Replacement:** “Calculate category/spill feasibility without mutation, complete all admission checks, then apply transfers, reservation insertion and counter changes atomically.”

**N2-15 — SHOULD-FIX — Acceptance assertions need stronger and corrected race cases.**  
[A2-design-note.md:625](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md:625)  
There is no explicit reserve-versus-reserve boundary test. `committed ≤ effective + overrun` alone permits erroneous admission disguised as overrun. The expected parent block after every child overrun is also wrong when aggregate commitment remains within the season cap.  
**Replacement:** “Use independent PostgreSQL connections and controlled barriers for sibling and same-child admitters: only affordable admissions succeed, with no admission-created overrun. Add the stale-parent and outer-billing cycles above; deadlock/timeouts are failures. Test child-only and aggregate overruns separately, amendment rollback/replay, and all new direct-SQL guard negatives.”