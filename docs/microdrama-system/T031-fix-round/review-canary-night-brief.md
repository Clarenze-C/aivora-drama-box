# Codex review — T031 canary-night commits (money path)

Independent review, read-only. Repo `/root/AIVORA/drama-box`, branch
`feat/microdrama-m0-m4`. Scope: **`git diff 13da3e2...0851374`**. That is 24 commits,
27 files, +1,329/−63, of which 8 source files account for +207/−38. Claude Code sessions
wrote them during and after the live RunPod canary on 4–5 Nov. They have never been
independently reviewed. Your 4 Nov ACCEPT of T045 (up to `13da3e2`) does not cover them.

Ignore uncommitted files in the working tree; review only the committed range.

## What the range does

Fixes found while flying a real RunPod canary (rented A40, stub sampler, two test videos,
billed $0.036 for run 14):

- `3e16485` CLI pool open, create-request ports, canary image
- `092c0f7` / `ecd6b78` carry provider and ComfyUI error status and body in rejections
- `91d12ac` preserve the GPU allowlist order (create sent an arbitrary id)
- `014bca8` seed the canary preset with the RunPod catalog GPU id
- `ce23b83` runtime price check treats the quote as a ceiling, not equality
- `9ff7fe9` a RUNNING pod without an endpoint is warmup, not a conflict
- `0c79363` declared `8188/http` port exposes the endpoint without runtime lag
- `989bf12` bind the created pod to its lease before verification can fail (previously
  pods orphaned when a failure hit between create and activate)
- `3866faa` retry the `/object_info` gate through the ComfyUI boot window (proxy 502/404)
- `27a8bc2` send our own User-Agent (Cloudflare banned the stock Python-urllib UA)
- `a1f8456` shipped canary example prompts carried an unbindable negative
- `af09523` normalize ComfyUI's legacy `gifs` output key to the video kind
- `c703f7b` name the cause when the ComfyUI transport outcome is uncertain
- `c65089a` billing amounts round to the micro-USD atom instead of being rejected
- `9b133f1` invoice coverage accepts the provider-resolved query window
- plus docs and style commits

Source files: `budget/billing.py`, `persistence/db.py`, `pipeline/canary.py`,
`pipeline/live_world.py`, `rendering/comfy_transport.py`, `rendering/leases.py`,
`rendering/pods.py`, `rendering/runpod_transport.py` (all under `microdrama/src/microdrama/`),
plus their tests.

## Focus (money and safety first)

1. **Rounding and price checks:** no path may under-reserve or under-record cost.
   Check direction (ceil vs floor) in `c65089a` and `ce23b83`, the µUSD-per-second
   rule, and "quote as ceiling" — can a higher actual price now pass?
2. **Invoice matching (`9b133f1`):** can widening the accepted query window let an
   invoice match the wrong period or lease, or double-count across leases?
3. **Pod/lease lifecycle (`989bf12`, `9ff7fe9`, `0c79363`):** no duplicate pod create
   after a durable intent; no orphaned pod on any failure or interrupt between create
   and activate; warmup-vs-conflict can't mask a pod that belongs to another lease;
   cleanup and termination verification still hold.
4. **Retries (`3866faa`):** bounded; no duplicate prompt submission after an uncertain
   outcome; 502/404 "still starting" can't be confused with a terminal error after boot.
5. **Error bodies in rejections (`092c0f7`, `ecd6b78`, `c703f7b`):** provider response
   bodies must not leak secrets (API keys, auth headers, signed URLs) into exceptions,
   logs or persisted rows. Check for truncation and redaction.
6. **Tests:** fixes are tests-first; no existing assertion weakened; new tests prove the
   fix rather than restating the implementation.

## Constraints and output

- Your sandbox is read-only and cannot write files or run `systemd-run`. Review from
  code, `git show` and `git diff`, and in-memory reasoning. Do not run the
  integration suite.
- **Put the full report in your final message.** It is saved as the report.
- Per finding: ID (`CN-1`…), severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, the
  concrete failure scenario (inputs/state → wrong outcome), and a suggested fix.
  Report only what you can point to in code. Mark uncertainty explicitly.
- End with a verdict: **ACCEPT** or **FIX-REQUIRED**, plus a one-paragraph summary.
