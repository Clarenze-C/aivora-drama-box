# Codex review: H-2 build P4, HBF, LF and P5 against spec v3 (money path)

Read-only. Checkout `/root/AIVORA/drama-box/.scratch/t031-gate-h2` (detached at `0e34630`). The full offline
gate is running in it under systemd. Don't run tests there and don't write files.

**Scope: `git diff 45e4f2a...0e34630`.** That is 20 commits, 23 files, about +6,300/−540. GLM wrote all
of them; you did not. They are:
- **P4** `941ab6d`: §6 shared lock order + R5, billing-wrapper reorder, `resolve_create` with SC2-3 replay,
  storage release only at sweep with R1, the contradiction incident path.
- **HBF** `30d5e30`..`5790a45` + `9c28ac6`: GLM's fixes for **your** P1–P3 findings HB-1..HB-14. **This is
  the re-review (round 2) of those findings.**
- **LF** `8810068`, `3b63acd`, `bdf1e2b`: GLM's fixes for the GLM review of Luna's `82135d4` (L-1..L-7).
- **P5** `0e34630`: §7 `finalize_terminal`, terminal mapping, monotonic projection, R6 atomic fail-fast,
  R7 operator resolution, R8.

Out of scope: P1–P3 code except where HBF changed it, and Luna's `82135d4` itself except where LF changed
it.

## The requirement

- Spec v3: `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md` (it contains your
  R1–R8 and SC2 wording).
- Your P1–P3 review: `T031-fix-round/codex-review-h2-p1p3.md`. The rulings are at the end of
  `T031-fix-round/rulings-canary-night.md`.
- The GLM Luna review: `T031-fix-round/glm-review-luna-REPORT.md`.
- The builder's report: `T031-fix-round/h2-build-REPORT.md`. Read its judgement calls critically.
- Contract: `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`.

## Review

1. **HB-1..HB-14:** for each, **CLOSED / PARTIAL / OPEN**, with `file:line`. Check that each fix's test
   fails without the fix (from the reported red lines and the code), and that HB-13's fixtures are
   strict, not merely changed.
2. **L-1..L-7:** CLOSED / PARTIAL / OPEN (L-1 and L-2 were BLOCKING).
3. **P4 and P5 conformance** per §6 and §7: DONE / PARTIAL / MISSING, with `file:line`. Check especially:
   - one lock order everywhere, including the billing wrapper; no inversion against canonical
     settlement;
   - `resolve_create` replay (SC2-3) never creates twice;
   - storage released only at sweep finality (R1);
   - `finalize_terminal` is idempotent and monotonic;
   - R6 atomic fail-fast;
   - R7 operator resolution, which must not release exposure blindly;
   - R8.
4. **Tests:**
   - Do AT-6/7/8/9/12/21/22/26 and the §9.3 extensions prove their invariants through public entry points?
   - Real PostgreSQL for the lock and race tests?
   - At least one real SIGKILL/`os._exit` death test?
   - Any weakened or skipped assertion?
5. **New defects:** money, duplicate effects, lock order, secrets.

## Output

- Read-only sandbox: no writes, no `systemd-run`, no integration suite. Small in-memory probes are fine.
- Put the full report in your final message.
- Findings use IDs `HC-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a concrete failure
  scenario and a fix.
- Verdict: **ACCEPT** or **FIX-REQUIRED**. This is round 1 for P4/P5/LF and round 2 for HB-1..HB-14.
