# Contributing

## Finding ways to help

Ohm is experimental and coordinates changes across its Rust, Cargo, and Clippy repositories. Please
discuss significant behavior or soundness changes before opening a pull request.

Ohm is a development-only toolchain. Validate production builds, release artifacts, CI correctness,
and final test results with the normal Rust toolchain.

## Use of AI

We **require all use of AI in contributions to follow our
[AI Policy](https://github.com/astral-sh/.github/blob/main/AI_POLICY.md)**.

If your contribution does not follow the policy, it will be closed.

## Setup

The release coordinator requires Git, `jq`, and either [`uvx`](https://docs.astral.sh/uv/guides/tools/)
or `check-jsonschema` to validate release manifests.

Source repositories keep an `upstream-<rust-version>` branch for the matching upstream release and
an `ohm-<rust-version>` branch for Ohm-specific changes. Coordinate compiler, Cargo, and Clippy
changes against the same upstream Rust version; update release manifests only when the matching
source revisions are finalized.

## Testing

Validate shell scripts and run the coordinator's focused tests:

```console
bash -n scripts/*.sh
sh -n scripts/install.sh
./scripts/test-release-sources.sh
bash scripts/test-installer.sh
```

When editing a release manifest, validate it and preserve existing release identities:

```console
./scripts/validate-release-manifest.sh "$MANIFEST_PATH"
./scripts/check-manifest-history.sh "$(git merge-base HEAD main)"
```

See [Architecture](docs/architecture.md) for source ownership and safety boundaries, and
[Releases](docs/releases.md) for source verification and publication.
