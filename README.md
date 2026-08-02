# Ohm

[![CI](https://github.com/astral-sh/ohm/actions/workflows/ci.yml/badge.svg)](https://github.com/astral-sh/ohm/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue.svg)](#license)

An alternative Rust toolchain for faster development-only iteration.

**Experimental:** Ohm backports and pulls forward Rust and Cargo performance optimizations that may
be unsound. Use it only for local development, at your own risk.

- Reduces dependency rebuilds and reuses code generation between incremental Rust builds.
- Includes matching Cargo, Clippy, rustfmt, and compiler binaries in a single rustup toolchain.
- Keeps the project's normal Rust toolchain unchanged.
- Supports Apple Silicon macOS, including terminals running under Rosetta.

> [!WARNING]
> Ohm's optimizations can produce stale or incorrect build output. Its default proc-macro cache, for
> example, is explicitly labeled potentially unsound by Rust. Never rely on Ohm for production
> builds, releases, CI correctness validation, or final test results. The normal Rust toolchain must
> remain authoritative. Disable Ohm's bundled defaults for a local comparison with
> `cargo +ohm -Zohm-defaults=no test`.

## Installation

Ohm supports Apple Silicon macOS, including terminals running under Rosetta. Install
[rustup](https://rustup.rs/), then install the latest Ohm release:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://releases.astral.sh/installers/ohm/latest/ohm-installer.sh | sh
```

The release-specific installer verifies its embedded archive checksum, installs the complete Rust
toolchain, and registers an exact version and the moving `ohm` alias with rustup. Your default Rust
toolchain is not changed. Installations are stored under
`${XDG_DATA_HOME:-$HOME/.local/share}/ohm/toolchains/`.

To install an exact version, set `OHM_VERSION` to a published release and use that release's
installer:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  "https://releases.astral.sh/github/ohm/releases/download/$OHM_VERSION/ohm-installer.sh" | sh
```

To change the installation directory, set `OHM_INSTALL_DIR`:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://releases.astral.sh/installers/ohm/latest/ohm-installer.sh \
  | env OHM_INSTALL_DIR=/path/to/toolchain sh
```

## Usage

Use rustup's `+toolchain` syntax to select Ohm without replacing the normal project toolchain:

```console
cargo +ohm test
cargo +ohm check
cargo +ohm clippy
cargo +ohm fmt
```

Exact toolchain names have the form `ohm-<rust-version>-<ohm-revision>`; for example,
`cargo +ohm-1.97.1-1 test` selects that specific installed revision. Running `cargo test` without a
toolchain selector continues to use the project's normal Rust toolchain.

Ohm enables dependency-aware rebuild reduction, cached relinking, and proc-macro caching by default.
Use its aggregate opt-out to compare against the same compiler and Cargo without those defaults:

```console
cargo +ohm -Zohm-defaults=no test
```

Repository-specific optimizations, such as uv's `--profile fast-build`, remain separate.

## Documentation

- [Architecture](docs/architecture.md): source repositories, compiler integration, and versioned
  release manifests.
- [Upstream changes](docs/upstream-changes.md): pull requests maintained in each Ohm source fork.
- [Releases](docs/releases.md): validating, building, and publishing a pinned Ohm toolchain.
- [Security](SECURITY.md): reporting vulnerabilities and experimental safety boundaries.

## Contributing

See the [contributing guide](CONTRIBUTING.md) for repository setup, validation, and contribution
expectations.

## License

Ohm is licensed under either of

- Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
  <https://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or <https://opensource.org/licenses/MIT>)

at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in Ohm
by you, as defined in the Apache-2.0 license, shall be dually licensed as above, without any
additional terms or conditions.
