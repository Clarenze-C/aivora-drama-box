# T041b — typed reference, prompt and workflow binding

## Goal

Compose the approved EpisodePack and T041a DirectingManifest with T040's
current asset/wardrobe/state records into an exact-version PromptManifest,
RenderRequest and vendor workflow graph. Every visible character binds its
identity and assigned outfit; each shot binds its actual location, props and
series style, plus first/last/handoff frames when required. No positional
guessing or flat asset-list substitution may grant a semantic role.

## Ownership and source anchors

Worker writes only `microdrama/src/microdrama/references/` resolver modules,
`microdrama/src/microdrama/rendering/workflows/`, a new rendering V2 packet/
preflight module, and scoped tests in references/rendering/integration T041.
T041a story compiler and frozen 2.11.0 contract files are read-only. Existing
T036 prop path is `references/v2_planning.py` and `rendering/routing.py`;
T040 asset repository is in the same references module. Existing flat binder
is `rendering/workflows/binding.py:1–143`; the mock template is in
`rendering/workflows/templates.py`. T045 owns `pods`, `comfy_jobs` and live
transports concurrently; do not edit those paths. Integrator owns pipeline
registration and migration ordering. Propose a shared contract change if
necessary rather than inventing a local incompatible schema.

## Pre-dispatch invariants

Validate exact record IDs/versions/hashes, current asset state, valid time
intervals and authoritative current RightsRegistry route/subject/version for
every bound role before reservation or `object_info`/provider call. Resolve
one outfit per visible character from exact scene assignment; reject missing,
wrong-day, retired, contradictory or unrelated assets. Prompt text includes
only permitted current/revealed facts, exact role/source hash references and
state/action/edit intent. A source change invalidates only dependent shots and
derivatives. Required controls unsupported by a pinned preset/template block
before reservation. The workflow graph maps semantic roles to named controls,
including first/last/handoff, with no index-based inference. Unknown vendor
control mappings remain disabled.

## Acceptance and tests

Offline composed trace: short draft/pack → directed scene/beat/shot → current
typed identity/outfit/prop/location/style/frame assets → prompt manifest →
RenderRequest → bound workflow graph. Inject unknown prop, stale outfit,
retired rights, contradictory state, future secret, wrong role, changed hash
and unsupported control; assert no budget reservation/provider operation for
each. Show day-one office/next-day home change, silent visible character and
prop handoff; exact asset IDs survive to graph. Run scoped tests/Ruff, then
parent runs `make check` and `make pilot` under CPUQuota45%. No live paid/cloud/
public action, no commit. Return exact handoff for T042 and T047.
