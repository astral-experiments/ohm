#!/usr/bin/env bash
set -euo pipefail

role=$1
base=af392995e5ca93b70fc487b45dfdf6604dbbbc84
host=x86_64-unknown-linux-gnu
test "$(git rev-parse HEAD)" = "$base"
if [[ -n "${COMPILER_REF:-}" && "$COMPILER_REF" != "$base" ]]; then
  [[ "$COMPILER_REF" =~ ^[0-9a-f]{40}$ ]]
  git cat-file -e "$COMPILER_REF^{commit}" || git fetch --no-tags origin "$COMPILER_REF"
  git diff --binary "$base" "$COMPILER_REF" -- compiler > "$RUNNER_TEMP/commit.patch"
  if [[ -s "$RUNNER_TEMP/commit.patch" ]]; then
    git apply "$RUNNER_TEMP/commit.patch"
  fi
fi
if [[ -n "${EXPERIMENT_PATCH:-}" ]]; then
  printf '%s' "$EXPERIMENT_PATCH" | base64 -d | gzip -dc > "$RUNNER_TEMP/experiment.patch"
  sha256sum "$RUNNER_TEMP/experiment.patch"
  git apply --include='compiler/*' "$RUNNER_TEMP/experiment.patch"
fi
unset EXPERIMENT_PATCH
git submodule update --init --depth 1 library/backtrace
kit="$RUNNER_TEMP/kits/$role"
mkdir -p "$kit/bin" "$kit/lib/rustlib/$host" "$RUNNER_TEMP/packages"
git add -N compiler
git diff --full-index --binary -- compiler > "$kit/compiler.patch"
git rev-parse HEAD > "$kit/revision"
cat > bootstrap.toml <<'TOML'
profile = "compiler"
change-id = "ignore"
[build]
allocator = "jemalloc"
submodules = false
description = "ohm-1.100.0-3"
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
fi
touch "$kit/bootstrap.patch"
if [[ "${OPTIMIZED:-}" == 1 && "${STAGE_TWO:-}" != true ]]; then
  # Bootstrap normally adds cross-crate Rust LTO flags starting at stage 2.
  # Use its existing flags for both single-stage benchmark kits.
  bootstrap=src/bootstrap/src/core/build_steps/compile.rs
  test "$(grep -Fc 'if is_lto_stage(build_compiler) {' "$bootstrap")" = 1
  sed -i 's/if is_lto_stage(build_compiler) {/if is_lto_stage(build_compiler) || matches!(builder.config.rust_lto, RustcLto::Thin) {/' "$bootstrap"
  git diff -- "$bootstrap" > "$kit/bootstrap.patch"
fi
if [[ -n "${PROFILED:-}" ]]; then
  # Match the release allocator and enable bootstrap's PGO flags for stage 1.
  sed -i '/^\[rust\]$/a mimalloc = true' bootstrap.toml
  sed -i 's/^lld = false$/lld = true/' bootstrap.toml
  if [[ "${STAGE_TWO:-}" != true ]]; then
    pgo_bootstrap=src/bootstrap/src/core/builder/cargo.rs
    sed -i '/fn apply_pgo(/,/let has_profile/ s/build_compiler.stage != 1/build_compiler.stage > 1/' "$pgo_bootstrap"
    ! git diff --quiet -- "$pgo_bootstrap" || exit 1
    git diff -- "$pgo_bootstrap" >> "$kit/bootstrap.patch"
  fi
  mkdir -p "$RUNNER_TEMP/profiles"
  if [[ "$PROFILED" == train ]]; then
    cat >>bootstrap.toml <<TOML
[pgo.rustc]
generate = "$RUNNER_TEMP/profiles"
TOML
  else
    cat >>bootstrap.toml <<TOML
[pgo.rustc]
use = "$RUNNER_TEMP/profile/rustc.profdata"
TOML
    sha256sum "$RUNNER_TEMP/profile/rustc.profdata" > "$kit/profile.sha256"
  fi
fi
cp bootstrap.toml "$kit/"
sed -n 's/^const OHM_METADATA_EPOCH: u32 = \([0-9]*\);/\1/p' compiler/rustc_metadata/src/rmeta/mod.rs > "$kit/epoch"
test -s "$kit/epoch"
stage="build/$host/stage1"
if [[ "${STAGE_TWO:-}" == true ]]; then
  # Build the compiler that builds the candidate from the same base in every job.
  if [[ -s "$kit/compiler.patch" ]]; then
    git apply -R "$kit/compiler.patch"
  fi
  env -u GITHUB_ACTIONS python3 x.py --ci false build --stage 1 library
  sha256sum "$stage/bin/rustc" "$stage/lib"/librustc_driver-*.so | tee "$kit/stage1.sha256"
  if [[ -s "$kit/compiler.patch" ]]; then
    git apply "$kit/compiler.patch"
  fi
  env -u GITHUB_ACTIONS python3 x.py --ci false build --keep-stage 0 --enable-bolt-settings --stage 2 library
  stage="build/$host/stage2"
  readelf --relocs --wide "$stage/lib"/librustc_driver-*.so | awk '
    /^Relocation section/ { count = ($3 ~ /\.rela\.(dyn|plt)/) }
    count && /R_X86_64/ { n[$3]++ }
    END { for (k in n) print k,n[k] }
  ' | sort | tee "$kit/relocations.txt"
else
  env -u GITHUB_ACTIONS python3 x.py --ci false build --stage 1 library
fi
if [[ "${PROFILED:-}" == train ]]; then
  git submodule update --init --depth 1 src/tools/rustc-perf
  patch -d src/tools/rustc-perf -t -N -F 0 -p1 -i "$GITHUB_WORKSPACE/coordinator/release/rustc-perf-relocated-dependencies.patch"
  exe="$PWD/$stage/bin/rustc"
  LLVM_PROFILE_FILE="$RUNNER_TEMP/pgo-smoke.profraw" "$exe" -vV
  test -s "$RUNNER_TEMP/pgo-smoke.profraw"
  mv "$RUNNER_TEMP/profiles" "$RUNNER_TEMP/bootstrap-profiles"
  mkdir "$RUNNER_TEMP/profiles"
  stage0="$PWD/build/$host/stage0"
  cargo3="$RUNNER_TEMP/cargo"
  name="ohm-1.100.0-3-$host.tar.gz"
  curl -fsSL --retry 4 "https://github.com/astral-experiments/ohm/releases/download/ohm-1.100.0-3/$name" -o "$RUNNER_TEMP/$name"
  echo "7fc3d21a5efad6bff7be654b14e0e60aa2fbbfd11db198582788f3cc4bcf7591  $RUNNER_TEMP/$name" | sha256sum -c -
  tar -C "$RUNNER_TEMP" -xzf "$RUNNER_TEMP/$name" --strip-components=3 "rust-1.100.0-dev-$host/cargo/bin/cargo"
  (
    cd src/tools/rustc-perf
    export LLVM_PROFILE_FILE="$RUNNER_TEMP/profiles/default_%m_%p.profraw"
    export RUSTC="$stage0/bin/rustc" RUSTC_BOOTSTRAP=1 CARGO_UNSTABLE_OHM_LINKER=lld
    "$stage0/bin/cargo" build -p collector --bins
    "$stage0/bin/cargo" run -p collector --bin collector -- profile_local eprintln "$exe" --id Test --cargo "$cargo3" --profiles Check,Debug,Opt --scenarios All --exact-match externs,ctfe-stress-5,cargo-0.87.1,token-stream-stress,match-stress,tuple-stress,diesel-2.2.10,bitmaps-3.2.1,serde-1.0.219-new-solver --frontend-threads 1 --jobs 4
  )
  profdata="$(find build -name llvm-profdata -type f | head -1)"
  "$profdata" merge -o "$RUNNER_TEMP/packages/rustc.profdata" "$RUNNER_TEMP/profiles"
  sha256sum "$RUNNER_TEMP/packages/rustc.profdata"
  exit
fi
cp -L "$stage/bin/rustc" "$kit/bin/"
cp -L "$stage/lib"/librustc_driver-*.so "$kit/lib/"
cp -aL "$stage/lib/rustlib/$host/lib" "$kit/lib/rustlib/$host/"
if [[ -d "$stage/lib/rustlib/$host/bin" ]]; then
  cp -aL "$stage/lib/rustlib/$host/bin" "$kit/lib/rustlib/$host/"
fi
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
