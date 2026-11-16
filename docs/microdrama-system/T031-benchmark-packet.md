# T031 — Pika H3 Flex native-audio benchmark packet

Prepared 6 November 2026. **Preparation complete; paid execution NOT authorized.**
This is a benchmark proposal and readiness inventory, not a runnable authorization
file or an accepted production preset. User direction: Drama Box uses **Pika H3
Flex, post-trained on MiniMax H3**, with native voice/audio. Separate TTS is not
the default. No model substitution is authorized by this packet.

## Decision and current evidence

Use the **Ref2VA Pika H3 Flex six-step adapter** for recurring cast and voice
references. Keep the matching FL2VA adapter as a separately measured endpoint-frame
comparison; do not claim that FL2VA has Ref2VA's audio-reference controls. Start
with 480p feasibility, then repeat at intended 768p portrait settings only when the
480p route passes the screening and the approved budget still covers it. Each
resolution/mode is a separate configuration; the first proposed budget covers
**one Ref2VA configuration**, not both resolutions or a model tournament.

Pika documents synchronized video and stereo audio, including dialogue, in its
local model release. This is the intended voice generator. Audio references
condition a speaker; they do not establish permanent identity or correct Thai
pronunciation. H3's upstream stable-language list has eleven languages and does
not include Thai. Thai capability remains an experiment, not a refusal based on
the language list and not an assumed pass. [Pika model card](https://huggingface.co/Pika-Labs/Pika-H3-Flex),
[H3 specifications](https://github.com/MiniMax-AI/MiniMax-H3).

Pika's hosted audio-stem separation, upscaling and prompt enhancement are separate
services. Local mixed audio is sufficient for the initial benchmark; do not assume
those hosted extensions are present in a RunPod image or call them automatically.
[Official product documentation](https://pika.art/pika-h3-flex).

The 5 November run-14 canary proved Drama Box's real provider lifecycle using
**stub-generated videos**. It did not load H3, Pika adapters or a Thai voice model.
The immutable completion JSON still says PENDING_PROVIDER_FINALITY because it was
written before invoice verification. The later recorded invoice and sweep settled
the lease BILLED. Preserve both records. See [canary close-out](T031-canary-closeout.md).

## Frozen research inputs and remaining runtime pins

[source-pins.json](t031-benchmark/source-pins.json) records fetched repository
revisions, published adapter checksums, license-document hashes and the byte hashes
of the three saved official ComfyUI workflow JSONs. These are **research pins**:
no weights were downloaded or executed, and no runtime schema was attested.

The saved upstream workflows are UI graphs, not Drama Box API prompts. Preserve
them as source evidence. A future implementation must convert/bind the selected
graph, replace showcase prompts/assets with the benchmark inputs, and hash the
final API graph independently. Never submit a UI JSON as an API prompt.

Before paid execution, freeze one manifest containing:

| Input | Required value / current status |
|---|---|
| Base and adapter | Official Comfy repack `Comfy-Org/MiniMax-H3` revision `54472221d27c695fca9621b0c3ed52f06c4af707`: Ref2VA pruned INT8 base + matching `pika_h3_flex_ref2va_v1_bf16` LoRA, Qwen NVFP4 AWQ encoder, INT8 video VAE, FP32 audio VAE; five component byte hashes/sizes in source pins |
| Quantization | Selected research candidate is the official workflow's pruned INT8/convrot base and NVFP4/AWQ encoder; A40 kernel support, offload and output fidelity remain unverified; no silent substitutions |
| Sampling | `lcm`, strength 1.0, exact sigmas `1, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0`; retain released video/audio shifts; six generic Euler steps are not equivalent |
| Image and software | New digest-pinned real-model image; exact ComfyUI/runtime/dependency revisions; no canary stub nodes or loader overrides |
| Schema and controls | Actual `/object_info` mapped-input schema hash, maximum duration/resolution, supported role-labeled references, audio generation enabled |
| Output | 480p portrait bucket, 9:16, 24 fps, requested five-second clips; record actual frame-grid duration and exact dimensions; 768p is a separate authorization/configuration |
| Character inputs | Two original adult fictional character anchors, stable outfit and set references; actual bytes, provenance, role and SHA pending |
| Voice inputs | Consented/licensed audio anchors for both speakers, source/cost/rights/byte hashes pending; do not download real actors' dialogue |
| Prompts | Frozen Thai lines from shot matrix, speaker labels, seeds, negatives and complete reference order; independent SHA per canonical prompt |
| Provider | Actual GPU catalog ID, host RAM, current compute/storage quote, validity window and account label; all pending refreshed preflight |

Native audio can also be tested without reference audio, but label that result
**unconditioned voice**. It cannot certify recurring voice identity. Do not create
a paid reference-voice dependency without reserving and authorizing its cost.

The five selected weight files total **42,030,014,463 bytes**; that is a download
size, not peak GPU/host memory. The Comfy-repacked adapter has a different byte
hash from the original Pika BF16 adapter. Pin the graph's exact file and do not
claim the two packages are byte-identical or swap them without revalidation.
The saved source graph uses 1344×768, 124 frames; the proposed 480p portrait
bucket/frame count is an explicit derived configuration requiring validation.

## Rights and deployment route

The published Pika adapters retain the **MiniMax H3 Community License**; the
example-code Apache license does not replace the weights' license. The current
license names EU, UK, South Korea and US exclusions and restricts use/display of
outputs outside its applicable territory. Global release therefore remains
unresolved under the current project requirement. Do not seed fake eligible
rights records to clear this benchmark. [Published license](https://huggingface.co/Pika-Labs/Pika-H3-Flex/blob/main/LICENSE).

Keep the selected model. Resolve the operating route explicitly: permission for
the actual compute, operator/reviewer locations and private benchmark access, and
written evidence for the intended release territories before release. A hosted
Pika agreement would require its own verified terms; it is not automatically an
override of the local-weight license. No contact with a vendor is authorized here.

**Hardware:** A40 48 GB baseline, minimum 64 GB host RAM as a planning floor, actual
memory fit unproven. Pika's official CLI examples use H100 80 GB, which is excluded
by this project's GPU rule. This does not prove A40 failure or success. A supported
offload/quantized Comfy route needs its own fit and fidelity check. No automatic
upgrade to A100/H100, GPU parallelism or wider allowlist.

## Eight-shot matrix and repeat plan

[shots.csv](t031-benchmark/shots.csv) contains the original test lines, English
meaning, speaker, action, required observations and reference roles. These are
proposed test scripts, not certified Thai translations or production canon.

| IDs | Shot class | Primary failure to detect |
|---|---|---|
| S01–S02 | Two dialogue close-ups | Names, amounts, negation, Thai clarity, speaker and mouth timing |
| S03–S04 | Two two-speaker exchanges | Turn-taking, wrong speaker, overlap and eyeline |
| S05–S06 | Two restrained emotional performances | Same recognizable voice/face under grief and anger; no exaggerated delivery |
| S07 | Prop interaction | Same envelope, owner/hand, object count and spoken meaning |
| S08 | Deliberate scene/costume change | Same person/voice, new setting and outfit; no stale wardrobe |

Each configuration has **8 shots × 3 independently seeded repeats = 24 planned
samples**, maximum one generation attempt per sample in this proposed experiment.
Replicates are not repair retries. Any repair study or replacement sample needs
remaining reserved funds and an explicit predeclared allowance; do not discard
failed samples or generate until one passes. `trials.csv` fixes sample IDs/seeds.

Start with S01-R1, S03-R1 and S07-R1 as a three-sample screen included in the 24.
Stop the configuration after that screen if native Thai speech, reference controls,
memory fit or output retrieval is unusable. The other 21 samples are conditional;
do not spend them merely to fill a table. A failed screen is a valid feasibility
result. Do not substitute dubbing, a different model, or manual lip repair.

Cold startup is measured once per actual acquisition. Warm timing is the full
submit-to-checksummed-durable-output duration, including encoding, decoding,
audio and download. Preserve sampler-only timing separately. Screening pauses for
human examination must happen with the GPU shut down; any reacquisition is a new
cold start and counts against the same experiment envelope.

## Proposed quality and economic decision rules

These thresholds are proposals for sign-off, not already measured acceptance.

- Pass A observes/listens to actual outputs without intended script or rationale;
  save independent transcript, speaker/visual observations and checked time ranges.
  Pass B compares the frozen observations against intended lines/references.
- Every accepted clip has zero critical wrong name/amount/negation/meaning,
  wrong-speaker, identity, outfit, prop-owner or missing-audio errors. ASR agreement
  alone does not establish pronunciation or emotion.
- Proposed lip timing limit: no clearly observable mismatch over 200 ms on a
  visible speaking face; record evaluator/measurement confidence. Unmeasured is
  UNKNOWN, not PASS. Check beginning, middle, end and both sides of every turn.
- Proposed subjective minimum: 4/5 for Thai intelligibility, speaker consistency,
  restrained emotion and mobile visual/audio usability, with zero critical errors.
  Any Thai listener used for one-time calibration must be explicitly available and
  permitted to access the output; this is not a new recurring episode approval.
  If calibration is unavailable, report that quality dimension unqualified.
- Proposed screen continuation: all three samples technically complete and no
  critical speech/control defect. Proposed full configuration threshold: at least
  20/24 accepted overall and at least 2/3 accepted in every shot class. This small
  set is a feasibility screen, not ten-episode reliability proof.
- Preserve all attempt costs. Report billed experiment dollars / accepted retained
  seconds, per-class acceptance and projected 180/300-second episode cost. If zero
  seconds are accepted, cost per accepted second is undefined, never zero.
- Episode fit requires **all** variable work, failures, reference allocation,
  writing, audio, QA, editing/storage and management ≤ $10. Do not extrapolate
  sampler speed as full episode cost or spend the entire $10 on GPU footage.

## Proposed envelope — NOT approved

One Ref2VA 480p configuration; one GPU; **$8 maximum new experiment exposure**,
at most **4 aggregate GPU hours**, with each lease separately bounded and quoted.
The 24 samples are a maximum, not a completion promise. A 4-hour lease is not
claimed to be supported by the current canary CLI.

| Component | Planning ceiling | Basis |
|---|---:|---|
| Compute | $3.44 | 4 h × allowed quote ceiling $0.86/h; A40's historical $0.59/h is not today's quote |
| Running storage | $0.11 | Proposed 100 GB container + 100 GB volume; 4 h × 200 GB × $0.10 / 730 h |
| Failed-delete storage tail | $1.98 | 100 GB volume × $0.20 / 730 h × 72 h; operational recovery must occur before that exposure is exhausted |
| Reference/voice preparation | $0.50 | Proposed maximum; no generation provider selected or authorized |
| Observation / ASR / comparison | $0.70 | Proposed maximum; model route, prices and coverage pending |
| Host encoding / transfer | $0.30 | Proposed allowance; actual metering/egress terms must be established |
| Shutdown / rounding reserve | $0.97 | Remaining reserved headroom |
| **Total new exposure** | **$8.00** | Conservative planning sum; recalculate from refreshed quotes before sign-off |

Storage rates were checked against [RunPod documentation](https://docs.runpod.io/pods/pricing).
730 hours/month is planning arithmetic, not a claim about provider invoice periods.
Weight/image disk fit is unproven: full upstream packages can exceed this disk
proposal. Fetch only the selected verified components; if they do not fit, stop
and revise sizes/cost before approval. Never download into an undersized paid pod.

Previous canary spending remains attributed to its existing durable account. The
night's ~$0.9 is approximate; only run 14's recorded settlement is exact here.
Reconcile total prior settled/pending/held exposure before deciding whether $8 of
new work fits the applicable $10 account cap. Do not reset accounts, mint episodes
or split authorizations to evade an exhausted allowance. A dedicated research
envelope, if needed, requires an explicit policy decision; none is created here.

Stop new dispatch on budget/time/storage/attempt exhaustion, unexpected price,
schema/pin mismatch, unsupported controls, missing rights, OOM, corrupt/incomplete
outputs or ambiguous create/submit. Reconcile ambiguous effects; never blind retry.
Run the independent janitor through verified termination/storage closure and keep
holds until actual billing finality. A budget overrun discovered later is recorded
and quarantines the configuration; it is not edited away.

## Execution readiness and exact next work

| Item | State | Next action |
|---|---|---|
| Stub canary | COMPLETE, BILLED recorded | Preserve completion/billing evidence and prior spend |
| Selected model/audio | FIXED by operator | Pika H3 Flex, native audio; no default external TTS |
| Source workflow/adapters | Research revisions and hashes recorded | Download/verify exact required components only during separately authorized setup |
| Canary-night code review | FIX REQUIRED, 6 Nov; 150 focused tests pass | Address R1 rounding/R2 redaction in [review report](T031-canary-night-review.md); see [integration spec](T031-integration-spec.md) |
| A40 model fit and compatible graph | NOT PROVEN | Build/test real-model image and binder offline where possible; distinguish driverless checks from GPU proof |
| Full benchmark dispatch | NOT IMPLEMENTED/ACCEPTED for this matrix | Existing canary global attempt cap is ≤3; design a durable aggregate experiment envelope/resume path before a 24-sample run |
| Rights, assets, voices, evaluators | OPEN | Record actual permissions, content hashes, access location and evaluation coverage |
| Budget / quote / hard stop | PROPOSED, UNSIGNED | Reconcile prior account exposure, capture current quote, then fill executable authorization |

Do not silently raise the canary cap or launch eight independent $8 canaries.
An experiment runner must reserve shared worst-case exposure, retain every sample
and failed attempt, persist a unique experiment/sample identity before effects,
reconcile restart/unknown outcomes, and account for all cold starts and storage
tails. Prove those properties offline before treating it as an executable path.
Any implementation touching spend/lifecycle follows the project's Large-work
spec → GLM Goldfish → findings resolution → build → independent review flow.
This preparation task does not implement or approve that change.

**Sign-off remains blank:** operator, actual rights route/access territories,
configuration/runtime manifest hash, exact GPU/current quote, total remaining
account budget, experiment cap, lease hard stops, storage sizes, maximum samples,
evaluator coverage and execution-command/preflight hash. Fill all of them after
the readiness gaps close; then request approval of that concrete run.

Steps 1–3 update: [review complete with open findings](T031-canary-night-review.md);
[implementation design](T031-integration-spec.md) awaits required Goldfish review
(quota-refused exit 75). Integration and 24-sample runner are not yet built.
See [resume instructions](T031-STEPS-1-3-RESUME.md).

T031 remains IN_PROGRESS, not qualified. T032–T035 and both existing application
human gates remain unchanged. No provider resources, paid model calls, messages,
publishing, pushes or production database changes were made by this preparation.
