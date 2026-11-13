# Stage 5 — Initial Zoom Out Report

- **Target**: /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md (v0.1 DRAFT)
- **Range**: full file, lines 1–490 (FeatureRange; no separate implementation-plan boundary exists in this document)
- **Reviewer**: egm:egm-zoom-out (Skeptical Architect), Mode: REVIEW, standard `resources/document_standards/zoom-out-standard.md`
- **Goldfish context**: none (reviewer read files the document references; codebase root /root/AIVORA/drama-box)
- **Date**: 2026-11-13
- **Headless uninterrupted run** (Preset 1) — findings only, no remediation applied.

---

# Zoom-Out review: /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md (v0.1 DRAFT)

**Overall**: This is a strong phase spec. Context sufficiency passes decisively — scope, motivation, dependencies (all pinned versions exist and say what is claimed), and a fact base (c-factmap.md) whose code anchors I independently re-verified (GenerationProvider at providers.py:187-204, ProviderOperation at cost.py:711, queue CHECK at 0001:77, identity_locks NOT NULLs at 0002:258/261, voices at 0002:134-152, asset_lineage at 0004:41-49, ARISA's flock pattern and lock file at /root/AIVORA/arisa/studio/sfw/recovery.py:90-106 and vertex-generation.lock, both Botnoi CSVs). Its reuse instincts are mostly right: it reuses identity_locks/identity_lock_assets instead of a new lock table, reads CastBinding from the lock instead of a second binding table, adds no job system, and keeps every paid path behind phase A's accounts. The findings below are the places where it still adds state, references, or mappings it does not need or does not anchor.

## Findings

**1. [Major] §2 migration C-3 (cast_dependency_edges, lines 98-100) and §3 (line 141) — a third representation of a two-parent-kind graph that is already fully encoded in cast_pick_items.**
Both edge kinds (BUILT_ON_FACE, COVERAGE_OF) are single-parent: every child item (outfit, appearance state, sheet view, expression, coverage plate) has exactly one parent pick, and the parent is derivable from the child's pick_kind plus its character/location demand. The spec itself says the edges are "derived deterministically at item creation", and §4's staleness rule already computes dependency state "from stored columns, never a stored flag" — using parent_pick_id and parent_version_at_generation, both already columns in C-1. So the append-only edge table duplicates a relationship the item rows already store, in a second place that can drift. Simpler: drop C-3 entirely and hand A4's DependencyProvider a closure computed from parent_pick_id + pick_kind (a recursive CTE or plain walk). If A4's provider contract genuinely requires persisted, addressable edge rows, the spec should say so — otherwise this is a whole migration, table, and registration code path for derivable data. (Either way, one of the two representations is redundant as written.)

**2. [Major] §7 "must pass the binder's byte validator" (line 292) and acceptance C-T11 (line 447) — the validator has no locatable existence in the merged tree.**
The "binder" is T031 benchmark code; its binding module lives only in the unmerged experiment tree (.scratch/a0d-gate/microdrama/src/microdrama/rendering/workflows/binding.py), and no WAV byte validator exists in microdrama/src/microdrama/rendering/ in the main tree (the only 24 kHz records are the T031 manifests under /root/AIVORA/drama-box/docs/microdrama-system/t031-benchmark/voices-manifest.json). A C7 builder implementing C-T11 has nothing concrete to call. The merged codebase already has the right primitive: /root/AIVORA/drama-box/microdrama/src/microdrama/references/media.py (wav_media_info parses RIFF layout, channels and sample rate; verify_generated is the existing byte gate for generated media). The spec should either anchor the binder validator to a real seam (and state that it lands with D's T031 merge) or declare C's own profile check — reusing/extending references/media.py — to be the validator of record. Same note for the decode step: the existing ffmpeg runner in editing/ffmpeg.py should be named as the isolated-decode subprocess rather than left implied.

**3. [Major] §2 (line 108) vs §8 step 3 (line 329) — the "pick kinds map to the five asset_kinds" mapping is asserted but never given, and several kinds have no legal target.**
Both reference_versions.ref_kind (0002:158) and identity_lock_assets.asset_kind (0002:275) are hard CHECKs over exactly FACE/VOICE/WARDROBE/LOCATION/STYLE. The pick_kind vocabulary has twelve values including PROP, EXTRAS_LOOK, SHEET_VIEW, EXPRESSION, LOCATION_COVERAGE, MUSIC_LIB, SFX_LIB. Where do props, extras looks, coverage plates and the music/SFX libraries land as lock members? V2 never solved this either (props live as PropSheet records with an asset_role, not as reference versions of a PROP kind). Since writing identity_lock_assets members is step 3 of the lock transaction, this mapping is load-bearing for C9 and is currently a promise, not a design. It belongs in the spec (one table row would do), and C1's critiqued migration note cannot sign off without it.

**4. [Nit] §8 (line 309) — "A1 §2.7" does not resolve.**
A1-design-note.md has §2.1-§2.4 only; the handler-registry rule ("unshipped gates return NOT_AVAILABLE before any recording") is phase-A-spec §2 item 7 (reinforced by the A1 note's §5 preflight seam and §6 command table). Same class of slip: attach_identity_lock is at S/references/service.py:285, cited as :284 twice (lines 77, 333). In a document family that treats line anchors as verified facts, these should be corrected.

**5. [Nit] §2 C-5 / §9 (lines 363-368) and C-T12 — the OCR/branding checks lack the fallback rule the spec correctly applies to likeness.**
Likeness honestly defers to "a recorded human check" until a qualified detector exists (O-2), but on-frame text (OCR) and branding are listed as running checks with no statement of what ships when no OCR detector is qualified — and the codebase has no OCR today (verified: zero hits). C10 ("Output inspection seam + deterministic checks") and the fixture-based C-T12 need the same "automated where a qualified detector exists, otherwise a recorded human check" sentence, or an explicit list of which checks are machine checks in P0 versus recorded findings. Otherwise C10 risks building detector plumbing with no detectors.

**6. [Nit] §12 package C9 / §8 (lines 346-349) — season-2 import is bundled into the riskiest package.**
import_cast (R-12.5) is master-mandated and correctly owned by C, but it is not needed until a second season exists, and it rides in the same package as the lock transaction and the R-12.1 fix — the two things the first season cannot ship without. Splitting it into its own small trailing package (ownership unchanged) would shrink C9's critique surface and let the lock land sooner. A scheduling suggestion, not a scope change.

**7. [Nit] §5 / §10 — the relationship between cast_v3.generate and the existing GenerationAdapter is unstated.**
S/references/generation.py:202+ (GenerationAdapter, check_rights, build_image_request) is the existing reserve→submit→poll→fetch discipline for paid generations, currently hardwired to episode-scoped reservations. C's jobs are season/step_04-scoped, so direct reuse is not automatic — but the spec should say whether C3 wraps/extends GenerationAdapter or writes a parallel driver, and whether check_rights/build_image_request are reused. Left unstated, the likely build outcome is a second provider-loop implementation next to the first one.

**8. [Nit] O-C1 (line 457) — a decision DECISIONS.md explicitly requires "before phase C" is still open at spec time.**
The design is sensibly decision-independent (either source feeds the same normalisation/assessment intake), and the recommendation (manual Studio upload for P0) matches the T031 evidence. But per the project's own rule ("Changes need a new dated entry here"), the operator's choice should be recorded in DECISIONS.md before C6/C7 build, or the intake's "only P0 path" framing rests on an unconfirmed recommendation.

## Vectors checked with no finding

- **YAGNI**: zip bulk import, four queue lanes, fairness parameters and upload limits are all master-mandated or operator-decided, not speculative; forecasts are arithmetic with honestly-labelled UNVERIFIED inputs. The CastV3Store-mirrors-StoryV3Store pattern is justified (keeps B's allowlist and byte-identity gates independent).
- **Premature optimization**: none — no caching, sharding, or speculative async beyond mandated lanes; fairness numbers are config-owned pending P0.
- **Architectural dead-ends**: reusing identity_locks with a V3-only NULL relaxation plus a version-aware trigger preserves the V1 rows and all existing readers; the flock-on-shared-inode lock mirrors ARISA's verified pattern because interoperability requires it; the absolute ARISA path stays config-owned (O-C5).
- **Root problem focus**: R-12.1 is fixed at the root (auto-adopt at creation plus stamp-all at lock) rather than patching the render gate; the picks-as-votes design kills the side-state problem (AR-4) by construction.
- **Altitude**: appropriate for this project's phase-spec genre; numeric limits appear because master delegates them to C.
