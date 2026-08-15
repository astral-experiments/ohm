# Real development-session replays

`scripts/replay_sessions.py` compares stock Rust and Ohm by replaying recorded
development sessions instead of isolated synthetic edits. Each fixture records
an actual session, exact public Git revisions, real source changes, and the
Cargo commands observed between those changes.

The bundled scenarios cover:

- Ruff/ty: inherited-attribute inference changes, focused mdtests, checks,
  Clippy, and package-wide tests.
- uv: the PyPI Simple API JSON parser, parser and registry-client tests,
  Clippy, and a localhost-only installation test.
- Codex: a publicly exported TUI rendering change, focused nextest workflows,
  strict Clippy, and the full TUI package. No private Codex source is required.

Run all three scenarios against existing repository checkouts:

```sh
ulimit -n 65536
python3 scripts/replay_sessions.py \
  --upstream 1.97.1 \
  --ohm ohm-1.97.1-17 \
  --source-path ruff=/path/to/ruff \
  --source-path uv=/path/to/uv \
  --source-path codex=/path/to/codex \
  --output-dir /tmp/ohm-real-session-benchmarks \
  --jobs 8 \
  --repetitions 2 \
  --require-idle
```

Source checkouts are never edited. The runner creates private Git mirrors and
detached worktrees, applies real commit-to-commit patches, and gives each
toolchain its own stable target directory. Baseline warmups populate each
toolchain's target before timed edits begin, making the comparison resemble an
already-active development session. Use `--no-warmup` to measure cold-start
sessions instead. If a public development branch has since been rebased or
deleted, missing replay commits are fetched by their exact pinned full SHAs.

Pass `--project ruff`, `--project uv`, or `--project codex` to run individual
scenarios. Repetitions counterbalance toolchain order across complete replays:
stock followed by Ohm in the first repetition, Ohm followed by stock in the
second. Detailed per-command logs and `results.json` are written beneath the
output directory. Add `--background` on remote hosts to survive an SSH
disconnect; the detached process maintains `run.log` and `status.json` in the
same output directory. Add `--resume` with the identical benchmark options to
preserve completed samples after an interruption. An incomplete sample always
restarts from a fresh worktree, target, shared build, and logs; its previous
artifacts and any interrupted source edits remain recoverable under
`interrupted/<project>/<toolchain>/<repetition>/<attempt>/`. This keeps both
warmup and timed samples comparable after failures. The idle guard recognizes
compiler children in the benchmark's process group even if short-lived native
compiler parents exit between process snapshots.

Fixtures can be inspected with `--dry-run`. The uv integration test requires
Python 3.12, and the Ruff and Codex scenarios require `cargo-nextest`; Codex also
requires `just`. Revision 17's fine-grained locking can exceed the default
1,024-descriptor limit on Codex's 1,029-crate test graph; raise the soft limit
before starting a complete replay.

## Compiler-work attribution

Cargo can print `Checking package` before early cutoff discovers that rustc does
not need to run. These progress messages are not compiler invocations. The
results therefore name them `cargo_reported_crates`, and leave
`actual_compiler_invocations` unknown by default instead of treating either
`Checking` or `Compiling` output as proof of executed compiler work.

For a separate attribution run, add:

```sh
--compiler-accounting verbose
```

This sets `CARGO_TERM_VERBOSE=true` equally for both toolchains. The runner
parses Cargo's actual `Running` commands, counts `rustc` and `clippy-driver`
executions, records their crate names, and identifies
`cargo_status_without_compiler_invocation`. A status-only crate can indicate
early cutoff; it can also reflect a build-script-only action, so inspect the
per-command log when assigning a cause. Verbose output has its own overhead:
compare verbose samples only against equally verbose samples, and keep the
default nonverbose mode for headline session timings.

## Ohm 1.97.1 revision 17 baseline

The checked-in [revision 17 baseline](release-1.97.1-17-baseline.json) contains
both repetitions and the exact untimed warmups. The two-run session means were:

| Project | Rust 1.97.1 | Ohm 1.97.1-17 | Improvement |
| ------- | ----------: | ------------: | ----------: |
| Ruff    |    391.75 s |      381.09 s |        2.7% |
| uv      |    137.57 s |      122.59 s |       10.9% |
| Codex   |    491.99 s |      459.41 s |        6.6% |
| Total   |  1,021.32 s |      963.09 s |        5.7% |

The combined check and test commands were 1.3% slower with Ohm. Its net session
improvement came from 23.4% faster Clippy commands and 32.8% faster formatting;
these end-to-end numbers do not demonstrate a general compiler speedup.

The first stock uv warmup was contaminated by a resumed, previously warmed
target. It is excluded from the checked-in cold-start data, while its timed
session remains valid. Ruff's fixture intentionally does not prewarm formatting:
its first timed formatter therefore includes cold initialization, matching this
baseline.
Ten Codex snapshots depended on an unrelated host-level Git repository and were
excluded equally from both toolchains; the second repetition also excluded one
independently flaky timing-sensitive test equally from both. The resulting full
suite passed 3,440 and 3,439 distinct tests respectively. Each toolchain incurred
one flaky retry in opposite repetitions. All three sessions were held out from
revision 17's upstream Rust PGO training corpus.

## Feature ablation

The compact uv fixture isolates a real private parser implementation edit. It
rechecks the downstream registry client and reruns focused parser unit tests,
without building the complete uv integration harness:

```sh
python3 scripts/replay_sessions.py \
  --project uv \
  --scenario scripts/session_replays/uv-feature-ablation.json \
  --source-path uv=/path/to/uv \
  --output-dir /tmp/ohm-feature-ablation \
  --feature-matrix \
  --jobs 8 \
  --require-idle
```

The matrix uses the same Ohm compiler for four combinations: both optimizations
enabled, public API hashing disabled, procedural-macro caching disabled, and
both disabled. Separate target and shared-build directories ensure changing
tracked compiler options never reuses incompatible artifacts. Each combination
warms the same unmodified checkout before applying the identical real edit.

The summary reports each complete edit-and-command workflow and the marginal
effect of each optimization averaged across both states of the other. Positive
benefits indicate time saved; negative benefits indicate net overhead. Check
per-command crate counts in `results.json` to distinguish downstream rebuilds
avoided by public API hashing from direct compilation and macro-caching costs.
Warmup timings are reported separately and excluded from the measured workflow.

```sh
python3 scripts/test_replay_sessions.py
```
