#!/usr/bin/env bash
set -euo pipefail

role=$1
base=cad56cdf53143b0a539218169451ca12f7064ff3
host=x86_64-unknown-linux-gnu
test "$(git rev-parse HEAD)" = "$base"
case "$role" in
  base) tip=138b9b74a947f60ba231d42608866d70b55843eb ;;
  parser) tip=13a07e28cd4ad2553cd70f26df61dddfed55da1c ;;
  queries) tip=5f6e2050215d0863b39669e8b01b982c10c3bfe2 ;;
esac
git diff "$base" "$tip" -- compiler | git apply -
git add -N compiler
git diff --quiet "$tip" -- compiler
rsync --delete --exclude .git -a ../clippy/ src/tools/clippy/
OPTIMIZED=1
git submodule update --init --depth 1 library/backtrace
kit="$RUNNER_TEMP/kits/$role"
mkdir -p "$kit/bin" "$kit/lib/rustlib/$host" "$RUNNER_TEMP/packages"
git add -N compiler
git diff --full-index --binary -- compiler > "$kit/compiler.patch"
git rev-parse "$tip" > "$kit/revision"
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
env -u GITHUB_ACTIONS python3 x.py --ci false build --stage 1 library src/tools/clippy
stage="build/$host/stage1"
cp -L "$stage/bin/rustc" "$kit/bin/"
cp -L "$stage/lib"/librustc_driver-*.so "$kit/lib/"
cp -aL "$stage/lib/rustlib/$host/lib" "$kit/lib/rustlib/$host/"
if [[ -d "$stage/lib/rustlib/$host/codegen-backends" ]]; then
  cp -aL "$stage/lib/rustlib/$host/codegen-backends" "$kit/lib/rustlib/$host/"
fi
for tool in clippy-driver cargo-clippy; do
  lib=$(find build/"$host" -path "*/stage*-tools-bin/$tool" -print -quit)
  if [[ -z "$lib" ]]; then
    lib=$(find build/"$host" -name "$tool" -type f -executable -print -quit)
  fi
  cp -L "$lib" "$kit/bin/"
done
shopt -s nullglob
for lib in "$stage/lib"/libLLVM*.so* build/"$host"/ci-llvm/lib/libLLVM*.so*; do
  cp -L "$lib" "$kit/lib/"
done
"$kit/bin/clippy-driver" --version
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
