# Stage 7 — Critic Review (Feature Spec gates)

- Reviewers (fresh Agents, no parent context, all on FeatureRange = lines 1-185):
  - `egm-design` (Architecture and Design critic) — standard: feature-spec-standard.md
  - `egm-structural` (Document Structure reviewer) — standard: feature-spec-standard.md
  - `egm-style` (Technical Writing reviewer) — persona rubric only
- Target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (209 lines)
- Date: 2026-11-13

---

## A. Design critic (`egm-design`)

REVIEW audit — Target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (FeatureRange lines 1-185), base feat/t031-fix3 @ 104b26b at /root/AIVORA/drama-box/.scratch/t031-fix3-worktree/. Standard: /root/.local/share/egm/403d888/resources/document_standards/feature-spec-standard.md. All file/line citations below were verified by direct reads.

What checked out (for orientation, not findings): every code citation in the G1-G6 table is accurate (benchmark_service.py:1195 straight to stage_inputs; pika_transport.py:139-145 attest before dispatch; comfy_transport.py:73-74 30 s bounded timeout; benchmark_authorization.py:410-420 LIVE_PROVIDER + INDEPENDENT_RUNTIME_CAPTURE and deny-set 339021b1...; experimental_world.py:705-717 attest_schema first in stage; runpod_transport.py:382-391 env injection). models.json numbers (5 files, 42,030,014,463 B, 8 GiB headroom) are exact. The 1a6023e2... CPU receipt hash exists and was reproduced byte-identically on the 12 Nov rebuild (BUILD_EVIDENCE.md:20,82). trials.csv/shots.csv agree with the plan model (24 samples, screen S01-R1/S03-R1/S07-R1 matches SCREEN_SAMPLE_IDS). Budget arithmetic is internally consistent. The problem statement is strong. The findings below are where the spec fails.

BLOCKER

1. [Blocker] Affected scope: spec lines 34-155 (§3 R5a/R5b/R5d/R5e); standard "The Alternatives Rule".
Finding: The standard makes evaluation of alternatives mandatory and states the spec fails if it "proposes a single path without proving that other viable designs were considered and rejected for specific, documented reasons". Only R5c (lines 106-111) does this (P vs capture-pod C, with cost and migration rationale — good). R5a, R5b, R5d and R5e are single-path with zero documented alternatives. The most consequential unevaluated decision is R5a's storage/provisioning: weights on the container disk, re-downloaded 42 GB per acquisition (twice per experiment), versus (a) a RunPod network volume that survives the screen→full boundary (near-zero second boot; rejected presumably for stopped-storage cost and H-2 volume semantics — but the rejection is nowhere stated), and (b) baking weights into the image (no per-run download at all; rejected presumably for 42 GB registry push/pull and digest churn — also nowhere stated). R5b (10 s polling vs alternatives; where the boot budget lives), R5d (bespoke tool vs extending tools/canary_db.py or the benchmark CLI) and R5e are likewise undocumented single paths.
Recommendation: Add a short "Alternatives considered" block per R5 item (two rejected options each with one-line cost/complexity/scalability rationale is enough). For R5a, explicitly evaluate volume-backed weights and pre-baked weights against per-run container-disk download; this is the highest-cost, highest-availability-impact decision in the package.

MAJOR

2. [Major] Affected scope: spec lines 63-73 (R5b wait_ready); code experimental_world.py:1261-1312 and live_world.py:334-372.
Finding: wait_ready as specified cannot run. Every Comfy HTTP call from the world passes request_guard, which resolves the request through benchmark_samples joined on job_id/reservation_id and an ACTIVE reservation (live_world.py:337-360), plus experiment ownership checks (experimental_world.py:1261-1278). At wait_ready time — after pod create/bind but before the first sample claim — there is no sample, hold or job, so a GET /__drama/ready through the client would be refused with EffectDenied. The spec never mentions that the request-guard architecture (the security backbone of the paid path) must be extended with a new pre-sample authorization scope, and no acceptance test (RR-T2/RR-T5 cover only the gateway side) exercises the guard side.
Recommendation: Specify the guard change: which durable scope authorizes a pre-dispatch ready poll (e.g., the acquisition's ACTIVE COMPUTE hold + owned lease + bound pod id), which world modes may issue it (EXECUTE and RECOVERY per line 65-66, but not CLEANUP?), and that the path is allowlisted exactly (/__drama/ready only, never proxied). Add an RR test that the ready poll is refused without the acquisition/lease linkage.

3. [Major] Affected scope: spec lines 75-80 (R5b timings); migration 0026_t031_benchmark_experiments.sql:33-47, 111-113.
Finding: "Timings are recorded durably in existing JSON columns only" has no legal home for the per-acquisition fields. benchmark_acquisitions' only JSON columns are quote and intent, and both are in the md_immutable_columns trigger (0026:47) — they cannot be updated with cold_start_ms/provision_ms after READY. benchmark_experiments has no mutable JSON column (plan is immutable, line 13). benchmark_samples.output/request are JSON but sample-scoped and set-once (0026:112), and the acquisition reaches READY before any sample is claimed. The spec's own escape hatch ("if none fit without a migration, stop and report") will therefore fire on the central timing requirement, colliding with §2's "No new migration" — the likeliest build-stall in the package. Similarly, "durable incident" for PROVISION_FAILED/BOOT_TIMEOUT has no existing incident table (incidents in export are derived contradiction records, benchmark_experiments.py:470-519).
Recommendation: Pre-decide the storage story before build: either name the intended column and accept a migration as an explicit carve-out from §2, or specify the fallback (e.g., derive cold_start_ms at export from create_intent_at plus a new ready timestamp recorded in a column that is mutable, or carry the ready record on the acquisition's first sample write) and state where the PROVISION_FAILED/BOOT_TIMEOUT incident is durably recorded.

4. [Major] Affected scope: spec lines 122-124 (R5d register assets); docs .../t031-benchmark/references-r1-manifest.jsonl (6 PNGs: A1-A3, B1-B3), references-r2-manifest.jsonl (4 PNGs: A-home, SET-office, SET-home, PROP-envelope-01), voices-manifest.json (2 WAVs), shots.csv required_reference_roles.
Finding: The asset inventory is factually wrong: "the 6 PNGs and 2 WAVs from references-r1/r2-manifest.jsonl and voices-manifest.json" — the two reference manifests together contain 10 PNGs, not 6. If the builder registers only 6, four roles required by shots.csv (outfit:A-home, set:office, set:home, prop:envelope-01) have no assets and seal/port_map authoring fails. Related and equally unspecified: (a) which of the three candidates per character (A1-A3, B1-B3) becomes the single character_identity anchor — the port validator refuses multiple anchors per role/subject — noting r2's A-home was generated FROM A2.png (input_ref), implying A2 is the canonical A, but the spec never says so; (b) how the outfit:A-office/B-office roles are satisfied (no dedicated office-outfit assets exist; presumably the same character PNG bound under a second role, which the duplicate-key check permits only because the tuple includes role/subject — an unstated design decision that consumes 2 of the 9 image ports).
Recommendation: Correct the count to 10 PNGs + 2 WAVs, and add an explicit role→asset mapping table (role, subject, chosen ref_id) including the office-outfit reuse decision and the A2-canonical selection rule, so `register`/`author` are deterministic and the frozen <Picture N>/<Audio N> prompt labels (which depend on the port_map) are pinned.

5. [Major] Affected scope: spec lines 29-32 (§2) vs 108-111 (R5c fallback C).
Finding: The fallback for the spec's single biggest open question contradicts the scope locks. If Codex rejects P, the stated fallback C needs "a pre-seal authorization and new experiment states, which likely means a migration" (line 109) — but §2 forbids new migrations and puts recovery/state semantics out of scope. As written, a "no" answer to open question 1 leaves the package with no in-scope path to a valid seal (G3 remains unsolved) and an undefined next step.
Recommendation: State explicitly what happens on rejection: C is a new spec round with its own migration/scope approval, not part of this package — and get the critique's answer to open question 1 resolved before the build starts, since R5d's `author` writes seal.json containing the R5c prediction (line 144-145) and everything downstream depends on it.

6. [Major] Affected scope: spec lines 40-45, 69-73 (R5a/R5b failure handling); provision.py:49-68.
Finding: Unmitigated single-shot download risk. provision.py has no retry and no resume: one dropped connection or SHA mismatch mid-42 GB raises, the whole provisioning fails, PROVISION_FAILED refuses the acquisition, and the pod (and its partially downloaded, verified files) is destroyed at cleanup. A retry means a brand-new acquisition and a full re-download from zero on a fresh pod. The spec's open question 2 (whether to delete partials in-pod) and open question 3 (boot budget) dance around this without addressing it: experiment-level retry semantics after PROVISION_FAILED or BOOT_TIMEOUT are never stated (can `execute --phase screen` be re-run under the same authorization while the ≤ 2 h quote window and GPU-ms budget remain? does the operator need a new console quote?). Each failure costs up to 25 min GPU time inside the $8 envelope, and two failures plus two legitimate cold starts can consume most of the 4 GPU-h.
Recommendation: Add a failure-and-retry subsection: what PROVISION_FAILED/BOOT_TIMEOUT leave durable (state, incident, holds), what the operator re-runs, whether the same quote/authorization remain valid, and how many acquisition attempts fit in the caps. State the known RunPod→HF CDN throughput assumption behind boot_budget (25 min for 42 GB requires ~28 MB/s sustained) and that anonymous HF downloads may be throttled (429) with no retry in provision.py.

7. [Major] Affected scope: spec lines 58-60, 86-99 (R5c digest binding), 192-194 (§7 operator steps); BUILD_EVIDENCE.md:80-88.
Finding: Digest-kind and ordering gap in condition 2 ("the seal's image_ref digest equal to the capture record's"). The seal's image_ref pins a REGISTRY manifest digest, which is only known after the operator pushes; the prediction tool runs locally against the local build, whose local image ID is a different digest (12 Nov evidence: local image ID abd32e9e... vs pinned reference e4ccc004...). Since the builder explicitly does not push (line 189-190) and the manifest digest is not predictable pre-push, the machine-checked equality can silently bind the wrong digest kind, or force a re-run of the prediction after push. The spec never sequences predict → push → author-seal.
Recommendation: Specify the ordering and digest kinds: operator pushes first, then the prediction tool runs INSIDE the pulled registry reference by manifest digest (docker run ghcr.io/...@sha256:<manifest>) and records that digest, then `author` binds it. Forbid recording the local image ID in the capture record.

NITS

8. [Nit] Spec line 78 vs line 24 (G5). "full_job_ms ... already observed in observe" contradicts the spec's own G5 ("no ... full-job timing writers"), and _observe (benchmark_service.py:1363-1434) writes only state/output/coverage with no timing; the ingredients exist (provider_operations.submitted_at, 0001_foundation.sql:180, plus observe time), but the writer must be built. Reword to "derivable from durable timestamps; writer to be added", and note sample output is set-once so the timing must ride the first observe write.

9. [Nit] Spec line 182 (RR-T9). "any edited byte changes the printed sha" is false for plan/seal: plan_sha256 and sealed_sha256 are canonical-JSON hashes (benchmark_authorization.py:69-78,158-160,280-282), so reformatting or key-reordering edits change file bytes without changing the printed hash. Only the authorization sha is over raw bytes (:460-473). Reword RR-T9 to "any semantic edit" or have the tool also print file-byte digests.

10. [Nit] Spec lines 95-99 and 180 (RR-T7) — enum-equality condition. The weight-free VAELoader enum already contains a baked "pixel_space" entry (schema-attestation.cpu.json), so strict "enums equal to the models.json file names" may be unsatisfiable on the weighted pod. Define equality precisely (per-folder listing membership vs exact set) before the builder codes the check and its test.

11. [Nit] Spec lines 38-49 (R5a gateway/start.sh). canary_gateway.py must stay byte-identical with the sibling image copy, guarded by tests/unit/rendering/test_canary_gateway.py (docstring lines 12-13) — adding /__drama/ready breaks that guard unless the sibling and test are updated. Also, provision.py as it stands writes no state.json, no per-file byte counts, and error messages that do not name the failing file; either provision.py changes (image content change beyond start.sh — say so) or start.sh must wrap it and own the state machine (including who writes PROVISIONING before the download starts).

12. [Nit] Spec lines 157-168 (§4). The envelope never states the run's two-cold-start structure: the screen acquisition and the full acquisition are separate pods (one-open-acquisition index, 0026:46), each paying boot + a full 42 GB download — up to 50 of the 240 GPU-minutes before any full-phase sample. Covered by the caps, but the budget table should show it, since it is the main consumer of the boot budget and the $3.44 compute line's biggest variance driver. Related: the $3.50 shutdown/rounding reserve is 44% of the envelope as undifferentiated headroom — acceptable, but label it as such.

13. [Nit] Whole document — standard "Risks & Limits". Risks are scattered inline and several are missing entirely: A40 availability/queueing (a pod pending without an endpoint is indistinguishable from a broken one until BOOT_TIMEOUT), HF anonymous rate-limiting, disk-fit slack on the 100 GB default (image 9.54 GB + peak provisioning need ~71.6 GB leaves ~19-28 GB depending on whether container disk includes image layers — the verification is deferred to the builder, good, but the slack margin should be stated), and the compose risk that placeholder-based enums diverge from real-weight enums for any node that reads file contents rather than names. Add a consolidated Risks & Limits section with mitigations.

Answers to the spec's open questions (as requested context for the critique): Q1 — P is acceptable in principle, because runtime re-attestation at READY remains the decisive gate and the worst case is one refused cold start; but only with findings 7 and 10 fixed. Q2 — agree: no deletion of partials; the container disk is discarded at terminate. Q3 — 25 min is a guess that requires ~28 MB/s sustained; keep it as the default but record the observed throughput in the ready body (already planned) and treat a first-run overrun as evidence for retuning, not a silent failure.

---

## B. Structural reviewer (`egm-structural`)

Structural Goldfish REVIEW — Target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md, FeatureRange lines 1-185 (full document read for context). Standard enforced: /root/.local/share/egm/403d888/resources/document_standards/feature-spec-standard.md.

STRUCTURE MAP (lines 1-185): H1 title -> preamble metadata (version/status/operator decisions/base/facts link) -> H2 "1. Problem" (gap table G1-G6) -> H2 "2. Scope and non-goals" -> H2 "3. Design" with H3s R5a-R5e -> H2 "4. Budget envelope" (table) -> H2 "5. Acceptance tests" (table RR-T1-T11). Lines 186-209 (sections 6-8) are outside the FeatureRange but present and consistently numbered. Heading hierarchy is clean: no skipped levels, H3s only under section 3, numbering sequential 1-8, bullet and numbered-list styles consistent throughout. Section order (Problem -> Scope/Non-Goals -> Design -> Budget -> Acceptance tests) is workable and matches the standard's example sequence for the sections that exist.

COMPLIANCE CONFIRMED:
- Problem Statement present (section 1); Goals & Non-Goals present in substance (section 2, in-scope R5a-R5e plus explicit out-of-scope list); Proposed Architecture present (section 3, component-level design per gap).
- The one document-relative link, [paid-run fact map](t031-benchmark/paid-run-factmap.md) at line 12, resolves under the stated base directory. Backticked artifact references (shots.csv, trials.csv, results-template.csv, references-r1/r2-manifest.jsonl, voices-manifest.json) all exist in /root/AIVORA/drama-box/docs/microdrama-system/t031-benchmark/.
- The Alternatives Rule IS satisfied for the pivotal R5c design (P vs C with documented cost/complexity rejection rationale and a fallback, lines 106-111), and acceptance-test and open-questions sections are present.

FINDINGS:

1. Severity: [Major] — Affected Scope: Section 4 "Budget envelope" table, lines 159-168 (delimiter row at line 160). — Discrepancy Description & Rationale: Broken table border. The header row declares three columns (`| Component | Ceiling | Note |`) but the delimiter row is `|---|---:|` — only two cells. Under CommonMark/GFM table rules the delimiter row must match the header cell count or the table is not recognized at all, so the entire budget table (the money-path centerpiece, 10 lines including the $8.00 total row) renders as plain paragraph text on strict renderers instead of a table. Every other table in the document (lines 18-25, 172-184) has a matching delimiter row, so this is an isolated defect. Fix is mechanical: `|---|---:|---|`.

> **[Orchestrator verification: REFUTED.]** Direct byte check of line 160 shows `|---|---:|---|` — three delimiter cells matching the three-column header; the budget table is well-formed GFM. The reviewer's premise (`|---|---:|`) does not match the file. Excluded from consolidated action items.

2. Severity: [Major] — Affected Scope: Whole document / feature-spec section set; standard clause "Risks & Limits" / example section "Risks & Mitigations". — Discrepancy Description & Rationale: No Risks & Mitigations (or Risks & Limits) section exists anywhere in the document. The standard requires the specification to explicitly identify failure modes, security implications, scalability limits, and mitigations; here that content is scattered and only partial: failure modes appear inline in R5a/R5b (PROVISION_FAILED refusal, BOOT_TIMEOUT incident) and security notes appear inline (token-checked /__drama/ready endpoint, no secrets in the ready body, 0600 token file, no credential values printed), but there is no consolidated section where a fresh reader can confirm "all major risks have been addressed" per the standard's Core Principle — e.g., anonymous HTTPS download integrity for 42 GB of weights, image-digest pinning after rebuild, and container-disk sizing headroom are each mentioned in different subsections with no consolidated risk register. If the team reads the Risks & Limits clause as requiring a dedicated section (it is stated as a "must"), this escalates to Blocker.

3. Severity: [Major] — Affected Scope: Section 3, R5a (lines 36-60) and R5b (lines 62-80); standard clause "The Alternatives Rule". — Discrepancy Description & Rationale: The Alternatives Rule is satisfied only for R5c. R5a and R5b propose single paths with no documented consideration of viable alternatives: (a) R5a's storage decision — weights on the container disk with persistent_volume_gb = 0 (lines 53-56) — silently rejects the obvious alternative (a RunPod network volume, the conventional way to host 42 GB of pinned weights and the choice that changes the budget's $0.00 stopped-tail row and the re-download cost on any recovery/retry) without a word of rationale; (b) R5a's provisioning-in-start.sh vs a separate provisioning step or pre-baked image layers is not weighed (a pre-baked 42 GB image would eliminate the 25-min boot budget entirely but costs push/registry bandwidth); (c) R5b's new gateway /__drama/ready endpoint vs polling existing ComfyUI endpoints or RunPod pod state is asserted, not compared. The standard fails a spec that "proposes a single path without proving that other viable designs were considered and rejected for specific, documented reasons"; R5c shows the document knows how to do this, so the omission in R5a/R5b is a compliance gap, not a style choice.

4. Severity: [Nit] — Affected Scope: Preamble line 11 and lines 29-31 (section 2), line 129, line 140. — Discrepancy Description & Rationale: Opaque unlinked identifiers with no in-document glossary or link: H-2 (lines 11, 16), HC-6/HC-9/HC-11/HB-13 and "the R1 residual" (line 30), A0-D/A1 and migration numbers 0027-0031 (lines 31-32), O-11 (line 129), DECISIONS "T031 run-readiness" and "D2 revised again" (lines 7, 140). Only the FM reference is linked (line 12). The standard's Core Principle requires a fresh engineer or AI session to understand the specification; these IDs are unresolvable without tribal access to prior review rounds. The one provided link (the fact map) is the right pattern and should be replicated for the decisions log and the H/HC/HB finding identifiers.

NOT FINDINGS (checked, clean): no skipped heading levels; no missing/misspelled expected section titles among those present; no unclosed code blocks; bullet/list nesting indentation is consistent and valid; acceptance-test table is well-formed with unique IDs RR-T1 through RR-T11; section order is workable.

Summary verdict: structurally sound document with one mechanical formatting defect (broken budget-table delimiter, finding 1) and two standard-compliance gaps against the feature-spec standard (missing consolidated Risks & Mitigations section, finding 2; Alternatives Rule satisfied for R5c only, finding 3). Findings 2 and 3 are the ones a critique round should force into the document before build sign-off; finding 1 is a one-line fix.

---

## C. Style reviewer (`egm-style`)

Style Goldfish REVIEW audit complete. Persona standard read at /root/.local/share/egm/403d888/agents/style.md; target read in full (209 lines) at /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md; audit applied to lines 1-185. No assigned document standard; persona rubric applied (precision, redundancy, subjectivity, bloat, wording-induced ambiguity).

Overall: the document is largely dry, factual, and well-anchored with file/line citations. Two precision defects rise to Major; the rest is polish. No Blockers.

FINDINGS

1. Severity: Major — Lines 53-56 (R5a, Storage). The disk-sizing requirement mixes decimal and binary units in one formula: "image + 42.03 GB + largest file + 8 GiB headroom", then "default 100 GB", while line 21 gives 42,030,014,463 B (decimal). Whether "100 GB" is decimal or binary changes the real headroom by several GiB; the wording introduces ambiguity the numbers should not carry. Fix one unit basis or state each value's basis.

2. Severity: Major — Line 133 (R5d, author). "authorization.draft.json (§4)" is an unresolvable cross-reference: §4 of this document is the budget envelope and does not describe the draft. If it means §7 step 4 or FM §4, the pointer does not say so. On the money path, a reference a fresh reader cannot resolve is a precision defect.

3. Severity: Nit — Lines 3-5 (status block). Opaque compressed metadata: "after the Codex week resets (13 Nov 10:30Z)" reads as garbled (noun or verb? what resets?); "Large / money path:" is unglossed internal shorthand.

4. Severity: Nit — Lines 7-9 (Operator decisions). "Neither is the paid-run sign-off" has an ambiguous antecedent (the two candidates — build decision and capture-cost ruling — are of different types). Also synonym redundancy: "counts inside the $8 benchmark envelope (total new exposure ≤ $8)" states the same cap twice in one sentence.

5. Severity: Nit — Line 12 (Facts). "(GLM swarm, spot-checked), cited `FM §n`" is elliptical to opacity: "cited FM §n" compresses a citation-convention instruction into three tokens; "GLM swarm" assumes context.

6. Severity: Nit — Lines 31-32 (§2 migration rule). "If a fix truly needs a schema change" — "truly" is a filler intensifier adding no testable meaning.

7. Severity: Nit — Lines 44, 49, 100; contractions at 24, 59. "exactly as today" / "keeps today's behaviour" / "stays accepted as today" use a date-of-reading anchor in a versioned spec whose baseline is the commit on line 11; "as of the base revision" is precise. Related inconsistency: "can't" (24), "don't" (59) beside "cannot" (16) in equally normative prose.

8. Severity: Nit — Lines 45, 46, 60, 64, 68, 75-76, 96, 101, 104, 110, 161 (recurring). Bold typographic emphasis carries normative force ("never", "one", "before", "only", "includes", "new image digest", "C is the fallback"); the verb should make the rule binding, and emphasis this frequent loses force. Line 68 also has a grammar slip: "They are never upload or submit ambiguity" (plural subject, singular complement) — "never count as an upload or submit ambiguity".

9. Severity: Nit — Lines 69-70 (R5b). "PROVISION_FAILED refuses the acquisition ... and proceeds to the normal verified cleanup" — a state value does not "proceed"; the world/controller does. Imprecise agency in a normative sentence.

10. Severity: Nit — Lines 50-51 (R5a). "(beside MICRODRAMA_COMFY_TOKEN)" — "beside" means "next to"; "besides" means "in addition to". As written it claims positional adjacency in the env payload, presumably not the requirement.

11. Severity: Nit — Line 105 (R5c). "the experiment holds a genuine runtime capture for the record" — "genuine" is a subjective qualifier adding nothing over "runtime capture"; "for the record" is filler.

12. Severity: Nit — Lines 107-108 (R5c, Why P over C). "That is exactly C's normal cost." — "exactly" overstates: P's worst case is a refused cold start with no capture work; C's normal cost includes the capture run. Approximate parity presented as exact equality.

13. Severity: Nit — Lines 84, 106, 110 (R5c). Labels P and C are used before definition ("Recommended (P)." opens the section; C first appears in the "Why P over ... (C)" heading). One sentence naming P (prediction) and C (capture pod) up front would remove the re-reading.

14. Severity: Nit — Lines 133-134 (R5d, author). "prints their sha256s (plan_sha256, sealed_sha256)" — "their" implies three digests for three written files; only two names are given, leaving whether the draft's sha is printed ambiguous.

15. Severity: Nit — Line 148 (R5d, quote). "enforces the ≤ 2 h window and whole µUSD per GPU-second" drops its noun (whole-µUSD price granularity); "refuses bare A40" is shorthand only FM §2 can decode — "an unqualified A40 GPU type" would be self-contained.

16. Severity: Nit — Line 155 (R5e). "UNKNOWN stays UNKNOWN" is a tautology; the intended rule (existing UNKNOWN values are preserved, not blanked or coerced to 0) should be stated plainly.

17. Severity: Nit — Line 176 (RR-T3). "reproduces the CPU attestation hash ... byte-identically" — reproducing a hash is exact by definition; redundant adverb.

18. Severity: Nit — Lines 21, 30, 54, 65, 74, 155, 163 (scattered). Unglossed internal shorthand at first use: "upload ambiguity" (21), "the R1 residual" (30), "stopped-storage tail" (54) / "stopped tail" (163), "screen and full" (65), "the experiment's holds" (74), "the human Pass A/Pass B" (155). One clause each would keep the spec self-contained.

19. Severity: Nit — Line 120 (R5d, register). "($10 cap)" is unglossed in a document whose headline cap is $8.00 and whose DB caps are ≤ 8,000,000 µUSD (line 168); which cap this is (account- vs experiment-level) should be said at point of use, else it reads as an inconsistency.

20. Severity: Nit — Line 1 (title). "make the accepted benchmark path able to run one real Pika H3 Flex experiment" — wordy causative; "Run one real Pika H3 Flex experiment on the accepted benchmark path" states the goal directly.

COUNTS: Blocker 0; Major 2; Nit 18. Substance, citation discipline, and budget arithmetic are strong; findings are wording-level precision and consistency issues concentrated in the header block and R5a-R5d requirement sentences.
