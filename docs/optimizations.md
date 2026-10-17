# How Ohm speeds up development

Ohm includes the following changes to Rust, Cargo, Clippy, and rustfmt.

This guide covers Ohm 1.99.0-5. The measurements come from release benchmarks and individual
experiments, including earlier prototypes. They do not predict the benefit for every project.

## Cargo and builds

### 1. Avoid rebuilding dependents after private changes

**Status:** New optimization.

Cargo normally recompiles downstream crates when a dependency changes. Ohm computes a hash of the
interface exposed by eligible libraries and avoids rebuilding dependents when that interface is
unchanged. (The changed library is still compiled, but its dependents can be reused.) If the
interface changes, Cargo starts downstream compilation once the new metadata is ready, without
waiting for the rest of the dependency's build.

For example, assume that `linter` depends on `parser`. If you fix a bug in a private parser helper
without changing the exposed interface, Ohm recompiles `parser` but can reuse `linter`. An
executable using them still needs to be relinked to pick up the change.

In a uv benchmark, we made a private change to uv's JSON parser in `uv-pypi-types`, then checked the
dependent `uv-client` crate, which took a median of 4.93 seconds without public API hashing and 2.16
seconds with it.

See:

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
require recompilation.

This helps most when an edit to a dependency would otherwise force an expensive executable or test
binary to recompile.

In the `linter` and `parser` example above, the linker combines their compiled code into the
`linter` executable. After the private parser fix, Ohm can link the rebuilt parser with the linter's
existing compiled code. The resulting executable includes the fix even though Ohm did not recompile
the linter's own code.

In a release benchmark, we changed a dependency, then rebuilt and ran a test. The median time for
the test command fell from 26.27 to 3.79 seconds for uv. This comparison includes public API hashing
and Ohm's other changes, so it doesn't measure the effect of relinking alone.

See:

- [Cargo #51](https://github.com/astral-sh/ohm-cargo/pull/51)
- [Cargo #52](https://github.com/astral-sh/ohm-cargo/pull/52)

### 3. Reuse builds during checks

**Status:** New optimization.

A build already produces some of the information that `cargo check` and Clippy need. Ohm can reuse
this metadata from registry and workspace libraries after verifying that the compiler, build inputs,
saved files, and cached diagnostics are compatible. It also keeps earlier check results when you
build tests, so switching between testing and checking can reuse work from both.

For example, suppose you run `cargo +ohm build`, then `cargo +ohm check` in the same workspace. The
build has already checked and compiled a dependency such as `memchr`. If its inputs still match, Ohm
can use the metadata from that build instead of checking `memchr` again.

In the release benchmarks, we built each project and then timed a check. The uv check took 70.46
seconds with stock Rust and 23.90 seconds with Ohm; the Codex check took 125.54 and 63.67 seconds,
respectively.

Ohm can also reuse a package's built library when checking its other targets, and reuse a built
test executable's compilation results when checking that test. An explicit `--lib` selection still
checks the library. Reusing compilation results does not run the tests.

Workspace build scripts no longer prevent this reuse when their saved execution records and all
affected consumers remain fresh. Missing records or changed inputs cause an ordinary check. As with
Cargo's normal freshness checks, this depends on build scripts declaring the inputs they read.

Libraries that use local procedural macros become eligible only with
`CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST=all`. This opt-in assumes those macros and their helpers do not
read untracked inputs; otherwise, reuse can preserve stale generated code. It does not enable reuse
through build scripts in a procedural macro's dependency chain.

See:

- [Cargo #75](https://github.com/astral-sh/ohm-cargo/pull/75)
- [Cargo #91](https://github.com/astral-sh/ohm-cargo/pull/91)
- [Cargo #89](https://github.com/astral-sh/ohm-cargo/pull/89)
- [Cargo #149](https://github.com/astral-sh/ohm-cargo/pull/149)
- [Cargo #150](https://github.com/astral-sh/ohm-cargo/pull/150)
- [Cargo #152](https://github.com/astral-sh/ohm-cargo/pull/152)
- [Cargo #154](https://github.com/astral-sh/ohm-cargo/pull/154)

### 4. Reuse checks during builds

**Status:** New optimization, enabled by default for eligible debug builds.

A native build repeats type checking and borrow checking that a preceding `cargo check` may have
already done. Ohm saves separate check and build checkpoints, then reuses compatible frontend
results after validating their dependencies. It retains the native build's generated objects for
later incremental builds. Check outputs remain distinct from build outputs: a successful check
cannot substitute for compiling and linking a program.

For example, after checking a parser change, you can build the parser and reuse some of the work
from that check. Release builds, test targets, procedural macros, build scripts, and unsupported
compiler configurations retain ordinary behavior. The extra checkpoints consume disk space. Use
`-Zohm-shared-stages=no` on both commands to opt out.

Ohm 1.99.0-5 fixes a compiler panic after const-generic type edits by rerunning queries whose side
effects cannot be restored from the saved check.

An earlier prototype reduced a first build after a check from 104.44 to 80.66 seconds. A later uv
warm-cycle pair was slightly slower with sharing, at 5.80 versus 5.72 seconds. These measurements
do not establish a general speedup for the released implementation.

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
eligible registry artifacts and reusable ThinLTO objects. We also include additional "trust" settings to allow for reuse of procedural macros and native tools, but
that reuse can be unsound.

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
the library builds successfully. If it cannot accept the early result, Cargo retries after the
library finishes successfully.

This also applies when editing a test whose previous build established that the library was unused.
Stale or inconclusive evidence keeps ordinary scheduling. The optimization requires Headstart and
at least two build jobs; `-Zohm-early-tests=no` disables it.

All requested libraries and application executables still finish before tests run. This setting
overlaps compilation; the separate opt-in below allows test execution to overlap compilation.

See:

- [Cargo #146](https://github.com/astral-sh/ohm-cargo/pull/146)
- [Cargo #147](https://github.com/astral-sh/ohm-cargo/pull/147)

### 10. Skip unused dev-dependency rebuilds in targeted tests

**Status:** New optimization, enabled by default for eligible native library-test rebuilds.

A library's test target can declare a workspace dev dependency without using it. After an edit,
ordinary Cargo may rebuild that dependency and the normal library it depends on before compiling
the tests. Ohm can skip those rebuilds when the previous test executable recorded the dependency
as unused. It accepts the new executable only after the compiler confirms that the dependency is
still unused. Missing or inconsistent evidence causes one retry with the complete graph.

For example, `cargo +ohm test -p parser --lib` can rebuild the parser's unit tests without rebuilding
an unused test helper. Dependencies still needed by another retained edge continue to build. The
optimization preserves dependency resolution, features, compiler arguments, and optimization settings.
Initial builds, unsupported targets, and dependencies with build scripts or other opaque effects
keep ordinary scheduling.

A successful targeted test no longer establishes that every declared dev dependency compiles:
errors and warnings in skipped dependencies are omitted. Use `-Zohm-defer-dev-deps=no` to validate
the complete declared graph. A failed speculative attempt can also add a compilation before the
ordinary retry.

An earlier off/on prototype pair reduced a ty unit-test edit and rebuild from 55.36 to 29.52 seconds.
The uv comparison was nearly unchanged, at 15.14 versus 14.88 seconds. These measurements preceded
the final validation checks and default setting.

See:

- [Cargo #161](https://github.com/astral-sh/ohm-cargo/pull/161)

### 11. Run ready test binaries while compilation continues

**Status:** New experiment, opt-in.

`cargo +ohm -Zohm-ready-tests test` can run confirmed test binaries while Cargo compiles other
targets. Test binaries still run one at a time, with their ordinary arguments and runtime
environment. Build scripts, application executables, and dynamic libraries must finish before early
execution starts. Unsupported platforms, custom runners, and incompatible terminal configurations
retain ordinary execution.

This can shorten the command when there is enough compilation to overlap with testing. It can also
be slower when tests and compilation compete for CPU, memory, or disk bandwidth. Test order can
change, and tests may produce side effects before a later compilation failure. Cancellation stops
active test processes but cannot undo those effects.

Ohm does not enable this option by default. You can also opt in with
`CARGO_UNSTABLE_OHM_READY_TESTS=true`; `-Zohm-ready-tests=no` overrides an opt-in. Changing
`ohm-defaults` does not change an explicit ready-test setting.

In a prototype ty comparison, the full command fell from 43.19 to 34.05 seconds while running the
same 868 tests. Those measurements preceded terminal support and the final stack changes.

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

Ohm 1.99.0-4 moves private build state from the global build directory into each worktree's target.
The first build after this layout change rebuilds private intermediates. Shared registry artifacts
stay in place; reuse still requires compatible build inputs. `cargo clean` removes the selected
project's private state, and removing a worktree removes its default target. Explicit target
directories outside the checkout need separate cleanup.

On Linux and macOS, `cargo +ohm gc --dry-run` previews cleanup of shared build caches, and
`cargo +ohm gc` performs it. Current-release compiler contexts and individual dependency builds
become eligible after one hour without use. Contexts from older Ohm releases, removed compilers,
and recognized legacy layouts are eligible immediately. Builds, tests, worktree commands, and
upgrades do not invoke this cleanup automatically.

GC preserves local targets and skips shared roots with active consumers. Builds and programs
launched by this Cargo version hold leases that protect their artifacts, including after Cargo
exits; programs launched by older Cargo versions may not have that protection. Unknown usage and
unfamiliar or malformed state do not establish that an artifact is disposable. Reclaimed artifacts
rebuild on demand.

Usage tracking reads the selected dependencies' records on warm builds. It updates timestamps at
five-minute intervals and rounds them upward, so cleanup always allows a full hour without use and
may retain artifacts for up to five additional minutes. Repeated builds within an interval skip
the write transaction; short builds also skip the completion query. A machine crash can lose recent
usage timestamps, allowing a later explicit GC command to reclaim artifacts that could have been
reused.

In a macOS benchmark, we ran the same development tasks with Ohm and stock Rust. Ohm used 40% less
disk space for Ruff and 35% less for uv. These savings include the effects of Ohm's build reuse and
default debug settings.

See:

- [Cargo #68](https://github.com/astral-sh/ohm-cargo/pull/68)
- [Cargo #157](https://github.com/astral-sh/ohm-cargo/pull/157)
- [Cargo #158](https://github.com/astral-sh/ohm-cargo/pull/158)
- [Cargo #160](https://github.com/astral-sh/ohm-cargo/pull/160)
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

The uv benchmarks compare stock Rust's full debug information with Ohm's line tables, so this
default can affect the comparison. Ruff and Codex explicitly request matching debug levels. The
release benchmarks do not measure the effect of line tables separately.

See:

- [Cargo #127](https://github.com/astral-sh/ohm-cargo/pull/127)

### 14. Use Wild for Linux linking

**Status:** Existing linker, bundled and enabled by default in Ohm.

The linker combines compiled code into the final executable. For native x86-64 Linux GNU builds, Ohm
uses the Wild linker by default. Explicit linker settings still take precedence.

Wild performs a full link each time it runs. Cached relinking lets Ohm reuse the compiled code that
it passes to the linker. The release benchmarks include Wild alongside Ohm's other changes, so they
do not measure its contribution separately.

Ohm recognizes the flags it adds for bundled Wild when deciding whether an integration test can be
reused. Those automatic flags no longer prevent reuse of a test that does not use a changed
library. Explicit linker inputs still receive the existing checks.

See:

- [Cargo #114](https://github.com/astral-sh/ohm-cargo/pull/114)
- [Cargo #139](https://github.com/astral-sh/ohm-cargo/pull/139)
- [Ohm #112](https://github.com/astral-sh/ohm/pull/112)

### 15. Reuse Cargo's dependency resolution

**Status:** New optimization.

Cargo resolves the workspace's dependencies before many commands. Ohm saves that result and reuses
it when the manifests, lockfile, configuration, and toolchain have not changed. Cargo still resolves
the packages and features needed by the current command.

For example, fixing a bug in `parse_number` leaves the workspace's dependency versions unchanged.
The next check can reuse the saved resolution. Adding a dependency to `Cargo.toml` invalidates it,
so Cargo resolves the dependencies again.

In an earlier experiment on a Codex workspace that had already been built, reusing the dependency
resolution reduced `cargo metadata` time from 413 to 358 milliseconds and Nextest time from 961 to
824 milliseconds.

See:

- [Cargo #66](https://github.com/astral-sh/ohm-cargo/pull/66)
- [Cargo #88](https://github.com/astral-sh/ohm-cargo/pull/88)
- [Cargo #16](https://github.com/astral-sh/ohm-cargo/pull/16)

Ohm also caches repeated filesystem checks while preparing a build graph, including canonical
build-profile paths and probes for custom codegen backends. These caches last only for the relevant
graph scan or lock reservation. See [Cargo #143](https://github.com/astral-sh/ohm-cargo/pull/143).

### 16. Cache unchanged ThinLTO objects

**Status:** New optimization, enabled by default for eligible Linux builds.

ThinLTO optimizes code across compilation units. In supported non-incremental native builds, Ohm
can reuse the finished object for an unchanged unit, avoiding repeated LLVM optimization and code
generation. Cache keys cover the compiler, target, options, bitcode, and the cross-unit information
that affects optimization. This preserves the build's selected optimization settings.

With a shared build directory, Cargo stores these objects under
`<build-dir>/.ohm-thinlto-cache/<compiler-context>`. Starting with Ohm 1.99.0-5, `cargo +ohm gc`
collects individual objects after one hour without compiler use, and obsolete compiler contexts
immediately. Shared caches no longer scan or prune at build completion. Cleanup remains manual and
respects active consumers. Rustc refreshes an object's modification time when it reuses the object;
Cargo does not add per-object database records or timestamp updates to warm builds.

If Cargo cannot record the shared cache's provenance, it keeps new objects private. Private caches
retain the existing policy: after a build, remove entries unused for 30 days and prune the least
recently used objects to limits of 2 GiB or 100,000 objects. Concurrent writers or contended locks can
temporarily leave those caches above their limits. Explicit compiler cache directories retain their
own policy.

Unsupported compiler configurations, instrumentation, and wrappers keep ordinary compilation, as do
cache misses or failures. Use `-Zohm-thinlto-cache=no` to disable this default, or `-Zohm-defaults=no`
to disable it with Ohm's other defaults. A focused smoke test observed 133 warm cache hits and
byte-identical executables; it does not establish a whole-build speedup.

See:

- [Cargo #142](https://github.com/astral-sh/ohm-cargo/pull/142)
- [Cargo #164](https://github.com/astral-sh/ohm-cargo/pull/164)
- [Rust #164](https://github.com/astral-sh/ohm-rust/pull/164)

## rustfmt

### 17. Format only what changed

**Status:** New optimization.

After a successful run, Ohm's `cargo fmt` remembers which workspace packages it formatted. It can
skip those packages on the next run if their sources, configuration, and formatter have not changed.
When a module changes, Ohm can format just that module if it can verify which crate owns it and how
the modules connect. Set `OHM_INCREMENTAL_FMT=0` to disable the cache.

In the Codex release benchmark, checking formatting on unchanged sources took 11.91 seconds with
stock Rust and 0.31 seconds with Ohm. After an edit, it took 12.44 and 0.50 seconds, respectively.
Ohm's formatting cache was already warm in both cases. In a Ruff benchmark, the first formatting run
took 7.46 seconds with stock Rust and 8.94 seconds with Ohm.

See:

- [rustfmt #13](https://github.com/astral-sh/ohm-rustfmt/pull/13)
- [rustfmt #14](https://github.com/astral-sh/ohm-rustfmt/pull/14)

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

In an experiment on an earlier Ohm release, we changed only the frontend thread setting and ran
development sessions for Ruff, uv, and Codex. Their combined time fell from 1,032 to 720 seconds,
about 30%.

Ohm also compiles later codegen units in batches of up to two instead of processing each one
serially. This bounds the amount of intermediate code waiting for LLVM. Development-commit replays
were 7.6% faster for ty and 2.0% faster for ripgrep, but 0.9% slower for uv; CPU use rose in all
three, and ty's peak memory use rose 6.2%. These compiler builds did not use PGO or BOLT.

See:

- [Cargo #90](https://github.com/astral-sh/ohm-cargo/pull/90)
- [Cargo #48](https://github.com/astral-sh/ohm-cargo/pull/48)
- [Rust #178](https://github.com/astral-sh/ohm-rust/pull/178)

### 19. Reuse compiler work across incremental builds

**Status:** New optimization.

The compiler groups generated code into units that it can compile separately. Ohm keeps these groups
stable across edits and reuses compatible decisions about where generic code belongs. This lets it
reuse more work from the previous build. Ohm also reuses part of the metadata it has already encoded
when the inputs to that metadata have not changed.

For example, suppose a test binary calls `parse::<u32>` and `parse::<u64>`. Changing an error
message in one test may leave both generated versions of `parse` and their dependencies unchanged.
Ohm can reuse its previous decisions about which compilation group contains each version, while
still compiling the edited test.

In a Codex TUI experiment, we repeatedly made and reverted one edit, then rebuilt the test binary.
Reusing the compiler's grouping decisions reduced average code generation time from 8.67 to 7.06
seconds.

See:

- [Rust #54](https://github.com/astral-sh/ohm-rust/pull/54)
- [Rust #57](https://github.com/astral-sh/ohm-rust/pull/57)
- [Rust #65](https://github.com/astral-sh/ohm-rust/pull/65)

For incremental builds at optimization levels 0 and 1, Ohm splits oversized codegen units into
stable groups using spare slots within the configured unit limit. A later edit can then recompile
a smaller group. The compiler splits each oversized unit into at most eight groups by default.
The compiler option `-Zohm-cgu-split-limit` changes that limit; `1` disables splitting, as does
`-Zohm-split-large-cgus=no`.

At optimization level 1, eight paired edit-and-rebuild measurements found a 32.8% reduction for ty
and a 45.8% reduction for uv. Splitting also made ty's tests about 3–4% slower and increased uv's
cold-build time by 5.7% in separate comparisons. Lower split limits did not eliminate the measured
runtime cost. These experiments used a compiler without PGO, eight build jobs, and no LTO;
packaged-release performance may differ. Splitting can also increase stored object size.

See:

- [Rust #179](https://github.com/astral-sh/ohm-rust/pull/179)
- [Rust #183](https://github.com/astral-sh/ohm-rust/pull/183)

Source-written exported macros no longer rule out metadata-prefix reuse for an entire crate. Ohm
allows reuse when the macro text and the exact source locations of its tokens and delimiters match.
Generated macros, changed locations, or invalid cache records require fresh encoding. Use
`-Zohm-metadata-macro-reuse=no` to disable this extension. See
[Rust #180](https://github.com/astral-sh/ohm-rust/pull/180).

### 20. Reuse async code after it moves

**Status:** New optimization.

Moving async code to another line can invalidate compiled code even when its behavior stays the
same. Ohm tracks the source locations used by debuggers separately from the layout used to generate
code, so the compiler can reuse more of its previous output. By default, debug information omits
declaration locations for the generated coroutine states. Pass `-Zdebug-info-type-line-numbers=true`
to restore those locations.

For example, adding a comment above an unchanged async function shifts its line numbers. Ohm keeps
those source locations separate from the layout of the function's saved state, so the line shift
alone need not invalidate compiler work that depends only on that layout.

In an earlier uv benchmark that exercised handling of Python version files, the development commands
took a total of 140.81 seconds before this change and 123.25 seconds after it. A separate benchmark
of uv's PyPI JSON parsing was essentially unchanged. Both benchmarks used full debug information, so
they do not establish the benefit with Ohm's default line tables.

See:

- [Rust #132](https://github.com/astral-sh/ohm-rust/pull/132)

### 21. Reduce repeated compiler work

**Status:** New optimization.

Ohm also removes smaller sources of repeated work inside the compiler. It reuses incremental query
results, avoids walking the same type constraints twice, and skips unnecessary work when generating
code for development builds. For example, it can omit cleanup paths that have become empty and avoid
constructing intermediate lists while checking type constraints.

For example, a generic type `Container<T>` might require `T: Clone`. When checking a use of that
type, the compiler gathers the bounds that apply to it. Ohm gathers those bounds in one walk through
their declarations, avoiding a second walk and temporary lists.

In an experiment, the simpler checks of type constraints reduced the time to check Ruff's
`ty_python_semantic` crate by about 4%. In a separate experiment, the changes to code generation in
development builds reduced `uv-resolver` compilation time by about 8–9%.

See:

- [Rust #72](https://github.com/astral-sh/ohm-rust/pull/72)
- [Rust #101](https://github.com/astral-sh/ohm-rust/pull/101)

Other changes avoid interner lookups for common primitive types, reuse LLVM target machines during
layout validation, and reduce the size of hashing and dependency-graph indices. Together with
Cargo's filesystem caches, these changes reduced total rebuild time across 13 uv development
commits from 478.19 to 446.97 seconds, or 6.5%. This comparison used compiler builds without PGO or
BOLT and does not isolate any one change. See
[Rust #173](https://github.com/astral-sh/ohm-rust/pull/173).

When computing async state layout, Ohm also skips a storage-conflict update if the current live set
is contained in the last set whose conflicts were recorded. After recording conflicts among
`{a, b, c}`, observing `{a, b}` adds nothing. This backports the change merged in
[rust-lang/rust #163126](https://github.com/rust-lang/rust/pull/163126); upstream performance testing
found no instruction-count regressions and one small improvement. See
[Rust #141](https://github.com/astral-sh/ohm-rust/pull/141).

On Unix, Ohm retains a read-only mapping while rewriting an incremental query cache instead of
copying its retained bytes into a temporary heap buffer. This lowers peak memory use without
changing the cache format. Focused Ruff measurements saved about 36 MiB during a check and 114 MiB
during a build, with no consistent wall-time improvement. See
[Rust #181](https://github.com/astral-sh/ohm-rust/pull/181).

### 22. Avoid generating async bodies for metadata

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

### 23. Cache derive macro expansions

**Status:** Existing experimental Rust feature, enabled by default in Ohm.

A derive macro generates Rust code from a type declaration. Ohm enables Rust's experimental cache
for that generated code so the compiler can reuse previous macro expansions. The cache can be
unsound if a macro depends on an input that the cache does not track: it may reuse code that no
longer matches the input. Cargo also has trust settings for reusing compiled macros and worktree
snapshots; those settings control separate caches and carry their own soundness risks.

For example, `#[derive(serde::Serialize)]` on a `Config` struct generates code to serialize its
fields. If you edit a separate `connect` function without changing the struct or the macro's other
inputs, Ohm can reuse that generated code while checking the edited function.

In the uv benchmark, we applied a private parser edit, checked the dependent crate, and ran the
parser tests. The full sequence took a median of 4.02 seconds with macro caching and 4.15 seconds
without it. The runs varied substantially, so they do not give a precise estimate of the cache's
benefit.

See:

- [Cargo #54](https://github.com/astral-sh/ohm-cargo/pull/54)

## Clippy

### 24. Reuse Clippy results for unchanged modules

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

### 25. Preserve dependency reuse during Clippy

**Status:** Fix to the default build/check reuse optimization.

Clippy runs workspace crates through its compiler wrapper, while ordinary dependencies still use
rustc. Ohm now makes reuse decisions for each compilation unit: wrapped workspace crates retain
Clippy's configuration and lint checks, and unwrapped dependencies can reuse compatible check and
build results. Compiler capability checks also use the underlying dependency compiler.

For example, after checking a workspace, running Clippy no longer causes Ohm to check unchanged
registry dependencies again merely because the command has a workspace wrapper. Workspace crates
still run through Clippy, including after an edit that introduces a lint.

In one controlled Codex session replay, replacing only Cargo with this fix reduced Clippy time
from 124.56 to 56.99 seconds and total session time from 322.72 to 250.58 seconds. Registry compiler
invocations during Clippy fell from 1,077 to zero. Both runs used the released compiler, Clippy,
and Wild, separate fresh build directories, and eight jobs; CPU monitoring found no competing work.
This single ordered pair demonstrates the regression and its repair, but does not give a precise
estimate across projects or repeated runs.

See:

- [Cargo #156](https://github.com/astral-sh/ohm-cargo/pull/156)
