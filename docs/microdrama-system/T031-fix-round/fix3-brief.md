# T031 fix round 3 — CN2-1..CN2-4 + harness review H-1..H-9 (GLM build)

Orchestrator: Opus session, 10 Nov 2026. Operator approved this third round (bundled).
Size: Medium, with H-2 the largest item. You are the builder.

## Where

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch
  `feat/t031-fix3`, created at `d971435` (tip of `feat/t031-pika-flex-native`). Commit
  on top; never amend or rewrite. `microdrama/.venv` is a symlink to the shared venv:
  never stage it.
- A full gate is running in the OTHER worktree (`.scratch/t031-native-worktree`). Never
  touch that worktree.
- Inputs, read all first:
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-rereview-fix2.md`
    (CN2-1..CN2-4)
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-harness-REPORT.md`
    (H-1..H-9)
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/rulings-canary-night.md`
    (CN2 rulings, binding)
  - `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`
    (§E reconciliation, §G billing evidence)

## Rulings (orchestrator), each fixed tests-first (red, then green)

**BLOCKING**

- **CN2-1:** the billing residual allocator must conserve the ceiling total in every
  case. Allocate the whole residual deterministically, including when tolerance crosses
  an integer boundary; no `assert` on the money path. Test with Codex's exact case
  (total 0.0000030000001, three components 0.0000009999999), plus property-style
  conservation tests and a genuine-mismatch-still-DISPUTED test.
- **CN2-2:** every resolved credential the request carries goes into the redaction
  context for that request's diagnostics. That covers the Runpod key AND the Comfy token
  in the create payload's env, plus any other body-borne secret. Test: an unlabelled
  echo of a synthetic Comfy token in a 400 body is absent from the exception, the run
  record and stderr.
- **H-1:** `pipeline/experimental_world.py:150` calls `bind_pod_endpoint(pod)`, but the
  signature is `(pod_id, endpoint_url)`. Fix the call. Also remove the `hasattr` escape
  hatch: the live client must bind, and a client without the method must fail loudly.
  Give the test fakes the real signature, so the default path is exercised. Add a
  composed test that runs the real `ComfyHttpClient`/`PikaHttpClient` binding through
  `acquire()`, with `urlopen` faked in memory.
- **H-2:** implement the provider-operation reconciler required by contract §E. Follow
  §E exactly; where it is silent, choose the conservative option and say so in the
  report.
  1. An UNKNOWN pod create reconciles by client token or deterministic name. If the pod
     is positively found, adopt it, then bind and open storage ownership. Set
     `NO_CREATE_PROVEN` only on positive proof per §E (for example, a durable record
     that the create was never sent). Otherwise give the operator an audited CLI
     resolution, mirroring the canary's `resolve_podless_create`.
  2. An UNKNOWN prompt reconciles by durable prompt id through ComfyUI history and
     queue. It never resubmits blindly.
  3. Once every UNKNOWN is resolved, the experiment leaves `NEEDS_RECONCILIATION` and
     resumes.
  4. Sweep must not hold the unique dispatch slot forever.

  Holds stay retained until resolution, so money stays safe throughout. Tests:
  ambiguous create → found, ambiguous create → operator-resolved, prompt POST timeout
  → history shows it → no resubmit, and resume after a restart.

**SHOULD-FIX**

- **CN2-3:** the POST-accept recorder opens storage ownership with the binding, and the
  janitor's bound-pod cleanup heals missing ownership before termination and accounting.
  Test: worker death right after POST-accept, then janitor cleanup; disk is attributed
  to the lease.
- **CN2-4:** refuse expired dispatch at the transport boundary (no request starts after
  the deadline), and cap the timeout at the actual positive remainder: drop the 1 s
  floor and update the test that codified it. Keep the cleanup-deadline reset. Tests
  advance the clock inside nested requests and cover sub-second and expired deadlines.
- **H-3:** preflight and the default factory share one validation source, so
  `ready` holds only when the factory would accept. Test: a state the factory refuses
  (rights, preset or account) must make preflight report not-ready.
- **H-4:** wire the §G `benchmark_billing_evidence` writer into the billing path, so raw
  provider amount strings persist. Test it.
- **H-5:** shot-scoped port maps must stage and bind (S08 costume change). If the
  `UNIQUE(acquisition_id, destination_slot)` constraint is the obstacle, edit 0026 in
  place: it has never been applied outside test DBs. Keep every guard trigger, and
  update test expectations that pin the schema.
- **H-6:** machine-deny the known CPU/no-weight attestation hash (`339021b1…`, see the
  report) and any LIVE attestation whose evidence is only a self-asserted label. Test it.

**NIT**

- **H-7:** fix the cleanup-hold-to-acquisition link.
- **H-8:** remove the dead duplicate `ExperimentalPresetPolicy`, by editing code, never
  with shell deletion.
- **H-9:** documentation only. State the prompt-hold resume window and its terminal
  downside in the benchmark README or runbook. No behaviour change.

If any ruling turns out to conflict with the contract or with another fix, stop at a
red test and explain the conflict in the report. Do not improvise a redesign.

## Hard limits

- Offline only. Export `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK
  MICRODRAMA_PAID_REQUESTS_ENABLED=false MICRODRAMA_CLOUD_RESOURCES_ENABLED=false
  MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`. No provider/network calls, no docker build
  or push, no pod creation, no service restarts, no clearing of shared data. No pushes,
  no merges.
- Do not touch migrations 0001–0025 or `microdrama/contracts/` (guardian-owned,
  2.16.0). If a fix truly needs a contract change, stop and report it.
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/t031-fix3-basetemp`. Each command must finish within 10 minutes;
  run focused files. If integration tests need a shared service that the running gate
  holds, run unit and contract tests only for that area, and say so.
- Never print env vars, `.env` files, keys, tokens or auth headers. Tests use synthetic
  secrets only.
- No deletion commands in shell (`rm`, `git rm`, `git clean`, `git reset`,
  `find -delete`).
- Do NOT run the full `make check` or `make pilot`. The orchestrator runs them.

## Done when

1. Every ID has red→green evidence. The focused unit, contract and integration files for
   the touched modules pass. `make lint` and `make contracts-check` pass.
2. One or more commits per ID, messages citing the ID. The tree is clean except for
   `microdrama/.venv`.
3. Report at
   `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix3-REPORT.md`. Per ID
   it covers: root cause, files, red/green pytest summary lines, commit hashes, and any
   conservative choice made where §E was silent.

Your final message: one line per ID, plus the report path.
