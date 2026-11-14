**Verdict: APPROVE** — v0.3 (`17ad7e0`), limited to B1R2-1/B1R2-2 and defects introduced by their edits.

- **B1R3-1 — CLOSED (B1R2-1).** [§4, B1-design-note.md:494](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:494) specifies entry guards before legacy reads or early returns, explicitly covers `load_reference_context`, gives `route_shot` its own workflow-check transaction, and requires ancestry-validated scope for generic persistence. The shared fixture requires direct-call refusal with V3 episodes lacking legacy documents, alongside worker-path coverage.

- **B1R3-2 — CLOSED (B1R2-2).** [§4, B1-design-note.md:467](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/B1-design-note.md:467) derives planning scope through the referenced STORY LOCK approval, using its extension identity when present. It requires ancestry/range and episode-number verification, refuses mismatches without fallback, and specifies tests for both season and extension bindings.

No new defects identified in the scoped edits. Read-only design verification; no files changed or tests run.