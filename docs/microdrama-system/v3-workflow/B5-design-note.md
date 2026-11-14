# B5 design note: season critic, finalization, STORY LOCK transaction, and the extension branch

**Version 0.3 DRAFT, 14 Nov 2026. Author: GLM (design note only; one file, no code).** Critiqued
first before any B build (phase-B §11 B5 row): the lock transaction and the closure. Nothing here
builds until the note is accepted and A0–A3 plus B1–B4 have shipped. **v0.2 applied the round-1
critique — all eight findings ACCEPTED per [`b5-critique-rulings.md`](b5-critique-rulings.md)
(`codex-b5-note-critique.md` B5-1..B5-8), each integrated per its Replacement paragraph:** B5-1 the
binding-hash / record-seal split (§2.1); B5-2 the extension-context snapshot (§5.1, §5.2, §5.3);
B5-3 the initial extension document set + effective-bible resolution (§5.1, §5.4); B5-4 the full
authorization predicate + the equality DDL (§5.2, §5.3, §5.5); B5-5 the critic's LlmStep outside
the completion transaction (§1, §9); B5-6 the typed input-model delta + OQ-1 resolved (§5.3, §8,
§13); B5-7 the binding document's address across the approval fence bump (§2.1); B5-8 the
completed callback/finalization audit + tier-only Revise (§3.2, §6, §8, §9). No acceptance row
weakened; A2-parked conflicts stay open questions (§13). **v0.3 applies the round-2 rulings — all
five findings ACCEPTED per [`b5-recritique-rulings.md`](b5-recritique-rulings.md)
(`codex-b5-note-recritique.md` B5R2-1..B5R2-5, each folded per its Replacement wording, which wins
where it restates v0.2):** B5R2-1 the serial-planning-aware admission predicate — the complete
pack-number set required at initial critic admission and STORY LOCK approval, not at every
enqueue/dispatch (§5.3, §5.5, §10); B5R2-2 authorities loaded exclusively from the verified
snapshot, duplicated input fields compared field-by-field — hash equality alone proves nothing
about them (§5.2, §5.3, §10); B5R2-3 the conditional extension-context addition and its
enqueue/dispatch validation registered for all four affected inputs — bible, promoted profile,
episode plan, season critic (§5.2, §5.3); B5R2-4 the lock-approval provenance contract — the
approved activation durably associated before the fence bump with the exact binding-document
`(record_id, version, content_sha256)` and its separate `binding_sha256`, replacing verification
against an activation that stores no document version (§0, §2.1, §3.1, §5.2, §5.3, §5.4, §5.5, §9,
§10, §12); B5R2-5 the critic enqueue behind the round's join — tier updates synchronous, the
critic's sole enqueue direct only when no asynchronous members remain (§1, §3.2, §6, §8, §9, §10).
No acceptance row weakened; no BLOCKED finding left unapplied; R3 verification follows under the
operator's standing waiver.

**Binding inputs:** [phase-B-spec.md](phase-B-spec.md) **v0.6 (ACCEPTED)** §0–§12, esp. §4.2–§4.3
(tiers, demand list), §5 (episodes → STORY LOCK), §5.4 (binding), §5.5 (closure revalidation),
§6.2 (season rules), §7 (jobs, the continuation idiom, prompts), §8 (extension), §9 (commands),
§11 (B5 row), §12 (B-T7..B-T11); [B1-design-note.md](B1-design-note.md) **v0.3 (ACCEPTED)** §0–§13
(records, store, registry, job registrations, command rows, lock audit — B5 consumes exactly these
shapes); [A1-design-note.md](A1-design-note.md) **v1.4 (ACCEPTED)** §2 (DDL), §4 (contracts),
§5 (decision transaction), §6 (command table), §9 (lock audit); [phase-A-spec.md](phase-A-spec.md)
v0.3 §2, §5.1/§5.4, §6, §7.1; [A2-design-note.md](A2-design-note.md) **v1.3 (parked — R4 pending)**
§2.2, §4, §5, §7, §8 (budget hierarchy facts cross-checked only; its parked items are **recorded,
not resolved**, §11); [phase-C-spec.md](phase-C-spec.md) v0.4.1 §8 (the `cast_lock_hash` preimage
that consumes B's binding — the downstream seam); [phase-E-spec.md](phase-E-spec.md) v0.4 (ED2: E
consumes pack fields through the reader); [phase-F-spec.md](phase-F-spec.md) v0.4 §8.4 (extension
decision, calendar modes, published canon); [SPEC-v3.md](SPEC-v3.md) v0.4.6 §4.3, §2.2. Style
model: B1 v0.3.

**Citation convention (D4):** "phase-B §x" = `phase-B-spec.md`; "B1 §x"/"A1 §x"/"A2 §x" = the
design notes; "phase-A §x" = `phase-A-spec.md`; "master §x" = `SPEC-v3.md`. Code references are
relative to `microdrama/`: `S/` = `src/microdrama/`, `M/` = `migrations/`, `X/` = `tests/`. Where
this note cites an A- or B-phase object that is specced but not yet merged, the citation names the
note section that defines it (B1's convention).

**Facts:** re-verified read-only on `feat/microdrama-m0-m4` @ `2446627` (applied migration tail
**0025**; no `S/story_v3/` package exists — `S/` holds only `story/`; the anchors below were each
read at this commit: `S/workers/runtime.py:245` handler call with `self._finish` immediately after
(the D5 premise), `S/core/jobs.py:676` `finish` under `self._lock`, `S/core/jobs.py:429-438` the
semantic-key replay check, `M/0001…sql:78` `semantic_key … UNIQUE`, `S/contracts/v2.py:206`
`PayoffDebt.debt_id`, `S/story/script_maker.py:64` the `_NS` convention,
`S/scheduling/service.py:199` `_w03_episode_cadence`; only docs commits have landed since, and
for v0.2 the sealing anchor was re-read at the current head: `S/contracts/v2.py:66-68`
`calculated_content_sha256` hashes the whole record minus the hash field itself — identity,
version and timestamps included — B1 §2.3's inherited seal and the premise of §2.1's split).
For v0.3 the round-2 cross-checks were re-read the same way: A1 §2.3's `gate_activations` carries
`binding_sha256` and the revision stamps and **no binding-document version or `content_sha256`**
(B5R2-4's premise); B1 §6 registers all four input models the extension-context addition touches —
`BibleStepInput`, `PromoteProfileStepInput`, `PlanEpisodeStepInput`, `SeasonCriticStepInput`
(B5R2-3); and phase-B §5.1 plans **one episode job at a time, in order**, while §7.1 gives a Revise
round's **last job** the critic enqueue (B5R2-1/B5R2-5).
**One pointer correction, recorded here**
(never a spec conflict): the task brief cites "lock order (A1 §7)" — A1 §7 is the
`require_workflow` inventory; the normative order is **phase-A §6 = A1 §9's table**, used
throughout this note.

---

## 0. Scope, prerequisites, migration allocation

**B5 builds** (phase-B §11 B5 row): the season critic + repair + closure revalidation (§5.2/§5.5);
the demand list (§4.3); `StoryLockBindingV3` finalization; **the lock-approval provenance
(B5R2-4, §2.1, migration B-6)**; the STORY LOCK handler + episode rows + bindings — **season and
extension branches (PB-7)**; `edit_tier` + tier revalidation (C-M3, PB-5); `create_extension` + the
extension authorization **with its extension-context snapshot (B5-2) and the extension's initial
seam (B5-3)** + the extension builder; the season critic prompt (PB-6); `reopen_v3_gate` at the
STORY LOCK gate (PB-14). Gate rows: **B-T7..B-T11** (§10).

**B5 does not build:** any episode planning handler (B4), any promotion job handler (B3), the LOCK
gate (B2), the UI (B6), the D5 seam itself (B2 shipped it; B5 adds its joins), any C/E/F consumer.

**Prerequisites:** A0–A3 and B1–B4 shipped and accepted (B4 is B5's direct predecessor: the last
episode's completion enqueues `story_v3.season_critic` — B1 §6 registered the type, C-M20). A2
v1.3 is **parked** (operator-authorized R4 pending); B5 consumes its facts as written and records
the dependency in §13 (OQ-5) — if R4 moves A2 §4/§5 shapes, B5's §5/§8 rows shift with them.

**Migration allocation (B1 §0 discipline; symbolic, expected 0040).** B1 allocated B-1..B-4
(expected 0036–0039) and B1 §12 OQ-6 explicitly leaves the extension authorization's table to this
note: "B5's note allocates it (first B-number after B4's needs)". B2–B4 allocate no migrations
(their notes carry none), so:

| # | Expected | File | Purpose |
|---|----------|------|---------|
| **B-5** | 0040 | `0040_v3_extension_authorizations.sql` | The immutable extension authorization **carrying the extension-context snapshot columns** (PB-8, PB-9; §5.2, B5-2) |
| **B-6** | 0041 | `0041_v3_lock_approval_provenance.sql` | The append-only **lock-approval provenance** — the approved activation durably bound to the exact binding-document `(record_id, version, content_sha256)` and its separate `binding_sha256` (B5R2-4; §2.1) |

Each row is one purpose and creates only new objects (B-5 references A1 0030's `season_extensions`
and A2 0034's `account_cap_amendments`; B-6 references A1 0030's `gate_activations` and
`approval_events` — all landed before any B build starts). Guard pattern per B1 §1 for both:
`md_forbid_mutation` (UPDATE+DELETE), statement TRUNCATE refusal and the integer-number guard via
the 0026-style DO loop; `EXPECTED_TABLES` grows by the two names. The builder re-audits the tail at
build time and allocates contiguously; if A/B allocations shift, B-5's and B-6's numbers shift
**as a block** (purpose and order do not); applied bytes are never edited.

**Deviations considered (the B1/C-N22 checklist): none.** Every mechanism below rides A1/A2/B1
primitives as specced. The two places the spec is silent were §13 open questions in v0.1; the
round-1 rulings resolve them inside the accepted contracts — the extension's first planning
enqueue is the adopted atomic enqueue, recorded as a **D6 register row** against B1 §7's inherited
`J: none` (a new register row, never a silent edit; §5.3, §8, §13 OQ-1), and the binding-member
encodings are pinned by the §2.1 hash split and the §5.2 snapshot (§13 OQ-4). The round-2 rulings
add two registered deltas of the same kind: the **lock-approval provenance** is a new B-owned
append-only table (migration B-6, §2.1 — B5R2-4: A1's activation row stores no document version,
and B never edits an A table's enforced shape), and the input-model register row now covers **all
four affected inputs** (B5R2-3). The A2-parked items (OQ-2/OQ-3/OQ-5) stay open questions —
recorded, not resolved.

## 1. The season critic (`story_v3.season_critic`, B5's handler)

New module `S/story_v3/season_critic.py`. Job type, input model (`SeasonCriticStepInput`:
`round`, `generation_round`, the frozen intake ref, **repair origin + authorized episode set**,
PB-4 — B1 §6), queue (PRODUCTION) and registration are B1's, already landed; B5 ships the handler.

**Call sites** (every enqueue is a D5-seam continuation join, phase-B §7.1; B1 §6 registered the
type so B4 could enqueue it before B5 existed):
1. the round's last `plan_episode` completion (B4's join enqueues it; B5's handler consumes it);
2. the last repair re-plan's completion (§1.4 below);
3. a STORY LOCK Revise round's **last asynchronous member** (origin `human-revise`, phase-B
   §5.3/§7.1) — the round's **sole** critic enqueue whenever asynchronous regeneration members
   exist; only a tier-only round (no asynchronous members) enqueues it directly in the decision
   transaction (§3.2, B5R2-5).

**Handler phases (B5-5: the resumable external call never runs inside the completion
transaction).** A0's step protocol commits durable intent before submission and can return waits
across executions (phase-A0 §5.1), while D5 is the **completion** transaction — so the season
critic runs in two phases:

- **Phase 1 — the LLM pass, outside any completion transaction.** One `LlmStep.ensure` (Opus,
  phase-B §5.2) whose `FrozenLlmCall` pins the prompt by ID + version + sha256 (§1.5) and is
  persisted as canonical text **before any POST**. A0's outcome mappings are preserved verbatim:
  `LlmWait` → `WaitExternal`; `LlmDeferred` → `Deferred` (the track projects
  `WAITING_QUOTA`/`WAITING_PROVIDER` through `track_waits`); `LlmBlocked` → `Failed
  ("LLM_BLOCKED")`; `LlmLeaseLost` → no finish — the janitor quarantines and phase-A0 §5.3's
  reconciler resolves the durable operation under its own authority. **Phase 1 performs no
  completion-transaction write.**
- **Phase 2 — the D5 completion transaction, entered only on valid completion** (phase-B §2.4 D5,
  B1 §5): acquire the scope track FOR UPDATE **before** job locks — `season_tracks`, then
  `season_extensions` when the scope is an extension (A1 §5 step 2's order); validate fence,
  lease and the frozen inputs; then the steps below — outputs, the handler's own successful
  completion, and the join evaluation — all atomic. The runtime does not finish the job again
  (`S/workers/runtime.py:245`; `S/core/jobs.py:676`).

1. **The deterministic season checks** (phase-B §6.2), pure functions over the scope's **current**
   documents loaded under the held lock: every §6.1 rule re-checked against the final set; the
   impossible-wardrobe-day rule through `WARDROBE_CHANGE` effects; debts matched by stable
   `PayoffDebt.debt_id` (`S/contracts/v2.py:206`) through `PAYOFF_SETTLEMENT` effects; unknown
   `debt_id` references CRITICAL (PB5-5); seam `status` **derived** from settlement effects, never
   a stored label (C-M9/PB-12); the episode-count authority check. Findings persist as a new
   version of `critic:<scope>:season`.
2. **The phase-1 LLM findings merge into that findings version:** character drift against the
   drift exclusions, psychology resets, weak escalation, payoff timing.
3. **Round persistence before any re-plan** (PB-4): the round's `origin` (`automatic` |
   `human-revise`) and its **authorized episode set** persist with the findings version — the
   continuation never regenerates a unit the round's persisted origin does not authorize.
4. **Repair policy:** for findings that name packs, at most 2 repair rounds (C-M2). The initial
   `automatic` round may re-plan the **earliest** named episode and every later episode whose
   continuity input changed (§4), **at most 6 episodes per round**; a round that would exceed 6
   stops: the finding is recorded with an **impact preview** (the episodes that would re-plan) and
   the flow continues to finalization — the gate opens with the finding and preview, Approve's
   callback blocker refuses while the CRITICAL is open, Revise and Reject stay usable (PB-11), and
   the operator decides. **After a human Revise the critic reports newly invalid dependents
   without regenerating them** (§4); `human-revise` rounds regenerate exactly the noted units.
   While a repair round runs, tab 3's wait state shows the blast radius (B6 consumes the
   projection; phase-B §5.2 step 3).
5. **Continuation join:** re-plans enqueue through the continuation idiom (`replaces_job_id` under
   the unchanged `logical_work_id` `plan:<scope>:<n>`; semantic keys carry round + generation
   round, so a deliberate re-plan never dedupes to a no-op — C-M1, B1 §6); the last repair
   re-plan's completion enqueues the next season-critic round; after the final round — tier
   promotion (B3's deterministic promotion over the effective profiles), **one
   `story_v3.promote_profile` job per promoted role** (C-M12; B3's handler), and **the last one to
   complete runs finalization inline (§2); the season critic itself finalizes inline when no
   promotions are pending** (phase-B §7.1). No quarantined work enqueues anything (A3 §3.4).

**Failure handling.** Invalid LLM output is a **content attempt, never a repair round** (B5-5):
a new `logical_call_id`, **1 initial + 2 repair = 3 content attempts** (C-N9), then the job
fails → `BLOCKED (failed)`. Content attempts never touch the two-round/six-episode episode-repair
budget — that budget counts origin-tagged repair rounds only (PB-4). Transport recovery retains
the call identity (phase-B §7.4); content retries **retain the critic round and episode-repair
counters**. **Rounds are the unit of retry** (C-M5/PB-2):
the operator's retry re-runs the failed round only, from its earliest failed episode, **as a
replacement job with a fresh execution-attempt key** (semantic key + the advanced generation-round
identity, B1 §2.4) **under the unchanged `logical_work_id`; successful members of the failed round
are retained**; **a retry never resets the repair counters** — the two-round/six-episode budget is
consumed per origin-tagged round (PB-4). Completed packs are kept (stable pack and demand IDs make
them safe); tab 3 labels per-pack version status during a round (C-M5).

**On an extension scope** the same handler runs with `planning_scope_id = extension_id` and the
§6.2 reinterpretations (C-M8): the episode-count authority is the **authorization's recorded
appended range and cumulative count** (§5) — never a count inferred from a monetary cap; the §6.1
"final set" re-check covers **the extension's packs only**; "seam thread resolved in the finale" is
CRITICAL **only when the thread's explicit `reserves_growth` is set** (PB-12).

**Acceptance anchor:** B-T7 (every injected defect fired through typed-effect derivation; the
six/seven repair-membership boundary), B-T10 (post-Revise reporting without regeneration).

### 1.5 The season critic prompt (PB-6)

One prompt, `story_v3.season_critic`, owned by **B5**: a module constant in
`S/story_v3/prompts_season_critic.py`, registered at composition into B1's registry
(`v3_llm_prompts`, B1 §2.5) with `owner_package = 'B5'` (inside the table's CHECK vocabulary),
`version = 1`, and the **calculated** SHA-256 of the canonical encoding (UTF-8, NFC, `\n` —
B1-12: no hand-written hash). `resolve_prompt` resolves **by the pinned version** and re-verifies
text/hash agreement on every read; every `FrozenLlmCall` in B5's tests references this
registration (B-T6's clause, extended to B5's calls). A text change is `version + 1`, never an
edit.

## 2. Finalization and the STORY LOCK activation

Finalization is deterministic, inline in the completing handler's phase-2 completion transaction
(the last `promote_profile`, or the season critic when no promotions are pending — B5-5: no
external call runs inside it), under the already-held scope track lock (D5). Order (PB-13/PB-3):

1. **Post-promotion re-validation:** re-run the deterministic checks against the **effective**
   profiles and tiers — promotions may have added speakers, psychology and profile fields since
   the critic's pass. A newly promoted speaker with missing psychology/profile data is caught
   **here**, not by the pre-promotion checks (B-T8's PB-13 clause).
2. **Derive the demand list** (§2.2) — only after step 1.
3. **Write `StoryLockBindingV3`** (§2.1) and, in the same transaction, **complete the planning
   transition before the activation opens (PB-3): `BIBLE → PLANNED` first**, then
   `open_gate(STORY_LOCK, season[, extension], binding = the binding record's `binding_sha256`)`
   **stamped with the
   final revisions** — the activation's `decision_revision`/`content_revision` equal the track's
   post-transition values, so A1 §5's three-way comparison reads it against current authority.
4. **Re-finalization after a Revise retains `PLANNED`** and opens a fresh activation without
   repeating the initial edge (phase-B §5.2 step 4) — the same rule PB5-3 states for proposals,
   applied to the `BIBLE → PLANNED` edge.

If CRITICAL findings remain after repair, the gate **still opens** (the operator must be able to
see and Revise); **Approve's callback blocker refuses** while any CRITICAL is open (PB-11).

**Who opens and closes the STORY_LOCK activation** (B5's complete lifecycle; A1 §2.3's immutable
rows mean every transition is an appended fact):

| Event | Activation effect |
|---|---|
| Finalization (§2 step 3) | opens, stamped with final revisions |
| `edit_tier` (standalone entry) | supersedes the open activation, opens the successor (§6) |
| STORY LOCK Revise (non-tier) | the decision closes it; finalization after the round opens a fresh one (§3.2) |
| STORY LOCK Revise (tier target) | the decision closes it; the successor opens after the revision advance — **no supersede of the just-closed activation** (PB-5) |
| STORY LOCK Approve / Reject | the decision closes it; Approve opens nothing (step 4 is C's); Reject leaves reopening to `reopen_v3_gate` (§7) |

### 2.1 `StoryLockBindingV3` — the exact preimage per member class

The record is `story-lock:<scope>:<content_revision>` (B1 §2.1 — the enforced slug list; C reads it
by this key, phase-C-spec.md:593). **Two hashes, two jobs (B5-1):** the record's `content_sha256`
**retains B1's whole-record sealing rules** — B1 §2.3's inherited `V2Record` seal
(`S/contracts/v2.py:66-68`: the canonical hash of the entire record minus the hash field itself,
identity, version and timestamps included), which `StoryV3Store` verifies on every write and read;
a value hashing only the member preimage would fail that verification. A separate, explicitly
typed field **`binding_sha256`** hashes the member preimage: **exactly phase-B §5.4's member
classes**, each encoded as canonical JSON with a fixed field order and canonically ordered arrays
by the shared canonical encoder, then sha256 — the same preimage discipline as C's `cast_lock_hash`
(phase-C-spec.md:608), so the family's locks hash alike. A leading `"planning_scope_id"` field
separates the domains (encoding hygiene; it adds no member). **Activations and C consume
`binding_sha256`** — A1 0030's `gate_activations.binding_sha256` carries it — while the
document-reference triples inside the preimage retain each document's own `content_sha256`,
sealed under B1's rule and never re-derived here.

| Member class (phase-B §5.4) | Per-member encoding | Canonical order |
|---|---|---|
| the bible | `(record_id, version, content_sha256)` of the current `bible:<scope>` | single |
| every pack | one triple per `episode:<scope>:<n>` | `episode_number` ascending |
| every `ContinuityStateV3` | one triple per `continuity:<scope>:<n>`; **binding-time verification: `continuity(n).source_pack_version == pack(n).version` for every *n*** (B1 §2.3's PB-9 pin — a standalone continuity record can never sit outside the hash as an unqualified "last stored" authority; a mismatch refuses finalization) | episode order |
| the demand list | triple of `demands:<scope>` | single |
| the seam | triple of `seam:<scope>` | single |
| the tier table | the **derived** canonical mapping `[character_key, tier]` over the effective profiles (bible-embedded + promoted), sorted by `character_key` — phase-B §5.4 names "the tier table" as a member without naming a record; B5 pins it as this derived projection of the hashed profiles (no new `contract_type`, D6-clean; §13 OQ-4) | `character_key` ascending |
| the promoted character profiles | one triple per standalone `character:<scope>:<key>` (C-M12; promotion completed before the gate opens, phase-B §4.2) | `character_key` ascending |
| the critic reports | one triple per current `critic:<scope>:<n>` and `critic:<scope>:season` | episode ascending, then season |

**That member hash — `binding_sha256` — is the activation binding** (phase-A §2.5): `open_gate`
carries it into `gate_activations.binding_sha256`, and A1 §5's resolver recomputes it from current
content — the recomputation is authoritative and doubles as the stale-page check (A1 §4). **On an
extension scope** the member set is the same **scoped** document set (`planning_scope_id =
extension_id` for packs, continuity, demands, seam, promoted profiles, critic reports) plus the
**pinned-authorities block** — §5.4's typed projection of the extension-context snapshot's
authorities (PB-9, §5.2); the season's documents are never re-hashed — they are pinned by
reference.

**The binding document's address across the approval fence bump (B5-7 + B5R2-4: the lock-approval
provenance).** Approve bumps the scope track's `content_revision` (§3.1 step 4) *after* finalization
wrote `story-lock:<scope>:<content_revision>` — the track's post-approval fence therefore no longer
names the approved document. v0.2 told the reader to verify "the record's version … against the
activation's value" — but **the activation row stores no document version**: A1 0030's
`gate_activations` (A1 §2.3) carries `binding_sha256`, `content_revision` and `decision_revision`
and nothing finer — and a tier edit rebuilds the binding at an **unchanged fence** (§6a: no
`content_revision` bump), so multiple binding-document versions can exist under one
`content_revision` with no activation column to pick among them. B5R2-4 therefore makes the
association an explicit, durable fact:

- **The write — before the approval fence bump.** Inside the Approve decision transaction, ahead of
  §3.1 step 4's bump (and ahead of §5.5 step 5's on an extension scope), the callback appends the
  **lock-approval provenance** row (migration B-6, §0): the approved `activation_id` (UNIQUE), the
  `approval_event_id`, and the exact approved binding-document `(record_id, version,
  content_sha256)` **plus its separate `binding_sha256`** — the activation's own value, which
  blocker (b) has just proved current, over the document whose member preimage produced it.

```sql
CREATE TABLE v3_lock_approval_provenance (
  id                uuid PRIMARY KEY,
  schema_version    text NOT NULL DEFAULT '1.0',
  activation_id     uuid NOT NULL UNIQUE REFERENCES gate_activations(id),
  approval_event_id uuid NOT NULL REFERENCES approval_events(id),
  record_id         uuid NOT NULL,
  version           integer NOT NULL CHECK (version >= 1),
  content_sha256    text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  binding_sha256    text NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
  created_at        timestamptz NOT NULL DEFAULT now()
  -- no FK on (record_id, version): the document is addressed through B1 §2.2's store,
  -- which enforces (contract_type, record_id, version) uniqueness and re-verifies the hash
);
CREATE TRIGGER v3_lock_approval_provenance_append_only BEFORE UPDATE OR DELETE
  ON v3_lock_approval_provenance FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- + statement TRUNCATE refusal and the integer-number guard (§0 DO loop).
```

- **The read — resolve through the provenance, never the fence.** Downstream readers (C's included)
  and the §5.2 extension pin resolve: approval event → its `activation_id` (A1 §5 step 7, N1R-3) →
  the provenance row → the exact `(record_id, version)`; read that version through B1 §2.2's store
  and verify its `content_sha256` and `binding_sha256` against the provenance row's values. **It
  never constructs the record address from the subsequently incremented track fence, never selects
  an unqualified current version, and never substitutes `binding_sha256` for the document-reference
  seal** — the seal is `content_sha256` under B1 §2.3's whole-record rule; `binding_sha256` is the
  separate member-preimage hash (§2.1's split, B5-1).

The extension-context snapshot pins exactly this provenance (approval event ID + the document triple
+ the separate `binding_sha256`, §5.2), and B-T11 exercises the chain approval → provenance → reader
resolution → extension pin, **including an approval after multiple same-fence binding versions** (a
tier edit between finalization and Approve — B5R2-4's case).

### 2.2 The demand list (`SeasonDemandListV3`, deterministic)

Derived per phase-B §4.3 after step 1: one `LogicalDemand` per item, `demand_id =
uuid5(STORY_V3_NS, "demand:<scope>:<kind>:<logical key>")` (B1 §2.1) — **stable across revisions**,
which `CastBinding` (C) relies on. The seven kinds and logical keys are phase-B §4.3's table
verbatim. Checks B5 enforces at derivation: two-way reference completeness (every pack reference
resolves to a demand; every demand used at least once — AT-4); the promotion merge (a promoted
role's `EXTRAS_ROLE` demand merged into its `CHARACTER` demand with lineage; pack references to
the role resolve to the `CHARACTER` demand — C-M7, one on-screen person, exactly one identity
demand, V3R-4); one neutral voice demand per speaker; the proof-prop flag on the props beats
depend on (C-N2). The STORY LOCK screen's counts by kind and tier are read from this record; the
cost forecast and image-volume projection are **C's** (`NOT_AVAILABLE` until C ships — phase-B
§4.3).

## 3. The STORY LOCK handler (the B handler for `STORY_LOCK`)

New module `S/story_v3/story_lock.py`, registered in every composition where phase B has shipped
(A1 §5 registry; `NOT_AVAILABLE` before that — A1 §12 OQ-5). The handler implements A1 §5's
protocol exactly; B5 pins the B-specific bodies.

- **`binding(tx, …)`** — recomputes the §2.1 hash from current content; returns the binding units
  (the D2 target vocabulary: `EPISODE_PLAN` packs, `BIBLE_SECTION`s, the `SEAM`, `TIER`s — so
  Revise note targets validate against the activation's recomputed units, A1 §4/§5).
- **`conditions(tx, binding)`** — **common decision prerequisites only** (PB-11): the activation is
  open (the resolver's checks). Every Approve-specific blocker lives inside the Approve callback.
- **`on_decision(tx, …)`** — per action below; its writes join the decision transaction.

### 3.1 Approve

**Callback blockers, checked at the start of the callback in the same rollback transaction
(PB-11; phase-B §5.3):** (a) **no open CRITICAL** (the critic reports re-read under the held
locks; an invalid dependent or impact-previewed CRITICAL counts); (b) **the binding is current**
(recomputed hash = the activation's hash); (c) **the tier revalidation passed** (the §2.1 tier
table *is* the revalidated one — a binding whose derivation failed never finalizes, so this is
re-asserted, not re-derived); (d) **the STORY LOCK budget attach succeeds** (phase-A §5.1; A2 §4 —
run, not pre-checked: an attach that cannot fit refuses and rolls the whole decision back, naming
both numbers, A2 §11 OQ-1). Then, still inside the one transaction:

1. **Season scope:** call **`create_v3_episodes_in(tx, decision_context, N)`** (A2 §7 — the
   internal helper, never a command; it creates **all N episode rows independently of the release
   cadence**, AT-18, plus `episode_tracks`, and runs the A2 §4 attach: mutex → SEASON account →
   setup attach → `EPISODE` accounts → production steps → base-cap validation → **count-vs-binding
   validation**, A2 §4 step 8's N2-10). **Extension scope:** the extension-aware branch (§5.5) —
   its callback **refuses a missing or mismatched extension authorization** first (PB5-4).
2. **Write `v3_episode_story_bindings`** (B-4, B1 §2.6): one append-only row per episode —
   `pack_record_id`/`pack_version`/`pack_sha256` from the bound pack, `story_lock_approval_event_id`
   = this decision, `content_revision` = the **new episode track's fence value at approval** (A1's
   episode tracks default to zero), `story_lock_scope_revision` = **the deciding transaction's
   revision *r*** (the originating STORY LOCK scope revision — the season's for a season scope,
   the extension's for an extension scope; PB-10's two distinct fences). **Approval never reseals
   or modifies the approved pack to add its episode ID (PB-10)** — the link lives only in this row
   — and **B-T9 immediately reads every newly created episode through the compatibility reader**
   (B1 §4) inside the same transaction.
3. `advance_planning(PLANNED → STORY_LOCKED)` — authorized inside the deciding transaction (A1 §5
   step 8); on the extension scope, the **extension** track advances (§5.5).
4. **`content_revision` bumps** (A1 §6: lock approvals bump it): the season track on a season
   scope; the **extension track only** on an extension scope (PB-7 — existing season tracks
   unchanged; PB5-1 — the extension's revision discipline is its own). **Immediately before the
   bump, the callback appends the lock-approval provenance row (B5R2-4, §2.1, migration B-6): the
   approved activation durably associated with the exact binding-document `(record_id, version,
   content_sha256)` and its separate `binding_sha256`.** The bump does not orphan the approved
   binding document: §2.1's provenance contract (B5-7/B5R2-4) keeps its exact address resolvable.
5. **No job enqueues** (step 4 is C's handler's to start; B1 §8's row).
6. The decision's single revision advance closes the transaction (A1 §5 step 9 — the season's or
   the extension's `revision` per scope).

### 3.2 Revise

Notes (`season_revision_notes`, ≥1; targets `EPISODE_PLAN`/`BIBLE_SECTION`/`SEAM`/`TIER`, D2 —
validated against the recomputed binding units). In the one transaction: the activation closes
(A1 §5 step 7); **only the noted units regenerate** — noted packs via `plan_episode(n)` rounds,
bible sections via a scoped `story_v3.bible` round, the seam likewise — **and the regeneration
enqueues join the decision transaction** (A1 §5 step 8 / §6's decide row: "J: handler callback
enqueues only"). **A tier target invokes the shared internal tier-update/revalidation operation
under this decision context (PB-5, §6, B5-8): during `on_decision` it applies its update
synchronously — persisting the tier change and every affected document version — *without* the
standalone entry's fence bump, supersede or successor open** (A1 §5 runs the callback at step 8,
before the transaction's sole revision advance at step 9, and no post-advance callback exists;
the activation this decision just closed is already closed at step 7 — there is nothing left to
supersede). **The round's members are then collected across both kinds of target (B5R2-5):** the
asynchronous regeneration rounds (noted packs, bible, seam) plus the synchronously applied tier
update. **The `human-revise` season-critic continuation is enqueued directly inside the decision
transaction only when no asynchronous members remain — a tier-only Revise; when any asynchronous
member exists (a pure regeneration round or a mixed tier-plus-regeneration round), the critic's
sole enqueue belongs to the last asynchronous member's completion join** (phase-B §7.1: a Revise
round's last job enqueues the season critic) — a mixed round can therefore never start the critic
before its required members complete. **The successor activation opens at the later finalization,
after the decision commits** (§6b). After the round: the closure revalidation (§4), then the
season critic round (origin `human-revise`, PB-4), and finalization reopens the gate with a new
binding (§2). A stale binding, a target outside the binding units, or an in-flight regeneration
refuses (the PB5-1 lifecycle guards).

### 3.3 Reject

A1 §6's row: no episode-creation authority; planning stays `PLANNED`; the scope revision advances
once; the operator re-enters through **`reopen_v3_gate`** (§7), which opens a fresh activation over
the current binding and preserves every prior decision (PB-14). The season is never cancelled.

## 4. Closure revalidation after a Revise or repair (phase-B §5.5, B5-owned)

1. Regenerate exactly the units the round's persisted origin authorizes (PB-4).
2. Re-run the deterministic continuity check **forward** from the earliest regenerated episode,
   against the stored later packs. A later pack that no longer satisfies its continuity input
   becomes an **invalid dependent**: a CRITICAL finding `continuity-dependent` naming the episode.
3. Invalid dependents are **never regenerated silently** — after a human Revise the critic only
   reports them. The STORY LOCK screen lists them with one "Revise these too" action (the scoped
   revision authority, master §2.1); regenerating them requires that authority, never the
   automatic repair path. Approve's callback blocker refuses until none remain (PB-11).
4. Non-episode targets (C-M18): a bible-section or seam Revise regenerates the noted section/seam,
   then runs this revalidation; **non-invalidated packs survive** — the machinery catches
   continuity invalidation, not conceptual drift; drift beyond continuity is the operator's
   judgement at the reopened gate.

## 5. The extension branch (PB-7): authorization, builder, and the extension-aware Approve

### 5.1 `create_extension(season, range, calendar, amendment_id)` — eligibility and atomicity

Human session + CSRF, through `IdempotencyService.execute` with A1 §5's preflight seam.
Prerequisites, in check order (every refusal writes **nothing**):

1. **Owner scope** first (A1 §5 step 3's NotFound-as-missing rule).
2. The season's release track is `RELEASING` or `COMPLETE` (master §4.3; A1 §2.3's N1-16 —
   never `STORY_LOCKED+` on the **release** track).
3. **No open extension exists for the season** (A1 0030's `season_extensions_one_open` partial
   index; B5 surfaces it as a typed refusal — an extension scope has its own STORY/CAST lifecycle,
   master §2.2, and closes outside B5, §13 OQ-6).
4. **The range is contiguous with the current count:** `episode_start = current_count + 1` and
   `episode_end ≥ episode_start`, where `current_count` is the season's highest bound episode
   number (the initial STORY LOCK's N, plus any prior extensions' appended ranges); the
   authorization's `cumulative_episode_count = episode_end`.
5. **The named amendment validates (PB5-4):** the `amendment_id` names an **approved**
   `account_cap_amendments` row on **this season's unique `SEASON` account** (A2 §5 — `amend_account_cap`
   with empty `category_deltas` is the extension's own amendment shape, phase-A §5.4), and it
   **funds the requested appended count**: the row's own delta
   `new_effective − old_effective ≥ appended_count × per_episode_base_cap` **and** the account's
   current `md_effective_cap(SEASON) − committed ≥ appended_count × per_episode_base_cap`
   (the envelope actually available now; both checks because the named row need not be the latest
   amendment — §13 OQ-2). A wrong-account, wrong-season or non-funding amendment is refused
   (B-T11). A2's `account_cap_amendments` records money, category/step deltas and human provenance
   — **no episode count or range** — which is exactly why the authorization row below exists
   (PB-8): "the amendment's count" has no enforced meaning without it.
6. `calendar` is explicit (present and non-empty; **F owns its semantics** — the `CONTINUED`/
   `RESUMED` modes are phase-F §8.4's; B5 validates presence only) **and persists verbatim in the
   creation-time context snapshot (§5.2) — its durable home (B5-2)**.
7. The expected `season_tracks.revision` matches under the held lock.

**Effect — one transaction** (B1 §7's row as amended by the D6 register row, §8): create the
`season_extensions` scope (A1 0030's table); the **immutable extension authorization** (§5.2) —
linking the exact appended range, the cumulative count, the amendment ID and the human provenance
— **with its extension-context snapshot (B5-2, §5.2: the authorization, the explicit calendar
input and every pinned authority, `context_sha256`-sealed)**; **the extension's initial seam
(B5-3)**: `seam:<extension_id>` v1, persisted from the pinned predecessor (season) seam with
source provenance — the predecessor triple it derives from — so §2.1's required seam member
resolves from the first extension binding on; and **the first planning enqueue** (OQ-1 resolved,
B5-6): `story_v3.plan_episode(episode_start)` on the extension scope with the pinned inputs and
the authorization + snapshot reference, all in this transaction — the admission check passes
in-transaction by construction and guards every later enqueue or retry. **A creation rollback
leaves none of the five** — no scope, authorization, snapshot, initial seam or first job (B-T11).
The extension scope opens at `planning_state = BIBLE` — the pinned season LOCK authority and
bible stand in for `IDEA → PROPOSED → LOCKED → BIBLE`; those edges never run on the extension
track (PB-7's "extension planning edges", §5.3). `EXTENDING` stays a derived activity flag
(A1 §2.3).

**The effective bible and profiles on an extension scope (B5-3), defined once:** the effective
bible is the **extension-local** `bible:<extension_id>` record when one exists, otherwise the
pinned season-bible triple from the context snapshot; **scoped revisions supersede only
extension-local documents** — a bible-section Revise on the extension scope writes
`bible:<extension_id>` v1 (then versions), which takes over the §2.1 bible member and §5.4's
fallback from that point. The effective profiles are the extension's own set: the effective
bible's embedded profiles plus promoted standalone `character:<extension_id>:<key>` records
(C-M12 over the extension's packs). Prior season documents are never touched, re-hashed or
superseded — pinned by reference only.

### 5.2 Migration B-5 — the extension authorization (PB-8)

```sql
CREATE TABLE v3_extension_authorizations (
  id                       uuid PRIMARY KEY,
  schema_version           text NOT NULL DEFAULT '1.0',
  season_id                uuid NOT NULL REFERENCES seasons(id),
  extension_id             uuid NOT NULL UNIQUE REFERENCES season_extensions(id),
  episode_start            integer NOT NULL CHECK (episode_start >= 1),
  episode_end              integer NOT NULL CHECK (episode_end >= 1),
  cumulative_episode_count integer NOT NULL CHECK (cumulative_episode_count >= 1),
  cap_amendment_id         uuid NOT NULL REFERENCES account_cap_amendments(id),
  calendar_input           jsonb NOT NULL CHECK (jsonb_typeof(calendar_input) = 'object'
                                           AND calendar_input <> '{}'::jsonb),
  context_snapshot         jsonb NOT NULL CHECK (jsonb_typeof(context_snapshot) = 'object'),
  context_sha256           text NOT NULL CHECK (context_sha256 ~ '^[0-9a-f]{64}$'),
  actor_owner_id           uuid NOT NULL REFERENCES owners(id),
  actor_session_id         uuid NOT NULL REFERENCES human_sessions(id),
  idempotency_key          text NOT NULL UNIQUE,
  created_at               timestamptz NOT NULL DEFAULT now(),
  CHECK (episode_end >= episode_start),
  CHECK (cumulative_episode_count = episode_end)  -- B5-4: §5.1 defines equality; the DDL enforces it
);
CREATE TRIGGER v3_extension_authorizations_append_only BEFORE UPDATE OR DELETE
  ON v3_extension_authorizations FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
-- + statement TRUNCATE refusal and the integer-number guard (§0 DO loop).
```

Immutable by DDL: the row is created once, atomically with its extension scope, and never updated
— the count/range authority cannot drift after creation (the extension count comes exclusively
from this row, never from a monetary cap — PB5-4/PB-8). **The equality CHECK is B5-4:** §5.1
defines `cumulative_episode_count = episode_end`; v0.1's `>=` admitted a count the flow can never
produce — the DDL now enforces the definition the checks verify.

**The extension-context snapshot (B5-2) — the durable home of the authorities and the calendar.**
`context_snapshot` holds, as one typed JSON object: the authorization facts (appended range,
cumulative count, amendment ID, human provenance — this row's own authority); the **explicit
calendar input exactly as given** (`calendar_input`; F owns its semantics, B5 validated presence
only — the input now has a scope-owned home); and **every pinned authority** (PB-9): the prior
STORY LOCK approval event ID with its binding provenance resolved through §2.1's contract
(B5R2-4) — the exact binding-document `(record_id, version, content_sha256)`, the
document-reference seal, **and** its separate `binding_sha256`; the **CAST LOCK slot** — an exact
approved reference when the season has one at creation time, otherwise the explicit
`absent-until-C` sentinel; the exact
planned-terminal `ContinuityStateV3` triple; the exact published-canon identity (synthetic in B's
tests); the season bible triple. `context_sha256` is the canonical hash of that object (the shared
canonical encoder) — **the value every extension job input references and is validated against**.
The snapshot is immutable with the row, and **deploying C never rewrites an existing snapshot**:
an extension created before C keeps its absent CAST sentinel for its whole life; a post-C
extension pins the exact reference at creation. The same freeze applies to every authority in the
block. All extension jobs — **the four registered inputs of B5R2-3: bible, promoted profile,
episode plan, season critic** — reference the snapshot (`authorization_id` + `context_sha256`) at
enqueue, dispatch and approval, and validate agreement (§5.3/§5.5): later job inputs are checked
**against the scope-owned snapshot**, never trusted as free-floating pinned references — and
**agreement identifies the snapshot, it does not substitute for its contents: the authorities are
loaded exclusively from the verified snapshot row, and any authority fields duplicated in an input
are compared field-by-field against that snapshot before use (B5R2-2, §5.3)**.

### 5.3 The extension planning edges and the builder

The same builder runs on the extension scope (`planning_scope_id = extension_id`):
`plan_episode` for the new range, then the season critic (§1's extension reinterpretations), then
STORY LOCK for the new packs only. Edges B5 defines (PB-7):

| Edge | When | Track |
|---|---|---|
| — (creation enters at `BIBLE`) | `create_extension` (the pinned season LOCK + bible stand in for the earlier edges) | `season_extensions.planning_state` |
| `BIBLE → PLANNED` | the extension's **initial** finalization (§2 step 3, PB-3 ordering); re-finalization after a Revise retains `PLANNED` | extension |
| `PLANNED → STORY_LOCKED` | the extension STORY LOCK Approve, inside the deciding transaction | extension |

**Builder admission (PB5-4 — creation and downstream enforcement are separate; B5-4's full
predicate, re-tiered by B5R2-1):** every extension-scope enqueue of the four inputs (B5R2-3)
carries the typed extension-context reference (`authorization_id` + `context_sha256`) in its
input and is validated **at enqueue and at dispatch**, then re-read under the held locks at
approval (§5.5). **The per-job predicate, applied at enqueue and dispatch:** **season/extension
ancestry** — the authorization's `season_id` is this extension's season and its `extension_id` is
the job's planning scope; **authorization range equals the immutable extension range** — the
referenced row's `[episode_start, episode_end]`, DDL-enforced contiguous with
`cumulative_episode_count = episode_end` (§5.1's definition) and **predecessor-contiguous**
(`episode_start =` the pre-extension bound count `+ 1`); **amendment-account identity** — the
named approved amendment on this season's unique `SEASON` account (§5.1 item 5); **episode
membership within the round** — every episode the job will plan or re-plan lies inside the
authorized range **and within its authorized initial or regeneration round**; and the extension
scope is open. **A complete, gap-free planned set is not required here and cannot be: phase-B
§5.1 plans one episode job at a time, in order, and creation enqueues only the first episode
before any extension packs exist (§5.1) — mid-build the planned set is partial by design.**
**Admission also validates the authorized planning state/round:** a re-plan or regeneration
enqueue must cite a round the scope's persisted round state actually opened (PB-4's persisted
origin) — **an open extension scope alone grants no regeneration authority.** **Snapshot
agreement and authority loading (B5R2-2):** the input's `context_sha256` equals the authorization
row's — and that agreement **only identifies the snapshot; the authorities themselves are loaded
exclusively from the verified snapshot row** named by `authorization_id` + `context_sha256`. If
an input duplicates authority fields, **every field is compared against that snapshot before
use** — copying the correct hash never establishes that the duplicated fields agree.
**The complete-set checkpoints (B5R2-1):** the **complete authorized pack-number set** — every
episode in `[episode_start, episode_end]`, no gap inside it, no episode outside it — is required
**at initial season-critic admission** (the enqueue and dispatch of the extension's initial
`story_v3.season_critic`, where the serially planned packs must all be present) **and at STORY
LOCK approval** (§5.5's exactly-the-authorized-pack-number-set check). A missing or mismatched
authorization, range, count, snapshot **or a duplicated authority field that differs from the
snapshot** refuses (B-T11, including the altered-authority negative case) — this is what makes a
hand-enqueued or replayed extension job unable to plan without the immutable authority. The
extension's job inputs carry **pinned references, never "latest" reads** (PB-9), **loaded from
the snapshot** (B5R2-2 — never from duplicated input fields): the prior STORY LOCK approval event
ID and its binding provenance (§2.1's contract: the exact `(record_id, version, content_sha256)`
plus the separate `binding_sha256`); the **CAST LOCK slot — the exact approved reference when the
season has one, otherwise the snapshot's explicit `absent-until-C` sentinel** (B's tests exercise
the STORY slot with the CAST slot recorded absent — phase-B §8); the exact planned-terminal
`ContinuityStateV3` triple (whose `source_pack_version`/`source_pack_sha256` pin, B1 §2.3, makes
the terminal state immutable by match); the exact published-canon identity (F owns the real
source; **B tests with a synthetic published canon**); the season bible triple. The prior
approvals and packs are never touched.

**The typed input-model delta (B5-6 + B5R2-3 — a D6 register row, not a convention).** The
extension-context reference is a registered model change, because B1 §6's input shapes do not
carry it and existing contract models reject unknown fields — and §5.2's snapshot enforcement
covers **all extension jobs**, not just planning and criticism: extension bible Revise and
profile promotion also run on the extension scope (§5.1's effective-bible and effective-profile
resolutions). **All four affected inputs registered in B1 §6 gain the optional typed group
`extension_context: ExtensionContextRef | None`** — `BibleStepInput` and `PromoteProfileStepInput`
(B1 §6 registers them separately for `story_v3.bible` and `story_v3.promote_profile`) alongside
`PlanEpisodeStepInput` and `SeasonCriticStepInput` — carrying `authorization_id`,
`context_sha256` and the pinned authority fields above, with **conditional validation and
enqueue/dispatch validation registered for all four alike**: required (and checked against the
snapshot) **iff the planning scope is an extension**; refused as non-null on a season scope.
Regenerated `schemas/v3` + examples **for all four inputs** ship with B5's contract bump, and the
same D6 register row that amends the `create_extension` command's `J:` cell (§8) records these
additions against B1 §6's registered shapes — a deliberate delta, never a silent edit.

### 5.4 The extension's binding

§2.1's scoped member set (the extension's packs, continuity, demand list, seam — §5.1 persists
the initial seam at creation and an extension scope may carry its own seam revision; §6.2 lets
extension packs resolve open payoffs, a legitimate endpoint when `reserves_growth` is unset —
plus tiers and promoted profiles effective over the extension's packs per §5.1's resolution, and
the extension's critic reports) **plus the pinned-authorities block** — §5.2's snapshot
authorities as a typed payload field group inside the `binding_sha256` preimage (PB-9: the
binding must not drift from what the builder consumed, and the builder consumed the snapshot):
prior STORY LOCK approval + binding provenance (per §2.1's contract, B5R2-4: the exact
`(record_id, version, content_sha256)` and its separate `binding_sha256`); the CAST slot
exactly as frozen in the snapshot (the exact reference or the explicit `absent-until-C`
sentinel); terminal continuity triple; published-canon identity; season bible triple. The bible
member is the **effective bible** of §5.1's resolution — the extension-local record once one
exists, the pinned season triple until then (OQ-4 resolved by the round-1 rulings: the fallback
and the CAST freeze are pinned here and in §5.2).

### 5.5 The extension-aware STORY LOCK Approve (`create_v3_extension_episodes_in`)

**Extension approval cannot reuse the initial creation path unchanged (PB-7)** — A2 §4's initial
path (the unique `SEASON` account creation, the setup attach, the initial episode accounts, the
base cap) **must not run again, and the base cap is immutable**. B5 supplies the sibling helper
`create_v3_extension_episodes_in(tx, decision_context, extension, authorization)`, called by the
Approve callback after §3.1's blockers (the **authorization re-read under the held locks first,
passing §5.3's predicate at its approval checkpoint (B5R2-1) — ancestry, the complete
authorized pack-number set as offered (every pack in `[episode_start, episode_end]`, no gap
inside it, no pack outside it), cumulative count, predecessor contiguity, amendment-account
identity, snapshot agreement with the authorities loaded from the verified snapshot and every
duplicated input field compared against it (B5R2-2), and the authorized planning state/round;
any mismatch refuses and rolls the decision back** (PB5-4 + B5-4)):

1. Create **only the contiguous appended range's** episode rows (legacy `PLANNED`, empty plan —
   phase-B §5.4) and `episode_tracks`.
2. Create the appended episodes' `EPISODE` accounts (base US$10, parent = the **existing** `SEASON`
   account; the idempotent factory shape, `S/budget/service.py:220-262` pattern per A2 §4) —
   **no** `SEASON` account, **no** setup attach, **no** base-cap change, **no** production-step
   minting (§13 OQ-3).
3. **Validate the envelope:** `md_effective_cap(SEASON) − season committed ≥ appended_count ×
   per_episode_base_cap`, naming both numbers on refusal (the amendment envelope; the
   authorization already proved it at creation — this re-proves it at approval under the locks).
4. Write the binding rows (§3.1 step 2) for the extension's episodes;
   `story_lock_scope_revision` = the deciding revision *r* on the **extension's** track.
5. `advance_planning(PLANNED → STORY_LOCKED)` on the extension track; **append the lock-approval
   provenance row (B5R2-4, §2.1)**; bump `season_extensions.content_revision`; **the season
   track, its accounts, prior approvals and existing episode rows remain unchanged** (PB-7;
   B-T11 asserts the rollback and the untouched-priors clauses).

**Rollback:** the whole branch is inside the A1 §5 decision transaction; any failure at any step
(A2-style forced failure in tests) leaves **no partial append** — no episode, track, account or
binding row (B-T11).

## 6. `edit_tier` and tier revalidation (C-M3, PB-5)

The single name for the re-check is **tier revalidation**, implemented once as the **shared
internal tier-update/revalidation operation** `apply_tier_update(tx, scope, character_key, tier,
…)`, living beside B3's promotion code in `S/story_v3/tiers.py`, with two entries:

- **(a) the standalone `edit_tier(character_key, tier)` command** (human session + CSRF; the tab-3
  tier controls invoke it): requires an **open STORY LOCK activation**; then, **atomically** (B1
  §7's B1-8 sequence, restated as B5 builds it): run tier revalidation — promotion validation,
  demand derivation, the season critic's deterministic checks — **refusing V3R-4-violating
  demotions** (a demotion that would leave a speaker without a voice demand, or a recognisable
  character without an identity demand, is refused — B-T9); persist the tier change and every
  affected document version (the `CharacterProfile` version; the revised demand/critic/binding
  records); rebuild the binding over the revised records; `supersede_gate` the activation; advance
  the scope revision **exactly once**; `open_gate` the successor stamped with the final revisions;
  **no `content_revision` bump**.
- **(b) a tier-targeted STORY LOCK Revise** — the same internal operation **under the decision
  context** (B5-8): during `on_decision` it **persists its update only** — the tier change and
  every affected document version — **without the standalone entry's fence bump, supersede or
  successor open**. A1 §5 runs the callback at step 8, *before* the transaction's sole revision
  advance at step 9, and no post-advance callback exists; the activation the decision just closed
  is already closed at step 7 — there is nothing left to supersede. The operation then **enqueues
  the `human-revise` season-critic continuation inside the decision transaction directly only
  when the round has no asynchronous regeneration members (a tier-only Revise); in a mixed round
  the critic's sole enqueue belongs to the last asynchronous member's completion join** (A1 §6's
  decide row: "J: handler callback enqueues only"; B5R2-5, §3.2), and **the successor activation
  opens at the later finalization, after the decision commits** — the standalone entry's revision
  advance is here the decision transaction's own; no double advance. Exercised through the real
  decision route in B-T10, **including the mixed tier-plus-regeneration round**.

**Overrides never waive** speaker counting, the voice requirement or identity coverage (V3R-4).

## 7. `reopen_v3_gate` at the STORY LOCK gate (PB-14)

B2 shipped the command and the LOCK-gate entry; **the STORY LOCK gate becomes decidable with
B5's handler** (the §9 prerequisite "the gate's phase handler is registered" now holds). B5's
entry: prerequisites — the requested gate's scope was **rejected**, with planning `PLANNED` at
STORY LOCK and its required work completed; refused after Approve and during Revise regeneration;
the expected revision matches (**season scope: `season_tracks.revision`; extension scope:
`season_extensions.revision` — a stale extension revision is refused**, PB5-1); no activation
already open for the (gate, scope). Effect: a fresh activation over the **recomputed current
binding**, preserving every prior decision — the re-entry path after a Reject ("Revise later").

## 8. B5's command rows (phase-B §9; B1 §6 format)

| Command | Actor | Scope / revision owner | Prerequisites | Effect (edges) | Writes · jobs · events | Replay | Activation |
|---|---|---|---|---|---|---|---|
| `edit_tier(character_key, tier)` | Operator (human session + CSRF) | season / `season_tracks.revision` | a STORY LOCK activation is open; expected revision matches | §6(a)'s atomic sequence; `PLANNED` retained; no `content_revision` bump | W: profile/demand/critic/binding versions + SUPERSEDED + new activation + one revision advance · J: none (deterministic) · E: `gate.superseded`, `gate.opened` | idempotency key | **B5** |
| `create_extension(season, range, calendar, amendment_id)` | Operator (human session + CSRF) | season / `season_tracks.revision` | §5.1's order (release state; no open extension; contiguity; the PB5-4 amendment checks; calendar explicit; revision match) | creates the authorization **with its context snapshot** + the extension scope at `BIBLE` + the initial `seam:<extension_id>` document + the first `story_v3.plan_episode(episode_start)` enqueue, all atomically (§5.1) | W: `v3_extension_authorizations` (authorization + snapshot + calendar) + `season_extensions` row + the initial seam document · J: `story_v3.plan_episode` — the D6 register row amends B1 §7's inherited "J: none" (OQ-1 resolved, §13) · E: `extension.opened` + authorization provenance | idempotency key | **B5** |
| `reopen_v3_gate(gate=STORY_LOCK, scope)` | Operator (human session + CSRF; owner scope enforced, PB5-1) | season: `season_tracks.revision`; extension: `season_extensions.revision` | §7 | opens a fresh activation over the recomputed binding | W: `gate_activations` row · J: none · E: `gate.opened` | idempotency key | **B2** (command); the STORY LOCK entry lives with **B5** |

**Revision effects per command (B1-10 discipline):** `edit_tier` advances the scope revision
exactly once, no fence bump; `create_extension` verifies `season_tracks.revision` and advances
neither (the extension scope starts at its initial revision); `reopen_v3_gate`'s advance is
`open_gate`'s own. A matching replay returns the stored response and writes nothing; the same key
with different parameters raises `IdempotencyConflict`.

**Decision-callback and finalization entries (B5-8 — the scoped rows §9 audits; A1 §5/§6's common
events and replay rules are inherited, not restated):**

| Entry | Writes · jobs · events beyond A1's `approval.recorded`/`gate.decided`/`track.advanced` |
|---|---|
| STORY LOCK **Approve** (season / extension branch) | W: episodes + `episode_tracks` + accounts (A2 §7 / §5.5) + `v3_episode_story_bindings` + the planning advance + **the lock-approval provenance row (B5R2-4, §2.1 — written before the bump)** + the `content_revision` bump · J: **none** (B1 §8's row; step 4 is C's) · E: `episode.created` + `track.created` per episode (A2's) |
| STORY LOCK **Revise**, non-tier targets | W: the notes rows (A1's) · J: the regeneration rounds for exactly the noted units (`plan_episode(n)` / scoped `story_v3.bible` / the seam round), enqueued in the decision transaction; the critic's enqueue belongs to the round's last member (phase-B §7.1) · E: none beyond A1's |
| STORY LOCK **Revise**, tier-only target | W: the tier change + affected document versions (profile/demand/critic) — **no fence bump, no supersede, no open** · J: `story_v3.season_critic` (origin `human-revise`) in the decision transaction — **no asynchronous members, so the direct enqueue is the round's sole critic enqueue (B5R2-5)** · E: none beyond A1's; the successor opens at finalization, after the decision commits |
| STORY LOCK **Revise**, **mixed targets** (tier + episode/bible/seam; B5R2-5) | W: the notes rows (A1's) + the synchronous tier change + affected document versions — **no fence bump, no supersede, no open** · J: the regeneration rounds for the noted non-tier units, enqueued in the decision transaction — **no critic enqueue here: its sole enqueue belongs to the last regeneration member's completion join** (phase-B §7.1) · E: none beyond A1's; the successor opens at finalization, after the decision commits |
| STORY LOCK **Reject** | W: nothing beyond A1's row (no episode-creation authority; planning stays `PLANNED`) · J: none · E: none beyond A1's |
| **Finalization, initial** (inline in the last completer) | W: the findings + demand-list + `story-lock` document writes, the `BIBLE → PLANNED` advance, the activation open · J: §1 step 5's continuation enqueues (promotion join) · E: `gate.opened` (+ `track.advanced`) |
| **Finalization, re-** (after a Revise/repair round) | W: a fresh findings + `story-lock` version + the activation open — **`PLANNED` retained**, no repeated edge · J: as above, over the round's members · E: `gate.opened` |

## 9. Transaction and lock audit (phase-A §6 = A1 §9's table; the task brief's "A1 §7" pointer is
recorded in the header)

Normative order: **1** idempotency → **2** `season_tracks`, then `season_extensions` → **3**
`episode_tracks` (id order) → **4** scope domain rows → **5** jobs (id order) → **6**
provider-operations/leases → **7** budget (A2 §8.1's stages). Every B5 mutation:

| Mutation | Locks in order | Verdict |
|---|---|---|
| Season-critic handler — **phase 1: the LlmStep** (B5-5) | A0's step protocol **outside any completion transaction**: durable intent — **#5** job SHARE under `lease_guard` → **#6** provider-operation advisories + invocation/operation INSERTs (`provider_ops.begin`) → **commit** — then the external call with no data locks held; waits/defers/lease-loss return with **no completion-transaction write** (janitor + phase-A0 §5.3 reconciler own recovery) | conforms (phase-A0 §5.1/§5.2; the A1 §9 begin/rearm shape; no #2 lock is taken, so no order to invert) |
| Season-critic handler — **phase 2: the D5 completion transaction** (B5-5) | on valid completion: **#2** `season_tracks` FOR UPDATE (→ `season_extensions` for an extension scope, A1 §5 step 2's order) **before** job locks → fence/lease/frozen-input validation → **#4** document writes (findings + round persistence; re-plan pack versions) → **#5** its own completion → continuation enqueues commit atomically; runtime does not finish again (`S/workers/runtime.py:245`; `S/core/jobs.py:676`) | conforms (D5; B1 §8's row) |
| Finalization, **initial** (inline in the last completer; B5-8) | #2 held (the completer's; season → extension for an extension scope) → **#4** demand-list + `story-lock` document writes + binding verification reads → `BIBLE → PLANNED` track update → `open_gate` activation INSERT — one atomic commit with the completion (PB-3: transition before activation) | conforms |
| Finalization, **re-** after a Revise/repair round (B5-8) | #2 held → **#4** fresh findings + `story-lock` version + activation INSERT — **`PLANNED` retained**, no track-edge write; same atomicity with the completion | conforms (PB5-3-analogue, §2 step 4) |
| STORY LOCK Revise, non-tier or mixed targets (B5-8, B5R2-5) | **1** → **2** track FOR UPDATE (→ extension track per scope) → **4** the notes rows (**mixed: the synchronous tier change + affected document versions here, before the enqueues — no fence bump, no supersede, no open**) → **#5** the regeneration-round enqueues (`plan`/`bible`/seam) inside the decision transaction — **no critic enqueue in this transaction when asynchronous members exist; its sole enqueue rides the last member's completion join** (phase-B §7.1) → single revision advance | conforms (A1 §5 step 8: "handler callback enqueues only") |
| STORY LOCK Revise, tier-only target (B5-8, B5R2-5) | **1** → **2** → **#4** tier change + affected document versions (**no fence bump, no supersede, no open**) → **#5** the `human-revise` season-critic continuation enqueue — **direct: no asynchronous members exist, so this is the round's sole critic enqueue** → single revision advance | conforms (§6b; the standalone entry's supersede/open/advance writes are absent by design) |
| STORY LOCK Reject (B5-8) | **1** → **2** → **4** the approval/notes rows only → single revision advance; **no #5, no #7** | conforms (A1 §6's row) |
| STORY LOCK Approve, season branch | **1** → **2** `season_tracks` FOR UPDATE → **4** seasons/approvals/notes → episode + `episode_tracks` INSERTs (A2 §7) → **#7** stage 3 mutex → stage 4 (setup lock → SEASON create → parent set → `EPISODE` accounts → steps — A2 §4) → **#4** binding INSERTs → planning advance → **#4 the lock-approval provenance INSERT (B5R2-4, before the bump)** → `content_revision` bump → single revision advance; **#5 none** (B1 §8's "no job enqueues at Approve") | conforms (A2 §8.2's row + B1 §8's binding row, composed) |
| STORY LOCK Approve, extension branch | **1** → **2** `season_tracks` → **2** `season_extensions` (A1 §5's extension order) → **#4** authorization re-read + seasons/approvals → episode + `episode_tracks` INSERTs (§5.5) → **#7** stage 3 mutex → stage 4 (SEASON lock → `EPISODE`-account INSERTs → envelope validation) → **#4** binding INSERTs → extension-track advance → **#4 the lock-approval provenance INSERT (B5R2-4, before the bump)** → `season_extensions.content_revision` bump → single extension-revision advance | conforms — the same subsequence; inserts of not-yet-existing rows serialise under #2/#7 (A1 §9's justification) |
| `edit_tier` | B1 §8's row: **1** → **2** FOR UPDATE → **#4** document versions + binding rebuild → `supersede_gate` → one revision advance → `open_gate` | conforms (B1-8) |
| `create_extension` | **1** → **2** `season_tracks` → **#4** seasons + authorization (with snapshot + calendar) + `season_extensions` INSERT + the initial `seam:<extension>` document → **#5** the first `plan_episode` enqueue (OQ-1 resolved) | conforms (B1 §8 + one #5 tail after #4) |
| `reopen_v3_gate` (STORY LOCK) | **1** → **2** track (season; or `season_tracks` then `season_extensions`) → `open_gate` admission checks → activation INSERT | conforms (A1 §6's row) |
| Closure revalidation reads, builder-admission checks, `resolve_prompt` | plain reads, no locks (A1 §7's read row) | n/a |

The only #6 locks B5 touches are phase 1's A0 protocol writes (their own audited row above — the
seam's, not a B5 transaction's); every B5-owned completion or decision transaction takes #2
before #4/#5/#7, and the seam mandates #2 before job locks. No inversion.

## 10. Acceptance mapping (phase-B §12; B5's gate rows B-T7..B-T11)

| Row | B5 alone passes | Clauses needing C/E/F (surface in B5's build) |
|---|---|---|
| **B-T7** (V3-AT-3 family) | every clause: all-24-pack renderability fixtures (B4 planned them; the critic catches each injected defect through typed-effect derivation — wardrobe-day both halves, unknown `debt_id`, RESOLVED-in-finale); the 6-vs-7 repair-membership boundary with impact preview; **the B5-5 boundary: waits/defers/lease-loss during the critic's phase-1 LlmStep leave no completion-transaction write, and the phase-2 completion transaction runs only on valid completion — malformed-output content attempts never consume the episode-repair budget** | none |
| **B-T8** (V3-AT-4) | every clause: demand completeness two ways; ID stability across a Revise; one promotion → one `promote_profile` call; the `EXTRAS_ROLE`→`CHARACTER` merge; post-promotion re-validation; **the D5 join clauses re-run for B5's joins: two concurrent last-promote completions → exactly one finalization; commit-boundary death → recovery re-evaluates over persisted members** (B-T6's seam clauses, exercised on B5's join set) | none (B3's promotion handler is a shipped prerequisite, not a co-owner) |
| **B-T9** | all N rows + tracks + accounts + bindings in one transaction; forced-failure rollback; `content_revision` bump; the cadence selector never creates V3 episodes (`S/scheduling/service.py:199` guarded, A1 §7); `edit_tier` revalidation incl. the refused demotion; the compatibility read; the pack byte-unchanged (PB-10) | none in the row; **step 4 (casting) starts only when C's handler registers** — B5 asserts `NOT_AVAILABLE` for CAST_LOCK, never opens it |
| **B-T10** | scoped Revise on *k*; `continuity-dependent` blocking; post-Revise reporting without regeneration (PB-4); bible-section/seam/tier revises (C-M18) with the tier revise through the real decision route (PB-5) **and the mixed tier-plus-pack round through the same route (B5R2-5): the tier update lands synchronously in the decision transaction, the pack re-plans asynchronously, and the critic starts only at the last member's completion — never before**; the PB-11 blocker split; Reject → `reopen_v3_gate` → Revise on a fresh activation | none |
| **B-T11** | eligibility refusals (incl. the wrong-account/non-funding amendment, PB5-4); atomic creation rollback; builder-admission and extension-approval authorization refusals; the count exclusively from the authorization; stale `season_extensions.revision` refused (PB5-1); the builder on pinned authorities + a **synthetic** published canon; the extension Approve branch incl. rollback and untouched priors (PB-7); the §6.2 reinterpretations; **the B5-2/B5-4/B5-7 additions: creation persists authorization + context snapshot (calendar + pinned authorities) + initial seam atomically — rollback leaves none of them; a job whose `context_sha256` mismatches the snapshot is refused; approval requires exactly the authorized pack-number set; the B5R2 additions — the serial-planning boundary (B5R2-1): the creation-time first enqueue and each serial `plan_episode` enqueue/dispatch pass the per-job predicate while the planned set is partial, and the complete authorized pack-number set is required at the extension's initial season-critic admission and at approval; the altered-authority negative case (B5R2-2): a job input with the correct `context_sha256` but one authority field changed against the snapshot is refused; and the approval → provenance → reader → extension-pin chain (B5R2-4) resolves the exact approved binding-document `(record_id, version, content_sha256)` + `binding_sha256` through the lock-approval provenance row — never the post-bump fence, never an unqualified current version — including approval after multiple same-fence binding versions (a tier edit between finalization and Approve)** | the **real** published-canon source and the extension decision screen/viewership windows are **F's** (phase-F §8.4); calendar mode semantics (`CONTINUED`/`RESUMED`) are F's — B5 validates presence only (and persists the input verbatim in the snapshot) |

Beyond the rows: the STORY LOCK screen's cost forecast and image-volume projection stay
`NOT_AVAILABLE` until C (phase-B §4.3); `text_zh` remains a planning aid — delivered captions are
E's (phase-B §15); the real-person/brand check is C's output inspection (C-M6). B-T6's
registry-prompt clause extends to B5's season-critic `FrozenLlmCall`s (§1.5).

## 11. Risks

| Risk | Mitigation | Owner |
|---|---|---|
| Finalization inline in a completer lengthens the completion transaction (demand derivation over 24 packs) | deterministic, read-mostly derivation under the already-held #2 lock; the B-T6/B-T8 commit-boundary cases cover process death mid-join | B5 builder |
| A parked-A2 R4 change moves `create_v3_episodes_in`/`md_effective_cap`/amendment shapes | B5's §5/§8/§9 cite A2 sections, not line numbers; the dependency is recorded (§13 OQ-5) — a shift is a re-audit of those sections, not a redesign | orchestrator |
| Repair-cascade cost at the season critic (up to 6 episodes × 2 rounds re-planned serially) | the persisted membership + impact preview + operator checkpoint (PB-4); blast radius on the wait state | Operator (pacing) |
| The authorization's funding predicate over- or under-shoots (multiple amendments; an amendment partially consumed by a prior extension) | §5.1's two-part check (the named row's delta **and** the current envelope) + OQ-2 | B5 |
| Extension binding encoding drifts from C's cast-lock preimage discipline | §2.1 pins the identical per-member triple + canonical ordering; C §8 consumes the record by key, not by re-derivation | B5/C boundary |
| A frozen snapshot authority diverges from later reality (an extension created pre-C keeps its `absent-until-C` CAST slot; a pinned season document is later revised) | B5-2's ruling: the snapshot is the authority **as pinned at creation**; C consumes the explicit sentinel, never an implicit "latest"; a season revision after the pin is exactly what PB-9's pin-and-verify discipline exists to surface — a mismatch refuses, it never silently re-points | B5/C boundary |
| A future edit sneaks a completion-transaction write into the critic's phase 1 | Phase 1 owns no completion surface — its only writes are A0's durable-intent rows under the job's own locks; B-T7's boundary case asserts no completion writes on wait/defer/lease-loss | B5 builder |

## 12. Alternatives rejected (one per major choice)

| Choice | Rejected alternative | Why rejected |
|---|---|---|
| Finalization inline in the last completing handler (§2) | A dedicated finalizer job type | the family adds no second job system (phase-B §16); the D5 seam exists precisely so joins commit atomically with completions (PB-1/PB5-2) |
| The tier table as a derived projection inside the binding (§2.1) | A stored `tier-table` document (new `contract_type`) | phase-B §5.4 lists it as a member, not a record; a derived projection adds no vocabulary to B1's enforced CHECK (D6-clean) |
| A sibling `create_v3_extension_episodes_in` (§5.5) | Reusing `create_v3_episodes_in` with flags | PB-7: the initial path (SEASON creation, setup attach, base cap) must not run again; flags would reopen A2's accepted row for a B concern |
| A dedicated authorization table (§5.2) | Range/count columns on `season_extensions` | PB-8 names an immutable, append-only, guarded authorization; A1 0030's table is A-owned and mutable-tracked — B does not edit an A table's enforced shape |
| `edit_tier` as two implementations (command + decision entry) | One shared internal operation (§6) | PB-5's ruling: one name, one implementation, two entries — divergence between the entries is the bug the ruling exists to prevent |
| Builder admission at enqueue only (§5.3) | Dispatch-only checks | enqueue-time refusal keeps a bad job out of the queue and the semantic-key space; dispatch re-validation is the defense in depth (A1's replay guard shape) |
| The extension-context snapshot as columns on the authorization row (§5.2) | A separate snapshot table, or a `v3_story_documents` record | the authorization and its context are one creation fact with one guard and one atomicity unit; a new slug would cross B1's enforced CHECK vocabulary (D6), and a second table would re-state the append-only guard for no gain |
| The critic's LlmStep outside the completion transaction (§1) | All handler steps inside one caller transaction (v0.1) | A0's protocol commits durable intent before submission and returns waits across executions — a caller transaction cannot return a wait; holding #2 track locks across a minutes-long Opus call would serialize every decision on the scope (B5-5) |
| The lock-approval provenance as its own append-only table (B-6, §2.1) | Selecting the binding version by matching `binding_sha256` against the activation, or adding document columns to `gate_activations` | B5R2-4: the activation stores no document version (A1 §2.3) and tier edits create multiple same-fence binding versions — hash-matching re-derives identity at every reader instead of recording it once in the approval's own transaction, before the fence bump; B never edits an A table's enforced shape (D6), so the association is a B-owned append-only fact every downstream reader and extension pin resolves through |

## 13. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | **The extension's first `plan_episode` driver — RESOLVED by the round-1 critique (B5-6); no longer open.** v0.1 recorded the gap: B1 §7's row says "J: none", A1 §6's row likewise, yet something must start planning and PB5-4's "builder admission" presumes enqueue-time enforcement has a first enqueue to guard. | **Adopted:** `create_extension` enqueues `story_v3.plan_episode(episode_start)` on the extension scope **in the same creation transaction** — authorization + scope + context snapshot + initial seam + first job atomically; the admission check passes in-transaction by construction and guards every later enqueue/retry (§5.1). Recorded as a **D6 register row amending B1 §7's inherited "J: none"** — a deliberate, registered delta, never a silent edit (§5.3, §8). The alternative — a separate operator "start planning" command — stays rejected: it adds a command surface the spec's §9 table does not carry. |
| OQ-2 | **The "funding the requested count" predicate (PB5-4).** A2 §5 records money only; the named amendment need not be the latest; a prior extension may have consumed part of an earlier raise. | The two-part check of §5.1 item 5 (the named row's own delta ≥ count × base **and** the current `md_effective_cap` − committed ≥ count × base). **Recorded against parked A2 (R4 pending): if A2's R4 reshapes amendments or `md_effective_cap`, this predicate is re-audited, not silently kept.** Not resolved here beyond the recommendation. |
| OQ-3 | **Production step rows for the appended episodes.** A2 §4 step 6 minted `step_05..step_09` + the `episode_production` envelope at initial LOCK scaled by count; PB-7 says that path must not run again — but nothing else raises step caps. | B5's branch mints **no** step rows; the operator's SEASON amendment carries `step_deltas` (A2 §5's mechanism, validated by A2's own guards). Recorded against parked A2: the split of "who mints extension steps" stays with the amendment until R4 rules. |
| OQ-4 | **The extension binding's member encodings — RESOLVED by the round-1 critique (B5-1/B5-2); no longer open.** v0.1 asked: the bible member's fallback when no extension-scope bible record exists; the CAST slot's representation; whether pinned authorities belong inside the hashed payload or beside it. | Pinned: the hash split is §2.1's — `binding_sha256` over the typed member preimage, `content_sha256` staying B1's whole-record seal; the authorities are **§5.2's snapshot, frozen at creation** — the CAST slot is the exact approved reference when the season has one, otherwise the explicit `absent-until-C` sentinel, and **C's deployment never rewrites an existing snapshot** (v0.1's "C's registration replaces it" is withdrawn — it contradicted frozen authority); the authorities ride **inside** the `binding_sha256` preimage as a typed payload field group (§5.4); the bible member is §5.1's effective-bible resolution (the extension-local record once written; the pinned season triple until then). |
| OQ-5 | **A2 v1.3 is parked (R4 pending)** and B5 consumes §4 (the attach), §5 (amendments) and §7 (`create_v3_episodes_in`) as facts. | Treat them as binding inputs exactly as written; B5's build re-audits the four A2 touchpoints (§3.1 step 1, §5.1 item 5, §5.5 steps 2–3, §9's two Approve rows) if R4 lands first. Recorded, not resolved (the task's instruction). |
| OQ-6 | **`season_extensions.closed_at` has no B5 writer** — the extension scope outlives B5 (its own CAST lifecycle, master §2.2), and `create_extension` refuses while one is open. | Correct as-is: closure belongs to the extension's CAST completion (C) or an operator close action, both outside B5. Recorded so the B-T11 "no open extension" refusal is read as lifecycle-correct, not a leak. |
| OQ-7 | **The `story-lock` record key vs phase-B §2's table.** Phase-B §2 writes `story-lock:<content_revision>`; B1 §2.1 (accepted, enforced slug list) pins `story-lock:<scope>:<content_revision>`; C reads by B1's key (phase-C-spec.md:593). | Follow B1 §2.1 (the enforced vocabulary); the spec's shorter form is the same convention at scope elision. No action beyond this record. |

## 14. Traceability

**Phase-B findings pinned here:** PB-4 (§1.3/§1.4, §4); PB-5 (§6); PB-7 (§5, §5.5); PB-8 (§5.1,
§5.2); PB-9 (§2.1, §5.3, §5.4); PB-10 (§3.1 step 2); PB-11 (§2, §3.1 blockers, §4 item 3); PB-12
(§1.1, §1 extension, §5.4); PB-13 (§2 steps 1–2); PB-14 (§3.3, §7); PB5-1 (§5.1 item 7, §7, §5.5
step 5); PB5-3-analogue for finalization (§2 step 4); PB5-4 (§5.1 item 5, §5.2, §5.3, §5.5); PB5-5
(§1.1); C-M2 (§1.4, §4 asymmetry); C-M3 (§6); C-M5 (§1 failure, §1.4); C-M7 (§2.2); C-M8 (§1
extension, §5.4); C-M9 (§1.1); C-M12 (§2.1, §1 step 5); C-M13d (§2 step 2); C-M18 (§4 item 4);
C-M19 (§1.1); PB-6 (§1.5); PB-1/D5 joins (§1, §2, §9); O-B1..O-B6 n/a here (B1's). **Round-1
critique findings integrated (all ACCEPTED, `b5-critique-rulings.md`):** B5-1 (§2.1); B5-2 (§5.1,
§5.2, §5.3, §5.4); B5-3 (§5.1, §5.4); B5-4 (§5.2, §5.3, §5.5); B5-5 (§1, §2, §9, §10);
B5-6 (§0, §5.3, §8, §13 OQ-1); B5-7 (§2.1, §3.1 step 4); B5-8 (§3.2, §6, §8, §9). **Round-2
rulings integrated (all 5 ACCEPTED, `b5-recritique-rulings.md`):** B5R2-1 (§5.3, §5.5, §10);
B5R2-2 (§5.2, §5.3, §10); B5R2-3 (§5.2, §5.3); B5R2-4 (§0, §2.1, §3.1, §5.2, §5.3, §5.4, §5.5,
§9, §10, §12); B5R2-5 (§1, §3.2, §6, §8, §9, §10). **B1
consumed:** §2.1 slugs, §2.2 store, §2.4 generation rounds, §2.5 registry, §2.6 bindings, §6 job
registrations, §7 command rows, §8 audit. **Downstream:** C §8's `cast_lock_hash` reads
`story-lock:<scope>:<content_revision>` (§2.1); E ED2 reads packs through B1 §4's reader; F §8.4
calls `create_extension` (§5.1) and owns the decision screen, viewership windows, calendar modes
and the published-canon source (§10). **Requirement coverage (phase-B §14):** R-3.4 (§2.2, B-T8);
R-3.5 (§3, B-T9/B-T10); R-3.7 mechanism (§5, B-T11 — C-N19: the milestone is F's).

— end of note —
