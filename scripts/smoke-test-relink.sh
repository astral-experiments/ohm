#!/usr/bin/env bash
set -euo pipefail

toolchain=$1
project=$2
mkdir -p "$project/src" "$project/engine/src"
cd "$project"
export CARGO_INCREMENTAL=1 CARGO_TARGET_DIR="$project/target" CARGO_BUILD_BUILD_DIR="$project/build"

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
cat >engine/src/lib.rs <<'EOF'
mod revision;
pub use revision::value;

pub fn payload<T>() -> u32 {
    let byte: u32;
    unsafe {
        core::arch::asm!(
            "jmp 3f", "2:",
            concat!(".incbin \"", env!("CARGO_MANIFEST_DIR"), "/payload.bin\""),
            "3:", "movzx {byte:e}, byte ptr [rip + 2b]",
            byte = out(reg) byte,
            options(nostack, preserves_flags),
        );
    }
    byte
}
EOF
cat >src/main.rs <<'EOF'
#![forbid(unsafe_code)]
fn main() {
    println!("{}:{}", engine::value(), engine::payload::<u8>());
}
EOF
build() { cargo +"$toolchain" -Zrelink-only=yes build --offline; }

echo 'pub fn value() -> u8 { 1 }' >engine/src/revision.rs
printf '\021' >engine/payload.bin
build
[[ "$("$CARGO_TARGET_DIR/debug/reader")" == "1:17" ]]
printf '\035' >engine/payload.bin
build
[[ "$("$CARGO_TARGET_DIR/debug/reader")" == "1:29" ]]

echo 'pub fn value() -> u8 { 2 }' >engine/src/revision.rs
rm engine/payload.bin
if build >missing.log 2>&1; then
  echo "The build unexpectedly succeeded with a missing assembler input." >&2
  exit 1
fi
grep -F 'incbin file' missing.log | grep -F 'payload.bin'
printf '\045' >engine/payload.bin
build
[[ "$("$CARGO_TARGET_DIR/debug/reader")" == "2:37" ]]
