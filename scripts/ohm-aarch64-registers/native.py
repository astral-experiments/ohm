"""Exercise the cross assembler and ordinary declared native search with the original, physically restored compiler."""
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-linux"))
import qualify as q
import runtime as rt
from study import MISSING, RECHECK, digest, need, save, sha

AS = "/usr/bin/aarch64-linux-gnu-as"
COPY = "/usr/bin/aarch64-linux-gnu-objcopy"
AR = "/usr/bin/aarch64-linux-gnu-ar"


def assembly():
    folder = rt.ROOT / "gnu-as"
    folder.mkdir()
    env = rt.environment()
    root = rt.LOG / "gnu-as"
    text = {}
    for name, option in (("base", ""), ("vector", "/*v0*/"), ("general", "/*x19*/"),
                         ("both", "/*v31*/\n/*x0*/"), ("file", '.incbin "payload"')):
        (folder / "payload").write_bytes(b"\x2c\x4f\x87")
        (folder / "code.s").write_text(".text\n.globl foo\nfoo:\n" + option + "\nmov w0, #17\nret\n")
        rt.record([AS, "-o", "tmp.o", "code.s"], root / name / "as", folder, env)
        rt.record([COPY, "--only-section=.text", "-O", "binary", "tmp.o", "text"], root / name / "copy", folder, env)
        text[name] = (folder / "text").read_bytes()
    need(all(text[k] == text["base"] for k in ("vector", "general", "both")) and text["file"] != text["base"], "assembler changed code")
    (folder / "payload").unlink()
    failure = rt.record([AS, "-o", "missing.o", "code.s"], root / "missing", folder, env, 1)
    need(b"payload" in failure.stderr and not (folder / "missing.o").exists(), "GNU accepted a missing .incbin")
    save(root / "complete.json", {n: v.hex() for n, v in text.items()})


def links():
    env = rt.environment()
    root = rt.LOG / "native-provider"
    fixture = rt.ROOT / "native-search-fixture"
    (fixture / "src").mkdir(parents=True)
    for n in ("early", "late"):
        (fixture / n).mkdir()
    home = rt.ROOT / "provider-work"
    target, shared = home / "target", home / "shared"
    env.update(CARGO_HOME=str(home / "cargo-home"), CARGO_TARGET_DIR=str(target), CARGO_BUILD_BUILD_DIR=str(shared),
               CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=q.CROSS)
    (fixture / "Cargo.toml").write_text('[package]\nname="qa-probe"\nversion="0.1.0"\nedition="2021"\n')
    (fixture / "src/main.rs").write_text('''
#[link(name="qa_ohm_external", kind="static")]
unsafe extern "C" { fn qa_value() -> i32; }
fn main() {
    let mut x = unsafe { qa_value() } as usize;
    let mut v: core::arch::aarch64::int32x4_t = unsafe { core::mem::zeroed() };
    unsafe { core::arch::asm!("/*{0}*/", inout(reg) x); core::arch::asm!("/*{:v}*/", inout(vreg) v); }
    std::hint::black_box(v);
    println!("{}", x);
}
''')
    (fixture / "build.rs").write_text('''
fn main() {
    let p = std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    for n in ["early", "late"] {
        println!("cargo:rerun-if-changed={n}");
        println!("cargo:rustc-link-search=native={}", p.join(n).display());
    }
}
''')
    def provider(name, value):
        path = fixture / name / "libqa_ohm_external.a"
        (fixture / "impl.c").write_text("int qa_value(void){return " + str(value) + ";}\n")
        rt.record([q.CROSS, "-c", "-o", "impl.o", "impl.c"], root / ("create-" + str(value)) / "gcc", fixture, env)
        rt.record([AR, "rcs", path, "impl.o"], root / ("create-" + str(value)) / "ar", fixture, env)
        return path.read_bytes()
    def command(name, status, value, accepted=()):
        folder = root / name
        folder.mkdir(parents=True)
        trace = folder / "open"
        trace.mkdir()
        cmd = ["strace", "-ff", "-qq", "-s", "2048", "-e", "trace=execve,execveat,openat",
               "-o", trace / "proc", "cargo", "+ohm", "build", "--target", rt.TARGET,
               "--offline", "-j4", "--message-format=json"]
        proc = rt.record(cmd, folder / "cargo", fixture, env, status)
        streams = {p.name: p.read_bytes() for p in sorted(trace.glob("proc.*"))}
        raw = b"".join(n.encode() + b"\n" + data + b"\n" for n, data in streams.items())
        observed, active = [], []
        for pid, stream in streams.items():
            rows = stream.decode(errors="replace").splitlines()
            ld = any(re.search(r'^execve\("[^"]*/(?:aarch64-linux-gnu-)?(?:ld|ld.bfd|ld.lld)",', l)
                     and l.endswith("= 0") for l in rows)
            for line in rows:
                if "libqa_ohm_external.a" in line and "openat(" in line:
                    observed.append([pid, ld, line])
                    if ld and re.search(r"= \d+$", line):
                        active.append(line)
        for n in accepted:
            need(any(str(fixture / n / "libqa_ohm_external.a") in line for line in active), f"{name}: missing real link input {n}")
        exe = target / rt.TARGET / "debug/qa-probe"
        exe_sha = None
        if status == 0:
            need(rt.elf(exe.read_bytes(), (2, 3)), "not an AArch64 native executable")
            actual = rt.record([*q.QEMU, exe], folder / "qemu", fixture, env).stdout
            need(actual == str(value).encode() + b"\n", f"bad runtime: {name} {actual}")
            exe_sha = sha(exe)
        else:
            need(b"qa_ohm_external" in proc.stdout + proc.stderr, "expected linker/provider diagnostic")
        data = {"code": status, "runtime": value, "elf": exe_sha, "opens": observed, "trace": digest(raw)}
        save(folder / "complete.json", data)
        (folder / "exec-open.gz").write_bytes(rt.gzip.compress(raw, compresslevel=2, mtime=0))
        need(digest(rt.gzip.decompress((folder / "exec-open.gz").read_bytes())) == digest(raw), "trace custody")
        for n in streams:
            (trace / n).unlink()
        return data
    def empty(name, warm, status, value, accepted):
        parked = home / ("park-" + name)
        parked.mkdir()
        for loc in (target, shared):
            loc.rename(parked / loc.name)
        result = command(name, status, value, accepted)
        if status == 0:
            need(result["elf"] == warm["elf"], "changed complete native output")
        for loc in (target, shared):
            loc.rename(parked / ("cold-" + loc.name))
            (parked / loc.name).rename(loc)
    late = fixture / "late/libqa_ohm_external.a"
    early = fixture / "early/libqa_ohm_external.a"
    original = provider("late", 17)
    command("cold-late", 0, 17, ["late"])
    preferred = provider("early", 29)
    warm = command("inserted-earlier", 0, 29, ["early"])
    empty("empty-earlier", warm, 0, 29, ["early"])
    command("unchanged", 0, 29)
    early.write_bytes(b"!<arch>\n"+b"\0"*60)
    late.unlink()
    failed = command("malformed", 101, None, ["early"])
    empty("empty-malformed", failed, 101, None, ["early"])
    early.unlink()
    absent = command("missing", 101, None)
    empty("empty-missing", absent, 101, None, [])
    late.write_bytes(original)
    good = command("repaired", 0, 17, ["late"])
    empty("empty-repaired", good, 0, 17, ["late"])
    # The compiler's own rlib classification independently preserves bundled files.
    (fixture / "bundle.rs").write_text('''#[link(name="qa_ohm_external",kind="static")] unsafe extern "C" { fn qa_value()->i32; }
pub fn value()->usize{let mut x=unsafe{qa_value()} as usize;unsafe{core::arch::asm!("/*{0}*/",inout(reg)x);}x}''')
    for n, lib in (("17", original), ("29", preferred)):
        late.write_bytes(lib)
        rc = rt.record(["rustc", "+ohm", "bundle.rs", "--edition=2021", "--crate-type=rlib", "--target", rt.TARGET,
                        "-Zohm-check-relink-inputs", "--emit=link,dep-info=-", "-L", "native=" + str(late.parent)],
                       root / ("bundle-" + n), fixture, env)
        need(MISSING in rc.stdout and RECHECK not in rc.stdout, "bundled native library incorrectly reusable")
        shutil.copyfile(fixture / "libbundle.rlib", root / ("bundle-" + n + ".rlib"))
    need(sha(root / "bundle-17.rlib") != sha(root / "bundle-29.rlib"), "updated bundled archive lost")
    save(root / "complete.json", {"lower": digest(original), "earlier": digest(preferred), "different": True,
                                  "cases": sorted(p.name for p in root.iterdir() if (p / "complete.json").is_file())})


if __name__ == "__main__":
    assembly()
    links()
