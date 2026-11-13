# Phase C Codex critique round 1 — GLM rulings (13 Nov 2026)

Input: `codex-phase-c-critique.md` (verdict REWORK; PC-1..7 BLOCKING, PC-8..16 SHOULD-FIX) against
`phase-C-spec.md` v0.2. Every ruling is a **GLM ruling, Opus re-check Mon**. The former Blockers are
partially resolved and the package/test placement is improved; the remaining 16 findings are technical
conformance fixes with replacement wording. **All ACCEPTED**; no operator decision taken (O-C1/O-C9
stay open; C8 placeholder sufficient — Codex agrees); no acceptance row weakened (PC-16 re-gates and
extends).

| ID | Ruling (one line) |
|---|---|
| PC-1 | ACCEPT — common idempotent entry helper runs after setup approval **and** after STORY LOCK; once both authorities exist it derives items + forecast, advances the scope to CASTING, enqueues each root's three jobs exactly once; votes never invoke it. |
| PC-2 | ACCEPT — CD2 grows: V3 reference-kind, lock-body and lock-view typed contracts + workflow-aware readers/builders; V1/V2 schemas/validation unchanged; C-T1 exercises every new kind and a V3 lock with NULL source/package through the real typed paths. |
| PC-3 | ACCEPT — each candidate immutably records parent reference/version + invalidation generation; freshness evaluated per selected candidate; parent reroll invalidates descendants without enqueueing; a fresh unselected candidate cannot freshen an older selection. |
| PC-4 | ACCEPT — voice uploads bind immutably to the audition vote + stable catalogue identity; Approve requires the registered clip matching the current audition; voice hash members = (speaker demand, catalogue identity, audition vote, registered reference-version ID, content hash, normalised hash) with canonical ordering; stable provider reference defined for operator entries without speaker_id (`voices.provider_voice_ref` NOT NULL). |
| PC-5 | ACCEPT — the activation binds complete proposed cast membership, exact registered clips, wardrobe-plan record/version/hash and reviewed inspection records; the sealed CAST contract includes the wardrobe binding + provenance-basis refs; mutating any bound input supersedes and reopens. |
| PC-6 | ACCEPT — transaction-owned adoption helper (creator's `tx`, invoked before the episode-creation commit, under A's lock order); resolves the applicable **effectively approved** lock; public V1 wrapper + typed missing-lock error preserved; initial stamping at CAST LOCK stands. |
| PC-7 | ACCEPT — batch limits stop new submissions, never release protection around unfinished work; worker death / ambiguous submission → shared recovery admission blocks new dispatch until reconciled; canonical inode not replaced while generators may run; mount topology must expose replacement; C-T6 exercises accepted-but-unfinished work across holder death on the real mount. |
| PC-8 | ACCEPT — CD4 extends typed reason, jobs CHECK, wait-view CASE **and** the wait-view IN filter; C-T5 asserts the row through the production wait reader. |
| PC-9 | ACCEPT — per-kind dispatch policy (image reroll → image candidate; library reroll → its media job; voice replacement → intake); initial library jobs explicitly scheduled; generate-next = 3 outfit candidates + specified derived-view counts; forecasts use the same counts. |
| PC-10 | ACCEPT — the C5 note defines transition vs temporary-interval semantics, terminal-state carry, explicit-reset rules, simultaneous-state composition/precedence, incompatible-combination rejection; C-T8 verifies through the V3 resolver. |
| PC-11 | ACCEPT — audition, intake registration, CAST approval, import and dispatch each validate the **selected voice's own** rights record; community voices need per-voice evidence (general O-11 attestation insufficient); Botnoi-owned keeps OPERATOR_ATTESTED + WORLDWIDE. |
| PC-12 | ACCEPT — the catalogue refresh's scope model registered explicitly (global-maintenance exception with its own replay identity **or** season-scoped request); fence + consumed snapshot stated; shortlist tie-break finishes with unique catalogue identity + explicit NULL ordering. |
| PC-13 | ACCEPT — cast-consistency and forbidden-likeness recorded separately; every candidate gets the forbidden-likeness assessment (recorded human check absent a qualified detector); empty selected set never PASS. |
| PC-14 | ACCEPT — planning scope/extension identity carried through C commands, jobs, demand selection and STORY binding resolution; initial CAST LOCK stamps initial episodes, extension locking binds the extension's; earlier published bindings unchanged; other rebinding needs scoped amendment authority. No F UI implied. |
| PC-15 | ACCEPT — seed + immutable request inputs persisted once per `<pick, gen_seq>`; only new initial candidates and explicit rerolls allocate new sequences/seeds; transport retries/polling/reconciliation/restart retain them. |
| PC-16 | ACCEPT (strengthens) — C2 gates forecast data/panel behaviour, C9 gates the CAST condition; add the early-budget entry, typed-reader roundtrips, old-selected/new-unselected case, stale-review cases, insert rollback/concurrency, and in-flight crash cases to the relevant package gates. |

**Apply:** fold all 16 into **phase-C-spec.md v0.3** (job `dramabox:c-spec-v03`, docs only, queued
behind f-spec-v02 and a2-note-rev1). Round-2 critique follows v0.3 (the last C round this weekend).
