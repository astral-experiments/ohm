#!/usr/bin/env bash
# bash reproduce.sh [stale|fixed|report] [rustup-toolchain]
# Requires native GNU x86-64 Linux, bash, Python 3, cc, ar, and the installed Ohm Cargo/rustc.
set -euo pipefail
umask 022
expect=${1:-report}; tool=${2:-ohm}
case "$expect" in stale|fixed|report) ;; *) echo "expected stale, fixed, or report" >&2; exit 2;; esac
work=$(mktemp -d "${TMPDIR:-/tmp}/ohm-gnu-script-XXXXXXXX"); work=$(realpath "$work")
trap 'rm -rf -- "$work"' EXIT
cd "$work"; mkdir -p native src engine/src tmp
target="$work/target"; shared="$work/build"
envargs=("HOME=$HOME" "PATH=$PATH" "RUSTUP_HOME=${RUSTUP_HOME:-$HOME/.rustup}" "LC_ALL=C"
         "TMPDIR=$work/tmp" "CARGO_HOME=$work/cargo-home" "CARGO_TARGET_DIR=$target" "CARGO_BUILD_BUILD_DIR=$shared" "CARGO_NET_OFFLINE=true" "CARGO_INCREMENTAL=1")
env -i "${envargs[@]}" rustc "+$tool" -vV | grep -Fx 'host: x86_64-unknown-linux-gnu'
env -i "${envargs[@]}" cargo "+$tool" -vV
cat > Cargo.toml <<'EOF'
[package]
name = "reader"
version = "0.0.0"
edition = "2021"
[dependencies]
engine = { path = "engine" }
EOF
printf '[package]\nname="engine"\nversion="0.0.0"\nedition="2021"\n' > engine/Cargo.toml
cat > engine/src/lib.rs <<'EOF'
pub fn register(x: i32) -> i32 {
    unsafe { core::arch::asm!("/* {0:e} */", in(reg) x, options(nostack, nomem, preserves_flags)); }
    x
}
EOF
cat > src/main.rs <<'EOF'
extern "C" { fn answer() -> i32; }
fn main() { println!("{}", engine::register(unsafe { answer() })); }
EOF
cat > build.rs <<'EOF'
fn main() {
    let dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();
    for file in ["libanswer.a", "libohm_private.a", "libohm_alternate.a", "libgcc_s.so"] {
        println!("cargo::rerun-if-changed={dir}/native/{file}");
    }
    println!("cargo::rustc-link-search=native={dir}/native");
    println!("cargo::rustc-link-lib=static=answer");
}
EOF
archive() {
    printf '%s\n' "$2" | cc -fPIC -x c -c -o "native/$1.o" -
    ar rcs "native/lib$1.a" "native/$1.o"
}
archive answer 'extern int provider(void);int answer(void){return provider();}'
archive ohm_private 'int provider(void){return 17;}'
archive ohm_alternate 'int provider(void){return 29;}'
libgcc=$(realpath -e "$(cc -print-file-name=libgcc_s.so.1)")
printf 'GROUP ( %s -lohm_private )\n' "$libgcc" > native/libgcc_s.so
provider=native/libohm_private.so
select_input() {
    if [[ $1 == absent ]]; then rm -f -- "$provider"; return; fi
    local dest="$work/native/libohm_alternate.a"
    if [[ $1 == bad ]]; then dest=/missing-ohm-transitive-provider; fi
    python3 - "$provider" "$dest" <<'PY'
from pathlib import Path
import os, sys
p=Path(sys.argv[1]); old=p.stat() if p.exists() else None
p.write_text(f'INPUT ( {sys.argv[2]} )'.ljust(512)+'\n')
if old:
    os.utime(p,ns=(old.st_atime_ns,old.st_mtime_ns))
    s=p.stat()
    assert (s.st_ino,s.st_size,s.st_mtime_ns)==(old.st_ino,old.st_size,old.st_mtime_ns)
PY
}
visit() {
    local name=$1 status=0 value=- digest=- seals
    select_input "$2"
    if [[ ${3:-warm} == empty ]]; then rm -rf -- "$target" "$shared"; fi
    env -i "${envargs[@]}" cargo "+$tool" build --offline --message-format=json > "$name.json" 2> "$name.err" || status=$?
    if [[ $status == 0 ]]; then
        value=$("$target/debug/reader"); digest=$(sha256sum "$target/debug/reader" | cut -d' ' -f1)
    elif [[ $status != 101 ]] || ! grep -Fq '/missing-ohm-transitive-provider' "$name.json" "$name.err"; then
        cat "$name.json" "$name.err" >&2; exit 1
    fi
    seals=$(find "$target" "$shared" -path '*/declared-native/seal' -type f -print 2>/dev/null | wc -l || true)
    printf '%s %s %s %s %s\n' "$name" "$status" "$value" "$seals" "$digest" | tee -a visits.txt
}
printf 'phase cargo native seals whole-ELF-SHA256\n'
visit cold absent; visit warm absent; visit new valid; visit malformed bad; visit repair valid; visit removed absent
visit empty-new valid empty; visit empty-malformed bad empty; visit empty-old absent empty
# Confirm the actual Cargo can produce a declared-link cache entry in this environment.
rm -f native/libgcc_s.so
sed -i 's/, "libgcc_s.so"//' build.rs
archive answer 'int answer(void){return 17;}'
visit declared-cold absent empty; visit declared-warm absent
python3 - "$expect" <<'PY'
import sys
from pathlib import Path
r={p[0]:(int(p[1]),p[2],int(p[3]),p[4]) for l in Path('visits.txt').read_text().splitlines() if (p:=l.split())}
assert all(r[n][0:2]==(0,'17') for n in ('cold','warm','removed','empty-old'))
assert r['empty-new'][0:2]==(0,'29') and r['empty-malformed'][0:2]==(101,'-')
assert r['empty-new'][3]!=r['empty-old'][3]==r['cold'][3]
stale=all(r[n][0:2]==(0,'17') and r[n][3]==r['empty-old'][3] for n in ('new','malformed','repair')) and r['warm'][2]>0
fixed=all(r[n][0:2]==(0,'29') and r[n][3]==r['empty-new'][3] for n in ('new','repair')) and r['malformed'][0:2]==(101,'-')
eligible=r['declared-cold'][2]>0 and r['declared-warm'][2]>0 and r['declared-warm'][0:2]==(0,'17')
result='stale' if eligible and stale else 'fixed' if eligible and fixed else 'inconclusive'
print('outcome',result)
if result=='inconclusive' or sys.argv[1] not in ('report',result):sys.exit(1)
PY
