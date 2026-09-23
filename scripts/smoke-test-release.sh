#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: smoke-test-release.sh RELEASE_DIRECTORY TOOLCHAIN TARGET CLIPPY_REVISION" >&2
  exit 2
fi
RELEASE_DIRECTORY="$(cd -- "$1" && pwd)"
OHM_TOOLCHAIN=$2
OHM_TARGET=$3
CLIPPY_REVISION=$4
if [[ ! "$OHM_TOOLCHAIN" =~ ^ohm-[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*$ ||
      ! "$CLIPPY_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid toolchain name or Clippy revision" >&2
  exit 1
fi
case "$OHM_TARGET" in
  aarch64-apple-darwin|x86_64-unknown-linux-gnu) ;;
  *) echo "unsupported release target: $OHM_TARGET" >&2; exit 1 ;;
esac

(
  cd "$RELEASE_DIRECTORY"
  shasum -a 256 --check "$OHM_TOOLCHAIN-$OHM_TARGET.tar.gz.sha256"
  grep '  ohm-installer\.sh$' SHA256SUMS | shasum -a 256 --check
)

smoke_root="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/ohm-smoke.XXXXXX")"
trap 'rm -rf "$smoke_root"' EXIT

toolchain_root="$smoke_root/toolchain"
export CARGO_HOME="$smoke_root/cargo-home"
export RUSTUP_HOME="$smoke_root/rustup-home"
mkdir -p "$CARGO_HOME" "$RUSTUP_HOME"
OHM_DOWNLOAD_URL="file://$RELEASE_DIRECTORY" \
  OHM_INSTALL_DIR="$toolchain_root" \
  sh "$RELEASE_DIRECTORY/ohm-installer.sh"

case "$OHM_TARGET" in
  *-apple-darwin)
    otool -L "$toolchain_root/bin/cargo" | awk '
      NR == 1 { next }
      $1 ~ /^\/usr\/lib\// || $1 ~ /^\/System\/Library\// { next }
      {
        print "non-system Cargo dependency: " $1 > "/dev/stderr"
        invalid = 1
      }
      END { exit invalid }
    '
    ;;
  *-unknown-linux-gnu)
    if ldd "$toolchain_root/bin/cargo" \
      | grep -E '(^|[[:space:]])lib(ssl|crypto|curl|git2|ssh2|z|zstd)[.-]'; then
      echo 'Cargo links against nonportable native libraries' >&2
      exit 1
    fi
    ;;
esac

unset RUSTC_BOOTSTRAP
rustc +"$OHM_TOOLCHAIN" -Z help \
  | grep -F 'public-api-hash' >/dev/null
rustdoc +"$OHM_TOOLCHAIN" --version
cargo +"$OHM_TOOLCHAIN" -Z help \
  | grep -F 'relink-only' >/dev/null
clippy_revision="${CLIPPY_REVISION:0:10}"
"$toolchain_root/bin/cargo-clippy" --version \
  | grep -F "$clippy_revision" >/dev/null
"$toolchain_root/bin/clippy-driver" --version \
  | grep -F "$clippy_revision" >/dev/null
rustfmt_version="$("$toolchain_root/bin/rustfmt" --version)"
cargo_fmt_version="$("$toolchain_root/bin/cargo-fmt" --version)"
grep -F 'rustfmt ' <<< "$rustfmt_version" >/dev/null
[[ "$cargo_fmt_version" == "$rustfmt_version" ]]

smoke_crate="$smoke_root/crate"
mkdir -p "$smoke_crate/src" "$smoke_crate/macros/src"
cat > "$smoke_crate/Cargo.toml" <<'EOF'
[package]
name = "ohm-smoke"
version = "0.0.0"
edition = "2024"

[dependencies]
ohm-smoke-macros = { path = "macros" }
EOF
cat > "$smoke_crate/macros/Cargo.toml" <<'EOF'
[package]
name = "ohm-smoke-macros"
version = "0.0.0"
edition = "2024"

[lib]
proc-macro = true
EOF
cat > "$smoke_crate/macros/src/lib.rs" <<'EOF'
use proc_macro::TokenStream;

#[proc_macro]
pub fn make_answer(_: TokenStream) -> TokenStream {
    "fn answer() -> u32 { 42 }".parse().unwrap()
}
EOF
cat > "$smoke_crate/src/main.rs" <<'EOF'
ohm_smoke_macros::make_answer!();

fn main() {
    assert!(invert(false));
    assert_eq!(answer(), 42);
}

fn invert(value: bool) -> bool {
    !value
}
EOF

rustc_wrapper="$smoke_root/rustc-wrapper"
cat > "$rustc_wrapper" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

crate_name=
has_public_api_hash=false
has_proc_macro_cache=false
previous_argument=
for argument in "$@"; do
  if [[ "$previous_argument" == "--crate-name" ]]; then
    crate_name="$argument"
  fi
  case "$argument" in
    -Zpublic-api-hash) has_public_api_hash=true ;;
    -Zcache-proc-macros) has_proc_macro_cache=true ;;
  esac
  previous_argument="$argument"
done

if [[ "$crate_name" == "ohm_smoke" ]]; then
  case "${OHM_EXPECT_DEFAULTS:?}" in
    enabled)
      if [[ "$has_public_api_hash" != true || "$has_proc_macro_cache" != true ]]; then
        echo "Ohm defaults missing from ohm_smoke rustc invocation" >&2
        exit 1
      fi
      ;;
    disabled)
      if [[ "$has_public_api_hash" == true || "$has_proc_macro_cache" == true ]]; then
        echo "Ohm defaults present on disabled ohm_smoke rustc invocation" >&2
        exit 1
      fi
      ;;
    *)
      echo "invalid OHM_EXPECT_DEFAULTS value" >&2
      exit 1
      ;;
  esac
  printf '%s\n' "$OHM_EXPECT_DEFAULTS" >> "${OHM_RUSTC_LOG:?}"
fi

exec "$@"
EOF
chmod +x "$rustc_wrapper"

unset CARGO_BUILD_RUSTFLAGS CARGO_ENCODED_RUSTFLAGS RUSTFLAGS RUSTC_WORKSPACE_WRAPPER
defaults_log="$smoke_root/defaults-rustc-args"
OHM_EXPECT_DEFAULTS=enabled \
  OHM_RUSTC_LOG="$defaults_log" \
  RUSTC_WRAPPER="$rustc_wrapper" \
  CARGO_TARGET_DIR="$smoke_root/defaults-target" \
  cargo +"$OHM_TOOLCHAIN" build --manifest-path "$smoke_crate/Cargo.toml"
grep -Fx enabled "$defaults_log" >/dev/null

disabled_log="$smoke_root/disabled-rustc-args"
OHM_EXPECT_DEFAULTS=disabled \
  OHM_RUSTC_LOG="$disabled_log" \
  RUSTC_WRAPPER="$rustc_wrapper" \
  CARGO_TARGET_DIR="$smoke_root/disabled-target" \
  cargo +"$OHM_TOOLCHAIN" -Zohm-defaults=no build \
    --manifest-path "$smoke_crate/Cargo.toml"
grep -Fx disabled "$disabled_log" >/dev/null

# Linking a Wasm executable requires both the target's std and the host's rust-lld.
CARGO_TARGET_DIR="$smoke_root/defaults-target" \
  cargo +"$OHM_TOOLCHAIN" build --target wasm32-unknown-unknown \
    --manifest-path "$smoke_crate/Cargo.toml"
python3 - "$smoke_root/defaults-target/wasm32-unknown-unknown/debug/ohm-smoke.wasm" <<'PY'
import pathlib
import sys

with pathlib.Path(sys.argv[1]).open("rb") as wasm:
    assert wasm.read(8) == b"\0asm\x01\0\0\0", "invalid Wasm module"
PY

if [[ "$OHM_TARGET" == x86_64-unknown-linux-gnu ]] && \
  jq -e '.bundled_tools.wild' "$RELEASE_DIRECTORY/$OHM_TOOLCHAIN.json" >/dev/null; then
  readelf --string-dump=.comment "$smoke_root/defaults-target/debug/ohm-smoke" \
    | grep -i 'Wild' >/dev/null
  for linker in lld wild; do
    CARGO_TARGET_DIR="$smoke_root/linker-target" \
      cargo +"$OHM_TOOLCHAIN" -Zohm-linker="$linker" run \
      --manifest-path "$smoke_crate/Cargo.toml"
    CARGO_TARGET_DIR="$smoke_root/linker-target" \
      cargo +"$OHM_TOOLCHAIN" -Zohm-linker="$linker" test \
      --manifest-path "$smoke_crate/Cargo.toml"
    readelf --string-dump=.comment "$smoke_root/linker-target/debug/ohm-smoke" \
      | grep -i "$linker" >/dev/null
  done
fi

cargo +"$OHM_TOOLCHAIN" clippy --manifest-path "$smoke_crate/Cargo.toml" -- -D warnings
cargo +"$OHM_TOOLCHAIN" doc --no-deps --manifest-path "$smoke_crate/Cargo.toml"
cargo +"$OHM_TOOLCHAIN" fmt --manifest-path "$smoke_crate/Cargo.toml" -- --check

env -u RUST_SRC_PATH RUSTUP_TOOLCHAIN="$OHM_TOOLCHAIN" \
  "${RUST_ANALYZER:?set RUST_ANALYZER to the stock rust-analyzer executable}" \
  diagnostics "$smoke_crate"

# Exercise cache admission with the installed compiler, without a wrapper.
registry_crate="$smoke_root/registry-crate"
mkdir -p "$registry_crate/src"
cat > "$registry_crate/Cargo.toml" <<'EOF'
[package]
name = "ohm-registry-smoke"
version = "0.0.0"
edition = "2024"

[dependencies]
itoa = "=1.0.15"
EOF
cat > "$registry_crate/src/main.rs" <<'EOF'
fn main() {
    println!("{}", itoa::Buffer::new().format(42));
}
EOF
(
  set -euo pipefail
  cargo_bin="$(dirname "$(command -v cargo)")"
  export PATH="$cargo_bin:/usr/bin:/bin"
  export CARGO_BUILD_BUILD_DIR="$smoke_root/shared-build"
  export CARGO_TARGET_DIR="$smoke_root/registry-target"
  cargo +"$OHM_TOOLCHAIN" build --manifest-path "$registry_crate/Cargo.toml" -v \
    2>&1 | tee "$smoke_root/registry-build.log"
  if [[ "$OHM_TARGET" == x86_64-unknown-linux-gnu ]]; then
    grep -F 'bin/wild-ld' "$smoke_root/registry-build.log"
  fi
  registry_outputs="$CARGO_BUILD_BUILD_DIR/debug/build/registries"
  test -d "$registry_outputs"
  find "$registry_outputs" -name 'libitoa-*.rmeta' | grep . >/dev/null

  cp -R "$registry_crate" "$smoke_root/registry-sibling"
  export CARGO_TARGET_DIR="$smoke_root/registry-sibling-target"
  cargo +"$OHM_TOOLCHAIN" build --locked --offline \
    --manifest-path "$smoke_root/registry-sibling/Cargo.toml" -v \
    2>&1 | tee "$smoke_root/registry-sibling.log"
  grep -E 'Fresh itoa v1\.0\.15' "$smoke_root/registry-sibling.log"
  if grep -E 'Compiling itoa ' "$smoke_root/registry-sibling.log"; then
    exit 1
  fi

  cargo +"$OHM_TOOLCHAIN" check --locked --offline \
    --manifest-path "$smoke_root/registry-sibling/Cargo.toml" -v \
    2>&1 | tee "$smoke_root/registry-check.log"
  grep -E 'Fresh itoa v1\.0\.15' "$smoke_root/registry-check.log"
  if grep -E '(Checking|Compiling) itoa ' "$smoke_root/registry-check.log"; then
    exit 1
  fi
  if find "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces" \
    -name '.ohm-worktree-seed-deny-v7' | grep .; then
    exit 1
  fi
)
