All five packages are complete. Final state: tracked tree clean, F1–F5 committed on `feat/t031-fix3`, `make lint` green, all regression batches green. The stash was already applied and dropped by the earlier session (the `wip/t031-hcf-f3-stash` branch remains at `1f9bc18` for the orchestrator, per the brief).

- **F1** — HC-2: out-of-spec canonical receipt conversions reverted; late billing met in the benchmark layer — `6db5fe8`
- **F2** — HC-6 one ordered lock helper incl. L/S + corrected inventory; HC-5 live ownership everywhere — `9b736da`
- **F3** — HC-1 invoice finality; HC-7 every reservation entry point; HC-8 durable ambiguity; HC-9 deadline recompute — `e521653`
- **F4** — HC-3 R7 recoverability via the RECOVERY path (client-ID discovery, EXPIRED read); HC-4 complete terminal replay, U4 failfast, durable-asset-gated success — `c044daf`
- **F5** — HC-10 honest proofs (real wrapper + gate in the races, no swallowed exceptions, exact dedup counts, S08 actually bound, storage_final requires financial finality, worker lock_timeout); HC-11 CLI recovery-first; HC-12 durable incidents in status/export; acquisition monotonicity on replayed cleanup — `7060e02`

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-hcf-REPORT.md` (top line: `H2-HCF: ALL FIXES DONE`; "Resume here" names the untracked leftovers — the empty `.md` stray, `zz_debug_f3.py`, `.scratch/` red-run diffs — none ever staged).
