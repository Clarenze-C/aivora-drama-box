# Native Goldfish Stage9 scoped re-audit — round2

All three fresh reviewers completed; no third review round launched.

- Implementation reviewer resolved I1/I2/I4–I6 and W1–W3. Residual I3 (Major):
  exclude supplied experiment UUID from canonical plan identity while retaining
  explicit experiment_nonce; same plan with another UUID aliases existing row.
- Style reviewer resolved W1/W3 and W2's behavior; requested replacing leftover
  “signed” terminology with operator file/hash. One direct-regression Major:
  candidate reservation could be counted twice by pre/post-insertion wording.
- Codebase reviewer resolved K1–K6 at design level. Independent contract-guardian
  verdict ACCEPT for VOICE="voice", one anchor/speaker, explicit hashed port map,
  package2.16.0, payload schema versions unchanged, RenderRequest unchanged, old
  hashes preserved, optional config omitted from hashes when absent. Strict
  reference preflight must include sealed VOICE entries, never be bypassed.

## Author resolution after scoped re-audit

Both concrete residuals were corrected: canonical plan hash excludes supplied
UUID, includes nonce and all work/config/caps; three exact replay/conflict tests
specified. Admission inserts candidate linkage then projects linked exposure once;
text forbids adding it a second time and covers reservation replay. Leftover
signature wording was replaced. §F already resolves staged intent/hold versus
job/lease materialization, and the superseded transition row is consolidated.
No unresolved design finding is retained. These final mechanical edits are author
rulings, not a fabricated third independent review. Implementation must prove them
with targeted identity and money-boundary tests and receive independent code review.

Read evidence: implementation and style reviewers read full spec/contract and
round1 report; implementation source inspection was not repeated. Codebase reviewer
also inspected roles/manifests/hash/version, reference preflight, RenderRequest,
workflow hashes/binder/verifier, reserve/submit_v2, transport schemas/guards,
budget reserve/release, lease claim/adoption and live composition validation.
No reviewer used memory/history, edited code, ran tests, called providers or
spawned nested reviewers. Native identities: goldfish_implementation_r2,
goldfish_style_r2, goldfish_codebase_r2.
