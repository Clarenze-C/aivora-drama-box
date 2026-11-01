# T045 billing build brief

Goal and invariants: implement `T045-billing-integration-spec.md` against
frozen contract package 2.13.0, using fixture billing records only. The
Runpod adapter's `billing_history()` returns raw provider buckets; it must
remain unallocated until the new service validates/stores them. No live API
call, Pod, paid request, public action or invoice claim.

Worker is explicitly assigned an ordered new migration after 0021, a new
`microdrama/src/microdrama/budget/` billing-reconciliation service/repository,
`persistence/` helper if needed, and scoped `tests/unit/budget/` and
`tests/integration/persistence/`. Existing receipt posting is
`budget/service.py:539–735`; GPU interval overlap protection is there too.
Existing ledger/policy is `budget/ledger.py:300–355` and `budget/policy.py`.
Contract models and cross-record validators are guardian-owned and frozen in
`contracts/cost.py:287–460` (package 2.13.0); do not edit them. Do not edit rendering transports,
pipeline registration, root config, review, publishing or task ledger.

Acceptance: idempotent raw observation and revision/delta; exact integer money
and full component allocation; warm-lease overlap split and recovery pool;
post-stop disk ownership; empty/unknown stays pending; invoice mismatch and
finality; replay/concurrency/restart with no duplicate charges or allowance
restoration. Test isolated PG migration upgrade/readback and these cases; run
scoped tests/Ruff/contracts-check. Parent runs full `make check` after
integration. Return exact commands/results, any schema proposal and T045
bootstrap handoff. No commit.
