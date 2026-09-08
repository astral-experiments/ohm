# Clippy/codegen benchmarks

These studies compare Ohm 1.98.0-10 with and without `-Zohm-clippy-codegen` on Linux. Each comparison keeps both arms on one machine, with the same installed compiler, Cargo, Clippy, source revisions, profiles, and job count. Matched validation and current sessions use Linux host A; the full workflow matrix, uv ablations, and historical Ruff pairs use Linux host B. Absolute times are not compared across machines.

The [result file](../scripts/benchmark_results/clippy-codegen-1.98.0-10.json) contains individual observations, tool and source identities, and hashes and locations for the retained raw archives.

## Matched validation results

Combining Clippy and tests took 17.6–50.8% less time than running the two commands separately in these focused workflows. Direct edits took 12.6% longer than tests alone in uv and 27.5% longer in Codex. Cold results have one observation per arm; the other rows show medians of six observations.

| Project    | Phase      | Tests only | Clippy then tests | Combined | Time saved vs separate |
| ---------- | ---------- | ---------: | ----------------: | -------: | ---------------------: |
| uv         | cold       |    147.23s |           217.12s |  152.66s |                  29.7% |
| uv         | noop       |      1.65s |             3.35s |    1.74s |                  48.0% |
| uv         | dependency |      6.96s |             8.44s |    5.54s |                  34.4% |
| uv         | direct     |     18.11s |            24.75s |   20.39s |                  17.6% |
| codex-core | cold       |    244.72s |           388.03s |  260.40s |                  32.9% |
| codex-core | noop       |      3.05s |             5.59s |    3.04s |                  45.7% |
| codex-core | dependency |      6.46s |            10.03s |    4.94s |                  50.8% |
| codex-core | direct     |     30.86s |            53.61s |   39.34s |                  26.6% |

After all edits, the private target directories occupied the following stat-allocated space:

| Project    | Tests only | Clippy then tests | Combined |
| ---------- | ---------: | ----------------: | -------: |
| uv         |   6.80 GiB |          8.04 GiB | 6.80 GiB |
| codex-core |   9.14 GiB |         11.37 GiB | 9.18 GiB |

These sizes count stat-allocated blocks once per regular-file inode within each root and include each workflow’s retained edit history. They are not physical or reclaimable copy-on-write measurements.

## Validation workflows

The workflow comparison uses the existing uv and Codex edits from [`benchmark.py`](../scripts/benchmark.py):

- **Tests only:** ordinary compilation and the selected test.
- **Separate:** standalone Clippy followed by the same test command, sharing a private target directory.
- **Combined:** the test command with Clippy/codegen enabled.

The two linting workflows use the same Cargo target selection and workspace lint settings: uv's `it` integration-test target, and the Codex core library-test target. Both use the test profile; standalone `clippy --lib --profile test` selects the library test harness without adding integration targets. This is a focused validation comparison; it does not replace workspace-wide `clippy --all-targets`.

Each arm has its own target directory. Cold runs start with empty target directories. Six no-op, dependency-edit, and direct-edit samples use all six permutations of the three arms. Cycle times sum the command timers; source resets, warmups, pre-command idle checks, and runner bookkeeping are excluded. Command logs and rejected observations are retained. Completed target directories are removed after their footprint is recorded. The tests-only arm measures the added cost of linting; the separate arm measures the benefit of combining work that otherwise needs two commands.

## Published benchmark matrix

A second workflow pass schedules the 216 cells in the published benchmark matrix with default Ohm and opt-in Ohm: cold, no-op, dependency, and direct edits for check, Clippy, and test; build-to-check transitions; formatting; and shared-worktree builds. Both arms use the same shared-build behavior. Standalone Clippy and formatting are explicit controls with the combined option disabled in both arms; check, build, and test enable it only in the opt-in arm.

Ohm 1.98.0-10 fails the immutable-registry-cache readiness check before the shared-worktree timings. Its automatically supplied Wild linker flags are treated as user overrides by the cache trust checks. These cells are reported as unmeasured readiness failures. The remaining workflows use the released toolchain unchanged; build-to-check timings therefore also include this release’s failure to reuse immutable registry artifacts. The proposed [Cargo fix](https://github.com/astral-sh/ohm-cargo/pull/123) and [installed-release regression check](https://github.com/astral-sh/ohm/pull/113) are validated separately.

### Workflow results

The completed matrix contains 212 measurements. Four additional shared-worktree cells remain unmeasured: each arm and project failed its own immutable-cache readiness probe. Values below are medians; `n` is the count per arm. Standalone Clippy and formatting use identical settings in both arms, so their differences show measurement variation.

| Project    | Workflow    | Phase      |  Default |   Opt-in |   n | Control |
| ---------- | ----------- | ---------- | -------: | -------: | --: | ------- |
| uv         | check       | cold       |  69.517s |  72.771s |   1 |         |
| uv         | check       | noop       |   0.474s |   0.499s |   3 |         |
| uv         | check       | dependency |   1.167s |   0.816s |   7 |         |
| uv         | check       | direct     |   3.573s |   3.716s |   5 |         |
| uv         | clippy      | cold       |  76.244s |  74.333s |   1 | yes     |
| uv         | clippy      | noop       |   0.518s |   0.576s |   3 | yes     |
| uv         | clippy      | dependency |   0.848s |   0.826s |   7 | yes     |
| uv         | clippy      | direct     |   3.434s |   3.536s |   5 | yes     |
| uv         | test        | cold       | 143.982s | 152.939s |   1 |         |
| uv         | test        | noop       |   1.293s |   1.338s |   3 |         |
| uv         | test        | dependency |   5.518s |   5.022s |   7 |         |
| uv         | test        | direct     |  14.900s |  15.071s |   5 |         |
| uv         | build-check | transition |  71.236s |  71.600s |   1 |         |
| codex-core | check       | cold       | 120.272s | 121.672s |   1 |         |
| codex-core | check       | noop       |   1.060s |   1.127s |   3 |         |
| codex-core | check       | dependency |   1.754s |   1.541s |   7 |         |
| codex-core | check       | direct     |   6.852s |   6.944s |   5 |         |
| codex-core | clippy      | cold       | 161.051s | 151.272s |   1 | yes     |
| codex-core | clippy      | noop       |   1.246s |   1.090s |   3 | yes     |
| codex-core | clippy      | dependency |   1.437s |   1.438s |   7 | yes     |
| codex-core | clippy      | direct     |  17.550s |  17.349s |   5 | yes     |
| codex-core | test        | cold       | 237.998s | 248.723s |   1 |         |
| codex-core | test        | noop       |   2.961s |   2.612s |   3 |         |
| codex-core | test        | dependency |   4.730s |   4.434s |   7 |         |
| codex-core | test        | direct     |  29.679s |  32.080s |   5 |         |
| codex-core | build-check | transition | 107.859s | 115.491s |   1 |         |
| codex-core | fmt         | noop       |   0.317s |   0.418s |   3 | yes     |
| codex-core | fmt         | direct     |   0.589s |   0.529s |   5 | yes     |

The uv feature experiment crosses all four public-API-hash/procedural-macro-cache combinations with Clippy/codegen disabled and enabled. Two repetitions give 16 replays, or eight matched pairs. Each arm retains the original fixture's downstream check and parser tests, with separate caches for each combination.

### uv ablation results

Each value is the median of two replays on Linux host B, including the same private parser edit, downstream check, and nine selected parser tests.

| Public API hashes | Proc-macro cache | Default total | Opt-in total | Default commands | Opt-in commands |
| ----------------- | ---------------- | ------------: | -----------: | ---------------: | --------------: |
| on                | on               |        3.556s |       3.990s |           3.117s |          3.892s |
| off               | on               |        5.696s |       7.841s |           5.589s |          7.722s |
| on                | off              |        3.275s |       4.029s |           3.172s |          3.925s |
| off               | off              |        6.075s |       8.191s |           5.975s |          8.088s |

Totals include edit preparation and application, pre-command idle checks, and runner bookkeeping. The first default run with both features enabled spent 0.768s outside the command and edit timers; the other cells spent 0.093–0.125s. The result file retains both observations and their separate command/edit totals.

## Recorded sessions

The comparison replays the existing Ruff/ty, uv, and Codex sessions, plus the historical Ruff session. It compares default Ohm with opt-in Clippy/codegen while keeping every recorded command, including standalone Clippy and formatting checks. Standalone Clippy runs with the combined option disabled because its compiler wrapper is incompatible with that option.

Some recorded Clippy steps cover more targets than the preceding focused test commands. Retaining those steps preserves their lint coverage. This comparison therefore measures the effect of enabling the option in an unchanged development session, including any duplicated lint work. It answers a different question from the combined-validation comparison above.

Each arm and repetition has private worktree, target, and shared-build directories. Both arms use the replay runner's procedural-macro trust setting. Repetitions run default/combined, then combined/default. Warmups and source setup are reported separately.

### Current session results

Each entry shows the median and range of two complete replays on Linux host A, excluding warmups. All recorded lint, formatting, and test commands passed.

| Session |  Default median (range) |   Opt-in median (range) |
| ------- | ----------------------: | ----------------------: |
| ruff    | 369.73s (357.90–381.57) | 375.25s (368.29–382.21) |
| uv      | 144.69s (143.77–145.62) | 140.94s (134.82–147.07) |
| codex   | 452.63s (451.18–454.08) | 470.71s (467.02–474.41) |

Codex timings are descriptive observations: substantial Falcon security-service CPU activity repeatedly overlapped its final package tests, including the rerun. They do not support a quiet-run or speedup claim. The four final selections each contain the same 3,439 unique test identities.

### Historical Ruff results

The historical session runs twice per arm on Linux host B. Each replay retains all source edits and commands, including strict Clippy, formatting, and the final 867 package tests.

| Session |  Default median (range) |   Opt-in median (range) |
| ------- | ----------------------: | ----------------------: |
| Ruff    | 363.02s (362.95–363.09) | 383.12s (381.75–384.50) |

## Measurement conditions

The runner requires six consecutive five-second preflight intervals with at least 95% CPU idle, at most 0.5% I/O wait and 0.1% steal, and no unrelated compiler processes. Process monitoring continues during commands. Both arms use eight build jobs and the checksum-verified release toolchain. Raw evidence records executable hashes, helper versions, source revisions, test counts, and command logs.

The VMs also run periodic Teleport and Kubernetes maintenance, using roughly one CPU each while active, and ordinary system and security services. These system services remain enabled. Their timing and CPU use are recorded as background activity; balanced arm ordering reduces dependence on when they run. A completed Codex/default session was excluded after its final test overlapped substantial Falcon security-service CPU use. Its source and 3,439-test selection proof are retained; the complete default/opt-in pair was restarted. Command-level CPU overlap is reviewed using log-write timestamps and two-second process snapshots, so interval boundaries are approximate. The CPU trace for other processes on Linux host A starts during the Codex cold builds. All 76 timed uv components and one Codex cold component in the matched study precede that trace; they have the initial idle gate and compiler monitoring.

In the current sessions, the four final Codex test commands averaged 15.8–17.3% external CPU across the 32-CPU VM, with interval peaks up to 31.3%. Two short Ruff commands averaged 5.4% and 6.2%; longer Ruff commands had brief peaks up to 17.3% with much lower means. The highest uv command mean was 4.8%. On Linux host B, the largest command means were 6.3% for the workflow matrix, 3.5% for ablations, and 5.9% for historical Ruff; interval peaks reached 11.9%. These are observations with recorded background activity.

The released toolchain passes the 25 original cross-component smoke checks on Linux. Additional controls verify that the environment setting used by the benchmark disables lint denial when false and rejects the same program when true.

Combined compilation preserves normal Rust cfgs rather than adding `cfg(clippy)`. Normal lowering can also change individual diagnostics. Both validation workflows run Clippy on the selected targets, but do not promise byte-identical diagnostics. The unchanged-session comparison retains standalone Clippy for those differences.

## Reproduce

Install Ohm 1.98.0-10, just 1.58.0, cargo-nextest 0.9.140, and the fixture dependencies before running on a quiet Linux host. The harness runs with the host's Python 3.12.3; the uv workloads use Python 3.12.13 and uv 0.12.8.

```sh
python3 scripts/benchmark_clippy_codegen.py workflows \
  --ohm ohm-1.98.0-10 --jobs 8 \
  --cold-runs 1 --noop-runs 6 --dependency-runs 6 --direct-runs 6 \
  --require-idle --discard-targets --output-dir /path/to/empty-workflow-results

umask 022
mkdir -m 700 -p /tmp/ohm-cr10
export TMPDIR=/tmp/ohm-cr10

python3 scripts/benchmark_clippy_codegen.py replay \
  --ohm ohm-1.98.0-10 --jobs 8 --repetitions 2 \
  --scenario scripts/session_replays/ruff-rust-1.98.json \
  --scenario scripts/session_replays/codex-stable-goal-accounting.json \
  --require-idle --offline --discard-targets --output-dir /path/to/empty-session-results
```

For the historical Ruff comparison, run the replay command with `--project ruff --scenario scripts/session_replays/ruff-historical-rust-1.98.json` and a separate output directory. Both commands support the source-path options of their underlying runners.

```sh
python3 scripts/benchmark_clippy_codegen_matrix.py workflows \
  --ohm ohm-1.98.0-10 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --require-idle --discard-targets --output-dir /path/to/empty-matrix-results

python3 scripts/benchmark_clippy_codegen_matrix.py ablation \
  --ohm ohm-1.98.0-10 --jobs 8 --repetitions 2 --project uv \
  --scenario scripts/session_replays/uv-feature-ablation.json \
  --require-idle --offline --discard-targets --output-dir /path/to/empty-ablation-results
```

On Ohm 1.98.0-10, the workflow matrix stops at the shared-cache readiness error. The retained continuation runs the remaining commands with the same inputs and counters, records each missing shared-cache cell separately, and preserves the original results unchanged.

## Excluded attempts

An unrelated linker observed during an earlier attempt could not be attributed after it exited. That attempt was excluded in full. Subsequent runs use the replay runner’s process-group-aware monitor to recognize briefly reparented helpers. Preflight attempts that missed the idle or I/O-wait limits remain archived; each restart required a fresh six-interval gate.

The first Codex session attempt failed seven existing tests because the launcher inherited umask `0002` and used `/tmp/oc10` for temporary files. The socket tests reject group-writable directories. The Kitty test incorrectly treats `cG5n` inside the base64-encoded temporary file path as inline image data. Focused reruns confirmed that umask `0022` and `/tmp/ohm-cr10` resolve these assertions without source or test-selection changes. The entire incomplete Codex cell was excluded and restarted. Both arms of every accepted pair use the same environment; the completed Ruff and uv pairs from repetition zero were retained.

The first ablation warmup failed because a logical arm label containing `:` was also used in its target directory, which Cargo includes in the dynamic-library search path. Target and shared-cache paths now use separate arm and feature directories. No measured ablation cell preceded this correction; the original harness, logs, and cache artifacts are retained.
