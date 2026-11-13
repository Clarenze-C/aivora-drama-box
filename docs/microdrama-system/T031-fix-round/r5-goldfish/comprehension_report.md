# Stage 6 — Comprehension Test

- Reviewer persona: `egm-comprehension` (Naive Reader; fresh Agent, no parent context)
- Target: /root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md (209 lines)
- Scope: FeatureRange = lines 1-185 AND DetailedRange = lines 186-209
- No document standard applied (self-containment test only)
- Date: 2026-11-13

---

**What this proposes**

The document is a run-readiness spec ("R5") proposing five build increments, R5a-R5e, to make the already-accepted T031 "H-2" paid-run controller able to execute one real "Pika H3 Flex" benchmark experiment on a rented RunPod GPU pod, inside an unchanged envelope of $8.00 new exposure, 4 GPU-hours, one A40-class GPU. R5a bakes weight provisioning (5 pinned files, ~42 GB) into a new image revision behind a create-time env flag, exposed via a new read-only gateway endpoint `GET /__drama/ready`; R5b adds a `wait_ready` gate between pod create and the first upload, with a boot deadline and durable timing capture; R5c lets the seal be authored from a *predicted* schema (zero-byte placeholders in the pinned image; new evidence values `PREDICTED_FROM_PINNED_IMAGE`/`MANIFEST_PLACEHOLDER_CAPTURE`) verified live at `READY` before any upload; R5d/R5e add offline tools to assemble plan/seal/quote/authorization documents and DB rows and to map exported JSON into the results CSV template. Acceptance is 11 offline tests (RR-T1..RR-T11); no schema migration allowed.

**How the existing system works, per this document**

Per Section 1 and the linked fact map, the accepted H-2 controller already handles budget, recovery and billing for paid pod runs but cannot run a real model: nothing invokes `provision.py` so pods boot without weights; there is no boot/ready wait, so a booting pod's 502/refused connection is misread as failure or upload ambiguity; the seal demands `LIVE_PROVIDER`+`INDEPENDENT_RUNTIME_CAPTURE` schema evidence that cannot exist before the first paid pod; there are no authoring tools for the documents or real registry rows (assembly is ad-hoc Python); and timing capture and export to `results-template.csv` are manual. Paid runs execute as "acquisitions" — pods running ComfyUI behind a token gateway on RunPod — gated by plan/seal/quote/authorization documents, an episode budget account ($10 cap), holds, and a lease with a hard stop.

Findings (no Blockers — every section paraphrases coherently):

1. [Major] R5d `author`, line 133 — "an unsigned `authorization.draft.json` (§4)". The cross-reference is wrong or dangling under any reading: Section 4 of this document is the Budget envelope; the fact map's §4 is "Pins and their checks"; the authorization schema is fact-map §2. The document never describes the draft's required contents, so the only pointer misleads.

2. [Major] R5d `plan.json`, line 141 (and header line 7) — "S05/S06 expression text per DECISIONS 'D2 revised again'" delegates load-bearing frozen prompt content to an external "DECISIONS" log that is never linked, located, or quoted. The header's DECISIONS citation is fine (content summarized inline); the D2 reference is not reconstructible by a fresh reader.

3. [Major] Section 6, line 189 — "The image rebuild runs under the documented flock/CPUQuota command": the command is not quoted or linked; it exists only in the unlinked microdrama/deployment/pika-h3-flex/BUILD_EVIDENCE.md (lines 39-47 of the worktree copy). A build-safety constraint (serialized, CPU-capped rebuild) resting on "documented" with no pointer is an unstated prerequisite for the GLM builder.

4. [Nit] Section 2, lines 30-31 — scope exclusions named only by opaque codes: HC-6, HC-9, HC-11, HB-13, "R1 residual", "phase D", "768p; FL2VA" (undefined acronym). Intent (deferral) is clear; content is not.

5. [Nit] Section 2, line 31 — "A0-D owns 0027 on top of this tree; A1 has 0028-0031" assumes knowledge of workstream labels and migration numbering; the operative no-migration rule is self-contained, the parenthetical is not.

6. [Nit] R5a/R5b lines 51, 64-74; R5d line 124 — domain vocabulary used unglossed: "world" ("the Pika benchmark world", "world step", "recovery worlds"), "acquisition", "holds", "lease deadline", "verified cleanup", and "shutdown margin" (no value given in the boot-deadline formula, line 71). Also: "dedicated loopback paid DB (tools/canary_db.py)" versus "the canary DB's own episode" (line 124) — same database holding two episodes, never stated.

7. [Nit] Title line 1 vs line 126 — the experiment is "Pika H3 Flex" throughout but the rights record cites the "MiniMax H3 Community License" (weights: Comfy-Org/MiniMax-H3 per FM). The document never explains what "Pika H3 Flex" is or how "Pika" and "MiniMax H3" relate.

8. [Nit] Lines 1-11, 16 — "T031" and "H-2" never expanded; H-2 gets a functional gloss (budget/recovery/billing controller), enough to proceed but not defined.

9. [Nit] RR-T1(b) line 174 vs line 47 — the test says "ready state FAILED" while the endpoint enum defines `PROVISION_FAILED`; the acceptance test should use the exact enum value.

10. [Nit] Lines 59 and 176 — the CPU attestation hash is truncated (`1a6023e2…`) and the document never states what it hashes (the receipt file `schema-attestation.cpu.json`, full digest 1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89, distinct from FM's denied mapped-schema hash `339021b1…`). RR-T3's "byte-identically" requirement needs the full digest and referent, both only in unlinked BUILD_EVIDENCE.md.

11. [Nit] Lines 123-124, 138, 154-155 — packet files (shots.csv, trials.csv, references-r1/r2-manifest.jsonl, voices-manifest.json, results-template.csv) cited by bare filename without their directory; "Pass A/Pass B" (line 155) undefined human review passes; "O-11" (line 129) undefined rights/decision code.

12. [Nit] Lines 123-124, 164 — unglossed external proper nouns: "Nano Banana via Vertex", "Botnoi Studio V4", and "ARISA's Vertex project" (unexplained account/person that absorbed reference-generation billing).

13. [Nit] Section 7 step 1, line 194 — "Push the new image (same two commands; new digest)" presumes a prior push procedure not in this document; mitigated by line 200 (orchestrator prepares exact commands).

Overall: the document's mechanics are clear and paraphrasable end to end, and its single link (the fact map) resolves and supports the FM-cited facts. The dominant pattern is unlinked reliance on sibling artifacts (DECISIONS log, BUILD_EVIDENCE.md, packet file locations) for content the spec treats as given — items 1-3 are the ones worth fixing before the Codex critique.
