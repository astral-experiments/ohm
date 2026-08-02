# Releases

Ohm releases are built from protected `main` using an immutable, pinned toolchain manifest.

## Prepare a release

Finalize the matching changes in `ohm-rust`, `ohm-cargo`, and `ohm-rust-clippy`, then record their
exact revisions in `toolchains/<rust-version>/<ohm-revision>.json`. The Rust revision must pin the
same Cargo revision through its `src/tools/cargo` gitlink, and Cargo must support the `ohm-defaults`
feature required by [`release/bootstrap.toml`](../release/bootstrap.toml).

A pinned manifest's source revisions can be updated until its immutable release tag is published.
After publication, the release identity and source revisions cannot change.

Validate a compatible pinned manifest and its checked-out source revisions:

```console
manifest="toolchains/${RUST_VERSION:?}/${OHM_REVISION:?}.json"
./scripts/validate-release-manifest.sh --require-pinned "$manifest"
./scripts/verify-release-sources.sh "$manifest" /path/to/ohm-rust /path/to/ohm-cargo \
  /path/to/ohm-rust-clippy
```

The protected `release` environment needs an `OHM_REPOSITORIES_TOKEN` with read access to the Rust,
Cargo, and Clippy source repositories. The Apple Silicon build uses the shared `depot-macos-15`
runner and needs at least 50 GiB of available disk space. Planning and publication use
`depot-ubuntu-24.04-4` runners.

## Build and publish

Run the release workflow from `main` with the pinned manifest and enable the full distribution
build:

```console
gh workflow run release.yml --repo astral-sh/ohm --ref main \
  -f manifest="$manifest" -F build=true
```

The workflow verifies source revisions, builds the complete stage-2 Rust distribution, smoke-tests
the installed toolchain, and creates a GitHub Release named after the immutable toolchain version.
Its internal smoke test uses `OHM_DOWNLOAD_URL` to read staged artifacts before publication.
Each release includes:

- an Apple Silicon macOS `.tar.gz` archive;
- `ohm-installer.sh`, with the release version and archive checksum embedded;
- the release manifest and source provenance; and
- `SHA256SUMS` for the published assets.

The installer and archive checksum share GitHub Releases as their trust root. HTTPS and checksums
verify transport and artifact integrity; they are not independent signatures or attestations.

Release versions cannot be republished. If source revisions or release inputs change, prepare a new
Ohm revision and repeat the protected release workflow.
