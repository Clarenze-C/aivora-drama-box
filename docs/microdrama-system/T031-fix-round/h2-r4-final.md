**H2-R4: ALL FIXES DONE**

- **R1 / HD-1** — DONE, commit `92f7b51`: `resolve_sample` binds the composed RECOVERY world to the owning acquisition before probing; composition/binding failures and `EffectDenied` refuse even with `--force-unrecoverable` (only R7's source evidence reaches force). Red `3 failed, 1 passed in 11.75s` → green `4 passed`, regressions `32 passed`.
- **R2 / HD-3 + HC-10 gaps** — DONE, commit `621e49e`: race proofs reject `ServiceUnavailable` incl. translated 40P01/55P03 (injection through the real translator, red `1 failed in 2.87s` on the pre-R4 proof); wrapper race re-interleaved on an L holder and proven red against the restored pre-P4 order (`ServiceUnavailable('deadlock detected')`, `1 failed in 10.80s`); AT-9 `sweep_finalization_mid` now dies in a real subprocess between the sweep's finalization stages and the next sweep completes every stage exactly once; F2's worker connection gets the bounded `lock_timeout` explicitly. All test-only.
- **R3 / HD-2** — DONE, commit `0cda424`: the late identity is chosen once under the account lock (serialized with posting and closure); an interval already posted while ACTIVE keeps its immutable ACCRUAL identity on replay after closure — same receipt UUID and provider key, `accrued_until` advances. Red `1 failed in 6.60s` (`Conflict: interval already attributed`) → green `5 passed`.

Final net at `0cda424`: **85 passed** across all nine H2/HCF files, `make lint` clean; working tree clean apart from pre-existing untracked strays. Two scratch branches kept as red-proof evidence (never merge): `t031-r4-red-oldorder` @ `05369f7`, `t031-r4-red-oldproof` @ `ccc9b53`.

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-r4-REPORT.md`
