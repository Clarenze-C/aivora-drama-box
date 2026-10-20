# Optimized local generation: correction to the cost model

Checked 19 October 2026 after the user's follow-up. No GPU renders were performed. All episode costs below are conditional arithmetic, not measured episode-production costs.

**Subsequent confirmed scope:** the current design is fully automated between season approval and final-video approval, with automatic agency-style post management and **US$10 variable costs per episode**. See [automation-plan.md](automation-plan.md). The owner-editing time illustrations below explain the earlier model; they are not recurring editing tasks in the current workflow. Track only actual season/final-review time and exceptions separately.

**Correction:** the original plan's API output prices and slow, explicitly unmeasured local timing scenarios were insufficient to assess an optimized local business model. FastH3, distilled turbo LoRAs and SageAttention belong in the initial feasibility comparison. The $271–$2,668 all-in scenarios are not predictions of the minimum achievable cost; they combine particular human-labor budgets with API-like generation charges. Neither the rendering times nor the 9–39 labor hours per episode had been established by a pilot.

**What the sources establish**

| Mechanism | Evidence and interpretation |
|---|---|
| FastH3 distilled models | The FastVideo maintainers document four-forward and eight-forward checkpoints. Their current cookbook lists FastH3 text-to-audio/video paths separately from full-H3 first/last-frame and reference paths. A fast T2VA result does not establish identical reference conditioning on every distilled variant. [FastVideo repository](https://github.com/hao-ai-lab/FastVideo), [mode matrix](https://haoailab.com/FastVideo/cookbook/minimax-h3/) |
| Turbo LoRA workflows | Community workflow authors publish four-step reference and eight-step first/last-frame graphs. Exact base checkpoint, LoRA, scheduler and supported conditioning must match. These are implementations to benchmark, not invented options. [Workflow repository](https://github.com/ssssssanjiu/minimax-h3-turbo/blob/main/README.en.md) |
| SageAttention / KJ patch | SageAttention accelerates attention kernels. KJ's source contains an attention-override node requiring the library. A kernel speedup is not a guaranteed whole-job speedup. Confirm actual backend activation and avoid applying the same attention patch twice. [SageAttention authors](https://github.com/thu-ml/SageAttention), [KJ implementation](https://github.com/kijai/ComfyUI-KJNodes/blob/main/nodes/model_optimization_nodes.py) |
| Consumer-GPU speed evidence | A community author reports roughly 16–19 seconds per 362-frame clip on one RTX 5090 at 448×448 with a particular four-step setup; its tables separate sampler and full-pipeline timing and show quality tradeoffs. This is self-reported first-hand evidence, not independently reproduced here. It supports the cheap-compute hypothesis, without validating portrait 768p, Thai speech or persistent cast. [First-hand timing report](https://huggingface.co/datasets/jacokon/fasth3-live/blob/main/README.md) |
| Reference-capable fused turbo | A publisher supplies a fused FL2VA/Ref2VA turbo checkpoint, but reports 76 seconds for a 10-second 1152×640 clip on an RTX PRO 6000 96GB using a specific four-step sparse-attention setup. That figure belongs to those settings, not a 5090 or 3090. [Model publisher's card](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) |

These sources make 15–20-second generation claims credible enough to test. They do not establish that every five-second Thai drama shot will take that time. Some fast routes lower resolution, use approximate caching/sparsity, interpolate frames, or use a preview decoder. Record which changes preserve the quality needed for final release. Quantization is a memory/precision change whose speed benefit depends on kernels and hardware; it is not automatically another multiplicative speedup.

**Episode arithmetic**

For a 300-second final episode built from five-second retained shots:

`60 shots × 15–20 seconds/shot = 900–1,200 seconds = 15–20 minutes`.

This is correct if all clips are accepted, all generated seconds are retained and the timing includes the complete generation path. It is a first-pass runtime estimate, not a maximum. The table assumes the same 20-minute wall time on each GPU purely to expose price arithmetic; **the same runtime has not been established across GPUs**.

| Conditional GPU workload | At $0.50/h | At $0.89/h | At $1.19/h |
|---|---:|---:|---:|
| 20 min, one take per shot | $0.17 | $0.30 | $0.40 |
| 40 min, average two takes | $0.33 | $0.59 | $0.79 |
| 60 min, average three takes | $0.50 | $0.89 | $1.19 |
| 100 min, average five takes | $0.83 | $1.48 | $1.98 |

Runpod's checked pricing page lists RTX 3090 $0.50/h, RTX 4090 $0.89/h and RTX 5090 $1.19/h. Availability, region and host RAM differ; use the actual offered instance. A 5090 timing cannot be combined with the 3090 rental price as though measured together. [Runpod current pricing](https://www.runpod.io/pricing).

Below $0.20 for 20 minutes requires a rate below $0.60/h. At $0.89/h the same first pass is $0.297, which remains cheap. Persistent storage, model downloads, startup/compilation, idle review time, CPU encoding, image/reference generation, TTS/LLM usage and subscriptions are additional. Batch episodes within a warm session, cache valid reference assets and stop idle compute. Cache text embeddings only when inputs match; new dialogue/prompts may require new encoding.

General formula:

`GPU dollars = hourly rate × [(final seconds / generated seconds per shot) × full-job seconds per shot × average total takes × generated/retained factor + startup/compile seconds + billed idle seconds] / 3600`.

This linear formula is valid only at the measured shot duration/settings. A 15-second shot does not necessarily take three times a five-second shot. For example, 60 five-second shots at 20 seconds each, three takes average, 1.2 duration overhead and ten minutes startup take 82 billed minutes: $1.22 on a $0.89/h pod or $1.63 at $1.19/h. Those are assumptions, not an observed Thai production run.

**Do not multiply overlapping speedup claims**

If a reported 20-second run already includes the turbo checkpoint and SageAttention, do not divide it by another turbo factor and another Sage factor. If attention occupied 60% of runtime and became 3× faster, the overall speedup would be `1 / (0.4 + 0.6/3) = 1.67×`; the other work remains. Reducing denoising steps can make decode, encoding or transfers the new bottleneck. A memory-saving node may improve fit without improving speed.

**Business-cost interpretation**

There are three different costs to measure: (1) GPU inference; (2) recurring cash services, including bought labor; (3) economic cost including owner time and setup amortization. Low GPU cost makes a lean pipeline worth testing. It does not prove a high labor budget is necessary, or that quality control can be entirely automated.

At the original base labor assumptions, replacing $74.88 of API generation with $1 of local compute lowers the four-minute episode estimate from $850.86 to about $765.90 including its 15% contingency. The remaining amount is principally the assumed $615 labor budget plus other services. That is an explanation of the old model, not a recommendation to spend it.

For a lean owner-operated example, if a five-minute episode uses $1 GPU, $3 other variable services and 45 minutes of owner work valued at $20/h, its contribution cost is $19 before allocated fixed tools, setup, bought specialist/voice work and tax. If review takes three hours instead, the same illustration becomes $64. Those inputs are targets/sensitivities, not estimates from production evidence. Track owner time separately so an apparently cheap pipeline does not hide an unmanageable workload.

**Revised benchmark**

Use the same original cast and Thai audio to compare: (A) full H3 with working SageAttention baseline; (B) a compatible four-step reference-capable turbo path; (C) its eight-step alternative; (D) a FastH3 distilled route where the needed conditioning is actually supported. Do not compare different modes as though controls were identical. Begin with 480p drafts and the intended final portrait resolution as separate results.

Use eight representative five-second shots: two dialogue close-ups, two two-speaker exchanges, two restrained emotional performances, one prop interaction and one deliberate scene/costume change. Repeat each three times per viable configuration. Measure cold start once; time warm jobs from submission to complete video/audio file, including text/reference encoding and VAE decode, not just the sampler. Record GPU and host RAM, source commits, precision, attention backend, frame count/resolution, actual source audio and seeds. Blind-review identity, Thai accuracy, speaker matching, lip timing and emotion.

Compare dollars and human minutes per accepted finished minute. A slower eight-step setting may be cheaper overall if it avoids repeated rejections. Use a preagreed experimental cap and retain unsuccessful outputs. No actual GPU benchmark has been run here.

Speed derivatives still need their own license review, including upstream H3 restrictions. Optimizations do not themselves resolve the global-release rights issue identified in the main plan.
