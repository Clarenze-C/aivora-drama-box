# B5 design note (GLM, docs only): STORY LOCK + the extension branch

Orchestrator: GLM (operator autonomy window), 14 Nov 2026. **Write one file:**
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B5-design-note.md`, **v0.1 DRAFT**. It
will be Codex-critiqued before any B build. Resume if the file exists.

## Binding inputs (read fully)
- `phase-B-spec.md` **v0.6 (ACCEPTED)** — the note implements **B5** per §13's package table: the
  STORY LOCK transaction (one transaction, episode rows created at once, binding hash complete),
  the **extension-aware branch** (§5.3/§8: scoped by `extension_id`, appended contiguous range only,
  existing budget hierarchy reused, only the extension planning track advances), the immutable
  episode-count **authorization** (§8), the season critic prompt (B5-owned, registered in B1's
  prompt registry), and the §5.4 binding/preimage rules.
- **B1-design-note.md v0.3 (ACCEPTED)** — the records/registry B5 consumes; stay exactly consistent.
- `A1-design-note.md` **v1.4 (ACCEPTED)** + `phase-A-spec.md` v0.3 — the decision transaction, fence,
  activations, RevisionTargetKind; B5's gate runs through A1's machinery.
- `A2-design-note.md` v1.3 (parked — cross-check the budget hierarchy facts only, flag conflicts as
  open questions, do not resolve A2's parked items).
- `phase-C-spec.md` v0.4.1, `phase-E-spec.md` v0.4, `phase-F-spec.md` v0.4 — the downstream seams
  (binding hashes C/F consume).
- Style model: `B1-design-note.md` v0.3.

## What the note must pin
1. The STORY LOCK transaction: lock order (A1 §7), the exact preimage per member class, episode-row
   creation, the binding write, the activation it opens.
2. The extension branch: entry conditions, the authorization read/validation, the appended-range
   edges, rollback, the extension track's advance.
3. The season critic: its prompt registration (B1's registry), call sites, failure handling.
4. Command table entries (actor, states/prerequisites, transactions+locks, events, jobs, replay).
5. Acceptance mapping: the B-T rows B5 alone can pass; the clauses needing C/E/F.
6. Open questions with recommendations (A2-parked conflicts recorded, not resolved).

## Rules
Never contradict the accepted specs; conflicts → open question. Facts carry file:line, verified
read-only on `feat/microdrama-m0-m4`. Target 400–600 lines. No deletions; never print env/keys.
**Commit yourself**: `docs(v3): B5 design note v0.1 (GLM)`. Final message ≤12 lines + path.
