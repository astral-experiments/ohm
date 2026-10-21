# Test/build overlap

We compare the published Ohm 1.99.0-6 binary with the overlap option unset and with `CARGO_UNSTABLE_OHM_READY_TESTS=true`. Each pair uses the same source, commands, profiles, and cache settings on the same host. Linux timing runs rotate and reverse the configuration order. APFS allocation cohorts run with the option unset first, then enabled.

With 4 repetitions, overlap reduced the median edited test command in the constructed uv workspace workload from 21.21 s to 16.57 s (21.9%). The recorded uv session changed from a mean of 99.42 s to 97.15 s (2.3%, 2 repetitions); interpret that smaller difference alongside the Nextest controls.

Positive percentages mean the option saved time. Small differences, especially with two repetitions or a single cold build, may reflect measurement variation.

The option applies to Cargo’s test runner. Cargo [disables it for `--no-run` and JSON build output](https://github.com/astral-sh/ohm-cargo/blob/5e5d271d763d7beb38b48755e22bd59e93f02b97/src/ops/cargo_test/mod.rs#L70-L78), which Nextest uses to build its test executables. Ruff/ty and Codex use Nextest in these workflows, so their timings provide a control. UV uses `cargo test`; the constructed workspace workload selects multiple test executables that can overlap with remaining builds.

## Developer workflows

| Workload                                    | Overlap off | Overlap on | Time saved | Repetitions |
| ------------------------------------------- | ----------: | ---------: | ---------: | ----------: |
| Ruff/ty / edit → focused test               |     12.76 s |    12.80 s |      -0.3% |           4 |
| Ruff/ty / edit dependency → downstream test |      3.03 s |     3.47 s |     -14.8% |           4 |
| Ruff/ty / edit → check → test → check       |     19.26 s |    19.94 s |      -3.5% |           4 |
| Ruff/ty / check → build → check             |     52.73 s |    53.19 s |      -0.9% |           4 |
| Ruff/ty / edit → format → Clippy → test     |     21.12 s |    21.09 s |      +0.1% |           4 |
| uv / edit → focused test                    |      9.49 s |     9.32 s |      +1.8% |           4 |
| uv / edit dependency → downstream test      |      3.34 s |     3.41 s |      -2.2% |           4 |
| uv / edit → check → test → check            |     12.75 s |    13.15 s |      -3.1% |           4 |
| uv / check → build → check                  |     76.70 s |    77.11 s |      -0.5% |           4 |
| uv / edit → format → Clippy → test          |     15.38 s |    15.78 s |      -2.6% |           4 |
| Codex / edit → focused test                 |     27.81 s |    26.84 s |      +3.5% |           4 |
| Codex / edit dependency → downstream test   |      5.57 s |     5.55 s |      +0.4% |           4 |
| Codex / edit → check → test → check         |     36.75 s |    34.77 s |      +5.4% |           4 |
| Codex / check → build → check               |    132.44 s |   132.66 s |      -0.2% |           4 |
| Codex / edit → format → Clippy → test       |     34.91 s |    35.18 s |      -0.8% |           4 |

Aggregation: median.

Source: [developer-workflows.json](developer-workflows.json).

## Session replays

| Workload | Overlap off | Overlap on | Time saved | Repetitions |
| -------- | ----------: | ---------: | ---------: | ----------: |
| uv       |     99.42 s |    97.15 s |      +2.3% |           2 |
| Codex    |    348.26 s |   341.99 s |      +1.8% |           2 |
| Ruff/ty  |    306.36 s |   307.17 s |      -0.3% |           2 |

Aggregation: mean of full replay totals, including edits and runner overhead; warmup excluded.

Source: [sessions.json](sessions.json).

## Historical session

| Workload | Overlap off | Overlap on | Time saved | Repetitions |
| -------- | ----------: | ---------: | ---------: | ----------: |
| Ruff/ty  |    277.81 s |   271.51 s |      +2.3% |           2 |

Aggregation: median of each replay's timed-command total; edits and warmup excluded.

Source: [historical.json](historical.json).

## ty session

| Workload | Overlap off | Overlap on | Time saved | Repetitions |
| -------- | ----------: | ---------: | ---------: | ----------: |
| ty       |    181.93 s |   183.33 s |      -0.8% |           4 |

Aggregation: mean of session totals, including edits and runner overhead; initial CLI build excluded.

Source: [ty-worktree.json](ty-worktree.json).

## Parser-edit benchmark

| Workload | Overlap off | Overlap on | Time saved | Repetitions |
| -------- | ----------: | ---------: | ---------: | ----------: |
| uv       |      2.46 s |     2.47 s |      -0.4% |           2 |

Aggregation: median of each replay's timed-command total; edits and warmup excluded.

Source: [ablation-overlap.json](ablation-overlap.json).

## Constructed workspace test workload

| Workload           | Overlap off | Overlap on | Time saved | Repetitions |
| ------------------ | ----------: | ---------: | ---------: | ----------: |
| uv / after edit    |     21.21 s |    16.57 s |     +21.9% |           4 |
| uv / cold baseline |    163.07 s |   150.30 s |      +7.8% |           4 |

Aggregation: median of each replay's timed-command total; edits and warmup excluded. median wall time of the recorded baseline test command, starting from fresh artifacts; reported separately from the edited replay.

RUST_TEST_THREADS=1 in every configuration of the constructed workspace workload avoids a process-global certificate-environment race in uv-client tests. Cargo may still overlap test executables with compilation. The earlier parallel-libtest attempt is excluded in full and retained in the raw evidence.

Source: [constructed-overlap.json](constructed-overlap.json).

## Individual commands

| Workload                                | Overlap off | Overlap on | Time saved | Repetitions |
| --------------------------------------- | ----------: | ---------: | ---------: | ----------: |
| uv / check / cold                       |     72.00 s |    77.90 s |      -8.2% |           1 |
| uv / check / no edit                    |     0.486 s |    0.555 s |     -14.3% |           3 |
| uv / check / dependency edit            |     0.815 s |    0.810 s |      +0.6% |           7 |
| uv / check / direct edit                |      2.56 s |     2.57 s |      -0.5% |           5 |
| uv / clippy / cold                      |     74.65 s |    74.06 s |      +0.8% |           1 |
| uv / clippy / no edit                   |     0.563 s |    0.582 s |      -3.4% |           3 |
| uv / clippy / dependency edit           |     0.873 s |    0.880 s |      -0.8% |           7 |
| uv / clippy / direct edit               |      3.37 s |     3.39 s |      -0.5% |           5 |
| uv / test / cold                        |    118.91 s |   121.50 s |      -2.2% |           1 |
| uv / test / no edit                     |      1.22 s |     1.26 s |      -3.4% |           3 |
| uv / test / dependency edit             |      2.89 s |     2.90 s |      -0.4% |           7 |
| uv / test / direct edit                 |      9.86 s |     9.34 s |      +5.2% |           5 |
| uv / build → check / transition         |     17.93 s |    18.96 s |      -5.8% |           1 |
| uv / shared build / reuse               |     0.827 s |    0.950 s |     -14.8% |           1 |
| Codex core / check / cold               |    115.53 s |   115.85 s |      -0.3% |           1 |
| Codex core / check / no edit            |     0.968 s |    0.969 s |      -0.1% |           3 |
| Codex core / check / dependency edit    |      1.38 s |     1.38 s |      -0.2% |           7 |
| Codex core / check / direct edit        |      5.34 s |     5.35 s |      -0.2% |           5 |
| Codex core / clippy / cold              |    148.48 s |   145.98 s |      +1.7% |           1 |
| Codex core / clippy / no edit           |      1.80 s |     1.20 s |     +33.4% |           3 |
| Codex core / clippy / dependency edit   |      1.66 s |     1.69 s |      -1.7% |           7 |
| Codex core / clippy / direct edit       |     17.94 s |    18.32 s |      -2.1% |           5 |
| Codex core / test / cold                |    246.99 s |   246.05 s |      +0.4% |           1 |
| Codex core / test / no edit             |      3.08 s |     2.51 s |     +18.5% |           3 |
| Codex core / test / dependency edit     |      4.17 s |     4.30 s |      -3.2% |           7 |
| Codex core / test / direct edit         |     28.11 s |    26.42 s |      +6.0% |           5 |
| Codex core / build → check / transition |     37.09 s |    36.30 s |      +2.1% |           1 |
| Codex core / shared build / reuse       |      1.80 s |    0.933 s |     +48.2% |           1 |
| Codex core / fmt / no edit              |     0.446 s |    0.364 s |     +18.4% |           3 |
| Codex core / fmt / direct edit          |     0.717 s |    0.594 s |     +17.2% |           5 |

Aggregation: median.

Source: [workflow.json](workflow.json).

## Observed execution

The JSON report separates timed commands from warmups and retains all three configurations. Early test output means Cargo printed a test launch before its first test-build completion message. Sampled concurrency requires a matching test executable and a compiler outside test process trees in the same observation. The original process monitor misses Ohm’s private executable paths; those entries are marked “not covered.” The supplemental parser-edit run records all owned executables. Two-second sampling can still miss short overlap, so zero samples do not establish its absence.

Cargo messages interleaved with partial libtest output are recovered from the saved logs. The constructed-workload report records each correction and its log hash; timings and test counts are unchanged.

| Workload                    | Phase  | Commands | Early test output | Sampled compiler/test concurrency |
| --------------------------- | ------ | -------: | ----------------: | --------------------------------: |
| ablation-overlap / uv       | timed  |        4 |                 2 |                                 0 |
| ablation-overlap / uv       | warmup |        4 |                 2 |                                 0 |
| constructed-overlap / uv    | timed  |        4 |                 4 |                       not covered |
| constructed-overlap / uv    | warmup |        4 |                 4 |                       not covered |
| developer-workflows / codex | timed  |       44 |                 0 |                                 0 |
| developer-workflows / codex | warmup |       56 |                 0 |                                 0 |
| developer-workflows / ruff  | timed  |       44 |                 0 |                                 0 |
| developer-workflows / ruff  | warmup |       56 |                 0 |                                 0 |
| developer-workflows / uv    | timed  |       44 |                16 |                       not covered |
| developer-workflows / uv    | warmup |       56 |                16 |                       not covered |
| historical / ruff           | timed  |       24 |                 0 |                                 0 |
| historical / ruff           | warmup |        4 |                 0 |                                 0 |
| sessions / codex            | timed  |       22 |                 0 |                                 0 |
| sessions / codex            | warmup |        2 |                 0 |                                 0 |
| sessions / ruff             | timed  |       24 |                 0 |                                 0 |
| sessions / ruff             | warmup |        2 |                 0 |                                 0 |
| sessions / uv               | timed  |       28 |                16 |                       not covered |
| sessions / uv               | warmup |       12 |                 8 |                       not covered |
| workflow / codex-core       | timed  |       58 |                 0 |                                 0 |
| workflow / uv               | timed  |       50 |                16 |                       not covered |

## Retained APFS space

Each entry is one completed allocation cohort. These are retained-space measurements.

| Workload      | Overlap off | Overlap on | Space saved |
| ------------- | ----------: | ---------: | ----------: |
| ruff / single |    3.59 GiB |   3.59 GiB |       +0.0% |
| ruff / forks  |   27.00 GiB |  27.00 GiB |       +0.0% |
| uv / single   |    7.92 GiB |   7.91 GiB |       +0.2% |
| uv / forks    |   33.20 GiB |  33.22 GiB |       -0.1% |

Source: [disk-ready-tests.json](disk-ready-tests.json).

## Scope

The constructed workspace workload explicitly selects multiple library-test executables. The parser-edit comparison uses the existing feature-ablation fixture. Neither is presented as an additional recorded developer session.

The worktree startup study retains stock, shared-build, and trusted-clone configurations. Nextest builds with --no-run, which disables early Cargo test execution.

Cache and trust settings follow each suite’s existing method. The individual-command suite sets neither trust override; generic replays enable procedural-macro trust; developer workflows, ty, and disk cohorts enable both trust options. Only the ready-tests option changes within each Ohm pair.

See [the machine-readable comparison](ready-tests.json) and the linked source reports for individual measurements and archived evidence.
