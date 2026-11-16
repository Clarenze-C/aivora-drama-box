**Verdict: FIX-REQUIRED — round 1, P1–P3.**

Reviewed `82135d4...45e4f2a`, verified HEAD `45e4f2a`: 13 files, +6,253/−154. P4/P5 and unrelated inherited defects are excluded. Retained code is discussed where P1–P3 explicitly required replacing its behavior.

This was read-only. `git diff --check` passed. I ran six small in-memory probes, with no database or provider connections. I did not run the acceptance or integration suites; the builder’s green receipts remain reported evidence.

All locations below refer to the pinned checkout.

Conformance against v3:

| Requirement | Status | Evidence |
|---|---|---|
| §3.1 explicit modes and mandatory object store | **DONE** | `experimental_world.py:1021`, `benchmark.py:192` |
| §3.1 complete effect denial at three layers | **PARTIAL** | Native composition and HTTP refusals exist, but recovery can still reserve; the transport-layer test does not establish mode denial. `experimental_world.py:1199`, `experimental_world.py:1279`; HB-11/HB-13 |
| §3.1 one world per acquisition | **PARTIAL** | Upload recovery supplies acquisition identity; ordinary slot recovery omits it, and sweep reuses one world. `benchmark_service.py:1462`, `benchmark_service.py:1495`, `benchmark_service.py:1315`; HB-3 |
| §3.2 authorization bytes and provenance | **PARTIAL** | Exact bytes are persisted and the dedicated loader verifies them. Normal recovery can bypass that loader or select the latest payload. `benchmark_service.py:244`, `experimental_world.py:870`, `experimental_world.py:1031`; HB-3 |
| §3.3 EXPIRED reads and settlement | **PARTIAL** | The HTTP exception is read-scoped and does not itself authorize POSTs. The settlement addition incorrectly zero-settles non-lease-covered renders. `experimental_world.py:933`, `comfy_jobs.py:1143`; HB-1 |
| §3.4 recovery binding | **PARTIAL** | Binding avoids `ensure_pod`, but UNKNOWN recovery skips it; the binding predicate also lacks a running-pod check. `experimental_world.py:171`, `benchmark_service.py:1687`; HB-2 |
| §4.1 U1–U6/U3p and blocking scopes | **PARTIAL** | Canonical reservation traversal and label-independent U1 are implemented. Finality and upload-retirement predicates remain incomplete. `benchmark_experiments.py:107`; HB-12 |
| §4.1 SC2-1 first-send right | **PARTIAL** | Sequential intent replay is conservative. Ownership expiry and concurrent first-send authorization are not secured at the effect boundary. `benchmark_service.py:312`, `benchmark_service.py:817`; HB-7 |
| §4.2 locked gates | **PARTIAL** | Gates exist in execute, acquisition, claims and dispatch. Reconcile still uses separate predicates to restore running state. `benchmark_service.py:229`, `benchmark_service.py:426`, `benchmark_service.py:909`, `benchmark_service.py:1499`; HB-8/HB-9 |
| §4.2 CLI recovery ordering | **PARTIAL** | Argument validation still precedes recovery, and some admission failures escape instead of returning recovered status plus blockers. `benchmark.py:130`, `benchmark_service.py:1056`; HB-10 |
| §5.1 ambiguity classification | **PARTIAL** | Original execution has separate create/upload/submit handlers. Ambiguity discovered during recovery does not enter the same durable grace lifecycle. `benchmark_service.py:765`, `benchmark_service.py:804`, `benchmark_service.py:1718`; HB-5 |
| §5.2 PENDING_SUBMIT takeover | **PARTIAL** | Token-expiry check and locked UNKNOWN transition exist; no resubmit is attempted. Fresh-client binding and public conflict reporting are incomplete. `benchmark_service.py:1666`, `comfy_jobs.py:810`; HB-2/HB-14 |
| §5.3 upload readback | **PARTIAL** | Existing intents use checksum GETs without a second upload POST. Unrecoverable intents have no completed retirement path. `experimental_world.py:739`; HB-12 |
| §5.4 deadline composition, scope and fencing | **PARTIAL** | Absolute timestamps and shortening writes exist, but effective limits, historical-deadline scope, recovery entry and fencing are incomplete. `benchmark_service.py:605`, `benchmark_service.py:1132`, `benchmark_service.py:1610`; HB-4–HB-8 |
| §8 additive DDL | **DONE structurally** | Required columns and indexes are present; existing delete/truncate/integer guards cover the changed tables. `0026_t031_benchmark_experiments.sql:28`, `:94`, `:115`. Migration execution was not rerun. |

**HB-1 — BLOCKING — EXPIRED settlement forgives non-lease-covered render costs.**

Location: [comfy_jobs.py:1143](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/rendering/comfy_jobs.py:1143).

The new EXPIRED branch always records a zero-amount, zero-unit settlement before consulting `lease_covered` or the configured price. This changes the shared canonical service, not just benchmark lease-covered prompts.

A paid render can finish after its reservation expires and have its retained liability replaced by zero, despite no pod lease carrying that cost. The in-memory probe confirmed that a 60-second, non-lease-covered attempt settles with amount `0` and units `0`.

**Fix:** apply the existing canonical settlement calculation to both ACTIVE and EXPIRED reservations. Preserve the distinction between lease-covered cost, independently charged execution and positively unused holds. Add a focused expired, non-lease-covered settlement case.

**HB-2 — BLOCKING — fresh UNKNOWN recovery never binds its client.**

Location: [benchmark_service.py:1687](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1687).

Binding runs only when the operation is **not** UNKNOWN. UNKNOWN operations—including PENDING_SUBMIT just converted on takeover—go directly to `reconcile_unknown`.

With a fresh production world, the endpoint is unbound. The deterministic client-ID lookup raises `EffectDenied`; the tolerant handler swallows it and leaves the accepted prompt unrecovered. The probe confirmed lookup without any binding call.

The binding implementation at `experimental_world.py:212` also returns BOUND for an endpoint-bearing pod without checking that it is running.

**Fix:** bind the owning acquisition before both UNKNOWN lookup and known-ID polling. Enforce the §3.4 pod-state predicate and handle the returned binding result explicitly. Exercise AT-1 and AT-15 with fresh real clients.

**HB-3 — BLOCKING — normal recovery bypasses acquisition-bound provenance.**

Locations: [benchmark_service.py:1495](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1495), [experimental_world.py:1031](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/experimental_world.py:1031), `benchmark_service.py:1315`.

Slot recovery constructs its world without `acquisition_id`. The fallback selects the latest authorization payload and latest acquisition quote, without verifying stored source bytes. Supplied authorization/quote arguments also bypass durable loading, even when an acquisition ID is available.

Sweep retains the first constructed CLEANUP world for later acquisitions. Cleanup still depends on authorization namespace, account, credentials and quote configuration, even without Comfy rebinding.

With acquisitions under different authorizations, recovery can use the wrong namespace or credentials and fail ownership checks. The normal path also avoids the byte-provenance verification that AT-23 tests directly.

**Fix:** derive the acquisition from the sample/lease being recovered; always load its recorded authorization and quote in RECOVERY/CLEANUP. Construct a separate world for each acquisition. New-generation arguments must not replace recovery provenance.

**HB-4 — BLOCKING — a historical grace deadline blocks later healthy work.**

Location: [benchmark_service.py:1623](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1623), called at `:1701`.

`_recovery_request_bound` applies any persisted deadline, including while polling healthy SUBMITTED/RUNNING work after an earlier episode recovered successfully.

After that historical deadline passes, the real transport refuses the GET. The exception is swallowed, U3p remains, and admission stays blocked. Because U3p is not an ambiguity for the U2 deadline predicate, this can stall without deadline cleanup.

The probe reproduced the refused healthy poll. AT-18b misses it because its ordinary fake client ignores the deadline context.

**Fix:** apply the grace bound only while the acquisition has an unresolved recovery episode. Preserve the historical timestamp for a later ambiguity, while enforcing ordinary execution limits independently.

**HB-5 — BLOCKING — takeover can discover ambiguity without ever persisting grace.**

Location: [benchmark_service.py:1666](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1666), especially `:1685` and `:1718`.

Takeover converts PENDING_SUBMIT to UNKNOWN, but does not enter grace. Likewise, a recovery poll that discovers uncertainty merely returns through the exception handler.

If the original worker dies before `_mark_submit_ambiguity`, no recovery deadline exists. Fresh resumes then retain the blocking operation without establishing the required bounded recovery episode. Public `reconcile` also does not start cleanup when an existing recovery deadline is exhausted.

**Fix:** make recovery-discovered submit/poll ambiguity enter the same durable classification and grace path before recovery proceeds. Reuse or shorten existing deadlines, and start cleanup at exhaustion despite intermediate read failures.

**HB-6 — BLOCKING — R3’s effective deadline calculation is incomplete.**

Location: [benchmark_service.py:627](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:627).

The aggregate candidate is:

`now + max(plan_gpu_limit − gpu_ms, 0)`

It omits reserved shutdown GPU time and the tighter accepted authorization limit. The hard-stop candidate similarly uses the experiment’s deadline alone. Recovery and sweep do not recompute this bound when newly discovered liability reduces the allowance.

The probe with 50 seconds of GPU allowance remaining and a 60-second shutdown allowance persisted another 50 seconds of grace, rather than immediate exhaustion.

**Fix:** calculate the earliest absolute timestamp from the acquisition’s effective authorization, all durable—including reopened—windows and reserved shutdown time. Re-evaluate under the required locks when liability changes; persist only shortening updates. AT-18 must independently make each limit decisive.

**HB-7 — BLOCKING — the dispatch gate does not secure the exclusive first-send right.**

Locations: [benchmark_service.py:312](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:312), `:817`; `experimental_world.py:1252`.

The coordination check compares token values but never checks token expiry. The probe confirmed acceptance of matching tokens whose ownership lease had expired.

The gate also commits before staging/submission. Lower HTTP guards do not validate coordinator ownership. A paused original caller can overlap a takeover after both have passed their respective gates and operation-existence checks. Canonical `begin` can return the same existing PENDING_SUBMIT operation, and `_submit_bound_graph` treats that state as dispatchable for either caller.

Thus intent-before-send supports sequential replay safety, but does not establish the exclusive send right claimed in P2 judgement call 4.

**Fix:** check token validity, including expiry, in first-send authorization and atomically distinguish creation of an intent from replay of it. Only the original authorized invocation may consume that right. Add a barrier-driven overlap/takeover test at the pre-begin and pre-POST boundaries.

**HB-8 — BLOCKING — a new coordinator transaction reverses the fence’s lock order.**

Location: [benchmark_service.py:723](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:723).

Acquisition coordination locks D first, then updates A. `_deadline_fence` locks E → A → D.

A worker can hold D and wait for A while sweep holds A and waits for D. PostgreSQL must abort one transaction, potentially interrupting deadline cleanup.

The token predicates are also incomplete across control writes: `_observe` checks only D, the ACTIVE update checks only A, and ambiguity handlers do not apply the matching-token predicate.

**Fix:** use the shared order for these newly modified transactions and check the required matching ownership within each control-write transaction. P4 may supply shared helpers, but the P3 fence is not complete until these callers use them.

**HB-9 — BLOCKING — reconcile can restore running state while canonical blockers remain.**

Location: [benchmark_service.py:1499](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1499).

The NEEDS_RECONCILIATION → running transition still checks acquisition labels, slot state and open uploads separately. It does not evaluate `unresolved_items` under the full gate locks.

For example, U5 can remain after late adoption while those separate conditions are clear. The public-reconcile probe confirmed a `SCREEN_RUNNING` write with U5 present.

**Fix:** predicate this transition on zero relevant canonical blockers through the common repository function under the required lock order. Keep reconcile as the sole transition owner, but make its transition satisfy the gate.

**HB-10 — BLOCKING — CLI resume is not fully recovery-first.**

Locations: [benchmark.py:130](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark.py:130), [benchmark_service.py:1056](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1056).

Authorization and quote files are loaded before recovery. Most normal-resume errors are softened, but `--cleanup-only` disables that soft handling: an invalid, irrelevant generation document prevents sweep entirely.

After recovery, `_admission_blockers` checks presence and flags rather than current authorization/quote/rights eligibility. A well-formed expired quote passes that stage, then `execute` raises `EffectDenied`; resume catches only `AdmissionBlocked`. The CLI returns an error instead of recovered status plus an admission blocker.

**Fix:** complete durable recovery before loading new-generation documents. Then perform admission validation and report refusal on the recovered status. Cleanup-only resume should not validate irrelevant generation inputs.

**HB-11 — BLOCKING — RECOVERY/CLEANUP can still create non-cleanup reservations.**

Locations: [experimental_world.py:1279](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/experimental_world.py:1279), [benchmark_experiments.py:461](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/rendering/benchmark_experiments.py:461).

The composed recovery world receives an unrestricted `ExperimentBudgetService`. Neither `reserve` nor `reserve_linked` knows the world mode. A healthy running experiment can therefore acquire a new non-cleanup hold through the recovery world’s budget or canonical service methods.

The native `current()` refusal does not protect those service entry points. Similarly, calling `ensure_pod` in recovery creates canonical create-intent state before refusal, potentially manufacturing U1.

**Fix:** enforce mode restrictions at composition/service boundaries, including non-cleanup reservations and create-intent admission, while preserving canonical cleanup grants. Test with otherwise valid ownership and reservation scopes; an unrelated unbound-client refusal is insufficient.

**HB-12 — BLOCKING — unresolved-item completeness does not match the required finality rules.**

Location: [benchmark_experiments.py:139](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/rendering/benchmark_experiments.py:139), especially `:154`, `:203`, `:223`, `:295`, `:314`.

Specific gaps:

- **U2/R1:** NO_CREATE_PROVEN storage debt is detected only while the reservation is ACTIVE. An EXPIRED, unfinalized original storage hold is omitted.
- **U5:** verified termination plus closed ownership clears the item without checking billing finality.
- **U3u:** every INTENT/UNKNOWN row blocks indefinitely, including after cleanup. There is no predicate for a durably fenced and finalized upload episode.
- **U6:** a claimed sample with a job but no operation is omitted, despite the specified job-or-operation materialization definition.
- The U3u scope filter also needs reconciliation with R2’s experiment-wide prohibition on new generation while provider uncertainty remains.

For an upload accepted ambiguously but never readable, sweep can remove the source while U3u remains forever. `resolve_sample` refuses because no prompt operation exists.

**Fix:** derive these predicates from complete canonical finality. Provide the specified fenced failure/finalization path for unrecoverable uploads, retaining liability until that path completes. Cover EXPIRED storage and billing-pending contradictions explicitly.

**HB-13 — BLOCKING — acceptance fixtures hide the production failures they are intended to exclude.**

Locations: [test_t031_h2b_p1_modes.py:166](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/tests/unit/rendering/test_t031_h2b_p1_modes.py:166), [test_t031_h2b_p3_ambiguity.py:809](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/tests/unit/rendering/test_t031_h2b_p3_ambiguity.py:809), [test_benchmark_experiments.py:288](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/tests/unit/rendering/test_benchmark_experiments.py:288).

Most steps create a fresh service while reusing the same adapter, client and server. Fake Comfy availability is independent of pod lifetime. AT-19 expressly recovers output from that fake after cleanup.

The cleanup fixture treats a verified stop as VERIFIED storage cleanup and synthesizes BILLED/storage-final status. That does not meet §9.1’s verified termination and canonical billing requirement.

AT-4’s third-layer probe constructs an unbound client with permissive guards; it proves an unbound refusal, not independent RECOVERY-mode transport denial.

**Fix:** use fresh composed worlds and real clients at the required boundaries, connect fake server availability to pod lifetime, require canonical cleanup/finality evidence, and isolate each guard with otherwise valid inputs.

**HB-14 — SHOULD-FIX — multiple-prompt conflict is hidden by the public reconciler.**

Location: [benchmark_service.py:1718](/root/AIVORA/drama-box/.scratch/t031-verify-h2b/microdrama/src/microdrama/pipeline/benchmark_service.py:1718).

The finder correctly rejects multiple distinct prompt IDs, but reconcile catches that `Conflict` and returns no conflict diagnostic. Operators see an ordinary unresolved operation, indistinguishable from a history miss. AT-25 checks only UNKNOWN/null external ID.

**Fix:** retain UNKNOWN and exposure, while returning or durably recording a bounded, nonsecret conflict reason. Assert that diagnostic through the public entry point.

The acceptance-test evidence is as follows. “Partial” means the named scenario has useful assertions but does not prove the full v3 invariant.

| AT | Assessment | Test location and limitation |
|---|---|---|
| AT-0 | **PARTIAL** | P2 `:334`: public resume covers healthy sample progression and sequential replay. Uses the shared fake adapter; no native upload sequence or concurrent send-right proof. |
| AT-1 | **PARTIAL** | P3 `:103`: accepted timeout recovery works through the memory fake, masking fresh UNKNOWN binding failure. |
| AT-2 | **PARTIAL** | P3 `:877`: UNKNOWN/exposure/failure assertions exist. Stop-or-terminate evidence and synthetic billing do not prove required closure. |
| AT-3 | **PARTIAL** | P3 `:1056`, `:1115`: real `os._exit`; child drives service methods, not CLI. Restart CLI runs in the parent process with an injected fake adapter. |
| AT-4 | **PARTIAL** | P1 `:795`, `:844`: useful refusals, but invalid/unbound scopes obscure the denying layer. CLI recovery substitutes an offline adapter. No non-cleanup-reservation denial test. |
| AT-5 | **PARTIAL** | P2 `:442`: public resume checks admission waits for finalization, but finality is controlled by an adapter flag rather than canonical billing. |
| AT-10 | **PARTIAL** | P2 `:563`: permitted private-helper exception used; kind coverage is useful. No insertion/transition race proof or full first-send extension. |
| AT-11 | **Covered narrowly** | P2 `:747`: public resume proves durable PASS wins over supplied `screen`. This is sound phase-selection evidence. |
| AT-13 | **PARTIAL** | P2 `:802`, `:940`: real process exit bypasses cleanup and leaves canonical U1 without the label. It is not the required subprocess CLI death/restart flow. |
| AT-14 | **PARTIAL** | P2 `:1139`, `:1193`: public resume covers ACTIVE adoption and expired unused-hold closure, with reused world objects. |
| AT-15 | **PARTIAL** | P3 `:225`, `:259`: seeded pending states exercise takeover through public reconcile. Fake lookup masks binding; valid-coordinator/non-preemption coverage is incomplete. |
| AT-16 | **PARTIAL** | P3 `:294`, `:328`: reservation traversal and U3p admission refusal are exercised. Recovery uses the memory fake. |
| AT-17 | **PARTIAL** | P3 `:1799`: strongest composition test—real Pika client, native inputs, scripted transports, no second upload. Missing lifetime coupling and unrecoverable-upload closure. |
| AT-18 | **PARTIAL** | P3 `:477`: expected deadline copies the implementation formula; no independent winning-limit matrix. “Slow request” consults the timeout function without exercising a slow real transport request. Cleanup is invoked well after the deadline. |
| AT-19 | **PARTIAL** | P3 `:693`: useful parked-thread fence/projection check. No death during grace; subsequent recovery relies on a fake server surviving cleanup. |
| AT-20 | **PARTIAL** | P1 `:502`: direct helper checks plus operator settlement; does not prove real expired output/history recovery. P3 `:1909` does exercise real expired input readback without a prompt operation. |
| AT-23 | **PARTIAL** | P1 `:323`: exact stored bytes and dedicated loaders are checked. Ordinary recovery-world construction is bypassed. |
| AT-24 | **Covered narrowly** | P1 `:282`: public service and CLI acquisition-less recovery make no world/effect and need no quote. |
| AT-25 | **PARTIAL** | P3 `:372`: rejects first-match adoption, but uses the fake finder and never asserts public conflict reporting. |

For the §9.3 P3 extensions:

| Extension | Assessment |
|---|---|
| Real first create/upload/prompt through guards | AT-17 supplies useful native composition coverage, but AT-0/10 do not establish exclusive first-send behavior across overlapping ownership. |
| U3p missing linkage | Present in AT-16/16b, with the client limitations above. |
| Acquisition-scoped upload blocking | Present for the active acquisition; retirement and global uncertainty scopes remain incomplete. |
| EXPIRED input readback without operation | Present through the real Pika client in AT-17d. |
| Wrong owner/mode/POST refusal | Present at request boundaries; independent three-layer mode refusal remains unproven. |
| Successful recovery beyond historical deadline | Test exists, but its fake client hides HB-4. |
| Fence valid coordinator and reject stale control writes | Parked-thread coverage exists for projection; not every control write or send authorization is covered. |

The death injections **do bypass cleanup**: P2 `:822` and P3 `:1052` use `os._exit(86)`. They are not SIGKILL injections, and neither implements the complete subprocess CLI death/restart requirement.

The fake ComfyUI is **not tied to pod lifetime**. The two cleanup assertions were restored for pod-bound cleanup, but the fixture still accepts stop evidence and fabricates final billing/storage readiness.

I found no added `skip`/`xfail` in these AT files and no direct `_advance` invocation in the new tests. The changed operator-failure expectations match fail-fast policy. The principal problem is insufficient assertions and substitutes that permit behavior forbidden by the spec, rather than removal of existing assertions.

Every listed judgement call is assessed below; numbering follows the builder’s report.

| P1 judgement | Assessment |
|---|---|
| 1. Deadline columns excluded from set-once | **Partly consistent.** Deadline shortening needs an exception. That does not justify allowing `recovery_started_at` to change; the first start must remain fixed. |
| 2. Payload equals parsing accepted bytes | **Consistent.** Correct interpretation of §3.2, including noncanonical formatting. |
| 3. One CLEANUP world per sweep | **Inconsistent.** Cleanup remains authorization/account/namespace/quote scoped. §3.1 requires per-acquisition composition; HB-3. |
| 4. Latest authorization fallback | **Not acceptable for production recovery.** A test helper’s synthetic row cannot justify timestamp-selected provenance; HB-3. |
| 5. Only execute hard-refuses CLI flags | **Intent consistent; implementation incomplete.** Resume must recover before validation and return admission blockers; HB-10. Default-world recovery behavior also needs genuine flag-boundary coverage. |
| 6. `ensure_pod` commits intent before refusal | **Inconsistent with complete composition denial.** It can manufacture U1 and consume the original create right despite sending nothing. Deny before entering that path; HB-11. |
| 7. AT-20 releases unused exposure after settlement | **Consistent for lease-covered prompts.** It does not justify zero settlement for every EXPIRED render; HB-1. |
| 8. Deadline blocker independent of seal | **Consistent.** Reporting both blockers is reasonable. |

| P2 judgement | Assessment |
|---|---|
| 1. Live no-create lease contributes U2 | **Consistent.** Canonical close/finalization remains owed. |
| 2. Reconcile polls U3p | **Consistent and necessary.** Fresh-world binding and deadline scope must also work; HB-2/HB-4. |
| 3. Execute raises; resume returns blockers | **Consistent API choice.** Resume does not yet return all required admission failures as blockers; HB-10. |
| 4. No explicit first-send ownership plumbing needed | **Inconsistent.** Intent-before-send alone does not arbitrate overlapping original/takeover callers; HB-7. |
| 5. U6/U2 scope exceptions | **Consistent in principle.** U6 permits local materialization; U2 does not prohibit claims on a healthy acquisition. Neither excuses incomplete item predicates. |
| 6. Takeover waits for coordinator expiry | **Consistent.** Ordinary recovery must not preempt valid ownership; R3 is the explicit deadline exception. |
| 7. Expired-unused settlement on benchmark budget service | **Acceptable location.** It still requires positive unused-effect proof and canonical transaction discipline. |
| 8. Two assertions constitute restored fixture strictness | **Insufficient against v3.** §9.1 additionally requires verified termination and canonical billing readiness; HB-13. |
| 9. Parent loads durable authorization/time and uses random IDs | **Consistent harness choice.** It does not establish that ordinary recovery selects and verifies the correct acquisition provenance. |
| 10. Named item blockers | **Consistent.** Useful operator diagnostics. |

| P3 part 1 judgement | Assessment |
|---|---|
| 1. Unclassified ambiguity treated as create ambiguity | **Only conservative about stopping work.** It is not generally §5.1-conformant: classification must follow the actual canonical effect, rather than invent create ambiguity. |
| 2. Operator failure fails experiment; revised AT-20 projection | **Consistent.** Fail-fast and structural canonical exposure assertions are appropriate. |
| 3. Binding before recovery poll is best-effort | **Partly consistent.** Failed binding may leave work blocked, but UNKNOWN recovery currently does not attempt it at all; HB-2. |

| P3 part 2a judgement | Assessment |
|---|---|
| 1. Fence refusal uses AdmissionBlocked | **Consistent.** It avoids spuriously failing the experiment. |
| 2. No fence-marker column | **Acceptable design if all predicates enforce it.** Current ownership/control-write checks do not complete that design; HB-7/HB-8. |
| 3. Fake timeout probe plus existing transport tests | **Insufficient.** Separate tests do not prove correct composition or SC2-2 scope; HB-4/HB-6/HB-13. |
| 4. Parked thread models returning coordinator | **Valid for that race.** It does not replace death-during-grace evidence, and its post-cleanup recovery is invalid without pod lifetime coupling. |
| 5. Stop evidence substitutes for termination | **Inconsistent.** The spec explicitly requires termination and canonical finality. |
| 6. Row equality proves “no state write” | **Partial evidence.** It proves equality of selected rows, not absence of writes or duplicate financial/audit records. |
| 7. Correct screen IDs | **Consistent.** |

| P3 part 2b judgement | Assessment |
|---|---|
| 1. Child continues through resume | **Consistent.** U3p recovery belongs before fresh admission. |
| 2. SUBMITTED or RUNNING accepted at death | **Consistent.** Both satisfy the stated mid-poll window. |
| 3. Parent reconstructs provider pod from durable identity | **Reasonable simulation technique.** Lifetime and fresh-process requirements still need coverage. |
| 4. Every upload times out after acceptance | **Consistent and useful.** Strong sequential per-intent no-repost evidence. |
| 5. Patch policy to return a real disabled preset record | **Reasonable focused fixture.** It does not establish eligibility-policy correctness. |
| 6. Captured runtime schema fixture | **Consistent offline evidence.** No live qualification follows from it. |
| 7. Persist PromptManifest at construction point | **Reasonable.** It supplies the canonical document required by submit. |
| 8. Existence check instead of ON CONFLICT | **Acceptable on the serialized initial-claim path.** The justification should be that transaction’s serialization, not a general assumption that coordinator ownership can never overlap. |

No new secret-disclosure defect was established in this scoped diff. The proven money regression is HB-1; duplicate-effect authorization, recovery limits and lock ordering remain unresolved as detailed above. Deferred P4/P5 resolution and terminal-finalization work was not graded as completed here.

