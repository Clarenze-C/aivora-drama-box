# Codex critique: B1 design note v0.1 — round 1 (before any B build)

Note: `B1-design-note.md` **v0.1** (`b3343a8`, 599 lines), GLM-drafted from **phase-B-spec.md v0.6
(ACCEPTED)** §13's B1 package + §9 command table, building on **A1-design-note.md v1.4 (ACCEPTED)**.

Binding context: `phase-B-spec.md` v0.6; `phase-A-spec.md` v0.3; `A1-design-note.md` v1.4;
`A3-design-note.md` v1.3 (accepted); `phase-A0-spec.md` v0.4; `SPEC-v3.md` v0.4.6; DECISIONS O-B1..6.
Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer
1. Records/DDL vs the spec's §2/§6 rows and the symbolic `B-1…` allocation; V1/V2 preservation.
2. The D1..D6 delta rows B1 owns — each matched to A1's enforced vocabulary?
3. Command table completeness (actor, states/prerequisites, transaction+locks per A1 §7's order,
   events, jobs, replay) vs the spec §9.
4. The prompt-registry table (B1-owned, §7.3) vs the V2 PromptManifest staying untouched.
5. Generation-round identity + intake/version linkage vs `core/jobs.py:429` replay matching.
6. Which B-T rows B1 alone can pass; B2/B3 preparation clauses correctly not gated here.
7. Anything that would make the B1 build fail or contradict A/A1/A3/B.

## Output: read-only; ≤140 lines; issues `B1-x` BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
