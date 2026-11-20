#!/usr/bin/env bash
set -euo pipefail

role=$1
base=cad56cdf53143b0a539218169451ca12f7064ff3
host=x86_64-unknown-linux-gnu
test "$(git rev-parse HEAD)" = "$base"
case "$role" in
  control) ;;
  candidate)
    tips=(
      19b163d170f777a8fcf08e6e1a308e9223364113
      348b2bebc9cbabe0f7091e4f8e74a2fa06913653
      2b0876f27b147ff94f271a7a93795b8bb326731c
      7f5e45ead8f2c8553c1dcaa83a155e8613df1025
      8b48b7cf2dbc0ca895d48268a94c4fbd3e6681e2
    )
    paths=38
    if [[ "${PUBLIC_STACK:-}" == 1 ]]; then
      tips=(138b9b74a947f60ba231d42608866d70b55843eb)
      paths=36
    fi
    for tip in "${tips[@]}"; do
      git cat-file -e "$tip^{commit}" || git fetch --no-tags origin "$tip"
      git diff "$base" "$tip" -- compiler | git apply -
    done
    test "$(git diff --name-only | wc -l)" -eq "$paths"
    if [[ "${PROTOTYPE:-}" == 1 ]]; then
      git apply ../coordinator/scripts/uv-check-instructions/prototype.patch
    fi
    ;;
  *) exit 2 ;;
esac
git submodule update --init --depth 1 library/backtrace
kit="$RUNNER_TEMP/kits/$role"
mkdir -p "$kit/bin" "$kit/lib/rustlib/$host" "$RUNNER_TEMP/packages"
git diff --full-index --binary -- compiler > "$kit/compiler.patch"
git rev-parse HEAD > "$kit/revision"
cat > bootstrap.toml <<'TOML'
profile = "compiler"
change-id = "ignore"
[build]
allocator = "jemalloc"
submodules = false
description = "ohm-1.100.0-2"
locked-deps = true
docs = false
extended = false
profiler = false
[rust]
channel = "dev"
download-rustc = false
optimize = true
debug = false
debug-logging = false
frame-pointers = false
debug-assertions = false
debuginfo-level = 0
codegen-units = 16
codegen-units-std = 16
incremental = false
lto = "off"
lld = false
llvm-tools = false
[llvm]
download-ci-llvm = true
TOML
if [[ "${OPTIMIZED:-}" == 1 ]]; then
  sed -i -e 's/ = 16$/ = 1/' -e 's/lto = "off"/lto = "thin"/' bootstrap.toml
  # Bootstrap normally adds cross-crate Rust LTO flags starting at stage 2.
  # Use its existing flags for both single-stage benchmark kits.
  bootstrap=src/bootstrap/src/core/build_steps/compile.rs
  test "$(grep -Fc 'if is_lto_stage(build_compiler) {' "$bootstrap")" = 1
  sed -i 's/if is_lto_stage(build_compiler) {/if is_lto_stage(build_compiler) || matches!(builder.config.rust_lto, RustcLto::Thin) {/' "$bootstrap"
  git diff -- "$bootstrap" > "$kit/bootstrap.patch"
fi
cp bootstrap.toml "$kit/"
sed -n 's/^const OHM_METADATA_EPOCH: u32 = \([0-9]*\);/\1/p' compiler/rustc_metadata/src/rmeta/mod.rs > "$kit/epoch"
test -s "$kit/epoch"
env -u GITHUB_ACTIONS python3 x.py --ci false build --stage 1 library
stage="build/$host/stage1"
cp -L "$stage/bin/rustc" "$kit/bin/"
cp -L "$stage/lib"/librustc_driver-*.so "$kit/lib/"
cp -aL "$stage/lib/rustlib/$host/lib" "$kit/lib/rustlib/$host/"
if [[ -d "$stage/lib/rustlib/$host/codegen-backends" ]]; then
  cp -aL "$stage/lib/rustlib/$host/codegen-backends" "$kit/lib/rustlib/$host/"
fi
shopt -s nullglob
for lib in "$stage/lib"/libLLVM*.so* build/"$host"/ci-llvm/lib/libLLVM*.so*; do
  cp -L "$lib" "$kit/lib/"
done
"$kit/bin/rustc" -vV | tee "$kit/version.txt"
printf 'fn main() { println!("uv"); }\n' > "$RUNNER_TEMP/sample.rs"
"$kit/bin/rustc" "$RUNNER_TEMP/sample.rs" -o "$RUNNER_TEMP/sample"
test "$("$RUNNER_TEMP/sample")" = uv
(
  cd "$kit"
  find bin lib -type f -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
)
out="$RUNNER_TEMP/packages/$role.tar.zst"
tar -C "$RUNNER_TEMP/kits" -cf - "$role" | zstd -T4 -3 > "$out"
sha256sum "$out"
