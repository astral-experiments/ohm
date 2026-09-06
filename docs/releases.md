# Releases

Ohm releases are built from protected `main` using an immutable, pinned toolchain manifest.

## Prepare a release

Finalize the matching changes in `ohm-rust`, `ohm-cargo`, `ohm-rust-clippy`, and `ohm-rustfmt`,
then record their exact revisions in `toolchains/<rust-version>/<ohm-revision>.json`. The Rust
revision must pin the same Cargo revision through its `src/tools/cargo` gitlink, and Cargo must
support the `ohm-defaults` feature required by
[`release/bootstrap.toml`](../release/bootstrap.toml).

Pin source revisions with fork-owned CI. In particular, the rustfmt checkout must not contain its
upstream tag-triggered release workflow, which would start unrelated builds when source tags are
created.

A pinned manifest's source revisions can be updated until its immutable release tag is published.
After publication, the release identity and source revisions cannot change.

Validate a compatible pinned manifest and its checked-out source revisions:

```console
manifest="toolchains/${RUST_VERSION:?}/${OHM_REVISION:?}.json"
./scripts/validate-release-manifest.sh --require-pinned "$manifest"
./scripts/verify-release-sources.sh "$manifest" /path/to/ohm-rust /path/to/ohm-cargo \
  /path/to/ohm-rust-clippy /path/to/ohm-rustfmt
```

A dedicated GitHub App needs Contents read and write access to the four source repositories.
Planning and build jobs request short-lived, read-only installation tokens; source tagging uses a
separate, write-scoped token after the distribution has been built and tested.

Store the GitHub App private key and Cloudflare R2 credentials as protected `release` environment
secrets:

- `OHM_RELEASE_APP_PRIVATE_KEY`
- `MIRROR_R2_ACCESS_KEY_ID`
- `MIRROR_R2_SECRET_ACCESS_KEY`

Store the GitHub App client ID and Cloudflare account and bucket configuration as protected
`release` environment variables:

- `OHM_RELEASE_APP_CLIENT_ID`
- `MIRROR_R2_CLOUDFLARE_ACCOUNT_ID`
- `MIRROR_R2_BUCKET_NAME`

The bucket is served publicly from `labs.astral.sh` and should be separate from Astral's production
release bucket. Its credentials should only grant access to the experimental release bucket.

Apple Silicon builds use `depot-macos-15` because PGO-instrumented binaries crash on Namespace
runners; macOS smoke tests still use `namespace-profile-macos-15`. x86_64 Linux builds use
`github-ubuntu-24.04-x86_64-8`. macOS builds need at least 50 GiB of available disk space, while
Linux builds need at least 150 GiB for the temporary BOLT profiling corpus. Planning and publication
use `depot-ubuntu-24.04-4` runners.

Component-PGO-capable Rust source revisions additionally optimize rustdoc, Cargo, Clippy, rustfmt,
and cargo-fmt on both platforms; historical source revisions retain rustc-only PGO. Cargo shares
the compiler's training profile, rustfmt shares its profile with cargo-fmt, and rustdoc and Clippy
each train on their own workloads. Release builds reject missing, invalid, or misattributed merged
profiles, reuse Rust's optimized CI LLVM, and additionally optimize the compiler with BOLT on Linux.

## Build and publish

Run the release workflow from `main` with the pinned manifest and enable the full distribution
build:

```console
gh workflow run release.yml --repo astral-sh/ohm --ref main \
  -f manifest="$manifest" -F build=true
```

The workflow verifies source revisions, builds both complete stage-2 Rust distributions, and
generates one universal installer with both archive checksums embedded. It smoke-tests that exact
installer on macOS and Linux before checking existing source tags across all four repositories and
tagging any missing pinned revisions with the toolchain name. Existing tags at the expected commit
are reused; conflicting immutable tags fail the release before any new source tags are created. The
workflow then creates the private GitHub Release and publishes the public assets.

For compilers supporting `ohm-cloned-query-cache-prefix`, the installed-toolchain smoke test also
checks Cargo's cache defaults, automatic and explicit Clippy isolation, ordinary build reuse after
Clippy, child-worktree lint configuration, and donor cache immutability. Automatic isolation requires
clone-capable storage; `-Zohm-clippy-seed-isolation=yes` also exercises snapshot reuse through byte
copies on filesystems without cloning. To run that check against a locally installed candidate:

```console
bash scripts/smoke-worktree-cache.sh "$candidate_toolchain" /path/to/new-smoke-directory
```

The directory must not already exist. It retains the fixture, logs, and donor checksums for review.

Release notes include version-pinned installation instructions, usage examples, the development-only
safety warning, and public download links alongside the generated changelog. Internal smoke tests use
`OHM_DOWNLOAD_URL` to read staged artifacts before publication. The private release includes:

- Apple Silicon macOS and x86_64 Linux (glibc) `.tar.gz` archives and `.sha256` sidecars;
- `ohm-installer.sh`, with the release version and both archive checksums embedded;
- the release manifest and platform-specific source provenance; and
- `SHA256SUMS` for the release assets.

Only the installer, archives, checksum sidecars, and a public-only `SHA256SUMS` file are copied to
Cloudflare R2. Versioned assets are served publicly from
`https://labs.astral.sh/ohm/releases/<version>/` and cached immutably for one year. The
release-specific installer is available at
`https://labs.astral.sh/ohm/releases/<version>/install.sh`. Its archives are available at
`https://labs.astral.sh/ohm/releases/<version>/<version>-aarch64-apple-darwin.tar.gz` and
`https://labs.astral.sh/ohm/releases/<version>/<version>-x86_64-unknown-linux-gnu.tar.gz`. The latest
installer is available at `https://labs.astral.sh/ohm/install.sh` and cached for five minutes. Source
repositories, GitHub Releases, release manifests, and source provenance remain private.

The public installer and its embedded archive checksum share Cloudflare R2 as their trust root.
HTTPS and checksums verify transport and artifact integrity; they are not independent signatures or
attestations.

Release versions cannot be republished. If source revisions or release inputs change, prepare a new
Ohm revision and repeat the protected release workflow.
