#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: verify-release-sources.sh MANIFEST OHM_RUST_CHECKOUT OHM_CARGO_CHECKOUT" >&2
  exit 2
fi

manifest="$1"
rust_checkout="$2"
cargo_checkout="$3"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"$script_dir/validate-release-manifest.sh" --require-pinned "$manifest"

rust_revision="$(jq -er '.sources.rust.revision' "$manifest")"
cargo_revision="$(jq -er '.sources.cargo.revision' "$manifest")"
rust_version="$(jq -er '.release.upstream_rust_version' "$manifest")"
expected_cargo_repository="$(jq -er '.sources.cargo.repository' "$manifest")"

for checkout in "$rust_checkout" "$cargo_checkout"; do
  if ! git -C "$checkout" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "not a Git checkout: $checkout" >&2
    exit 1
  fi
  if [[ -n "$(git -C "$checkout" status --porcelain --untracked-files=normal)" ]]; then
    echo "source checkout is not clean: $checkout" >&2
    exit 1
  fi
done

actual_rust_revision="$(git -C "$rust_checkout" rev-parse HEAD)"
actual_cargo_revision="$(git -C "$cargo_checkout" rev-parse HEAD)"

if [[ "$actual_rust_revision" != "$rust_revision" ]]; then
  echo "ohm-rust is at $actual_rust_revision, expected $rust_revision" >&2
  exit 1
fi

if [[ "$actual_cargo_revision" != "$cargo_revision" ]]; then
  echo "ohm-cargo is at $actual_cargo_revision, expected $cargo_revision" >&2
  exit 1
fi

actual_rust_version="$(tr -d '\r\n' <"$rust_checkout/src/version")"
if [[ "$actual_rust_version" != "$rust_version" ]]; then
  echo "ohm-rust reports version $actual_rust_version, expected $rust_version" >&2
  exit 1
fi

gitlink="$(git -C "$rust_checkout" ls-tree HEAD -- src/tools/cargo)"
read -r gitlink_mode gitlink_type gitlink_revision gitlink_path <<<"$gitlink"

if [[ "$gitlink_mode" != "160000" || "$gitlink_type" != "commit" || "$gitlink_path" != "src/tools/cargo" ]]; then
  echo "ohm-rust does not contain a src/tools/cargo gitlink" >&2
  exit 1
fi

if [[ "$gitlink_revision" != "$cargo_revision" ]]; then
  echo "ohm-rust pins Cargo $gitlink_revision, expected $cargo_revision" >&2
  exit 1
fi

cargo_repository="$(git -C "$rust_checkout" config -f .gitmodules --get submodule.src/tools/cargo.url)"
case "$cargo_repository" in
  git@github.com:*) cargo_repository="https://github.com/${cargo_repository#git@github.com:}" ;;
esac
cargo_repository="${cargo_repository%.git}"

if [[ "$cargo_repository" != "$expected_cargo_repository" ]]; then
  echo "ohm-rust Cargo submodule uses $cargo_repository, expected $expected_cargo_repository" >&2
  exit 1
fi

echo "verified ohm-rust $rust_revision with ohm-cargo $cargo_revision"
