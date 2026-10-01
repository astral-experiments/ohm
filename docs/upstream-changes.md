# Changes from upstream

Ohm combines experimental Rust, Cargo, Clippy, and rustfmt changes for local development.
Each release pins the complete set of sources in its [toolchain manifest](../toolchains/).
Use the official Rust toolchain for production builds and final validation.

## In Ohm 1.99.0-1

This release updates Rust, Cargo, Clippy, and rustfmt to Rust 1.99.0 while retaining the
features shipped in Ohm 1.98.1-5. The existing component PRs have been rebased onto the
new upstream sources. See the [pinned manifest](../toolchains/1.99.0/1.json) for exact revisions.

Bundled upstream Wild remains the default linker for native x86_64 Linux GNU builds,
including the shared-cache fix. The allocator changes, indexed Cargo scheduling, line-table
debug information, and clone-only worktree seeds are retained. Both distributions include
rust-src, the rust-analyzer procedural-macro server, and the Wasm standard library and linker.

The Clippy/codegen shared-cache experiment, ohm-wild fork, and Mach-O linker remain excluded.

## In Ohm 1.98.1-2

- **Line-table debug information by default.** Development and test builds retain file-and-line
  backtraces while omitting interactive debugger type and variable information. Explicit profile,
  Cargo configuration, environment, and package overrides keep their normal precedence. Set
  `[profile.dev] debug = true` for full debug information. [Cargo #127](https://github.com/astral-sh/ohm-cargo/pull/127)
- **Clone-only worktree seeds.** Build state is imported only when the filesystem can clone every
  snapshot file. A profile that cannot be cloned builds normally without a seed; ordinary I/O errors
  still surface. [Cargo #126](https://github.com/astral-sh/ohm-cargo/pull/126)
- **Reuse after moving async code.** Coroutine code generation no longer depends on debug names
  and source locations. `-Zdebug-info-type-line-numbers=true` restores coroutine state declaration
  locations when needed. [Rust #132](https://github.com/astral-sh/ohm-rust/pull/132)

This release uses upstream Rust 1.98.1. Clippy, rustfmt, and bundled Wild retain their revision-1 pins.
The [benchmarks](../BENCHMARKS.md) compare the complete release with stock Rust; they do not isolate
these changes from previous Ohm releases.

## Incremental builds

Public API hashes avoid rebuilding dependents when an edit leaves their relevant interface unchanged.
Cached relinking reuses generated code when only the final executable needs to change. Ohm also reuses
compatible generic-function partitions, metadata, and compiler query results across edits.

Cargo reuses compiled dependencies across builds, checks, tests, and Clippy. It preserves check graphs
across test builds, avoids relinking unaffected integration tests, and skips redundant dependency
resolution. Procedural-macro caching reuses expansions subject to the configured trust policy.

## Worktrees and disk usage

Shared registry artifacts live in a separate build directory; each worktree keeps its own target
directory. Fine-grained locks coordinate concurrent builds. `cargo +ohm worktree add` seeds compatible
workspace and incremental state using filesystem clones, then revalidates source and build inputs.
Matching Clippy state stays separate from reusable build and test state.

The compiler reduces sparse metadata, retires superseded incremental sessions, and reuses stable
paths for retained debug objects. Optional `-Zohm-incremental-gc` tracking allows age-based collection
with `cargo -Zohm-incremental-gc clean incremental --max-age '30 days'`; tracking is disabled by default.

See the [usage guidance](../README.md#usage) for target-directory layout, trust settings, and worktree
commands.

## Compiler and tools

Ohm enables parallel compiler frontends and reduces repeated work in trait selection, type folding,
borrow checking, metadata handling, and dependency scheduling. Clippy can replay eligible diagnostics
for unchanged modules; rustfmt can skip unchanged packages and format individual changed modules.

Release compilers use PGO, with BOLT on Linux, and component PGO where supported. Native x86_64 Linux
GNU builds use bundled upstream Wild for full linking; explicit linker settings take precedence.
`-Zohm-linker=lld` selects LLD. `-Zohm-defaults=no` disables Cargo's automatic experimental defaults.
See [release documentation](releases.md) for the build and packaging details.

## Included patches

Generate the exact component commit inventory from any pinned manifest:

```console
python3 scripts/list_patches.py toolchains/1.99.0/1.json
```

The command uses `gh-auto` to compare each pinned component with the corresponding revision in the
upstream Rust release. It prints commit links in source-history order, including setup and CI changes.
This avoids maintaining a second list of release contents as PR titles and branches change.

The parsed-lockfile-cache, recent-type-fold, and prefix-cloning experiments remain excluded. The
combined Clippy/codegen experiment also remains excluded; use standalone `cargo +ohm clippy`.
The experimental ohm-wild fork and Mach-O linker are not packaged.
