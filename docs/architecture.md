# Architecture

Ohm is an alternative Rust toolchain for development-only iteration. It ships a matching Rust
compiler, Cargo, Clippy, rustfmt, and sysroot as a custom rustup toolchain. Selecting `cargo +ohm`
uses those binaries without replacing the default Rust toolchain.

## Source repositories

- [`astral-sh/ohm-rust`](https://github.com/astral-sh/ohm-rust) contains the compiler, standard
  library, bootstrap configuration, and vendored tools.
- [`astral-sh/ohm-cargo`](https://github.com/astral-sh/ohm-cargo) contains the corresponding Cargo
  changes and is pinned by the Rust repository's `src/tools/cargo` gitlink.
- [`astral-sh/ohm-rust-clippy`](https://github.com/astral-sh/ohm-rust-clippy) contains the Clippy
  revision overlaid onto Rust's vendored Clippy source during a release build.
- [`astral-sh/ohm-rustfmt`](https://github.com/astral-sh/ohm-rustfmt) contains the rustfmt revision
  overlaid onto Rust's vendored rustfmt source during a release build.

This coordinator records exact Rust, Cargo, Clippy, and rustfmt commits in an immutable release
manifest. Source repositories retain an `upstream-<rust-version>` branch for upstream Rust and an
`ohm-<rust-version>` branch for Ohm changes.

## Incremental compilation

See [How Ohm speeds up development](optimizations.md) for the changes to Cargo and rustc.
Reusing build output can be unsound. For example, if a procedural macro reads an input its cache
does not track, the compiler can reuse a stale expansion.

Use Ohm only for local iteration, never for production builds, releases, CI correctness validation,
or final test results. Use the normal Rust toolchain as the authoritative source of truth. Ohm's
bundled defaults can be disabled for a local comparison:

```console
cargo +ohm -Zohm-defaults=no test
```

## Release identity

Toolchains are named `ohm-<rust-version>-<ohm-revision>`. Each release is described by
`toolchains/<rust-version>/<ohm-revision>.json`, using the
[`manifest schema`](../toolchains/manifest.schema.json).

A manifest starts as a draft and becomes pinned when its Rust, Cargo, Clippy, and rustfmt revisions
are finalized. Only compatible pinned manifests can be released. Source revisions can be updated
until the release is published; afterward, its release identity and source pins are immutable.
Publishing another revision requires a new manifest.
