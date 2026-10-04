#!/usr/bin/env bash
# stage1 is the patched compiler and its matching standard library.
set -euo pipefail
root=/tmp/ohm-release-campaign/llvm
export RUSTC="$root/stage1/bin/rustc"
export CARGO_HOME=/tmp/codex-cargo-home
export CARGO_TARGET_DIR=/tmp/codex-cargo-targets/ruff/isolated/release-llvm/flag-validation
unset CARGO_BUILD_BUILD_DIR CARGO_BUILD_JOBS CARGO_INCREMENTAL RUSTFLAGS CARGO_ENCODED_RUSTFLAGS RUSTC_WRAPPER RUSTC_WORKSPACE_WRAPPER CARGO_PROFILE_RELEASE_LTO CARGO_PROFILE_RELEASE_CODEGEN_UNITS CARGO_PROFILE_RELEASE_OPT_LEVEL CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST
parity="$root/evidence/flag-parity-reproduction"
python3 "$root/harness/measure-v3.py" --output "$parity" --name flag --cwd "$root/ruff" -- "$root/toolchain/bin/cargo" rustc --locked --offline --release -p ruff --bin ruff -- -Zearly-lto-merge-functions=yes -Zautodiff=PrintPasses
cp "$CARGO_TARGET_DIR/release/ruff" "$parity/flag-ruff"
python3 "$root/harness/measure-v3.py" --output "$parity" --name plugin --cwd "$root/ruff" -- "$root/toolchain/bin/cargo" rustc --locked --offline --release -p ruff --bin ruff -- "-Zllvm-plugins=$root/plugins/merge.so" -Zautodiff=PrintPasses
cp "$CARGO_TARGET_DIR/release/ruff" "$parity/plugin-ruff"
python3 "$root/harness/validate-parity.py" "$parity"
# This contextual actual-flag pair makes a fresh, identical edit for both variants.
python3 "$root/harness/actual-flag-pair.py"
