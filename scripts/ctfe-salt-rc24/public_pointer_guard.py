"""Exercise observable pointer identity across ordinary Cargo public-hash edits."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

u = Path(__file__).resolve().parent
role = sys.argv[1]
rustup = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else u.parent / "release-24-distro-01/rustup"
at = u / "public-pointer-guard" / role
work = at / "workspace"
at.mkdir(parents=True, exist_ok=False)
for crate, manifest in {
    "": '[workspace]\nresolver="3"\nmembers=["producer","observer"]\n',
    "producer": '[package]\nname="producer"\nversion="0.1.0"\nedition="2024"\n',
    "observer": '[package]\nname="observer"\nversion="0.1.0"\nedition="2024"\n[dependencies]\nproducer={path="../producer"}\n',
}.items():
    d = work / crate
    d.mkdir(parents=True, exist_ok=True)
    (d / "Cargo.toml").write_text(manifest)
    if crate:
        (d / "src").mkdir()
base = """
#[repr(align(64))]
pub struct Wide(pub [u8; 32]);
pub static ONE: [u8; 32] = [83; 32];
pub static TWO: [u8; 32] = [83; 32];
pub static WIDE: Wide = Wide([83; 32]);
pub static mut MUTABLE: [u8; 32] = [83; 32];
pub const ANON: &'static [u8; 32] = &[83; 32];
pub const PAIR: (*const u8, *const u8) = (ONE.as_ptr(), RHS);
pub const PROMOTED: (&'static [u8; 32], &'static [u8; 32]) = ANON_PAIR;
"""
(work / "observer/src/main.rs").write_text("""
fn main() {
    use producer::*;
    let (a, b) = PAIR;
    let mp = (&raw mut MUTABLE).cast::<u8>();
    unsafe { mp.write(71); }
    println!("{} {} {} {} {} {} {} {}",
        a == b, b == TWO.as_ptr(), b == a.wrapping_add(1), b == WIDE.0.as_ptr(),
        b == mp, unsafe { b.read() }, std::ptr::eq(PROMOTED.0, PROMOTED.1), PROMOTED.0[0]);
}
""")
env = {k: os.environ[k] for k in ("HOME", "USER", "PATH", "LANG", "TZ") if k in os.environ}
env.update(RUSTUP_HOME=str(rustup), CARGO_HOME=str(at / "cargo-home"), CARGO_NET_OFFLINE="true")
sha = lambda b: hashlib.sha256(b).hexdigest()
def run(args, active, **extra):
    return subprocess.run(args, cwd=work, env=active, capture_output=True, **extra)
def ver():
    return run(["rustc", "+ohm", "-Vv"], env, check=True).stdout.decode().strip()
def build(loc, invalid=False):
    active = dict(env, CARGO_TARGET_DIR=str(loc / "target"), CARGO_BUILD_BUILD_DIR=str(loc / "build"))
    result = run(["cargo", "+ohm", "build", "--offline", "-p", "observer", "--message-format=json"], active)
    lines = [json.loads(x) for x in result.stdout.splitlines()]
    code = [v["message"]["code"]["code"] for v in lines if v["reason"] == "compiler-message" and v["message"].get("code")]
    if invalid:
        assert result.returncode == 101 and "E0308" in code, (result.returncode, code, result.stderr)
        return {"status": 101, "codes": code}
    assert result.returncode == 0, (lines[-3:],result.stderr)
    units = {v["target"]["name"]: v for v in lines if v["reason"] == "compiler-artifact"}
    binary = Path(units["observer"]["executable"])
    meta, = (Path(x) for x in units["producer"]["filenames"] if x.endswith(".rmeta"))
    metadata = run(["rustc", "+ohm", "-Zls=public_hash", str(meta)], active, check=True).stdout
    public, = re.findall(rb"Public hash: ([0-9a-f]+)", metadata)
    return {"public_hash": public.decode(), "metadata_sha256": sha(meta.read_bytes()),
            "elf": sha(binary.read_bytes()), "output": run([str(binary)],active,check=True).stdout.decode().strip(),
            "fresh": {k: a["fresh"] for k, a in units.items()}}
pair = "(ANON, ANON)"
states = [
    ("shared", "ONE.as_ptr()", pair, "true false false false false 83"),
    ("distinct", "TWO.as_ptr()", pair, "false true false false false 83"),
    ("offset", "ONE.as_ptr().wrapping_add(1)", pair, "false false true false false 83"),
    ("aligned", "WIDE.0.as_ptr()", pair, "false false false true false 83"),
    ("mutable", "(&raw const MUTABLE).cast::<u8>()", pair, "false false false false true 71"),
    ("separate-promotions", "ONE.as_ptr()", "(&[83; 32], &[83; 32])", "true false false false false 83"),
    ("invalid", "false", pair, ""),
    ("repaired", "ONE.as_ptr()", pair, "true false false false false 83"),
]
records = []
for label, rhs, anon, prefix in states:
    src = base.replace("RHS", rhs).replace("ANON_PAIR", anon)
    (work / "producer/src/lib.rs").write_text(src)
    row = {"label": label, "source": sha(src.encode())}
    dirty = at / "history"
    if label == "invalid":
        row["attempts"] = [build(dirty, True) for _ in range(2)]
    else:
        row["edit"], row["settled"], row["empty"] = build(dirty), build(dirty), build(at / ("empty-" + label))
        edit, settled, empty = row["edit"], row["settled"], row["empty"]
        assert edit["output"].startswith(prefix + " ") and edit["output"].endswith(" 83")
        assert edit["output"] == settled["output"] == empty["output"]
        assert edit["elf"] == settled["elf"]
        assert all(settled["fresh"].values())
    records.append(row)
    print(label, row.get("edit", row.get("attempts")), flush=True)
    (at / "result.json").write_text(json.dumps({"rustc":ver(), "records":records},indent=2,sort_keys=True) + "\n")
hashes = [r["edit"]["public_hash"] for r in records[:5]]
assert len(set(hashes)) == 5
