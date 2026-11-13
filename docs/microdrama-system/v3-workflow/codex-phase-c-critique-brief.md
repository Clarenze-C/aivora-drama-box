# Codex critique: phase C spec v0.2 (character bible → picks → wardrobe → voices → CAST LOCK), before code — round 1

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md` **v0.2** (734 lines).
GLM drafted v0.1 and applied its own Goldfish rulings to make v0.2 (`phase-c-goldfish-rulings.md`,
review in `phase-c-review/consolidated_review_report.md`). You did not write any of it.

Binding context:
- `SPEC-v3.md` v0.4.6 §4.4 (step 4), §5–§7, §10.2–§10.3, §12.1–§12.2, §15 (phase C row: V3-AT-5, 6, 7, 15, 22, 23, 28, 33);
- `DECISIONS.md`: "D2 revised again" (one neutral Botnoi voice per speaker), Q8 (Nano Banana, shared with ARISA), O-11 (Botnoi OPERATOR_ATTESTED), the community-voice rule;
- `phase-A-spec.md` v0.3; `A1-design-note.md` v1.2; `phase-A0-spec.md` v0.4; `phase-B-spec.md` (v0.4; v0.5 in flight);
- facts: `c-factmap.md`.

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/` on `feat/microdrama-m0-m4`
(migrations 0026–0027 only under `.scratch/a0d-gate/microdrama/migrations/`). ARISA's Nano Banana lock
code: `/root/AIVORA/arisa/studio/sfw/providers/` (read-only).

## Answer

1. **The two former Blockers:** is the initial-generation batch (BLK-1 resolution: ordinary
   `cast_v3.generate` jobs at setup-budget approval, 3 candidates/root item, one job per candidate,
   `<gen_seq>` segment) now complete and consistent with §1.2 "votes start no work"? Is the BLK-2
   mapping table + version-aware CHECK growth + ref_key namespacing sound and V1-preserving?
2. **The crossing register (§2.2, CD1–CD5):** does every C identifier that crosses an A-enforced
   contract match its enforced vocabulary (jobs queue CHECK, identity_locks NOT NULLs,
   `RevisionTargetKind.PICK`, `PROVIDER_LOCK_BUSY`, `visual_lock.sheet_views`)?
3. **Pick flow (V3-AT-5):** votes start no work; Re-roll requeues one item; Lock refused until every
   required item is picked (human vs derived split); lock hash covers every picked version (exact
   per-class preimage).
4. **CAST LOCK and R-12.1 (V3-AT-6):** identity lock attaches to every episode including later ones —
   is the adopt-if-present split (initial stamped at lock vs extension episodes at insert) correct
   against the real helper (`service.py:285-308`)?
5. **Wardrobe continuity (V3-AT-7/23)** across episode boundaries with timed changes.
6. **Cross-system lock (V3-AT-15/28):** inode-pinned flock interop with ARISA, crash-safe, typed
   outcomes.
7. **Provenance + output inspection (V3-AT-33)** and voices (catalogue, shortlist determinism,
   quarantine, rights incl. WORLDWIDE default).
8. **Packages and tests:** C1–C9b order, C8's note-first placeholder (do not demand its content), and
   whether C-T1..C-T15 now gate each package where its clauses can pass.
9. **Anything that would make a C build fail or contradict A0/A/A1–A3/B.**

Two questions are OPEN (OPERATOR) by design — O-C1 (neutral-source intake) and O-C9 (V1 lock
carve-out): flag dependency risk, do not demand their resolution.

## Output

- Read-only; no writes. Final message at most about 180 lines.
- Issues use `PC-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`/`§`, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
