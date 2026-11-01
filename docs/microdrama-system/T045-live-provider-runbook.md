# T045 live provider adapter notes

This is implementation guidance for T031. T045 does not authorize a Pod, paid prompt,
rights route, or public action. The live bootstrap remains blocked on durable billing
allocation/finality integration, so there is intentionally no executable canary command
here. Do not call the provider adapter directly.

## Integrator status (T045 bootstrap)

`microdrama.pipeline.live_world.build_live_benchmark_world` is the only intended composition
entrypoint. It checks `PAID_BENCHMARK`, both explicit paid/cloud flags, no public-action
capacity, `credref:` names, current quote/evidence expiry, rights and workflow callbacks,
and matching image/GPU/namespace pins before constructing clients. Construction performs no
DNS, credential resolution, or provider request. The provider clients additionally require
durable reservation/operation context at each effect boundary.

Composition remains blocked until the billing owner wires durable Runpod bucket allocation
and provider-finality state into lease settlement and the independent GPU janitor. The
Runpod REST adapter's empty per-interval `usage()` result is unknown usage; it must never be
used to release a reservation or report zero cost. Raw billing history remains
`PENDING_PROVIDER_FINALITY`, not a per-lease receipt. No live canary command is available
until this blocker is cleared and T031 separately authorizes the bounded run.

The current database registries also cannot attest every live route property yet. The
integrator validates the exact current rights route/subject/version, enabled preset/version,
workflow hash, preset controls, mapped template node classes, image digest, GPU/RAM allowlist,
and quote timestamp/rates/storage/exposure before composition. The mapped node-class hash is
not a ComfyUI input-schema digest; `PresetRecord` has no durable field for that schema or for
maximum output controls/resolution/duration. `RunpodQuoteAttestation` has no stable quote ID,
currency, persistent-volume size, or reservation-backed maximum storage exposure. A guardian
contract change should add those current evidence fields and bind the selected T031 quote and
Comfy node schema/output ceilings to the persisted benchmark/preset record. Until then, those
checks remain evidence blockers even after billing settlement is available.

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
