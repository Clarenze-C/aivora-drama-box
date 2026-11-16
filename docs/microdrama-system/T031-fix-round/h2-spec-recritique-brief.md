# Codex re-critique (round 2 of 2) — T031 H-2 recovery spec v2

Spec v2: `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`.
It accepts all of your round-1 findings, SC-1..SC-14
(`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-h2-spec-critique.md`);
its §12 maps each finding to its section. Ground truth is unchanged: the contract (§A,
§C, §E, §F, §G), your code map (`.../T031-fix-round/h2-codemap.md`), and the code at
`/root/AIVORA/drama-box/.scratch/t031-review-r3` (`628fe5b`).

## Scope (round 2: fixed findings and new defects only)

1. For each of SC-1..SC-14: **CLOSED / PARTIAL / OPEN**, with one line on why. If PARTIAL
   or OPEN, give exact replacement wording.
2. Any **new** BLOCKING issue that v2 itself introduced. Check especially:
   - §4.1 U1–U6 completeness against your round-1 list, and whether any predicate blocks
     the happy path (rerun the SC-2 check across U1–U6);
   - §5.4's deadline composition and fencing;
   - §6.1's lock order against every listed transaction (any remaining cycle?);
   - §6.4's incident path versus the partial unique index and `gpu_ms()`;
   - §3.3's EXPIRED-read exception (does it open a dispatch path?);
   - §4.2's CLI `resume` ordering.
3. Is AT-0..AT-26 sufficient and feasible offline (local PostgreSQL, subprocess,
   fake HTTP)? Name only what is missing to prove an invariant.

Do not re-litigate accepted decisions (Q1–Q3 in §11, fail-fast in §7.4) unless they
violate the contract. Quote the clause if so.

## Output

- Read-only sandbox, no writes. Put the full report in your final message.
- New issues use IDs `SC2-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, the
  section, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** (listing the exact edits) / **REWORK**.
  This is the last critique round. Anything left after it goes to the operator.
