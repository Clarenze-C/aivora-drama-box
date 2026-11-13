# Codex critique: T031 run-readiness spec v0.2 (R5), before the build — round 1

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md` **v0.2**. Opus wrote v0.1. GLM applied
Opus's rulings on a Goldfish review to make v0.2. The rulings are `T031-fix-round/r5-goldfish-rulings.md` and the review
is `T031-fix-round/r5-goldfish/consolidated_review_report.md`. You did not write any of it.

Code (read-only): this cwd, `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree` (`feat/t031-fix3`, the accepted
T031 H-2 tree plus build-tooling commits). Facts: `docs/microdrama-system/t031-benchmark/paid-run-factmap.md` in the
main checkout. Your own earlier T031 reviews are binding history (`T031-fix-round/codex-review-*.md`).

**This is a money path:** paid RunPod GPU pods on a $8 cap.

## Answer

1. **Predicted schema (R5c, ruling CON-B1):** is "sealed predicted schema from the pinned image with placeholder model
   files, verified live before any upload" an acceptable replacement for `INDEPENDENT_RUNTIME_CAPTURE`? Which
   failure could it let through that a live capture would catch? If unacceptable, say so plainly; C becomes a new
   spec round.
2. **Ready gate (CON-M1):**
   - Is the request-guard placement conforming?
   - Can any prompt hold expire during boot?
   - Can a booting pod ever be recorded as upload or submit ambiguity?
3. **Weights (R5a):** `start.sh` + state file + gateway endpoint, both gateway copies, and the env flag's layer
   (CON-M13). Is it fail-closed when provisioning fails?
4. **No-migration landing zone (CON-M3):** is the mutable `benchmark_samples.coverage` sound for timings,
   live-capture records and incidents? Check the `benchmark_acquisitions.state` CHECK.
5. **Assembly (R5d) and the runbook (§7):**
   - Is the role → asset mapping valid against the seal and port-map validators?
   - Is every step executable in order?
   - Does the digest sequencing (push → predict on the registry digest → author → sign) hold?
6. **Budget, retry and risks:** do two cold starts plus up to 3 boot attempts per phase fit $8 / 4 GPU-h with the
   screen?
7. **Anything that would make the build fail or weaken an accepted H-2 invariant.**

## Output

- Read-only; no writes. Final message at most about 180 lines.
- Findings `R5C-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a concrete failure scenario, and
  replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
