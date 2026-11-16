**A2-design-note.md v1.1 complete — all 15 findings applied, none BLOCKED:**

- N2-1 applied — §3.2 rewritten mutex-first: immutable identity → mutex → attachment re-read under it → parent locked before child; attachment probed via the SEASON account's existence (state-machine-free); locked parent returned
- N2-2 applied — §2.1/§2.3: committed-cap guard never selects the not-yet-inserted account; 0032 uses `NEW.cap_micro_usd`, 0034 swaps in `md_row_effective_cap(NEW.id, NEW.cap_micro_usd)`; original rejection preserved on INSERT+UPDATE
- N2-3 applied — §2.3 exact DDL: two BEFORE INSERT guards (authority stamping) + AFTER ROW DEFERRABLE constraint trigger validating final transaction state; deltas validated once against post-application rows
- N2-4 applied — §2.3: `md_apply_cap_amendment()` takes hierarchy locks, validates predecessor/revision/floor/ancestor, advances `amendment_revision` atomically; `UNIQUE(account_id, account_revision)` + `UNIQUE(predecessor_id)` lineage; effective cap ordered by lineage, timestamps audit-only
- N2-5 applied — §8: full outer-transaction audit (ingestion `billing.py:208`, `verify_invoice_period` `:449`, `resolve_podless_create` `:786`); all bucket advisories pre-acquired in `bucket_identity_sha256` order; cross-season mutex ordering defined; competing-ingestion test added
- N2-6 applied — §3.3: authorized-V3-cleanup exemptions from exhausted step/category/child/aggregate checks; `pre_record_overrun` before flush with NULL charge ref (column already nullable, `M/0003:150`); stop/terminate + truthful accounting survive failed admission; V1 unchanged
- N2-7 applied — §2.2/§4: steps 5–9 keep real identities with own approved caps; `episode_production` = derived envelope, `Σ(step_05..step_09 caps) ≤ envelope cap`; no cross-step borrowing
- N2-8 applied — §2.2/§2.4: `budget_steps_cap_amendment_only` (xact-bound), reservation `step_key` immutable, `md_charge_step_rules` linkage guard, `UsageReceipt.step_key` contract, explicit no-delete/no-truncate/integer guards + direct-SQL tests
- N2-9 applied — §5/§6/§4: `require_season_access` + foreign-scope NotFound; season-owner binding in the SQL guard; `link_season_creator` in `create_v3_season`
- N2-10 applied — §7: only external human commands enter `execute`; `create_v3_episodes_in(tx, …)` inherits the decision transaction + replay identity; exact events/responses/mismatched-replay; count-vs-binding validation (§4 step 8)
- N2-11 applied — §2.3/§9: full `AccountRow` constructor/query inventory with consistent alias; explicit `workflow_version` guards for `analytics/cost.py` (kind ≠ version); qualification readers audited
- N2-12 applied — §6: non-overlapping committed/remaining with in-flight residuals; plan source/version pinned (`lock_base_cap` + binding hash); pre-LOCK setup-only view; live revalidation at CAST_LOCK + render dispatch
- N2-13 applied — §6: separate subscription (basis `unavailable`) / estimate (`unknown_estimate_count`, no COALESCE) / quota (`quota_unknown_count`) fields; expired exposure in accrued + unresolved listing; provider totals replacement-aware
- N2-14 applied — §3.3: category/spill feasibility computed pure; all checks before any write; transfer + insert + counters in one atomic tail
- N2-15 applied (strengthens) — §10: independent-connection barrier tests for sibling/same-child admitters (no admission-created overrun), stale-parent + competing-ingestion cycles, child-only vs aggregate overrun separated, amendment rollback/replay, all direct-SQL guard negatives; deadlock/timeout = failure

**Commit:** `b454832` on `feat/microdrama-m0-m4` (469 insertions, 157 deletions). **Line count:** 954. No BLOCKED findings; no report file written; no pushes/merges. Codex round 2 can follow the revision per the rulings' apply note.
