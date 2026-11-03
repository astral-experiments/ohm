"""Exercise the real compiler and ordinary Cargo across literal content and allocation boundaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument("--rustup-home", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--role", choices=["parent", "candidate"], required=True)
parser.add_argument("--compiler-sha", required=True)
parser.add_argument("--wait-for-reserve", action="store_true")
args = parser.parse_args()
here = Path(__file__).resolve().parent
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=False)
workspace = out / "workspace"
base = {k: v for k, v in os.environ.items() if not k.startswith(("CARGO_", "RUST", "LD_PRELOAD"))}
base.update(RUSTUP_HOME=str(args.rustup_home.resolve()), CARGO_HOME=str(out / "cargo-home"), CARGO_NET_OFFLINE="true")
driver, = (args.rustup_home / "toolchains/ohm/lib").glob("librustc_driver-*.so")
def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
def save(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n")
def need(test, message):
    if not test:
        raise ValueError(message)
need(sha(driver) == args.compiler_sha, "incorrect registered compiler")
registration = json.loads((here / "registration.json").read_bytes())
for name, expected in registration["literal_controls"]["fixture"].items():
    clean = here / "literal-fixture" / name
    raw = clean.read_bytes()
    oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    rust_path = "tests/run-make/incremental-large-byte-literal/" + name
    need(sha(clean) == expected and registration["changed_sources"][rust_path]["C"] == oid, "unregistered fixture source")

def available():
    return int(re.search(r"^MemAvailable:\s*(\d+)", Path("/proc/meminfo").read_text(), re.M)[1]) * 1024
def cmd(argv, cwd, env, destination, code=0):
    if args.wait_for_reserve:
        while available() < (8 << 30) + (300 << 20):
            time.sleep(3)
        need(shutil.disk_usage(out).free >= (15 << 30) + (128 << 20), "disk admission")
    destination.mkdir(exist_ok=False)
    with (destination / "stdout").open("wb") as stdout, (destination / "stderr").open("wb") as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        while child.poll() is None:
            if args.wait_for_reserve and available() < (8 << 30):
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                save(destination / "refused.json", {"argv":argv,"reason":"shared host RAM reserve"})
                raise RuntimeError("shared host RAM reserve")
            time.sleep(.025 if args.wait_for_reserve else .08)
    save(destination / "command.json", {"argv":argv,"cwd":str(cwd),"exit":child.returncode})
    need(child.returncode == code, (argv, child.returncode, (destination / "stderr").read_text()[-1500:]))
    return (destination / "stdout").read_bytes()
def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
write(workspace / "Cargo.toml", '[workspace]\nmembers=["producer","app"]\nresolver="3"\n')
write(workspace / "producer/Cargo.toml", '[package]\nname="producer"\nversion="0.0.0"\nedition="2024"\n')
write(workspace / "app/Cargo.toml", '[package]\nname="literal_app"\nversion="0.0.0"\nedition="2024"\n[dependencies]\nproducer={path="../producer"}\n')
for package, source in [("producer","lib.rs"),("app","main.rs")]:
    p = workspace / package / "src" / source
    p.parent.mkdir()
    shutil.copyfile(here / "literal-fixture" / source, p)
asset = workspace / "producer/src/asset"
def set_asset(length, flag):
    data = bytearray(b"a" * length)
    data[length//2] = flag
    asset.write_bytes(data)
def env(history, incremental):
    return base | {"CARGO_TARGET_DIR":str(out / (history + "-target")), "CARGO_BUILD_BUILD_DIR":str(out / (history + "-build")), "CARGO_INCREMENTAL":str(int(incremental))}
cmd(["rustc","+ohm","-vV"],workspace,base,out/"version")
cmd(["cargo","+ohm","generate-lockfile","--offline"],workspace,env("warm",True),out/"lock")
records = {}
def run(name, history, length, flag, incremental=True, invalid=False, change=True):
    scope = out/name
    if change:
        set_asset(length,flag)
    need(asset.stat().st_size == length and asset.read_bytes()[length//2] == flag, "wrong source bytes")
    before = sha(asset)
    e = env(history,incremental)
    argv = ["cargo","+ohm","build","-p","literal_app","--locked","--offline","-j1","--message-format=json"]
    raw = cmd(argv,workspace,e,scope,101 if invalid else 0)
    rows = [json.loads(line) for line in raw.splitlines()]
    need(rows[-1] == {"reason":"build-finished","success":not invalid}, (name, "incomplete Cargo rows"))
    errs = [m["message"] for m in rows if m["reason"] == "compiler-message" and m["message"]["level"] == "error"]
    dirty = [m["target"]["name"] for m in rows if m["reason"]=="compiler-artifact" and not m["fresh"]]
    typed = [e["code"]["code"] for e in errs if e.get("code")]
    fact = {"asset_bytes":length,"sha256":before,"middle":flag,"incremental":incremental,"compiler_artifacts_dirty":dirty,"errors":typed,"history":history}
    if invalid:
        need("E0080" in typed and all(c=="E0080" for c in typed), (name,typed))
    else:
        need(not errs, (name,errs))
        binary, = [Path(m["executable"]) for m in rows if m["reason"]=="compiler-artifact" and m.get("executable") and m["target"]["name"]=="literal_app"]
        need(binary.resolve().is_relative_to(out), ("unexpected executable",binary))
        result = cmd([str(binary)],workspace,e,out/(name+"-native"))
        expected = f"{flag} {19 if flag==97 else 83} 0\n".encode()
        need(result == expected, (name,result,expected))
        fact.update(stdout=result.decode(),elf_sha256=sha(binary))
    need(sha(asset)==before, "compiler modified the source asset")
    records[name]=fact
    save(scope/"verdict.json",fact)
for n in [65535,65536,65537]:
    run("old-"+str(n),"warm",n,97)
run("unchanged","warm",65537,97,change=False)
run("middle-edit","warm",65537,98)
run("clean-edit","empty",65537,98)
run("uninitialized","warm",65537,33,invalid=True)
run("repair","warm",65537,97)
run("small-nonincremental","small",31,97,incremental=False)
run("large-nonincremental","large",65537,98,incremental=False)
need(records["middle-edit"]["stdout"]==records["clean-edit"]["stdout"] and records["repair"]["stdout"]==records["old-65537"]["stdout"],"independent reconstruction")
# This nonincremental unit resolves thousands of different small literal addresses from CTFE.
small = out / "common-lookups"
small.mkdir()
pieces = ["asset-%04x" % n for n in range(2048)]
small_src = small / "lookup.rs"
small_src.write_text("const A: &[&[u8]] = &[" + ",".join('b"' + word + '"' for word in pieces) + "];\n"
    "const fn sum()->u32 {let mut i=0;let mut n=0;while i<A.len(){n+=A[i][9]as u32;i+=1;}n}\n"
    "pub const SUM:u32=sum(); fn main(){println!(\"{}\",SUM);}")
cmd(["rustc","+ohm",str(small_src),"-o",str(small/"case")],small,base,out/"common-compile")
require_sum = sum(ord(p[-1]) for p in pieces)
expected_small = str(require_sum).encode() + b"\n"
need(cmd([str(small/"case")],small,base,out/"common-native")==expected_small,"small allocation lookup")
save(out/"accepted.json",{"common_lookup":{"literal_count":len(pieces),"source_sha256":sha(small_src),"result":expected_small.decode()},"schema":"ohm-frozen-literal-ordinary-v1","role":args.role,"driver_sha256":args.compiler_sha,
    "source_files":{s:sha(here/"literal-fixture"/s) for s in ("main.rs","lib.rs")},"cases":records})
