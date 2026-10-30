#!/usr/bin/env bash
set -euo pipefail
study="$GITHUB_WORKSPACE/scripts/ohm-packed-ruff"
base="$GITHUB_WORKSPACE/scripts/ohm-apple-zmij/source-transport"
root="$RUNNER_TEMP/ohm-branch-object-qa"
receipts="$root/logs"
host=x86_64-unknown-linux-gnu
parent=b676a640c76193a0e241d2517a64e37e156659b9
candidate=eb15cd3dc0ab0404f8ad18589569e05a70a4d401
mkdir -p "$receipts"
cd "$base"
sha256sum --check SHA256SUMS
python3 -IB prepare.py "$root/rust" > "$receipts/transport.json"
cd "$root/rust"
bundle="$study/packed-objects.bundle"
printf '%s  %s\n' 5f12c7fed6e3b36fd151d7d498156fcb73fd6b9d2918c8a534071fce413752a9 "$bundle" | sha256sum --check
git bundle verify "$bundle"
git fetch --no-tags --no-recurse-submodules "$bundle" refs/heads/charlie/compact-inactive-branch-objects
test "$(git rev-parse FETCH_HEAD)" = "$candidate"
git merge-base --is-ancestor "$parent" "$candidate"
test "$(git rev-parse "$candidate:compiler")" = b8fa7ed926a6589fb8fd7e913b0eaadc36875611
test "$(git rev-parse "$parent:compiler")" = 1df08b3c45a7e6fa3739a8e753132f707f97896a
flags=(--ci false --set build.submodules=false --set rust.omit-git-hash=true
       --set rust.debug-assertions=false --set rust.lto=off --set llvm.download-ci-llvm=true)
for role in C P; do
    rev="$candidate"
    if [[ "$role" == P ]]; then rev="$parent"; fi
    git switch --detach "$rev"
    git diff --exit-code --ignore-submodules=none
    python3 x.py "${flags[@]}" build --stage 1 -j8 compiler/rustc library 2>&1 | tee "$receipts/build-$role.log"
    python3 -IB "$study/runtime.py" freeze "build/$host/stage1" "$role" "$rev"
    cp "$root/capsule/$role.json" "$receipts/"
done
python3 -IB "$study/runtime.py" reopen > "$receipts/reopen.json"
