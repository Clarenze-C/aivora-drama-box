# Scoped review: T045-FIX post-round-2 commits (Codex, read-only)

You are the independent reviewer for the Drama Box T045 fix round. GLM-5.3 wrote all of T045;
you wrote none of it. This is a READ-ONLY review: do not edit, commit, push or revert anything.
Do not run destructive git commands. Report findings only.

## Scope

Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`. Review the diff `7faef9e..HEAD`
(everything after the round-2 reviewer's focused run): session 3's tail (`b05b66a` RR-N3/B-N1),
the docs handoff (`4acc67d`), and session 5's close-out (`10d7d31..c51c709`: F-1 + F-1 follow-up,
F-4, O-1, F-5, F-2, F-3, O-2, B-S1 rest, F-6, runbook, evidence).

## Binding context (read these first, in this order)

1. `docs/microdrama-system/T045-fix-round/brief-t045-fix4.md` — the binding rulings. Every fix
   must satisfy its ruling text, not just look reasonable.
2. `docs/microdrama-system/T045-fix-round/rereview2-t045fix.md` — round-2 report (9 FIXED,
   1 PARTIAL, 0 BLOCKING at `7faef9e`).
3. `docs/microdrama-system/T045-fix-round/T045-FIX-REPORT.md` — session 5's close-out report
   (what it claims, including its own list of loosened/changed/removed test assertions).
4. `docs/microdrama-system/T045-fix-round/README.md` — the round's record index.

## What to verify (in priority order)

1. **F-1 and F-4 are money-path.** F-1: the stop→terminate→verify tail retry for a terminal
   lease whose Pod terminate failed; billing ingest must defer while a seen Pod's terminate is
   unverified; the follow-up (`0161120`) scopes the retry to Runpod-only. Check: can any path
   still ingest an unfinalized lease window, double-charge a retried terminate, or re-stop a
   non-Runpod terminal Pod forever? F-4: a failed prompt with no retry settles its hold at 0 at
   run end. Check: any path where a hold stays ACTIVE, or a production FAILED attempt is settled
   at 0 when it must keep its charge.
2. **Each remaining ruling (O-1, F-5, F-2, F-3, O-2, B-S1 rest, F-6) is actually implemented as
   ruled**, with tests that pin the ruled behavior (red-then-green claimed in the evidence), not
   tests adjusted to whatever the code does.
3. **The changed-tests list in T045-FIX-REPORT.md is honest**: every rewritten/pinned/re-parented
   test matches its stated ruling reason; nothing was quietly loosened beyond the rulings.
4. **No new defects introduced** in the diff: regressions in janitor/sweep/canary CLI behavior,
   shutdown handling (F-2), DSN guard completeness (F-5), filesystem-safety holes (O-1/O-2/B-S1).
5. Evidence honesty: `microdrama/evidence/T045.md` section "T045-FIX (2 Nov)" — the IDs recorded
   as "red line never recorded" are labeled as such and their suites pass at HEAD.

You may run the focused test suites (they are offline/fixture-only) under the CPU quota, e.g.:

    systemd-run -p CPUQuota=45% --scope bash -c '.venv/bin/python -m pytest tests/unit/rendering tests/unit/pipeline -q' 

(from `microdrama/`). Do NOT run `canary execute`, `make canary-db`, or any command that touches
a real provider, network or paid resource. No pod, no key, no platform.

## Output

Write your full report to `docs/microdrama-system/T045-fix-round/codex-review-t045fix5.md`
(create it; leave it uncommitted) with:

- a verdict line first: `VERDICT: ACCEPT` or `VERDICT: FIX-REQUIRED`;
- findings each with ID (CR-1, CR-2, ...), severity (BLOCKING / NON-BLOCKING / NIT), file:line,
  the failure scenario, and the ruling text it violates when it violates one;
- a per-ruling table: F-1 (incl. follow-up), F-4, O-1, F-5, F-2, F-3, O-2, B-S1-rest, F-6 →
  SATISFIES-RULING / VIOLATES / OUT-OF-SCOPE with one line of why.

Your final message (stdout) should be only a short summary: the verdict plus the count of
BLOCKING/NON-BLOCKING/NIT findings.
