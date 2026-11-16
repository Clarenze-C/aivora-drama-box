# T031 canary preparation and historical live attempt log — 4–5 November 2026

> **Current-status addendum, 6 November 2026:** run 14 completed and later invoice
> verification/sweep settled billing on 5 November. The earlier preparation-only
> paragraphs and run-8 “open defect #7” below are historical: `989bf12` subsequently
> persisted the pod ID before verification. The canary used stub-generated video;
> no H3/Thai quality acceptance follows. See the reconciled
> [close-out](../../docs/microdrama-system/T031-canary-closeout.md) and the next
> [Pika H3 Flex native-audio packet](../../docs/microdrama-system/T031-benchmark-packet.md).

## Live attempt log (night of 2026-11-04/05)

| Run | Outcome | Root cause | Spend |
|-----|---------|-----------|-------|
| run1 23:36Z | refused (PROVIDER_ERROR, masked) | preset GPU alias "A40" sent on create (unknown GPU type) | $0 |
| run2 23:41Z | refused (CONFLICT lease not live) | re-ran the same authorization → collided with run1's dead lease | $0 |
| run3 23:43Z | refused (masked) | same as run1 | $0 |
| run4 23:58Z | refused, error detail now visible (HTTP 422 Unknown GPU type: A40) | `gpu_type_allowlist` order loss fixed first (real, lesser bug); actual source: the render request carries the preset record's gpu_type verbatim | $0 |
| run5 00:05Z | **pod CREATED** (image pulled, port exposed ✓) then emergency-stopped; stop raced startup and failed; sweep's guard refused (no durable lease row for the pod id); pod `x1ghheymcrt0ry` terminated manually 00:10Z via RunPod API, verified 404 | runtime price check demanded EXACT equality with the quote; quote must be whole µUSD/GPU-second → no real rate can ever match | **~$0.05** (5 min × $0.59/h) |
| run6 00:14Z | refused (pilot rule: one live lease per episode) | five dead leases from runs 1-5 counted live | $0 |
| run7 00:25Z | pod CREATED; killed the run at T+1s ("pod exposes no endpoint"); pod terminated via API, verified gone | verify() treated a RUNNING pod without a runtime port mapping as a permanent conflict; the machine was still downloading the image | ~$0.04 |
| run8 00:49Z | pod CREATED; image downloaded (server up 00:54:36Z, proxy 200 ✓, stub nodes loaded ✓); runner stuck polling RunPod's lagging `runtime.ports` until Ctrl-C at ~01:47Z; **SIGINT cleanup did NOT stop the pod** — operator stopped+terminated it manually in the console ~01:55Z | endpoint derived only from runtime.ports, which lagged/never populated while the proxy served; and the crash-before-pod_id-persisted gap again left cleanup with nothing durable to act on | **~$0.62** (66 min) |

| run9 02:30Z | pod created, endpoint bound, first ComfyUI call → bare "HTTP error"; pod auto-terminated ✓ | ComfyUI errors masked status/body; AND the endpoint now binds at create (declared port), so the first call lands during container boot (proxy 502/404 = "still starting") | ~$0.02 |
| run10 02:48Z | first /object_info → Cloudflare **Error 1010 browser_signature_banned**; pod auto-terminated ✓ | RunPod's pod proxy (Cloudflare Browser Integrity Check) bans the stock `Python-urllib` User-Agent; curl passed all along | ~$0.02 |
| run11 03:00Z | object_info **MATCH** (first live); prompt composition refused | shipped example prompts carried a negative the mock workflow cannot bind (UnsupportedControl — correct refusal) | ~$0.02 |
| run12 03:12Z | **full lifecycle COMPLETE** but all renders MISSING_REQUIRED_OUTPUT (3 attempts) | real ComfyUI reports videos under the legacy "gifs" UI key; the job layer requires media kind "video" | ~$0.04 |
| run13 05:12Z | first submit died in 0.58s, connection-level; runner stopped for a human (correct, no blind retry); cause masked | transport uncertainty messages carried no cause | ~$0.01 |
| **run14 05:21Z** | **CANARY COMPLETE** | — | ~$0.05 |

## Run 14 — the canary record (2026-11-05T052140Z-canary.json)

- reserve → create (`xykul8kobl1e6s`) → endpoint bound → `/object_info` **MATCH** →
  prompt 0 **succeeded** (attempt 1) → prompt 1 **succeeded** (attempt 1) →
  shutdown; `outcome: COMPLETE`, attempts 2/3, prompts 2/2, deadline not hit.
- Outputs durably stored and checksum-verified on this host:
  - `renders/…/canary-0/a1/combine.mp4` — 38,171,044 B, sha256 `a79c8e0bdb9d485c0e232f25b5260df2cf8feafa978e9e64da12da9f6675e774`
  - `renders/…/canary-1/a1/combine.mp4` — 36,759,237 B, sha256 `2bf81cc11ba42031d6fea5530f899a0a3b380bb2432bfa7b3204ea4b9d008934`
- `billing_state: PENDING_PROVIDER_FINALITY` — honest by design; the lease
  settles BILLED only after the operator's period-invoice verification (step 4).
- Zero pods remain; every failed run's pod was auto-terminated from run 9 onward
  (defect 7's fix, verified live four times).

**Total night spend: ~$0.9 of the $5.00 cap (final figure lands with the invoice).**

**Eight defects found and fixed this night, each tests-first red→green:**
`092c0f7` provider error detail, `91d12ac` GPU allowlist order, `014bca8` seed
catalog GPU id, `ce23b83` price ceiling, `9ff7fe9` warmup transient + poll,
`0c79363` declared-port endpoint, `989bf12` pod id durable before verify,
`3866faa` Comfy boot-window retry, `27a8bc2` User-Agent, `a1f8456` example
prompts, `af09523` gifs→video media kind, `c703f7b` uncertainty causes.

**Remaining for T031:** ~~sweep~~ ~~invoice~~ **DONE 2026-11-05 15:45Z** —
bucket ingested and allocated to the microcent (GPU 35,174 µ + disk 579 µ =
35,753 µ), period invoice **MATCHED** (console evidence, sha `a6f1dea3…`),
final sweep **settled the lease BILLED at 35,174 µ**. Two more shipped defects
fell on the way (billing floats round to the micro-USD atom, `c65089a`;
invoice coverage accepts the provider-resolved window, `9b133f1`). The run-14
record plus this ledger are T031's canary qualification evidence. The FULL
benchmark (8 shots × 3 repeats, Thai voice/quality) needs its own authorization
per the packet — nothing here clears it.

Fixes this night, each tests-first red→green: provider error detail carried in
rejections (`092c0f7`), GPU allowlist order preserved (`91d12ac`), seed preset
recorded with the catalog GPU id (`014bca8`), price check treats the quote as a
ceiling (`ce23b83`), warmup-without-endpoint is transient + the canary polls
ensure_pod to the deadline (`9ff7fe9`), and the declared `8188/http` port
exposes the endpoint without waiting for runtime lag (`0c79363`).

**Open defect #7 (observed twice, not yet fixed): the runner only records the
provider pod id on the lease at ACTIVATE — every failure/interrupt between
create and activate leaves the pod invisible to its own cleanup (run5's
emergency stop, run8's SIGINT). The sweep's guard then correctly refuses to
touch an unrecorded owned-name pod. Fix direction: persist the pod id on the
lease row immediately after create, before verify/activate, so any later
failure can stop what it created.**

---

Operator instruction this session: "Execute T031 RunPod run. Spend cap $5."
Status at end of session: **every locally-derivable precondition is READY; one
artifact (the canary container image) does not exist yet and no paid provider
call was made.** Nothing here qualifies T031; it is preparation plus one shipped
defect fix.

## 1. Operator preconditions — verified state (2026-11-04T19:25Z)

| Packet §1 box | State | Evidence |
|---|---|---|
| T045 DONE | ✅ | ledger 2026-11-04, `1ce71cb` gates |
| RunPod key rotated | ✅ **verified via RunPod audit log** | `rpa_K1H83VJ447` deleted 2026-11-03T01:19:40Z; `rpa_MQQQRWRSOU` ("aivora-ovh-sg", account-wide) created 2026-11-03T01:22:01Z, actor clarenze.c@gmail.com |
| Key stored per policy | ❌ operator step | currently in `~/.claude/.env` (per operator message); must move to `/root/.secrets/drama-box/runpod-canary.key` (0600) — packet forbids `.env` and the runner only resolves FILE credrefs |
| Account isolation | ✅ de facto | account reads: 0 pods, $0.00 spend in 7 days (fallback shared-account route, idle; janitor scoped to owned names) |
| Rights route | ✅ (fixture route by design) | canary DB seeds `route-video-fake` v1 / `model-output:qualified` / TH / `canary:rights-license`, LIVE_PROVIDER labels, ELIGIBLE |
| Pins recorded | ✅ all but image | computed with the real code paths (below); image digest pending the image build |
| Quote captured | ✅ live API read 19:25Z | A40 secure $0.59/h; **recorded as 590,400 µUSD/h = 164 µUSD/s** — `_gpu_second_price` refuses any rate not divisible into whole µUSD/GPU-second, and `canary_pod_config` requires the cap ≥ the pod's real hourly cost, so round UP. Quote window refreshes at sign-off (2 h validity) |
| Dedicated canary DB | ✅ up | loopback :41833, episode `1c0ffee0-0000-4000-8000-00000000cafe`, `out/canary-db.json` |
| Comfy endpoint credref | ✅ registered | both FILE credrefs inserted (names + paths only, no values) |

Live stock at 19:25Z: **no secure-cloud availability** on A40 / RTX A6000 / L40S
(anywhere); community A40 not offered; L40S secure $1.09/h would breach the
$0.86/h allowlist anyway. Stock is instantaneous — re-check at run time.

## 2. Shipped defect found and fixed (tests-first): canary CLI never opened its DB pool

- **Defect:** `microdrama/pipeline/canary.py main()` constructed `Database(...)`
  for preflight/execute/sweep/invoice but never called `.open()`; `Database.__init__`
  creates the pool with `open=False`. Every real invocation died with
  `psycopg_pool.PoolClosed` before the first gate. All prior `main(argv)` tests
  masked it via `monkeypatch.setattr(canary_module, "Database", lambda _dsn: db)`
  (test comment at tests/integration/pipeline/test_t045_canary_composed.py:1310
  said so outright). Reproduced live: first real `preflight` run died with
  `PoolClosed: the pool 'pool-2' is not open yet`.
- **Red:** new test `test_main_opens_and_uses_its_own_database_pool` (same file)
  runs `main(["preflight", …])` with the Database patch deliberately absent —
  failed `PoolClosed: the pool 'pool-3' is not open yet`.
- **Fix:** `main()` now does `db = Database(database_url).open()` and passes that
  `db` to the preflight and invoice branches (they previously built fresh unopened
  pools). `Database.open()` is now idempotent (`_opened` guard; `close()` resets
  it) so the test seam's already-open fixture is unaffected. The pool is not
  closed on exit: each canary command is a one-shot process and the seam shares
  one fixture db across sequential `main(argv)` calls.
- **Green receipts:** new test passed; whole file 38 passed in 28.69 s;
  `-k "database or pool or db_"` 20 passed; ruff clean on all three touched
  files; full `make check` receipt in §4.

## 3. Authorization draft (gates all green via real preflight)

`/root/.secrets/drama-box/t031-canary-auth.json` + `t031-canary-prompts.json`
(fixture smoke prompts, pins match the shipped example exactly). Preflight at
19:4xZ printed `canary preflight OK … authorization_sha256=a66dcfc59e8ed584
bf42fedb64fd66428883e1447b09fac5049706795f34bffe` (sha will change when the
image digest and run-time quote window are filled in).

Derived pin values (computed with `template_sha256`, `canonical_hash`,
`prompt_pin` against `PRESET_TEMPLATES["fake-quality-8step"]`):

- `workflow_sha256` af20bebe9b5c78b09cdff53abcc62ceb6337bfb22e1f80211f9d0e26940727d7
- `node_schema_sha256` 00416e6984d2833d310b99631367d6f901d932cbcc2c610e31cf4a5de0734b91
- `output_controls_sha256` 2cad3960324f15cf3e686873792c0d8d716dfcf0d744dc967ca5ca6dc9f95dba
- `preset_id` fake-quality-8step v1, required controls SEED + TEXT_PROMPT
- `prompt_sha256` 4c80f52b…aea8f03, 9f093c60…bff2701 (equal to the example file's)

Allowlist shape: `["NVIDIA A40", "A40"]` — the create request sends element [0]
verbatim (`runpod_transport.py` `"gpu": {"id": …[0]}`), while the seeded preset's
`gpu_type` is the literal `"A40"` (`canary_db._seed`), which live_world requires
inside `allowed_gpu_types`; both entries carry a 64 GB host-RAM profile.

Caps as authorized: spend 5,000,000 µUSD ($5, operator 2026-11-04), wall 90 min,
storage 100 GB, 2 prompts, 3 attempts (the packet §4's "5 attempts" contradicts
the shipped contract — `CanaryCaps` hard-caps attempts at 3).

## 4. Second shipped defect found and fixed (tests-first): create never declared the Comfy port

- **Defect:** `runpod_transport.py` built the create payload as
  `{name, image, gpu, disk, mounts?}` with **no `ports`**, but the transport later
  requires a runtime port `private == 8188` and the Comfy endpoint is
  `https://<pod-id>-8188.proxy.runpod.net`. RunPod serves that URL only when the
  HTTP port is declared **at creation** ("ports cannot be added to a running pod" —
  docs.runpod.io/pods/configuration/expose-ports, and the plugin's
  runpod-usage/reference/pod-workflows.md). Every real execute would have waited
  for a port that never appears, hit the deadline, and stopped+terminated. Tests
  never caught it: the fixture `_pod()` fabricates `runtime.ports` regardless of
  the create body.
- **Red:** `test_create_pod_declares_the_comfy_http_port`
  (tests/unit/rendering/test_runpod_transport.py) asserts the create body carries
  `ports == ["8188/http"]` — failed before the fix.
- **Fix:** the payload now includes `"ports": ["8188/http"]`. Green: transport
  file 16/16 + composed canary file 38/38 → 54 passed across both; ruff clean.
- v2 create schema cross-checked against the RunPod MCP `create-pod` definition
  (`ports: ["<port>/<protocol>", …]`, e.g. `["8888/http", "22/tcp"]`).

## 5. Canary image (operator chose: build now; "RunPod's registry" → corrected)

- **RunPod hosts no pushable registry** — its `create-registry` only stores pull
  credentials for an external registry. Plan: push PUBLIC to Docker Hub or GHCR;
  public images need no registry credential on the pod create.
- Image built from
  [deployment/canary-image/](../deployment/canary-image/): pytorch 2.7.1 cu126
  runtime base, **ComfyUI pinned to v0.3.77** (commit 59afc398), stub nodes
  (`FakeVideoModelSampler` deterministic from seed; `CheckpointLoaderSimple` and
  `VHS_VideoCombine` overrides), placeholder `fake-video-model.safetensors`,
  ffmpeg, `--listen 0.0.0.0:8188`. Local smoke runs use a `--cpu` arg override
  (the VPS has no NVIDIA driver); the image CMD stays GPU-native for the pod.
- **Why v0.3.77 and not HEAD:** every ComfyUI tag in the v0.4x line imports
  `comfy_kitchen`/triton in `comfy/quant_ops.py`, which crashes at import on any
  GPU-less host (`RuntimeError: 0 active drivers` — verified with the first build
  against HEAD). Local CPU verification of the image is a hard requirement, so HEAD
  is not pinnable for the canary; v0.3.77 is the newest tag without that import
  (probed via raw.githubusercontent.com across v0.44.0…v0.3.30).
- **Why no real VideoHelperSuite:** VHS HEAD fails to import on v0.3.77
  (`comfy_api.v0_0_2.IO` missing), and the era-matched line (dc98c8b, 2025-06-22)
  imports fine but marks `loop_count`/`pingpong`/`save_output` REQUIRED — the
  repo binder sends exactly `{images, frame_rate, filename_prefix, format}` and
  ComfyUI 400s (`prompt_outputs_failed_validation`, verified live). The shipped
  image instead overrides `VHS_VideoCombine` in `canary_stub_nodes` with exactly
  the four contracted inputs, encoding via imageio-ffmpeg and reporting the
  standard `gifs` UI shape the client parses generically from `/history`
  (comfy_transport.py iterates every output key).
- Build gotchas hit: base image lacks `safetensors` (checkpoint step reordered
  after pip); a build was watchdog-killed (exit 143) while sharing the box with
  the full `make check` — builds and long gates must serialize on this host.
- `smoke_test_canary_image.py` proves the image against the repo binder's exact
  graph: /object_info exposes all four mapped classes, /prompt accepts, execution
  succeeds, output fetchable with sha256.
- **Receipt (2026-11-04, local `--cpu` run): SMOKE TEST PASSED** —
  `drama-canary:t031` (7.59 GB, pytorch 2.7.1-cu126 base + ComfyUI v0.3.77 +
  patch + stubs): all four mapped classes exposed; the binder graph accepted
  (prompt 77a56e3f/bab0b760); combine received the full (98,1280,720,3) batch;
  output fetched via `gifs`: **38,567,840 bytes,
  sha256=02b856b83c27aa05dcff6c33f70bc360a7f5783d5a53b2888e0eeddd25901a93**
  (left at `microdrama/out/canary-smoke-output/`). Ten build iterations were
  needed; the three image-shaping lessons: (1) custom nodes cannot override
  core class names on v0.3.77 → build-time core patch instead;
  (2) VHS_VideoCombine is overridden because no real VHS commit both imports on
  v0.3.77 and accepts only the four contracted inputs; (3) node FUNCTIONs must
  return TUPLES — a bare tensor return gets iterated by the execution engine and
  downstream `[node, 0]` links receive a single frame.

## 6. What still blocks `execute` (in order)

1. **Image digest**: build → smoke test → operator push (public) → paste digest
   into `pins.image_ref` → preflight re-print.
2. **Operator places the rotated key** outside `.env` (see §1) and a
   `comfy-canary.token` 0600 file; execute refuses until both exist.
3. **Refresh quote window + hard stop + §8 sign-off** (quote expires 2 h after
   capture; sha re-printed by preflight at that time).
4. **GPU stock** must be re-checked; at 19:25Z the whole allowlist read NONE.
5. §5 commands run from the **operator's shell** (packet rule: never inside an
   agent session).

## make check receipt

- First full run (both fixes in): **2769 passed, 1 failed** —
  `test_a_zero_amount_is_not_a_missing_amount` crashed on
  `Database(...).open()` because that refusal-path unit test's seam patches
  `canary_module.Database` to return **None**. Fix: open guarded (`if db is not
  None`), preserving the seam contract. The three touched files then passed
  together (83 passed: runner + transport + composed).
- **Full re-run receipt (2026-11-04, under CPUQuota=45%): `make check` — all
  offline checks passed. Unit 2,771 (2,770 prior + 1 new preflight test) /
  contract 462 / integration 269; EXIT=0.**
