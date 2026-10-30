#!/usr/bin/env bash
set -euo pipefail
host=x86_64-unknown-linux-gnu
triple=aarch64-unknown-linux-gnu
src="$QA_ROOT/rust"
study="$GITHUB_WORKSPACE/scripts/ohm-aarch64-linux"
transport="$GITHUB_WORKSPACE/scripts/ohm-apple-zmij/source-transport"
log="$QA_ROOT/receipts"
subject="$GITHUB_WORKSPACE/scripts/ohm-aarch64-compact"
prior="$GITHUB_WORKSPACE/scripts/ohm-aarch64-registers"
versioned="$GITHUB_WORKSPACE/scripts/ohm-aarch64-versioned"
final=8f42a1c11e66c2a55299914d5025e4fa7549ead4
upstream=444c0273a2e2bc0b161e988d43c882349bc2d7a6
parent=d3538b42a2dc56edb9bffbc9cc2373fb93c35054
child=f2edebc7a23b809749fb0cc44dd6ac902ca448ff
if [[ "${1:-build}" == build ]]; then
    (cd "$transport" && sha256sum --check SHA256SUMS)
    python3 -IB "$study/qualify.py" release
    python3 -IB "$transport/prepare.py" "$src" > "$log/parent-transport.json"
    cd "$src"
    git switch --detach "$upstream"
    test "$(git hash-object -t commit "$prior/transport/commit")" = "$parent"
    gzip -dc "$prior/transport/source.patch.gz" | git apply --index --binary -
    test "$(git write-tree)" = 5b86b3516db45ace6bbbdd536bbff9face291fbd
    test "$(git hash-object -w -t commit "$prior/transport/commit")" = "$parent"
    git update-ref --no-deref HEAD "$parent" "$upstream"
    test "$(git hash-object -t commit "$subject/transport/commit")" = "$child"
    gzip -dc "$subject/transport/source.patch.gz" | git apply --index --binary -
    test "$(git write-tree)" = c4205f70f7807a7309d0a56abc7d772cb18899c1
    git hash-object -w -t commit "$subject/transport/commit" > "$log/new-commit"
    test "$(cat "$log/new-commit")" = "$child"
    git update-ref --no-deref HEAD "$child" "$parent"
    python3 -IB "$versioned/transport.py" rust "$src" > "$log/versioned-source.json"
fi
cd "$src"
test "$(git rev-parse "$child^")" = "$parent"
test "$(git rev-parse "$parent:compiler")" = e589051c299788c2ee8ab47a06cbc5fe1a300211
test "$(git rev-parse "$child:compiler")" = df7a2fe72fd4caf809227afb0e95af130a38ab37
test "$(git rev-parse "$parent:library")" = "$(git rev-parse "$child:library")"
test "$(git diff --name-only "$parent" "$child" | wc -l)" -eq 3
test "$(git rev-parse "$final^")" = "$child"
test "$(git rev-parse "$final:compiler")" = c7a15a94598064f09fbe38e8d520bb9bf759cb99
test "$(git rev-parse "$final:library")" = "$(git rev-parse "$child:library")"
flags=(--ci false --set build.submodules=false --set rust.omit-git-hash=true
       --set rust.debug-assertions=false --set rust.lto=off --set llvm.download-ci-llvm=true
       --set "target.$triple.cc=/usr/bin/aarch64-linux-gnu-gcc" --set "target.$triple.cxx=/usr/bin/aarch64-linux-gnu-g++"
       --set "target.$triple.ar=/usr/bin/aarch64-linux-gnu-ar" --set "target.$triple.linker=/usr/bin/aarch64-linux-gnu-gcc")
export CC_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-gcc
export CXX_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-g++
export AR_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-ar
if [[ "${1:-build}" == test-host ]]; then
    test "$(git rev-parse HEAD)" = "$final"
    test "$(git rev-parse HEAD:tests/run-make/ohm-checked-dep-info)" = 657358008593afa8e425f6989cbe01d7ac17bdca
    test "$(git rev-parse HEAD:tests/run-make/ohm-relink-assembler-inputs)" = bdb3382107ead13c43d1b04272904de4c3a4c532
    python3 x.py "${flags[@]}" test --stage 1 -j8 --host "$host" --target "$host" \
      tests/run-make/ohm-checked-dep-info tests/run-make/ohm-relink-assembler-inputs 2>&1 | tee "$log/x86-host-run-make.log"
    printf '%s\n' "$final" > "$log/x86-host-run-make-pass"
    exit 0
fi
git switch --detach "$final"
git diff --exit-code --ignore-submodules=none
python3 -IB "$study/qualify.py" room
python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$host" compiler/rustc library 2>&1 | tee "$log/host-build-C.log"
python3 -IB "$versioned/version_kit.py" freeze C host
python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$triple" library 2>&1 | tee "$log/target-build-C.log"
python3 -IB "$versioned/version_kit.py" freeze C target
