# How Ohm speeds up development

Ohm includes the following changes to Rust, Cargo, Clippy, and rustfmt.

## Cargo and builds

### 1. Avoid rebuilding dependents after private changes

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
the test command fell from 26.27 to 3.79 seconds for uv (about 7×) and from 57.81 to 5.20 seconds
for Codex (about 11×). These comparisons include public API hashing and Ohm's other changes, so they
don't measure the effect of relinking alone.

See:

- [Cargo #51](https://github.com/astral-sh/ohm-cargo/pull/51)
- [Cargo #52](https://github.com/astral-sh/ohm-cargo/pull/52)

### 3. Reuse builds during checks

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

See:

- [Cargo #75](https://github.com/astral-sh/ohm-cargo/pull/75)
- [Cargo #91](https://github.com/astral-sh/ohm-cargo/pull/91)
- [Cargo #89](https://github.com/astral-sh/ohm-cargo/pull/89)

### 4. Share compiled dependencies across worktrees

Set `CARGO_BUILD_BUILD_DIR` to the same directory across projects or worktrees to let Ohm share
their compiled registry dependencies. Cargo verifies that the package, compiler, configuration, and
build inputs match before it reuses a dependency, and uses locks to coordinate concurrent builds.

Each worktree keeps its own workspace artifacts and final outputs in its target directory. We also
include additional "trust" settings to allow for reuse of procedural macros and native tools, but
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

### 5. Seed new worktrees from an existing build

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

### 6. Start checking dependent crates earlier

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

### 7. Reuse integration tests that do not use a changed library

Ruff has an integration test that runs `ruff config lint.select` and checks its output. Cargo builds
two programs for this test: the `ruff` executable and a test executable that launches it. Only the
`ruff` executable includes Ruff's library code.

When you edit Ruff's library, Ohm updates the `ruff` executable and reuses the test executable. The
test still runs and checks the updated program's output. Before reusing a test executable, Ohm
verifies that it does not link the changed library, either directly or through another dependency.

In a Ruff experiment, the time to rebuild and run tests after an edit to the package's library fell
from 8.26 to 5.14 seconds. After an edit to another unused workspace library, it fell from 7.20 to
4.41 seconds.

See:

- [Cargo #72](https://github.com/astral-sh/ohm-cargo/pull/72)
- [Cargo #73](https://github.com/astral-sh/ohm-cargo/pull/73)

### 8. Reduce build artifact disk usage

Ohm removes old incremental snapshots once newer ones replace them. It also keeps the names of
retained debug object files stable, so rebuilds replace those files instead of leaving old copies
behind. Ohm stores compiler metadata more compactly and avoids storing duplicate metadata in
eligible registry and Git libraries.

For example, after an edit and rebuild, a new incremental snapshot can replace the previous one. Ohm
removes that superseded snapshot, so repeated edits do not leave a growing collection of old
snapshots for the same build.

In a macOS benchmark, we ran the same development tasks with Ohm and stock Rust. Ohm used 40% less
disk space for Ruff and 35% less for uv. These savings include the effects of Ohm's build reuse and
default debug settings.

See:

- [Cargo #68](https://github.com/astral-sh/ohm-cargo/pull/68)
- [Rust #97](https://github.com/astral-sh/ohm-rust/pull/97)
- [Rust #98](https://github.com/astral-sh/ohm-rust/pull/98)
- [Rust #123](https://github.com/astral-sh/ohm-rust/pull/123)

### 9. Use line tables by default

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

(This is an existing stable Rust feature; Ohm makes it the default for development and test builds
to speed up development out of the box.)

See:

- [Cargo #127](https://github.com/astral-sh/ohm-cargo/pull/127)

### 10. Use Wild for Linux linking

The linker combines compiled code into the final executable. For native x86-64 Linux GNU builds, Ohm
uses the Wild linker by default. Explicit linker settings still take precedence.

Wild performs a full link each time it runs. Cached relinking lets Ohm reuse the compiled code that
it passes to the linker. The release benchmarks include Wild alongside Ohm's other changes, so they
do not measure its contribution separately.

(Wild is an existing linker; Ohm bundles it and enables it by default on supported Linux targets.)

See:

- [Cargo #114](https://github.com/astral-sh/ohm-cargo/pull/114)
- [Ohm #112](https://github.com/astral-sh/ohm/pull/112)

### 11. Reuse Cargo's dependency resolution

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

## rustfmt

### 12. Format only what changed

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

### 13. Run the compiler frontend in parallel

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

(This is an existing, experimental Rust compiler feature; Ohm enables it by default to speed up
development out of the box.)

See:

- [Cargo #90](https://github.com/astral-sh/ohm-cargo/pull/90)
- [Cargo #48](https://github.com/astral-sh/ohm-cargo/pull/48)

### 14. Reuse compiler work across incremental builds

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

### 15. Reuse async code after it moves

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

### 16. Optimize the compiler and its allocator

Ohm builds its release compiler with profile-guided optimization (PGO). It runs a training workload,
then uses the resulting profile to optimize the compiler's machine code. Ohm also applies PGO to
Cargo, rustdoc, Clippy, and rustfmt. Linux releases use BOLT to further optimize the compiled
binary.

(PGO and BOLT are existing compiler optimizations; Ohm applies them when building its release
toolchain.)

See:

- [Ohm #60](https://github.com/astral-sh/ohm/pull/60)
- [Rust #67](https://github.com/astral-sh/ohm-rust/pull/67)

Ohm also changes the memory allocator used by two of its tools:

- On Linux, the Rust compiler (`rustc`) uses mimalloc.
- On Apple Silicon macOS, Cargo uses mimalloc.

This changes how those tools allocate and free memory while they run.

In an earlier Linux benchmark, switching to mimalloc reduced a Ruff check by 5.3%, a uv rebuild by
9.8%, and a uv edit-and-test command by 7.8%. Some compiler workloads used 21–25% more memory at
their peak.

In a macOS comparison, running a check on unchanged Ruff sources took 216 milliseconds before the
allocator change and 199 milliseconds after it. Running a build on unchanged uv sources took 296 and
267 milliseconds, respectively.

See:

- [Rust #109](https://github.com/astral-sh/ohm-rust/pull/109)
- [Cargo #106](https://github.com/astral-sh/ohm-cargo/pull/106)

### 17. Reduce repeated compiler work

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

### 18. Avoid generating async bodies for metadata

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

### 19. Cache derive macro expansions

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

(This is an existing, experimental Rust compiler feature; Ohm enables it by default to speed up
development out of the box.)

See:

- [Cargo #54](https://github.com/astral-sh/ohm-cargo/pull/54)

## Clippy

### 20. Reuse Clippy results for unchanged modules

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
