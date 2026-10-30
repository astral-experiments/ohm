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
    python3 -IB "$transport/crc/prepare.py" "$src" > "$log/crc-transport.json"
    python3 -IB "$GITHUB_WORKSPACE/scripts/ohm-cgu-reuse/transport/prepare.py" "$src" > "$log/cgu-transport.json"
    python3 -IB "$GITHUB_WORKSPACE/scripts/ohm-cgu-reuse/transport/guard/prepare.py" "$src" > "$log/external-input-transport.json"
    python3 -IB "$GITHUB_WORKSPACE/scripts/ohm-cgu-reuse/transport/host/prepare.py" "$src" > "$log/host-tuning-transport.json"
fi
cd "$src"
parent=82911b516fb35608fd70ada4deb6f8429277f410
child=f69f7b7cf6de57972b310900decfac2d3a0c6fd6
test "$(git rev-parse "$child^^^")" = "$parent"
test "$(git rev-parse "$parent:compiler")" = 019b0e35598a054357018731f9f8426c0520fc53
test "$(git rev-parse "$child:compiler")" = 543ce83b4251f8c9ec0d55cee2833dd224396b90
test "$(git rev-parse "$parent:library")" = "$(git rev-parse "$child:library")"
test "$(git diff --name-only "$parent" "$child" | wc -l)" -eq 4
flags=(--ci false --set build.submodules=false --set rust.omit-git-hash=true
       --set rust.debug-assertions=false --set rust.lto=off --set llvm.download-ci-llvm=true
       --set "target.$triple.cc=/usr/bin/aarch64-linux-gnu-gcc" --set "target.$triple.cxx=/usr/bin/aarch64-linux-gnu-g++"
       --set "target.$triple.ar=/usr/bin/aarch64-linux-gnu-ar" --set "target.$triple.linker=/usr/bin/aarch64-linux-gnu-gcc")
export CC_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-gcc
export CXX_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-g++
export AR_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-ar
if [[ "${1:-build}" == test-host ]]; then
    test "$(git rev-parse HEAD)" = "$child"
    test "$(git rev-parse HEAD:tests/run-make/ohm-checked-dep-info)" = 2dacccc466da9358208d2b9a6d3cc36bac5e6fdf
    test "$(git rev-parse HEAD:tests/run-make/ohm-relink-assembler-inputs)" = beeb6077efdac7e300e94a653b13a40a3f8a78bb
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
