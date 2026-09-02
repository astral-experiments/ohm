# Clippy during build and test compilation

The experimental `-Zohm-clippy-codegen` option reports Clippy diagnostics while
producing build or test artifacts in the same compiler invocation:

```sh
cargo +ohm -Zohm-clippy-codegen test -p my-package
cargo +ohm -Zohm-clippy-codegen nextest run -p my-package
CARGO_OHM_CLIPPY_ARGS='-D warnings' cargo +ohm -Zohm-clippy-codegen build
```

This requires a toolchain containing the matching Cargo, compiler, and Clippy
changes; the implementation is unreleased. The option is
disabled by default, including when Ohm's other experimental defaults are enabled.

The draft implementation uses these matching component revisions:

| Component | Review                                                                     | Revision                                   |
| --------- | -------------------------------------------------------------------------- | ------------------------------------------ |
| Compiler  | [ohm-rust#96](https://github.com/astral-sh/ohm-rust/pull/96)               | `fc8a9b7d921e23525d440459ab66d14ff7ad5531` |
| Cargo     | [ohm-cargo#102](https://github.com/astral-sh/ohm-cargo/pull/102)           | `19a17825cb1d62d5e85771c368fd5d651b940be7` |
| Clippy    | [ohm-rust-clippy#51](https://github.com/astral-sh/ohm-rust-clippy/pull/51) | `33adb72eeb96282e533d5a5c582df9727fa42a7d` |

The compiler's Cargo gitlink matches the Cargo revision above. A future release
manifest must select these components together; the current release selection
is unchanged.

## Compilation and lint coverage

Cargo selects targets, profiles, features, and compiler options normally.
Workspace compilation uses the matching Clippy driver. Registry dependencies
continue to use rustc. Clippy analyzes the program being compiled, including
`cfg(test)` where applicable, without adding `cfg(clippy)`.

The compiler retains a separate MIR view for lint analysis. Code generation
keeps its normal optimization passes, pointer checks, and format-argument
lowering. Consequently, projects with `cfg(clippy)` branches still need a
separate `cargo clippy` command to analyze those branches. A runtime test filter
does not restrict lint coverage to the tests that execute.

Diagnostics can also reflect differences in normal lowering. For example,
format-argument flattening removes temporaries before MIR is built, which can
reduce `large_stack_frames` estimates compared with standalone Clippy. The lint
still runs; its estimate describes the normally lowered program. This mode does
not promise identical diagnostics for programs transformed differently by
standalone Clippy.

`CARGO_OHM_CLIPPY_ARGS` accepts whitespace-separated lint levels: `-A`, `-W`,
`-D`, `-F`, and their long forms. It accepts both `-D warnings` and `-Dwarnings`.
Manifest lint settings and Clippy configuration files also apply. Arguments
after `cargo test --` remain test-harness arguments:

```sh
CARGO_OHM_CLIPPY_ARGS='-D warnings' \
  cargo +ohm -Zohm-clippy-codegen test -p my-package --test integration -- my_test
```

Cargo's `[env]` configuration can supply the lint arguments too:

```toml
[env]
CARGO_OHM_CLIPPY_ARGS = "-D warnings"
```

Process environment values take precedence unless the configuration uses
`force = true`. The same rules apply to direct Cargo commands and nextest.

A denied lint fails compilation and prevents test execution. Test failures keep
the runner's usual exit status. Doctests still use rustdoc; this option does not
add Clippy analysis to doctests. Automatic fixes use the existing fix workflow.

## Artifact reuse and compatibility

Combined artifacts occupy a separate namespace from ordinary build artifacts.
This deliberately avoids treating a plain build as proof that linting passed.
Repeated combined commands reuse their artifacts; source, lint arguments, and
Clippy configuration changes must invalidate the corresponding lint results.

The option propagates through external Cargo subcommands such as nextest. A
nested Cargo command can explicitly disable it with
`-Zohm-clippy-codegen=no`. Cargo configuration also accepts
`unstable.ohm-clippy-codegen = true`.

Cargo checks the driver's capability and compiler version before using it.
Conflicting compiler wrappers and primary compiler overrides are rejected.
Standalone `cargo clippy` retains its existing behavior.

## Development validation

The cross-component smoke check exercises diagnostic replay, source and
configuration invalidation, rejected lints, test failures, normal `cfg` behavior,
and nextest forwarding:

```sh
python3 scripts/test_clippy_codegen.py
```

Use `--cargo /path/to/cargo --rustc /path/to/sysroot/bin/rustc` for a locally
built toolchain. The sysroot must also contain its matching `clippy-driver`,
`cargo-clippy`, and `rustdoc`. `cargo-nextest` must be available on `PATH`.
The script defaults to an `ohm-clippy-codegen-smoke` directory under the system
temporary directory, with a JSON report and raw logs in its `evidence` child.
Use `--artifact-root`, `--evidence-dir`, and `--cargo-home` to choose other paths.
The release smoke job runs this check on each assembled platform toolchain.
Older Cargo builds without the option are skipped with `--if-supported`;
an advertised option with missing or incompatible compiler support fails.

Compiler tests separately compare ordinary and combined codegen and exercise
MIR ownership with const evaluation, closures, coroutines, and parallel queries.
Clippy tests cover MIR-dependent lints and formatting expressions transformed
by normal lowering. Cargo tests cover selection, capability checks, wrapper
conflicts, artifact identities, and propagation to external commands.

Local validation passed 25 cross-component checks, including configured lint
denial, the compiler ownership and
codegen checks, and Clippy's diagnostic/codegen harness. Three existing Clippy
formatting fixtures produced 89 exactly matching diagnostics. The codegen
comparison covers an exported library body; binary inline-assembly source
location metadata can differ because Clippy loads additional source files.

## Measured edit replays

The expanded study replays three production fixes while retaining each final
regression test:

- **ty:** the four-line inference fix from Ruff commit
  `d3f235fae30f786f7ae58cc1b534e59b15b8e948`, with
  `mdtest::narrow/assignment.md` in `ty_python_semantic`'s `mdtest` target.
- **uv:** all three production-file changes from commit
  `bcc7e6afc2398f158179e8917ddd7ba9d1a8b2df`, rejecting a reserved inferred
  project name, with `init::init_python_current_directory` in the `project` target.
- **Codex:** the macOS native MCP spawn selection fix, pinned at
  `3be08eb4ad79e7986c6418354822bc1ced5076d3`, with
  `bare_mcp_command_initializes_without_fork` in `codex-rmcp-client`'s
  `macos_path_spawn` target.

Both validation workflows fail the intended regression before its fix and pass
afterward. Every measured cycle executes exactly the selected passing test.
The separate workflow runs Clippy followed by nextest; combined validation runs
nextest with native Clippy codegen. Codex uses its existing `just test` recipe.
Tests-only reuses the ordinary artifacts from the separate workflow, resetting
them with a tests-only build before each edit.

All workflows use the same compiler, eight build jobs, locked offline
dependencies, and default workspace lint coverage. Ohm's existing defaults,
including incremental Clippy and build/check reuse, remain enabled. Profiles
match within each workload: `test` for ty and Codex, `no-debug` for uv. ty and uv
use `-D warnings`; Codex keeps historical warnings at warning level, retaining
all analyses and its manifest-denied lints.

There are four edit samples and five no-op samples per workflow per project,
**81 accepted cycles** in total. Edit order is
separate/combined/plain/plain/combined/separate, repeated twice. Warmup and
reset builds are excluded. The three no-op cohorts reuse all artifacts without
compilation. Process monitoring detected no competing compiler processes in
any retained timed command.

| Edit replay | Separate Clippy + tests | Combined | Tests only | Reduction vs separate |
| ----------- | ----------------------: | -------: | ---------: | --------------------: |
| ty          |                 15.84 s |  12.11 s |    10.96 s |                 23.5% |
| uv          |                 26.72 s |  18.92 s |    16.28 s |                 29.2% |
| Codex       |                  6.62 s |   5.59 s |     6.79 s |                 15.7% |

Values are medians. ty's separate/combined samples span 15.66–16.08 s and
11.86–12.18 s; uv's span 26.57–26.97 s and 18.66–19.28 s. Codex's separate and
combined samples span 6.16–7.13 s and 5.35–5.93 s. Its tests-only samples are
noisy (5.03–17.25 s), so they do not establish that combined compilation is
faster than ordinary compilation. All samples, including the outlier, are
retained. Codex's combined CPU cost is 1.1% above tests-only.

| Edit replay | Separate CPU | Combined CPU | CPU reduction | Separate peak process RSS | Combined peak process RSS |
| ----------- | -----------: | -----------: | ------------: | ------------------------: | ------------------------: |
| ty          |      29.58 s |      25.04 s |         15.4% |                2713.2 MiB |                2813.0 MiB |
| uv          |      48.84 s |      35.68 s |         26.9% |                1709.6 MiB |                1718.1 MiB |
| Codex       |      11.41 s |      10.03 s |         12.1% |                1419.4 MiB |                1418.6 MiB |

CPU totals sum both separate commands; peak process RSS takes their maximum.
Darwin `wait4` supplies CPU and the largest process high-water mark. Sampled
aggregate RSS is also recorded every 250 ms; it can double-count shared pages
and miss brief peaks, so it is reported separately in the raw summary.

| No-op replay | Separate Clippy + tests | Combined | Tests only |
| ------------ | ----------------------: | -------: | ---------: |
| ty           |                 0.864 s |  0.447 s |    0.438 s |
| uv           |                 3.798 s |  2.953 s |    2.681 s |
| Codex        |                 2.142 s |  1.209 s |    1.177 s |

These are Apple M5 Max measurements with 128 GiB RAM, optimized Cargo, and a
local stage-1 compiler at optimization level 2, 16 codegen units, no LTO, and no
PGO. They cover three incremental edits, not release-toolchain or full clean
workspace performance. Earlier launcher and `cargo test` experiments used
different workflows and are not pooled with these results.

The [recorded samples](../scripts/benchmark_results/clippy-codegen-prototype.json)
include all 81 cycles, source hashes, compiler-build provenance, and medians.
Measurements precede the Cargo `[env]` routing fix; all measured workflows
supplied lint arguments directly through the process environment. The local
measurement harness, command logs, and source snapshots are retained with the
development evidence rather than installed as a user-facing benchmark command.

## Private cache footprint

A separate pass populates fresh private target namespaces at the fixed revision,
retaining the existing shared registry cache. A final unchanged cycle confirms
that every workflow reuses all artifacts. This avoids artifacts from previous
compiler versions, failed setup attempts, and earlier source edits. uv's separate
workflow needs a one-time rebuild during population when Cargo begins reusing
built dependencies for Clippy.

| Workload | Separate Clippy + tests | Combined | Logical size reduction |
| -------- | ----------------------: | -------: | ---------------------: |
| ty       |                1.86 GiB | 1.45 GiB |                  22.0% |
| uv       |                4.34 GiB | 2.84 GiB |                  34.6% |
| Codex    |                2.88 GiB | 2.37 GiB |                  17.8% |

These are logical regular-file bytes, counting hardlinks once per workflow.
The scope includes private target outputs, workspace build artifacts, and
incremental caches; shared registry artifacts are excluded. Stat-allocated
footprints fall by 22.0%, 34.5%, and 17.7%, respectively. Neither measure
deduplicates APFS copy-on-write extents across distinct inodes, so these are
retained-cache comparisons, not physical or reclaimable disk-space estimates.
Mixing ordinary and combined compilation retains both artifact namespaces.

The recorded samples also include the logical and stat-allocated footprint for
each workflow. Footprint-population timings are excluded from the latency study.
