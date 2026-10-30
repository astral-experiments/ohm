"""Freeze and physically reopen the two source-built host and cross-target runtimes."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-apple-zmij"))
from study import CHILD, CARGO_SOURCE, MISSING, PARENT, RECHECK, digest, git, load, need, physical, save, sha, text_git

HOST = "x86_64-unknown-linux-gnu"
TARGET = "aarch64-unknown-linux-gnu"
ROOT = Path(os.environ.get("QA_ROOT", "/unused-linux-aarch64-qa"))
LOG = ROOT / "receipts"
SDK = ROOT / "rustup/toolchains/ohm"
CAP = ROOT / "capsule"
WORK = ROOT / "work"
RUFF = ROOT / "ruff"
WILD = "lib/rustlib/" + HOST + "/bin/wild-ld/ld.bfd"
TOOLS = {"bin/cargo": "1d06626bcef3c5235676ada14f4b7107f56e98aef620f81b0e0c47381dbe0add",
         WILD: "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"}
BASE = "ohm-1.99.0-20-" + HOST
ARCHIVE = BASE + ".tar.gz"
A = "edb64a2ee39b2f2951614f98d53ec4e4197f55149ff794c911bd81bc7f870b15"
SIDE = "31164b6c91d93ee4662b50ae347b1165983fc92521cf6faeb4cd322de2f10ec0"
PROV = "1bac589fa5a90d9d9ddcbbc1e847ff2bf8cb500aa58df02b0dd8c2933ceeb15a"


def room(bootstrap=False):
    available = int(next(l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemAvailable:")).split()[1]) * 1024
    disk = shutil.disk_usage(ROOT).free
    need(platform.system() == "Linux" and platform.machine() == "x86_64", "wrong physical host")
    need(disk > (32 if bootstrap else 6) * 2**30 and available > (6 if bootstrap else 2) * 2**30,
         f"insufficient physical capacity: disk={disk} memory={available}")
    return {"disk": disk, "memory": available}


def release():
    room(True)
    inbox = ROOT / "inbox"
    archive, side, prov = (inbox / n for n in (ARCHIVE, ARCHIVE + ".sha256", BASE + "-provenance.json"))
    need(archive.stat().st_size == 359585079 and sha(archive) == A and sha(side) == SIDE and sha(prov) == PROV,
         "signed release archive, published sidecar or provenance changed")
    need(side.read_text().split() == [A, ARCHIVE], "detached release checksum mismatch")
    wanted = {"cargo/bin/cargo": "bin/cargo", "rustc/" + WILD: WILD}
    found = {}
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            parts = Path(member.name).parts
            tail = "/".join(parts[1:])
            if tail not in wanted:
                continue
            n = wanted[tail]
            need(member.isfile() and 0 < member.size < 50_000_000 and n not in found, "invalid signed member")
            path = SDK / n
            path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, path.open("xb") as out:
                shutil.copyfileobj(source, out)
            path.chmod(0o755)
            found[n] = sha(path)
    need(found == TOOLS, "signed Cargo or Wild bytes changed")
    save(LOG / "release.json", {"release": A, "checksum": SIDE, "provenance": PROV, "tools": found})


def inventory(stage):
    files = [stage / "bin/rustc", *(stage / "lib").glob("*.so*")]
    for triple in (HOST, TARGET):
        leaf = stage / "lib/rustlib" / triple / "lib"
        members = sorted(p for p in leaf.rglob("*") if p.is_file())
        for component in ("core", "std", "alloc", "proc_macro", "test"):
            need(any(p.name.startswith("lib" + component + "-") and p.suffix == ".rlib" for p in members),
                 f"missing complete {triple} {component} rlib")
        files.extend(members)
    host_bin = stage / "lib/rustlib" / HOST / "bin"
    for name in ("rust-lld", "gcc-ld"):
        item = host_bin / name
        if item.is_file():
            files.append(item)
        elif item.is_dir():
            files.extend(sorted(p for p in item.rglob("*") if p.is_file()))
    need(any(p.name.startswith("libLLVM") for p in files) and any(p.name.startswith("librustc_driver") for p in files),
         "incomplete compiler/LLVM runtime")
    names = [p.relative_to(stage).as_posix() for p in files]
    need(len(files) == len(set(names)) and 60 < len(files) < 600, "unexpected runtime roster")
    return sorted(files)


def freeze(role):
    source = ROOT / "rust"
    rev = {"P": PARENT, "C": CHILD}[role]
    need(text_git(source, "rev-parse", "HEAD") == rev and not git(source, "status", "--porcelain", "--untracked-files=no"),
         "compiler source changed")
    stage = source / "build" / HOST / "stage1"
    files = {}
    objects = CAP / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    for p in inventory(stage):
        key = sha(p)
        obj = objects / key
        if not obj.exists():
            shutil.copyfile(p, obj)
        need(sha(obj) == key, "compiler capsule changed during export")
        files[str(p.relative_to(stage))] = [key, p.stat().st_size, p.stat().st_mode & 0o777]
    stage0 = stage.parent / "stage0/bin"
    binding = {"stage0_rustc": sha(stage0 / "rustc"), "stage0_cargo": sha(stage0 / "cargo"),
               "stage0_source": sha(source / "src/stage0"), "std_tree": text_git(source, "rev-parse", "HEAD:library")}
    save(LOG / (role + "-sdk.json"), {"source": rev, "tree": text_git(source, "rev-parse", "HEAD^{tree}"),
                                      "files": files, "bootstrap": binding})


def select(role):
    products = {r: load(LOG / (r + "-sdk.json")) for r in "PC"}
    p, c = products.values()
    need(p["files"].keys() == c["files"].keys() and p["bootstrap"] == c["bootstrap"], "unequal kit inputs")
    diff = [n for n in p["files"] if p["files"][n] != c["files"][n]]
    need(any(n.startswith("lib/librustc_driver") for n in diff) and
         all(n == "bin/rustc" or n.startswith(("lib/librustc_driver", "lib/librustc_codegen_llvm")) for n in diff),
         f"unexpected host/target runtime or compiled library difference: {diff}")
    for name, (key, size, mode) in products[role]["files"].items():
        target = SDK / name
        if not target.exists() or name in diff:
            base = CAP / "objects" / key
            need(base.stat().st_size == size and sha(base) == key, "changed frozen SDK member")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".installing")
            need(not tmp.exists(), "unexpected pending role change")
            shutil.copyfile(base, tmp)
            tmp.chmod(mode)
            os.replace(tmp, target)
        need(target.stat().st_size == size and sha(target) == key, f"wrong live {role} member {name}")
    need(all(sha(SDK / name) == key for name, key in TOOLS.items()), "signed tools changed")
    return diff


def environment():
    env = {k: os.environ[k] for k in ("HOME", "PATH", "USER", "LOGNAME", "SSL_CERT_FILE", "SSL_CERT_DIR") if k in os.environ}
    env.update(RUSTUP_HOME=str(ROOT / "rustup"), CARGO_HOME=str(WORK / "cargo-home"),
               CARGO_TARGET_DIR=str(WORK / "target"), CARGO_BUILD_BUILD_DIR=str(WORK / "shared"),
               CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never", CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
               RUSTUP_AUTO_INSTALL="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, LC_ALL="C", TZ="UTC")
    return env


def record(argv, folder, cwd, env, code=0):
    folder.mkdir(parents=True, exist_ok=False)
    args = list(map(str, argv))
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=1800)
    for name, data in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        (folder / (name + ".gz")).write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
    save(folder / "command.json", {"argv": args, "exit": proc.returncode, "stdout": digest(proc.stdout), "stderr": digest(proc.stderr)})
    need(proc.returncode == code, f"{folder.name}: expected {code}, got {proc.returncode}: {proc.stderr[-1600:]!r}")
    return proc


def probe(role):
    env = environment()
    env.update(CARGO_HOME=str(ROOT / "diagnostic-cargo-home"), CARGO_TARGET_DIR=str(ROOT / "diagnostic-target"),
               CARGO_BUILD_BUILD_DIR=str(ROOT / "diagnostic-shared"))
    out = LOG / ("probe-" + role)
    out.mkdir()
    r = ["rustc", "+ohm"]
    ids = {}
    for exe in ("cargo", "rustc"):
        p = Path(record(["rustup", "which", "--toolchain", "ohm", exe], out / (exe + "-which"), ROOT, env).stdout.decode().strip())
        need(p.samefile(SDK / "bin" / exe), "wrong proxy dispatch")
        ids[exe] = physical(p)
    cv = record(["cargo", "+ohm", "-Vv"], out / "cargo", ROOT, env).stdout
    rv = record(r + ["-vV"], out / "rustc", ROOT, env).stdout
    cfg = record(r + ["--print", "cfg", "--target", TARGET], out / "cfg", ROOT, env).stdout.splitlines()
    need(CARGO_SOURCE.encode() in cv and HOST.encode() in rv, "wrong Cargo or compiler host")
    need({b'target_arch="aarch64"', b'target_os="linux"', b'target_env="gnu"', b'target_feature="neon"'} <= set(cfg)
         and b"miri" not in cfg, "not the actual zmij cfg")
    folder = ROOT / ("smoke-" + role)
    folder.mkdir()
    (folder / "mac.rs").write_text('extern crate proc_macro; use proc_macro::TokenStream;\n#[proc_macro] pub fn answer(_:TokenStream)->TokenStream {"29u32".parse().unwrap()}\n')
    (folder / "main.rs").write_text('fn main(){println!("{}", mac::answer!());}\n')
    record(r + ["--crate-name", "mac", "--crate-type", "proc-macro", "mac.rs", "-o", "libmac.so"], out / "macro", folder, env)
    caller = r + ["--edition=2024", "main.rs", "--extern", "mac=libmac.so"]
    record(caller + ["-o", "host"], out / "host-link", folder, env)
    need(record(["./host"], out / "host-run", folder, env).stdout == b"29\n", "host expansion changed")
    live = dict(env, LD_DEBUG="files")
    probe = record(caller + ["--target", TARGET, "-C", "linker=/usr/bin/aarch64-linux-gnu-gcc", "-o", "cross"],
                   out / "target-link", folder, live)
    driver, = list((SDK / "lib").glob("librustc_driver-*.so"))
    need(any(b"calling init:" in l and driver.name.encode() in l and str(SDK).encode() in l for l in probe.stderr.splitlines()),
         "ELF loader did not report the selected kit driver")
    need(elf((folder / "cross").read_bytes(), (2, 3)), "not an AArch64 executable")
    need(record(["/usr/bin/qemu-aarch64", "-L", "/usr/aarch64-linux-gnu", "./cross"], out / "target-run", folder, env).stdout == b"29\n",
         "cross-compiled program failed")
    asm_path = "tests/run-make/ohm-checked-dep-info/inline.rs"
    source = ROOT / "rust"
    need(text_git(source, "rev-parse", CHILD + ":" + asm_path) == "6a36b0f4ef7febb78a53dea5528b011fa74b3695", "wrong checked-in asm source")
    (folder / "inline.rs").write_bytes(git(source, "show", CHILD + ":" + asm_path))
    payload = folder / "payload.bin"
    payload.write_bytes(b"\xa5")
    for cfg, expected in (("ordinary", role == "P"), ("vector_modifier", True), ("vector_directive", True)):
        flags = [*r, "inline.rs", "--target", TARGET, "--crate-type=rlib", "-Zohm-check-relink-inputs", "--cfg", cfg, "--emit=link,dep-info=-"]
        rules = record(flags, out / ("asm-" + cfg), folder, env).stdout
        need((MISSING in rules) == expected and (RECHECK in rules) == (not expected), "incorrect Linux AArch64 " + cfg + " dependencies")
    payload.unlink()
    archive = folder / "libinline.rlib"
    need(archive.is_file(), "missing successful inline assembly archive")
    archive.unlink()
    missing = record(flags, out / "asm-missing-file", folder, env, 1)
    need(b"payload.bin" in missing.stderr and not archive.exists(), "missing real inline assembler input accepted or misdiagnosed")
    save(out / "verified.json", {"rustc": ids, "driver": physical(driver), "rustc_version": digest(rv), "cfg": sorted(x.decode() for x in cfg)})


def elf(data, kinds):
    return len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01" and int.from_bytes(data[16:18], "little") in kinds and data[18:20] == b"\xb7\0"
