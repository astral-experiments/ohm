# Benchmarks

The timing benchmarks below compare stock Rust 1.98.0 with `ohm-1.98.0-7` across the
[uv](https://github.com/astral-sh/uv) and [Codex](https://github.com/openai/codex) codebases.
The main uv and Codex tables below come from one fresh Linux devbox study.
The earlier September 2, August 31, August 27, and August 24 complete studies and August 22 Linux uv study are retained
in the historical appendices.
The separate [disk-usage study](#disk-usage-ohm-1980-7-on-macosapfs) measures
`ohm-1.98.0-7` against stock Rust in Ruff/ty and uv development sessions on macOS/APFS.

The fresh Linux study finished on September 2, 2026 (UTC), on an AMD EPYC 9V74 devbox with 32 logical
CPUs and eight build jobs. Both toolchains use the same source revision, default development
profiles, and separate Cargo target directories. Dependencies are cached before timing begins.
The study started after six consecutive five-second CPU samples, each with at least 95% idle,
at most 0.5% I/O wait and 0.1% steal time, and no unrelated compiler processes. Samples
contaminated by concurrent builds are discarded. These are fresh paired comparisons against
stock Rust, not a controlled comparison of Ohm revisions 6 and 7. The exact released toolchains were verified against the
[revision 7 manifest](toolchains/1.98.0/7.json).

- **Cold:** One build from an empty target directory.
- **Dependency (indirect) edit:** Median of seven implementation-only edits to a crate the target
  depends on. Its public API is unchanged, so Ohm can avoid rebuilding downstream crates.
- **Direct edit:** Median of five implementation-only edits to the target crate itself, which must
  be recompiled.
- **No-op:** Median of three runs without source changes.

Each test workflow builds and runs one existing test. The current uv workflow runs a black-box
integration test against the compiled `uv` executable; Codex runs a library test. The pinned Codex
revision uses Rust 1.95.0; these benchmarks use Rust 1.98.0 for both projects to match Ohm's Rust base.

The fresh Linux study completed all 216 planned samples: 192 successful core-workflow samples
and all 24 targeted build-to-check, formatting, and cross-worktree samples. All 216 passed
validation. None were discarded for interference. The [per-sample results](scripts/benchmark_results/release-1.98.0-7.json)
retain all timings, commands, source pins, and toolchain hashes.
The 216 samples include 100 uv samples and 116 Codex samples. Earlier studies are separate
historical evidence and are not pooled with these measurements. The benchmark runner and fixtures
are unchanged from [the release coordinator](https://github.com/astral-sh/ohm/commit/d172b411f28dc2dd0ddc0c55cd394485b56f570e).

## uv

These benchmarks target the `uv` crate. Dependency edits change `uv-normalize`; direct edits change
`uv` itself. The `test` rows execute the `help::help` integration test against the compiled uv CLI.

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |     66.92 s |  60.59 s |   1.10× |
| Dependency edit, `check`  |     10.38 s |   0.59 s |  17.57× |
| Direct edit, `check`      |      2.24 s |   2.10 s |   1.07× |
| No-op `cargo check`       |      0.55 s |   0.42 s |   1.31× |
| Cold `cargo clippy`       |     69.78 s |  62.45 s |   1.12× |
| Dependency edit, `clippy` |     14.56 s |   0.67 s |  21.59× |
| Direct edit, `clippy`     |      3.52 s |   3.13 s |   1.13× |
| No-op `cargo clippy`      |      0.59 s |   0.46 s |   1.28× |
| Cold `cargo test`         |    133.02 s | 120.55 s |   1.10× |
| Dependency edit, `test`   |     20.76 s |   4.27 s |   4.86× |
| Direct edit, `test`       |     18.24 s |  10.96 s |   1.66× |
| No-op `cargo test`        |      1.31 s |   1.14 s |   1.15× |

The measured commands are:

```console
cargo +1.98.0 check -p uv --lib --locked --offline
cargo +1.98.0 clippy -p uv --lib --locked --offline
cargo +1.98.0 test -p uv --test it --locked --offline help::help -- --exact
```

Replace `+1.98.0` with `+ohm-1.98.0-7` to run the Ohm variants.

## Codex

These benchmarks target the `codex-core` crate. Dependency edits change `codex-utils-string`; direct
edits change `codex-core` itself.

| Workflow                  | Rust 1.98.0 |      Ohm | Speedup |
| ------------------------- | ----------: | -------: | ------: |
| Cold `cargo check`        |    112.75 s |  91.85 s |   1.23× |
| Dependency edit, `check`  |     17.44 s |   1.04 s |  16.72× |
| Direct edit, `check`      |      4.42 s |   3.88 s |   1.14× |
| No-op `cargo check`       |      1.14 s |   0.86 s |   1.32× |
| Cold `just clippy`        |    171.67 s | 117.96 s |   1.46× |
| Dependency edit, `clippy` |     38.74 s |   1.26 s |  30.63× |
| Direct edit, `clippy`     |     18.89 s |  14.81 s |   1.28× |
| No-op `just clippy`       |      1.28 s |   1.01 s |   1.27× |
| Cold `just test`          |    227.70 s | 189.60 s |   1.20× |
| Dependency edit, `test`   |     45.05 s |   7.17 s |   6.28× |
| Direct edit, `test`       |     25.40 s |  22.61 s |   1.12× |
| No-op `just test`         |      2.46 s |   1.90 s |   1.29× |

The measured commands follow Codex's existing development workflows:

```console
cargo +1.98.0 check -p codex-core --lib --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just clippy -p codex-core --locked --offline
RUSTUP_TOOLCHAIN=1.98.0 just test -p codex-core --lib --locked --offline \
  --no-tests fail preparation_canonicalizes_data_urls_and_rejects_remote_urls
```

Replace `+1.98.0` with `+ohm-1.98.0-7`, or set `RUSTUP_TOOLCHAIN=ohm-1.98.0-7`,
to run the Ohm variants.

## Additional feature workflows

The benchmark runner includes three additional workflows that exercise optimizations not covered by
the existing check, Clippy, and test matrix:

- **Build-to-check reuse:** Build `uv` or `codex-core` without timing, then measure the first
  `cargo check` against the same target directory. This measures whether already-built registry
  dependencies can be reused across commands.
- **Incremental formatting:** Run Codex's actual
  `cargo fmt -- --config imports_granularity=Item --check` command. After an untimed warmup, measure
  three unchanged runs and five reversible, correctly formatted source edits. Ohm must publish a
  real incremental-formatting snapshot before its results are accepted.
- **Shared-worktree builds:** Build a real workspace dependency (`uv-normalize` or
  `codex-utils-string`) in one checkout, then measure a build with a real edit to that dependency in
  a second checkout at the same revision. Stock Rust uses separate build directories for each
  checkout; Ohm shares one build directory while keeping workspace outputs private. This gives both
  toolchains equivalent workspace isolation while allowing Ohm to reuse immutable registry
  artifacts. Both receive separate target directories and the same trusted system-native-tool
  `PATH`. Ohm must publish its shared-cache marker and immutable registry artifacts before its
  results are accepted.

All 24 feature samples were collected with the same released toolchains, pinned repositories, and
eight build jobs as the 192 completed core samples.

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-7 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     63.94 s |      17.55 s |   3.64× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      6.90 s |       0.49 s |  13.98× |       1 |
| Codex   | Build, then check        | `codex-core`         |    104.08 s |      44.93 s |   2.32× |       1 |
| Codex   | No-op formatting         | Workspace            |     11.09 s |       0.32 s |  34.69× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     11.08 s |       0.52 s |  21.20× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      2.81 s |       0.63 s |   4.46× |       1 |

Together these workflows add 24 matched samples to the completed 192-sample core matrix, for a
full-study total of 216 successful samples. Cold builds, build-to-check transitions, and
shared-worktree builds have only one sample per compiler; their ratios are preliminary.

## Reproducing the benchmarks

The benchmark runner requires [uv](https://docs.astral.sh/uv/), Git, and the upstream Rust and Ohm
toolchains. The Codex workflows also require [`just`](https://github.com/casey/just) and
`cargo-nextest`; this study used versions 1.58.0 and 0.9.140, respectively.
Run it from the Ohm repository:

```console
uv run scripts/benchmark.py --dry-run
uv run scripts/benchmark.py \
  --upstream 1.98.0 --ohm ohm-1.98.0-7 --jobs 8 \
  --cold-runs 1 --noop-runs 3 --dependency-runs 7 --direct-runs 5 \
  --require-idle --discard-targets --output-dir /path/to/new-empty-results
```

The runner clones the public repositories at exact benchmark-compatible source revisions:

- [uv `c22e6b71933443e9cd299d4b6ac8de035ed4825b`](https://github.com/astral-sh/uv/commit/c22e6b71933443e9cd299d4b6ac8de035ed4825b)
- [Codex `5157493c23713ac12034cf250ffb0a8ce0670277`](https://github.com/openai/codex/commit/5157493c23713ac12034cf250ffb0a8ce0670277)

Cloning requires network access, but the benchmark commands run offline, so Cargo dependencies must
already be cached. `--dry-run` prints the benchmark plan without cloning or running a build.

By default, the runner compares Rust 1.98.0 against `+ohm` across `uv` and `codex-core`, using eight
build jobs. Each original workflow includes one cold build, three no-op runs, seven dependency edits,
and five direct edits; the three additional feature workflows run afterward. Use `--project` to run a
smaller matrix:

```console
uv run scripts/benchmark.py \
  --project codex-core
```

Use `--uv-path` and `--codex-path` to reuse existing local repositories, or `--uv-rev` and
`--codex-rev` to override the pinned commits. Use `--upstream` and `--ohm` to select different
toolchains; `--jobs`, `--cold-runs`, `--noop-runs`, `--dependency-runs`, and `--direct-runs` to
control the sample counts; and `--output-dir` to choose a new or empty directory for the JSON results
and Markdown summary.

The runner creates temporary Git worktrees, isolates Cargo target directories by workflow and
toolchain, and applies reversible edits without modifying the original checkouts. Pass
`--require-idle` to wait for other Rust builds to finish and reject overlapping samples;
`--idle-timeout` controls the maximum wait, `--quiet-seconds` sets the required quiet window, and
`--contention-retries` controls how often an interrupted workflow restarts from a cold build. Pass
`--discard-targets` to remove each completed workflow's isolated build artifacts while preserving
its results and logs.

## Disk usage: Ohm 1.98.0-7 on macOS/APFS

This study measures actual allocated disk space throughout recorded development sessions and
across ten real worktrees. It compares the published
[Ohm 1.98.0-7 release](https://github.com/astral-sh/ohm/releases/tag/ohm-1.98.0-7) with stock
Rust 1.98.0. It ran on September 2, 2026, on an Apple Silicon Mac (Mac17,6, 18 logical CPUs,
128 GiB RAM, macOS 26.6.2), with eight build jobs per project. Both toolchains target
`aarch64-apple-darwin` and use LLVM 22.1.8. These results are independent of the revision 7
Linux timing study above.

The [machine-readable results](scripts/benchmark_results/disk-1.98.0-7.json) retain exact bytes,
source and toolchain pins, workload details, measurement timing, and audit provenance.
The [README table](README.md) summarizes the completed sessions and two- and
ten-worktree totals.

### Session progression

Every project/toolchain/scenario combination starts on a separate empty APFS volume. The totals
include source checkouts, all target directories, Ohm's shared artifacts, and session temporary
files and runtime caches. Compilers, Cargo source downloads, Python, Cargo extensions, and common
Git objects and worktree administrative files are already available outside the measured volumes.
Thus “from empty” means an empty project workspace and build state, rather than a new machine
without development tools. No compiled project artifacts are imported and no manual cleanup runs
during a session.

Ruff/ty replays three edits from [Ruff PR #27736](https://github.com/astral-sh/ruff/pull/27736):
simplifying recursive attribute inference, indexing implicit attribute dependencies, and
introducing component fixed points. This exercises **ty semantic development inside Ruff**.
The full session has 13 Cargo commands: focused cycle/attribute mdtests, affected-package tests,
all semantic mdtests, strict Clippy, and formatting. Both toolchains use the recorded developer
profile: `opt-level=1`, `lto=off`, and `debug=line-tables-only`. Snapshot updates are disabled;
the existing `clippy::format_push_string` allowance is identical in both runs.

uv replays implementation and simplification of a dedicated PyPI Simple API JSON parser. Its
20-command session includes parser and PyPI types tests, registry-client tests, strict Clippy,
formatting, and an installation integration test against a local mock index. Both toolchains use
the repository's normal development profile, including full debug information. Python 3.12 is
fixed and Python downloads are disabled. Source edits, command arguments, test selectors,
features, and requested profiles match within each pair.

All sizes below are GiB (2^30 bytes). The edit rows include that edit's complete validation;
the final idle row is a separate observation after the session finishes.

| Stage                   | Ruff stock | Ruff Ohm | Less disk | uv stock | uv Ohm | Less disk |
| ----------------------- | ---------: | -------: | --------: | -------: | -----: | --------: |
| Source checkout         |       0.11 |     0.11 |      0.0% |     0.04 |   0.04 |      0.0% |
| Cold baseline completed |       2.80 |     2.68 |      4.2% |     7.94 |   6.70 |     15.6% |
| Edit 1 validated        |       4.78 |     3.27 |     31.5% |     8.93 |   7.60 |     14.9% |
| Edit 2 validated        |       5.54 |     3.31 |     40.3% |     9.48 |   7.59 |     19.9% |
| Edit 3 validated        |       5.99 |     3.41 |     43.1% |    13.04 |  10.83 |     17.0% |
| Final idle endpoint     |       5.97 |     3.36 |     43.7% |    13.01 |  10.80 |     17.0% |

Ruff/ty's retained footprint separates further through the edit/test/Clippy cycle. uv's largest
increase follows the installation integration test, which builds a much larger part of the
workspace. These measurements describe the complete workflows; they do not isolate individual
compiler features.

### Ten actual worktrees

Each toolchain independently builds a cold donor, applies edit 1, and completes its validation.
That donor then stays paused. Nine sibling worktrees are created sequentially from its first-edit
revision; each performs edits 2 and 3 and their validation commands. All earlier worktrees and
outputs remain present. A two-tree result is therefore one paused donor plus one completed
continuation; a ten-tree result is one donor plus nine completed continuations. The nine siblings
replay the same continuation, rather than sampling nine different developer histories.

Ohm uses its automatic experimental defaults, one initially empty shared build directory per
project/scenario, and a separate private target directory for every worktree. Both
`CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all` and `CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST=all` are enabled
as development trust opt-ins. Stock Rust uses independent worktree targets. Ruff and uv have
separate shared stores, so these totals do not include cross-project sharing.

**Workspace snapshot seeding did not occur.** These graphs contain workspace-local procedural
macros (`ruff_macros` and `uv_macros`), which the
[released admission policy](https://github.com/astral-sh/ohm-cargo/blob/bbf4a22e66d6d134b07b5c39bfde2c65c0f8e95f/src/doc/src/reference/unstable.md#L2037)
excludes from workspace snapshot seeding. Every Ohm sibling creation reported no compatible
snapshot. Immutable registry artifacts were nevertheless shared: every sibling's continuation
had zero registry compiler invocations while referencing donor-produced registry artifacts.
The final inventories confirmed ten separate private workspace namespaces without shared
regular-file inodes between them. The savings should not be attributed to workspace snapshots.

These totals are actual after-operation measurements, including the newly completed sibling's
source and build outputs. The one-tree donor is a different endpoint from the full single-session
row above.

| Active worktrees | Ruff stock | Ruff Ohm | Less disk | uv stock | uv Ohm | Less disk |
| ---------------- | ---------: | -------: | --------: | -------: | -----: | --------: |
| 1 (donor)        |       4.76 |     3.23 |     32.1% |     8.93 |   7.60 |     14.9% |
| 2                |      10.28 |     6.22 |     39.4% |    17.43 |  12.54 |     28.0% |
| 3                |      15.77 |     9.18 |     41.8% |    25.93 |  17.46 |     32.7% |
| 4                |      21.24 |    12.17 |     42.7% |    34.42 |  22.38 |     35.0% |
| 5                |      26.74 |    15.12 |     43.5% |    42.92 |  27.30 |     36.4% |
| 6                |      32.20 |    18.07 |     43.9% |    51.42 |  32.22 |     37.3% |
| 7                |      37.69 |    21.06 |     44.1% |    59.91 |  37.15 |     38.0% |
| 8                |      43.18 |    23.98 |     44.5% |    68.41 |  42.07 |     38.5% |
| 9                |      48.67 |    26.94 |     44.6% |    76.91 |  46.99 |     38.9% |
| 10               |      54.16 |    29.91 |     44.8% |    85.41 |  51.92 |     39.2% |

The marginal costs below subtract the independently measured donor. Creation-only captures the
new checkout before its first build. The nine-sibling mean is the actual increase divided by nine;
the ten-tree total was measured directly, not extrapolated from this mean.

| Project | Added disk above donor           | Stock GiB | Ohm GiB |
| ------- | -------------------------------- | --------: | ------: |
| Ruff/ty | Create first sibling             |     0.114 |   0.115 |
| Ruff/ty | Create and develop first sibling |     5.516 |   2.993 |
| Ruff/ty | Mean per sibling across all nine |     5.488 |   2.964 |
| uv      | Create first sibling             |     0.037 |   0.035 |
| uv      | Create and develop first sibling |     8.502 |   4.944 |
| uv      | Mean per sibling across all nine |     8.498 |   4.924 |

### Physical accounting and validation

The primary measurement is APFS's volume allocation counter, `ATTR_VOL_SPACEUSED`, minus the
initial empty-volume baseline. A separate container-allocation delta cross-checks it. This counts
shared filesystem blocks once; apparent file sizes, `du`, and summed inode allocations do not
reliably account for APFS clones. A small calibration confirmed that adding a 16 MiB clone and
hardlink consumed no additional physical blocks, while changing 4 KiB in the clone allocated
16 KiB. See [Apple's allocation-counter documentation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/getattrlist.2).

Each checkpoint flushes the volume and waits for stable allocation samples. The README's full
single-session and ten-tree results use separate final captures after at least 30 seconds idle,
with five stable samples. Intermediate points, including two trees and the scaling table above,
use the historical after-operation checkpoints. APFS can release preallocated tails later: the
single-session idle totals fell by 10–47 MiB. Three ten-tree totals were unchanged; Ruff Ohm grew
by 116 KiB. The README uses these idle endpoints for completed cohorts. Its disk savings and
reductions are calculated from unrounded bytes and displayed to two decimal places. Seven idle
container deltas match their volume deltas exactly; Ruff Ohm's ten-tree container delta is one
4 KiB block larger.

One-second allocator sampling also recorded transient lower bounds:

| Project | Cohort              | Stock sampled peak GiB | Ohm sampled peak GiB |
| ------- | ------------------- | ---------------------: | -------------------: |
| Ruff/ty | Full single session |                   5.99 |                 3.86 |
| Ruff/ty | Ten worktrees       |                  54.24 |                30.32 |
| uv      | Full single session |                  13.04 |                10.88 |
| uv      | Ten worktrees       |                  85.43 |                52.03 |

These are sampled peaks, not exact maximum free-space requirements. The study ran two project
queues concurrently and makes no wall-time or speedup claim.

All eight cohorts completed: **404 successful Cargo commands, 53,664 repeated test executions,
and 592 accepted operation checkpoints**, plus eight final idle captures. The independent audit
passed source/profile/command equivalence, nonempty test selections, matching pass/fail/skip
counts, output containment, actual worktree counts, allocation arithmetic, and shared-versus-private
artifact checks. Repeated tests are execution counts, not counts of distinct cases. Four
independently cold-started single-session/donor prefix pairs agreed within 1.3% at every matched
command checkpoint. These correlated prefix observations are not full-session repeats or
statistical confidence intervals.

One stock Ruff nextest command passed all 482 tests with zero skips but reported two handle-leak
diagnostics; its Ohm counterpart reported none. The recorded output does not identify the tests,
so their historical cause is unknown. A later scoped inspection found no matching surviving
process or open handle and no retained runtime files. The stock final disk measurement, about
162 seconds later, matched its idle measurement. The audit preserves this reviewed diagnostic
difference while requiring matching test outcomes.

Preparation and measurement corrections are recorded separately from command outcomes. An
initial offline registry-configuration mismatch caused the first two lanes to be excluded and
restarted on fresh empty volumes. The observer was versioned to inventory files before flushing
and sampling, because inventory access times and delayed APFS trimming could otherwise perturb
its stability check. A donor-verification correction accounted for legitimate Git checkout CRLF
filters; a rejected resume restored the recorded Python interpreter and `PATH` before proceeding.
These corrections changed no measured source edits or test expectations, and successful commands
were not rerun to repair measurements.

### Disk-study inputs and limits

The exact replay fixtures and their source revisions are:

| Project | Base revision                                                                                                                   | Replay fixture                                                     |
| ------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Ruff/ty | [`21c9b077ab3b10dd9007710ffa471cd12f7eceab`](https://github.com/astral-sh/ruff/commit/21c9b077ab3b10dd9007710ffa471cd12f7eceab) | [ruff-rust-1.98.json](scripts/session_replays/ruff-rust-1.98.json) |
| uv      | [`a50af60fb4162d7f94812d64c481c30a0200b6d8`](https://github.com/astral-sh/uv/commit/a50af60fb4162d7f94812d64c481c30a0200b6d8)   | [uv.json](scripts/session_replays/uv.json)                         |

The installed release was verified against the [revision 7 manifest](toolchains/1.98.0/7.json).
The compiler and Cargo source pins are:

| Toolchain    | rustc commit                               | Cargo commit                               |
| ------------ | ------------------------------------------ | ------------------------------------------ |
| Rust 1.98.0  | `88d9e12ae178fab0fb5cc050a94da85685d449ea` | `797e8a9bca276c1c9f9f738d2a20f484fa4eea9d` |
| Ohm 1.98.0-7 | `26568fdc7faa53e40722c29fddf0c840b7eb09e4` | `bbf4a22e66d6d134b07b5c39bfde2c65c0f8e95f` |

The compact results preserve fixture and tool hashes alongside the measured data. They document
this disk study; the timing-runner command above does not reproduce its dedicated-volume meter
and worktree schedule.

The conclusions apply to this released configuration and these two fixed macOS/APFS workflows.
They do not measure an isolated contribution from either disk-fix PR, a revision 6-to-7 change,
Linux/Windows filesystems, or long-term cache growth across dependency upgrades and unrelated
projects. Excluded prerequisites were inventoried separately, but installed toolchain components
and pre-existing clone relationships were not controlled for a cold-install comparison. Their
descriptive inode allocations must not be added to the measured physical totals.

## Earlier Ohm 1.98.0-6 direct study — September 2, 2026

These measurements are preserved from the previous publication. This study used an AMD EPYC 9V74
Linux devbox with 32 logical CPUs and eight build jobs, the same pinned uv and Codex source
revisions, default development profiles, and separate target directories. All 216 samples passed,
with none discarded for interference. Dependency edits report seven-run medians, direct edits
five-run medians, and no-op runs three-run medians. Cold builds, build-to-check transitions, and
shared-worktree builds have one sample per compiler. These results are not pooled with the new study.

### uv

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-6 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |     71.66 s |      61.44 s |   1.17× |
| Dependency edit, `check`  |     11.82 s |       0.61 s |  19.30× |
| Direct edit, `check`      |      2.52 s |       2.25 s |   1.12× |
| No-op `cargo check`       |      0.57 s |       0.44 s |   1.30× |
| Cold `cargo clippy`       |     73.35 s |      63.58 s |   1.15× |
| Dependency edit, `clippy` |     15.85 s |       0.69 s |  23.00× |
| Direct edit, `clippy`     |      3.87 s |       3.34 s |   1.16× |
| No-op `cargo clippy`      |      0.59 s |       0.48 s |   1.24× |
| Cold `cargo test`         |    139.11 s |     126.36 s |   1.10× |
| Dependency edit, `test`   |     22.48 s |       4.47 s |   5.03× |
| Direct edit, `test`       |     19.22 s |      11.57 s |   1.66× |
| No-op `cargo test`        |      1.33 s |       1.14 s |   1.16× |

### Codex

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-6 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |    119.84 s |      96.10 s |   1.25× |
| Dependency edit, `check`  |     18.19 s |       1.06 s |  17.19× |
| Direct edit, `check`      |      4.61 s |       4.00 s |   1.15× |
| No-op `cargo check`       |      1.21 s |       0.89 s |   1.35× |
| Cold `just clippy`        |    185.69 s |     121.45 s |   1.53× |
| Dependency edit, `clippy` |     39.85 s |       1.28 s |  31.04× |
| Direct edit, `clippy`     |     19.53 s |      15.19 s |   1.29× |
| No-op `just clippy`       |      1.34 s |       1.00 s |   1.33× |
| Cold `just test`          |    230.67 s |     195.59 s |   1.18× |
| Dependency edit, `test`   |     46.70 s |       7.26 s |   6.43× |
| Direct edit, `test`       |     26.01 s |      23.19 s |   1.12× |
| No-op `just test`         |      2.49 s |       1.95 s |   1.28× |

### Additional feature workflows

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-6 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     63.05 s |      17.95 s |   3.51× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      6.91 s |       0.49 s |  14.03× |       1 |
| Codex   | Build, then check        | `codex-core`         |    111.27 s |      46.69 s |   2.38× |       1 |
| Codex   | No-op formatting         | Workspace            |     11.05 s |       0.32 s |  34.45× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     11.09 s |       0.52 s |  21.18× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      2.79 s |       0.60 s |   4.62× |       1 |

## Earlier Ohm 1.98.0-5 direct study — August 31, 2026

These measurements are preserved from the previous publication. This study used an AMD EPYC 9V74
Linux devbox with 32 logical CPUs and eight build jobs, the same pinned uv and Codex source
revisions, default development profiles, and separate target directories. All 216 samples passed,
with none discarded for interference. Dependency edits report seven-run medians, direct edits
five-run medians, and no-op runs three-run medians. Cold builds, build-to-check transitions, and
shared-worktree builds have one sample per compiler. These results are not pooled with the new study.

### uv

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-5 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |     66.30 s |      61.88 s |   1.07× |
| Dependency edit, `check`  |     10.76 s |       0.57 s |  18.85× |
| Direct edit, `check`      |      2.34 s |       2.12 s |   1.10× |
| No-op `cargo check`       |      0.56 s |       0.40 s |   1.42× |
| Cold `cargo clippy`       |     70.03 s |      63.39 s |   1.10× |
| Dependency edit, `clippy` |     14.69 s |       0.63 s |  23.27× |
| Direct edit, `clippy`     |      3.56 s |       3.11 s |   1.14× |
| No-op `cargo clippy`      |      0.60 s |       0.43 s |   1.38× |
| Cold `cargo test`         |    133.77 s |     124.92 s |   1.07× |
| Dependency edit, `test`   |     20.99 s |       4.12 s |   5.10× |
| Direct edit, `test`       |     18.18 s |      10.84 s |   1.68× |
| No-op `cargo test`        |      1.33 s |       1.18 s |   1.13× |

### Codex

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-5 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |    112.59 s |      95.18 s |   1.18× |
| Dependency edit, `check`  |     17.67 s |       1.00 s |  17.68× |
| Direct edit, `check`      |      4.41 s |       3.88 s |   1.14× |
| No-op `cargo check`       |      1.15 s |       0.81 s |   1.42× |
| Cold `just clippy`        |    169.69 s |     120.73 s |   1.41× |
| Dependency edit, `clippy` |     38.80 s |       1.18 s |  33.00× |
| Direct edit, `clippy`     |     18.83 s |      14.68 s |   1.28× |
| No-op `just clippy`       |      1.29 s |       0.94 s |   1.37× |
| Cold `just test`          |    228.02 s |     192.93 s |   1.18× |
| Dependency edit, `test`   |     46.07 s |       7.07 s |   6.51× |
| Direct edit, `test`       |     26.40 s |      23.44 s |   1.13× |
| No-op `just test`         |      2.48 s |       1.86 s |   1.34× |

### Additional feature workflows

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-5 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     63.73 s |      17.98 s |   3.54× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      7.00 s |       0.49 s |  14.16× |       1 |
| Codex   | Build, then check        | `codex-core`         |    105.38 s |      47.81 s |   2.20× |       1 |
| Codex   | No-op formatting         | Workspace            |     11.11 s |       0.32 s |  34.64× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     11.07 s |       0.52 s |  21.18× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      2.81 s |       0.61 s |   4.61× |       1 |

## Earlier Ohm 1.98.0-3 direct study — August 27, 2026

These measurements are preserved from the previous publication. This study used an AMD EPYC 9V74
Linux devbox with 32 logical CPUs and eight build jobs, the same pinned uv and Codex source
revisions, default development profiles, and separate target directories. All 216 samples passed,
with none discarded for interference. Dependency edits report seven-run medians, direct edits
five-run medians, and no-op runs three-run medians. Cold builds, build-to-check transitions, and
shared-worktree builds have one sample per compiler. These results are not pooled with the new study.

### uv

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-3 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |     66.81 s |      60.73 s |   1.10× |
| Dependency edit, `check`  |     10.25 s |       0.58 s |  17.80× |
| Direct edit, `check`      |      2.18 s |       1.94 s |   1.12× |
| No-op `cargo check`       |      0.57 s |       0.40 s |   1.42× |
| Cold `cargo clippy`       |     69.66 s |      60.56 s |   1.15× |
| Dependency edit, `clippy` |     14.69 s |       0.64 s |  22.91× |
| Direct edit, `clippy`     |      3.39 s |       3.01 s |   1.13× |
| No-op `cargo clippy`      |      0.60 s |       0.44 s |   1.36× |
| Cold `cargo test`         |    128.17 s |     117.48 s |   1.09× |
| Dependency edit, `test`   |     19.53 s |       4.08 s |   4.79× |
| Direct edit, `test`       |     17.09 s |      10.08 s |   1.70× |
| No-op `cargo test`        |      1.32 s |       1.14 s |   1.16× |

### Codex

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-3 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |    112.68 s |      96.13 s |   1.17× |
| Dependency edit, `check`  |     17.81 s |       1.00 s |  17.80× |
| Direct edit, `check`      |      4.47 s |       3.95 s |   1.13× |
| No-op `cargo check`       |      1.15 s |       0.81 s |   1.42× |
| Cold `just clippy`        |    170.81 s |     123.67 s |   1.38× |
| Dependency edit, `clippy` |     39.42 s |       1.18 s |  33.54× |
| Direct edit, `clippy`     |     19.23 s |      15.01 s |   1.28× |
| No-op `just clippy`       |      1.30 s |       0.94 s |   1.38× |
| Cold `just test`          |    224.82 s |     195.37 s |   1.15× |
| Dependency edit, `test`   |     43.76 s |       7.05 s |   6.21× |
| Direct edit, `test`       |     24.73 s |      22.03 s |   1.12× |
| No-op `just test`         |      2.49 s |       1.86 s |   1.34× |

### Additional feature workflows

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-3 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     63.80 s |      18.14 s |   3.52× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      6.89 s |       0.48 s |  14.26× |       1 |
| Codex   | Build, then check        | `codex-core`         |    104.55 s |      47.27 s |   2.21× |       1 |
| Codex   | No-op formatting         | Workspace            |     11.06 s |       0.32 s |  34.75× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     11.08 s |       0.52 s |  21.21× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      2.80 s |       0.61 s |   4.58× |       1 |

## Earlier Ohm 1.98.0-2 direct study — August 24, 2026

These measurements are preserved unchanged. This earlier study used an AMD EPYC-Milan Linux
devbox with 32 logical CPUs and eight build jobs, the same pinned uv and Codex source revisions,
and separate target directories. It completed 216 validated samples without interference:
192 core workflow samples and 24 feature samples. Dependency edits report seven-run medians,
direct edits five-run medians, and no-op runs three-run medians; cold builds and the other
feature workflows have one sample per compiler. These results are not pooled with the new study.

### uv

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |     91.65 s |      89.96 s |   1.02× |
| Dependency edit, `check`  |     15.84 s |       0.77 s |  20.59× |
| Direct edit, `check`      |      3.41 s |       2.97 s |   1.15× |
| No-op `cargo check`       |      0.70 s |       0.46 s |   1.52× |
| Cold `cargo clippy`       |     99.58 s |      91.21 s |   1.09× |
| Dependency edit, `clippy` |     20.62 s |       0.82 s |  25.11× |
| Direct edit, `clippy`     |      4.86 s |       4.30 s |   1.13× |
| No-op `cargo clippy`      |      0.73 s |       0.52 s |   1.39× |
| Cold `cargo test`         |    178.83 s |     176.08 s |   1.02× |
| Dependency edit, `test`   |     33.32 s |       6.07 s |   5.49× |
| Direct edit, `test`       |     24.57 s |      14.87 s |   1.65× |
| No-op `cargo test`        |      1.44 s |       1.20 s |   1.19× |

### Codex

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup |
| ------------------------- | ----------: | -----------: | ------: |
| Cold `cargo check`        |    143.74 s |     136.28 s |   1.05× |
| Dependency edit, `check`  |     25.58 s |       1.14 s |  22.49× |
| Direct edit, `check`      |      6.25 s |       5.65 s |   1.11× |
| No-op `cargo check`       |      1.32 s |       0.97 s |   1.35× |
| Cold `just clippy`        |    222.87 s |     165.63 s |   1.35× |
| Dependency edit, `clippy` |     56.64 s |       1.36 s |  41.80× |
| Direct edit, `clippy`     |     28.11 s |      23.62 s |   1.19× |
| No-op `just clippy`       |      1.45 s |       1.46 s |   1.00× |
| Cold `just test`          |    293.08 s |     264.79 s |   1.11× |
| Dependency edit, `test`   |     67.59 s |       9.44 s |   7.16× |
| Direct edit, `test`       |     37.22 s |      31.46 s |   1.18× |
| No-op `just test`         |      4.34 s |       3.57 s |   1.22× |

### Additional feature workflows

| Project | Workflow                 | Package              | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| ------- | ------------------------ | -------------------- | ----------: | -----------: | ------: | ------: |
| uv      | Build, then check        | `uv`                 |     81.49 s |      26.57 s |   3.07× |       1 |
| uv      | Shared-worktree build    | `uv-normalize`       |      9.36 s |       0.64 s |  14.55× |       1 |
| Codex   | Build, then check        | `codex-core`         |    132.83 s |      65.73 s |   2.02× |       1 |
| Codex   | No-op formatting         | Workspace            |     12.29 s |       0.31 s |  40.12× |       3 |
| Codex   | Formatting after an edit | `codex-core`         |     12.81 s |       0.46 s |  27.73× |       5 |
| Codex   | Shared-worktree build    | `codex-utils-string` |      3.39 s |       0.73 s |   4.68× |       1 |

## Earlier Linux uv study — August 22, 2026

These earlier measurements are preserved unchanged; they are not part of the fresh 216-sample study.

The complete 100-sample Linux comparison used Rust 1.98.0 and `ohm-1.98.0-2` on an AMD EPYC-Milan
machine with 32 logical CPUs and eight build jobs. Both toolchains used the same pinned uv revision,
offline dependencies, isolated target directories, and uncontaminated samples.

| Workflow                  | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| ------------------------- | ----------: | -----------: | ------: | ------: |
| Cold `cargo check`        |     84.99 s |      74.84 s |   1.14× |       1 |
| No-op `cargo check`       |      0.64 s |       0.44 s |   1.47× |       3 |
| Dependency edit, `check`  |     13.74 s |       0.70 s |  19.71× |       7 |
| Direct edit, `check`      |      2.92 s |       2.69 s |   1.09× |       5 |
| Cold `cargo clippy`       |     85.51 s |      76.78 s |   1.11× |       1 |
| No-op `cargo clippy`      |      0.69 s |       0.48 s |   1.43× |       3 |
| Dependency edit, `clippy` |     19.40 s |       0.76 s |  25.39× |       7 |
| Direct edit, `clippy`     |      4.58 s |       4.07 s |   1.12× |       5 |
| Build, then check         |     83.06 s |      25.67 s |   3.24× |       1 |
| Shared-worktree build     |     10.34 s |       0.83 s |  12.48× |       1 |

The uv integration-test workflow selects the existing `help::help` integration test, which executes
the real `uv` CLI. Changing `crates/uv/src/install_source.rs` still recompiles the application and
relinks its executable, while Ohm can reuse the integration-test executable because it does not use
the package library. Changing `uv-normalize` retains the existing dependency-edit workload.

These 32 integration-test samples are included in the complete 100-sample Linux comparison:

| Phase           | Rust 1.98.0 | Ohm 1.98.0-2 | Speedup | Samples |
| --------------- | ----------: | -----------: | ------: | ------: |
| Cold            |    159.07 s |     164.29 s |   0.97× |       1 |
| No-op           |      2.02 s |       1.34 s |   1.51× |       3 |
| Dependency edit |     31.94 s |       5.88 s |   5.43× |       7 |
| Direct edit     |     26.82 s |      18.12 s |   1.48× |       5 |

The single cold integration-test build was 3.3% slower with Ohm; unchanged runs and both edit
workflows were faster. The cold result is retained rather than excluded from the comparison.

The previous Rust 1.97.1 comparison is preserved as historical evidence:

| Phase           | Rust 1.97.1 | Ohm 1.97.1-20 | Speedup | Samples |
| --------------- | ----------: | ------------: | ------: | ------: |
| Cold            |    157.47 s |      164.23 s |   0.96× |       1 |
| No-op           |      1.96 s |        1.89 s |   1.04× |       3 |
| Dependency edit |     31.17 s |        5.31 s |   5.88× |       7 |
| Direct edit     |     23.33 s |       18.06 s |   1.29× |       5 |
