# Stage 9 — Implementation Readiness Test (DetailedRange gates)

- Reviewers (fresh Agents, no parent context, all on DetailedRange = lines 186-209, full document read for context):
  - `egm-implementation-readiness` — standard: implementation-readiness-standard.md
  - `egm-codebase-details` — standard: implementation-readiness-standard.md (technical accuracy + code reuse lens)
  - `egm-style` — persona rubric only
- Target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (209 lines)
- Date: 2026-11-13

---

## A. Implementation Readiness reviewer (`egm-implementation-readiness`)

EGM Implementation Readiness review — Mode: REVIEW
Target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (read fully, 209 lines)
DetailedRange audited: lines 186-209 (§6 Build packages, §7 Operator steps, §8 Open questions)
Standard: /root/.local/share/egm/403d888/resources/document_standards/implementation-readiness-standard.md (Zero-Decision Rule, Phasing & Checkpoints)
Base verified against: /root/AIVORA/drama-box/.scratch/t031-fix3-worktree (feat/t031-fix3 @ 104b26b)

VERDICT: NOT READY to hand to a builder. One Blocker (an unresolved design decision governing two of the five build packages, with an unspecifiable fallback) and six Majors (runbook incompleteness, two dangling/unsatisfiable sequencing references, three Zero-Decision violations that land directly on §6's packages). The Phasing & Checkpoints requirement is partially met (ordered one-commit packages, tests first, offline acceptance tests in §5); the Target Scope requirement is not met at §6 altitude.

FINDINGS

1. Severity: Blocker
   Affected Scope: §8 Q1 (lines 204-205) governing §6 packages R5c and R5d (line 188); fallback sketch §3 lines 106-110; scope conflict with §2 lines 31-32.
   Finding & Guidance: The central R5c design (predicted schema "P" vs capture pod "C") is still an open question while §6 simultaneously hands R5c ("prediction tool + seal evidence") and R5d (whose `author` writes "the R5c prediction" into seal.json) to the builder in fixed order. Under the Zero-Decision Rule the plan fails as-is: if the critique upholds P, §3 R5c is adequately specified; if it does not, C exists only as three sketch bullets — C "needs a pre-seal authorization and new experiment states, which likely means a migration," which collides with §2's hard "No new migration" scope (builder stops at a red test), and C has no file list, no state machine, no tool changes, and no acceptance tests. Nothing in §6 marks R5c/R5d as conditional. Guidance: do not dispatch R5c/R5d until the critique ruling is folded back into §3/§6 as the single answer; if C remains live, spec it to the same depth as P (files, states, migration-exception ruling, tests) or descope it explicitly.

2. Severity: Major
   Affected Scope: §7 lines 192-200 (entire operator runbook).
   Finding & Guidance: The runbook is materially incomplete, and followed literally it fails at step 5. Between step 4 (sign) and step 5 (`execute --phase screen`) the enforced pipeline (verified in the factmap, /root/AIVORA/drama-box/docs/microdrama-system/t031-benchmark/paid-run-factmap.md §3, order of operations) requires: `tools/canary_db.py up` (dedicated loopback paid DB), `t031_prepare_run.py register`, `author`, `benchmark prepare --plan`, `benchmark seal --manifest`, `t031_prepare_run.py quote` (consuming the step-3 console quote), and `verify`/preflight — none appear in §7. `execute` refuses unless the experiment is prepared and sealed in the DB and hard-requires env gates (MICRODRAMA_EXECUTION_MODE=PAID_BENCHMARK, MICRODRAMA_PAID_REQUESTS_ENABLED=true, MICRODRAMA_CLOUD_RESOURCES_ENABLED=true, loopback MICRODRAMA_DATABASE_URL, absolute MICRODRAMA_OBJECT_STORE_ROOT, --authorization + --authorization-sha256 + --quote). All post-screen steps are also absent: record-screening (human Pass A), `execute --phase full`, sweep/cleanup verification, export, `t031_results.py`, invoice finality. "The orchestrator prepares every file and the exact commands" (line 200) is a blanket deferral, not a runbook. Guidance: enumerate every command with actor, order, working dir, env, and the DB it targets; mark which steps the operator runs vs the orchestrator.

3. Severity: Major
   Affected Scope: §7 step 1 (line 194).
   Finding & Guidance: "Push the new image (same two commands; new digest)" is a dangling reference. The pika-h3-flex push commands are recorded nowhere: /root/AIVORA/drama-box/.scratch/t031-fix3-worktree/microdrama/deployment/pika-h3-flex/BUILD_EVIDENCE.md (lines 85-88) records only that the operator pushed on 12 Nov with a `gh` token (write:packages) and made the package public — not the commands. The only in-repo documented push commands are for a different image (microdrama/deployment/canary-image/README.md lines 45-58). Guidance: write the exact commands (registry login, tag/push, and digest capture for the seal's image_ref) into §7 or the pika-h3-flex README before handoff.

4. Severity: Major
   Affected Scope: §6 R5c (line 188) vs §7 step 1 (line 194); §3 validate_for condition 2 (lines 96-99).
   Finding & Guidance: The image-digest binding is unsatisfiable as scheduled. validate_for must hold "the seal's image_ref digest equal to the capture record's," and the seal pins the pushed registry digest. But the prediction tool runs offline inside the locally built image at build time — before the operator's push — and the local image ID is not the registry manifest digest (proven in-tree by the 12 Nov evidence: local ID abd32e9e… vs pinned e4ccc004…, BUILD_EVIDENCE.md lines 80-88). No step in §6 or §7 schedules the prediction capture against the pulled, pushed image (post-push, pre-author), so either the capture record carries the wrong digest or the seal authoring edits it after the fact (breaking the "idempotent, refuses drift" contract of R5d). Guidance: schedule the prediction capture after §7 step 1 (run schema_smoke.py inside the pulled @sha256: image) and state explicitly which digest value the capture record carries.

5. Severity: Major
   Affected Scope: §6 R5b package (line 188); root text §3 lines 75-76.
   Finding & Guidance: The R5b package delegates a data-placement design decision to the builder: "Timings are recorded durably in existing JSON columns only (the builder names them; if none fit without a migration, stop and report)." Choosing which durable columns hold cold_start_ms/provision_ms/full_job_ms/sampler_ms (benchmark_experiments vs benchmark_acquisitions intent/attestation JSON vs benchmark_samples output JSON) shapes the export and the results mapping built in R5e; the stop-and-report clause bounds but does not eliminate the choice. This violates the Zero-Decision Rule. Guidance: name the exact tables and JSON keys for each timing field in the plan.

6. Severity: Major
   Affected Scope: §6 R5a package (line 188); root text §3 lines 50-52; microdrama/src/microdrama/rendering/runpod_transport.py:340-391.
   Finding & Guidance: The transport change is under-specified for a first-attempt build. `create_pod` must add MICRODRAMA_PROVISION_MODELS=1 "only for the Pika benchmark world" and the flag "is part of the attested create intent," but create_pod (verified: env payload built at runpod_transport.py:391) has no world notion, and the plan does not say which type carries the flag (PodCreateRequest? RunpodQuoteAttestation? the durable acquisition intent JSON?), its default for non-Pika worlds, or which site refuses "a create without it for this world." That is API design left to the implementer. Guidance: name the field, its owning model, its default, and the refusal check.

7. Severity: Major
   Affected Scope: §7 step 2 (line 195) with §3 R5d (lines 131-132).
   Finding & Guidance: The Comfy gateway token file has no pinned path and the new credref ref name is unnamed. `register` must write the credential_refs locator; the paid-path FILE resolver later lstats exactly that path (0600, non-symlink, owner-checked). The existing RunPod key is documented (/root/.secrets/drama-box/runpod-canary.key per T031-authorization-packet.md:171) but the new token file is not, so the builder's `register` row and the operator's step-2 file can diverge and only collide at execute. Guidance: pin the credref ref name and absolute file path in both §3 R5d and §7.

8. Severity: Nit
   Affected Scope: §6 lines 186-190.
   Finding & Guidance: No per-package checkpoint definition: the packages never map §5's RR-T1..RR-T11 to packages (RR-T1..4→R5a, RR-T5/6→R5b, RR-T7/8→R5c, RR-T9→R5d, RR-T10→R5e, RR-T11→all is only inferable), nor state the per-commit gate (e.g., make check green). Also "the documented flock/CPUQuota command" is uncited: it lives at microdrama/deployment/pika-h3-flex/BUILD_EVIDENCE.md lines 39-47, and its paths (.scratch/runtime-image/context, verify.sh) belong to the superseded t031-native worktree — the builder must adapt build.sh's required dedicated context dir to the fix3 worktree. Cite the file and adapted paths.

9. Severity: Nit
   Affected Scope: §6 R5a package (line 188) with §3 R5a (lines 38-45).
   Finding & Guidance: R5a's implied file list is incomplete: adding start.sh requires a Dockerfile COPY plus ENTRYPOINT change, a build.sh staging update (build.sh line 8 stages a fixed file set), and updating the recipe guard test microdrama/tests/unit/rendering/test_pika_image_recipe.py — introduced by commit 304ea77 exactly because a COPY source was not staged. Neither §3 R5a nor §6 lists build.sh or the guard test. Tests-first would catch it, but the standard expects explicit target scope.

10. Severity: Nit
    Affected Scope: §8 Q2 (lines 206-207) and Q3 (lines 208-209).
    Finding & Guidance: Both questions leave build-package details nominally open but carry documented recommendations ("no" for partial-download deletion — provision.py promotes only SHA-verified files, verified in the factmap §5; 25 min boot_budget, already §3's default in runtime_profile). Before handoff, fold the rulings into §3 and remove the questions so the builder reads exactly one answer per detail.

CONTEXT CLAIMS VERIFIED (no finding): all document-relative support files exist under /root/AIVORA/drama-box/docs/microdrama-system/t031-benchmark/ (shots.csv, trials.csv, results-template.csv, references-r1/r2-manifest.jsonl, voices-manifest.json, paid-run-factmap.md); benchmark_service.py:1195 is `world.stage_inputs` and pipeline/experimental_world.py:705-717 is stage() with attest_schema() before uploads, matching G2/G3's cites; runpod_transport.py:391 sets env MICRODRAMA_COMFY_TOKEN at create; current Dockerfile ENTRYPOINT (line 24) is the gateway+ComfyUI inline sh that R5a replaces; make check and make pilot targets exist (microdrama/Makefile lines 56, 62).

---

## B. Codebase Details reviewer (`egm-codebase-details`)

REVIEW audit of /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md, DetailedRange lines 186-209 (§6 Build packages, §7 Operator steps, §8 Open questions), against the Implementation Readiness Standard, with the technical-accuracy and code-reuse lens. Standard and full document were read. All code verified against the pinned base worktree /root/AIVORA/drama-box/.scratch/t031-fix3-worktree (@ 104b26b).

FINDINGS

1. Severity: [Major]
   Affected Scope: §6 lines 186-190 (with the file lists scattered in §3, lines 36-155).
   Discrepancy: The five build packages name no Create/Modify/Delete file dispositions. The plan does mention new files (start.sh in the image, tools/t031_schema_predict.py, tools/t031_prepare_run.py, tools/t031_results.py) and modified touch points (gateway endpoint, runpod_transport.create_pod env, benchmark_authorization validate_for, export), but never as a consolidated target scope, and several touch points name no module at all: no module is given for the new world step wait_ready (world-step code lives in src/microdrama/rendering/experimental_world.py), the timings targets are explicitly deferred ("existing JSON columns only (the builder names them; if none fit ... stop and report", line 76-77), and no file is named for R5c's "durable recording of that live capture" (line 104) or for the export changes (line 80). Under the standard's Target Scope requirement this leaves the implementer to discover which files change; per the canonical rule this is reported once, not per path. The stop-and-report guard on the JSON columns is a bounded deferral and acceptable, but wait_ready's host module and the live-capture recording location are unqualified design choices.

2. Severity: [Major]
   Affected Scope: §7 step 1, line 194 ("Push the new image (same two commands; new digest)").
   Discrepancy: Non-resolvable reference. No document anywhere records a two-command push procedure for this image. microdrama/deployment/pika-h3-flex/README.md documents no push commands at all ("Never push without separate authorization", line 18); BUILD_EVIDENCE.md:85-88 records only the outcome of the 12 Nov push (operator's own shell, gh token with write:packages, package made public, pinned digest e4ccc004...), not the commands; the only documented push procedures in the repo (microdrama/deployment/canary-image/README.md:45-58) are 3-4 command blocks (login/tag/push[/inspect]) for a different image and repo (drama-canary). A fresh operator or session cannot reconstruct "the same two commands" from the repository. Mitigated by line 200 ("The orchestrator prepares every file and the exact commands"), but on a money path whose digest the seal pins, the two commands should be inlined in §7 rather than referenced to a procedure that does not exist.

3. Severity: [Major]
   Affected Scope: §7 lines 192-200, the operator step sequence.
   Discrepancy: The sequence is not executable in the printed order. Step 4 "Sign the authorization" requires the authorization draft, which binds sealed_sha256; the seal's image_ref must match ^...@sha256:<64hex>$ (src/microdrama/pipeline/benchmark_authorization.py:29, IMAGE_PATTERN) and must be the pushed registry manifest digest — which only exists after step 1's push. The codebase proves the two digests differ pre/post push: BUILD_EVIDENCE.md:80-88 records local image ID abd32e9e... versus pinned registry digest e4ccc004..., and create refuses any image not pinned by the attestation (src/microdrama/rendering/runpod_transport.py:349-350). R5c's proposed validate_for check (seal image_ref digest == capture record digest, line 97-98) makes the R5c prediction and the R5d author/verify steps necessarily interleave between operator steps 1 and 4. §3 R5a acknowledges the dependency ("Rebuild and the operator's re-push give a new image digest; the seal pins it", line 58-60), but the §7 checklist hides it, and line 200's "The orchestrator prepares every file" reads as if everything can be prepared before the operator starts. One sentence placing "orchestrator: predict, author, verify (R5d) after your push, before you sign" into the sequence closes it.

4. Severity: [Nit]
   Affected Scope: §7 step 5, line 198 ("Run `benchmark execute --phase screen` from your own shell").
   Discrepancy: No `benchmark` executable or console-script entry point exists (no [project.scripts] in microdrama/pyproject.toml; the factmap confirms no Makefile target either). The real surface is `PYTHONPATH=src .venv/bin/python -m microdrama.pipeline.benchmark execute` with required `--experiment-id --authorization --authorization-sha256 --quote` (src/microdrama/pipeline/benchmark.py:29-68) and hard env gates (MICRODRAMA_EXECUTION_MODE=PAID_BENCHMARK, MICRODRAMA_PAID_REQUESTS_ENABLED=true, MICRODRAMA_CLOUD_RESOURCES_ENABLED=true, loopback MICRODRAMA_DATABASE_URL, absolute MICRODRAMA_OBJECT_STORE_ROOT). The shorthand is used consistently across the doc and is mitigated by line 200, but the operator-facing step omits that their shell must carry those gates and flags; naming them (or their export lines) removes the last guess.

5. Severity: [Nit]
   Affected Scope: §8 open question 2, lines 206-207 ("Should start.sh delete partial downloads on failure? Recommendation: no. provision.py already promotes only verified files...").
   Discrepancy: The question's premise is moot in the code: provision.py already deletes every partial download itself — each download goes to a `.unverified-*` tempfile unlinked in a `finally` block (microdrama/deployment/pika-h3-flex/provision.py:51 and 67-68), so after a PROVISION_FAILED run only previously verified complete files remain on disk. The stated rationale ("promotes only verified files", true per provision.py:13-20,64-66: size+SHA256 precedes atomic os.replace) understates the existing behavior; there is no code path under which partial downloads linger for start.sh to clean. The recommendation ("no") still matches the code, so this is accuracy-of-rationale only; the "container disk is discarded at terminate" clause is consistent with persistent_volume_gb=0 (runpod_transport.py:380-381 mounts a volume only when volume_gb > 0).

VERIFIED ACCURATE (no finding): §6's "documented flock/CPUQuota command" resolves to pika-h3-flex/README.md:13-16 and BUILD_EVIDENCE.md:39-47; §6's "No push" matches README:18 and the 12 Nov record; §7 step 2's 0600 read -rs file matches the FILE-only credential resolver contract (src/microdrama/pipeline/canary.py:108-178: real file, never symlink, owner-only, 0600/0400), with operator precedent in T031-authorization-packet.md:171; §7 step 3's <=2 h window and exact "NVIDIA A40" catalog ID (bare "A40" refused) match benchmark_authorization.py:306-311; §8 Q3's "about 42 GB" matches models.json total_bytes 42030014463 from the pinned HF revision (provision.py:54); §8 Q1's "runtime re-attestation is unchanged" matches the design. Reuse is good where claimed: R5a reuses the in-image canary_gateway.py and the existing create-time env injection point (runpod_transport.py:382-391 — the new flag extends an existing dict beside MICRODRAMA_COMFY_TOKEN), R5c reuses schema_smoke.py in the pinned image, R5d reuses tools/canary_db.py for the loopback paid DB, and tools/t031_prepare_run.py / t031_results.py correctly target the existing tools/ directory beside canary_db.py and ledger.py.

---

## C. Style reviewer (`egm-style`)

Style Goldfish REVIEW audit — target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (read in full for context; audited range: lines 186-209, §6 Build packages, §7 Operator steps, §8 Open questions). No document standard assigned; persona technical-writing rubric applied (precision, redundancy, subjectivity, bloat, wording-induced ambiguity). No Blockers found. 2 Major, 6 Nit.

FINDINGS

1. Severity: Major
   Affected Scope: §6 Build packages, line 189 — "The image rebuild runs under the documented flock/CPUQuota command."
   Style Rationale: Dangling definite reference in an actionable build instruction. The spec's own citation discipline is precise everywhere else (FM §n, `benchmark_service.py:1195`, `experimental_world.py:705-717`, a doc-relative factmap link), which makes this the one outlier. Verified in the repo: the exact phrase "flock/CPUQuota" occurs only in this spec; `flock` and `CPUQuota` appear separately across roughly 10 and 53 documents respectively (concentrated in /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/ and the various fix-round dirs), with no single canonical location, and nothing under the spec's own companion dir /root/AIVORA/drama-box/docs/microdrama-system/t031-benchmark/ mentions either term. A fresh reader or the GLM builder must run a repository-wide search and then guess which variant is "the documented" one. Fix: cite the doc path and/or inline the command.

2. Severity: Major
   Affected Scope: §8 Open questions, Q3, line 208 — "Recommendation: 25 min, recorded with the actual."
   Style Rationale: "recorded with the actual" is a fragment with a dangling noun ("the actual" what?) and no destination (recorded where?). Two plausible readings: (a) keep the 25 min default and record the observed duration alongside it, or (b) replace the recorded default with the observed value — different actions. R5b already records `cold_start_ms` and `provision_ms` durably, so the clause is either redundant with R5b or underspecified, and the reader cannot tell which. As the operative recommendation in a question addressed to the critic, it should be rewritten, e.g. "Recommendation: keep 25 min; R5b's cold_start_ms/provision_ms will record the observed actual." Secondary, same line: "Is `boot_budget` = 25 min right?" — "right" is informal and criterion-free; the evaluation criterion (42 GB download completing within budget at unknown throughput) is only supplied by the following sentence.

3. Severity: Nit
   Affected Scope: §7 step 1 (line 194) and closing sentence (line 200) — "(same two commands; new digest)" / "The orchestrator prepares every file and the exact commands."
   Style Rationale: "same two commands" has no in-document antecedent — the two push commands appear nowhere in this spec. The closing sentence already promises the orchestrator supplies the exact commands, which makes the "same two" half-reference redundant; either name the commands or drop the parenthetical and keep "new digest". The two statements of who supplies commands also talk past each other.

4. Severity: Nit
   Affected Scope: §7 step 3, line 196 — "within 2 h of execute."
   Style Rationale: Compressed grammar: "execute" (the subcommand in step 5) is used as a noun naming an event. A fresh reader must back-reference step 5 plus R5d's "≤ 2 h window" to reconstruct "capture the quote no more than 2 h before running `benchmark execute`". Suggest "within 2 h before `benchmark execute` (step 5)".

5. Severity: Nit
   Affected Scope: §7 step 5, line 198 — "from your own shell."
   Style Rationale: The document's only second-person shift. The intended contrast (operator-run, not orchestrator- or CI-run) is implied but never stated, so the phrase asserts a distinction it does not define. Suggest "run directly by the operator (not via the orchestrator)".

6. Severity: Nit
   Affected Scope: §7, lines 194-198 (the step list as a whole).
   Style Rationale: The runbook terminates at `benchmark execute --phase screen` with no statement of whether or how the full phase follows. The document's stated goal is one real experiment of 8 shots / 24 samples, of which only S01-R1/S03-R1/S07-R1 are screen samples (R5d `plan.json`); the remaining ~21 samples have no operator step, gating condition, or pointer. If the truncation is deliberate (screen gates the full run; separate paid-run approval per the header), one clause stating that removes the ambiguity. As written, the list silently stops halfway through the experiment it exists to enable. Borderline content-completeness rather than pure wording, hence Nit, but it is the one structural gap in the range.

7. Severity: Nit
   Affected Scope: §8 Q1, lines 204-205 — "If not, C." and "runtime re-attestation".
   Style Rationale: (a) "If not, C." is a telegraphic fragment; "C" is a label defined two sections up (§3 R5c's capture-pod alternative), forcing a hunt. Expand to "If not, fall back to C (§3 R5c)." (b) Terminology drift: §3 R5c heads the mechanism "Live verification is unchanged and decisive"; Q1 renames it "runtime re-attestation". One mechanism, two names in one document — pick one and use it in both places.

8. Severity: Nit
   Affected Scope: §8 Q2, line 206 — "the container disk is discarded at terminate."
   Style Rationale: "at terminate" uses the pod-termination verb as a bare noun; "on pod termination" is the standard form. Minor compression in an otherwise exemplary rationale.

CLEAN BILL ON THE RUBRIC'S CORE VECTORS
No hyperbole, marketing fluff, subjective quality judgments, filler, or synonym redundancy anywhere in the audited range. The §6 arrow chain with parenthetical package scoping ("image + gateway + transport env", "ready gate + timings", ...) is precise and earns its compression. Each §8 question carries a recommendation plus a factual rationale — Q2's "`provision.py` already promotes only verified files" is exactly the right kind of objective justification — and Q3's frank "observed RunPod throughput is unknown" is good honest-uncertainty framing. The two Majors are both citation/clarity defects in operative instructions, not tone problems.
