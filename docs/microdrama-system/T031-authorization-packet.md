# T031 canary — authorization packet (prepared 2 November 2026, NOT run)

This packet asks the operator to approve **one bounded Runpod/Comfy canary**. The canary is T031's
first step: it proves Drama Box's own lease → reserve → submit → durable output → verified shutdown
→ billing path on a real Pod. It is **not** the full T031 benchmark (8 shots × 3 repeats per
configuration, Thai voice/quality comparison). That benchmark needs its own authorization once this
canary's results are in.

Nothing here has been executed. No Pod, paid request or provider call has been made.

## 1. Preconditions — every box must be true before `execute`

- [x] **T045 is DONE** in `task_status.csv` (2026-11-04): T045-A/B built, the full fix round
      (sessions 1–7) closed by a three-round Codex review cycle ending ACCEPT, and the
      orchestrator confirmed `make check` (unit 2770 / contract 462 / integration 268) and
      `make pilot` (two HUMAN gates, 16 exports, 303,000 synthetic micro-USD) at the final
      HEAD under CPUQuota=45%. The commands in §5 are the final CLI as the runbook states
      them.
- [ ] **The RunPod API key is rotated.** On 2026-11-02 the old key was printed into a GLM build
      session, which sends its output to z.ai.
  - Create the new key in the Runpod console.
  - Store it **only** in a root-owned 0600 file outside every repo and outside `~/.claude/.env`, for
    example `/root/.secrets/drama-box/runpod-canary.key`.
  - Register it as `credref:runpod-drama-box-canary` with store kind `FILE`. The database stores
    only the ref name and the locator, never the value.
  - No GLM or Codex session may run with this file readable in its environment.
- [ ] **The Runpod account is isolated.**
  - Preferred: a separate Runpod account or team for Drama Box, with auto-pay off and credit topped
    up to at most the spend cap + $1. On a prepaid balance, that balance is then a hard ceiling the
    provider enforces.
  - Fallback: the shared account (it also runs the PPV pods), with pod-scoped invoice evidence. The
    janitor only touches Pods with the owned-name namespace.
- [ ] **A rights route is chosen** (section 2) and recorded as a current, eligible registry rights
      record: route id, subject, version, territories, evidence id, expiry.
- [ ] **Pins are recorded:** container image **digest**, workflow sha256, the `/object_info`
      node-schema sha256 of the mapped node classes, output-controls sha256, preset id and version.
- [ ] **A quote has been captured** from the Runpod console within the quote's validity window
      (section 3). The docs page does not list GPU prices.
- [ ] **A dedicated canary database exists** (§5, the `canary_db` commands; durable root defaults
      to `/var/lib/microdrama/canary-pg`, `--data-root` overrides). The T046 staging stack refuses
      PAID_BENCHMARK by design.
- [ ] **The Comfy endpoint credential**, if the image needs one, is a separate `credref:` in the
      same 0600 style.

## 2. Rights route — operator decision

| Route | Rights position (from the 2026-10-19 research, not legal advice) | Fit for this canary |
|-------|-------------------------------|---------------------|
| **A. Wan2.2 (official repo, Apache-2.0)**, image-to-video, silent, with separate Thai audio later | The model licence is permissive. Each accessory (text encoder, VAE, LoRAs, reference-image model, voice) still needs its own licence check. This is the research's "globally releasable fallback". | **Recommended for the canary.** The canary tests lifecycle and hardware, not H3 acting. Outputs stay private. |
| **B. MiniMax H3 community weights** | Licence V.4 restricts **displaying outputs** outside its permitted territory, including the US, EU and UK. It also requires attribution and further authorization above $20m revenue. This is not a global release route. | Only if the operator has read V.4 and records that a private internal benchmark viewed from Singapore is permitted. Release stays blocked either way. |
| **C. H3 with written MiniMax authorization** | Global, if granted. | Blocked on an external party. |

Approving route A for the canary does **not** clear any route for release. Release rights are T032/T033
evidence.

## 3. Quote (indicative; recapture at authorization time)

- **GPU allowlist:** A40 48 GB is the baseline. RTX A6000, L40, L40S and RTX 6000 Ada are allowed at
  ≤ $0.86/h. **Never A100 or H100** (operator rule, 2026-10-20). The attestation must list only the
  GPUs actually quoted.
- **Indicative compute price:** A40 $0.59/h. This is the operator's 2026-10-20 note, **not today's
  console price**. Record the live console price, the quote id and the capture time in the
  authorization file. The quote expires 2 h after capture.
- **Storage** (docs.runpod.io/pods/pricing, read 2026-11-02; billed per second):
  - Container disk: $0.10/GB/month while running, not charged while stopped.
  - Volume disk: $0.10/GB/month running, **$0.20/GB/month stopped**, until the Pod is deleted.
  - Network volume: $0.07/GB/month. **Not used** in this canary.

## 4. Proposed caps (the operator sets the final figures)

| Cap | Proposed | Basis |
|-----|----------|-------|
| Max wall time | **90 min** (`max_wall_seconds=5400`); `hard_stop_utc` = start + 90 min | Covers a cold start with weight download plus 3 prompts. The deadline stops and terminates. |
| Prompts / attempts | **3 prompts (1 cold + 2 warm), 5 attempts max** | Lifecycle proof, not a benchmark |
| Container disk / volume | **50 GB / 100 GB**, no network volume, volume deleted at terminate | Sized to the image plus weights; reduce if the image bakes in the weights |
| GPU worst case | 1.5 h × $0.86 = **$1.29** | Top of the allowlist |
| Storage while running | 150 GB × $0.10 / 730 h × 1.5 h ≈ **$0.03** | |
| Stuck-volume exposure | 100 GB × $0.20 / 730 h × 72 h ≈ **$1.97** | Terminate fails and is noticed within 3 days |
| Shutdown / billing reserve | **$1.00** | |
| **Total spend cap** | **$5.00 = 5,000,000 micro-USD** | Sum $4.29, rounded up; under the SPEC §6 $10 episode cap |

## 5. Runner commands (final CLI, as the T045 runbook states them; T045 DONE 2026-11-04)

Run them from the operator's own shell only, never inside an agent session. The authorization file
lives outside the repo (`/root/.secrets/drama-box/…`). `MICRODRAMA_DATABASE_URL` is loopback-only
and never a CLI flag; `MICRODRAMA_OBJECT_STORE_ROOT` must be an **absolute** path — `execute`,
`sweep` and `invoice` refuse with exit 2 without one. The Comfy endpoint is never a flag: it is
late-bound from the created Pod's own proxy URL. `preflight` reads and writes no object store.

```bash
cd /root/AIVORA/drama-box/microdrama
export MICRODRAMA_EXECUTION_MODE=PAID_BENCHMARK
export MICRODRAMA_PAID_REQUESTS_ENABLED=true
export MICRODRAMA_CLOUD_RESOURCES_ENABLED=true
export MICRODRAMA_DATABASE_URL='<dedicated canary DB, loopback>'
export MICRODRAMA_OBJECT_STORE_ROOT=/var/lib/microdrama/canary-objects

# The dedicated canary database (durable root defaults to /var/lib/microdrama/canary-pg)
make canary-db                                            # up;   or: python tools/canary_db.py up
python tools/canary_db.py status                          # prints the DSN, stored in out/canary-db.json
python tools/canary_db.py down                            # when finished

# 1. Preflight: no network, no credential values; prints the plan and authorization_sha256
.venv/bin/python -m microdrama.pipeline.canary preflight \
  --authorization /root/.secrets/drama-box/t031-canary-auth.json

# 2. Execute: only with the sha256 preflight printed, only before the authorized hard stop
.venv/bin/python -m microdrama.pipeline.canary execute \
  --authorization /root/.secrets/drama-box/t031-canary-auth.json \
  --authorization-sha256 <hex-from-preflight> \
  --prompts /root/.secrets/drama-box/t031-canary-prompts.json

# 3. One janitor pass over the same attested world (any time after the run)
.venv/bin/python -m microdrama.pipeline.canary sweep \
  --authorization /root/.secrets/drama-box/t031-canary-auth.json \
  --authorization-sha256 <hex-from-preflight>

# 4. Verify the operator's period invoice once Runpod invoices the canary.
#    --source is INVOICE or CONSOLE; --evidence is the exported file; --observed-at
#    (optional, ISO-8601) records when the operator observed the invoice.
.venv/bin/python -m microdrama.pipeline.canary invoice \
  --authorization /root/.secrets/drama-box/t031-canary-auth.json \
  --pod-id <pod-id> --period-start <iso> --period-end <iso> \
  --amount-micro-usd <int> --source INVOICE --evidence <invoice-file> \
  [--observed-at <iso-8601>]
```

The authorization file itself (schema and a fake-valued example:
`microdrama/runbooks/canary-authorization.example.json`, which loads through the real parser in
tests) must carry, among the runbook's fields: the `episode_id` the canary is attributed to, the
**full image reference** `<registry>/<repo>@sha256:<64 hex>` for the pinned Pod image, and
`max_attempts` as **one global cap** (there is no per-prompt attempts field).

## 6. Stop conditions (the runner enforces them; the operator watches for them)

- Any ambiguity (create or submit timeout without a provable outcome) → stop for a human. Never a
  blind retry.
- `/object_info` digest ≠ pinned node schema → stop and terminate before the first prompt.
- The hard stop or `max_wall_seconds` is reached → stop and terminate. The janitor is the
  independent backstop.
- The reservation would exceed the cap, or the quote has expired → refused before any effect.
- After the run, the hold stays (`PENDING_PROVIDER_FINALITY`) until invoice evidence matches. A
  mismatch → `DISPUTED`: the hold is kept and the result is reported as not qualified.

## 7. Outputs the operator gets

- `microdrama/evidence/provider-qualification/<utc>-canary.json`, holding the runbook's canary-record
  fields: quote, caps, pins, reservation/lease/Pod/prompt ids, output keys with byte length and
  sha256, stop/terminate verification, janitor observation, billing readiness.
- Billed cost is shown as **pending** until step 3. Provider-reported bucket amounts are never
  relabelled as billed.

## 8. Sign-off

| Item | Operator value |
|------|----------------|
| Change reference | |
| Rights route (A / B / C) and evidence id | |
| GPU and console price/hour, quote id, capture time UTC | |
| Spend cap (micro-USD) | |
| Max wall time, hard stop UTC | |
| Disk sizes (container / volume) | |
| Key rotated (date) and credref name | |
| Isolated account (yes/no; prepaid balance) | |
| Approved by / date | |
