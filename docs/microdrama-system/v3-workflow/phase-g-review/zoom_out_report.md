# Stage 5 — Initial Zoom Out Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md` (full file, lines 1-556)
**Reviewer:** `egm-zoom-out` (fresh instance) · Standard: `zoom-out-standard.md`
**Status:** completed — 0 Blocker / 2 Major / 6 Nit
**Run:** headless uninterrupted (Preset 1), 14 Nov 2026

## Verification summary

**Altitude verdict: PASS at zoom-out altitude.** The document clears the prerequisite check (objective and motivation explicit in §0 and the header), solves the root problem (qualification and proof of an already-built system, not new pipeline machinery), and is unusually disciplined about simplicity: exactly one migration (G-1) mirroring the accepted F-1 store pattern; no new queue lane, job type, DeferReason, GateType or state machine (decision 1); no second quota table (decision 2, with a §16 rejection rationale); throughput reads F-6 and adds nothing (decision 11); AT-34 is explicitly bounded against duplicating F-T8/AT-29; the pilot reuses the composition factory, the drill's fresh-project pattern and the T031-R5 authorization discipline. Code searches for reuse candidates found nothing G reinvents: no pilot profile exists under `microdrama/deployment/` (only staging + canary-image), no `PILOT-REPORT.md` exists anywhere in the repo, and the FM's gap list is consistent with what was verified on disk. The obligation set (SPEC-v3.md:884 and :936 — AT-14/17/32/34, AT-28 live half, LIVE §16.3, R-11.1/R-12.10/R-12.11/R-12.13) is fully traced by §13, and every R/AT claim checked against the master resolved correctly. The risks in §15 are the right risks (money, external adoption lag, quota exhaustion, drill brittleness, CPU contention, profile drift). The two Majors are "does the whole hold together" seams inside G's only new runtime behavior (the AT-14 pause/alert) and the AT-32 proof economics — both fixable with a few architectural sentences, neither requiring redesign.

**Files checked against the tree (all absolute paths):**

- Target: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md` (full read)
- Factmap: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/g-factmap.md` — all FM §1–§7 claims used by the target
- Master: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md` — §1 rules (V3C-1 :90-94, rule 5 :101-102), §2.1-2.2 (:126-155), §3.1-3.3 (:161-210), §9.4 (:616-624), §10.0-§10.6 (:630-736), §11 (:740-773), §12.3 (:799-812), §15.1-15.2 (:873-938, incl. :884 G tests and :936 G R-IDs), §16.1-16.3 (:944-970), §17-§19 (:973-1033, incl. N36 :436/:868)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/REQUIREMENTS.md` — :24-27 (R-12.13 preamble), :169 (R-11.1), :189-190 (R-12.10/R-12.11)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/DECISIONS.md` — Dramabox Bot rows 11 Nov (token pasted in chat, rotate before go-live), T031 $8 envelope 12 Nov, O-11 attestation, S05/S06
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` — §3.1 (:76), §3.4 (:139-150 admission table), §4.2 (:208), §5.1 (:288), §5.5.6 (:380), §5.7 (:408-413), §5.8 (:419-421), §7 (:441, :472)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A-spec.md` — §2.7 (:105-111), §8.3-8.4 (:367-387), §9.1.2/9.1.4 (:402-411), §9.2.4/9.2.6 (:427-432)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md` — §2.4 (:432-465), §5/§13.1 (:905), §6
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` — header/status, :110/:158 (20-30 band), §5.1 (:378-379), §7.2 (:579-591), :213 (migrations 0036; A-line 0027-0035)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md` — header (v0.4.1), §1.2/§1.6/§1.7 (:80-106), §5 (:347-414), §15 O-C1/O-C4 (:804, :813), §17 (:853)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-E-spec.md` — header/status, §1 (:101-112 ED5 pattern, no phase-D spec), §3 (:388-389 CPU quota rule)
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` — header/status, §1.4/§1.11 (:94-112, :158-162), §2 F-1/F-6 (:214-227), §6.3 (:527-538), §7.1 (:543-545), §7.3 (:675-685), §8.1, §9 (:899-920), §10, §12 (:974), trace (:1059)
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md` — §3 R5d (:204-246), R5f (:254-274), §4 (:276-283), §7 (:336-376)
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-benchmark-packet.md` — :117, :147-148
- Code: `/root/AIVORA/drama-box/microdrama/src/microdrama/scheduling/service.py` (:1-26, :57-59), `/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/providers.py` (:190-203), `/root/AIVORA/drama-box/microdrama/src/microdrama/core/events.py` (:1-14)
- Migrations: `/root/AIVORA/drama-box/microdrama/migrations/0008_m0_revalidation_hardening.sql` (:62-95), `/root/AIVORA/drama-box/microdrama/migrations/0017_schedule_state.sql` (:1-10), full migrations Glob (tail = `0025_t045_billing_finality.sql`)
- Deployment/evidence: `/root/AIVORA/drama-box/microdrama/deployment/staging/drill.sh` (:105-149), `/root/AIVORA/drama-box/microdrama/deployment/staging/DOMAIN-RUNBOOK.md` (:28-37), `/root/AIVORA/drama-box/microdrama/evidence/T046.md` (:1-15)
- Absence checks (Glob): no phase-D spec in v3-workflow; no `PILOT-REPORT.md` anywhere under `/root/AIVORA/drama-box`; no `deployment/pilot/` directory — all consistent with the target's claims.

**Claims marked UNVERIFIED** (accepted on secondary evidence, not independently opened):

- ARISA-side facts (canonical lock file `/root/AIVORA/arisa/studio/sfw/vertex-generation.lock`, `recovery.py` behavior, absence of ARISA recovery admission) — taken from g-factmap §5; outside the drama-box repo.
- Worktree-only code (`S/llm/step.py` deferral mapping, `M/0027 quota_observations`, `ai_route dramabox_llm` role) — via g-factmap §3; unmerged worktrees not opened.
- `WEEKEND-GLM-RUNBOOK.md` draft-queue order (C, F, E, G, D) — via g-factmap; file not opened.
- "B's scenario scripts" for A0's fake gateway (target §6, line 314) — not located; the role table in B §7.2 was verified instead.
- `A0-LIVE-REPORT.md` — referenced as a future prerequisite artifact; does not exist yet (consistent with its use).

## Prioritized Findings (Blockers → Major → Nits)

### S5-Z-1. AT-14 pause/alert machinery's durable state is architecturally unpinned - Severity: Major
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §4 / GD1 / GD2 (lines 158-165, 232-254) and G-T2 (line 483)
* **Discrepancy Description**: (a) The pause predicate is "derived, never stored" (line 234, invoking AR-4), but a rising-edge detector needs memory of the previous sample across ticks and restarts. The spec claims `scheduler_firings` "deduplicates the pause-edge evaluation across ticks and restarts" (line 161) — but `scheduler_firings(trigger, period_key)` uniqueness (phase-A-spec.md §9.1.2) dedupes one tick's effects, not an episode-level edge; for a 60 s interval schedule the period key is the tick bucket itself, and "one alert per pause episode" still requires a stored previous-edge reading whose home is unnamed. (b) The un-pause reader is unstated: while the route is paused "no new LLM dispatch admits" (lines 241-243), so the mechanism that re-reads quota and clears the pause must be either the deferred jobs' ~+10 min retries re-running A0 §5.7's dispatch/health gate, or the `g.quota_pause` tick probing gateway health (A0 §4.2 exposes live quota readability). (c) The predicate reads "the latest quota observation" (stored) while enforcement is the dispatch gate's live health check — two sources that can disagree.
* **Rationale & Recommendation**: This is G's only new runtime behavior and its first-owned acceptance test; the seams it needs (A0 §5.7, the scheduler registry, the event registry) all exist and are correctly chosen, so this is not over-engineering — it is one missing architectural sentence per sub-point. State in §4: where the edge sample lives (e.g., derived from the last emitted scope event identity), and that the un-pause reader is the A0 §5.7 gate re-evaluated on deferred retries. Details can stay in the G2 note.

### S5-Z-2. Restore-proof cadence/kind matrix is underdetermined - Severity: Major
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §3.3 (lines 204-210), §3.5 (lines 219-229), §5.1 (lines 260-267) and O-G2 (line 519)
* **Discrepancy Description**: §3.3 says every backup writes its `RestoreProofV3` point fields at creation and "the §5 proof completes the record"; §3.5 refuses activation without a PASS verdict within 7 days; but §5.1's procedure is defined on a *seeded unclean test-profile world*, while O-G2 says "proof per §5 on each timer window's set" — i.e., on production timer backups, where no unclean state can be injected (a live production backup naturally contains in-flight work, but that equivalence is never stated). Which procedure may complete a production backup's verdict, on which world, at what cadence, and in which composition is unstated — and it matters operationally: a nightly proof that resumes the sender in a fresh project must use the fake transport, or per §5.4's own at-least-once admission it can deliver real duplicate Telegram messages to the operator's chat.
* **Rationale & Recommendation**: As written, either production `RestoreProofV3` rows can never complete (activation always fails) or O-G2's nightly proof silently runs a procedure §5.1 defines only for the test profile. Recommend an explicit matrix: nightly timer = clean restore+resume control proof (G-T3's drained-world variant) in a fake-transport composition; the unclean-world proof runs in the test profile (or on live production sets, if that is the intent, with the natural-unclean-state argument made); activation accepts the freshest PASS of either kind within the window.

### S5-Z-3. FM §5 mis-pointed for restore facts (should be FM §1) - Severity: Nit
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** line 35 (§0) and line 107 (decision 8)
* **Discrepancy Description**: "no composed restore proves DB + objects resume without duplicate effects (FM §5)" and "(the T046 drill drains *before* backup, `drill.sh:110-113`; FM §5)" — both facts live in g-factmap.md §1 ("Backups / restore today", final paragraph "Restore gap vs AT-32"). FM §5 is the cross-system lock section (correctly used in §8, line 414).
* **Rationale & Recommendation**: Repoint both citations to FM §1.

### S5-Z-4. "pg_restore with ON_ERROR_STOP" mischaracterizes the drill - Severity: Nit
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §5.1 step 2 (lines 267-270)
* **Discrepancy Description**: `drill.sh:121-141` restores the plain-text dump with `psql -v ON_ERROR_STOP=1` (drill.sh:127), not `pg_restore`; the `pg_dump --format=custom` → `pg_restore` path belongs to `X/integration/persistence/test_migrations.py:252-281` (per FM §1).
* **Rationale & Recommendation**: Either cite `psql`, or declare the switch to custom-format dumps as a deliberate G3 change.

### S5-Z-5. Code-line drift in two inherited citations - Severity: Nit
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §5.2 (line 285) and §5.2/§5.1 (lines 272, 283-284)
* **Discrepancy Description**: The at-least-once/consumer-dedupe rule is at `S/core/events.py:8-10`, not `:5-7` (cite inherited from FM §1); the quoted scheduler sentence sits at `S/scheduling/service.py:21-22`, not `:18-21`. Substantively both claims are correct (verified against the files).
* **Rationale & Recommendation**: Re-point both when the G3 note is written.

### S5-Z-6. Migration-tail attribution is incomplete - Severity: Nit
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** line 18
* **Discrepancy Description**: "main ends at 0025; the A-line allocates 0027–0035, B from 0036 — FM §7 gap 13" — FM §7 gap 13 documents only main-ends-at-0025, A0-D=0027 and A1=0028–0031. The full allocation is established by phase-B-spec.md:213 ("B's migrations start at 0036 (A0=0027, A1=0028–0031, A2=0032–0034, A3=0035)"). Fact correct (independently verified: highest migration on this branch is `M/0025_t045_billing_finality.sql`); attribution incomplete.
* **Rationale & Recommendation**: Add the B-spec cite alongside FM §7 gap 13.

### S5-Z-7. P0's numbered order couples the pilot's opening step to the longest external pole - Severity: Nit
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** §7.2 (lines 354-360)
* **Discrepancy Description**: The calibration batch is item 1 with "prerequisite: C3 merged, ARISA-side adoption per master §10.2" — the dependency the spec itself flags as the long pole (O-G4, §15). Master §10.4 (SPEC-v3.md:717-718) requires the lock measurement only *before CAST generation starts*, and planning steps 1–3 are LLM-only (A0+B). §15's mitigation ("the pilot's image legs stay disabled until adoption") implies decoupling, but §7.2's ordering does not say planning may run ahead with O-C7 defaults as the interim forecast.
* **Rationale & Recommendation**: One sentence stating that planning steps 1–3 may run ahead using O-C7 defaults as the interim forecast keeps the pilot's critical path off the ARISA dependency.

### S5-Z-8. Acceptance-state asymmetry in the header - Severity: Nit
* **Reviewer Lens:** `egm-zoom-out`
* **Affected Scope:** header (lines 7-8)
* **Discrepancy Description**: "accepted B v0.6 / C v0.4.1 / E v0.4" — B's and C's own status lines still read "round-2 rulings applied (GLM); awaiting Opus re-check — no round 3 run" and E's reads "Opus re-check Mon", yet only F's pending re-check is flagged ("round-2 rulings applied, Opus re-check queued"). The family convention (phase-E-spec.md's header uses the same formula) makes this cosmetic, but a fresh reader could conclude B/C/E are frozen while only F is moving.
* **Rationale & Recommendation**: Flag E (and B/C if still pending) symmetrically with F.

## Strengths worth keeping (no action)

- **Decision 2** (records over schema; no second quota table) is the right YAGNI call and §16 argues it properly: image constraint is throughput, the rest is money or attestation — a `QuotaObservation` equivalent for non-LLM providers would model nothing that exists (confirmed: grep finds none outside the LLM gateway, FM §4).
- **Decision 8** (restore proof from an unclean world, not a drained one) targets the real crash window rather than a sanitized one; §5.3 justifies it correctly, and §5.4's honest at-least-once notification statement matches master §19.2's supersession exactly.
- **Decision 9 / §6** (AT-34 with real handlers, fake providers, evidence as a committed file not a DB row) is the minimal design that actually proves handler-registry completeness; the "what it proves that per-phase tests don't" paragraph (a)-(f) is a genuine scope bound, and producing exactly 5 episodes + teaser is the minimum that lets LAUNCH approve (F §1.5/O-7).
- **GD2's** jobless payload variant instead of a new event name respects master §3.3's binding vocabulary (verified: "quota wait" is in the §3.3 event list, SPEC-v3.md:209).
