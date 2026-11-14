# Stage 6 — Comprehension Report

**Target:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md` (FeatureRange lines 1-454, DetailedRange lines 455-556)
**Reviewer:** `egm-comprehension` (fresh instance, naive reader) · No standard (self-containment test)
**Status:** completed — 0 Blocker / 2 Major / 10 Nit
**Run:** headless uninterrupted (Preset 1), 14 Nov 2026

Referenced-file verification: all key referenced documents exist and resolve — `SPEC-v3.md`, `REQUIREMENTS.md`, `DECISIONS.md`, `phase-A0-spec.md`, `phase-A-spec.md`, `phase-F-spec.md`, `A1-design-note.md`, `g-factmap.md` (in `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/` and its parent); `T031-run-readiness-spec.md` and `T031-benchmark-packet.md`; `microdrama/evidence/T046.md`; `microdrama/deployment/staging/drill.sh` and `DOMAIN-RUNBOOK.md`. Two referenced artifacts exist nowhere in the repo: `A0-LIVE-REPORT.md` (flagged below) and `PILOT-REPORT.md` (correctly absent — it is G's own future deliverable).

**What this proposes**

Phase G is the "qualification layer" that takes the microdrama V3 pipeline from all-offline acceptance to live operation, without adding new pipeline logic. It has seven deliverables: (1) finish the production composition — per-provider live switches, qualification rows, fail-closed startup checks, worker CPU limits, and an operator-gated domain activation checklist; (2) an off-pace pause and one-shot bot alert for the `dramabox-llm` subscription role, with a structural no-fallback proof; (3) a composed-restore drill that backs up a deliberately "unclean" world (in-flight provider operation, claimed notification, uncommitted scheduler marker) and proves DB + object restore with no duplicate money or publication effects, honestly documenting that notifications are only at-least-once; (4) an all-gate composition test running one 24-episode season through all six approval gates with real handlers and fake providers; (5) the LIVE pilot — P0 (planning plus a bounded live image calibration batch), P1 (one full episode as the quality screen, including a mixed-emotion exit check), P2 (three more episodes measured against throughput and cost thresholds) — in an isolated compose project, every live/paid leg gated by a signed operator authorization and a hard spending envelope, ending in a generated, operator-signed PILOT-REPORT.md and per-destination LIVE claims; (6) the live half of the ARISA/Drama cross-system file-lock test (G owns only the procedure, C owns the mechanism); and (7) live throughput reporting that reads F's existing counters only. Durable state is one new guarded, hash-sealed document store (`v3_ops_documents`, symbolic migration `G-1`) holding four document types (PilotRunV3, LiveClaimV3, RestoreProofV3, ProductionCompositionV3); everything else reuses existing metering tables or evidence files. Build is seven packages (G1–G7) with acceptance tests G-T1 through G-T8, plus LIVE rows that only the operator's execution can pass.

**How the existing system works, per this document**

Per §0, phases A0–F delivered an offline-accepted pipeline: staging runs the `OFFLINE_MOCK` composition only; the production composition is a skeleton (A6c) with role selection, fail-closed startup, and empty `provider_qualifications`; the T046 backup/restore drill exists but drains state before backup; metering tables (`charges`, `cost_allocations`, `llm_invocations`, `quota_observations`, `pod_usage_intervals`, F's `release_throughput_observations`) and A2's budget accounts already exist; the scheduler deduplicates firings via `scheduler_firings`, the event outbox is at-least-once with consumer dedupe, and provider operations reconcile via client tokens ("NOT_FOUND = safe to resubmit") — all cited to code or the factmap (FM). The `dramabox-llm` subscription role exists only in unmerged worktrees; bot alert wiring is F's; platform qualification (T032), the lock mechanism (C3), and all adapters belong to other phases. Runtime modes (`OFFLINE_MOCK`/`PAID_BENCHMARK`/`CONTROLLED_ACCOUNT_TEST`/`PRODUCTION`) already exist in the schema (M/0008). G's stance is that it only adds records, wiring, procedures, and tests on top of this base, and never spends money autonomously.

## Findings (no Blockers — every section was paraphrasable; guessed-at paraphrase parts are named within findings)

### S6-C-1. Bot-alert scope: "both" in binding decision 6 is ambiguous - Severity: Major
* **Affected Scope:** §1 binding decision 6, lines 95–97; concept: bot-alert scope ("both raise one bot alert per pause episode").
* **Discrepancy Description & Rationale:** The sentence lists three A0 refusal kinds (PACE_WEEK, QUOTA_5H/CONCURRENCY, QUOTA_UNREADABLE), then states "per-window refusals defer per job with retry times; an unreadable quota pauses production at route level; both raise one bot alert per pause episode." The antecedent of "both" is ambiguous and admits the reading that QUOTA_5H/CONCURRENCY per-window refusals also raise a scope-level bot alert — which §4 ("Per-job waits (QUOTA_5H, CONCURRENCY): ... no scope alert"), GD2 (cause limited to `QUOTA_UNREADABLE | PACE_WEEK`), and G-T2 explicitly contradict. Conversely, PACE_WEEK — which per §4 and GD2 *is* an alert cause — is not the subject of either clause "both" could point at. The binding-decisions summary cannot be paraphrased correctly from §1 alone; I had to resolve it against §4 and G-T2. One clause naming the two alert causes would fix it.

### S6-C-2. "Pre-agreed contingency (split coverage at speech-safe boundaries)" never explained or anchored - Severity: Major
* **Affected Scope:** §7.3, lines 374–376; concept term: "the pre-agreed contingency (split coverage at speech-safe boundaries)."
* **Discrepancy Description & Rationale:** The pilot's below-threshold quality path routes to "the pre-agreed contingency (split coverage at speech-safe boundaries)," but what split coverage actually does is explained nowhere in the document and carries no link to where it is pre-agreed (presumably the T031 lineage, but no anchor is given). This is load-bearing: it is the decision option the operator faces at `SCREEN_REVIEW`, with a "projected clip/cost impact." My paraphrase here is a guess (that a clip's emotional coverage is somehow re-rendered as split segments at points where no speech occurs). A one-line description or an explicit pointer to the pre-agreement is needed.

### S6-C-3. "master" alias for SPEC-v3.md never declared - Severity: Nit
* **Affected Scope:** Preamble line 13 onward, term "master" (used ~30 times, e.g., "master §10.0," "master §16.3").
* **Discrepancy Description & Rationale:** The alias "master" for SPEC-v3.md is never declared. The reader must infer it by matching section numbers against the preamble's binding-inputs list. A high-confidence inference, but it should be stated once.

### S6-C-4. "the runbook's draft queue", "the A-line", and unexplained 0026 in migration arithmetic - Severity: Nit
* **Affected Scope:** Preamble, lines 10 and 17–19; terms: "the runbook's draft queue," "the A-line," migration-tail arithmetic.
* **Discrepancy Description & Rationale:** "the runbook's draft queue is C, F, E, G, D — FM §7" names no runbook (at least three runbooks are in play: the author's "weekend runbook," the DOMAIN-RUNBOOK, and this unnamed planning runbook). "the A-line allocates 0027–0035" uses "A-line" (guessed: phase A's migration-number lineage) without definition, and the arithmetic leaves 0026 unexplained ("main ends at 0025; the A-line allocates 0027–0035"). Both are decipherable with effort but assume prior knowledge of the migration-allocation conventions.

### S6-C-5. "YuE2" undefined and unlinked - Severity: Nit
* **Affected Scope:** §7.4 line 387 and G-T6 line 490; term: "YuE2."
* **Discrepancy Description & Rationale:** YuE2 appears only in quota-capture enumerations ("SFX/YuE2 (charges)", "quota lines (LLM/images/GPU/SFX/YuE2/Botnoi)") with no definition or link anywhere in the document. Companion providers get incidental context (Nano Banana via "images/hour" and "per-image price"; Botnoi Studio via "voices for both"), so the reader can classify them; YuE2 gets none (I infer it is the music-generation provider from the "SFX / music: C8" pairing in §3.1). One word of context would close it.

### S6-C-6. `dramabox-llm` never given a one-line identity - Severity: Nit
* **Affected Scope:** §4 heading and lines 91–97, 234–254; term: "dramabox-llm."
* **Discrepancy Description & Rationale:** The subject of §4 is never given a one-line identity. Its nature must be assembled from three scattered facts: it "exists only in unmerged worktrees" (§0), it is "the role" that refuses with PACE_WEEK (§1.6), and its behavior is governed by A0 §5.x/§7 anchors. A reader cannot tell whether it is a service, a composition role, or a branch until several sections combine. (It is anchored to A0, so per the linking rule this is borderline — flagged as a clarity nit, not a gap.)

### S6-C-7. "Home" (operator dashboard) never defined - Severity: Nit
* **Affected Scope:** §4 line 252, §5.4 line 304, §11 G2 line 465; term: "Home."
* **Discrepancy Description & Rationale:** "Recovery is visible on Home," "a dead-lettered intent is shown on Home," and G2's "Home surface" all assume the reader knows Home is the operator dashboard/UI. It is never defined or linked in the document.

### S6-C-8. "V1 `make pilot`" and "populated V1+V2+V3 database" left implicit - Severity: Nit
* **Affected Scope:** §11 line 455 and G-T8 line 492; terms: "V1 `make pilot`," "populated V1+V2+V3 database" (G-T1, line 482).
* **Discrepancy Description & Rationale:** Every package gate requires "`make check` + V1 `make pilot` green," but what the V1-era `make pilot` target is and why G's gates depend on it is stated nowhere. Similarly, G-T1's "populated V1+V2+V3 database" assumes the reader knows the database carries three version eras of tables. Both are inherited conventions left implicit.

### S6-C-9. Operator commands' invocation surface unstated - Severity: Nit
* **Affected Scope:** §10 commands table, Actor column ("Operator (human session + CSRF)").
* **Discrepancy Description & Rationale:** Where and how the operator invokes commands like `record_pilot_authorization` (an admin web UI? a console? an HTTP endpoint?) is never stated; "human session + CSRF" and the "(A1 note §6 format)" header assume the reader already knows the A1 command-surface convention. The commands' effects are clear; their invocation surface is an unstated prerequisite.

### S6-C-10. B's planning step numbering assumed - Severity: Nit
* **Affected Scope:** §7.2, items 2–3 ("Full planning, steps 1–3," "Reduced step 4").
* **Discrepancy Description & Rationale:** The numbering of B's planning steps is assumed: the reader must infer that planning has four steps and that step 4 is cast/asset generation (recoverable only from step 4's parenthetical: "2 characters, 2 locations, voices for both"). An explicit listing of B's step numbering would remove the guess.

### S6-C-11. Residual bare external IDs: O-11, AR-4, S05/S06 - Severity: Nit
* **Affected Scope:** §1.2 line 74 ("Botnoi points — O-11 lineage"), §4 line 234 ("AR-4"), §7.3 line 375 ("T031's S05/S06 lineage").
* **Discrepancy Description & Rationale:** Residual bare external IDs with neither an inline gloss nor a link. AR-4's rule is restated in the sentence itself ("derived, never stored") but the ID's home document is not given; O-11 and S05/S06 get no gloss at all (the reader cannot know what S05/S06 or O-11 refer to). Most other external IDs in the document (N12, N36, MA12, V3C-1, D5, O-C4, O-C7, O-5, C-T6, F-T8, PC5-2, PC-7) are properly glossed inline, so these three stand out.

### S6-C-12. A0-LIVE-REPORT.md unpathed and nonexistent; drill.sh cited by bare filename - Severity: Nit
* **Affected Scope:** §3.1 line 183 ("A0-LIVE-REPORT.md") and unpathed file references ("drill.sh:115-119" etc. at lines 106, 116, 206, 267).
* **Discrepancy Description & Rationale:** A0-LIVE-REPORT.md is cited as a current qualification artifact but exists nowhere in the repository and is given no path; a naive reader cannot tell it is a prospective artifact of A0 §7's live qualification rather than an existing document. drill.sh is cited by bare filename with line numbers throughout §3.3/§5.1 without a path (it lives at `microdrama/deployment/staging/drill.sh`); its association with the T046 drill is only inferable.

---

Overall: the document is dense but genuinely self-contained on its load-bearing concepts — the pilot phases, the record store, the pause/alert design, the restore drill, and the gate chain are all defined inline, and nearly every external ID carries a gloss. The two Major items are the only places where a careful naive reader would build a wrong or empty model from the text alone.
