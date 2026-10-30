#!/usr/bin/env bash
set -euo pipefail
host=x86_64-unknown-linux-gnu
triple=aarch64-unknown-linux-gnu
src="$QA_ROOT/rust"
study="$GITHUB_WORKSPACE/scripts/ohm-aarch64-linux"
transport="$GITHUB_WORKSPACE/scripts/ohm-apple-zmij/source-transport"
log="$QA_ROOT/receipts"
subject="$GITHUB_WORKSPACE/scripts/ohm-aarch64-registers"
parent=444c0273a2e2bc0b161e988d43c882349bc2d7a6
child=d3538b42a2dc56edb9bffbc9cc2373fb93c35054
if [[ "${1:-build}" == build ]]; then
    (cd "$transport" && sha256sum --check SHA256SUMS)
    python3 -IB "$study/qualify.py" release
    python3 -IB "$transport/prepare.py" "$src" > "$log/parent-transport.json"
    cd "$src"
    git switch --detach "$parent"
    test "$(git hash-object -t commit "$subject/transport/commit")" = "$child"
    gzip -dc "$subject/transport/source.patch.gz" | git apply --index --binary -
    test "$(git write-tree)" = 5b86b3516db45ace6bbbdd536bbff9face291fbd
    git hash-object -w -t commit "$subject/transport/commit" > "$log/new-commit"
    test "$(cat "$log/new-commit")" = "$child"
    git update-ref --no-deref HEAD "$child" "$parent"
fi
cd "$src"
test "$(git rev-parse "$child^")" = "$parent"
test "$(git rev-parse "$parent:compiler")" = 1276de33b6b3042ee60ca5866621a63a12de8894
test "$(git rev-parse "$child:compiler")" = e589051c299788c2ee8ab47a06cbc5fe1a300211
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
    test "$(git rev-parse HEAD:tests/run-make/ohm-checked-dep-info)" = 91a93f4659cef7c6789c2d89804cc49f988f680a
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
    python3 -IB "$subject/subject.py" freeze "$role" host
    python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$triple" library 2>&1 | tee "$log/target-build-$role.log"
    python3 -IB "$subject/subject.py" freeze "$role" target
done
