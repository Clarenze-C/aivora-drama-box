# Codex critique — T031 H-2 recovery spec (before the build)

Attack this spec before anyone builds it:
`/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`

Ground truth:
- the contract `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`
  (§A, §C, §E, §F, §G);
- your own code map `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-codemap.md`;
- the code at `/root/AIVORA/drama-box/.scratch/t031-review-r3` (detached `628fe5b`);
- your round-3 findings `.../T031-fix-round/codex-rereview-r3.md`.

## Answer

1. **Contract conformance.** Does any clause in the spec contradict §A, §C, §E or §F?
   Quote the clause and the spec line.
2. **Does each CN3 finding actually close?** For each of CN3-1..CN3-5, say whether
   the spec closes it, and how it could still fail.
3. **Missing failure modes.** Look for crash or race windows the spec does not cover.
   Specifically check:
   - the §5 grace path: the pod billing during the grace, the hard stop, and a crash
     during the grace;
   - the §6 lock order against every existing transaction that touches the same rows
     (janitor, billing finality, sweep, `_claim_sample`, `reserve_linked`). Is there
     any deadlock cycle?
   - the U1–U5 completeness: is there an unresolved state the gate misses?
   - `PENDING_SUBMIT` operations (crash after begin, before POST): how should they be
     classified?
4. **Implementability.** Can each item be built on the current code without changing the
   contract package or migrations 0001–0025? Is anything vague enough that a builder
   would have to invent behaviour? Name it and propose exact wording.
5. **The three open questions in §10.** Give a recommendation with reasons. On Q2,
   quote §A.
6. **Test plan.** Are AT-1..AT-12 sufficient and feasible offline? Is any test missing
   that is needed to prove an invariant?

## Output

- Read-only sandbox: no file writes. Put the full critique in your final message.
- Per issue: ID `SC-1`…, severity **BLOCKING** (spec must change before the build) /
  **SHOULD-FIX** / **NIT**, the spec section, the problem, and **replacement wording**.
- End with: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
