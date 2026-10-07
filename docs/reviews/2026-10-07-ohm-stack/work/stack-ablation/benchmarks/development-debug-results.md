# Development debug: representative library builds

**Keep the intended `line-tables-only` development default.** In this screen, it saves a median 10.64 s on a cold Ruff build, 4.42 s on uv and 36.30 s on Codex. Ruff edits and Codex Edits 1 and 2 improve in both orders; Codex Edit 3 is mixed. uv Edits 1 and 3 improve in both orders, while Edit 2 is slower in both. Warm no-ops are mixed and occasionally slower. Full debug remains useful when a debugger must inspect variables and types. The performance result supports a default policy, with a deliberate full-debug override for that workflow.

Both arms use the same compiler, Cargo, source, PGO and installed libraries. The full arm sets `CARGO_PROFILE_DEV_DEBUG=2` and `CARGO_PROFILE_TEST_DEBUG=2`; the line-table arm sets both to `line-tables-only`. The selected timed commands use the **dev profile**. This comparison does not remove compiler code, measure test-profile performance, measure final executable linking, or establish equivalent variable inspection in a debugger.

Each project ran two opposite-order pairs on `charlie-oss-4`, using eight Cargo jobs and separate initially empty target/shared histories. Slot 0 ran debug=2 then line tables; slot 1 ran line tables then debug=2. Each arm ran the original five library BUILD states: cold, warm no-op, and after each of three recorded source edits. The package selection was `ty_python_semantic`/`ty_python_core` for Ruff, `uv-pypi-types`/`uv-client` for uv, and `codex-tui` for Codex; every command retained `--locked --offline --lib`. Source preparation and dependency availability preceded timing; zero project tests ran.

Edits 1, 2 and 3 follow each project’s recorded source history in order. Ruff simplifies recursive attribute inference, indexes implicit attribute dependencies, then adds component fixed points. uv implements the dedicated Simple API JSON parser, simplifies its implementation, then simplifies compatibility tests. Codex adds transcript layout bookkeeping, implements stable active-cell rendering and snapshots, then invalidates cached layouts when active cells are removed. Each state retains the previous edits; the third uv edit may be inactive for the selected library commands.

All deltas below mean **line tables minus debug=2**. A negative delta favors line tables. Percentages are medians of the two paired percentages; the delta interval is the range of those two observed cells, not a confidence interval. This is a two-pair screen for each project. No outlier was removed.

| Project | State | Debug=2 median (s) | Line-table median (s) | Paired median delta (s) | Paired delta range (s) | Paired median (%) | Line tables slower |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| Ruff | cold | 77.882 | 67.243 | -10.639 | -10.971 to -10.307 | -13.66 | 0/2 |
| Ruff | warm no-op | 0.515 | 0.742 | +0.227 | -0.031 to +0.485 | +46.90 | 1/2 |
| Ruff | edit 1 | 31.790 | 28.051 | -3.739 | -4.034 to -3.444 | -11.77 | 0/2 |
| Ruff | edit 2 | 41.281 | 36.056 | -5.225 | -6.406 to -4.044 | -12.65 | 0/2 |
| Ruff | edit 3 | 47.879 | 39.384 | -8.494 | -9.044 to -7.945 | -17.73 | 0/2 |
| uv | cold | 72.324 | 67.905 | -4.419 | -5.106 to -3.731 | -6.08 | 0/2 |
| uv | warm no-op | 0.831 | 0.854 | +0.022 | -0.078 to +0.123 | +1.20 | 1/2 |
| uv | edit 1 | 9.716 | 8.845 | -0.871 | -1.313 to -0.429 | -8.76 | 0/2 |
| uv | edit 2 | 5.998 | 6.520 | +0.522 | +0.142 to +0.902 | +9.14 | 2/2 |
| uv | edit 3 | 7.438 | 6.505 | -0.934 | -1.358 to -0.509 | -12.52 | 0/2 |
| Codex | cold | 287.430 | 251.125 | -36.304 | -39.102 to -33.506 | -12.62 | 0/2 |
| Codex | warm no-op | 10.948 | 2.423 | -8.525 | -15.344 to -1.706 | -63.41 | 0/2 |
| Codex | edit 1 | 29.907 | 22.947 | -6.960 | -9.019 to -4.902 | -23.76 | 0/2 |
| Codex | edit 2 | 16.919 | 14.131 | -2.788 | -5.283 to -0.294 | -14.82 | 0/2 |
| Codex | edit 3 | 16.251 | 14.367 | -1.884 | -4.383 to +0.615 | -10.17 | 1/2 |

The individual cells preserve the direction of the two orders. Small no-op percentages can look large because these commands take less than two seconds. The absolute deltas are the practical comparison.

| Project | State | Slot 0 delta (s / %) | Slot 1 delta (s / %) |
| --- | --- | ---: | ---: |
| Ruff | cold | -10.971 / -14.10% | -10.307 / -13.22% |
| Ruff | warm no-op | -0.031 / -5.75% | +0.485 / +99.55% |
| Ruff | edit 1 | -4.034 / -12.79% | -3.444 / -10.75% |
| Ruff | edit 2 | -4.044 / -9.83% | -6.406 / -15.46% |
| Ruff | edit 3 | -7.945 / -16.72% | -9.044 / -18.75% |
| uv | cold | -5.106 / -6.80% | -3.731 / -5.36% |
| uv | warm no-op | -0.078 / -10.75% | +0.123 / +13.14% |
| uv | edit 1 | -1.313 / -12.87% | -0.429 / -4.65% |
| uv | edit 2 | +0.142 / +2.23% | +0.902 / +16.05% |
| uv | edit 3 | -1.358 / -18.15% | -0.509 / -6.88% |
| Codex | cold | -39.102 / -13.37% | -33.506 / -11.87% |
| Codex | warm no-op | -15.344 / -87.27% | -1.706 / -39.54% |
| Codex | edit 1 | -9.019 / -32.05% | -4.902 / -15.47% |
| Codex | edit 2 | -5.283 / -27.64% | -0.294 / -1.99% |
| Codex | edit 3 | +0.615 / +4.20% | -4.383 / -24.54% |

## Memory and artifact size

GNU `time` records the maximum RSS of an individual child process in each command. It does **not** measure concurrent aggregate memory. The following medians and observed ranges use GiB (KiB / 1,048,576).

| Project | State | Debug=2 child RSS median [range], GiB | Line-table child RSS median [range], GiB |
| --- | --- | ---: | ---: |
| Ruff | cold | 3.920 [3.904, 3.935] | 3.277 [3.262, 3.293] |
| Ruff | warm no-op | 0.060 [0.060, 0.060] | 0.060 [0.060, 0.060] |
| Ruff | edit 1 | 4.129 [4.120, 4.137] | 3.528 [3.525, 3.532] |
| Ruff | edit 2 | 4.840 [4.840, 4.840] | 4.294 [4.292, 4.296] |
| Ruff | edit 3 | 5.050 [5.048, 5.052] | 4.342 [4.335, 4.350] |
| uv | cold | 1.027 [1.016, 1.038] | 0.955 [0.948, 0.961] |
| uv | warm no-op | 0.089 [0.089, 0.090] | 0.089 [0.089, 0.089] |
| uv | edit 1 | 1.066 [1.065, 1.067] | 0.968 [0.966, 0.969] |
| uv | edit 2 | 0.964 [0.961, 0.967] | 0.869 [0.866, 0.872] |
| uv | edit 3 | 1.012 [1.002, 1.022] | 0.873 [0.868, 0.878] |
| Codex | cold | 3.885 [3.877, 3.894] | 3.253 [3.249, 3.257] |
| Codex | warm no-op | 0.180 [0.180, 0.180] | 0.180 [0.180, 0.180] |
| Codex | edit 1 | 4.279 [4.269, 4.289] | 3.727 [3.725, 3.729] |
| Codex | edit 2 | 3.299 [3.293, 3.305] | 2.926 [2.909, 2.943] |
| Codex | edit 3 | 2.602 [2.579, 2.624] | 2.578 [2.575, 2.581] |

The final history artifact sizes are secondary evidence. The logical size below adds the history’s target and shared-build files after its last edit; it counts files in both roots. The unique allocated size deduplicates inode sharing across those roots. Neither is a latency estimate, and neither includes the installed toolchain or registry cache.

| Project | Debug=2 logical median [range], GiB | Line-table logical median [range], GiB | Debug=2 unique allocated median, GiB | Line-table unique allocated median, GiB |
| --- | ---: | ---: | ---: | ---: |
| Ruff | 2.954 [2.954, 2.954] | 1.812 [1.812, 1.812] | 2.410 | 1.575 |
| uv | 2.195 [2.195, 2.195] | 1.494 [1.494, 1.494] | 2.141 | 1.469 |
| Codex | 16.159 [16.159, 16.159] | 8.458 [8.458, 8.458] | 15.503 | 8.144 |

## Profile validation and scope

The current fixtures produced 24 untimed Cargo unit graphs: two arms for each project at the initial source and after all three edits. Matching units preserve dependencies, features, roots, opt-level, LTO, incremental settings, codegen settings and every serialized field other than debuginfo. Package and build overrides remain authoritative. Two tiny untimed library builds with standard Cargo `-vv`, using the same Cargo/runtime, verified the environment-value mapping to `-C debuginfo=2` and `-C debuginfo=line-tables-only`; those builds are validation evidence only. The frozen Cargo argument-builder source binds that mapping to the project graphs.

| Project | Phase-0 units | Debug=2 → line tables | Unchanged debug=0 units |
| --- | ---: | ---: | ---: |
| Ruff | 266 | 159 | 107 |
| uv | 532 | 408 | 124 |
| Codex | 1357 | 941 | 416 |

These explicit profile overrides price debug=2 versus line tables on the recorded libraries. They do not claim that each repository currently builds every unit with full debug by default. Repository-specific package/build overrides, including debug=0, were retained. The dev/test environment values are recorded, but only dev library build performance was timed.

The choice has much less maintenance cost than a compiler fork: it is a development-profile policy, not a compiler algorithm or extra cache. Removing the line-table default would restore more debug information and its measured build/artifact cost. Keep the narrow policy while keeping full debug available for debugging that needs it. The screen does not justify changing release debug, a custom repository profile, or debugger functionality.

## Histories and accepted evidence

The totals below add the five timed commands. They exclude source edits, setup, validation, quiet waits and rejected attempts; they do not predict how often developers run each state.

| Project | Slot 0 command-total delta (s / %) | Slot 1 command-total delta (s / %) |
| --- | ---: | ---: |
| Ruff | -27.025 / -13.61% | -28.716 / -14.35% |
| uv | -7.714 / -7.72% | -3.644 / -3.93% |
| Codex | -68.132 / -18.32% | -44.790 / -12.76% |

The 60 accepted commands total 40.807 minutes of elapsed command time. This is not total campaign duration. Three rejected whole attempts remain in the raw archive and contribute no accepted cells. Replacements ran complete original pairs after positive release and the unchanged host gates. The final root audit accepted all six pairs, 60 commands, 15 command statistics, 1,947 continuous monitor observations and 144 quiet observations. All source/lock/status phases match; raw log hashes are checked without a claim of identical warning rendering.

The [final root review](development-debug-inplace-openai3-01/debug-final-root-review-01.json) (SHA-256 `96aca4d654fcb2dbd0302ea3a0cea4d3b8dbf0388f394c83a639b0e14fef3024`) rehashed all 892 payloads, 893 safe original tar members and modes, all 35 readiness proofs, the complete same 69,859-file runtime and 14 loader environments, accepted schedules and current ownership release. The [per-command statistics](development-debug-inplace-openai3-01/debug-complete-command-root-review-01.json) retain both samples and RSS; the [campaign audit](development-debug-inplace-openai3-01/completed-raw-retrieval-ssh-01/campaign-audit-01.json) records the accepted/rejected histories.

The immutable [raw archive](development-debug-inplace-openai3-01/completed-raw-retrieval-ssh-01/raw.tar.gz.not-included.md) is 117,939,136 bytes, SHA-256 `ed6ed1bea287323378d7ed40745e5b6dd369cf4169dd9156cbd710e186be47d4`. The [last reader/current release](development-debug-inplace-openai3-01/final-reader-ownership-actual-ssh-01/stdout.txt) has SHA-256 `48b49666724418b68bd20a95c1a3b9a142aef569f4f079cde653321dc6cb2e50`. No native, optimized compiler build or training suite was repeated on the timing host.
