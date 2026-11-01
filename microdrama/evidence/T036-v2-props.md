# T036 — prop/outfit routing correction

Contract package 2.10.0. Offline/fake-provider evidence only; no paid or
public action.

Dialogue `staging.prop_ids` and scene props compile into `Shot.prop_ids`, never
`outfit_ids`. V1 corrupt manifests remain readable for audit and explicitly
not V2-ready. The V2 resolver binds each requested prop to the exact current
PropSheet ID/version/hash and a semantic PROP reference. W05 and repair now
build and persist a hash-sealed PromptManifest before reservation and pass the
manifest's exact asset IDs into RenderRequest. Missing/unknown/stale/retired
prop records fail before a budget hold or provider operation. The ordinary
same-key retry reuses its request/job/reservation. A prop-free V1 path remains
supported.

Scoped test receipts: 21 prop/reference/routing/W05 tests passed and Ruff
passed. Independent review closed the optional-preflight bypass and confirmed
the prop-bearing W05 and repair paths. It identified a separate T041
requirement: identity/location and other non-prop bindings still need full
record-hash, validity, rights and workflow-control validation before paid V2
dispatch.

Final integrated receipts under `systemd-run -p CPUQuota=45%`:

- `make check` exit 0: contracts 2.10.0 (97 schemas, 57 valid/126 invalid
  examples), Ruff, unit phase, 453 contract and 182 integration tests passed.
- `make pilot` exit 0: W01–W12, exactly two human approvals, 16 local exports,
  303,000 synthetic micro-USD settled.

The pilot and focused prop tests are software evidence, not real visual quality
or provider cost qualification.
