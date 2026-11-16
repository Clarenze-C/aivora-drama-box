# Slice1 independent code review — round1

Reviewer `/root/review_transport_fixes`, fresh context, not implementer.
Snapshot `.scratch/keep/t031-native-review/slice1/manifest.json`, seven files,
patch SHA256 a85af678f5ae0585987fbd08ca13f7e5cdac69acc4a9454e8ecf06ae945db91f.
All snapshot file byte hashes/lengths and patch hash verified; base0851374.

**FIX_REQUIRED: one P2 remains in R2.** diagnostics.py9–13,33–34 stops sensitive
header values at semicolons/commas/newlines, losing association with remaining
unknown reflected values. Source-derived synthetic counterexamples:

- Cookie: theme=dark; sessionid=synthetic-session-secret
- Authorization: Bearer followed by newline + space + synthetic-continuation-secret
- JSON Authorization value containing Bearer synthetic-prefix,synthetic-secret-tail

Exact replacement of the supplied request credential does not cover unknown or
transformed reflected values. Both transports persist sanitized text into error
messages; consume complete enclosing sensitive values/folded continuations while
preserving separate useful diagnostics. Add transport-level exception-chain tests.
These are not observed real provider secret echoes.

R1: no identified blocking finding. Decimal validation/tolerance, authoritative
rounding/conserving tie allocation, true mismatch dispute and raw-aware hash with
legacy hash preservation fit the reviewed scope. Old observations are immutable.
Canonical raw-string reconstruction remains explicitly deferred to benchmark
internal evidence; current rows commit source strings by hash only.

No ordinary HTTP success regression identified. Reviewer inspected seven changed
files, requirements/spec/contract and relevant caller paths. No tests, provider
calls, file changes, memory, ai-route or subagents. The implementer's95-test receipt
was read, not independently rerun. Implementer is fixing only this finding before
one scoped re-review.
