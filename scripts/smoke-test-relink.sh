#!/usr/bin/env bash
set -euo pipefail

toolchain=$1
project=$2
mkdir -p "$project/src" "$project/engine/src"
cd "$project"
export CARGO_INCREMENTAL=1

cat >Cargo.toml <<'EOF'
[package]
name = "reader"
version = "0.1.0"
edition = "2021"

[dependencies]
engine = { path = "engine" }
EOF
cat >engine/Cargo.toml <<'EOF'
[package]
name = "engine"
version = "0.1.0"
edition = "2021"
EOF

check_output() {
  local actual
  actual=$("$CARGO_TARGET_DIR/debug/reader")
  if [[ "$actual" != "$1" ]]; then
    echo "$case_name: expected $1, got $actual" >&2
    exit 1
  fi
}

exercise() {
  local mode=$1
  shift
  local case_name="$object-$mode"
  export CARGO_TARGET_DIR="$project/$case_name/target" CARGO_BUILD_BUILD_DIR="$project/$case_name/build"
  echo "Checking $case_name"
  echo 'pub fn value() -> u8 { 1 }' >engine/src/revision.rs
  printf '\021' >engine/payload.bin
  cargo +"$toolchain" "$@" build --offline
  check_output 1:17
  printf '\035' >engine/payload.bin
  cargo +"$toolchain" "$@" build --offline
  check_output 1:29
  echo 'pub fn value() -> u8 { 2 }' >engine/src/revision.rs
  cargo +"$toolchain" "$@" build --offline
  check_output 2:29
  rm engine/payload.bin
  if cargo +"$toolchain" "$@" build --offline >missing.log 2>&1; then
    echo "$case_name: build succeeded with a missing assembler input" >&2
    exit 1
  fi
  grep -F 'incbin file' missing.log | grep -F 'payload.bin'
  printf '\045' >engine/payload.bin
  cargo +"$toolchain" "$@" build --offline
  check_output 2:37
}

for object in executable library; do
  cat >engine/src/lib.rs <<'EOF'
mod revision;
pub use revision::value;
EOF
  if [[ "$object" == executable ]]; then
    # The executable instantiates this generic function from the dependency.
    cat >>engine/src/lib.rs <<'EOF'
pub fn payload<T>() -> u32 {
    let byte: u32;
    unsafe {
        #[cfg(target_arch = "x86_64")]
        core::arch::asm!(
            "jmp 3f", "2:",
            concat!(".incbin \"", env!("CARGO_MANIFEST_DIR"), "/payload.bin\""),
            "3:", "movzx {byte:e}, byte ptr [rip + 2b]",
            byte = out(reg) byte, options(nostack, preserves_flags),
        );
        #[cfg(target_arch = "aarch64")]
        core::arch::asm!(
            "b 3f", "2:",
            concat!(".incbin \"", env!("CARGO_MANIFEST_DIR"), "/payload.bin\""),
            ".balign 4", "3:", "adr {ptr}, 2b", "ldrb {byte:w}, [{ptr}]",
            ptr = out(reg) _, byte = out(reg) byte, options(nostack, preserves_flags),
        );
    }
    byte
}
EOF
    reader='engine::payload::<u8>()'
  else
    # The dependency's rlib owns the bytes even when its consumer has no assembly.
    cat >>engine/src/lib.rs <<'EOF'
extern "C" { static PAYLOAD: u8; }
core::arch::global_asm!(
    ".globl {payload}", "{payload}:",
    concat!(".incbin \"", env!("CARGO_MANIFEST_DIR"), "/payload.bin\""),
    ".balign 4", payload = sym PAYLOAD,
);
#[inline(never)]
pub fn payload() -> u8 { unsafe { core::ptr::read_volatile(&raw const PAYLOAD) } }
EOF
    reader='engine::payload()'
  fi
  cat >src/main.rs <<EOF
#![forbid(unsafe_code)]
fn main() { println!("{}:{}", engine::value(), $reader); }
EOF
  exercise default
  exercise relink -Zrelink-only=yes
done
