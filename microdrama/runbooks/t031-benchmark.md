# T031 benchmark operator notes

## Resume window after an uncertain prompt submission

Each prompt reservation expires 600 seconds (10 minutes) after it is created by
default. After a worker restart, resume reconciles the durable provider operation
through ComfyUI history and queue; it never submits the prompt again. Resume the
experiment within the hold window so the reservation remains active while that
reconciliation proceeds.

If the janitor expires the hold first, the resumed submit is refused. That refusal
is terminal for the experiment: its execution outcome becomes `FAILED`. The
operator can still reconcile the provider operation, clean up the owned pod, and
settle billing, but cannot reopen the experiment or dispatch another prompt.

## Re-issuing pre-existing LIVE seals (schema attestation source)

`BenchmarkSeal.schema_attestation_source` now defaults to `SELF_ASSERTED`, and
`BenchmarkAuthorization.validate_for` refuses a seal whose `schema_evidence` is
`LIVE_PROVIDER` unless the attestation source is `INDEPENDENT_RUNTIME_CAPTURE`.
Seals are operator-authored JSON recorded through `service.seal`, and no in-repo
tool sets this field, so:

- a genuine live seal captured before this field existed — or authored per the
  older docs — is refused with "self-asserted", fail-closed;
- fixing the field changes `sealed_sha256`, so the recorded authorization must
  be re-issued from the new seal bytes together with the seal (the byte SHA the
  CLI pins with `--authorization-sha256` changes with it).

Operator checklist for an existing live benchmark: re-capture (or re-enter) the
runtime schema attestation independently, set
`schema_attestation_source: "INDEPENDENT_RUNTIME_CAPTURE"` on the new seal, and
re-issue the authorization document against the new `sealed_sha256`.
