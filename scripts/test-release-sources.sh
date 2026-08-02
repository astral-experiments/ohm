#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/ohm-release-sources.XXXXXX")"
trap 'rm -rf -- "$test_root"' EXIT

commit_fixture() {
  local checkout="$1"
  shift
  git -C "$checkout" -c user.name='Ohm release fixture' \
    -c user.email='ohm-release-fixture@example.invalid' commit --quiet "$@"
}

cargo_checkout="$test_root/cargo"
clippy_checkout="$test_root/clippy"
rustfmt_checkout="$test_root/rustfmt"
rust_checkout="$test_root/rust"
mkdir -p "$cargo_checkout" "$clippy_checkout" "$rustfmt_checkout" "$rust_checkout"

git -C "$cargo_checkout" init --quiet
printf 'fixture cargo\n' > "$cargo_checkout/README.md"
git -C "$cargo_checkout" add README.md
commit_fixture "$cargo_checkout" -m 'Add Cargo fixture'
cargo_revision="$(git -C "$cargo_checkout" rev-parse HEAD)"

git -C "$clippy_checkout" init --quiet
printf 'optimized fixture clippy\n' > "$clippy_checkout/README.md"
git -C "$clippy_checkout" add README.md
commit_fixture "$clippy_checkout" -m 'Add Clippy fixture'
clippy_revision="$(git -C "$clippy_checkout" rev-parse HEAD)"

git -C "$rustfmt_checkout" init --quiet
printf 'optimized fixture rustfmt\n' > "$rustfmt_checkout/README.md"
git -C "$rustfmt_checkout" add README.md
commit_fixture "$rustfmt_checkout" -m 'Add rustfmt fixture'
rustfmt_revision="$(git -C "$rustfmt_checkout" rev-parse HEAD)"

git -C "$rust_checkout" init --quiet
mkdir -p "$rust_checkout/src/tools/clippy" "$rust_checkout/src/tools/rustfmt"
printf '1.97.1\n' > "$rust_checkout/src/version"
printf 'original embedded clippy\n' > "$rust_checkout/src/tools/clippy/README.md"
printf 'original embedded rustfmt\n' > "$rust_checkout/src/tools/rustfmt/README.md"
cat > "$rust_checkout/.gitmodules" <<'EOF'
[submodule "src/tools/cargo"]
	path = src/tools/cargo
	url = https://github.com/astral-sh/ohm-cargo.git
EOF
git -C "$rust_checkout" add .gitmodules src/version \
  src/tools/clippy/README.md src/tools/rustfmt/README.md
git -C "$rust_checkout" update-index --add \
  --cacheinfo "160000,$cargo_revision,src/tools/cargo"
commit_fixture "$rust_checkout" -m 'Add Rust fixture'
rust_revision="$(git -C "$rust_checkout" rev-parse HEAD)"
git clone --quiet "$cargo_checkout" "$rust_checkout/src/tools/cargo"

manifest_directory="$test_root/toolchains/1.97.1"
mkdir -p "$manifest_directory"
cp "$repository_root/toolchains/manifest.schema.json" "$test_root/toolchains/manifest.schema.json"

release_manifest="$manifest_directory/2.json"
jq --arg rust "$rust_revision" --arg cargo "$cargo_revision" \
  --arg clippy "$clippy_revision" --arg rustfmt "$rustfmt_revision" \
  '.status = "pinned" |
   .sources.rust.revision = $rust |
   .sources.cargo.revision = $cargo |
   .sources.clippy.revision = $clippy |
   .sources.rustfmt = {
     repository: "https://github.com/astral-sh/ohm-rustfmt",
     revision: $rustfmt
   }' \
  "$repository_root/toolchains/1.97.1/2.json" > "$release_manifest"

"$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" "$clippy_checkout" "$rustfmt_checkout"

if "$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" "$clippy_checkout" >/dev/null 2>&1; then
  echo 'source verification accepted a missing rustfmt checkout' >&2
  exit 1
fi

wrong_clippy_checkout="$test_root/wrong-clippy"
git clone --quiet "$clippy_checkout" "$wrong_clippy_checkout"
commit_fixture "$wrong_clippy_checkout" --allow-empty -m 'Change Clippy revision'
if "$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" \
  "$wrong_clippy_checkout" "$rustfmt_checkout" \
  >/dev/null 2>&1; then
  echo 'source verification accepted the wrong Clippy revision' >&2
  exit 1
fi

wrong_rustfmt_checkout="$test_root/wrong-rustfmt"
git clone --quiet "$rustfmt_checkout" "$wrong_rustfmt_checkout"
commit_fixture "$wrong_rustfmt_checkout" --allow-empty -m 'Change rustfmt revision'
if "$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" \
  "$clippy_checkout" "$wrong_rustfmt_checkout" \
  >/dev/null 2>&1; then
  echo 'source verification accepted the wrong rustfmt revision' >&2
  exit 1
fi

mv "$rust_checkout/src/tools/clippy" "$test_root/original-clippy"
git clone --quiet "$clippy_checkout" "$rust_checkout/src/tools/clippy"
mv "$rust_checkout/src/tools/rustfmt" "$test_root/original-rustfmt"
git clone --quiet "$rustfmt_checkout" "$rust_checkout/src/tools/rustfmt"
"$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" \
  "$rust_checkout/src/tools/clippy" "$rust_checkout/src/tools/rustfmt"

printf 'unexpected rustfmt change\n' >> "$rust_checkout/src/tools/rustfmt/README.md"
if "$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" \
  "$rust_checkout/src/tools/clippy" "$rust_checkout/src/tools/rustfmt" \
  >/dev/null 2>&1; then
  echo 'source verification accepted a dirty rustfmt checkout' >&2
  exit 1
fi
git -C "$rust_checkout/src/tools/rustfmt" restore README.md

printf 'unexpected Rust change\n' >> "$rust_checkout/src/version"
if "$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" \
  "$rust_checkout/src/tools/clippy" "$rust_checkout/src/tools/rustfmt" \
  >/dev/null 2>&1; then
  echo 'source verification ignored a dirty Rust checkout outside tool overlays' >&2
  exit 1
fi

echo 'release source verification tests passed'
