# GLM independent review — T031 native H3 Flex harness (Codex-written)

You are the **reviewer**, not the builder: do not edit, commit or fix anything. Codex
wrote this code, so Codex cannot review it; that is why you are reviewing it.
Orchestrator: Opus session, 10 Nov 2026.

## Where and what

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-native-worktree`, branch
  `feat/t031-pika-flex-native`, HEAD `d971435`.
- **Scope: the 81 files of `048cc05`** (`git show --stat 048cc05`; +12,157/−300):
  - H3 Flex workflow bindings: `rendering/workflows/pika_h3_flex.py`
  - transport and diagnostics: `rendering/pika_transport.py`, `rendering/diagnostics.py`
  - benchmark controller and service: `pipeline/benchmark*.py`,
    `rendering/benchmark_experiments.py`, `rendering/experimental_presets.py`
  - experimental world: `pipeline/experimental_world.py`
  - CLI/auth: `pipeline/benchmark_authorization.py`
  - migration `0026_t031_benchmark_experiments.sql`
  - the VOICE contract additions (package 2.16.0)
  - the image sources in `deployment/pika-h3-flex/`

  Read each file at HEAD. Later commits touched some of them: `c6e19e0`/`2ceb341`
  (migration guards) and `9197c52..d971435` (CN-1..CN-6 fixes, under a separate Codex
  re-review). Don't re-review those fix diffs. Do report anything in the harness they
  missed.
- Context, read first:
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-STEPS-1-3-RESUME.md`. Its
    "Exact next work" items 2–4 are your checklist.
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-benchmark-packet.md`: 8 Thai
    shots × 3 seeds, an unsigned $8 envelope, Ref2VA 480p.
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`

## Review the actual default live composition, not only the injected fixtures

The 124-test composed fixture drives `_advance` with scripted providers. That is not
proof that the default public `execute` path is correct. Trace the real default
factory and CLI path end to end and check:

1. **Money:**
   - 3 screening clips, then 21 samples, share one budget and its hard stops;
   - the $8 envelope cannot be exceeded by retries, restarts or a crash between hold and
     settle;
   - holds, leases and settlements use canonical services and `PriceUnit.REQUEST`;
   - the existing three-attempt canary and production preset eligibility are
     unchanged;
   - storage and invoice finality, and raw billing evidence persistence.
2. **Idempotency:**
   - no duplicate pod create after a durable intent;
   - no duplicate prompt after an uncertain outcome;
   - dispatch-slot races;
   - restart and coordinator adoption;
   - expired-lease cleanup;
   - acquisition-scoped uploads and UNKNOWN reconciliation.
3. **Rights and identity:**
   - current model rights (the `model_rights_*` pins) AND reference rights are both
     required; a reference grant alone never clears model rights;
   - auth byte hash and current caps;
   - logical plan alias and seal identity;
   - per-shot speaker and outfit selection.
4. **Honest readiness:**
   - the no-effect preflight reads current canonical account, rights and asset state;
   - it never reports executable-ready from labels or hashes when the default factory
     would later refuse;
   - CPU/no-weight schema attestation (`schema-attestation.cpu.json`) can never be
     relabelled as a LIVE executable attestation.
5. **Safety:**
   - every paid, cloud or public effect is gated by the execution-mode flags;
   - no secrets in the image, logs, records or exceptions;
   - the image and weights (~42 GB) are pulled only at an authorized time, with pinned
     sources;
   - 0026 guards are present.
6. **Tests:** do they prove behaviour, or restate the implementation? Name important
   paths that have no test.

## Constraints

- Read-only. The orchestrator is running the full `make check` in this worktree right
  now, so **do not run pytest suites** and do not write anywhere in the worktree.
  Small in-memory Python probes are fine, using `PYTHONPATH=microdrama/src` and the
  worktree's interpreter. Don't import anything that opens network connections or
  databases.
- No provider/network calls, no docker, no deletion commands (`rm`, `git rm`,
  `git clean`, `git reset`, `find -delete`).
- Never print env vars, `.env` files, keys or tokens.

## Output

Write the full report to
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-harness-REPORT.md`.
That is the only file you may write; `--out` gets overwritten by your final message.

- Per finding: ID `H-1`…, severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, the
  concrete failure scenario (inputs/state → wrong outcome), a suggested fix, and your
  confidence level.
- Report only what you can point to in code. Then add a coverage table: each checklist
  item above → CHECKED-OK / FINDING / NOT-REACHED.
- End with a verdict: **ACCEPT** or **FIX-REQUIRED**.

Final message: the verdict, the counts by severity, and the report path.
