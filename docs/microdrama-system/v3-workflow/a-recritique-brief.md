# Codex re-critique (round 2 of 2): Phase A spec v0.2 (Foundations)

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A-spec.md` **v0.2**.
Your round-1 report: `codex-a-critique.md` (AC-1..23, REWORK). v0.2 §12 maps each finding.
v0.2 §0 makes your round-1 replacement wording binding, except where §2–§9 choose differently.
Master: `SPEC-v3.md` v0.4.2. A0: `phase-A0-spec.md` v0.3.

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/`. Branch `feat/microdrama-m0-m4`.

## Scope: this is a re-review

1. For each AC-1..23: **RESOLVED / PARTIAL / NOT RESOLVED**, with one line of evidence.
2. **New defects introduced by the v0.2 decisions**, in particular:
   - **derived waits** (`track_waits` from job facts, §3);
   - **legacy state staying at `PROPOSED`/`PLANNED` for V3** plus `require_workflow` guards (§1);
   - the **V3 Reject semantics** on CAST_LOCK/LAUNCH (§2.2);
   - the **`SEASON` account created at STORY LOCK** with setup checked alone before it (§5.1);
   - the **lock order** (§6) against existing transactions;
   - **dispatcher fan-out** with an intent row per event/channel (§8.1);
   - the **scheduler lock held on a dedicated connection** across handler transactions (§9.1).
3. **The package split** (§10): is the order right? Are the A1–A3 note-first gates enough? Is any package
   still too large?

Do not re-open settled design unless it is unsafe or unbuildable. Package design notes will settle DDL
details; flag only what a note can't settle.

## Output

- Read-only; no writes. Final message at most about 130 lines.
- A table AC-1..23 → status + evidence. New issues use `AR-1`…, with severity
  **BLOCKING / SHOULD-FIX / NIT** and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
