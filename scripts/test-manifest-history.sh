#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/ohm-manifest-history.XXXXXX")"
trap 'rm -rf -- "$test_root"' EXIT

manifest_path='toolchains/1.97.1/1.json'
manifest="$test_root/$manifest_path"
mkdir -p -- "$(dirname -- "$manifest")"
cp "$repository_root/$manifest_path" "$manifest"

git -C "$test_root" init --quiet
git -C "$test_root" add "$manifest_path"
git -C "$test_root" \
  -c user.name='Ohm manifest fixture' \
  -c user.email='ohm-manifest-fixture@example.invalid' \
  commit --quiet -m 'Add pinned manifest fixture'
base_revision="$(git -C "$test_root" rev-parse HEAD)"

check_history() {
  (cd -- "$test_root" && "$script_dir/check-manifest-history.sh" "$base_revision")
}

expect_history_failure() {
  local description="$1"

  if check_history >/dev/null 2>&1; then
    echo "manifest history accepted $description" >&2
    exit 1
  fi
}

check_history

jq '
  .sources.rust.revision = "1111111111111111111111111111111111111111" |
  .sources.cargo.revision = "2222222222222222222222222222222222222222" |
  .sources.clippy.revision = "3333333333333333333333333333333333333333"
' "$manifest" > "$test_root/updated.json"
cp "$test_root/updated.json" "$manifest"
check_history

jq '.sources.cargo.repository = "https://github.com/example/cargo"' \
  "$manifest" > "$test_root/changed-identity.json"
cp "$test_root/changed-identity.json" "$manifest"
expect_history_failure 'an unpublished source repository change'
cp "$test_root/updated.json" "$manifest"

release_tag="$(git -C "$test_root" show "$base_revision:$manifest_path" | jq -er '.release.toolchain_name')"
git -C "$test_root" tag "$release_tag"
expect_history_failure 'a published source revision change'

git -C "$test_root" show "$base_revision:$manifest_path" > "$manifest"
check_history

echo 'manifest history tests passed'
