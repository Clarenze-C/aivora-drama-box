**Verdict: APPROVE-WITH-CHANGES.** Six findings CLOSED; PC5-2 PARTIAL pending one recovery clarification. No remaining BLOCKING finding.

Reviewed v0.4 at `deb850c`; the working spec matches. `C` = [phase-C-spec.md](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md).

| Finding | Status | Verification |
|---|---|---|
| PC5-1 | **CLOSED** | §4, C:325–338; C-T4, C:777. The selected candidate’s immutable parent version **and generation** are compared against current parent authority. Explicit rerolls advance generation idempotently even when selection stays unchanged; retries do not. |
| PC5-2 | **PARTIAL** | §5, C:379–409; C-T6, C:779. Shared admission is published before submit and checked under flock by every participant; ARISA adoption is required before live use. Parent-directory mounts and submission-only time limits are explicit. The no-submission crash case needs the clarification below. |
| PC5-3 | **CLOSED** | §7, C:494–501, 540–544; §8, C:590–601. Reference-pick tuples exclude catalogue votes; voice tuples bind the current audition’s registered clip. “Other” has a tagged identity in both tuple and provider reference. |
| PC5-4 | **CLOSED** | §3, C:266–269; §4, C:319–324; C-T3/C-T14a, C:776/788. Appearance states receive three candidates, consistently across dispatch and forecast. |
| PC5-5 | **CLOSED** | CD6, C:206; §7, C:457–467; §10, C:696–698. Global refresh uses importer-run authority; shortlists preserve ranked payloads/hashes or immutable versions, and reranking creates a new version. |
| PC5-6 | **CLOSED** | §2, C:142–149, 213–218; C-T1/C-T13, C:774/787. Document identity, ownership validation, current resolution and lock keys are scoped to season or extension. |
| PC5-7 | **CLOSED** | §7, C:550–554; §13, C:759–763; C-T11, C:784. Rights enforcement and tests are assigned to their owning packages; C7 no longer requires later implementations. |

**PC6-1 — SHOULD-FIX — Explicitly resolve recovery admission after proven non-acceptance.**

§5, C:390–394 requires publication **before submit**, but says “only a reconciled terminal state” re-admits dispatch. A worker can die between publication and submit; reconciliation then returns `NOT_FOUND`. The terminal-only wording leaves that blocker’s resolution ambiguous, while §10, C:702–703 and [GenerationProvider.reconcile](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/providers.py:199) explicitly permit resubmission after `NOT_FOUND`.

**Replacement:** “Under flock, recovery admission may be cleared after reconciliation proves either terminal completion or `NOT_FOUND`—the provider never accepted the recorded operation. Running or unknown outcomes retain the blocker. Before resubmission, publish recovery admission again. C-T6 also kills a holder after admission publication but before submit, then proves safe recovery without overlapping submissions.”

Read-only verification completed. No files changed, tests run or provider calls made.