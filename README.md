# Ohm

Ohm is an experimental Rust toolchain for faster local incremental builds. Its source is split
across four repositories:

- [`astral-sh/ohm-rust`](https://github.com/astral-sh/ohm-rust) contains the Rust compiler,
  standard library, vendored Clippy and rustfmt snapshots, and bootstrap changes.
- [`astral-sh/ohm-cargo`](https://github.com/astral-sh/ohm-cargo) contains the matching Cargo
  changes.
- [`astral-sh/ohm-rust-clippy`](https://github.com/astral-sh/ohm-rust-clippy) contains the matching
  Clippy changes, which are overlaid onto Rust's vendored Clippy source tree during release builds.
- [`astral-sh/ohm-rustfmt`](https://github.com/astral-sh/ohm-rustfmt) carries rustfmt-specific
  changes before their exact source tree is synced into `ohm-rust`.

This repository pins exact `ohm-rust`, `ohm-cargo`, and `ohm-rust-clippy` revisions, coordinates
candidate builds, and will eventually publish the combined toolchain. rustfmt is built from the
exact snapshot vendored by the pinned `ohm-rust` revision.

## `cargo +ohm`

`cargo` in a rustup installation is a proxy. A `+toolchain` argument selects the `cargo` and
`rustc` binaries from that named toolchain:

```console
cargo test                         # the project's normal Rust toolchain
cargo +ohm-1.97.1-1 test           # an exact Ohm toolchain
cargo +ohm test                    # a moving local alias, if one has been registered
cargo +ohm clippy                  # the matching Clippy from the Ohm Rust source tree
cargo +ohm fmt                     # the matching rustfmt from the Ohm Rust source tree
```

Installing or linking Ohm does not replace the default Rust toolchain. An Ohm toolchain directory
contains the forked Cargo binary, matching compiler, Clippy and rustfmt binaries, and sysroot.

Cargo shipped in an Ohm distribution enables the complete Ohm workflow by default: Cargo's
`-Zrelink-only` reuses cached code generation when a unit only needs to be relinked, rustc's
`-Zpublic-api-hash` uses public-API hashes for dependency invalidation, and
`-Zcache-proc-macros` caches derive proc-macro invocations. No additional performance flags are
required:

```console
cargo +ohm test
```

For a controlled comparison with the same Cargo and compiler binaries, disable all of those defaults
for one invocation:

```console
cargo +ohm -Zohm-defaults=no test
```

rustc labels `-Zcache-proc-macros` as potentially unsound. Ohm is experimental; use the aggregate
opt-out above for invocations where that risk is unacceptable or when investigating cache-related
behavior.

The individual unstable flags are implementation details of this bundle. Repository-specific
options such as uv's `--profile fast-build` remain separate and should only be used when appropriate
for that repository.

## Installation

Ohm currently supports Apple Silicon macOS. Install [rustup](https://rustup.rs/), then install the
latest Ohm release with:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/astral-sh/ohm/releases/latest/download/ohm-installer.sh | sh
```

Each release publishes its own installer with the exact Ohm version and archive checksum embedded.
The installer downloads the matching Apple Silicon archive, verifies its SHA-256 checksum, and
installs the complete compiler, Cargo, Clippy, and rustfmt toolchain. No GitHub account, GitHub
CLI, or GitHub API request is required. By default, versions are installed under
`${XDG_DATA_HOME:-$HOME/.local/share}/ohm/toolchains/` and registered with rustup under both their
immutable version and the moving `ohm` alias:

```console
cargo +ohm-1.97.1-2 test
cargo +ohm test
```

Your default Rust toolchain is never changed. To install an exact Ohm version, download the
installer from that version's GitHub Release:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/astral-sh/ohm/releases/download/ohm-1.97.1-2/ohm-installer.sh | sh
```

Pass `--no-alias` to retain an existing `ohm` alias while registering the exact version, or `--prefix`
to choose the exact directory in which that version is installed:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/astral-sh/ohm/releases/latest/download/ohm-installer.sh \
  | sh -s -- --prefix /path/to/ohm-1.97.1-2 --no-alias
```

For an offline installation, provide the downloaded archive and its accompanying `SHA256SUMS`
file. GitHub authentication is not required in this mode:

```console
sh scripts/install.sh \
  --version ohm-1.97.1-2 \
  --archive ohm-1.97.1-2-aarch64-apple-darwin.tar.gz \
  --checksums SHA256SUMS
```

Maintainers can also install an unpublished GitHub Actions build by providing its workflow run ID.
This mode requires the [GitHub CLI](https://cli.github.com/) and access to the workflow artifact:

```console
sh scripts/install.sh --run 123456789 --version ohm-1.97.1-2
```

## Versions and source pins

Ohm versions have the form `ohm-<rust-version>-<ohm-revision>`:

```text
ohm-1.97.1-1  first Ohm release based on Rust 1.97.1
ohm-1.97.1-2  second Ohm release based on the same Rust version
ohm-1.98.0-1  first Ohm release based on Rust 1.98.0
```

Each immutable release has a manifest at
`toolchains/<rust-version>/<ohm-revision>.json`. For example,
[`toolchains/1.97.1/1.json`](toolchains/1.97.1/1.json) describes `ohm-1.97.1-1`. The shared format is
described by [`toolchains/manifest.schema.json`](toolchains/manifest.schema.json).

A versioned manifest records the upstream Rust version, the downstream Ohm revision, and full
commit IDs for `ohm-rust`, `ohm-cargo`, and `ohm-rust-clippy`. The pinned Clippy checkout replaces
the Rust source tree's vendored Clippy snapshot before bootstrap builds the toolchain.
Publishing a later Ohm revision adds another manifest; it does not replace the earlier release
record.

CI treats pinned manifests as immutable. A checked-in draft may remain unchanged or transition once
to `pinned`; pinning may fill the source revisions but cannot change the release identity. Existing
pre-release manifests may add the mandatory Clippy source without changing their other contents.
New versioned manifests remain allowed.

The Rust revision must pin the same Cargo revision through its `src/tools/cargo` gitlink. Its
`.gitmodules` entry must also point to `astral-sh/ohm-cargo`. This gives one Rust commit a complete,
reproducible identity for the combined toolchain.

A new manifest may be checked in as a draft while its source revisions are being finalized. The
release workflow rejects drafts. `toolchains/1.97.1/1.json` now pins the first complete candidate
source pair; it does not imply that an Ohm archive has been built or released.

[`toolchains/1.97.1/2.json`](toolchains/1.97.1/2.json) reserves the revision for the default Ohm
workflow. It remains a draft until the Cargo, Rust, and Clippy stacks are squash-merged and their
final source revisions can be pinned.

## Validation

Validate the manifest structure and derived toolchain name:

```console
./scripts/validate-release-manifest.sh toolchains/1.97.1/1.json
```

After checking out the pinned repositories, verify their exact revisions and the Cargo gitlink:

```console
./scripts/verify-release-sources.sh \
  toolchains/1.97.1/1.json \
  /path/to/ohm-rust \
  /path/to/ohm-cargo \
  /path/to/ohm-rust-clippy
```

The source check also verifies that `ohm-rust/src/version` matches the upstream Rust version in the
manifest.

## Release workflow status

The manual [`release.yml`](.github/workflows/release.yml) workflow accepts the path to one versioned
manifest and:

1. selects a versioned manifest, then checks out and verifies its exact private source revisions;
2. optionally runs Rust bootstrap's full `x.py dist extended` build for the configured native
   target, smoke-installs the combined archive, and prepares its distribution artifacts;
3. writes checksummed provenance containing the coordinator revision, manifest digest, and exact
   Rust, Cargo, and Clippy revisions;
4. retains the combined archive, its checksums, provenance, manifest, and Ohm installer as a
   private GitHub Actions artifact for seven days; and
5. publishes those verified assets as a versioned public GitHub Release, including an installer
   containing the release version and archive checksum.

Cross-repository checkout currently requires an `OHM_REPOSITORIES_TOKEN` secret in a protected
`release` Environment. It must be a read-only, fine-grained token scoped only to `ohm-rust`,
`ohm-cargo`, and `ohm-rust-clippy`. Before publication, we should replace this stored credential
with a short-lived token minted per run by a GitHub App. The Environment must require the protected
`main` branch and an approval before exposing the credential.

The distribution build uses Astral's shared `depot-macos-15` Apple Silicon runner.
The runner needs at least 50 GiB of free disk space for Rust bootstrap, which builds the stage-2
compiler, sysroot, combined extended archive, and pinned Cargo while reusing the matching Rust CI
LLVM rather than rebuilding unchanged LLVM. Release planning and publication use Astral's shared
`depot-ubuntu-24.04-4` Linux runners.

Only the protected release-publication job can write repository contents. Public release assets can
be downloaded without authentication; unpublished GitHub Actions artifacts still require repository
access.
