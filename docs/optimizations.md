# How Ohm speeds up development

Ohm includes the following changes to Rust, Cargo, Clippy, and rustfmt. Unless otherwise noted, they
are included in [Ohm 1.99.0-1](../toolchains/1.99.0/1.json). Headstart is an opt-in prototype and
has not been released.

In two warm replays of three Ruff/ty, uv, and Codex development sessions on Linux, Ohm took a
combined median of 869 seconds versus 1,328 seconds for Rust 1.99.0, 35% less time. Those results
compare the full toolchains, with a shared build directory and permissive procedural-macro trust
for Ohm. The uv comparison also includes Ohm's different debug-information default. See the
[benchmark guide](../BENCHMARKS.md) for the workloads and raw results.

Ohm includes experimental optimizations that may be unsound. Use the official Rust toolchain for
production builds, releases, CI correctness, and final validation.

## Avoid rebuilding dependents after private changes

Cargo normally recompiles downstream crates when a dependency changes. Ohm computes a hash of the
interface exposed by eligible libraries and stops the rebuild when that interface is unchanged. The
changed library is still compiled, but its dependents can be reused. This also applies to
`cargo check` and Clippy. If the interface changes, Cargo starts downstream compilation once the
new metadata is ready, without waiting for the rest of the dependency's build.

In a [uv replay](../scripts/session_replays/release-1.99.0-1-uv-feature-ablation.json) consisting of
a private parser edit, a downstream check, and a focused test, public API hashing reduced the total
from 7.00 to 4.02 seconds with macro caching enabled. The comparison used two repetitions per setting
on the released Ohm compiler, and includes the edit and runner overhead. See
[Rust #43](https://github.com/astral-sh/ohm-rust/pull/43),
[Cargo #53](https://github.com/astral-sh/ohm-cargo/pull/53),
[#55](https://github.com/astral-sh/ohm-cargo/pull/55), and
[#71](https://github.com/astral-sh/ohm-cargo/pull/71).

## Headstart

The [Headstart](https://github.com/PowderworksCode/headstart)-inspired prototype publishes a library's
metadata before checking all of its function bodies. Cargo can then start checking dependent crates
while those body checks finish. Cargo holds the dependent results and diagnostics until the
upstream crate succeeds, and discards them on failure. Private changes can still avoid rebuilding
dependents.

Headstart applies when checking libraries, including `cargo check --tests` and `--all-targets`. Build
scripts and procedural macros still need executable dependencies. The feature is opt-in via
`-Zheadstart` and requires the prototype Cargo and compiler; it is not included in Ohm 1.99.0-1.

In three paired workspace rebuilds with registry and native dependencies cached, Ruff checks fell
from 22.89 to 18.17 seconds (20.6%) and rust-analyzer checks from 25.28 to 18.72 seconds (26.1%).
A private parser edit that already skipped downstream checks took about 1.29 seconds in both modes.
The measurements used compiler `144c59f` and Cargo sources equivalent to `72e9956`. See
[Rust #156](https://github.com/astral-sh/ohm-rust/pull/156) and
[Cargo #133](https://github.com/astral-sh/ohm-cargo/pull/133).

## Relink executables without recompiling them

When a dependency's implementation changes, an executable still needs to be linked against the new
code, even if its own code does not need recompilation. Ohm saves the previous link inputs and, for
eligible executable and test targets, can run the linker again without regenerating the target's
code. Procedural macros, build scripts, and native libraries can require the normal compilation path.

In the [whole-toolchain benchmarks](../scripts/benchmark_results/release-1.99.0-1.json), the uv
dependency-edit test fell from 26.27 to 3.79 seconds and the Codex test from 57.81 to 5.20 seconds.
These results include public API cutoff and other changes alongside relinking. See
[Cargo #51](https://github.com/astral-sh/ohm-cargo/pull/51) and
[#52](https://github.com/astral-sh/ohm-cargo/pull/52).

## Reuse integration tests that do not use a changed library

An integration test may depend on a package without linking its library; for example, the test may
only launch the package's executable. Ohm uses the compiler's record of which libraries are used to
keep the test executable when a changed library is irrelevant.

In three alternating comparisons on an earlier Ohm version, two Ruff edit-to-test cases fell from
8.26 to 5.14 seconds and from 7.20 to 4.41 seconds. See
[Cargo #72](https://github.com/astral-sh/ohm-cargo/pull/72) and
[#73](https://github.com/astral-sh/ohm-cargo/pull/73).

## Reuse builds during checks

After a build, Ohm can reuse compatible metadata from compiled registry and workspace libraries for
`cargo check` and Clippy. It validates the compiler, artifacts, fingerprints, and cached diagnostics
before reuse. Ohm also preserves an existing check graph across a test build, so switching between
testing and checking need not discard earlier work.

In the whole-toolchain benchmarks, the check after an untimed build fell from 70.46 to 23.90 seconds
for uv and from 125.54 to 63.67 seconds for Codex, with one sample per toolchain. See
[Cargo #75](https://github.com/astral-sh/ohm-cargo/pull/75),
[#91](https://github.com/astral-sh/ohm-cargo/pull/91), and
[#89](https://github.com/astral-sh/ohm-cargo/pull/89).

## Share compiled dependencies across worktrees

With `CARGO_BUILD_BUILD_DIR` set to a shared directory, Ohm can reuse compiled registry dependencies
across projects and worktrees. Cargo checks the package, compiler, configuration, and build inputs,
and coordinates concurrent builds with locks. Workspace artifacts and final outputs remain in each
worktree's target directory. Trust settings can expand reuse of procedural macros and native tools,
with additional soundness risk.

In the whole-toolchain benchmarks, a build of uv's `uv-normalize` in a second worktree fell from
9.54 to 1.64 seconds, and a build of Codex's `codex-utils-string` fell from 3.97 to 0.75 seconds.
Each comparison has one sample per toolchain. The worktrees used fresh target directories, not the
workspace-state seeding described below. See [Cargo #77](https://github.com/astral-sh/ohm-cargo/pull/77)
and [#78](https://github.com/astral-sh/ohm-cargo/pull/78).

## Seed new worktrees from an existing build

`cargo +ohm worktree add` can seed a new worktree with compiled workspace crates and incremental
state from an existing worktree. The files are copy-on-write clones, so each worktree can
change independently. Ohm rechecks inputs and reruns build scripts; if a suitable seed or filesystem
cloning is unavailable, the new worktree builds normally.

In a local macOS experiment, worktree creation and the first build took 23.95 seconds without a seed
and 3.59 seconds with one. With a small edit before the build, it took 25.08 versus 8.33 seconds.
Each case used two samples, a warm registry cache, and permissive trust settings; the comparison
also included a compiler path-relocation fix. See
[Cargo #101](https://github.com/astral-sh/ohm-cargo/pull/101),
[#126](https://github.com/astral-sh/ohm-cargo/pull/126), and
[Rust #91](https://github.com/astral-sh/ohm-rust/pull/91).

## Cache derive macro expansions

Ohm enables Rust's experimental cache for derive macro expansions. The cache is potentially unsound
if a macro depends on inputs that are not tracked. Cargo's separate macro trust settings govern reuse
of compiled macro artifacts and worktree snapshots, with their own soundness tradeoffs.

In the uv feature matrix, with public API hashing enabled, the two-sample median was 4.02 seconds
with macro caching and 4.15 seconds without it. The samples varied substantially, so this is not a
precise estimate of the cache's impact. See [Cargo #54](https://github.com/astral-sh/ohm-cargo/pull/54)
and the [feature matrix](../scripts/session_replays/release-1.99.0-1-uv-feature-ablation.json).

## Reuse compiler work across incremental builds

Ohm reuses compatible decisions about where generated generic code belongs, keeps code-generation
partitions more stable across edits, and reuses part of previously encoded metadata when its inputs
have not changed.

For one Codex TUI edit, test-binary partition reuse reduced mean code-generation time from 8.67 to
7.06 seconds and the complete command from 38.48 to 37.60 seconds across eight edit/revert
transitions. The comparison used matched Rust 1.98 compilers without PGO. See
[Rust #54](https://github.com/astral-sh/ohm-rust/pull/54),
[#57](https://github.com/astral-sh/ohm-rust/pull/57), and
[#65](https://github.com/astral-sh/ohm-rust/pull/65).

## Reuse async code after it moves

Moving async code within a file changes its source locations, even when its behavior is unchanged.
Ohm separates those debug locations from the layout used for code generation, allowing more compiled
code to be reused. Coroutine state declaration locations are omitted by default; the compiler flag
`-Zdebug-info-type-line-numbers=true` restores them.

In an earlier full-debug uv session, the command total fell from 140.81 to 123.25 seconds over three
alternating pairs; one pair was slower. Another full-debug uv session was essentially unchanged.
The compilers did not use release PGO/BOLT, and the result does not establish the benefit under
Ohm's line-table default. See [Rust #132](https://github.com/astral-sh/ohm-rust/pull/132).

## Avoid generating async bodies for metadata

When checking a crate, the compiler needs the layout of its async code but does not need its
executable bodies. Ohm separates those steps, avoiding work and producing smaller metadata for
downstream crates.

In an earlier six-sample, single-CPU comparison, `codex-core` metadata fell from 23.43 to 11.34 MB,
and the selected compile fell from 29.05 to 28.70 seconds. See
[Rust #99](https://github.com/astral-sh/ohm-rust/pull/99).

## Run the compiler frontend in parallel

Ohm enables Rust's experimental parallel frontend, the part of the compiler that parses and analyzes
Rust code, with up to eight threads through Cargo. Explicit thread settings take precedence, and
`-Zohm-defaults=no` disables the default. Direct `rustc` invocations do not receive Cargo's defaults.

Changing only the frontend thread setting on an earlier Ohm release reduced the combined Ruff, uv,
and Codex session time from 1,032 to 720 seconds, about 30%, in two repetitions on a
32-logical-CPU Linux machine. Parallel workers can also use more memory. See
[Cargo #90](https://github.com/astral-sh/ohm-cargo/pull/90) and
[#48](https://github.com/astral-sh/ohm-cargo/pull/48).

## Reduce repeated compiler work

Ohm includes smaller changes to trait checking, incremental query reuse, and development code
generation. For example, streaming certain well-formedness checks reduced selected Ruff checks by
about 4% in four paired comparisons with a non-release compiler. Development code-generation changes
improved selected single-CPU uv-resolver compilations by about 8–9% in an earlier experiment with
prepared dependencies. See [Rust #72](https://github.com/astral-sh/ohm-rust/pull/72) and
[#101](https://github.com/astral-sh/ohm-rust/pull/101).

## Optimize the compiler and its allocator

Ohm builds its release compiler with profile-guided optimization (PGO), using a training workload to
optimize the compiler's machine code. Linux releases also use BOLT. Ohm applies additional
component-specific profiling where supported; its additional benefit has not been measured
independently. See [Ohm #60](https://github.com/astral-sh/ohm/pull/60) and
[Rust #67](https://github.com/astral-sh/ohm-rust/pull/67).

Ohm uses mimalloc for Linux `rustc` and Apple Silicon macOS Cargo. In matched PGO/BOLT experiments
on an earlier Ohm version, the Linux allocator reduced a Ruff check rebuild by 5.3% and two uv
build workflows by 7.8–9.8%, while some compiler workloads used 21–25% more peak process memory.
In a matched PGO comparison on macOS, unchanged Ruff checks fell from 216 to 199 milliseconds and
unchanged uv builds from 296 to 267 milliseconds. See
[Rust #109](https://github.com/astral-sh/ohm-rust/pull/109) and
[Cargo #106](https://github.com/astral-sh/ohm-cargo/pull/106).

## Use line tables by default

Ohm's development and test profiles default to line tables. Backtraces retain file and line numbers,
but the type and variable information used for interactive debugging is omitted. Explicit profile,
configuration, and environment settings take precedence; set `debug = true` in `[profile.dev]` for
full debug information.

The current uv comparison uses stock Rust's full-debug default and Ohm's line tables. Ruff and Codex
explicitly set matching debug levels. The release benchmarks do not isolate the effect of this
default. See [Cargo #127](https://github.com/astral-sh/ohm-cargo/pull/127).

## Reduce build artifact disk usage

Ohm removes superseded incremental snapshots and uses stable names for retained debug objects, so
rebuilds do not accumulate old copies. It also stores sparse compiler metadata more compactly and
avoids duplicating metadata inside eligible registry and Git libraries.

An isolated sparse-metadata study found individual metadata files 21–38% smaller and complete
incremental targets 1.84% smaller for syn and 2.64% for Ruff/ty, with a small instruction cost. In
the [whole-toolchain APFS study](../scripts/benchmark_results/disk-1.99.0-1.json), one Ruff worktree
used 40% less physical allocation and one uv worktree used 35% less; those results include all reuse
and debug-default changes. See
[Cargo #68](https://github.com/astral-sh/ohm-cargo/pull/68),
[Rust #97](https://github.com/astral-sh/ohm-rust/pull/97),
[#98](https://github.com/astral-sh/ohm-rust/pull/98), and
[#123](https://github.com/astral-sh/ohm-rust/pull/123).

## Format only what changed

Ohm's `cargo fmt` skips previously formatted workspace packages when their sources, configuration,
and formatter have not changed since a successful run. When it can verify module ownership and the
module graph, it can format a changed module instead of the whole crate. Set `OHM_INCREMENTAL_FMT=0`
to disable the cache.

With a warm formatting cache, the whole-toolchain Codex benchmark fell from 11.91 to 0.31 seconds
for a no-op format and from 12.44 to 0.50 seconds after an edit. In the
[current Ruff replay](../scripts/session_replays/release-1.99.0-1-baseline.json), the first format
took 7.46 seconds with stock Rust and 8.94 seconds with Ohm. See
[rustfmt #13](https://github.com/astral-sh/ohm-rustfmt/pull/13) and
[#14](https://github.com/astral-sh/ohm-rustfmt/pull/14).

## Reuse Clippy results for unchanged modules

Ohm runs selected Clippy lint passes through the compiler's incremental query system. After an edit,
unchanged modules can reuse their diagnostics instead of running those passes again. Passes with
inputs that cannot be tracked safely retain the normal whole-crate traversal.

An earlier six-pair Ruff experiment reduced average Clippy time from 40.55 to 38.85 seconds, about
4.2%, using matched builds without PGO/BOLT. A small direct-driver benchmark became slower, from
52.99 to 60.92 milliseconds. See [Clippy #48](https://github.com/astral-sh/ohm-rust-clippy/pull/48)
and [#49](https://github.com/astral-sh/ohm-rust-clippy/pull/49).

Ohm also skips expensive lint analysis when it cannot produce a diagnostic. For example,
[Clippy #38](https://github.com/astral-sh/ohm-rust-clippy/pull/38) skips redundant-clone analysis in
functions with no relevant calls. Earlier refinements reduced one incremental Codex Clippy workload
from 5.62 to 5.04 seconds against an already-prefiltered baseline; see
[Clippy #7](https://github.com/astral-sh/ohm-rust-clippy/pull/7).

## Reuse Cargo's dependency resolution

Ohm can reuse a previous workspace dependency resolution when the manifests, lockfile,
configuration, and toolchain are unchanged. Cargo still selects packages and features for the
current command.

In an earlier Codex experiment, graph reuse alone reduced warm metadata commands from 413 to 358
milliseconds and Nextest commands from 961 to 824 milliseconds. See
[Cargo #66](https://github.com/astral-sh/ohm-cargo/pull/66),
[#88](https://github.com/astral-sh/ohm-cargo/pull/88), and the original
[#16](https://github.com/astral-sh/ohm-cargo/pull/16).

## Use Wild for Linux linking

Ohm selects the bundled upstream Wild linker by default for native x86-64 Linux GNU builds. Wild
performs a full link; this is separate from cached relinking. Explicit linker settings take
precedence. The release benchmarks include this choice but do not isolate its effect on complete
sessions. See [Cargo #114](https://github.com/astral-sh/ohm-cargo/pull/114) and
[Ohm #109](https://github.com/astral-sh/ohm/pull/109).
