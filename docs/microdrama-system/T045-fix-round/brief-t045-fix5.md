# Resume build T045-FIX (session 5): finish what session 4 left

Session 4 stopped after 24 minutes on a z.ai usage limit (HTTP 429). You continue it. All briefs, reviews and
probes are in `docs/microdrama-system/T045-fix-round/` (see its README). Write the report there as
`T045-FIX-REPORT.md` and leave it uncommitted; the orchestrator commits it after checking it.

**The binding brief is `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/brief-t045-fix4.md`.**
Read it in full first, and the two briefs it names. Every ruling, hard limit, ordering rule, the no-deletion-verbs
rule, the `--deselect` rule for the two `_prepare_durable_root` tests, and the report path
(`docs/microdrama-system/T045-fix-round/T045-FIX-REPORT.md`, not `--out`) apply unchanged.

## Where session 4 stopped

- **HEAD:** a docs-only handoff commit ("T045 handoff to the GLM orchestrator") on top of `b05b66a` ("T045-FIX
  RR-N3/B-N1"), which sits on `7faef9e`. Check `git log --oneline 7f857eb..HEAD`.
- **Uncommitted, in progress: F-1.**
  - `rendering/janitor.py`: a shared `_stop_terminate_and_verify` tail. The orphan path sends a terminal lease
    with `terminate_verified_at IS NULL` through it.
  - `tests/unit/rendering/test_t045_billing_ingestion.py`: the F-1 tests.

  Read `git diff`. Check every clause of the F-1 ruling. Get the red line by running the new tests with the
  `janitor.py` change stashed. Get the green line. Run the focused billing/janitor suites under the CPU quota. Then
  commit as `fix(microdrama): T045-FIX F-1 - ...`.
- **Still to do, in this order:**
  F-4 → O-1 → F-5 → F-2 → F-3 → O-2 → the rest of B-S1 → F-6 → docs → evidence → gates → report.

**If you hit a usage limit again:** stop cleanly. Commit only work whose tests pass. Write what is done and what is
left to the REPORT path.
