# Appendices

# Appendix A. Greenlight, Research, and Project Workbench

This appendix turns the methods of Part I into a workbench you can copy straight into a project library. It is not a
creative pitch template. It is a set of production documents that tighten risk step by step. Any field without an answer
yet is written as `unknown` with an owner and a date to resolve it — never filled with adjectives.

The suggested order is: intake card → evidence log → audience and desire hypotheses → business model → competitor coding
→ story promise → pilot design → risk register → greenlight scorecard → decision memo. Every step can kill the project,
and every step can send it back for more evidence.

## A.1 Workspace and versioning rules

A project gets a stable ID the moment it is opened, without waiting for a script. All research, contracts, versions and
decisions hang off that one ID.

```text
PROJECT_<code>/
  00_intake/
  01_research/
  02_audience/
  03_competition/
  04_business/
  05_promise/
  06_pilot/
  07_risk/
  08_greenlight/
  09_decisions/
```

Filenames follow `entity_purpose_version_state`, for example `PRJ_NGSG_AUDIENCE_HYPOTHESES_v03_CANDIDATE.md`. Approved
files are never overwritten; a change produces a new version. Chat logs can be a source of evidence; they can never be
the source of a final decision.

## A.2 The project intake card

The intake card is filled in by the client, the producer or the creator, and describes only what is known now. It does
not require pretending the answers already exist.

```yaml
project_intake:
  project_id: PRJ_NIGUANG
  working_title: Backlit Takeover
  owner: PROD_001
  requester: INTERNAL_STUDIO
  business_mode_candidates: [paid_unlock, IAA]
  target_platforms: [vertical_mobile]
  planned_episode_count: 60
  target_episode_duration_sec: 75
  available_ip:
    type: original
    chain_status: documented
  required_delivery_date: unknown
  target_markets: [zh_CN]
  known_constraints:
    - a limited number of principal locations
    - no live-action pickup available as a rescue
    - campaign creatives must be derivable
  unknowns:
    - id: U001
      question: which episode should carry the first paywall
      owner: BUSINESS_STORY
      resolve_by: pilot_greenlight
```

Review questions for the intake card: what completes the exchange of value; who owns the content and its derivatives;
whether the target duration and episode count are only a wish; whether the delivery date leaves room to develop assets;
and whether anything required is uncertain in rights or in technology.

## A.3 The research evidence log

Every research conclusion keeps its source, date, observation and inference. "Someone said so online" and "everyone in
the industry does it" are not facts.

| Field | Meaning |
| --- | --- |
| `evidence_id` | Stable identifier |
| `source_type` | Platform post, interview, published report, competitor episode, first-party data |
| `source_ref` | Link, screenshot, file or internal query |
| `observed_at` | Date obtained |
| `observation` | What the source directly shows |
| `inference` | What the team concludes from it |
| `confidence` | High, medium or low, with a reason |
| `limits` | Sample, population, platform and time boundaries |
| `rights` | Whether it may be stored, quoted and redistributed |

**A correct entry:** "Of 20 sampled vertical workplace-revenge series, 15 show a visible loss of status in the first 30
seconds; the sample comes from one platform's June 2026 chart and does not represent all markets."

**An incorrect entry:** "Audiences now like a humiliation-and-payback opening." The first can be re-checked; the second
cannot be falsified.

## A.4 Audience desire and viewing context canvas

An audience is not "women aged 25 to 40." It is people who, in a particular viewing situation, want a particular
psychological change.

```yaml
audience_hypothesis:
  id: AUD_H01
  segment_name: viewers excluded by procedure at work
  viewing_context:
    device: phone
    duration: 5_to_15_minutes
    environment: commute_or_late_night
    interruption_risk: high
  current_tension: effort erased by relationships and rules
  desired_shift: evidence forces power to acknowledge a fact
  fantasy: reclaiming standing through procedure and competence, not by shouting
  aversions:
    - a protagonist who endures for a long time with no strategy
    - an antagonist who fails only by becoming stupid
    - no payoff after payment
  observable_prediction:
    - proof in the first frame may lower clicks and raise episode match
    - collective reaction after procedural confirmation should raise next-episode intent
  falsifier:
    - cold viewers cannot say why the authorization changes her standing
```

Interviews do not ask whether someone likes revenge stories. They ask about the last thing the person finished, paid
for, abandoned or shared: at which second they wanted to continue, which episode felt like a cheat, and what proof made
a reversal land.

## A.5 The business model decision table

| Decision dimension | Paid unlock | Ad-supported | Branded | Platform commission | Narrated comic |
| --- | --- | --- | --- | --- | --- |
| Core exchange | Payment for immediate satisfaction | Attention for continued viewing | Story for awareness and action | Content for purchase and distribution | Voice and image for dense narrative |
| Principal structure | Cut points and payoffs | Small in-episode payoffs and ad tolerance | Product inside the causality | Meeting the buyer's interface | Narration authority and picture updates |
| Primary risk | Overdrawing trust | Padding that costs retention | Clumsy placement | Format and acceptance mismatch | Slide decks and voice drift |
| Key metrics | Unlocks, post-paywall retention, refunds | Completion, next episode, ad revenue | Recall, leads, purchase | Acceptance, delivery, cost | Retention, listening quality, update efficiency |

Once chosen, write down the irreversible production consequences: where episodes end, episode length, cut point density,
ad breaks, calls to action, the creative variants required, the proportion of sound, and the rights scope. If two models
run in parallel, declare the shared beat master and each one's episode compilation rules.

## A.6 Competitor coding

Code every competitor episode second by second against the same fields, rather than copying surface genre.

```yaml
competitor_episode:
  title_id: CMP_014
  episode: 1
  duration_sec: 82
  hook:
    first_frame: the protagonist blocked outside the meeting room door
    promise_confirmed_at: 00:05
  beats:
    - {time: 0_8, function: pressure, visible_change: publicly stripped of standing}
    - {time: 8_26, function: strategy, visible_change: she records instead of arguing}
    - {time: 26_49, function: proof, visible_change: the document enters public space}
  payoff:
    old_debt_paid: the right to enter
    new_debt: who signed the authorization
  production:
    shot_count: 18
    locations: 1
    difficult_actions: 1
  notes:
    mechanism: procedural proof forces power to change its position
    do_not_copy: the doorway, the look of the authorization, the original lines
```

After coding, plot three curves: pressure, what the audience newly knows, and satisfaction against debt. An opportunity
is not necessarily something nobody has made. It can be the same mechanism improved for a new desire, a new production
route, or a more honest payoff.

## A.7 The story promise card

```yaml
story_promise:
  project: PRJ_NIGUANG
  one_sentence: an auditor cast out by the family business uses the procedural evidence her father left to reclaim her standing, and discovers a dead man's account is still paying out
  audience_fantasy: fact eventually forces relationships and power to yield
  repeatable_engine:
    pressure: the opposition excludes her through identity and procedure
    strategy: she observes with restraint and builds evidence
    reversal: the evidence enters public space
    consequence: power is forced to adjust, and a larger cost is exposed
  proof_of_promise_in_E001: security stands aside once the authorization is confirmed
  season_question: is her father still alive, and who is using his identity
  forbidden_shortcuts:
    - the protagonist suddenly obtains evidence from nowhere
    - the antagonist exposes herself through stupidity
    - humiliation with no payoff
```

The promise has to be visible in the pilot; it is not poster copy. If a cold reader cannot say what satisfaction the
series will deliver every few episodes, the promise has not yet entered the structure.

## A.8 The pilot scope card

A pilot is not a cheap miniature of the season. It is the smallest work that validates the most dangerous assumptions.

```yaml
pilot_scope:
  episodes: [E001, E002, E003]
  hypotheses:
    H1: a proof-driven reversal is comprehensible on a phone
    H2: Lin Yun's and Lin Wei's identities hold across angles and in shared frames
    H3: a single location can sustain three episodes without feeling repetitive
    H4: the 75-second structure scales within cost
  must_build:
    - golden identities and base looks for the two leads
    - the boardroom map, empty plates and four camera zones
    - the authorization graphic master and the old pen
    - two voice identities and the boardroom room tone
  intentionally_deferred:
    - the banquet ensemble
    - complete localized versions
    - every wardrobe change in the season
  stop_conditions:
    - lead identity close-up pass rate below the minimum threshold
    - cold comprehension of the evidence insufficient after two revisions
    - the stress budget exceeds the approved reserve
```

## A.9 The risk register

| Risk | Likelihood | Impact | Earliest signal | Prevention | Fallback | Owner |
| --- | ---: | ---: | --- | --- | --- | --- |
| Profile identity drift | Medium | High | Candidates diverging by angle | More angle coverage plus stress tests | Avoid full profile, or composite | Character assets |
| Illegible authorization | Medium | High | Fails the phone test | Independent graphics and an insert shot | Narration supplies only the minimum field | Graphics / director |
| Late client feedback | High | Medium | Milestone exceeds SLA | Contract terms and reminders | Slip the date and release capacity | Project manager |
| Missing advertising rights for music | Low | High | Rights ledger pending | A campaign-specific licence | No music, or an alternative stem | Rights lead |

Risk scores are only for ordering. Nothing involving rights, safety, a core fact or a release block gets averaged away
because its likelihood is low.

## A.10 The greenlight scorecard

Each item is `pass / conditional / fail / unknown`. No composite score is used to hide a blocker.

1. **Audience evidence:** are the desires and aversions traceable to sources?
2. **Commercial structure:** are the value exchange, cut points, metrics and versions explicit?
3. **Story engine:** can pressure, strategy, reversal and consequence repeat and escalate?
4. **Pilot testability:** can the key assumptions be proven with three episodes or fewer?
5. **Production route:** is there a workable plan for identity, locations, action, sound and text?
6. **Rights:** can IP, likeness, voice, music, fonts and model terms all be cleared?
7. **Unit economics:** do the baseline and stress budgets stay inside the loss ceiling?
8. **Team and schedule:** does the slowest review station have capacity?
9. **Stop conditions:** is it written down when to stop investing?

A greenlight is not "everyone liked it." Any blocking item marked `fail` prevents the project entering full production;
every `conditional` carries its condition, owner, deadline and the consequence of missing it.

## A.11 The greenlight meeting agenda

The meeting is confined to decision questions; nobody reads the materials aloud.

1. The producer restates the business model, the loss ceiling and the decision needed today.
2. The research lead presents the three strongest pieces of evidence and the three largest uncertainties.
3. The showrunner takes two minutes on the story promise and how the pilot proves it.
4. The asset, technical, sound and rights leads report only blockers and fallback routes.
5. Finance shows the baseline, the stress scenario and the irreversible spend.
6. The decision maker chooses `greenlight / conditional / hold / kill`.
7. The note-taker restates the conditions, owners, deadlines and next gate on the spot.

## A.12 The decision memo

```yaml
greenlight_decision:
  project: PRJ_NIGUANG
  decision: conditional_greenlight
  approved_scope: E001_E003_pilot_only
  conditions:
    - id: C01
      requirement: Lin Yun's 45-degree-left identity asset passes the stress test
      owner: ART_DIRECTOR
      due_before: keyframe_batch_01
    - id: C02
      requirement: advertising use of the authorization is cleared for rights
      owner: RIGHTS
      due_before: creative_release
  budget_ceiling: INDEX_100
  stop_conditions: [identity_gate_fail_twice, stress_budget_exceeded]
  evidence_snapshot: GREENLIGHT_PACK@sha256
  approvers: [SHOWRUNNER, PRODUCER, RIGHTS]
```

## A.13 A worked example from *Backlit Takeover*

The project was first described as "a woman goes home, humiliates her family and takes back the fortune." The workbench
forced a rewrite: the audience fantasy is not wealth itself, but somebody excluded by relationships reclaiming standing
through verifiable procedure. What episode one proves is not that the protagonist says she is formidable; it is that the
authorization makes security stand down. The pilot therefore invested first in the document, the space and identity
stability, rather than in sixty sets of luxurious locations.

The stress scenario showed that the banquet ensemble and multi-person synchronized lip sync would magnify cost
substantially, so the banquet was deferred until the route had been proven. The first three episodes tested only whether
a single boardroom could sustain escalation. That decision reduced visual spectacle and increased the clarity of what the
project could prove.

## A.14 Common counterexamples

- **Writing sixty episodes before researching the business model:** the structure fits neither paid nor ad-supported.
- **Treating a trending chart as audience evidence:** you know someone else succeeded, not why your own mechanism works.
- **Picking only the prettiest shots for the pilot:** the pass rate and real cost of ordinary shots stay unknown.
- **Averaging the greenlight scores:** a rights gap gets offset by a high story score.
- **No kill conditions:** every failure is explained away as needing one more round of optimization.
- **A conditional greenlight with no deadline:** the project burns budget as though it were fully greenlit.

## A.15 Final checklist

- [ ] Project ID, owner, business model and target versions are explicit.
- [ ] Every key conclusion has a source, a date, an observation and the limits of its inference.
- [ ] Audience hypotheses include observable predictions and a falsifier.
- [ ] The story promise has visible proof inside the pilot.
- [ ] Competitors are coded against uniform fields rather than collected as screenshots.
- [ ] The pilot validates the most dangerous assumptions instead of pre-building the world.
- [ ] Risks have an earliest signal, prevention, fallback and an owner.
- [ ] Rights and release blockers are excluded from averaged scoring.
- [ ] Baseline budget, stress budget and stop conditions are approved.
- [ ] Decisions, conditions, deadlines and an evidence snapshot are in the decision log.

## A.16 Exercises and deliverables

Exercise one: take an existing idea, fill in the intake card, and convert every adjective into a verifiable field.
Exercise two: sample ten competitors and code their openings, proofs, reactions and cut points. Exercise three: write the
production consequences of the same story under paid and under ad-supported models. Exercise four: design a pilot that
validates only three high-risk assumptions. Exercise five: run a 30-minute greenlight meeting where participants may cite
only the evidence pack.

Deliverables for this appendix: project intake, evidence log, audience hypotheses, business model decision, competitor
coding, story promise, pilot scope, risk register, greenlight scorecard and decision memo.
