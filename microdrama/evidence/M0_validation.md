# M0 exit validation (Contracts ready)

Independent validator (no implementation duties) ran five rounds against T001/T002/T003/T007.

| Round | Commit | Verdict | Outcome |
|---|---|---|---|
| 1 | 7de642a | FAIL | 25 findings (7 critical: approval trigger trusted caller time, unbound season/package approvals, fake-evidence records, readback links, qualification rules, preset Thai/quality). Fixed in contract 1.2.0 + migration 0007 (388ed9a). |
| 2 | 388ed9a | FAIL | 19/25 closed; new N-3 (decision recorded on a BLOCKED package then laundered), V-22/V-4 disputes, N-1/N-2/N-4/N-5. Fixed in 0008 + 1.2.1 (5b72cad). |
| 3 | 5b72cad | FAIL | N-3 closed; caption seam N-6/N-7/N-8, text-JSON floats N-9, evidence shapes N-10. Fixed by class in 0009 (713ed57). |
| 4 | 713ed57 | FAIL | float + evidence classes closed; caption helper NULL trap N-11 and unguarded tables N-12..N-14, N-15. Fixed in 0010 + schema catalog test (c6c35e5). |
| 5 | c6c35e5 | **PASS_WITH_FINDINGS** | No critical/major demonstrable. Minor R5-1..R5-4 fixed in 0011 + catalog test (this commit); validator probe_db_r5: 14/15, the remaining line is the probe reporting that the R5-1 gap no longer reproduces. |

Recorded decisions and residuals (see `contracts/COMPATIBILITY.md`, "Recorded guardian decisions"):
- Fake-evidence fixtures allowed only in OFFLINE_MOCK databases (`md_runtime_mode`); T006 must
  also refuse them outside mock and refuse non-fake labels on fake-provenance records (D3 —
  a named T006 acceptance criterion with tests).
- Deployment role must not own tables / hold ALTER, DROP, TRIGGER or md_runtime_mode UPDATE;
  `/ready` must compare DB mode with Settings and detect ownership (T029).
- T020 re-checks listed caption tracks before every submit (N-17); T026 allow-lists provider
  URL shapes (N-2); T019 reserves funds per human revision (V-20).
- Residuals: a float literal written into SQL source; floats in TEXT columns (no money column
  is text); JSON Schema cannot reject integral floats (Pydantic does).

Final state: `make check` passes (163 unit / 124 contract / 124 integration at this commit).
