# Ohm

Ohm is an experimental Rust toolchain for faster local incremental builds. This repository is the
release coordinator for two source repositories:

- [`astral-sh/ohm-rust`](https://github.com/astral-sh/ohm-rust) contains the Rust compiler,
  standard library, exact-tree Clippy, and bootstrap changes.
- [`astral-sh/ohm-cargo`](https://github.com/astral-sh/ohm-cargo) contains the matching Cargo
  changes.
- `astral-sh/ohm` pins one exact revision of each repository, coordinates candidate builds, and
  will eventually publish the combined toolchain.

## `cargo +ohm`

`cargo` in a rustup installation is a proxy. A `+toolchain` argument selects the `cargo` and
`rustc` binaries from that named toolchain:

```console
cargo test                         # the project's normal Rust toolchain
cargo +ohm-1.97.1-1 test           # an exact Ohm toolchain
cargo +ohm test                    # a moving local alias, if one has been registered
cargo +ohm clippy                  # the matching Clippy from the Ohm Rust source tree
```

Installing or linking Ohm does not replace the default Rust toolchain. An Ohm toolchain directory
contains the forked Cargo binary, matching compiler and Clippy binaries, and sysroot.

Selecting the toolchain alone does not enable the current acceleration prototypes. The measured uv
configuration currently requires the rustc public-API hash, Cargo's cached-relink mode, and uv's
existing fast-build profile:

```console
RUSTFLAGS="-Zpublic-api-hash" \
  cargo +ohm-1.97.1-1 -Zrelink-only \
  test --profile fast-build -p uv --lib TEST_NAME -- --exact
```

`--profile fast-build` is specific to the measured uv workflow. The Rust and Cargo flags are still
unstable prototype interfaces; a future Cargo-owned Ohm flag or launcher should coordinate them.
Ohm distributions are built using Rust's `dev` channel so these explicit `-Z` flags work without
setting `RUSTC_BOOTSTRAP`; selecting the toolchain still leaves the prototypes disabled by default.

There is no released Ohm toolchain or installer yet. After building one locally, rustup can
register an extracted toolchain directory with:

```console
rustup toolchain link ohm-1.97.1-1 /path/to/ohm-toolchain
```

The exact archive layout and installer command are still to be implemented and tested.

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
commit IDs for `ohm-rust` and `ohm-cargo`. Publishing a later Ohm revision adds another manifest;
it does not replace the earlier release record.

CI treats pinned manifests as immutable. A checked-in draft may remain byte-for-byte unchanged or
transition once to `pinned`; that transition may fill the source revisions but cannot change the
release identity. New versioned manifests remain allowed.

The Rust revision must pin the same Cargo revision through its `src/tools/cargo` gitlink. Its
`.gitmodules` entry must also point to `astral-sh/ohm-cargo`. This gives one Rust commit a complete,
reproducible identity for the combined toolchain.

A new manifest may be checked in as a draft while its source revisions are being finalized. The
release workflow rejects drafts. `toolchains/1.97.1/1.json` now pins the first complete candidate
source pair; it does not imply that an Ohm archive has been built or released.

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
  /path/to/ohm-cargo
```

The source check also verifies that `ohm-rust/src/version` matches the upstream Rust version in the
manifest.

## Release workflow status

The manual [`release.yml`](.github/workflows/release.yml) workflow accepts the path to one versioned
manifest and currently provides three pieces of release scaffolding:

1. select a versioned manifest, then check out and verify its exact private source revisions; and
2. optionally run Rust bootstrap's full `x.py dist extended` build for the configured native target
   and retain its distribution artifacts; and
3. write checksummed provenance containing the coordinator revision, manifest digest, and exact
   Rust and Cargo revisions.

Cross-repository checkout currently requires an `OHM_REPOSITORIES_TOKEN` secret in a protected
`release` Environment. It must be a read-only, fine-grained token scoped only to `ohm-rust` and
`ohm-cargo`. Before publication, we should replace this stored credential with a short-lived token
minted per run by a GitHub App. The Environment must require the protected `main` branch and an
approval before exposing the credential.

The distribution build uses a self-hosted Apple Silicon runner with the labels `self-hosted`,
`macOS`, `ARM64`, and `ohm-builder`. It must have at least 50 GiB of free disk space. The bootstrap
configuration builds the stage-2 compiler, sysroot, combined extended archive, and pinned Cargo,
while reusing the matching Rust CI LLVM rather than rebuilding unchanged LLVM.

The workflow deliberately does **not** create a GitHub release, publish artifacts, update a moving
`ohm` alias, or install the resulting distribution. Archive smoke tests, an installer, artifact
signing or attestation, and publication remain required before the first release.
