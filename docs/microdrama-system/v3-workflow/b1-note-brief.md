# B1 design note (GLM, docs only): seasons, gates registry, decision transaction base, prompt registry

Orchestrator: GLM (operator autonomy window), 14 Nov 2026. **Write one file:**
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md`, **v0.1 DRAFT**. It
will be Codex-critiqued before any B build. If the file exists, resume it.

## Binding inputs (read fully)
- `phase-B-spec.md` **v0.6 (ACCEPTED)** — the note implements **B1** per §13's package table and the
  command table (§9); follow every B1 clause incl. the §2.4 contract-delta register rows B1 owns
  (D1..D6 as assigned) and the §7.1 completion seam + §7.3 prompt registry that ship in B2/B3 but
  whose **tables/records B1 creates**.
- `phase-A-spec.md` v0.3 + `A1-design-note.md` **v1.4 (ACCEPTED)** — the decision transaction, gates,
  fence, RevisionTargetKind, activations; B1 builds on A1's accepted contracts exactly.
- `A3-design-note.md` v1.3 (accepted) for the worker/job seams; `phase-A0-spec.md` v0.4.
- `SPEC-v3.md` v0.4.6 §4.1–4.3, §15; `DECISIONS.md` O-B1..O-B6 answers.
- Style model: `A2-design-note.md`/§A3 (accepted chains' shape): records/DDL (symbolic `B-1…`),
  commands, transactions+locks (A1 §7's order), jobs/waits, acceptance mapping to B-T1/B-T3 rows,
  open questions.

## What the note must pin
1. Records + DDL for B1's scope (per the spec's §2/§6 rows): v3 season documents/intake, the
   generation-round identity (§2), `SeasonBibleV3`/`EpisodePackV3` stores, the prompt registry
   (B1-owned table, §7.3), approval/activation linkage via A1's transaction.
2. The D1..D6 delta rows B1 owns, each matched to A1's enforced vocabulary.
3. Command table entries for B1's operator commands (actor, states/prerequisites, transaction+locks,
   events, jobs, replay per the spec §9).
4. Transaction/lock audit against A1 §7's order for every mutation.
5. Acceptance: which B-T rows B1 alone can pass; the B2/B3 clauses B1 prepares but doesn't gate.
6. Open questions with recommendations.

## Rules
Never contradict the accepted specs; conflicts → open question. Facts carry file:line; code facts
verified read-only on `feat/microdrama-m0-m4`. Target 400–600 lines. No deletions; never print
env/keys. **Commit yourself**: `docs(v3): B1 design note v0.1 (GLM)`. Final message ≤12 lines + path.
