# Consolidated Review Report — T031 run-readiness spec (R5)

- **Target**: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (209 lines)
- **Mode**: Headless EGM consolidated review (Preset 1, uninterrupted; stages 5-9, one reviewer round each, no remediation)
- **Pinned base verified by reviewers**: feat/t031-fix3 @ 104b26b → /root/AIVORA/drama-box/.scratch/t031-fix3-worktree
- **Date**: 2026-11-13
- **Stage artifacts** (this directory): `zoom_out_report.md` (S5), `comprehension_report.md` (S6), `critic_report.md` (S7), `intermediate_zoom_out_report.md` (S8), `implementation_readiness_report.md` (S9)

**Semantic split**: the document has no `## Detailed Implementation Plan` header. The implementation-plan portion in substance begins at `## 6. Build packages` (line 186), which is a work breakdown by another name (ordered packages, one commit each). Bound: **FeatureRange = 1-185, DetailedRange = 186-209**. The spec owner may want to rename §6 to a standard `## Implementation Plan` heading in the fix round.

**Overall verdict**: the spec's factual base is strong — every code citation in the G1-G6 gap table, the models.json byte counts, the budget arithmetic, and the 12 Nov image evidence were independently verified against the pinned tree by four separate reviewers and all held. The failures are integration-level: five components are specified, but the seams where they meet the existing request-authorization architecture, the immutable-schema constraints, the image-content invariants, and the operator runbook are left to the builder. Nearly every required fix is a one-sentence-to-one-paragraph decision, not new code. Stage 9's verdict on the plan tail: **NOT READY to hand to a builder** until the Blocker below is resolved.

---

## 🔴 Blockers (1)

### CON-B1. §6 dispatches R5c/R5d unconditionally while their governing design decision (§8 Q1: predicted schema P vs capture pod C) is unresolved — and fallback C cannot be built inside this package
**Sources**: IR1, DE5, IZ-A7 · **Spec**: §6 line 188, §8 Q1 lines 204-205, §3 lines 106-110, §2 lines 31-32
`author` (R5d) writes "the R5c prediction" into seal.json, so R5c+R5d are coupled to Q1's answer; nothing in §6 marks them conditional. If the critique rejects P, C exists only as three sketch bullets, needs "a pre-seal authorization and new experiment states, which likely means a migration" — colliding with §2's hard no-migration rule (builder stops at a red test) — and has no file list, state machine, tool changes, or acceptance tests.
**Action**: resolve Q1 before any build dispatch; fold the ruling into §3/§6 as the single answer. If C remains live, spec it to P's depth or explicitly declare it a new spec round with its own scope/migration approval.

---

## 🟡 Majors — substantive (16)

### CON-M1. `wait_ready` cannot execute as specified: it collides with the request-guard architecture (highest-priority finding)
**Sources**: DE2, IZ-A1 · **Spec**: R5b lines 63-73 · **Code**: experimental_world.py:1261-1312, live_world.py:334-375, benchmark_service.py:1179-1183
Every pod-bound HTTP call in the world passes `request_guard`, which requires a benchmark_samples row with job_id+reservation_id (join at 1265-1270); canonical_guard allows a pre-operation read only on `/object_info`. At wait_ready time no sample exists (materialize_sample runs immediately before stage), so the ready poll is refused with EffectDenied. Two conforming designs exist: (i) place wait_ready between materialize_sample and stage_inputs, reusing the exact authorization scope `_scope()` builds for attest_schema (experimental_world.py:690-703) plus one allowlisted path; or (ii) the canary's discipline — create the first prompt's hold + durable job before any ComfyUI request and retry through the boot window (canary.py:1023-1054).
**Action**: name the guard integration in the spec and add the RR test the critic proposed (ready poll refused without acquisition/lease linkage). **Refuse any mitigation that polls /__drama/ready via raw HTTP bypassing request_guard** — that silently removes the paid path's central invariant.

### CON-M2. A PREDICTED seal fails `benchmark preflight`: the admissibility widening names only one of the two LIVE_PROVIDER gates
**Sources**: ZO1, IZ-A2 · **Spec**: R5c lines 93-105, RR-T7/RR-T9 lines 180-183 · **Code**: benchmark_service.py:198, benchmark_authorization.py:172-175
preflight independently refuses any seal whose schema_evidence != "LIVE_PROVIDER"; R5d `verify` runs preflight; RR-T9 demands "preflight PASS on the authored set" — impossible with PREDICTED unless preflight is widened in the same change.
**Action**: name all R5c touch points (Literal widening, validate_for, benchmark_service.preflight) as one coherent commit, and add an acceptance row that a PREDICTED seal passes preflight end-to-end.

### CON-M3. No named durable landing zone for per-acquisition timings, the R5c live-capture record, or the PROVISION_FAILED/BOOT_TIMEOUT incidents — a Zero-Decision violation with a known no-migration answer
**Sources**: ZO3, DE3, IR5, IZ-A3, CD1 (part) · **Spec**: R5b lines 75-80, R5c line 104-105 · **Code**: migrations/0026:13,47,112; benchmark_service.py:3071-3074
Acquisition intent/quote and experiment plan are immutable; sample request/output are set-once. "The builder names them; if none fit, stop and report" will therefore fire on the central timing requirement (the likeliest build-stall), and R5c's recording obligation has no hedge at all. There is no incidents table (export "incidents" are derived contradiction records). Concrete fix verified in-tree: `benchmark_samples.coverage` is a **mutable** jsonb column (0026:112's set-once list omits it) — timings/capture can ride per-sample coverage or the first request/output write; the mutable `benchmark_acquisitions.state` text column is the natural home for the two incident states.
**Action**: name one landing zone covering R5b timings + R5c capture + both incident states. No migration needed.

### CON-M4. Asset inventory is wrong/underdetermined: the manifests hold 10 PNGs, the spec says 6, and the picks/anchor/reuse decisions that make it 6 are nowhere in the document
**Sources**: ZO7, DE4, IZ-A6 · **Spec**: R5d lines 122-124 · **Data**: references-r1-manifest.jsonl (6: A1-A3, B1-B3), references-r2-manifest.jsonl (4: A-home, SET-office, SET-home, PROP-envelope-01)
The count 6 is correct only given DECISIONS "T031 benchmark inputs" (A=A2, B=B2, plus the four r2 assets) — cited for S05/S06 text but not for the picks. Unstated: which candidate becomes the single character_identity anchor (r2's A-home input_ref chain implies A2-canonical), and how outfit:A-office/B-office roles are satisfied (role-reuse of the same PNGs — no office assets exist). A register step that must "refuse on any drift" is left nondeterministic, and the frozen `<Picture N>/<Audio N>` labels depend on the resulting port_map.
**Action**: name the picks explicitly, add the role→asset mapping (role, subject, chosen ref_id) including the office-outfit reuse, and state the A2-canonical rule.

### CON-M5. Image-digest binding is unsatisfiable as scheduled: local image ID ≠ registry manifest digest; sequence push → predict → author
**Sources**: DE7, IR4, CD3, IZ-A5 · **Spec**: R5c lines 96-99, §6-§7 · **Evidence**: BUILD_EVIDENCE.md:80-88 (local abd32e9e… vs pinned e4ccc004…)
The seal's image_ref pins the pushed registry manifest digest; the prediction tool as specified runs against the local build before the push. validate_for's machine-checked equality would bind the wrong digest kind, or force drift-editing the capture record. §7's printed order (push → sign) hides that predict/author/verify must interleave after the push and before signing; `create` refuses any image not pinned by the attestation (runpod_transport.py:349-350).
**Action**: sequence it explicitly — operator pushes first; the prediction runs INSIDE the pulled registry reference by manifest digest and records that digest; `author` binds it; forbid the local image ID in the capture record; put "orchestrator: predict, author, verify after your push, before you sign" into §7.

### CON-M6. The §7 operator runbook is materially incomplete and not executable as printed
**Sources**: IR2, SY9-6, CD4 (part) · **Spec**: §7 lines 192-200
Missing between sign and execute: `canary_db.py up`, `register`, `author`, `benchmark prepare --plan`, `benchmark seal --manifest`, `quote`, `verify`/preflight (verified order in FM §3). Missing after screen: record-screening (Pass A), `execute --phase full`, sweep/cleanup verification, export, `t031_results.py`, invoice finality — the runbook silently stops halfway through the experiment it exists to enable. "The orchestrator prepares every file and the exact commands" is a blanket deferral, not a runbook, on a money path.
**Action**: enumerate every command with actor, order, working dir, env, and target DB; state whether/how the full phase follows screen.

### CON-M7. "Push the new image (same two commands; new digest)" references a procedure that exists nowhere
**Sources**: IR3, CD2, CP13, SY9-3 · **Spec**: §7 step 1 line 194
BUILD_EVIDENCE.md records only the 12 Nov push outcome (gh token, write:packages, digest), not the commands; the only documented push procedures in the repo are for a different image (canary-image README). The digest these commands produce is what the seal pins.
**Action**: inline the exact commands (login, tag/push, digest capture) in §7 or the pika-h3-flex README.

### CON-M8. Unlinked load-bearing content the builder must execute verbatim: three dangles
**Sources**: CP1, CP2, CP3, SY7-2, SY9-1, IR8 (part), IZ-A10 · **Spec**: line 133, line 141, line 189
(1) `authorization.draft.json (§4)` — §4 of this document is the budget; the fact map's §4 is "Pins and their checks"; the authorization schema is FM §2. Wrong or dangling under any reading, and the draft's contents are never described. (2) S05/S06 frozen prompt text delegated to DECISIONS "D2 revised again" — log never linked, located, or quoted. (3) "the documented flock/CPUQuota command" — uncited; it lives at deployment/pika-h3-flex/BUILD_EVIDENCE.md:39-47 (and README.md:13-16), and its recorded paths (.scratch/runtime-image/context, verify.sh) belong to the superseded t031-native worktree, so the builder must adapt them.
**Action**: link or inline all three; fix the (§4) pointer to the real schema location.

### CON-M9. R5a/R5b single-path decisions lack documented alternatives (the Alternatives Rule holds only for R5c)
**Sources**: DE1 (part), ST3 (part), IZ-A8, IZ-B3 · **Spec**: R5a lines 36-60, R5b lines 62-80
Genuinely architectural and undocumented: (a) R5a weight transport — per-run container-disk download vs RunPod network volume (survives the screen→full boundary, near-zero second boot) vs pre-baked image (no per-run download); (b) R5b gate placement — world step vs the canary's existing client-side boot-window retry. The by-construction consequence — two cold starts per experiment, each re-downloading 42 GB (~50 of the 240 GPU-minutes before any full-phase sample) — is stated nowhere.
**Action**: a short "alternatives considered" block for R5a and R5b with one-line rejection rationale (cost, stopped-tail, retry semantics); per IZ-A8, demanding alternatives for every sub-decision (poll interval, CSV mapping, quote mechanics) would be ceremony — don't.

### CON-M10. Experiment-level retry semantics are absent, and they decide whether the $8 envelope is actually sufficient
**Sources**: DE6 (part), IZ-A9, IZ-B2 · **Spec**: §4 lines 157-168, R5b lines 71-73, §8 Q2/Q3
With container-disk weights and the one-open-acquisition index, screen and full are separate pods; every PROVISION_FAILED/BOOT_TIMEOUT forfeits the download and pays a fresh ~25-min cold start (~$0.36 at $0.86/h). Unstated: what each failure leaves durable (state, incident, holds); what the operator re-runs; whether the same quote/authorization survive a failed attempt (the ≤ 2 h window makes multi-attempt the norm, not the edge); how many attempts fit the caps; the ~28 MB/s sustained throughput assumption behind boot_budget=25 min; anonymous-HF 429 throttling with no retry in provision.py.
**Action**: one failure-and-retry subsection covering durable leftovers, re-run procedure, quote/authorization validity, attempt budget, and the throughput assumption. Do NOT add in-pod retry/resume machinery (IZ-A9: over-engineering for a one-experiment package whose disk dies at terminate).

### CON-M11. The ready endpoint's state machine has three unresolved ownership decisions inside one security component
**Sources**: IZ-B1, DE11 (part) · **Spec**: R5a lines 40-48, R5b READY definition
provision.py today writes no state file, no per-file byte counts, no failing-file names — the spec's state.json obligations silently require modifying provision.py (which has its own guard test) or degrading the fields. `READY = provisioned AND ComfyUI answering` makes the gateway probe 127.0.0.1:8189, adding an HTTP-client dependency to a deliberately tiny, byte-identical-guarded security component.
**Action**: one sentence naming the state-file owner (start.sh wrapping provision.py, or a --state-file flag); either drop comfy_up from the gateway (learn "ComfyUI answering" via the existing canary-style client boot retry) or explicitly accept the probe with failure semantics.

### CON-M12. /__drama/ready vs the gateway byte-identity guard: both copies must change, and build.sh must stage start.sh
**Sources**: ZO2, DE11a, IZ-A4, IR9 · **Spec**: R5a lines 46-49; **Code**: tests/unit/rendering/test_canary_gateway.py:29-33, test_pika_image_recipe.py (added by 304ea77), build.sh line 8
The two canary_gateway.py copies are guarded byte-identical; the spec is silent on both. Adding the endpoint breaks the guard unless both copies gain it (canary: BOOTING→READY, empty provision object when the flag is absent). Separately, start.sh needs a Dockerfile COPY, a build.sh staging update, and a recipe-guard-test update — none listed in R5a/§6.
**Action**: state that both copies gain the endpoint (keeping the guard green) and list build.sh + the guard tests in R5a's scope.

### CON-M13. The transport env flag is under-specified for a first-attempt build: which type carries it, its default, who refuses, and at which layer
**Sources**: IR6, IZ-B4 · **Spec**: R5a lines 50-52, RR-T4 · **Code**: runpod_transport.py:382-391
create_pod has no world notion. Unstated: the owning model (PodCreateRequest / RunpodQuoteAttestation / durable acquisition intent JSON), the default for non-Pika worlds, and which site enforces "refused without it for this world". Right placement per IZ-B4: the flag lives in existing request/attestation data (transport stays world-agnostic), refusal enforced at intent validation on the benchmark side.
**Action**: name the field, owning model, default, refusal site, and layer.

### CON-M14. The Comfy gateway token file path and the new credref ref name are unpinned
**Sources**: IR7 · **Spec**: §7 step 2 line 195, R5d lines 131-132
`register` writes the credential_refs locator; the paid-path FILE resolver later lstats exactly that path (0600, non-symlink, owner-checked). The existing RunPod key is documented; the new token file is not — builder's register row and operator's step-2 file can diverge and only collide at execute.
**Action**: pin the credref ref name and absolute path in both §3 R5d and §7.

### CON-M15. Decimal/binary unit mixing in the disk-sizing requirement
**Sources**: SY7-1 · **Spec**: R5a lines 53-56 vs line 21
"image + 42.03 GB + largest file + 8 GiB headroom" then "default 100 GB", against the exact decimal 42,030,014,463 B. Whether "100 GB" is decimal or binary changes real headroom by several GiB.
**Action**: fix one unit basis or state each value's basis.

### CON-M16. §6 names no consolidated target scope: no per-package file dispositions, and several touch points name no module at all
**Sources**: CD1, IR8 (part) · **Spec**: §6 lines 186-190 with §3 scattered
No Create/Modify/Delete list per package; wait_ready's host module (experimental_world.py), the live-capture recording location, and the export changes are unnamed. Under the implementation-readiness standard the implementer is left to discover which files change.
**Action**: one target-scope table mapping each package to files touched (cross-referenced with CON-M3/M11 for the unnamed locations).

---

## 🟡 Major — [format] (1)

### CON-F1. [format] No consolidated Risks & Limits / Risks & Mitigations section
**Sources**: ST2, IZ-A13 · **Standard**: feature-spec-standard "Risks & Limits"
The section the EGM feature-spec template expects does not exist; risk content is scattered inline. If kept, cap it per IZ-A13 (download reliability/retry semantics, digest-kind binding, A40 queueing, HF throttling) — an exhaustive register would be ceremony. The substantive missing-risk content is tracked separately as CON-N19.

---

## 🟢 Nits — substantive (19)

- **CON-N1** wait_ready's tolerated set (refused, 502/503) is narrower than the canary's documented 404/502/503/524 through the RunPod proxy; align and reuse the poll_sleep/deadline discipline (ZO4, IZ-A12; canary.py:1026-1054).
- **CON-N2** R5d `quote`: say "load through load_document(AcquisitionQuote)" instead of restating the three rules (already enforced, benchmark_authorization.py:306-313); drop the RunPod API price cross-check entirely — no refusal power, unspecified comparison semantics (ZO5, ZO6, IZ-A12).
- **CON-N3** RR-T1(b) says "ready state FAILED"; the endpoint enum is PROVISION_FAILED — use the exact value (CP9, IZ-A12).
- **CON-N4** RR-T7's "enums equal the models.json file names" is unsatisfiable as written: the weight-free schema already contains a baked "pixel_space" entry. Define equality as per-folder listing membership (DE10, IZ-A12).
- **CON-N5** RR-T3 needs the full digest and its referent (the CPU receipt hash, only in the unlinked BUILD_EVIDENCE.md) (CP10, IZ-A12).
- **CON-N6** RR-T9's "any edited byte changes the printed sha" is false for plan/seal: those are canonical-JSON hashes. Say "any semantic edit" or also print file-byte digests (DE9, IZ-A12).
- **CON-N7** "full_job_ms … already observed in observe" contradicts the spec's own G5; the writer must be built (ingredients exist: provider_operations.submitted_at + observe time); the timing must ride the first observe write since output is set-once (DE8).
- **CON-N8** Budget table: state the two-cold-start structure (screen + full each pay boot + a full 42 GB download) and label the $3.50 reserve as undifferentiated headroom (DE12, IZ-B3, IZ-A12).
- **CON-N9** Opaque unlinked identifiers: HC-6/HC-9/HC-11/HB-13, "R1 residual", "phase D", A0-D/A1, 0027-0031, O-11, H-2, T031 — link or gloss (CP4, CP5, CP8, ST4).
- **CON-N10** Unglossed domain vocabulary at first use: world, acquisition, holds, lease deadline, "shutdown margin" (no value in the boot-deadline formula), verified cleanup, "screen and full", upload ambiguity, stopped(-storage) tail, the canary DB's two episodes, Pass A/Pass B (CP6, CP11, SY7-18).
- **CON-N11** "Pika H3 Flex" vs the "MiniMax H3 Community License": the document never says what "Pika H3 Flex" is or how Pika and MiniMax H3 relate (CP7).
- **CON-N12** Unglossed proper nouns: "Nano Banana via Vertex", "Botnoi Studio V4", "ARISA's Vertex project" (CP12).
- **CON-N13** Style/precision group: header-block compression ("after the Codex week resets", "Large / money path:", "cited FM §n", "GLM swarm"); "Neither" antecedent + cap stated twice; "truly" filler; "as today" date-anchored wording vs the pinned base; contraction inconsistency; bold-emphasis overuse + line 68 grammar ("They are never upload or submit ambiguity"); state-value agency (a state does not "proceed to cleanup"); "beside" vs "besides"; "genuine … for the record" filler; "exactly C's normal cost" overstates; P/C labels defined late; "their sha256s" leaves the draft's digest ambiguous; "whole µUSD"/"bare A40" need self-contained phrasing; "UNKNOWN stays UNKNOWN" tautology; "byte-identically" redundant; "$10 cap" unglossed beside the $8/8,000,000 µUSD caps; wordy title causative (SY7-3…SY7-20, SY9-2 part).
- **CON-N14** §8 leftovers: fold the Q2/Q3 rulings into §3 so the builder reads one answer per detail (IR10); Q2's premise is moot — provision.py already deletes partials itself (`.unverified-*` tempfile unlinked in `finally`, provision.py:51,67-68) (CD5); Q3's "recorded with the actual" is an ambiguous fragment (rated Major by one reviewer — operative-recommendation ambiguity) (SY9-2); expand "If not, C."; fix terminology drift ("runtime re-attestation" vs "Live verification is unchanged and decisive"); "at terminate" → "on pod termination" (SY9-7, SY9-8).
- **CON-N15** Runbook wording: "within 2 h of execute" (noun-ified subcommand) → "within 2 h before `benchmark execute` (step 5)"; "from your own shell" asserts an undefined contrast → "run directly by the operator (not via the orchestrator)" (SY9-4, SY9-5).
- **CON-N16** No `benchmark` console-script entry point exists; the real surface is `PYTHONPATH=src .venv/bin/python -m microdrama.pipeline.benchmark execute` with required flags and hard env gates (MICRODRAMA_EXECUTION_MODE=PAID_BENCHMARK, MICRODRAMA_PAID_REQUESTS_ENABLED, MICRODRAMA_CLOUD_RESOURCES_ENABLED, loopback DATABASE_URL, absolute OBJECT_STORE_ROOT). Name them in §7 (CD4).
- **CON-N17** §6 defines no per-package checkpoint: map RR-T1..RR-T11 to packages (T1-4→R5a, T5/6→R5b, T7/8→R5c, T9→R5d, T10→R5e, T11→all is only inferable) and state the per-commit gate (make check) (IR8 part).
- **CON-N18** R5d's boundary with the existing benchmark CLI is unstated ("prepare_run authors and registers; the benchmark CLI remains the only enforcement entry"), and "refuses on any drift" is undefined across 10+ tables — define a named frozen-field set per row type (IZ-B5).
- **CON-N19** Specific unrecorded risks (substantive core of the Risks & Limits gap, distinct from CON-F1's section-shape ask): A40 queueing (a pending pod is indistinguishable from a broken one until BOOT_TIMEOUT), anonymous HF 429 throttling, disk-fit slack on the 100 GB default (~19-28 GB depending on the unresolved image-layers question), and placeholder-vs-real enum divergence for any node that reads file contents rather than names (DE13, IZ-A13).

---

## 🟢 Nit — [format] (1)

- **CON-F2** [format] No document-level "Alternatives Considered" section (satisfied only inline for R5c). The template expects the section; note that per IZ-A8, demanding per-item alternatives beyond R5a/R5b (the substantive portion, CON-M9) would be ceremony. (DE1 remainder, ST3 remainder.)

---

## ❌ Refuted finding (verified, no action)

- **ST1** "Budget table delimiter row has two cells → table breaks in strict GFM renderers" — **refuted by direct byte check** (orchestrator) and **independently re-verified** by the Stage 8 reviewer (IZ-A11): line 160 is `|---|---:|---|`, a well-formed three-column delimiter. The budget table renders correctly.

---

## Severity adjudications applied during consolidation

1. **DE1 (Alternatives Rule) Blocker → Major** (CON-M9 + [format] CON-F2): three reviewers rated it Blocker/Major/Major; the Stage 8 adjudication (IZ-A8) confined the substantive requirement to R5a/R5b and dismissed the per-item demand as ceremony. If the spec owner follows the strict standard reading, CON-F2 can be promoted.
2. **SY9-2 ("recorded with the actual") Major → Nit** (folded into CON-N14): an ambiguity in an open question's recommendation that Q3's resolution will rewrite anyway; dissent noted.
3. **IR1 Blocker retained** as the sole consolidated Blocker (CON-B1); DE5 folded into it.
4. Cross-stage duplication (timings landing zone appeared in 4 stages; digest binding in 4; asset picks in 3; "same two commands" in 4) was merged into single items — see the matrix.

---

## Traceability matrix (raw → consolidated)

| Raw finding | Stage / reviewer | Consolidated |
|---|---|---|
| ZO1 preflight gate | S5 zoom-out | CON-M2 |
| ZO2 gateway byte-identity | S5 zoom-out | CON-M12 |
| ZO3 timings landing zone | S5 zoom-out | CON-M3 |
| ZO4 tolerated set vs canary | S5 zoom-out | CON-N1 |
| ZO5 quote restates rules | S5 zoom-out | CON-N2 |
| ZO6 price cross-check YAGNI | S5 zoom-out | CON-N2 |
| ZO7 "6 PNGs" underdetermined | S5 zoom-out | CON-M4 |
| CP1 (§4) dangling pointer | S6 comprehension | CON-M8 |
| CP2 DECISIONS D2 unlinked | S6 comprehension | CON-M8 |
| CP3 flock/CPUQuota unlinked | S6 comprehension | CON-M8 |
| CP4, CP5, CP8 opaque IDs | S6 comprehension | CON-N9 |
| CP6, CP11 unglossed vocabulary | S6 comprehension | CON-N10, CON-N13 |
| CP7 Pika vs MiniMax | S6 comprehension | CON-N11 |
| CP9 RR-T1(b) enum | S6 comprehension | CON-N3 |
| CP10 truncated hash | S6 comprehension | CON-N5 |
| CP12 proper nouns | S6 comprehension | CON-N12 |
| CP13 same-two-commands | S6 comprehension | CON-M7 |
| DE1 Alternatives Rule (Blocker) | S7 design | CON-M9 + CON-F2 |
| DE2 wait_ready/request_guard | S7 design | CON-M1 |
| DE3 timings + incidents | S7 design | CON-M3 |
| DE4 asset inventory | S7 design | CON-M4 |
| DE5 fallback C scope conflict | S7 design | CON-B1 |
| DE6 single-shot download | S7 design | CON-M10 |
| DE7 digest-kind gap | S7 design | CON-M5 |
| DE8 full_job_ms vs G5 | S7 design | CON-N7 |
| DE9 RR-T9 sha wording | S7 design | CON-N6 |
| DE10 RR-T7 enum equality | S7 design | CON-N4 |
| DE11 gateway guard + provision.py state | S7 design | CON-M11, CON-M12 |
| DE12 budget structure | S7 design | CON-N8 |
| DE13 risks scattered/missing | S7 design | CON-N19 (+CON-F1) |
| ST1 table delimiter (Major) | S7 structural | **REFUTED** |
| ST2 Risks section missing | S7 structural | CON-F1 |
| ST3 Alternatives only R5c | S7 structural | CON-M9 + CON-F2 |
| ST4 opaque identifiers | S7 structural | CON-N9 |
| SY7-1 GB/GiB | S7 style | CON-M15 |
| SY7-2 (§4) pointer | S7 style | CON-M8 |
| SY7-3…SY7-20 style group | S7 style | CON-N13 (CP11→CON-N10) |
| IZ-A1…A7, A9, A12 adjudications | S8 zoom-out | confirm sources of CON-M1/M2/M3/M4/M12/M5, CON-M10, N1-N8 |
| IZ-A8 alternatives adjudication | S8 zoom-out | CON-M9 + CON-F2 |
| IZ-A10 unlinked content | S8 zoom-out | CON-M8 |
| IZ-A11 table refutation | S8 zoom-out | (confirms REFUTED) |
| IZ-A13 risks size-cap | S8 zoom-out | CON-F1, CON-N19 |
| IZ-B1 ready ownership | S8 zoom-out | CON-M11 |
| IZ-B2 retry semantics | S8 zoom-out | CON-M10 |
| IZ-B3 double download | S8 zoom-out | CON-M9, CON-N8 |
| IZ-B4 env-flag layer | S8 zoom-out | CON-M13 |
| IZ-B5 R5d boundary/drift | S8 zoom-out | CON-N18 |
| IR1 Q1 open (Blocker) | S9 impl-readiness | CON-B1 |
| IR2 runbook incomplete | S9 impl-readiness | CON-M6 |
| IR3 push commands dangling | S9 impl-readiness | CON-M7 |
| IR4 digest unsatisfiable | S9 impl-readiness | CON-M5 |
| IR5 timings Zero-Decision | S9 impl-readiness | CON-M3 |
| IR6 transport flag under-specified | S9 impl-readiness | CON-M13 |
| IR7 token file/credref unpinned | S9 impl-readiness | CON-M14 |
| IR8 RR mapping + flock paths | S9 impl-readiness | CON-N17, CON-M8, CON-M16 |
| IR9 R5a file list | S9 impl-readiness | CON-M12 |
| IR10 fold Q2/Q3 | S9 impl-readiness | CON-N14 |
| CD1 no target scope | S9 codebase-details | CON-M16 (+CON-M3) |
| CD2 push reference | S9 codebase-details | CON-M7 |
| CD3 §7 order unexecutable | S9 codebase-details | CON-M5, CON-M6 |
| CD4 benchmark entry point | S9 codebase-details | CON-N16 (+CON-M6) |
| CD5 Q2 premise moot | S9 codebase-details | CON-N14 |
| SY9-1 flock/CPUQuota | S9 style | CON-M8 |
| SY9-2 Q3 fragment | S9 style | CON-N14 |
| SY9-3 same two commands | S9 style | CON-M7 |
| SY9-4, SY9-5 runbook wording | S9 style | CON-N15 |
| SY9-6 runbook stops at screen | S9 style | CON-M6 |
| SY9-7, SY9-8 §8 wording | S9 style | CON-N14 |

---

## Counts

- 🔴 **Blockers: 1**
- 🟡 **Majors: 17** (16 substantive + 1 [format] CON-F1)
- 🟢 **Nits: 20** (19 substantive + 1 [format] CON-F2)
- ❌ Refuted: 1 (ST1)

**Suggested fix order for the spec owner**: CON-B1 (resolve Q1 before anything else) → CON-M1/M2/M3/M5 (the four "build predictably halts" seams) → CON-M4/M6/M7/M8 (determinism of the assembly path and runbook) → the remaining Majors → Nits. The [format] items (CON-F1, CON-F2) are template-shape asks; triage them separately from the defects.
