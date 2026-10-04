#!/usr/bin/env bash
# Run one phase per host; never overlap builds and runtime measurements.
set -euo pipefail
root=/tmp/ohm-release-campaign/llvm
workload=${1:?ruff or uv}
phase=${2:?screen, paired, cold, or runtime}
case "$workload" in ruff|uv) ;; *) exit 2;; esac
export PATH="$root/toolchain/bin:$PATH"
export RUSTC="$root/toolchain/bin/rustc"
export RUSTDOC="$root/toolchain/bin/rustdoc"
export CARGO_HOME=/tmp/codex-cargo-home
export CARGO_TARGET_DIR="/tmp/codex-cargo-targets/$workload/isolated/release-llvm/screening"
unset CARGO_BUILD_BUILD_DIR CARGO_BUILD_JOBS CARGO_INCREMENTAL RUSTFLAGS CARGO_ENCODED_RUSTFLAGS RUSTC_WRAPPER RUSTC_WORKSPACE_WRAPPER CARGO_PROFILE_RELEASE_LTO CARGO_PROFILE_RELEASE_CODEGEN_UNITS CARGO_PROFILE_RELEASE_OPT_LEVEL CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST
case "$phase" in
  screen)
    for variant in baseline merge; do
      python3 "$root/harness/measure-v3.py" --output "$root/evidence/screen-$workload" --name "$variant" --cwd "$root/$workload" -- "$root/toolchain/bin/cargo" rustc --locked --offline --release -p "$workload" --bin "$workload" -- "-Zllvm-plugins=$root/plugins/$variant.so"
      cp "$CARGO_TARGET_DIR/release/$workload" "$root/evidence/binaries/$variant-$workload"
    done
    ;;
  paired) python3 "$root/harness/paired-$workload.py" ;;
  cold) python3 "$root/harness/cold-pairs.py" "$workload" ;;
  runtime)
    # UV needs one public-index warmup; the final measured suite is fully offline.
    if [ "$workload" = uv ]; then
      python3 "$root/harness/measure-v3.py" --output "$root/evidence/runtime-uv" --name runtime-suite --cwd "$root" -- python3 "$root/harness/runtime-uv.py"
    fi
    python3 "$root/harness/measure-v3.py" --output "$root/evidence/runtime-$workload-final" --name runtime-suite --cwd "$root" -- python3 "$root/harness/runtime-$workload-final.py"
    touch "$root/evidence/runtime-$workload-final/complete"
    ;;
  *) exit 2 ;;
esac
