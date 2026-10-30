#!/usr/bin/env bash
set -euo pipefail
host=x86_64-unknown-linux-gnu
triple=aarch64-unknown-linux-gnu
src="$QA_ROOT/rust"
study="$GITHUB_WORKSPACE/scripts/ohm-aarch64-linux"
transport="$GITHUB_WORKSPACE/scripts/ohm-apple-zmij/source-transport"
log="$QA_ROOT/receipts"
if [[ "${1:-build}" == build ]]; then
    (cd "$transport" && sha256sum --check SHA256SUMS)
    python3 -IB "$study/qualify.py" release
    python3 -IB "$transport/prepare.py" "$src" > "$log/transport.json"
fi
cd "$src"
parent=2035696c5316079f5b2e4373aee834839aac97e9
child=444c0273a2e2bc0b161e988d43c882349bc2d7a6
test "$(git rev-parse "$child^")" = "$parent"
test "$(git rev-parse "$parent:compiler")" = 294dda2b65f1801a085427c13923da2aa0938a40
test "$(git rev-parse "$child:compiler")" = 1276de33b6b3042ee60ca5866621a63a12de8894
test "$(git rev-parse "$parent:library")" = "$(git rev-parse "$child:library")"
test "$(git diff --name-only "$parent" "$child" | wc -l)" -eq 3
flags=(--ci false --set build.submodules=false --set rust.omit-git-hash=true
       --set rust.debug-assertions=false --set rust.lto=off --set llvm.download-ci-llvm=true
       --set "target.$triple.cc=/usr/bin/aarch64-linux-gnu-gcc" --set "target.$triple.cxx=/usr/bin/aarch64-linux-gnu-g++"
       --set "target.$triple.ar=/usr/bin/aarch64-linux-gnu-ar" --set "target.$triple.linker=/usr/bin/aarch64-linux-gnu-gcc")
export CC_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-gcc
export CXX_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-g++
export AR_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-ar
if [[ "${1:-build}" == test-host ]]; then
    test "$(git rev-parse HEAD)" = "$child"
    test "$(git rev-parse HEAD:tests/run-make/ohm-checked-dep-info)" = f402c0ba267d64b86769d9715519aa8502debbd5
    test "$(git rev-parse HEAD:tests/run-make/ohm-relink-assembler-inputs)" = bdb3382107ead13c43d1b04272904de4c3a4c532
    python3 x.py "${flags[@]}" test --stage 1 -j8 --host "$host" --target "$host" \
      tests/run-make/ohm-checked-dep-info tests/run-make/ohm-relink-assembler-inputs 2>&1 | tee "$log/x86-host-run-make.log"
    printf '%s\n' "$child" > "$log/x86-host-run-make-pass"
    exit 0
fi
for role in P C; do
    revision="$parent"
    if [[ "$role" == C ]]; then revision="$child"; fi
    git switch --detach "$revision"
    git diff --exit-code --ignore-submodules=none
    python3 -IB "$study/qualify.py" room
    python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$host" compiler/rustc library 2>&1 | tee "$log/host-build-$role.log"
    python3 -IB "$study/qualify.py" freeze "$role" host
    python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$triple" library 2>&1 | tee "$log/target-build-$role.log"
    python3 -IB "$study/qualify.py" freeze "$role" target
done
