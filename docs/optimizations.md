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
executable using them still needs to be relinked to pick up the change. If `linter` produces a
static library, Cargo rebuilds the archive because it contains the parser's code. This also applies
when `linter` produces both a static library and an `rlib`.

During `cargo check`, moving a private method can also move the source spans in a private type's
trait implementations. Ohm keeps the trait headers that downstream code needs for type inference,
but can omit private implementation details from the interface hash. Two edits to Ruff's parser
then required checking just the parser, down from 35 and 22 compiler invocations. An edit to
its public lexer still required all 35.

Incremental native builds can reuse downstream crates after the same kind of private edit. A
re-export can expose a source location or a macro expansion to another crate. Ohm tracks those
locations and looks up each expansion by its stable identity, so an unrelated edit can renumber
expansions without forcing a rebuild. Moving a source location that a caller uses still invalidates
the cached metadata. The first build after upgrading rebuilds old workspace metadata once.

We changed the diagnostic for a mixed literal in Ruff's parser and compared the Ohm compiler
before and after the native optimization on Linux. Across 12 paired runs per command, the median
workspace build fell from 19.21 to 5.60 seconds and `cargo test --no-run` fell from 25.58 to 8.24
seconds. Full compiler invocations fell from 35 to 3 for the build and from 93 to 6 for the test
binaries. Both compilers invoked the linker eight times for the build and 67 times for the tests.

A crate can export a macro and still keep a private enum's derived implementations out of its
public interface. Ohm tracks which types a caller can reach and keeps the trait headers that
downstream selection needs. With the compiler change, correcting a private doc comment in Ruff's
linter reduced full compiler invocations from 11 to 2 for a workspace build and from 26 to 4 when
building the tests.

A procedural macro can read the position or text of a token from another crate. In 1.99.0-18, Cargo
reruns rustc for a unit that observed such a span. An input can change after rustc reads it but
before Cargo records its checksum. The next warm build must pick up that edit even if the file still
has its original timestamp.

Rustc also tracks both ends of exported source spans. Moving a public `#[track_caller]` function
from column 1 to column 257 used to leave an incremental caller reporting column 1. The caller now
reports 257, as it does after a clean build. Moving a public identifier in a crate that emits both
Rust metadata and a native library also invalidates the downstream reader.

A procedural macro can return a span whose endpoint falls inside a multibyte UTF-8 character.
In 1.99.0-19, hashing that span as a string could make both `cargo check` and `cargo build`
panic. In 1.99.0-20, rustc hashes the selected bytes directly.
[Rust #259](https://github.com/astral-experiments/ohm-rust/pull/259)

In a paired Linux comparison on Ruff before 1.99.0-18, the earlier reuse policy reduced the median for an unchanged
`cargo test --no-run` from 6.09 to 0.96 seconds. All 619 units were fresh, eliminating 50 native
links. The ordinary workspace build was already fresh with either Cargo. Checking the inputs has a
cost when a macro observes a real change. In a seven-package fixture, moving the observed token
increased the median build from 346 to 485 milliseconds.

In a uv benchmark, we made a private change to uv's JSON parser in `uv-pypi-types`, then checked the
dependent `uv-client` crate, which took a median of 4.93 seconds without public API hashing and 2.16
seconds with it.

In a separate experiment, the compact metadata graph reduced the time to check Ruff after an edit by
3.0%.

See:

- [Rust #194](https://github.com/astral-sh/ohm-rust/pull/194)
- [Rust #201](https://github.com/astral-sh/ohm-rust/pull/201)
- [Rust #232](https://github.com/astral-sh/ohm-rust/pull/232)
- [Rust #233](https://github.com/astral-sh/ohm-rust/pull/233)
- [Cargo #254](https://github.com/astral-sh/ohm-cargo/pull/254)
- [Cargo #261](https://github.com/astral-sh/ohm-cargo/pull/261)
- [Rust #243](https://github.com/astral-sh/ohm-rust/pull/243)
- [Rust #245](https://github.com/astral-sh/ohm-rust/pull/245)
- [Ruff private doc edit](https://github.com/astral-sh/ohm-cargo/tree/2f07518331735487c84aaeadab58ce98d7c5a71b/benchmarks/ruff-dev-loop-20261027/native-qualified-results)
- [Ruff test builds](https://github.com/astral-sh/ohm-cargo/tree/d2fae69374cda17ef47ef198a75fdd24d690b34f/benchmarks/ruff-dev-loop-20261027/whole-ruff-cargo-observer-fifo)
- [Observed-token edit](https://github.com/astral-sh/ohm-cargo/tree/0c7fdaea22df8b42e67c1ccb6e12b92886c6cb2f/benchmarks/ruff-dev-loop-20261027/observer-fifo-seven-package-results)
- [Ruff native build measurements](https://github.com/astral-sh/ohm-cargo/tree/837a3a07a7368c1a3706ab2779b8ab3450814f7d/benchmarks/ruff-dev-loop-20261027/corrected-workspace-parser)
- [Rust #43](https://github.com/astral-sh/ohm-rust/pull/43)
- [Cargo #53](https://github.com/astral-sh/ohm-cargo/pull/53)
- [Cargo #55](https://github.com/astral-sh/ohm-cargo/pull/55)
- [Cargo #71](https://github.com/astral-sh/ohm-cargo/pull/71)

### 2. Relink executables without recompiling them

**Status:** Rust proposal, implemented in Ohm.

Ohm implements the [Relink, don't rebuild](https://github.com/rust-lang/compiler-team/issues/790)
approach for eligible executables and test binaries. When a dependency changes but the executable's
compiled code is still valid, Ohm reuses that code and reruns the linker to include the updated
dependency. Before relinking, Cargo verifies the list of link inputs and the contents of each
saved object file. If an input is missing or a checksum fails, Cargo recompiles the target.
Changes involving procedural macros, build scripts, or native libraries may also require
recompilation.

In 1.99.0-20, rustc keeps saved link objects separate from its incremental cache. Overwriting
a saved object can no longer change the cached copy through a hard link. If inline assembly reads
a file through `.incbin` or `.include`, rustc rebuilds the code that embeds it. Register-only
instructions, including the x86 atomics used by Ruff, can reuse the compiled code. A build script
can use `cargo::rerun-if-changed` to tell Cargo which native library or search directory to watch.
Cargo uses modification times for these declarations, as stock Cargo does.
[Rust #255](https://github.com/astral-experiments/ohm-rust/pull/255) · [Rust #267](https://github.com/astral-experiments/ohm-rust/pull/267) · [Rust #268](https://github.com/astral-experiments/ohm-rust/pull/268) · [Cargo #294](https://github.com/astral-experiments/ohm-cargo/pull/294)

In 1.99.0-23, a procedural macro stays fresh when one of its dependencies contains register-only
assembly. Previously, Cargo could recompile the macro and its consumers on every build. In the
release test, replacing a declared native library relinks both executables. Building again leaves
both executables fresh.
[Cargo change](https://github.com/astral-experiments/ohm-cargo/pull/424) · [Release test](https://github.com/astral-experiments/ohm/blob/4b0ec186008e6220f78776fda60e1cf9ad20e3eb/scripts/smoke-test-relink.sh)

On Linux, three successive unchanged builds of Ruff's CLI and integration tests invoked no
compiler or linker. Changing a declared static library relinked both executables. Restoring the
library reproduced both original executables byte for byte. [Release qualification](https://github.com/astral-experiments/ohm/pull/206)

In 1.99.0-21, rustc also recognizes register-only assembly in `libm`, `zeroize`, and `num-bigint`
on x86-64, and in `zmij` and `zlib-rs` on AArch64. On Linux, the first uv package test build
after an integration-test edit took 3.30 seconds, down from 9.96 seconds with a matched build of the
1.99.0-20 compiler. [x86-64 floating point](https://github.com/astral-experiments/ohm-rust/pull/270) · [x86-64 register instructions](https://github.com/astral-experiments/ohm-rust/pull/275) · [AArch64 vector instructions](https://github.com/astral-experiments/ohm-rust/pull/276) · [AArch64 CRC instructions](https://github.com/astral-experiments/ohm-rust/pull/277)

In 1.99.0-22, rustc recognizes the register-only instruction that `objc2` emits on Apple Silicon.
Cargo also recognizes the older native-link marker that rustc emits for `zmij`. In an Apple Silicon Ruff
replay, two unchanged binaries each needed a rustc check, but both skipped Xcode’s linker. In an earlier
Linux comparison, an unchanged ty check took 1.15 s with Cargo #330 and 0.39 s with #328.
[Compiler change](https://github.com/astral-experiments/ohm-rust/pull/281) · [Cargo reader](https://github.com/astral-experiments/ohm-cargo/pull/330) · [Native qualification](https://github.com/astral-experiments/ohm/actions/runs/41223789368)

When a build script links a static archive, it can declare the archive with `cargo::rerun-if-changed`.
A custom linker must declare any private files it reads through the build script, too. Cargo can then reuse
the executable while the recorded link inputs match. On Linux and macOS, two binaries skipped the linker on
an unchanged build. Replacing their archive relinked both, even with its original timestamp.
[Cargo change](https://github.com/astral-experiments/ohm-cargo/pull/382) · [Linux linker trace](https://github.com/astral-experiments/ohm/actions/runs/41302557061)

This helps most when an edit to a dependency would otherwise force an expensive executable or test
binary to recompile.

In the `linter` and `parser` example above, the linker combines their compiled code into the
`linter` executable. After the private parser fix, Ohm can link the rebuilt parser with the linter's
existing compiled code. The resulting executable includes the fix even though Ohm did not recompile
the linter's own code.

In a release benchmark, we changed a dependency, then rebuilt and ran a uv test. The median time for
the command fell from 26.27 to 3.79 seconds.

A cached relink already has a list of its Rust crate inputs. In 1.99.0-19, rustc waits until it
needs to look up a crate before it opens the library search directories. In an earlier uv
test-harness relink, this avoided 519 directory opens and produced a byte-for-byte identical
executable. Rustc used about 5% fewer instructions on two machines. The count covers rustc’s own
work before and after the native linker runs.

See:

- [Cargo #51](https://github.com/astral-sh/ohm-cargo/pull/51)
- [Cargo #52](https://github.com/astral-sh/ohm-cargo/pull/52)
- [Cargo #197](https://github.com/astral-sh/ohm-cargo/pull/197)
- [Cargo #198](https://github.com/astral-sh/ohm-cargo/pull/198)
- [Cargo #234](https://github.com/astral-sh/ohm-cargo/pull/234)
- [Cargo #236](https://github.com/astral-sh/ohm-cargo/pull/236)
- [Rust #252](https://github.com/astral-sh/ohm-rust/pull/252)

### 3. Reuse builds during checks

**Status:** New optimization.

A build already produces some of the information that `cargo check` and Clippy need. Ohm can reuse
results from compatible builds of libraries, binaries, and tests after checking that the compiler,
build inputs, and saved files are compatible. Ohm also replays cached warnings and keeps earlier
check results when you build tests, so switching between testing and checking can reuse work from
both.

In 1.99.0-22, Cargo reruns a check if its saved outputs are incomplete. Previously, after you fixed
a type error, a successful check could still print the old error. [Cargo #305](https://github.com/astral-experiments/ohm-cargo/pull/305)

For example, suppose you run `cargo +ohm build`, then `cargo +ohm check` in the same workspace. The
build has already checked and compiled a dependency such as `memchr`. If its inputs still match, Ohm
can use the metadata from that build instead of checking `memchr` again. Similarly, after
`cargo +ohm build --bin parser`, a subsequent `cargo +ohm check --bin parser` can reuse the build
results if the inputs still match. If you check, build, and then check again, Ohm can also reuse
the first check's results.

If a single compiler invocation would see both a native and a checked copy of the same library,
Cargo checks the dependencies that would introduce the conflicting copy. Other roots and host
procedural macros can still reuse their native artifacts. On Ruff, `cargo check --workspace` used
to fail after a workspace build because rustc saw two copies of `pep440_rs`. With this change,
the check succeeds and all 520 units are fresh on the next check.

After a build script changes, Cargo uses the timestamp of its validated result when restoring
unchanged compiler metadata. Using the older timestamp on the script's stdout made the next
`cargo check` recompile `ruff`, `ty`, and `ty_wasm` even though none of their inputs had changed.
With the fix, all 520 units were fresh and the median for that unchanged check fell from 1.00 s to
0.62 s. Across 24 paired trials, the edited check and the following unchanged check together took
16.8% less time. The edited check alone had no clear timing difference.

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
- [Cargo #253](https://github.com/astral-sh/ohm-cargo/pull/253)
- [Cargo #256 and the build-script timestamp measurements](https://github.com/astral-sh/ohm-cargo/pull/256)
- [Ruff build followed by check](https://github.com/astral-sh/ohm-cargo/tree/0abc9677ba9cfa1a0525cbab6597e329a42eaa9e/benchmarks/ruff-dev-loop-20261027/consistent-native-check)

### 4. Reuse checks during builds

**Status:** New optimization, enabled by default for eligible debug builds.

A native build repeats type checking and borrow checking that a preceding `cargo check` may have
already done. Ohm saves the results of a check and reuses them in compatible builds. It also keeps
the build's generated objects for later incremental builds.

For example, after checking a parser change, you can build the parser and reuse some of the work
from that check. Release builds, test targets, procedural macros, build scripts, and unsupported
compiler configurations retain ordinary behavior. The extra checkpoints consume disk space. Use
`-Zohm-shared-stages=no` on both commands to opt out.

In 1.99.0-23, Ohm discards a shared checkpoint if it contains an invalid node. Rustc falls back
to the ordinary incremental graph if it can read it. If both graphs are damaged, it starts a fresh
compilation.
[Rust #338](https://github.com/astral-experiments/ohm-rust/pull/338)

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

Each worktree keeps its incremental compiler state, documentation, scratch files, and final
outputs in its own target directory. The shared build directory holds eligible registry artifacts
and reusable ThinLTO objects. Additional trust settings allow reuse of procedural macros and
native tools, but that reuse can be unsound.

For example, suppose you build your project on `main`, then build a fix in a second worktree. Both
worktrees use the same version of `memchr` with the same features and build settings. If they share
a build directory, Ohm can reuse the compiled `memchr` from the first worktree in the second.

If you turn off Ohm's defaults, both worktrees can still point to the same external build directory.
As long as each has its own target directory, Cargo keeps their intermediate files separate. Each
worktree's build scripts get their own `OUT_DIR`, and running `cargo clean` in one worktree
preserves the other's files.

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

Cargo records which worktrees it has seeded in a generated marker file. In 1.99.0-18, if that marker
was a symlink, even a fully fresh build could write through it to an unrelated file. Starting in
1.99.0-19, Cargo replaces the marker at its own path. The file the symlink pointed to keeps its
original contents.

In 1.99.0-20, Cargo also replaces symlinks when it writes the workspace resolution, public API
hash, compiler-message, and integration-test cache entries. A restored resolution cache entry
that points to a pipe used to hang `cargo metadata --offline`. Cargo now resolves the workspace again.
[Cargo #284](https://github.com/astral-experiments/ohm-cargo/pull/284)

See:

- [Cargo #101](https://github.com/astral-sh/ohm-cargo/pull/101)
- [Cargo #126](https://github.com/astral-sh/ohm-cargo/pull/126)
- [Rust #91](https://github.com/astral-sh/ohm-rust/pull/91)
- [Cargo #274](https://github.com/astral-sh/ohm-cargo/pull/274)

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

Starting in 1.99.0-20, Cargo rechecks callers while a dependency's metadata is still provisional.
Previously, an edit that introduced a second method with the same name could pass an incremental
check even though a clean check reported an ambiguous call. If a library fails after a dependent
uses its metadata, reverting the edit also rebuilds that dependent on the first retry.
[Cargo #279](https://github.com/astral-experiments/ohm-cargo/pull/279) · [Cargo #280](https://github.com/astral-experiments/ohm-cargo/pull/280)

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

If the library has already finished, Cargo compiles the integration test against it immediately. An
earlier version could compile and link the same test twice. In a paired comparison on Ruff, removing
that duplicate invocation cut the median first workspace test build after a test-source edit from
12.60 to 11.16 seconds.

See:

- [Cargo #146](https://github.com/astral-sh/ohm-cargo/pull/146)
- [Cargo #147](https://github.com/astral-sh/ohm-cargo/pull/147)
- [Cargo #260](https://github.com/astral-sh/ohm-cargo/pull/260)

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

`cargo clean` removes the selected project's private state. Removing a worktree also removes its
default target directory, but a target directory outside the checkout can remain on disk.

On Linux and macOS, `cargo +ohm gc` can reclaim build outputs in idle target directories as well
as unused shared dependencies, compiler caches, and ThinLTO objects. By default, Cargo waits at
least an hour after a target's last use. Builds, checks, and `cargo +ohm worktree add` all count
as uses. After an upgrade, Cargo can remove obsolete compiler intermediates immediately.

For example, run `cargo +ohm gc --max-age 2d --dry-run` to see how much space you could reclaim
from builds last used at least two days ago. Omit `--dry-run` to remove the eligible files. If an
active build holds a lock, Cargo skips that part of the cleanup and continues elsewhere. Use `-v`
to see which lock it encountered.

Since 1.99.0-22, the Linux collector stops at mount boundaries inside target directories and the shared
cache. This keeps garbage collection from deleting files reached through a bind mount.
[Shared cache](https://github.com/astral-experiments/ohm-cargo/pull/306) · [Private targets](https://github.com/astral-experiments/ohm-cargo/pull/308)

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

The linker combines compiled code into the final executable. On native x86-64 Linux GNU builds,
Ohm uses Wild unless you choose a different linker. Wild reads archive members in parallel and
uses up to 32 threads by default.

Wild performs a full link each time it runs. After a dependency changes, Ohm can pass saved
object files to Wild. It can also reuse an integration test executable if the test does not
link the changed dependency. If the output file has another hard link, Wild replaces the file
at the output path so the other link still opens the previous executable.

See:

- [Cargo #114](https://github.com/astral-sh/ohm-cargo/pull/114)
- [Cargo #139](https://github.com/astral-sh/ohm-cargo/pull/139)
- [Ohm #112](https://github.com/astral-sh/ohm/pull/112)
- [Ohm #181](https://github.com/astral-sh/ohm/pull/181)

### 15. Avoid repeated Cargo preparation work

**Status:** New optimization.

Cargo resolves the workspace's dependencies before many commands. Ohm saves that result and reuses
it when the manifests, lockfile, configuration, and toolchain have not changed. Cargo still resolves
the packages and features needed by the current command.

For example, fixing a bug in `parse_number` leaves the workspace's dependency versions unchanged.
The next check can reuse the saved resolution. Adding a dependency to `Cargo.toml` invalidates it,
so Cargo resolves the dependencies again.

Cargo shares inherited dependency declarations across workspace members. On Unix, it also caches
parsed registry manifests in Cargo home. If two projects use the same published crate, the second
can reuse the manifest parsed by the first. Cargo checks that the contents and parser version
match. On a cache miss, it parses the TOML and reports errors against the original file.

Ohm avoids repeated filesystem checks and skips work the command doesn't need, such as initializing
Git or generating a software bill of materials. On Unix, when Cargo needs at least 128 uncached
checksums to tell whether a build is up to date, it can hash the source files in parallel. It uses
up to four of the build's job slots and releases them before running compilers or build scripts.

Rustc hashes each input using its original filename. It escapes spaces when it writes the
dependency file. On Ohm 1.99.0-16, if both `input space` and `input\ space` existed, rustc could
compile the first file but hash the second. Cargo could then reuse an executable after its input
had changed. If two Unix filenames have the same spelling in the dependency file, rustc now omits
the ambiguous checksum. On upgrade, Cargo rebuilds units whose old records could have lost the
original filename. Later builds can reuse the corrected records.

Cargo avoids parsing the same registry URL for every package in a lockfile and copying workspace
lint tables that a member does not inherit. It also caches registry manifest warnings alongside
the parsed manifest. When a build script needs a list of package files, Cargo can recognize a Git
index it has already verified. It still walks the working tree, so new untracked files are visible.

Cargo checks explicit workspace members only when they can override an exclusion. Codex lists 165
workspace members and no exclusions. Skipping that scan reduced Cargo’s instruction count by 7.38%
on a warm workspace check and 16.80% on a check of `codex-utils-string`. These measurements count
instructions in Cargo itself.

When it writes a Make dependency file, Cargo collects the input paths directly. It sorts them once
and removes duplicates, preserving the first spelling of equivalent paths.

On a Ruff workspace with all 520 artifacts up to date, the ten Cargo changes together reduced
Cargo's instructions for `cargo check` by 10.51%.
[Paired measurements](https://github.com/astral-sh/ohm-cargo/tree/60f815537745e8dd8867c3062aea061c6865be34/benchmarks/ruff-dev-loop-20261026/ten-cargo-fresh)

In 1.99.0-20, Cargo can reuse the selected dependency versions after edits to workspace Rust or
Clippy lints and after edits confined to trailing profile tables. It still applies the new lint or
profile settings. In Ruff, editing an inactive profile cut a warm package build from 190 to 63 ms.
On a larger parser test build, the unchanged repeat after restoring the manifest was 3.75% slower.
In a separate test on a second host, a lint edit and its first repeat took 18.42% less time when
building Ruff's serde tests. [Profile edits](https://github.com/astral-experiments/ohm-cargo/pull/286) · [Lint edits](https://github.com/astral-experiments/ohm-cargo/pull/288)

Cargo also reuses the lockfile bytes it just encoded when it records the workspace resolution.
In a Ruff dependency edit, Cargo executed 7.77% fewer instructions. The wall-time measurements
could not establish a speedup. [Cargo #287](https://github.com/astral-experiments/ohm-cargo/pull/287)

In an earlier experiment on a Codex workspace that had already been built, reusing the dependency
resolution reduced `cargo metadata` time from 413 to 358 milliseconds and Nextest time from 961 to
824 milliseconds.

In a warm Ruff experiment, skipping unnecessary dependency-file generation reduced unchanged
workspace checks by 18.2% and test builds by 20.2%. A separate change to output preparation and
dependency-file parsing reduced unchanged workspace builds by 13.8%.

In a warm Ruff workspace with eight jobs, parallel hashing reduced the time for an unchanged
`cargo test --workspace --no-run` by 5.6%.

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
- [Cargo #242](https://github.com/astral-sh/ohm-cargo/pull/242)
- [Cargo #243](https://github.com/astral-sh/ohm-cargo/pull/243)
- [Cargo #244](https://github.com/astral-sh/ohm-cargo/pull/244)
- [Cargo #262](https://github.com/astral-sh/ohm-cargo/pull/262)
- [Cargo #263](https://github.com/astral-sh/ohm-cargo/pull/263)
- [Cargo #245](https://github.com/astral-sh/ohm-cargo/pull/245)
- [Cargo #246](https://github.com/astral-sh/ohm-cargo/pull/246)
- [Cargo #247](https://github.com/astral-sh/ohm-cargo/pull/247)
- [Cargo #248](https://github.com/astral-sh/ohm-cargo/pull/248)
- [Cargo #249](https://github.com/astral-sh/ohm-cargo/pull/249)
- [Cargo #250](https://github.com/astral-sh/ohm-cargo/pull/250)
- [Cargo #258](https://github.com/astral-sh/ohm-cargo/pull/258)
- [Rust #241](https://github.com/astral-sh/ohm-rust/pull/241)

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

For incremental debug checks on x86-64 Linux, Cargo uses one frontend thread for small workspace
crates. It uses the previous successful check's dependency file to identify them. The first check
keeps the usual thread count, as do larger crates. Explicit compiler flags take precedence. After
a small edit to Ruff's lexer, this reduced the time for the full workspace check by 3.20%.

For example, a build may reach a large parser crate after all its dependencies have finished. Even
if Cargo has no other crates ready to compile, the compiler can check independent function bodies in
the parser on several threads. In a native build, one thread can also start encoding the parser's
metadata while another works out which symbols it exports.

In an experiment, we changed only the frontend thread setting and ran development sessions for Ruff,
uv, and Codex. Their combined time fell from 1,032 to 720 seconds, about 30%.

See:

- [Cargo #90](https://github.com/astral-sh/ohm-cargo/pull/90)
- [Cargo #251](https://github.com/astral-sh/ohm-cargo/pull/251)
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

On the built-in x86-64 and AArch64 GNU Linux targets, 1.99.0-22 also handles crates that mix
ordinary Rust code with assembly that may read a file. Rustc recompiles the LLVM units that can
read the file. When the compiler uses LLVM with LTO off, the other units can keep their object code. In a GNU AArch64 cross-build of `ruff_python_ast`, a source
edit regenerated two of 95 units. Its first repeat regenerated one. The edit and repeat took
8.24 s with the -22 compiler changes and Cargo #328, down from 12.23 s with -21 across six matched
pairs. [Compiler change](https://github.com/astral-experiments/ohm-rust/pull/280) · [Source comparison](https://github.com/astral-experiments/ohm/pull/223)

In 1.99.0-23, rustc recognizes more assembly that reads no files. On GNU AArch64 this includes
register-only comments, literal Linux system calls and the atomic loops used by Ruff. Across two
Linux hosts, a Ruff CLI edit and its first repeat took 9.95 s with these changes, down from 25.09 s.
On x86-64 musl, recognizing two register-only comments cut a Ruff parser edit and its first repeat
from 1.89 s to 0.83 s. Both comparisons used eight paired trials.
[GNU AArch64 timings](https://github.com/astral-experiments/ohm/actions/runs/41343305124) · [x86-64 musl timings](https://github.com/astral-experiments/ohm/actions/runs/41342471218)

Rustc also invalidates cached metadata when a private item’s native export name changes. An incremental
build could previously use the old symbol or panic. [Rust #300](https://github.com/astral-experiments/ohm-rust/pull/300)

Ohm also reuses part of the metadata it has already encoded when its inputs have not changed. This
includes source-written exported macros when their text and source locations match. Generated macros
or changed locations require fresh encoding; `-Zohm-metadata-macro-reuse=no` disables this metadata
reuse for macros. If an incremental query cache cannot be loaded, Ohm discards the matching
dependency graph and recomputes it.

For example, suppose a test binary calls `parse::<u32>` and `parse::<u64>`. Changing an error
message in one test may leave both generated versions of `parse` and their dependencies unchanged.
Ohm can reuse its previous decisions about which compilation group contains each version, while
still compiling the edited test.

When rustc loads an unchanged query result from disk, it can keep the encoded bytes for the next
build. If it recomputes the result, it saves the new value even when its fingerprint matches the
old one. That matters when an edit moves the line an error points to without changing anything
else about the result. When replacing its private query cache and dependency graph, rustc unlinks
the old files first. On ext4 this can avoid waiting for writes to files it is about to discard.

In a Codex TUI experiment, we repeatedly made and reverted one edit, then rebuilt the test binary.
Reusing the compiler's grouping decisions reduced average code generation time from 8.67 to 7.06
seconds.

In one uv comparison from the same starting state, retaining query results reduced an edited test
from 18.96 to 15.49 seconds. Including the preceding compiler refresh, the cycle fell from 24.53 to
20.80 seconds.

In an edit-and-rebuild experiment at optimization level 1, splitting reduced times by 32.8% for ty
and 45.8% for uv. Splitting also made ty's tests about 3–4% slower and increased uv's cold-build
time by 5.7% in separate comparisons.

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

When laying out async state, Ohm skips redundant work when tracking which values are live at the
same time. This backports a change from
[rust-lang/rust #163126](https://github.com/rust-lang/rust/pull/163126). On Unix, Ohm also reduces
peak memory use by keeping a read-only mapping of an incremental query cache while rewriting it,
instead of copying the retained data into memory.

For example, a generic type `Container<T>` might require `T: Clone`. When checking a use of that
type, the compiler gathers the bounds that apply to it. Ohm gathers those bounds in one walk through
their declarations, avoiding a second walk and temporary lists.

Similarly, when checking an opaque return type such as `impl Iterator`, rustc can reuse its
declared bounds each time it compares two lifetimes. When looking for implementations of a trait,
it skips crates whose metadata lists none for that trait.

Starting in 1.99.0-23, rustc can reuse a trait lookup after an unrelated implementation changes.
This also applies to primitive types and small tuples. Across 12 paired trials on Linux, the
median first check of uv’s resolver after a workspace edit fell from 2.88 s to 1.33 s with the
two changes. Cargo rebuilt the same crates in both cases.
[Trait lookup](https://github.com/astral-experiments/ohm-rust/pull/296) · [Primitive types and tuples](https://github.com/astral-experiments/ohm-rust/pull/306) · [Qualification](https://github.com/astral-experiments/ohm/actions/runs/41327099284)

When a node has no attributes, the early lint visitor can keep using the enclosing lint settings.
Rustc also walks the packed dependency indexes from the previous build without updating a separate
count at every edge. In separate experiments on an edit to Ruff's parser, these changes reduced
instructions across Cargo and rustc by 0.45% and 0.50%, respectively.

Every generated Rust test imports the `test` crate. Once rustc has resolved that name, it can
reuse the result for the remaining tests in the same compilation.

Compiler workers allocate caches for trait bounds and function signatures on first use. A query
can also reuse the buffer that an earlier query used to record its dependencies. Keeping those
buffers available saves allocations but can increase memory use.

In an experiment, the simpler checks of type constraints reduced the time to check Ruff's
`ty_python_semantic` crate by about 4%. In a separate experiment, the changes to code generation in
development builds reduced `uv-resolver` compilation time by about 8–9%.

In another experiment, the lookup and data-structure changes, together with Cargo's filesystem
caches, reduced total rebuild time across 13 uv development commits from 478.19 to 446.97 seconds,
or 6.5%. Focused Ruff measurements of the query-cache change saved about 36 MiB during a check and
114 MiB during a build, with no consistent wall-time improvement.

Rustc checks command-line tool lints in each module. A workspace can enable Clippy lints even when
Clippy is absent. To decide which diagnostic to issue, rustc used to scan every registered lint
name. In 1.99.0-19, it records the tool prefixes when it registers those names and can answer with
one lookup. With an earlier stage-1 compiler, editing Ruff and running `cargo check -p ruff` took
2.16% less wall time across 64 pairs.

A test binary can also depend on hundreds of crates whose generic symbols the linker does not need
to retain. Rustc now records one bit in each crate’s metadata indicating whether any of its symbols
needs special treatment in a C-level link. A test-harness compile for uv decoded one local list and
read 479 summary bits. On the earlier compiler, rustc executed about half as many instructions in
that compile. The whole-command timing was inconclusive.

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
- [Rust #230](https://github.com/astral-sh/ohm-rust/pull/230)
- [Rust #231](https://github.com/astral-sh/ohm-rust/pull/231)
- [Rust #250](https://github.com/astral-sh/ohm-rust/pull/250)
- [Rust #251](https://github.com/astral-sh/ohm-rust/pull/251)

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

Starting in 1.99.0-18, rustc runs native derive and attribute macros on every compilation. A derive
macro can call a C helper. In one reproducer, changing the helper’s return value from `17` to `29`
rebuilt the macro and its consumer, but the warm executable still printed `17`. The first warm build
with -18 prints `29`. Rustc still accepts `-Zcache-proc-macros` for compatibility and keeps
expansion caching off.

In 1.99.0-21, inserting a line above an unchanged derive can preserve the compiler’s work on the
methods it generates. Rustc identifies the derive relative to a nearby struct, enum, or union in
the same source file. The macro runs and sees the new line number. Rustc can then reuse type and
borrow checking for the generated methods. On a 13-byte edit in uv, this change cut the median
`uv-cli` check from 12.53 s to 12.04 s across 12 paired runs. Checking the full `uv` binary went
from 3.12 s to 3.09 s. Both comparisons used source builds of the release stack with and without
the change. [Derive spans](https://github.com/astral-experiments/ohm-rust/pull/278) · [Linux timings](https://github.com/astral-experiments/ohm-rust/actions/runs/41084366039)

Earlier releases cached the code generated by macros such as `#[derive(serde::Serialize)]`. To reuse
an expansion, rustc had to restore generated source files and syntax contexts in the same order as a
fresh expansion. In 1.99.0-16, mixing artifacts from different cache histories caused six of 28
downstream builds in one reproducer to fail with `E0460`.

In an earlier uv benchmark, editing a private parser, checking its dependent crate and running the
parser tests took a median of 4.02 seconds with expansion caching and 4.15 seconds without it.
Cargo’s trust settings for reusing compiled macros across worktrees control a separate cache.

See:

- [Cargo #54](https://github.com/astral-sh/ohm-cargo/pull/54)
- [Rust #208](https://github.com/astral-sh/ohm-rust/pull/208)
- [Rust #238](https://github.com/astral-sh/ohm-rust/pull/238)
- [Rust #244](https://github.com/astral-sh/ohm-rust/pull/244)
- [Cargo #261](https://github.com/astral-sh/ohm-cargo/pull/261)
- [Downstream build reproducer on 1.99.0-16](https://github.com/astral-sh/ohm-cargo/tree/db71638cbb6dda4752d51ca6373e234811dff18f/benchmarks/ruff-dev-loop-20261027/shipping-16-macro-results)

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

## Documentation tests

### 28. Cache inline doctests

In Ohm 1.99.0-23, `cargo test --doc` caches supported examples in Rust 2024 libraries when
testing for the host platform. Cargo can reuse the extracted examples and compiled object
files on a warm run. It still runs every selected example and repeats the final link to pick
up changes to native archives. An edit to an example or its included Markdown invalidates the cache.

Rustdoc handles libraries with `compile_fail` examples, custom rustdoc flags, or unsupported
test arguments. Use `-Zohm-cached-doctests=no` to run eligible examples through rustdoc as well.

On 16 Ruff crates, caching reduced median warm doctest time from 19.171 s to 1.425 s across
five alternating pairs. Both modes passed 207 examples and ignored nine. This comparison used
the patched Cargo with the released Ohm 1.99.0-22 compiler.
[Cargo #429](https://github.com/astral-experiments/ohm-cargo/pull/429)
