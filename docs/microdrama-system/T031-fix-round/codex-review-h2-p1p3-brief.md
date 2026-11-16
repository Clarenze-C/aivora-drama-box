# Codex review — H-2 build P1–P3 against spec v3 (money path)

Read-only. Checkout `/root/AIVORA/drama-box/.scratch/t031-verify-h2b` (detached at
`45e4f2a`).

**Scope: `git diff 82135d4...45e4f2a`.** That is GLM's H-2 build packages P1 (`0bad31b`),
P2 (`67500b6`) and P3 (`2ec18f8`, `3a5710d`, `45e4f2a`): 13 files, about +6,250/−150.
You did not write these commits. Out of scope:
- earlier commits, including Luna's `82135d4` (GLM reviews it) and the base harness;
- P4/P5 (§6, §7), which are still being built.

## The requirement

- Spec v3: `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`.
  Your critiques built it, and v3 contains your R1–R8 and SC2 wording verbatim.
- Builder's report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-REPORT.md`.
  Read its "judgement calls" sections critically.
- Contract: `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`.

## Review

1. **Conformance per section, §3, §4, §5 and §8:** DONE / PARTIAL / MISSING, with
   `file:line`. Check especially:
   - the three-layer EffectDenied guards in RECOVERY;
   - the EXPIRED-read exception (does it open any dispatch path?);
   - `unresolved_items` completeness (U1–U6 + U3p) and its blocking scopes;
   - the first-send right (SC2-1): the original send is allowed once, and replay or
     takeover never sends;
   - the locked gate in `execute`, `_acquisition`, `_claim_sample` and dispatch;
   - CLI `resume` ordering;
   - recovery-deadline composition (R3: absolute timestamps only, shorten never
     extend), the deadline fence and token checks on control writes;
   - SC2-2 deadline scope;
   - PENDING_SUBMIT takeover;
   - upload readback with no second upload POST.
2. **Judgement calls:** for each one listed in the report, is it consistent with the
   spec and contract? If not, say what the spec requires.
3. **Tests:**
   - Do AT-0/1/2/3/4/5/10/11/13/14/15/16/17/18/19/20/23/24/25 and the §9.3 P3
     extensions prove their invariants through public entry points? (AT-10 is the
     allowed exception.)
   - Do the death tests really bypass cleanup (SIGKILL/`os._exit`)?
   - Is the fake ComfyUI tied to the pod's lifetime?
   - Were the cleanup-fixture assertions restored?
   - Has any assertion been weakened or skipped?
4. **New defects:** money, duplicate effects, lock order, secrets.

## Output

- Read-only sandbox: no writes, no `systemd-run`, no integration suite. Small
  in-memory probes are fine.
- Put the full report in your final message.
- Findings use IDs `HB-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a
  concrete failure scenario and a fix.
- Verdict: **ACCEPT** or **FIX-REQUIRED**. This is round 1 of the build-review cycle for P1–P3.
