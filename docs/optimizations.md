# How Ohm speeds up development

Ohm includes the following changes to Rust, Cargo, Clippy, and rustfmt.

## Cargo and builds

### 1. Avoid rebuilding dependents after private changes

**Status:** New optimization.

Cargo normally recompiles downstream crates when a dependency changes. Ohm computes a hash of the
interface exposed by eligible libraries and avoids rebuilding dependents when that interface is
unchanged. (The changed library is still compiled, but its dependents can be reused.) If the
interface changes, Cargo starts downstream compilation once the new metadata is ready, without
waiting for the rest of the dependency's build. Ohm also uses a compact metadata graph to reduce the
work needed to compute the interface hash.

For example, assume that `linter` depends on `parser`. If you fix a bug in a private parser helper
without changing the exposed interface, Ohm recompiles `parser` but can reuse `linter`. An
executable using them still needs to be relinked to pick up the change.

Static libraries also track changes to dependency implementations, because the archive contains
their code. This applies when a crate emits both an `rlib` and a static library.

In a uv benchmark, we made a private change to uv's JSON parser in `uv-pypi-types`, then checked the
dependent `uv-client` crate, which took a median of 4.93 seconds without public API hashing and 2.16
seconds with it.

In a separate experiment, the compact metadata graph reduced the time to check Ruff after an edit by
3.0%.

See:

- [Rust #194](https://github.com/astral-sh/ohm-rust/pull/194)
- [Rust #201](https://github.com/astral-sh/ohm-rust/pull/201)
- [Rust #43](https://github.com/astral-sh/ohm-rust/pull/43)
- [Cargo #53](https://github.com/astral-sh/ohm-cargo/pull/53)
- [Cargo #55](https://github.com/astral-sh/ohm-cargo/pull/55)
- [Cargo #71](https://github.com/astral-sh/ohm-cargo/pull/71)

### 2. Relink executables without recompiling them

**Status:** Rust proposal, implemented in Ohm.

Ohm implements the [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790)
approach for eligible executables and test binaries. When a dependency changes but the executable's
compiled code is still valid, Ohm reuses that code and reruns the linker to include the updated
dependency. Changes involving procedural macros, build scripts, or native libraries may still
require recompilation. Cargo checks the saved object bytes and the complete relink manifest before
reusing them. If either check fails, it recompiles the target.

Ohm 1.99.0-13 reads relink manifests up to 1 MiB into a buffer and decodes the fields Cargo
writes directly. Larger manifests still use the streaming reader. Checking the manifest and
object checksums remains part of every reuse decision. In a uv test build after a library edit,
buffering alone cut Cargo's instruction count by 10.19% and 10.05% on two Linux hosts. These
counts exclude rustc and the linker.

This helps most when an edit to a dependency would otherwise force an expensive executable or test
binary to recompile.

In the `linter` and `parser` example above, the linker combines their compiled code into the
`linter` executable. After the private parser fix, Ohm can link the rebuilt parser with the linter's
existing compiled code. The resulting executable includes the fix even though Ohm did not recompile
the linter's own code.

In a release benchmark, we changed a dependency, then rebuilt and ran a uv test. The median time for
the command fell from 26.27 to 3.79 seconds.

See:

- [Cargo #51](https://github.com/astral-sh/ohm-cargo/pull/51)
- [Cargo #52](https://github.com/astral-sh/ohm-cargo/pull/52)
- [Cargo #197](https://github.com/astral-sh/ohm-cargo/pull/197)
- [Cargo #198](https://github.com/astral-sh/ohm-cargo/pull/198)
- [Cargo #234](https://github.com/astral-sh/ohm-cargo/pull/234)
- [Cargo #236](https://github.com/astral-sh/ohm-cargo/pull/236)

### 3. Reuse builds during checks

**Status:** New optimization.

A build already produces some of the information that `cargo check` and Clippy need. Ohm can reuse
results from compatible builds of libraries, binaries, and tests after checking that the compiler,
build inputs, and saved files are compatible. Ohm also replays cached warnings and keeps earlier
check results when you build tests, so switching between testing and checking can reuse work from
both.

For example, suppose you run `cargo +ohm build`, then `cargo +ohm check` in the same workspace. The
build has already checked and compiled a dependency such as `memchr`. If its inputs still match, Ohm
can use the metadata from that build instead of checking `memchr` again. Similarly, after
`cargo +ohm build --bin parser`, a subsequent `cargo +ohm check --bin parser` can reuse the build
results if the inputs still match. If you check, build, and then check again, Ohm can also reuse
the first check's results.

In the release benchmarks, we built each project and then timed a check. The uv check took 70.46
seconds with stock Rust and 23.90 seconds with Ohm; the Codex check took 125.54 and 63.67 seconds,
respectively.

In a Linux uv experiment, reusing native dependencies reduced the median time for the first check
after `cargo test --no-run` from 36.1 to 22.2 seconds.

See:

- [Cargo #75](https://github.com/astral-sh/ohm-cargo/pull/75)
- [Cargo #91](https://github.com/astral-sh/ohm-cargo/pull/91)
- [Cargo #89](https://github.com/astral-sh/ohm-cargo/pull/89)
- [Cargo #149](https://github.com/astral-sh/ohm-cargo/pull/149)
- [Cargo #150](https://github.com/astral-sh/ohm-cargo/pull/150)
- [Cargo #152](https://github.com/astral-sh/ohm-cargo/pull/152)
- [Cargo #154](https://github.com/astral-sh/ohm-cargo/pull/154)
- [Cargo #169](https://github.com/astral-sh/ohm-cargo/pull/169)
- [Cargo #170](https://github.com/astral-sh/ohm-cargo/pull/170)
- [Cargo #171](https://github.com/astral-sh/ohm-cargo/pull/171)
- [Cargo #178](https://github.com/astral-sh/ohm-cargo/pull/178)

### 4. Reuse checks during builds

**Status:** New optimization, enabled by default for eligible debug builds.

A native build repeats type checking and borrow checking that a preceding `cargo check` may have
already done. Ohm saves the results of a check and reuses them in compatible builds. It also keeps
the build's generated objects for later incremental builds.

For example, after checking a parser change, you can build the parser and reuse some of the work
from that check. Release builds, test targets, procedural macros, build scripts, and unsupported
compiler configurations retain ordinary behavior. The extra checkpoints consume disk space. Use
`-Zohm-shared-stages=no` on both commands to opt out.

In a prototype, a first build after a check fell from 104.44 to 80.66 seconds. A separate uv
warm-cycle comparison was slightly slower with sharing, at 5.80 versus 5.72 seconds.

See:

- [Cargo #145](https://github.com/astral-sh/ohm-cargo/pull/145)
- [Rust #177](https://github.com/astral-sh/ohm-rust/pull/177)
- [Rust #187](https://github.com/astral-sh/ohm-rust/pull/187)

### 5. Share compiled dependencies across worktrees

**Status:** New optimization.

Set `CARGO_BUILD_BUILD_DIR` to the same directory across projects or worktrees to let Ohm share
their compiled registry dependencies. Cargo verifies that the package, compiler, configuration, and
build inputs match before it reuses a dependency, and uses locks to coordinate concurrent builds.

Each worktree keeps its own private intermediates, incremental compiler state, documentation,
scratch files, and final outputs in its target directory. The shared build directory retains
eligible registry artifacts and reusable ThinLTO objects. We also include additional "trust"
settings to allow for reuse of procedural macros and native tools, but that reuse can be unsound.

With Ohm defaults disabled, two workspaces with separate target directories can still share one
external build directory. Cargo gives each workspace its own intermediates, including build-script
outputs. Running `cargo clean` in one workspace preserves the other workspace’s files.

For example, suppose you build your project on `main`, then build a fix in a second worktree. Both
worktrees use the same version of `memchr` with the same features and build settings. If they share
a build directory, Ohm can reuse the compiled `memchr` from the first worktree in the second.

In the release benchmarks, building uv's `uv-normalize` in a second worktree took 9.54 seconds with
stock Rust and 1.64 seconds with Ohm. Building Codex's `codex-utils-string` took 3.97 and 0.75
seconds, respectively.

See:

- [Cargo #77](https://github.com/astral-sh/ohm-cargo/pull/77)
- [Cargo #78](https://github.com/astral-sh/ohm-cargo/pull/78)
- [Cargo #158](https://github.com/astral-sh/ohm-cargo/pull/158)
- [Cargo #211](https://github.com/astral-sh/ohm-cargo/pull/211)
- [Cargo #213](https://github.com/astral-sh/ohm-cargo/pull/213)

### 6. Seed new worktrees from an existing build

**Status:** New optimization.

`cargo +ohm worktree add` can copy compiled workspace crates and incremental compiler state into a
new worktree. It uses copy-on-write to share storage until one copy changes.

Continuing that example, suppose your project also contains a `parser` library and a `linter`
executable. Creating the second worktree with `cargo +ohm worktree add` can bring over their build
state too. When you make a small parser edit, the new worktree can start from the previous build and
reuse compatible artifacts and incremental state.

In a macOS experiment, creating a worktree and completing its first build took 23.95 seconds without
copied build state and 3.59 seconds with it. When we made a small edit before building, the times
were 25.08 and 8.33 seconds.

See:

- [Cargo #101](https://github.com/astral-sh/ohm-cargo/pull/101)
- [Cargo #126](https://github.com/astral-sh/ohm-cargo/pull/126)
- [Rust #91](https://github.com/astral-sh/ohm-rust/pull/91)

### 7. Start checking dependent crates earlier

**Status:** New optimization.

Ohm uses the idea behind [Headstart](https://github.com/PowderworksCode/headstart) to check
dependent crates sooner. The compiler publishes metadata describing a library's interface before it
finishes checking every function body; Cargo can then use that metadata to start checking dependent
crates while the library's remaining checks run.

For example, suppose `parser` exposes a function `parse(&str) -> SyntaxTree`, which `linter` calls.
Once the compiler has published the parser's interface, it can start checking how the linter uses
`parse` while it continues checking the parser's function bodies. It still checks both crates; their
work overlaps.

When rechecking first-party crates while reusing pre-compiled third-party dependencies, Ruff's check
time went from 22.89 to 18.17 seconds (20.6% faster) and rust-analyzer's went from 25.28 to 18.72
seconds (26.1% faster).

See:

- [Rust #156](https://github.com/astral-sh/ohm-rust/pull/156)
- [Cargo #133](https://github.com/astral-sh/ohm-cargo/pull/133)

### 8. Reuse integration tests that do not use a changed library

**Status:** New optimization.

Ruff has an integration test that runs `ruff config lint.select` and checks its output. Cargo builds
two programs for this test: the `ruff` executable and a test executable that launches it. Only the
`ruff` executable includes Ruff's library code.

When you edit Ruff's library, Ohm updates the `ruff` executable and reuses the test executable. The
test still runs and checks the updated program's output. Before reusing a test executable, Ohm uses
the compiler's record from a successful build to verify that it does not link the changed library,
either directly or through another dependency.

The library can still affect what the test observes at runtime, as Ruff's library does here. That
does not require new code in the test executable; the test runs again against the updated program.
Changes to the test, a used dependency, or native link inputs still prevent reuse, as does a missing
or stale compiler record. Ohm cannot discover arbitrary inputs that a build script reads without
declaring them; those inputs have the same tracking limits as in ordinary Cargo builds.

In a Ruff experiment, the time to rebuild and run tests after an edit to the package's library fell
from 8.26 to 5.14 seconds. After an edit to another unused workspace library, it fell from 7.20 to
4.41 seconds.

See:

- [Cargo #72](https://github.com/astral-sh/ohm-cargo/pull/72)
- [Cargo #73](https://github.com/astral-sh/ohm-cargo/pull/73)

### 9. Start compiling integration tests earlier

**Status:** New optimization, enabled by default for eligible native tests.

An integration test that launches a package's executable may not use the package's library itself.
Ohm can compile such a test while the library compiles, including on the first native build. It
accepts the early result only when the compiler confirms that the test does not use the library and
the library builds successfully. Otherwise, Cargo retries after the library finishes successfully.

After a test has built without using the library, Ohm can also compile it early on later edits. The
optimization requires Headstart and at least two build jobs; `-Zohm-early-tests=no` disables it.
Tests still wait until all requested libraries and executables are built. The option below can start
tests sooner.

See:

- [Cargo #146](https://github.com/astral-sh/ohm-cargo/pull/146)
- [Cargo #147](https://github.com/astral-sh/ohm-cargo/pull/147)

### 10. Skip unused dev-dependency rebuilds in targeted tests

**Status:** New optimization, enabled by default for eligible native library-test rebuilds.

A library's test target can declare a workspace dev dependency without using it. After an edit,
ordinary Cargo may rebuild that dependency and the normal library it depends on before compiling
the tests. Ohm can skip those rebuilds when the previous test executable recorded the dependency
as unused. If the compiler can't confirm that the dependency is still unused, Cargo rebuilds the
test with all its dependencies.

For example, `cargo +ohm test -p parser --lib` can rebuild the parser's unit tests without
rebuilding an unused test helper. Cargo still builds dependencies used elsewhere or with build
scripts, and falls back to the full dependency graph for unsupported native inputs. Initial builds
and unsupported targets follow Cargo's usual behavior.

Skipped dependencies are not compiled, so their errors and warnings won't appear. Use
`-Zohm-defer-dev-deps=no` to build all declared dev dependencies.

In a warm build, rebuilding ty's unit tests took 37.72 seconds with this optimization and 72.22
seconds without it; uv's took 26.22 and 30.97 seconds, respectively.

See:

- [Cargo #161](https://github.com/astral-sh/ohm-cargo/pull/161)

### 11. Run ready test binaries while compilation continues

**Status:** New experiment, opt-in.

Run `cargo +ohm -Zohm-ready-tests test` to start tests while Cargo is still compiling. Test binaries
run one at a time, with their ordinary arguments and environment. Build scripts, application
executables, and dynamic libraries must finish before tests start. Unsupported platforms, custom
runners, and incompatible terminal configurations retain ordinary execution.

Running tests alongside compilation can shorten the command, but it can also slow it down if they
compete for CPU, memory, or disk bandwidth. Tests may run in a different order and can make changes
before a later compilation failure.

You can also opt in with `CARGO_UNSTABLE_OHM_READY_TESTS=true`, or pass `-Zohm-ready-tests=no` to
disable it.

In a prototype ty comparison, the full command fell from 43.19 to 34.05 seconds while running the
same 868 tests.

See:

- [Cargo #153](https://github.com/astral-sh/ohm-cargo/pull/153)

### 12. Reduce build artifact disk usage

**Status:** New optimization.

Ohm removes old incremental snapshots once newer ones replace them. It also keeps the names of
retained debug object files stable, so rebuilds replace those files instead of leaving old copies
behind. Ohm stores compiler metadata more compactly and avoids storing duplicate metadata in
eligible registry and Git libraries.

For example, after an edit and rebuild, a new incremental snapshot can replace the previous one. Ohm
removes that superseded snapshot, so repeated edits do not leave a growing collection of old
snapshots for the same build.

When worktrees share a `CARGO_BUILD_BUILD_DIR`, each keeps its own mutable incremental state, so
cleanup in one cannot remove another's snapshots. Shared registry artifacts are keyed by their build
inputs and protected by locks: incompatible builds get separate artifacts, though concurrent builds
of the same artifact may wait.

`cargo clean` removes the selected project's private state, and removing a worktree removes its
default target directory. An external target can outlive its checkout.

On Linux and macOS, Ohm records when a build, check, or worktree seed uses a target. After an hour
of inactivity, `cargo +ohm gc` can reclaim that target’s binaries, documentation, incremental state,
and private compiler output. Cargo rounds the last-use time up to the next five-minute boundary.
An active build holds a lock that postpones cleanup.

`cargo +ohm gc --max-age 2d --dry-run` previews cleanup after two days of inactivity.
The same cutoff applies to shared compiler caches, individual dependency builds, and
ThinLTO objects. After an Ohm upgrade, GC can immediately reclaim marked intermediates from the old
compiler, even in a recently used checkout. It preserves directories that back external artifact
exports.

Manual cleanup continues in bounded batches until it finishes the available work. It scans idle
dependencies once per invocation, then rechecks their use under a lock before removal. A progress
bar reports eligible files and bytes during a dry run, or reclaimed files and bytes during cleanup.
If a cache is locked or inaccessible, Cargo continues independent cleanup and reports the problem;
`-v` identifies blocking locks.

On a Linux fixture with 2,048 expired dependency variants and 16 fresh ones, scanning candidates
once reduced median cleanup time from 30.1 to 4.9 seconds across four paired runs. Both versions
removed the same 18,432 files.

In a macOS benchmark, we ran the same development tasks with Ohm and stock Rust. Ohm used 40% less
disk space for Ruff and 35% less for uv.

See:

- [Cargo #68](https://github.com/astral-sh/ohm-cargo/pull/68)
- [Cargo #157](https://github.com/astral-sh/ohm-cargo/pull/157)
- [Cargo #158](https://github.com/astral-sh/ohm-cargo/pull/158)
- [Cargo #160](https://github.com/astral-sh/ohm-cargo/pull/160)
- [Cargo #174](https://github.com/astral-sh/ohm-cargo/pull/174)
- [Cargo #187](https://github.com/astral-sh/ohm-cargo/pull/187)
- [Cargo #188](https://github.com/astral-sh/ohm-cargo/pull/188)
- [Cargo #189](https://github.com/astral-sh/ohm-cargo/pull/189)
- [Cargo #190](https://github.com/astral-sh/ohm-cargo/pull/190)
- [Cargo #191](https://github.com/astral-sh/ohm-cargo/pull/191)
- [Cargo #77](https://github.com/astral-sh/ohm-cargo/pull/77)
- [Rust #97](https://github.com/astral-sh/ohm-rust/pull/97)
- [Rust #98](https://github.com/astral-sh/ohm-rust/pull/98)
- [Rust #123](https://github.com/astral-sh/ohm-rust/pull/123)

### 13. Use line tables by default

**Status:** Existing stable Rust feature, enabled by default in Ohm.

For development and test builds, Ohm records file and line numbers in the debug information by
default. These line tables let backtraces point to your source, but omit the type and variable
information that an interactive debugger needs. To retain full debug information for development
builds, set `debug = true` in `[profile.dev]`. Explicit profile, configuration, and environment
settings take precedence over Ohm's default.

For example, a panic backtrace can still point to `parser.rs:42`. If you stop there in a debugger
and want to inspect a local variable such as `tokens`, rebuild with full debug information.

See:

- [Cargo #127](https://github.com/astral-sh/ohm-cargo/pull/127)

### 14. Use Wild for Linux linking

**Status:** Existing linker, bundled and enabled by default in Ohm.

The linker combines compiled code into the final executable. For native x86-64 Linux GNU builds, Ohm
uses the Wild linker by default. Explicit linker settings still take precedence.

Wild performs a full link each time it runs. Cached relinking lets Ohm reuse the compiled code that
it passes to the linker, and Ohm can reuse eligible integration tests when it adds flags for Wild.

See:

- [Cargo #114](https://github.com/astral-sh/ohm-cargo/pull/114)
- [Cargo #139](https://github.com/astral-sh/ohm-cargo/pull/139)
- [Ohm #112](https://github.com/astral-sh/ohm/pull/112)

### 15. Avoid repeated Cargo preparation work

**Status:** New optimization.

Cargo resolves the workspace's dependencies before many commands. Ohm saves that result and reuses
it when the manifests, lockfile, configuration, and toolchain have not changed. Cargo still resolves
the packages and features needed by the current command. Ohm also avoids repeated filesystem checks
and unnecessary work preparing and reading build outputs. Commands that do not access Git skip
initializing its library.

When loading manifests, Ohm shares inherited workspace dependency maps between members and avoids
redundant allocations. It skips building a software bill of materials unless an output requests one.
It also reduces the work needed to prioritize build jobs and compare package identifiers. Separate
experiments on uv measured fewer instructions in Cargo for these changes; their wall-time effects
remain unresolved.

On Unix, Ohm 1.99.0-13 caches parsed registry manifests between Cargo invocations. For example,
two projects that use the same published crate can reuse its manifest through Cargo home. Cargo
checks the manifest contents and parser version before accepting a record; a miss parses the
original TOML and keeps its diagnostics. Each record has two possible slots in a bounded cache.
In the first version of the cache, an edited uv check used about 5% fewer Cargo instructions
with warm entries but about 18% more when populating them. Parsing each miss once reduced the
instruction count on that first run by about 7% relative to the initial implementation. These
experiments counted Cargo instructions; elapsed time was inconclusive.

Cargo can also order most package names by comparing their first eight bytes. When it changes
the source of a dependency, it can keep sharing the dependency's version and feature data.

On Unix, freshness checks hash source files in parallel when at least 128 checksums are uncached.
Cargo uses up to four workers within its job budget, preserves file order when reporting the first
stale input, and releases those slots before running compilers or build scripts.

For example, fixing a bug in `parse_number` leaves the workspace's dependency versions unchanged.
The next check can reuse the saved resolution. Adding a dependency to `Cargo.toml` invalidates it,
so Cargo resolves the dependencies again.

In an earlier experiment on a Codex workspace that had already been built, reusing the dependency
resolution reduced `cargo metadata` time from 413 to 358 milliseconds and Nextest time from 961 to
824 milliseconds.

In a warm Ruff experiment, skipping unnecessary dependency-file generation reduced unchanged
workspace checks by 18.2% and test builds by 20.2%. A separate change to output preparation and
dependency-file parsing reduced unchanged workspace builds by 13.8%.

In a separate warm Ruff comparison with eight jobs, parallel checksum checks reduced unchanged
`cargo test --workspace --no-run` wall time by 5.63% across 480 pairs (99% confidence interval:
2.92–8.27%). The `check` and `build` comparisons were inconclusive.

See:

- [Cargo #66](https://github.com/astral-sh/ohm-cargo/pull/66)
- [Cargo #88](https://github.com/astral-sh/ohm-cargo/pull/88)
- [Cargo #16](https://github.com/astral-sh/ohm-cargo/pull/16)
- [Cargo #143](https://github.com/astral-sh/ohm-cargo/pull/143)
- [Cargo #167](https://github.com/astral-sh/ohm-cargo/pull/167)
- [Cargo #175](https://github.com/astral-sh/ohm-cargo/pull/175)
- [Cargo #176](https://github.com/astral-sh/ohm-cargo/pull/176)
- [Cargo #177](https://github.com/astral-sh/ohm-cargo/pull/177)
- [Cargo #178](https://github.com/astral-sh/ohm-cargo/pull/178)
- [Cargo #179](https://github.com/astral-sh/ohm-cargo/pull/179)
- [Cargo #180](https://github.com/astral-sh/ohm-cargo/pull/180)
- [Cargo #181](https://github.com/astral-sh/ohm-cargo/pull/181)
- [Cargo #182](https://github.com/astral-sh/ohm-cargo/pull/182)
- [Cargo #183](https://github.com/astral-sh/ohm-cargo/pull/183)
- [Cargo #184](https://github.com/astral-sh/ohm-cargo/pull/184)
- [Cargo #185](https://github.com/astral-sh/ohm-cargo/pull/185)
- [Cargo #186](https://github.com/astral-sh/ohm-cargo/pull/186)
- [Cargo #235](https://github.com/astral-sh/ohm-cargo/pull/235)
- [Cargo #237](https://github.com/astral-sh/ohm-cargo/pull/237)
- [Cargo #238](https://github.com/astral-sh/ohm-cargo/pull/238)
- [Cargo #239](https://github.com/astral-sh/ohm-cargo/pull/239)
- [Cargo #240](https://github.com/astral-sh/ohm-cargo/pull/240)

### 16. Cache unchanged ThinLTO objects

**Status:** New optimization, enabled by default for eligible Linux builds.

ThinLTO optimizes code across compilation units. In supported non-incremental native builds, Ohm
can reuse the finished object for an unchanged unit, avoiding repeated LLVM optimization and code
generation. Cache keys cover the compiler, target, options, bitcode, and the cross-unit information
that affects optimization. This preserves the build's selected optimization settings.

With a shared build directory, Cargo shares these objects between compatible builds and cleans them
with `cargo +ohm gc`. If Cargo can't track where the cached objects came from, it keeps new objects
private. Private caches are pruned after builds; explicitly configured compiler cache directories
retain their own cleanup policy.

Unsupported compiler configurations, instrumentation, and wrappers keep ordinary compilation, as do
cache misses or failures. Use `-Zohm-thinlto-cache=no` to disable this default, or
`-Zohm-defaults=no` to disable it with Ohm's other defaults.

See:

- [Cargo #142](https://github.com/astral-sh/ohm-cargo/pull/142)
- [Cargo #164](https://github.com/astral-sh/ohm-cargo/pull/164)
- [Rust #164](https://github.com/astral-sh/ohm-rust/pull/164)

## rustfmt

### 17. Format only what changed

**Status:** New optimization.

After a successful run, Ohm's `cargo fmt` remembers which workspace packages it formatted. It can
skip those packages on the next run if their sources, configuration, and formatter have not changed.
When a module changes, Ohm can format or verify just that module if it can determine which crate
owns it and how the modules connect. Otherwise, it formats the whole crate. Set `OHM_INCREMENTAL_FMT=0`
to disable the cache.

Ohm also reduces filesystem and parsing work during formatting. For example, on Linux it can resolve
eligible paths with a single filesystem lookup, and it can skip scanning for comments when the text
contains no `/` character.

In the Codex release benchmark, checking formatting on unchanged sources took 11.91 seconds with
stock Rust and 0.31 seconds with Ohm. After an edit, it took 12.44 and 0.50 seconds, respectively.
Ohm's formatting cache was already warm in both cases. In a Ruff benchmark, the first formatting run
took 7.46 seconds with stock Rust and 8.94 seconds with Ohm.

In a separate Linux experiment on a warm Ruff workspace, formatting one edit that required a rewrite
fell from 4.62 to 0.37 seconds.

See:

- [rustfmt #13](https://github.com/astral-sh/ohm-rustfmt/pull/13)
- [rustfmt #14](https://github.com/astral-sh/ohm-rustfmt/pull/14)
- [rustfmt #27](https://github.com/astral-sh/ohm-rustfmt/pull/27)
- [rustfmt #28](https://github.com/astral-sh/ohm-rustfmt/pull/28)
- [rustfmt #29](https://github.com/astral-sh/ohm-rustfmt/pull/29)
- [rustfmt #30](https://github.com/astral-sh/ohm-rustfmt/pull/30)
- [rustfmt #31](https://github.com/astral-sh/ohm-rustfmt/pull/31)
- [rustfmt #32](https://github.com/astral-sh/ohm-rustfmt/pull/32)
- [rustfmt #33](https://github.com/astral-sh/ohm-rustfmt/pull/33)
- [rustfmt #34](https://github.com/astral-sh/ohm-rustfmt/pull/34)

## Rust compiler

### 18. Run the compiler frontend in parallel

**Status:** Existing experimental Rust feature, enabled by default in Ohm.

When Cargo invokes the compiler, Ohm enables Rust's experimental parallel frontend. The compiler can
then use up to eight threads to parse and analyze a crate. You can choose a thread count explicitly
or disable Ohm's defaults with `-Zohm-defaults=no`. Invoking `rustc` directly does not enable this
default. More threads can also increase memory use.

For example, a build may reach a large parser crate after all its dependencies have finished. Even
if Cargo has no other crates ready to compile, the compiler can check independent function bodies in
the parser on several threads.

In an experiment, we changed only the frontend thread setting and ran development sessions for Ruff,
uv, and Codex. Their combined time fell from 1,032 to 720 seconds, about 30%.

In native builds with multiple frontend workers, rustc starts encoding crate metadata as soon as the
function bodies it needs are ready. Another worker identifies exported symbols. Encoding waits for
that worker only when it needs the symbol list.

In two rounds with the same optimized compiler on the Rust #203 base, this change reduced the time
for an edited `check → build → check` by 3.6–5.4% on uv and 2.5–4.8% on Ruff. Timing ended when
Cargo returned, so pending filesystem writes could finish later.

See:

- [Cargo #90](https://github.com/astral-sh/ohm-cargo/pull/90)
- [Cargo #48](https://github.com/astral-sh/ohm-cargo/pull/48)
- [Rust #206](https://github.com/astral-sh/ohm-rust/pull/206)

### 19. Compile codegen units in batches

**Status:** New optimization.

The compiler divides generated code into units that LLVM can compile separately. Ohm compiles later
units in batches of up to two, rather than processing them one at a time. This bounds the amount of
intermediate code waiting for LLVM while allowing more work to proceed in parallel.

In a benchmark that replayed development commits, the batches made ty 7.6% faster and ripgrep 2.0%
faster, but uv 0.9% slower. CPU use rose in all three, and ty's peak memory use rose 6.2%.

See:

- [Rust #178](https://github.com/astral-sh/ohm-rust/pull/178)

### 20. Reuse compiler work across incremental builds

**Status:** New optimization.

The compiler groups generated code into units that it can compile separately. Ohm keeps these
groups stable across edits and reuses compatible decisions about where generic code belongs. It also
retains cached query results from those decisions so they can be reused after a later edit. This can
increase the size of the query cache; set `OHM_RETAIN_MONO_QUERY_VALUES=0` to disable the retention.

For incremental builds at optimization levels 0 and 1, Ohm can split large codegen units into
smaller stable groups. A later edit may then need to recompile only one group. Splitting can
increase stored object size and affect runtime performance. Use `-Zohm-cgu-split-limit` to change
the maximum number of groups, or `-Zohm-split-large-cgus=no` to disable splitting.

Ohm also reuses part of the metadata it has already encoded when its inputs have not changed. This
includes source-written exported macros when their text and source locations match. Generated macros
or changed locations require fresh encoding; `-Zohm-metadata-macro-reuse=no` disables this metadata
reuse for macros. If an incremental query cache cannot be loaded, Ohm discards the matching
dependency graph and recomputes it.

For example, suppose a test binary calls `parse::<u32>` and `parse::<u64>`. Changing an error
message in one test may leave both generated versions of `parse` and their dependencies unchanged.
Ohm can reuse its previous decisions about which compilation group contains each version, while
still compiling the edited test.

In a Codex TUI experiment, we repeatedly made and reverted one edit, then rebuilt the test binary.
Reusing the compiler's grouping decisions reduced average code generation time from 8.67 to 7.06
seconds.

In one uv comparison from the same starting state, retaining query results reduced an edited test
from 18.96 to 15.49 seconds. Including the preceding compiler refresh, the cycle fell from 24.53 to
20.80 seconds.

In an edit-and-rebuild experiment at optimization level 1, splitting reduced times by 32.8% for ty
and 45.8% for uv. Splitting also made ty's tests about 3–4% slower and increased uv's cold-build
time by 5.7% in separate comparisons.

When rustc loads a query result from disk, it can reuse the same bytes in the next incremental cache
until the cache needs compaction. If rustc recomputes a result, it writes the new value even when
its fingerprint stays the same. A source edit can move a diagnostic span without changing that
fingerprint. On uv, reusing the old span made a later incremental build crash.

Inside its private session directory, rustc unlinks the old query cache and dependency graph before
replacing them. On ext4, this can avoid waiting for pending writes.

On ext4, we used the same compiler binary to compare Rust #203 with the behavior at Rust #194.
Across two rounds of paired runs, a `check → build → check` sequence after an edit took 4.05% less
time on uv and 2.24% less on Ruff. Timing ended when the final check returned, so some filesystem
writes could finish after the measured sequence.

See:

- [Rust #54](https://github.com/astral-sh/ohm-rust/pull/54)
- [Rust #57](https://github.com/astral-sh/ohm-rust/pull/57)
- [Rust #65](https://github.com/astral-sh/ohm-rust/pull/65)
- [Rust #179](https://github.com/astral-sh/ohm-rust/pull/179)
- [Rust #183](https://github.com/astral-sh/ohm-rust/pull/183)
- [Rust #180](https://github.com/astral-sh/ohm-rust/pull/180)
- [Rust #190](https://github.com/astral-sh/ohm-rust/pull/190)
- [Rust #192](https://github.com/astral-sh/ohm-rust/pull/192)
- [Rust #193](https://github.com/astral-sh/ohm-rust/pull/193)
- [Rust #203](https://github.com/astral-sh/ohm-rust/pull/203)
- [Rust #207](https://github.com/astral-sh/ohm-rust/pull/207)

### 21. Reuse async code after it moves

**Status:** New optimization.

Moving async code to another line can invalidate compiled code even when its behavior stays the
same. Ohm tracks the source locations used by debuggers separately from the layout used to generate
code, so the compiler can reuse more of its previous output. By default, debug information omits
declaration locations for the generated coroutine states. Pass `-Zdebug-info-type-line-numbers=true`
to restore those locations.

For example, adding a comment above an unchanged async function shifts its line numbers. Ohm keeps
those source locations separate from the layout of the function's saved state, so the line shift
alone need not invalidate compiler work that depends only on that layout.

In an earlier uv benchmark with full debug information, development commands that exercised Python
version files took a total of 140.81 seconds before this change and 123.25 seconds after it. A
separate benchmark of uv's PyPI JSON parsing was essentially unchanged.

See:

- [Rust #132](https://github.com/astral-sh/ohm-rust/pull/132)

### 22. Reduce repeated compiler work

**Status:** New optimization.

Ohm also removes smaller sources of repeated work inside the compiler. It reuses incremental query
results, avoids walking the same type constraints twice, and skips unnecessary work when generating
code for development builds. For example, it can omit cleanup paths that have become empty and avoid
constructing intermediate lists while checking type constraints. Other changes avoid repeated
lookups, reuse LLVM target machines, and reduce the size of compiler data structures.

Within one compilation, rustc remembers which crate each direct `--extern` name or alias resolved
to. Generated tests and macros can then reuse that lookup. For transitive dependencies, rustc uses
the metadata hash to distinguish versions of the same crate.

Ohm 1.99.0-13 allocates three compiler worker caches only when a worker first uses them. It also
skips an extern lookup when crate metadata already identifies a dependency as public. When
collecting implementations of a trait, rustc skips crates whose metadata lists none for that trait.

When checking an opaque type such as `impl Iterator`, rustc can reuse the bounds from the
type's signature for each pair of lifetimes it compares. Each comparison gets its own inference
state. This change cut compiler instructions for uv's library by 2.44% and 2.29% on two Linux
hosts after a version-matching edit. The same edit exercises incremental queries in `uv-client`:
letting nested queries reuse up to eight dependency recorders instead of four cut compiler
instructions for that crate by 2.47% and 1.37%. The larger pool can retain more memory. Both
experiments used compilers without release PGO or BOLT and measured instructions for one crate.

When laying out async state, Ohm skips redundant work when tracking which values are live at the
same time. This backports a change from
[rust-lang/rust #163126](https://github.com/rust-lang/rust/pull/163126). On Unix, Ohm also reduces
peak memory use by keeping a read-only mapping of an incremental query cache while rewriting it,
instead of copying the retained data into memory.

For example, a generic type `Container<T>` might require `T: Clone`. When checking a use of that
type, the compiler gathers the bounds that apply to it. Ohm gathers those bounds in one walk through
their declarations, avoiding a second walk and temporary lists.

In an experiment, the simpler checks of type constraints reduced the time to check Ruff's
`ty_python_semantic` crate by about 4%. In a separate experiment, the changes to code generation in
development builds reduced `uv-resolver` compilation time by about 8–9%.

In another experiment, the lookup and data-structure changes, together with Cargo's filesystem
caches, reduced total rebuild time across 13 uv development commits from 478.19 to 446.97 seconds,
or 6.5%. Focused Ruff measurements of the query-cache change saved about 36 MiB during a check and
114 MiB during a build, with no consistent wall-time improvement.

In 12 paired runs on Ruff, caching these lookups reduced an edited `cargo test --lib --no-run` from
12.50 to 11.83 seconds. The experiment used stage2 compilers built without release PGO or BOLT.

See:

- [Rust #72](https://github.com/astral-sh/ohm-rust/pull/72)
- [Rust #101](https://github.com/astral-sh/ohm-rust/pull/101)
- [Rust #141](https://github.com/astral-sh/ohm-rust/pull/141)
- [Rust #173](https://github.com/astral-sh/ohm-rust/pull/173)
- [Rust #181](https://github.com/astral-sh/ohm-rust/pull/181)
- [Rust #205](https://github.com/astral-sh/ohm-rust/pull/205)
- [Rust #218](https://github.com/astral-sh/ohm-rust/pull/218)
- [Rust #219](https://github.com/astral-sh/ohm-rust/pull/219)
- [Rust #222](https://github.com/astral-sh/ohm-rust/pull/222)
- [Rust #226](https://github.com/astral-sh/ohm-rust/pull/226)
- [Rust #227](https://github.com/astral-sh/ohm-rust/pull/227)

### 23. Reduce allocator page-clearing work

**Status:** Default allocator setting on Linux.

Ohm disables transparent huge pages in rustc's mimalloc allocator by default. A Ruff edited-check
profile found that clearing huge pages accounted for roughly 40% of sampled CPU time. Disabling them
reduced the median check from 10.78 to 8.60 seconds across four trials. The `MIMALLOC_ALLOW_THP`
environment override remains available. See [Rust #191](https://github.com/astral-sh/ohm-rust/pull/191).

### 24. Avoid generating async bodies for metadata

**Status:** New optimization.

During `cargo check`, the compiler needs to know how an async function's state is laid out in
memory. Ohm can compute that layout without also constructing the code that resumes or drops the
future. The compiler generates those bodies later if it needs them for a build. This reduces work
during checks and leaves less metadata for dependent crates to read.

For example, consider a function that waits before printing a message:

```rust
async fn print_when_ready(message: String, ready: impl std::future::Future<Output = ()>) {
    ready.await;
    println!("{message}");
}
```

If the wait pauses execution, the future must keep `message` until it can print it. During a check,
Ohm determines how to store that state. It defers constructing the code that resumes the function or
drops its saved values until a build needs it.

In an earlier experiment on `codex-core`, the metadata shrank from 23.43 to 11.34 MB and average
compilation time fell from 29.05 to 28.70 seconds.

See:

- [Rust #99](https://github.com/astral-sh/ohm-rust/pull/99)

### 25. Cache derive and attribute macro expansions

**Status:** Existing experimental Rust feature, enabled by default in Ohm.

A derive macro generates Rust code from a type declaration. Ohm enables Rust's experimental cache
for that generated code so the compiler can reuse previous macro expansions. The cache can be
unsound if a macro depends on an input that the cache does not track: it may reuse code that no
longer matches the input. Cargo also has trust settings for reusing compiled macros and worktree
snapshots; those settings control separate caches and carry their own soundness risks.

For example, `#[derive(serde::Serialize)]` on a `Config` struct generates code to serialize its
fields. If you edit a separate `connect` function without changing the struct or the macro's other
inputs, Ohm can reuse that generated code while checking the edited function.

Ohm 1.99.0-12 also caches attribute macro expansions. Editing the annotated item, its attribute,
or the macro crate invalidates the entry. A macro that reads a tracked file or environment value,
inspects source locations or text, or requests nested expression expansion runs again. In the
original compiler comparison, this saved 0.66 seconds (9.1%) on an incremental Ruff check after an
unrelated edit.

In the uv benchmark, we applied a private parser edit, checked the dependent crate, and ran the
parser tests. The full sequence took a median of 4.02 seconds with macro caching and 4.15 seconds
without it.

See:

- [Cargo #54](https://github.com/astral-sh/ohm-cargo/pull/54)
- [Rust #208](https://github.com/astral-sh/ohm-rust/pull/208)

## Clippy

### 26. Reuse Clippy results for unchanged modules

**Status:** New optimization.

Ohm uses the compiler's incremental query system to cache the results of selected Clippy lint
passes. After an edit, it can reuse results from unchanged modules instead of running those passes
again. If Ohm cannot safely track all the inputs to a lint pass, that pass still scans the whole
crate.

For example, suppose you edit a private helper in `parser.rs`. If the edit leaves `network.rs` and
the inputs to its cached lint passes unchanged, Ohm can replay that module's warnings while checking
the code affected by your edit.

In an earlier Ruff experiment, we applied three edits and compared Clippy with and without this
cache. Average Clippy time fell from 40.55 to 38.85 seconds, about 4.2%. In a separate benchmark
that invoked Clippy's compiler driver directly on a small crate, the time increased from 52.99 to
60.92 milliseconds.

See:

- [Clippy #48](https://github.com/astral-sh/ohm-rust-clippy/pull/48)
- [Clippy #49](https://github.com/astral-sh/ohm-rust-clippy/pull/49)

Ohm also skips expensive lint analysis when it can establish that no warning can result. For
example, the change in [Clippy #38](https://github.com/astral-sh/ohm-rust-clippy/pull/38) skips the
analysis for unnecessary clones in functions with no relevant calls. Earlier refinements to this
analysis reduced the time to rerun Clippy after a Codex edit from 5.62 to 5.04 seconds, compared
with a version that already skipped some unnecessary analysis.

See:

- [Clippy #7](https://github.com/astral-sh/ohm-rust-clippy/pull/7)

### 27. Preserve dependency reuse during Clippy

**Status:** New optimization.

Clippy runs workspace crates through its compiler wrapper, while ordinary dependencies still use
rustc. Ohm lets dependencies reuse compatible check and build results while running Clippy on the
workspace crates. It also caches compiler capability checks when switching between rustc and Clippy.

For example, after checking a workspace, running Clippy can reuse unchanged registry dependencies
instead of checking them again. Workspace crates still run through Clippy, including after an edit
that introduces a lint.

In one Codex session replay, using a Cargo build with this reuse reduced Clippy time from 124.56 to
56.99 seconds and total session time from 322.72 to 250.58 seconds.

See:

- [Cargo #156](https://github.com/astral-sh/ohm-cargo/pull/156)
- [Cargo #168](https://github.com/astral-sh/ohm-cargo/pull/168)
