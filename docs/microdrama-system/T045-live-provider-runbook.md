# T045 live provider adapter notes

This is implementation guidance for T031. T045 does not authorize a Pod, paid prompt,
rights route, or public action: the canary commands below are exercised by T045 only
inside pytest with fixture transports. Running `canary execute` for real is T031, under
the operator's authorization. Do not call the provider adapter directly.

## Integrator status (T045 bootstrap — unblocked by T045-B)

`microdrama.pipeline.live_world.build_live_benchmark_world` is the only intended composition
entrypoint. It checks `PAID_BENCHMARK`, both explicit paid/cloud flags, no public-action
capacity, `credref:` names, current quote/evidence expiry, rights and workflow callbacks,
and matching image/GPU/namespace/account-label pins before constructing clients. Construction
performs no DNS, credential resolution, or provider request. The provider clients additionally
require durable reservation/operation context at each effect boundary.

**T045-B (2 Nov): the composition is no longer blocked.** The builder takes a required
`BillingRepository`, composes the lease service and janitor behind `RunpodInvoiceFinality`,
computes `billing_state` from per-lease readiness, and the unconditional refusal is gone.
The janitor ingests the provider's billing buckets for owned Runpod pods whose leases are
not BILLED (exact micro-USD mapping; identical responses are replays that add nothing;
revised responses post only the delta), including pods already absent at the provider
through the durable `pod_leases` ownership proof (`terminate_verified_at` + account label).
The Runpod REST adapter's empty per-interval `usage()` result stays unknown usage and still
never releases a reservation or reports zero cost — only a MATCHED period invoice reaches
BILLED and releases the remainder.

The database registries still cannot attest every live route property: the mapped
node-class hash is not a ComfyUI input-schema digest, and `PresetRecord` has no durable
field for that schema or for maximum output controls/resolution/duration. **R10
limitation:** the canary authorization pins `node_schema_sha256` and
`output_controls_sha256` (and the required controls) instead — they are authorization
pins, not `PresetRecord` fields. `RunpodQuoteAttestation` now carries the quote id,
USD-only currency, persistent-volume size, maximum storage exposure and the
`provider_account_ref` label (written to `pod_leases` at claim and used in the bucket
identity). A guardian contract change that binds the Comfy node schema and output
ceilings to the persisted preset record remains open as a proposal, not a blocker.

## Required bootstrap contract before a canary

The integrator must supply one composed command that performs all checks below before its
first external effect:

1. Require `PAID_BENCHMARK`, explicit paid-request and cloud-resource flags, and credential
   reference names only. OFFLINE_MOCK must reject the transport before DNS/network access.
2. Resolve the selected current Runpod quote and Comfy route outside source control. Record
   quote timestamp, currency, compute rate, persistent/container storage rate and maximum
   exposure. No default GPU price is valid.
3. Verify current rights eligibility and the exact enabled preset/workflow/image digest,
   GPU allowlist, node schema, maximum duration/resolution and output controls.
4. Create durable reservation and operation/lease records before Pod creation or prompt
   submission. Use an isolated Runpod account/API key namespace and durable lease proof so
   reconciliation and janitor actions cannot target another workload.
5. On ambiguous create/submit, reconcile from durable identifiers and stop for human
   investigation when the provider cannot establish whether work exists. Never blind retry.
6. Copy and checksum complete outputs to durable storage, collect actual provider billing
   evidence, then stop/terminate and independently verify shutdown and storage state.

The Runpod REST v2 create request documents `name`, `image`, `gpu`, `disk`, and optional
`mounts`; it has no idempotency token or ownership-tag field. The adapter encodes its
namespace and a stable client-token hash in the Pod name, then reconciles through paginated
`GET /v2/pods`. A timeout with no visible match remains unknown because list absence does
not prove non-creation. Pod response `cost` is documented as its hourly compute rate and
is checked against the operator quote. The attestation also requires current container and
persistent-storage rates; the code does not supply defaults.

ComfyUI documents `POST /prompt` returning `prompt_id` and queue number or `error` and
`node_errors`. It does not document idempotent submit. Persist the prompt ID before any
poll/reconnect; after a timeout without an ID, mark the operation ambiguous and reconcile
without resubmitting. Success requires completed `/history/{prompt_id}`, fetched output,
media verification, durable copy and checksum—not a progress or `executed` event.

## Durable billing reconciliation contract (integrator acceptance required)

> **T045-A (2 Nov):** this contract is implemented for R0–R8 (see
> `microdrama/evidence/T045.md` and the finality addendum
> `T045-finality-spec.md`, which overrides the older text below where they differ).
> One operating assumption to verify at the first live canary: buckets are only stored
> once their end is at least a **settle lag of 15 minutes** behind the observation
> (`BillingRepository(settle_lag=...)`, default 15 min). This lag is an unverified
> assumption about how long Runpod keeps reshaping a bucket — not a documented fact —
> so it is configurable, and the first live ingest should confirm bucket amounts stop
> changing after that window.

Runpod's official `GET /v2/billing/pods` response is time-bucketed and supplies
`podId`, `startTime`, `endTime`, `totalAmount`, `gpuAmount`, `cpuAmount`, and `diskAmount`.
The request metadata reports the provider-resolved window. The current adapter preserves
these fields as raw provider history; it does not turn an hourly bucket into a per-second
`UsageReceipt` because a bucket may cross warm-pod lease transfers.

Before T031 can use this data for qualification, add a durable reconciliation layer with
the following contract:

1. Store each raw bucket under a stable identity `(provider_account_ref, pod_id,
   bucket_start_utc, bucket_end_utc, bucket_size)`. Keep each provider response as an
   append-only observation with its raw-body hash, observation time, resolved query window,
   currency, and exact integer micro-USD component amounts. Require total = GPU + CPU + disk;
   malformed or mismatched rows enter `DISPUTED` and cannot allocate.
2. Repeated identical observations are idempotent. If the amount for an existing bucket
   changes, append a new revision and an adjustment delta; never overwrite the earlier
   observation or emit a second copy of the full amount. Keep a monotonic provider-bucket
   revision for dedupe and audit.
3. Allocate the GPU and CPU components by measured overlap with durable Pod running and
   lease ownership intervals. Split a bucket across transferred warm leases by overlap
   seconds, using deterministic largest-remainder micro-USD allocation; the component
   allocations must sum exactly to the provider component. Any uncovered running interval
   goes to the original lease episode, or to a named recovery pool if the creator is
   unknown. Failed attempts remain in their owning episode's total.
4. Allocate disk component by an explicit persisted storage owner. For a new Pod, pin the
   creating episode as storage owner and charge its retained-volume exposure until verified
   volume deletion; container-disk exposure follows the same owner while running. If no
   episode can own it, keep it in recovery headroom. A warm-pod transfer never transfers
   stored bytes' historical charges to the receiving episode.
5. Persist allocations by `(bucket_revision, component, owner_kind, owner_id,
   allocation_basis)`, and enforce that each component revision is fully allocated once.
   Reconciliation and allocation happen in one transaction. A newer bucket revision
   creates only component deltas, including negative adjustments; credits never restore
   episode allowance.
6. Use explicit states `PENDING_PROVIDER_FINALITY`, `ALLOCATED_PROVIDER_REPORTED`,
   `INVOICE_VERIFIED`, and `DISPUTED`. Runpod's bucket response has no documented finality
   flag, so API observations stay pending provider finality. Do not release reserved
   exposure or call the amount settled from this endpoint alone. Invoice/console evidence
   with source/time/amount is a separate final verification step. Missing buckets and empty
   responses mean unknown, never zero.
7. Canonical episode receipts are emitted from the durable allocation ledger with
   `PROVIDER_REPORTED` basis and stable bucket-revision keys. Mark `BILLED` only after
   invoice verification. Do not feed full-hour bucket receipts into
   `BudgetService.record_gpu_interval`; it rejects/risks double attribution when intervals
   overlap or cross lease ownership.

This needs a shared persistence and budget-accounting change owned by the integrator. Until
that lands, the raw bucket history is review evidence only, and actual-cost qualification
is blocked even though the provider endpoint is implemented.

## The canary runner (T045-B; `python -m microdrama.pipeline.canary`)

One authorization document authorizes one bounded run. The exact commands (as T031's
packet must state them), run from `microdrama/` against the dedicated canary database:

```bash
# 1) validate the authorization and every gate; print the plan and the sha to approve
python -m microdrama.pipeline.canary preflight --authorization runbooks/canary-authorization.json

# 2) the bounded run itself, only with the sha preflight printed and only before the
#    hard stop (T031 authorizes this; T045 runs it only under pytest with fixture
#    transports). The Comfy endpoint is NEVER a flag: it is late-bound from the
#    created Pod's own proxy URL.
python -m microdrama.pipeline.canary execute \
  --authorization runbooks/canary-authorization.json \
  --authorization-sha256 <hex-from-preflight> \
  --prompts runbooks/canary-prompts.json

# 3) one janitor pass over the same attested world (any time after the run): stop and
#    terminate an owned stray Pod, ingest provider billing, run finality
python -m microdrama.pipeline.canary sweep \
  --authorization runbooks/canary-authorization.json \
  --authorization-sha256 <hex-from-preflight>

# 4) verify the operator's period invoice once Runpod invoices the canary
python -m microdrama.pipeline.canary invoice \
  --authorization runbooks/canary-authorization.json \
  --pod-id <pod-id> --period-start <iso> --period-end <iso> \
  --amount-micro-usd <int> --source INVOICE --evidence <invoice-file>
```

`preflight` (the default command) validates the authorization and every `live_world`
gate, resolves no credential value (it only checks the refs are well-formed `credref:`
names), performs no network access, and prints the plan — caps, pins, quote, hard stop,
the pinned Pod image (the full `<registry>/<repo>@sha256:<64 hex>` reference the
authorization carries and the create request sends as-is) — plus
`authorization_sha256=<hex>` (the sha256 of the authorization file bytes).

`execute --authorization-sha256 <hex>` refuses, typed and before any transport call,
on: a sha mismatch; `now ≥ hard_stop_utc`; an expired quote; a mode other than
PAID_BENCHMARK or a missing paid/cloud flag; a spend cap above `episode_cap_micro_usd`;
a non-loopback DSN (every libpq form is parsed; `PGHOST`/`PGHOSTADDR`/`PGSERVICE`
included); a database whose single budget-account episode is not the pinned
`episode_id`; or a prompt object whose content hash is not pinned. It then runs runbook
steps 1–6 through the composed `live_world` only: reserve → owned-name Pod create
(carrying the pinned full image reference); a bounded wait for the Pod's runtime port,
then the `/object_info` digest of the mapped node classes against the pinned
`node_schema_sha256` (a mismatch stops + terminates and submits nothing); bounded
prompt submits (≤ `max_prompts` distinct prompts, ≤ `max_attempts` **total submit
attempts across all prompts — a global cap**, no blind retries — ambiguity stops for a
human); output fetch → checksum → durable copy; stop → terminate → verified read-back
(the T045-A final-release path); janitor ingest. `hard_stop_utc`/`max_wall_seconds`
(and the rights record's `eligible_until`) are enforced by a deadline that stops and
terminates; SIGTERM/SIGINT run the same shutdown path before exit. The runner never
prints credential values, `Authorization` headers or the environment. Credentials
resolve ONLY through FILE credential refs whose secret file is owner-only (mode 0600
or 0400); ENV, VAULT and NONE refs are refused.

`sweep --authorization <file> --authorization-sha256 <hex>` composes the janitor over
the same attestation, pod config, credentials and durable state and runs ONE pass:
stop/terminate an owned stray Pod (a Pod that appears after a podless resolution is
adopted onto its lease, the resolution is marked contradicted, and its cost is ingested
as an adjustment on the settled hold), ingest provider billing, run finality. The
quote's expiry gates only the start, so the sweep stays possible after the run; it
submits no work and takes no reservation.

`invoice` wraps `verify_invoice_period` (R5) from operator evidence: account ref (from
the authorization), pod id, period, amount, evidence file (**only its sha256 is
stored**), source (`INVOICE`/`CONSOLE`), and the optional `--supersedes`/`--actor`/
`--reason` for an audited supersede. A MATCHED invoice lets the janitor's next sweep
settle the lease BILLED and release exactly the unused remainder; a mismatch keeps the
hold and marks the lease DISPUTED.

### Authorization schema (exactly the R11 list)

A fully worked example with obviously fake values ships at
`microdrama/runbooks/canary-authorization.example.json` (references use `credref:`
names only). Fields: `operator`, `change_ref`, `episode_id` (the pinned canary episode
the database must hold exactly one of, with its budget account), `hard_stop_utc`,
`max_wall_seconds`;
`quote` (R10 fields: `quote_id`, USD-only `currency`, `captured_at`, `expires_at`,
`compute_micro_usd_per_hour`, `container_disk_gb`,
`container_storage_micro_usd_per_gb_month`, `persistent_volume_gb`,
`persistent_storage_micro_usd_per_gb_month`, `max_storage_exposure_micro_usd`,
`allowed_gpu_types`, `host_ram_gb_by_gpu`, `maximum_runtime_ms`,
`maximum_exposure_micro_usd`); `caps` (`max_spend_micro_usd` — including storage
exposure and the shutdown reserve — `max_storage_gb`, `max_prompts`, `max_attempts`
≤ 3 — a **global cap on submit attempts across all prompts** in the run, and each
prompt also gets at most this many); `rights` (`rights_route_id`,
`rights_subject_ref`, `rights_subject_kind`, `rights_version`, `territories`,
`rights_evidence_id`, `eligible_until`); `pins`
(`image_ref` — the full `<registry>/<repo>@sha256:<64 hex>` reference, sent as-is on
create; `workflow_sha256`, `node_schema_sha256`, `output_controls_sha256`,
`preset_id`, `preset_version`, `required_controls`); `runpod_credential_ref` and
`comfy_credential_ref` (`credref:` names only — the canary CLI resolves them ONLY
from FILE stores whose secret file is mode 0600/0400); `namespace`;
`provider_account_ref` (an `acct:` label); and the prompt/reference inputs as content
hashes (`prompt_sha256`, `reference_sha256`). Validation rules worth knowing: the
hourly rate must be a whole number of micro-USD per GPU-second (integer ledger
prices), the spend cap cannot exceed the quote's exposure ceiling, the storage cap
cannot be below the quoted volume, `max_wall_seconds × 1000` must not exceed the
quote's `maximum_runtime_ms`, and prompt pins are sha256 of the canonical prompt
object (`{"text", "seed", "negative", ...}`) supplied at execute time via `--prompts`
and verified before anything is submitted.

### Canary record JSON

`execute` writes the runbook's "Canary record" fields as JSON to
`microdrama/evidence/provider-qualification/<utc-ts>-canary.json` — authorization sha,
operator/change ref, times and deadline, quote and caps, rights and pins, reservation
ids, lease id, client tokens, pod id, prompt ids, output object keys with sha256 and
byte length, shutdown/terminate verification, janitor summary, and per-lease
`billing_readiness` with an honest `billing_state`
(`PENDING_PROVIDER_FINALITY`/`AWAITING_INVOICE` until the invoice matches; never a
pretend BILLED).

### The dedicated canary database

The T046 staging stack refuses PAID_BENCHMARK, so the canary cannot use it. Stand up
the canary's own database instead (from `microdrama/`):

```bash
make canary-db            # or: python tools/canary_db.py up
python tools/canary_db.py status
python tools/canary_db.py down
```

It starts a fresh loopback PostgreSQL on a free port (never 8091 or 8093 and never a
running container's port), applies every migration, and seeds the canary's registries
(the rights route with real evidence labels so it stays eligible in PAID_BENCHMARK,
the enabled benchmark preset) plus one canary episode with its budget account. The
DSN is printed and stored in `out/canary-db.json`; run the canary with
`MICRODRAMA_DATABASE_URL` set to it. The runner resolves the single seeded canary
episode (oldest with a budget account) — the canary database must not be shared with
production data.

## Canary record (must be filled from live evidence)

- Authorization/change reference and operator:
- Start time UTC; hard stop time UTC; max wall duration:
- Runpod quote time UTC; exact GPU; compute price/currency:
- Container disk and volume/network volume sizes and storage price/currency:
- Maximum spend including storage exposure and shutdown reserve:
- Rights evidence ID/expiry/territory/output route:
- Container image digest; workflow hash; node schema hash; preset version:
- Reservation ID; lease ID; provider operation IDs; client token(s):
- Pod ID; independent ownership evidence:
- Comfy prompt ID(s); verified output object key(s), byte length and SHA-256:
- Actual billed usage receipt IDs/amounts/currency/time window (failed attempts included):
- Stop/terminate request and verified terminal state/time:
- Independent janitor observation and storage deletion/retention outcome:
- Remaining uncertainty, discrepancy, or reason qualification is blocked:

## Primary interface references

- [Runpod Pod management REST API](https://docs.runpod.io/pods/manage-pods)
- [Runpod GraphQL Pod lifecycle](https://docs.runpod.io/sdks/graphql/manage-pods)
- [Runpod Pod pricing](https://docs.runpod.io/pods/pricing)
- [Runpod Pod billing history](https://docs.runpod.io/api-reference-v2/billing/get-pod-billing-history)
- [ComfyUI server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
