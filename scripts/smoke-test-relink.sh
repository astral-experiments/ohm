#!/usr/bin/env bash
set -euo pipefail
unset CDPATH

toolchain=$1
project=$2
# The native link driver requires private build directories.
umask 077
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

# Both binaries call into the same native archive. Its path and the build
# script's output stay constant when we replace the archive.
mkdir -p declared/src/bin declared/native declared/engine/src
cp Cargo.toml declared/
cp engine/Cargo.toml declared/engine/
cd declared
write_build_script() {
  cat >build.rs <<EOF
fn main() {
    let dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();
    println!("cargo::rerun-if-changed=$1");
    let earlier = "${2:-}";
    if !earlier.is_empty() {
        println!("cargo::rerun-if-changed={dir}/{earlier}");
        println!("cargo::rustc-link-search=native={dir}/{earlier}");
    }
    println!("cargo::rustc-link-search=native={dir}/native");
    println!("cargo::rustc-link-lib=static=answer");
}
EOF
}
write_build_script native/libanswer.a
echo 'pub fn register(value: usize) -> usize { value }' >engine/src/lib.rs
cat >src/bin/first.rs <<'EOF'
extern "C" { fn answer() -> i32; }
fn main() { println!("{}", engine::register(unsafe { answer() } as usize)); }
EOF
cp src/bin/first.rs src/bin/second.rs
export CARGO_TARGET_DIR="$PWD/target" CARGO_BUILD_BUILD_DIR="$PWD/build"
export OHM_SMOKE_LINK_LOG="$PWD/links"
cat >count-links <<'EOF'
#!/bin/sh
for arg do
  if [ "$arg" = -o ]; then echo link >>"$OHM_SMOKE_LINK_LOG"; break; fi
done
exec cc "$@"
EOF
chmod +x count-links
host=$(rustc +"$toolchain" -vV | awk '/^host: / {print $2}')
linker_var="CARGO_TARGET_$(printf '%s' "$host" | tr '[:lower:]-' '[:upper:]_')_LINKER"
export "$linker_var=$PWD/count-links"
write_archive() {
  printf 'int answer(void) { return %s; }\n' "$1" | cc -x c -c -o answer.o -
  ar rcs next-answer.a answer.o
  cat next-answer.a >"${2:-native/libanswer.a}"
}
check_links() {
  local bin actual count
  : >"$OHM_SMOKE_LINK_LOG"
  cargo +"$toolchain" build --bins --offline
  for bin in first second; do
    actual=$("$CARGO_TARGET_DIR/debug/$bin")
    if [[ "$actual" != "$1" ]]; then
      echo "$bin: expected $1, got $actual" >&2
      exit 1
    fi
  done
  if (( $# == 1 )); then
    return
  fi
  count=$(wc -l <"$OHM_SMOKE_LINK_LOG")
  if (( count != $2 )); then
    echo "Expected $2 linker calls for two executables returning $1, observed $count" >&2
    exit 1
  fi
}
check_declared_archive() {
  write_archive 17
  cargo +"$toolchain" build --bins --offline
  check_links 17 0
  write_archive 29
  check_links 29 2
  check_links 29 0
}
check_declared_archive

# Register-only assembly makes rustc mark this dependency for native-link rechecks.
cat >engine/src/lib.rs <<'EOF'
pub fn register(value: usize) -> usize {
    unsafe {
        core::arch::asm!("/* {0} */", in(reg) value, options(nomem, nostack, preserves_flags));
    }
    value
}
EOF
# An unchanged marked dependency must also skip both links when the archive is declared.
export CARGO_TARGET_DIR="$PWD/marked-declared-target" CARGO_BUILD_BUILD_DIR="$PWD/marked-declared-build"
check_declared_archive

# Leave the archive off the build script's watch list and preserve its inode and timestamp.
write_build_script build.rs
export CARGO_TARGET_DIR="$PWD/marked-target" CARGO_BUILD_BUILD_DIR="$PWD/marked-build"
write_archive 17
cargo +"$toolchain" build --bins --offline
check_links 17
touch -r native/libanswer.a archive-timestamp
archive_size=$(wc -c <native/libanswer.a)
write_archive 29
test "$(wc -c <native/libanswer.a)" = "$archive_size"
touch -r archive-timestamp native/libanswer.a
check_links 29 2
: >"$OHM_SMOKE_LINK_LOG"
echo 'malformed archive' >native/libanswer.a
if cargo +"$toolchain" build --bins --offline >bad-archive.log 2>&1; then
  echo "Build succeeded with a malformed native archive" >&2
  exit 1
fi
test -s "$OHM_SMOKE_LINK_LOG"
grep -F 'libanswer.a' bad-archive.log
write_archive 37
check_links 37 2

# Keep the original archive unchanged while a watched search directory gains and loses a library.
earlier_native=$(mktemp -d earlier-native.XXXXXX)
write_build_script native/libanswer.a "$earlier_native"
export CARGO_TARGET_DIR="$PWD/shadow-target" CARGO_BUILD_BUILD_DIR="$PWD/shadow-build"
write_archive 29
check_links 29
write_archive 41 "$earlier_native/libanswer.a"
check_links 41 2
rm "$earlier_native/libanswer.a"
check_links 29 2
rmdir "$earlier_native"
