**File written: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A2-design-note.md`** (642 lines, 11 sections, no code, read-only elsewhere).

Summary:
1. **Migrations 0032–0034** (A1 owns 0028–0031): account kinds+hierarchy / mutex+`budget_steps`+`step_key` / `account_cap_amendments`+`md_effective_cap()`; applied bytes never edited (`migrate.py:51,:95`).
2. **DDL** shows every changed CHECK old-beside-new (scope kinds, per-kind cap bound, committed≤effective+overrun becomes a trigger; V1 predicates identical); `parent_account_id` set-once at LOCK; setup/season unique indexes.
3. **Lookup** replaces the `service.py:372-375` research fallback with explicit dispatch + `UNSUPPORTED_SCOPE` (fallback kept V1-only); receipts route version-aware.
4. **Admission order** unit price → step cap → child → SEASON aggregate as pseudo-code against the real `reserve()`; proof sketch why no level can be exceeded; truthful overrun via `check_overrun` (`ledger.py:443`) blocks child+season; V3 cleanup admits past an exhausted cap and records the overrun (V1 unchanged — OQ-7).
5. **AR-2**: `season_budget_mutex` serialises all pre-LOCK setup mutations and the LOCK attach; **AR-1**: SEASON base = count × per-episode base; setup counters *are* the initial season counters; arithmetic shown (10×$10=$100, $30 setup → $70 episode capacity).
6. **Setup approval = an amendment from base 0** (no paid setup before it); amendments are human-session-guarded, V3-only, consistency-guarded, serialised with admission, wake `RETRY_WAIT`/`BUDGET` jobs via `run_after=now()` (jobs locked #5 before budget #7).
7. **Forecasts** (CAST_LOCK condition + render admission) and a **`GET /v3/seasons/{id}/costs`** data API with one exact query per quantity; V3 attribution writes `cost_allocations` rows but never moves counters — setup counted once.
8. **Lock audit** covers every commitment path; the one real inversion found is `billing.py:1296` (child before parent) — fixed by `lock_budget_hierarchy` before entry, with two more sites fixed the same way (`service.py:811`, `:654`) and a competing-transaction test per fix.
9. **V1 unchanged** section maps every touched path to its no-op guarantee; **tests** A-T9/A-T10/A-T11 in three new files on real PostgreSQL, ≥2 connections, plus migration-upgrade and contract cases.
10. **Seven open questions** with recommendations (LOCK refusal when setup > count×base, step-key vocabulary, launch caps at 0, the $1,000 SEASON ceiling, wakeup scope, allocation-table reuse, the V1-vs-V3 cleanup divergence).

The note is ready for the pre-code Codex critique.
