# Codex re-review round 3 (operator-approved, final) — GLM fix3 commits

Read-only. Checkout `/root/AIVORA/drama-box/.scratch/t031-review-r3` (detached at
`628fe5b`). **Scope: `git diff d971435...628fe5b`**, six commits written by GLM:

| Commit | ID | Fix |
|--------|----|-----|
| `726a56e` | CN2-1 | The ceiling total is conserved when tolerance crosses an integer boundary |
| `252a6dc` | CN2-2 | Redact every resolved credential the request carries, including the Comfy token in the create env |
| `4330780` | CN2-4 | Refuse expired dispatch at the transport boundary; timeout capped at the actual remainder |
| `e3ab087` | CN2-3 | Storage ownership opens with the POST-accept binding; janitor heals before termination |
| `8e23104` | H-1 | `acquire()` binds the pod endpoint with the real signature (from GLM's harness review) |
| `628fe5b` | H-2 | Provider-operation reconciler for UNKNOWN effects (contract §E), plus CLI `resolve` |

Out of scope: later commits by another builder, which get a separate review, and the
native harness base, which you wrote.

Read first:
- your round-2 report,
  `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-rereview-fix2.md`;
- the rulings, `.../T031-fix-round/rulings-canary-night.md`;
- for H-1/H-2: GLM's findings in `.../T031-fix-round/glm-review-harness-REPORT.md`
  (sections H-1, H-2) and `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md` §E.

## Answer

1. **CN2-1..CN2-4: CLOSED / PARTIAL / OPEN.** Re-run your round-2 probes (the Decimal
   boundary case, the unlabelled Comfy-token echo, worker death after POST-accept
   followed by janitor cleanup, and nested requests after expiry).
2. **H-1:** does the default live `acquire()` now bind correctly with the real client
   classes? Is the `hasattr` escape gone? Do the tests exercise the real signature?
3. **H-2:** is it correct against §E?
   - Ambiguous create: adopt only on positive identification. `NO_CREATE_PROVEN` only
     on real proof. Otherwise an audited operator resolution.
   - Ambiguous prompt: reconcile via history/queue by durable prompt id, and never
     resubmit blindly.
   - Holds retained until resolution. The experiment resumes cleanly. The dispatch slot
     is freed.
   - Can the operator `resolve` path be misused to release money or a pod that still
     exists?
4. Any new defect introduced by these six commits. Any test weakened, skipped, or that
   only restates the implementation.

## Constraints and output

- Read-only sandbox: no file writes, no `systemd-run`. Don't run the integration suite.
  Small in-memory probes are fine.
- **Put the full report in your final message.**
- New findings: ID `CN3-1`…, severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a
  concrete failure scenario, and a fix.
- Verdict: **ACCEPT** or **FIX-REQUIRED**. This is the final operator-approved round.
