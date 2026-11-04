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
rust_checkout="$test_root/rust"$'\n'
mkdir -p "$cargo_checkout" "$clippy_checkout" "$rustfmt_checkout" "$rust_checkout"

dependency="$test_root/dependency"
git init --quiet "$dependency"
printf 'pub const VALUE: u8 = 1;\n' > "$dependency/lib.rs"
git -C "$dependency" add lib.rs
commit_fixture "$dependency" -m 'Add source dependency'

git -C "$cargo_checkout" init --quiet
git -C "$cargo_checkout" -c protocol.file.allow=always submodule add --quiet \
  --name fixture "$dependency" 'vendor/fixture code'
printf 'fixture cargo\n' > "$cargo_checkout/README.md"
ln -s README.md "$cargo_checkout/readme-link"
git -C "$cargo_checkout" add README.md readme-link
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
git -c protocol.file.allow=always clone --quiet --recurse-submodules "$cargo_checkout" "$rust_checkout/src/tools/cargo"

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

invalid_version="$manifest_directory"$'\n'
mkdir "$invalid_version"
cp "$release_manifest" "$invalid_version/2.json"
if "$script_dir/validate-release-manifest.sh" "$invalid_version/2.json" >/dev/null 2>&1; then
  echo 'manifest validation accepted a version directory ending in a newline' >&2
  exit 1
fi

"$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout" "$clippy_checkout" "$rustfmt_checkout"

verify_sources=("$script_dir/verify-release-sources.sh" "$release_manifest" "$rust_checkout"
  "$cargo_checkout" "$clippy_checkout" "$rustfmt_checkout")
printf '/build.rs\n' >> "$cargo_checkout/.git/info/exclude"
printf 'fn main() {}\n' > "$cargo_checkout/build.rs"
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted a locally ignored build script' >&2
  exit 1
fi
rm -- "$cargo_checkout/build.rs"

readme="$cargo_checkout/README.md"
git -C "$cargo_checkout" config core.trustctime false
touch -t 200001010000 "$readme"
git -C "$cargo_checkout" update-index --refresh -- README.md
cp -p "$readme" "$test_root/original-readme"
printf 'altered cargo\n' >"$readme"
touch -r "$test_root/original-readme" "$readme"
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted changed contents with a preserved size and mtime' >&2
  exit 1
fi
cp -p "$test_root/original-readme" "$readme"
"${verify_sources[@]}" >/dev/null
git -C "$cargo_checkout" config --unset core.trustctime

printf 'README.md filter=ohm-test\n' > "$cargo_checkout/.git/info/attributes"
git -C "$cargo_checkout" config filter.ohm-test.clean 'git show HEAD:README.md'
git -C "$cargo_checkout" config filter.ohm-test.required true
printf 'hidden cargo!\n' > "$readme"
git -C "$cargo_checkout" add -- README.md
git -C "$cargo_checkout" diff --cached --quiet HEAD -- README.md
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted a tracked edit hidden by a clean filter' >&2
  exit 1
fi
cp -p "$test_root/original-readme" "$readme"
"${verify_sources[@]}" >/dev/null
git -C "$cargo_checkout" config --remove-section filter.ohm-test
rm -- "$cargo_checkout/.git/info/attributes"

embedded_cargo="$rust_checkout/src/tools/cargo"
nested_dependency="$embedded_cargo/vendor/fixture code"
mv "$nested_dependency/.git" "$test_root/dependency-gitfile"
mv "$nested_dependency/lib.rs" "$test_root/dependency-source"
"${verify_sources[@]}" >/dev/null
mv "$test_root/dependency-source" "$nested_dependency/.source.rs"
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted a populated uninitialized submodule' >&2
  exit 1
fi
mv "$nested_dependency/.source.rs" "$nested_dependency/lib.rs"
mv "$test_root/dependency-gitfile" "$nested_dependency/.git"

git -C "$rust_checkout" config submodule.src/tools/cargo.ignore all
git -C "$embedded_cargo" config submodule.fixture.ignore all
for source in "$embedded_cargo/README.md" "$nested_dependency/lib.rs"; do
  printf '// uncommitted edit\n' >> "$source"
  if "${verify_sources[@]}" >/dev/null 2>&1; then
    echo "source verification accepted an ignored submodule edit in $source" >&2
    exit 1
  fi
  git -C "${source%/*}" restore -- "${source##*/}"
done
commit_fixture "$nested_dependency" --allow-empty -m 'Change the submodule revision'
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted an ignored nested submodule revision' >&2
  exit 1
fi
git -C "$nested_dependency" checkout --quiet --detach "$(git -C "$dependency" rev-parse HEAD)"
"${verify_sources[@]}"

git -C "$nested_dependency" config core.fileMode false
chmod +x "$nested_dependency/lib.rs"
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted a changed executable bit' >&2
  exit 1
fi
chmod -x "$nested_dependency/lib.rs"

git -C "$cargo_checkout" config core.symlinks false
git -C "$cargo_checkout" update-index --skip-worktree readme-link
rm "$cargo_checkout/readme-link"
printf 'README.md' > "$cargo_checkout/readme-link"
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted a symlink replaced by a regular file' >&2
  exit 1
fi
rm "$cargo_checkout/readme-link"
ln -s README.md "$cargo_checkout/readme-link"
git -C "$cargo_checkout" update-index --no-skip-worktree readme-link
"${verify_sources[@]}"

pinned_tree="$(git -C "$cargo_checkout" rev-parse 'HEAD^{tree}')"
printf 'replaced Cargo source\n' >> "$cargo_checkout/README.md"
git -C "$cargo_checkout" add README.md
replacement_tree="$(git -C "$cargo_checkout" write-tree)"
git -C "$cargo_checkout" replace "$pinned_tree" "$replacement_tree"
if "${verify_sources[@]}" >/dev/null 2>&1; then
  echo 'source verification accepted a replacement tree' >&2
  exit 1
fi
git -C "$cargo_checkout" replace -d "$pinned_tree" >/dev/null
git -C "$cargo_checkout" restore --staged --worktree README.md

for flag in assume-unchanged skip-worktree; do
  git -C "$cargo_checkout" update-index "--$flag" README.md
  flagged_entry="$(git -C "$cargo_checkout" ls-files -v -- README.md)"
  "${verify_sources[@]}"
  printf 'uncommitted Cargo source\n' >> "$cargo_checkout/README.md"
  if "${verify_sources[@]}" >/dev/null 2>&1; then
    echo "source verification accepted an edit hidden by $flag" >&2
    exit 1
  fi
  if [[ "$(git -C "$cargo_checkout" ls-files -v -- README.md)" != "$flagged_entry" ]]; then
    echo "source verification changed the $flag index bit" >&2
    exit 1
  fi
  git -C "$cargo_checkout" update-index "--no-$flag" README.md
  git -C "$cargo_checkout" restore README.md
done

mkdir "$cargo_checkout/nested"
if "$script_dir/verify-release-sources.sh" \
  "$release_manifest" "$rust_checkout" "$cargo_checkout/nested" "$clippy_checkout" "$rustfmt_checkout" \
  >/dev/null 2>&1; then
  echo 'source verification accepted a subdirectory as the Cargo checkout' >&2
  exit 1
fi

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
