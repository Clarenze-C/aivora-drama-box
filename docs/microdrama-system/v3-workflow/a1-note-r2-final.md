**`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/A1-design-note.md`** — revised in place to v1.2 (764 lines, ≤ the ~750 target; every code claim re-verified against `39e5319`). Findings → where they are resolved:

- **N1-1** — §2.2 (`p_entity_type`/`p_entity_id` params), §2.4 (`job_id` in every `v3_jobs` consumer), §1/§2.3 (deferred notes trigger moved into 0030).
- **N1-2** — §2.2 (feedback branches by gate; Gate 2 keeps timecoded feedback in both versions), §4 (`V3DecisionCommand.feedback` + validators/examples), §10 A-T1/A-T2.
- **N1-3** — §4 (v1 schema enum pin, typed `ValueError` membership guard, explicit v3 generation/registration, frozen-baseline byte test).
- **N1-4** — §2.4 (`alert_dismissals` TRUNCATE + integer guards via the 0031 DO loop), catalog registration covers all seven new tables.
- **N1-5** — §2.3 (immutable `gate_activations` + append-only `gate_activation_events`; derived openness; supersession needs no approval; ruling 1).
- **N1-6** — §5 steps 3–5 (owner scope before any workflow/state error, ancestry proof, three-way binding/revision comparison under the locks).
- **N1-7** — §5 revision plan + steps 7–9 (validate at r, record at r, handler transitions in the decision context, single revision advance; ruling 3).
- **N1-8** — §8 (common scope-lock admission across activation/claim/pod/Comfy/transfer; ACTIVE V3 heartbeat refused; verified shutdown before a wait; season/extension GPU ownership), §9, §10 A-T6.
- **N1-9** — §2.4 (typed `enqueue` with ancestry/scope validation, extension fence, validated transitive replacement links, `extension_id` reader argument).
- **N1-10** — §2.4 (all eight enum values mapped explicitly, NULL = transport retry excluded), §3 (0027 write-boundary CHECK, A0-D), §12 OQ-3 (read-time CHECK claim withdrawn; ruling 2).
- **N1-11** — §2.4 (three-form subject CHECK; operation identity with optional validated job context; extension scope in row, index and join).
- **N1-12** — §5 step 1 (preflight seam after replay lookup, before the idempotency INSERT).
- **N1-13** — §5 registry (intrinsic `is_test_handler` provenance, `for_testing` registry, production asserts at composition, real injection tested).
- **N1-14** — §7 new boundary table (all nine missing boundaries) + closing rules; §10 A-T5.
- **N1-15** — §6 (`advance_production`/`advance_release` rows, per-gate Reject table, extension revision owner, activation/decision identity).
- **N1-16** — §2.3 + §6 `create_extension` (master §4.3 `RELEASING`/`COMPLETE` + calendar choice; extension identity end-to-end).
- **N1-17** — §9 (GPU/advisory/transfer transactions audited; `2→4→3` justified as inserts; worker fencing kept with A3, settlement with A2, cadence recorded as a V1 gap; new two-connection races).
- **N1-18** — §10 (V1 acceptance/rejection matrix, retained guards, frozen bytes, no-`KeyError`, supersession/reopening, stale-replacement + extension isolation, operation dismissals, every quota reason, write tracing, real injection, activation-vs-claim/adoption/transfer, rollback incl. jobs + idempotency, populated accepted-0027 upgrade with checksums, `make check` + V1 `make pilot`).

§12 keeps the rulings with OQ-3 adjusted per ruling 2, and §13 is the finding→resolution table. Read-only outside the note; no code, tests, commits, network or deletions.
