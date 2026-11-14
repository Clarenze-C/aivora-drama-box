# Codex critique: B5 design note v0.1 — round 1 (before any B build)

Note: `B5-design-note.md` **v0.1** (`e8849ef`), GLM-drafted from **phase-B-spec.md v0.6 (ACCEPTED)**
§13's B5 package (STORY LOCK transaction; the extension branch §5.3/§8; the immutable count
authorization; the season critic prompt; §5.4 bindings), building on **B1-design-note.md v0.3
(ACCEPTED)** and **A1-design-note.md v1.4 (ACCEPTED)**.

Binding context: `phase-B-spec.md` v0.6; `B1-design-note.md` v0.3; `A1-design-note.md` v1.4;
`phase-A-spec.md` v0.3; `A2-design-note.md` v1.3 (parked — conflicts are open questions);
`phase-C-spec.md` v0.4.1; `phase-E-spec.md` v0.4; `phase-F-spec.md` v0.4; `SPEC-v3.md` v0.4.6.
Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer
1. The STORY LOCK transaction: lock order vs A1 §7; the exact preimage per member class; episode-row
   creation; the binding write; the activation opened.
2. The extension branch: entry conditions, authorization validation, appended-range edges, rollback,
   the extension track's advance — vs the spec §8 exactly.
3. The season critic: prompt registration in B1's registry; call sites; failure handling.
4. Command table completeness (actor/states/transactions+locks/events/jobs/replay).
5. Which B-T rows B5 alone can pass; cross-phase clauses correctly deferred.
6. Anything that would make the B5 build fail or contradict A/A1/B1/C/E/F.

## Output: read-only; ≤140 lines; issues `B5-x` BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
