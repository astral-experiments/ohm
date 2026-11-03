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
jq 'del(.sources.rustfmt)' "$manifest" > "$test_root/legacy.json"
cp "$test_root/legacy.json" "$manifest"

git -C "$test_root" init --quiet
git -C "$test_root" add "$manifest_path"
git -C "$test_root" \
  -c user.name='Ohm manifest fixture' \
  -c user.email='ohm-manifest-fixture@example.invalid' \
  commit --quiet -m 'Add pinned manifest fixture'
base_revision="$(git -C "$test_root" rev-parse HEAD)"

check_history() {
  (cd -- "${1:-$test_root}" && "$script_dir/check-manifest-history.sh" "$base_revision")
}

expect_history_failure() {
  local description="$1"

  if check_history "${2:-$test_root}" >/dev/null 2>&1; then
    echo "manifest history accepted $description" >&2
    exit 1
  fi
}

check_history

jq '
  .sources.rustfmt = {
    repository: "https://github.com/astral-sh/ohm-rustfmt",
    revision: "4444444444444444444444444444444444444444"
  }
' "$manifest" > "$test_root/with-rustfmt.json"
cp "$test_root/with-rustfmt.json" "$manifest"
check_history

jq '.sources.rustfmt.repository = "https://github.com/example/rustfmt"' \
  "$manifest" > "$test_root/wrong-rustfmt.json"
cp "$test_root/wrong-rustfmt.json" "$manifest"
expect_history_failure 'an unpublished Rustfmt repository change'
cp "$test_root/with-rustfmt.json" "$manifest"

jq '
  .sources.rust.revision = "1111111111111111111111111111111111111111" |
  .sources.cargo.revision = "2222222222222222222222222222222222222222" |
  .sources.clippy.revision = "3333333333333333333333333333333333333333" |
  .sources.rustfmt.revision = "5555555555555555555555555555555555555555"
' "$manifest" > "$test_root/updated.json"
cp "$test_root/updated.json" "$manifest"
check_history

jq '.sources.cargo.repository = "https://github.com/example/cargo"' \
  "$manifest" > "$test_root/changed-identity.json"
cp "$test_root/changed-identity.json" "$manifest"
expect_history_failure 'an unpublished source repository change'
cp "$test_root/updated.json" "$manifest"

git -C "$test_root" add "$manifest_path"
git -C "$test_root" \
  -c user.name='Ohm manifest fixture' \
  -c user.email='ohm-manifest-fixture@example.invalid' \
  commit --quiet -m 'Add pinned Rustfmt source fixture'
base_revision="$(git -C "$test_root" rev-parse HEAD)"

jq '.sources.rustfmt.revision = "6666666666666666666666666666666666666666"' \
  "$manifest" > "$test_root/updated-rustfmt.json"
cp "$test_root/updated-rustfmt.json" "$manifest"
check_history

release_tag="$(git -C "$test_root" show "$base_revision:$manifest_path" | jq -er '.release.toolchain_name')"
git -C "$test_root" tag "$release_tag"
expect_history_failure 'a published Rustfmt source revision change'
expect_history_failure 'a published revision change from a subdirectory' "$test_root/toolchains/1.97.1"
ln -s toolchains/1.97.1 "$test_root/nested"
expect_history_failure 'a published revision change from a symlinked subdirectory' "$test_root/nested"

git -C "$test_root" show "$base_revision:$manifest_path" > "$manifest"
check_history

check_history "$test_root/toolchains/1.97.1"

mv -- "$manifest" "$test_root/same-content.json"
ln -s ../../same-content.json "$manifest"
expect_history_failure 'a symlink replacing a published manifest'
unlink "$manifest"
mv -- "$test_root/same-content.json" "$manifest"

ln -s 1.json "$test_root/toolchains/1.97.1/2.json"
expect_history_failure 'a new symlinked manifest'
unlink "$test_root/toolchains/1.97.1/2.json"

mv -- "$test_root/toolchains/1.97.1" "$test_root/version"
ln -s ../version "$test_root/toolchains/1.97.1"
expect_history_failure 'a symlink replacing the manifest directory'

# The base commit can be available while its tree still needs to be fetched.
partial_checkout="$test_root/partial"
git -C "$test_root" config uploadpack.allowFilter true
git clone --quiet --filter=tree:0 --no-checkout "file://$test_root" "$partial_checkout"
git -C "$partial_checkout" checkout --quiet HEAD
git -C "$partial_checkout" remote set-url origin "$test_root/missing-remote"
base_revision="$(git -C "$partial_checkout" rev-parse HEAD^)"
expect_history_failure 'an unavailable base tree' "$partial_checkout"

echo 'manifest history tests passed'
