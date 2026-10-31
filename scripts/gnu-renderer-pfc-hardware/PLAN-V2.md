# Registration amendment for the native GNU renderer experiment

This amendment changes the spelling of one rustc type in each candidate. It is sealed before either candidate builds successfully and before the first candidate instruction count. The original registration in `ORDINARY-STUDY.md` (SHA-256 `70076984ab6feb82a8a9eae43cb9a9c34eec7a9cc42a50305c018391c14afe66`) still defines the workloads, the selected whole-command endpoint, the host order, every threshold, all correctness and storage controls and both independent cohorts.

| Role | Previously enrolled Rust commit | Newly enrolled Rust commit | New compiler tree |
| --- | --- | --- | --- |
| P | `4e7c5b1f765b24ccd585d8ddb7eeae99a02b514e` | `4e7c5b1f765b24ccd585d8ddb7eeae99a02b514e` | `b429aa02503b16993d9b8f94a6ab17f4f3bfaa01` |
| F | `96e6c29c1ed9bf7229ef3b89843712139529cd10` | `51e72261c0b36dfd49c078b35732956d6b950e8e` | `84107218ae14ae41937c2bbea83b84338ac18d9d` |
| C | `b79ec99c44772853c313161bee2bbfaecc80e0de` | `11876886792274b44a9a37567fbac57bf843a24c` | `d4b3be137de57d758c2f68712ffb5c819496ec1c` |

The first source run stopped before testing P because a separate rustdoc invocation removed libcore from the sysroot. The second built and tested P, verified identical 81-file manifests before and after the regression suite, then stopped compiling F on `rustc::usage_of_qualified_ty` with warnings denied. It never built C. The source job now requests rustc, rustdoc and the library together. Each candidate imports `Ty` beside `TyCtxt` and uses `Ty<'tcx>` at the single closure annotation. The reconstruction script compares both complete compiler sources and fixtures against their previously enrolled counterparts. [First source job](https://github.com/astral-experiments/ohm/actions/runs/41183356225) · [Second source job](https://github.com/astral-experiments/ohm/actions/runs/41184069572)

Use fresh, complete P/F/C toolchains produced on one successful source job with the fixed Cargo and signed Wild specified in the original registration. Require that job's product and observation archives and the independent unscored native and Ruff qualification before either screen host can enter the scored study. The ordinary modern Ruff source-map edit uses the workspace's O1 dev setting. The historical notebook edit uses its original O0 setting and remains the fixed holdout for regressions. Both continue to use the exact ordinary commands and complete historical input changes originally registered.
