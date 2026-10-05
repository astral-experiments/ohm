# How Ohm speeds up development

Ohm changes Rust, Cargo, Clippy, and rustfmt to make local development faster and to reduce the
space used by builds. This guide explains the major changes in the released
[Ohm 1.99.0-1](../toolchains/1.99.0/1.json) toolchain, why they help, and what we know about their
impact. It describes feature families rather than every individual patch. The linked component PRs
include implementation details and, in many cases, additional measurements. Some remain open even
though their commits are included in the pinned release.

The measurements need context. In warm replays of three recorded Ruff/ty, uv, and Codex development
sessions, the complete Ohm toolchain's combined median time was 869 seconds versus 1,328 seconds for
stock Rust 1.99.0, or about 35% less time. These are two repetitions per toolchain on one Linux
host, with a separate shared build directory and the permissive procedural-macro trust setting
enabled. They are examples of the combined toolchain, not predictions for every project or
measurements of each change below. The uv
comparison also includes Ohm's different default debug-information level. See
[the benchmarks](../BENCHMARKS.md) for the workloads, raw results, and limitations.

Many of these optimizations are experimental and some may be unsound: cached results can be stale if
an input is missed. Use Ohm for local iteration, and use the official Rust toolchain for production
builds, releases, CI correctness, and final validation.

## Stop rebuilding dependents after private changes

Ordinarily, changing a library can cause its dependents to be compiled again, even when the change
is entirely internal. Ohm can give eligible libraries a hash of the interface that downstream
compilation can observe. Cargo recompiles the changed library, compares the old and new hashes, and
stops the rebuild from spreading when that interface is unchanged. This also applies to `cargo check`
and Clippy. Changes to public metadata, downstream source, or relevant compiler inputs still require
the affected work. When the interface does change, Cargo can start downstream compilation as soon as
the new metadata is ready, without waiting for the rest of the dependency's build. See
[Rust #43](https://github.com/astral-sh/ohm-rust/pull/43),
[Cargo #53](https://github.com/astral-sh/ohm-cargo/pull/53), and
[Cargo #55](https://github.com/astral-sh/ohm-cargo/pull/55) for cutoff, and
[Cargo #71](https://github.com/astral-sh/ohm-cargo/pull/71) for pipelining.

In a small uv replay consisting of a private parser edit, a downstream check, and a focused test,
enabling public API hashing reduced the total from 7.00 to 4.02 seconds with macro caching enabled.
The totals include the edit and runner overhead. Each setting was measured twice on the released
Ohm compiler, and the other Ohm optimizations stayed enabled. The complete-toolchain benchmarks
also show large gains for selected interface-preserving edits: uv `cargo check` went from 12.97 to
1.09 seconds and Codex `cargo check` from 21.60 to 1.63 seconds. Those latter results include all
of Ohm's changes, not just this one. See the
[feature matrix](../scripts/session_replays/release-1.99.0-1-uv-feature-ablation.json) and
[workflow results](../scripts/benchmark_results/release-1.99.0-1.json).

## Relink executables without recompiling them

An unchanged interface does not mean an unchanged program: an executable still needs the new
implementation of a dependency. Ohm tracks changes needed by the linker separately from changes
that require recompilation. For eligible executable and test targets, it saves the inputs to the
previous link and can run the linker again without regenerating the target's own code. Changes
involving procedural macros, build scripts, or native libraries take the ordinary path when they
cannot be safely reused. See [Cargo #51](https://github.com/astral-sh/ohm-cargo/pull/51) and
[#52](https://github.com/astral-sh/ohm-cargo/pull/52).

This complements public API cutoff, especially for edit-and-test workflows. The selected uv and
Codex dependency-edit tests in the complete-toolchain comparison fell from 26.27 to 3.79 seconds
and from 57.81 to 5.20 seconds, respectively. Those numbers combine cutoff, relinking, and other
changes; they do not isolate the cost of relinking. See the
[workflow results](../scripts/benchmark_results/release-1.99.0-1.json).

## Reuse integration tests that do not use a changed library

An integration test can depend on a package without actually linking its library; for example, it
may only launch the package's executable. Ohm uses the compiler's record of which libraries a test
uses to keep a test executable when a changed library is proven irrelevant. Changes to inputs the
test does use still invalidate it. See [Cargo #72](https://github.com/astral-sh/ohm-cargo/pull/72)
and [#73](https://github.com/astral-sh/ohm-cargo/pull/73).

In three alternating comparisons on an earlier Ohm version, two Ruff edit-to-test cases fell from
8.26 to 5.14 seconds and from 7.20 to 4.41 seconds. These are examples of particular unused-library
edits, not a general reduction for every test run.

## Reuse builds during checks

`cargo build` produces information that `cargo check` often needs again. Ohm can reuse compatible
metadata from previously built registry and workspace libraries instead of checking those libraries
again. It validates the compiler, artifacts, fingerprints, and cached diagnostics; unsupported or
changed inputs fall back to normal checking. Ohm also preserves a useful check graph across a test
build, so switching between testing and checking need not discard earlier work. See
[Cargo #75](https://github.com/astral-sh/ohm-cargo/pull/75),
[#91](https://github.com/astral-sh/ohm-cargo/pull/91), and
[#89](https://github.com/astral-sh/ohm-cargo/pull/89).

In the current complete-toolchain benchmarks, the check after an untimed build fell from 70.46 to
23.90 seconds for uv and from 125.54 to 63.67 seconds for Codex. Each comparison has only one
sample per toolchain and includes other Ohm changes. An earlier same-compiler Codex test-build to
check experiment reported 65.83 to 38.72 seconds over two repetitions, with permissive macro trust.
See the [workflow results](../scripts/benchmark_results/release-1.99.0-1.json) and
[Cargo #49](https://github.com/astral-sh/ohm-cargo/pull/49).

## Share compiled registry dependencies between projects and worktrees

When `CARGO_BUILD_BUILD_DIR` points to a shared directory, Ohm can store eligible compiled registry
dependencies there and reuse them in other projects and worktrees. It checks the package, compiler,
configuration, and relevant build inputs, and coordinates concurrent users with locks. Mutable
workspace artifacts and final outputs remain in each worktree's own target directory. Trust options
can expand reuse of procedural macros and native tools, with additional soundness risk. See
[Cargo #77](https://github.com/astral-sh/ohm-cargo/pull/77) and
[#78](https://github.com/astral-sh/ohm-cargo/pull/78).

In the complete-toolchain shared-worktree examples, a build of uv's `uv-normalize` crate fell from
9.54 to 1.64 seconds and a build of Codex's `codex-utils-string` from 3.97 to 0.75 seconds. Each has
one sample per toolchain and includes other Ohm changes. The benchmark uses ordinary Git worktrees
with fresh private target directories, not the workspace-state seeding described below. See the
[workflow results](../scripts/benchmark_results/release-1.99.0-1.json).

## Seed a new worktree from an existing build

Sharing compiled registry dependencies does not by itself reuse a project's own compiled code. With
`cargo +ohm worktree add`, Ohm can also seed a new Git worktree with compatible workspace artifacts
and incremental state from an existing one. The files are copy-on-write clones, so the worktrees can
change independently. Ohm rechecks inputs, reruns build scripts, and builds normally when a suitable
seed or filesystem cloning is unavailable. See
[Cargo #101](https://github.com/astral-sh/ohm-cargo/pull/101),
[#126](https://github.com/astral-sh/ohm-cargo/pull/126), and
[Rust #91](https://github.com/astral-sh/ohm-rust/pull/91).

In a local macOS experiment, creating a worktree and running its first build took 23.95 seconds
without a seed and 3.59 seconds with one; with a small edit before the build, it took 25.08 versus
8.33 seconds. There were two samples per case, a warm shared registry cache, and permissive trust
settings; the comparison also included a compiler path-relocation fix. The
[APFS disk study](../scripts/benchmark_results/disk-1.99.0-1.json) found 35–58% less physical
allocation for the whole Ohm bundle across its uv worktree cases, but does not isolate seeding from
shared dependencies, debug settings, and other changes.

## Cache procedural-macro expansions

Derive macros generate Rust code during compilation. Ohm enables Rust's existing experimental
cache for those expansions, so an unchanged derive can sometimes reuse its previous result. This
cache is potentially unsound when a macro depends on inputs that the cache does not track. Cargo's
separate macro trust settings govern reuse of compiled macro artifacts and worktree snapshots; they
have their own soundness tradeoffs. See
[Cargo #54](https://github.com/astral-sh/ohm-cargo/pull/54) and the
[architecture guide](architecture.md#incremental-compilation).

In the current uv feature matrix, with public API hashing enabled, the two-sample median was 4.02
seconds with macro caching and 4.15 seconds without it. Individual samples varied enough that this
is only a tentative indication for that fixture, not a reliable estimate of a general speedup. See
the [feature matrix](../scripts/session_replays/release-1.99.0-1-uv-feature-ablation.json).

## Reuse more of the compiler's incremental work

Even when a crate itself must be rebuilt, parts of the compiler's previous work can still be useful.
Ohm reuses compatible decisions about where generated generic code belongs, keeps code-generation
partitions more stable across edits, and reuses an encoded metadata prefix when its inputs have not
changed. Changed code is still compiled, and invalid or incompatible cached data takes the normal
path. See [Rust #54](https://github.com/astral-sh/ohm-rust/pull/54),
[#57](https://github.com/astral-sh/ohm-rust/pull/57), and
[#65](https://github.com/astral-sh/ohm-rust/pull/65).

For one Codex TUI edit, the test-binary partition reuse in #65 reduced mean code-generation time
from 8.67 to 7.06 seconds and the complete command from 38.48 to 37.60 seconds across eight
edit/revert transitions. This used matched optimized Rust 1.98 compilers without PGO, not the
installed release. The individual effects of the other reuse changes on current development
sessions have not been established.

## Keep async code reusable when it moves

Moving async code within a file can change source locations even when its generated behavior has
not changed. Ohm separates those debug locations from the layout used for code generation, allowing
more compiled code to be reused. As a tradeoff, coroutine state declaration locations are omitted
by default; a compiler flag can restore them. See
[Rust #132](https://github.com/astral-sh/ohm-rust/pull/132).

In an older, full-debug uv session, the measured command total fell from 140.81 to 123.25 seconds
over three alternating pairs; one pair was slower. Another full-debug uv session was essentially
flat. These used compilers without release PGO/BOLT, and the larger gain should not be assumed for
Ohm's line-table default.

## Avoid generating async bodies just for metadata

When a crate is checked rather than built, the compiler needs information about the layout of async
code but does not need to generate its executable bodies. Ohm separates those steps, avoiding some
work and producing smaller metadata for downstream crates. See
[Rust #99](https://github.com/astral-sh/ohm-rust/pull/99).

In an older six-sample, single-CPU comparison, metadata for `codex-core` fell from 23.43 to
11.34 MB, and the selected compile fell from 29.05 to 28.70 seconds. The size reduction is for one
metadata file, not the whole build directory.

## Run the compiler frontend in parallel

The compiler frontend parses and analyzes Rust code before generating machine code. Ohm enables
Rust's experimental parallel frontend with up to eight threads through Cargo by default. Explicit
thread settings take precedence, and `-Zohm-defaults=no` turns off this default. Direct `rustc`
invocations do not receive Cargo's defaults. See
[Cargo #90](https://github.com/astral-sh/ohm-cargo/pull/90) and the earlier measurement in
[#48](https://github.com/astral-sh/ohm-cargo/pull/48).

Changing only the frontend thread setting on an older Ohm release reduced the combined Ruff, uv,
and Codex session time from 1,032 to 720 seconds, about 30%, in two repetitions on a 32-logical-CPU
Linux machine. The result will depend on the workload and available cores; the study did not measure
macOS or low-core machines, and parallel workers can use more memory.

## Reduce repeated work inside the compiler

Ohm also includes smaller compiler changes that make operations such as trait checking, incremental
query reuse, and development code generation do less work. These generally help only when a workload
spends time in the affected operation. For example, streaming certain well-formedness checks in
[Rust #72](https://github.com/astral-sh/ohm-rust/pull/72) reduced selected Ruff checks by about 4%
in four paired comparisons with a non-release compiler. Changes to development code generation in
[#101](https://github.com/astral-sh/ohm-rust/pull/101) improved selected single-CPU uv-resolver
compilations by about 8–9% in an older, prepared-dependency experiment. Neither is an estimate of the
whole released toolchain's speedup.

## Use optimized compiler builds and allocators

Ohm builds its release compiler using profile-guided optimization, which trains the compiler on
representative work and uses the resulting profile to optimize its own machine code. Linux releases
also use BOLT to optimize the compiled binary. Ohm applies additional component-specific profiling
where supported, although upstream Rust already profiles some tools and Ohm's extra component
profiling has not been independently measured. See [Ohm #60](https://github.com/astral-sh/ohm/pull/60)
and [Rust #67](https://github.com/astral-sh/ohm-rust/pull/67).

On Linux, Ohm also uses mimalloc for `rustc`. Matched PGO/BOLT experiments on an older Ohm version
reported 5.3% less time for a Ruff check rebuild and 7.8–9.8% less for two uv build workflows; some
compiler workloads used 21–25% more peak process memory. The result does not apply to Clippy or
rustdoc, which use a different allocator. See [Rust #109](https://github.com/astral-sh/ohm-rust/pull/109).

Ohm also uses mimalloc for Cargo on Apple Silicon macOS. In a matched PGO comparison, unchanged Ruff
checks fell from 216 to 199 milliseconds and unchanged uv builds from 296 to 267 milliseconds. The same
experiment did not establish a Linux timing win. See
[Cargo #106](https://github.com/astral-sh/ohm-cargo/pull/106).

## Use smaller debug information by default

Ohm's development and test profiles default to line tables: backtraces retain file and line numbers,
but the full type and variable information used for interactive debugging is omitted. Explicit
profile, configuration, and environment settings take precedence. Set `[profile.dev] debug = true`
when full debug information is needed. See [Cargo #127](https://github.com/astral-sh/ohm-cargo/pull/127).

This is a deliberate capability tradeoff as well as a potential speed and space saving. The current
uv comparison uses stock Rust's full-debug default versus Ohm's line tables, so its aggregate
improvement cannot be attributed entirely to caching. The Ruff and Codex fixtures explicitly set
matching debug levels. The current release benchmarks do not isolate this default's effect.

## Prevent build artifacts from growing unnecessarily

Ohm removes superseded incremental snapshots after successful builds and uses stable names for
retained debug objects, so repeated rebuilds do not keep accumulating old copies. It uses a more
compact representation for sparse compiler metadata and avoids duplicating metadata inside eligible
registry and Git dependency libraries when a separate metadata file is available. These changes target
disk usage rather than necessarily making commands faster. See
[Cargo #68](https://github.com/astral-sh/ohm-cargo/pull/68),
[Rust #97](https://github.com/astral-sh/ohm-rust/pull/97),
[#98](https://github.com/astral-sh/ohm-rust/pull/98), and
[#123](https://github.com/astral-sh/ohm-rust/pull/123).

For sparse metadata, an isolated study found individual metadata files 21–38% smaller, but complete
incremental targets only 1.84% smaller for syn and 2.64% for Ruff/ty, with a small instruction
cost. An earlier metadata-deduplication experiment reduced the combined library and metadata files
for 26 uv dependencies from 38.94 to 25.86 MB; that is not a whole-target measurement. Separately,
the current whole-toolchain APFS study found 40% less physical allocation for one Ruff worktree and
35% less for one uv worktree. That larger comparison includes all storage, reuse,
and debug-default changes; it is not the impact of metadata compression alone. See the
[disk results](../scripts/benchmark_results/disk-1.99.0-1.json).

## Format only what changed

Ohm's `cargo fmt` remembers successfully formatted workspace packages and skips them when their
sources, configuration, and formatter remain unchanged. When it can verify the module graph and
ownership, it can also format a changed module instead of the whole crate. Uncertain cases fall back
to ordinary formatting. Set `OHM_INCREMENTAL_FMT=0` to disable the cache. See
[rustfmt #13](https://github.com/astral-sh/ohm-rustfmt/pull/13) and
[#14](https://github.com/astral-sh/ohm-rustfmt/pull/14).

With a warmed formatting cache, the complete-toolchain Codex benchmark fell from 11.91 to 0.31
seconds for a no-op format and from 12.44 to 0.50 seconds after an edit. First-time formatting can
cost more: in the current Ruff replay, the first format took 7.46 seconds with stock Rust and 8.94
seconds with Ohm. See the [workflow results](../scripts/benchmark_results/release-1.99.0-1.json)
and [session results](../scripts/session_replays/release-1.99.0-1-baseline.json).

## Reuse Clippy results for unchanged modules

Ohm runs selected Clippy lint passes through the compiler's incremental query system. After an edit,
eligible unchanged modules can reuse their previous diagnostics instead of running those passes
again. The implementation tracks inputs used by each selected pass, including source text needed
for suggestions; passes that cannot be tracked safely keep the normal whole-crate traversal. See
[Clippy #48](https://github.com/astral-sh/ohm-rust-clippy/pull/48) and
[#49](https://github.com/astral-sh/ohm-rust-clippy/pull/49).

An earlier six-pair Ruff experiment reduced average Clippy time from 40.55 to 38.85 seconds, about
4.2%, using matched builds without PGO/BOLT. A small direct-driver benchmark became slower, from
52.99 to 60.92 milliseconds. The larger complete-toolchain Clippy gains in the README also include
dependency cutoff, compiler parallelism, and other changes.

Other Clippy changes avoid expensive analysis when it cannot produce a diagnostic. For example,
[Clippy #38](https://github.com/astral-sh/ohm-rust-clippy/pull/38) skips redundant-clone analysis in
functions with no relevant calls. Earlier refinements reduced one incremental Codex Clippy workload
from 5.62 to 5.04 seconds against an already-prefiltered baseline. See the historical
[Clippy #7](https://github.com/astral-sh/ohm-rust-clippy/pull/7).

## Reuse Cargo's dependency resolution

Cargo normally resolves the workspace's dependency graph before deciding which packages and
features a particular command needs. Ohm can reuse a previous workspace resolution when its inputs
are unchanged, while still selecting the packages and features for the current command. Changed or
incompatible inputs use the normal resolver. See [Cargo #66](https://github.com/astral-sh/ohm-cargo/pull/66)
and [#88](https://github.com/astral-sh/ohm-cargo/pull/88).

In an earlier Codex experiment, graph reuse alone reduced warm metadata commands from 413 to 358
milliseconds and Nextest commands from 961 to 824 milliseconds. Those are historical measurements,
not a current-release estimate. See [Cargo #16](https://github.com/astral-sh/ohm-cargo/pull/16).

## Use Wild for Linux linking

On native x86-64 Linux GNU builds, Ohm selects the bundled upstream Wild linker by default. Linking
combines compiled code and libraries into an executable or other output; Wild performs a full link,
and is separate from Ohm's cached-relinking optimization. Explicit linker settings still take
precedence. See [Cargo #114](https://github.com/astral-sh/ohm-cargo/pull/114) and
[Ohm #109](https://github.com/astral-sh/ohm/pull/109).

The current release comparisons include this choice, but do not isolate its effect on complete
development sessions. Ohm does not ship its experimental Wild fork or the experimental macOS
linker in this release.
