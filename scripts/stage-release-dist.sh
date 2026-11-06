#!/usr/bin/env bash
set -euo pipefail

manifest_sha256="$(shasum -a 256 "$MANIFEST_PATH" | awk '{print $1}')"
jq -n \
  --arg toolchain "$OHM_TOOLCHAIN" \
  --arg target "$OHM_TARGET" \
  --arg coordinator_repository "$GITHUB_REPOSITORY" \
  --arg coordinator_revision "$GITHUB_SHA" \
  --arg manifest_path "$MANIFEST_PATH" \
  --arg manifest_sha256 "$manifest_sha256" \
  --arg rust_revision "$RUST_REVISION" \
  --arg cargo_revision "$CARGO_REVISION" \
  --arg clippy_revision "$CLIPPY_REVISION" \
  --arg rustfmt_revision "$RUSTFMT_REVISION" \
  --argjson bundled_tools "$(jq --arg target "$OHM_TARGET" \
    'if $target == "x86_64-unknown-linux-gnu" then .bundled_tools // {} else {} end' "$MANIFEST_PATH")" \
  '{
    schema_version: 1,
    toolchain: $toolchain,
    target: $target,
    bundled_tools: $bundled_tools,
    coordinator: {
      repository: $coordinator_repository,
      revision: $coordinator_revision
    },
    manifest: {
      path: $manifest_path,
      sha256: $manifest_sha256
    },
    sources: {
      rust: { revision: $rust_revision },
      cargo: { revision: $cargo_revision },
      clippy: { revision: $clippy_revision },
      rustfmt: { revision: $rustfmt_revision }
    }
  }' > source/rust/build/dist/ohm-provenance.json

rust_version="$(tr -d '\r\n' < source/rust/src/version)"
combined_archive="source/rust/build/dist/rust-$rust_version-dev-$OHM_TARGET.tar.gz"
if [[ ! -f "$combined_archive" ]]; then
  echo "combined Ohm archive not found: $combined_archive" >&2
  exit 1
fi

release_directory="$(mktemp -d "${RUNNER_TEMP:?}/ohm-release.XXXXXX")"
archive_name="$OHM_TOOLCHAIN-$OHM_TARGET.tar.gz"
provenance_name="$OHM_TOOLCHAIN-$OHM_TARGET-provenance.json"
cp "$combined_archive" "$release_directory/$archive_name"
cp source/rust/build/dist/ohm-provenance.json \
  "$release_directory/$provenance_name"

(
  cd "$release_directory"
  shasum -a 256 "$archive_name" > "$archive_name.sha256"
  shasum -a 256 "$provenance_name" > "$provenance_name.sha256"
)

echo "directory=$release_directory" >> "$GITHUB_OUTPUT"
