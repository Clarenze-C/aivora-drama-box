# T031 paid-run fact map (GLM swarm): how today's code runs one real Pika H3 Flex benchmark

Orchestrator: Opus, 12 Nov 2026. The orchestrator will assemble the operator's signable run from your
facts. **Facts only:** no design and no recommendations. **Read-only. Write no files.** Put the whole fact
map in your final message.

## Where

- Worktree `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch `feat/t031-fix3` (the accepted
  T031 tree, tip `104b26b`). Code is under `microdrama/src/microdrama/` (cite it as `S/…`), tests under
  `microdrama/tests/` (`X/…`), the image recipe under `microdrama/deployment/pika-h3-flex/` (`D/…`), and
  runbooks under `microdrama/runbooks/` (`R/…`).
- Context, skimmed rather than summarised: `docs/microdrama-system/T031-benchmark-packet.md`,
  `docs/microdrama-system/t031-benchmark/{shots.csv,trials.csv,source-pins.json}`.

## Rules for every fact

- Cite `file:line` and quote the decisive line or signature (≤ 2 lines).
- If you searched and found nothing, write **NOT FOUND** and the search terms you used. Never guess.
- Keep the whole answer under about 400 lines. Use tables.
- Never print environment variables, `.env` files, keys or tokens.

## Facts needed

1. **Entry points.** Every CLI module and subcommand for the paid benchmark/experiment path. Cover
   creating an experiment, sealing, authorizing, preflight, execute/run, resume, status, sweep, invoice,
   resolve and export. Give the exact invocation, every flag, which are required, and the exit codes.
2. **Input documents.** For each file the operator or orchestrator must author:
   - the seal;
   - the authorization;
   - the experiment/sample manifest or prompts;
   - any quote or attestation file.

   Give the model/parser class, every field with type and constraints, which fields are hashed (and how:
   `sealed_sha256`, `authorization_sha256`), and any example or fixture file that loads through the
   real parser.
3. **Order of operations,** from an empty paid database to settled billing, as the code enforces it:
   - which step must precede which;
   - what each step writes durably;
   - which steps touch the provider (RunPod/Comfy) and which are offline.
4. **Pins and their checks:**
   - image reference/digest;
   - workflow/API-graph hash;
   - `/object_info` schema hash and `schema_evidence` / `schema_attestation_source`;
   - output-controls hash;
   - preset id/version;
   - weight manifest.

   Where each is declared, where it is compared, and what happens on mismatch. In particular: how and
   when the runtime schema is captured on the GPU pod after weights are present (the weight-free image's
   model enums are empty), and what `INDEPENDENT_RUNTIME_CAPTURE` requires.
5. **Weights on the pod:** how `D/provision.py` (`--download`, destination, free-space and hash checks)
   is invoked in the paid path, or NOT FOUND. Cover the source (Hugging Face repo/revision), the auth
   needed, disk sizing fields in the authorization, and cold-start timing capture.
6. **Binding of benchmark inputs:**
   - how a sample's references (character, outfit, set, prop images; voice audio) are registered as
     assets (content hash, role, rights record) and mapped to Ref2VA slots and prompt labels
     (`<Picture N>` / `<Audio N>`);
   - how the Thai prompt text, seeds (`trials.csv`), negatives, resolution (480p portrait), frame count
     and fps are supplied;
   - which rights/registry records must exist (route id, evidence id, voice rights basis) and how they are
     created.
7. **Budget and stop controls:**
   - spend cap, aggregate GPU-hours, per-lease hard stop, quote id/price/validity, storage sizes,
     max samples/attempts, the 3-sample screen;
   - the fields and the enforcement points;
   - how prior spend on the same account is reconciled against the $10 episode cap;
   - which account/episode a benchmark is attributed to.
8. **Credentials:** every `credref:` the paid path needs (RunPod key, Comfy gateway token
   `MICRODRAMA_COMFY_TOKEN`, Hugging Face if any), the store kind and locator rules. Names only, never
   values.
9. **Outputs/evidence:** what files and records a run produces (paths, fields), and how results map to
   `results-template.csv`.
10. **Gaps:** anything in facts 1–9 that the code expects but nothing in the repo provides (no tool, no
    example, no CLI) — listed plainly.
