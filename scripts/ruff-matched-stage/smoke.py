"""Save a binary input between expansion and dep-info emission, through ordinary Cargo."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

from capsule import need, save, sha

OLD = bytes([17, 255, 134, 93])
NEW = bytes([29, 255, 134, 93])
TARGET = "consumed-input"
SAVE = r'''
extern crate proc_macro;
use proc_macro::TokenStream;
#[proc_macro]
pub fn save(_: TokenStream) -> TokenStream {
    let root = std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    if root.join("armed").exists() {
        let path = root.join("src/payload.bin");
        let temp = root.join("src/replacement.bin");
        std::fs::write(&temp, [29, 255, 134, 93]).unwrap();
        std::fs::rename(temp, path).unwrap();
    }
    "0".parse().unwrap()
}
'''
MAIN = r'''
const USED: &[u8] = include_bytes!("payload.bin");
const _: [(); 17] = [(); USED[0] as usize];
const _: usize = saver::save!();
fn main() { println!("{}", USED[0]); }
#[test]
fn returns_seventeen() { assert_eq!(USED[0], 17); }
'''


def seed(work):
    (work / "src").mkdir(parents=True)
    (work / "saver/src").mkdir(parents=True)
    (work / "Cargo.toml").write_text('[package]\nname="consumed-input"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nsaver={path="saver"}\n[workspace]\n')
    (work / "saver/Cargo.toml").write_text('[package]\nname="saver"\nversion="0.1.0"\nedition="2021"\n[lib]\nproc-macro=true\n')
    (work / "saver/src/lib.rs").write_text(SAVE)
    (work / "src/main.rs").write_text(MAIN)
    (work / "src/payload.bin").write_bytes(OLD)
    (work / "armed").touch()


def run(work, env, mode, suffix, label, expected):
    target, build = (work / (s + suffix) for s in ("target", "build"))
    env = dict(env, CARGO_HOME=str(work / "cargo-home"), CARGO_TARGET_DIR=str(target),
               CARGO_BUILD_BUILD_DIR=str(build), CARGO_NET_OFFLINE="true")
    env.pop("CARGO_INCREMENTAL", None)
    args = [mode] + (["--no-run"] if mode == "test" else [])
    argv = ["cargo", "+ohm", *args, "--offline", "--message-format=json", "-vv"]
    before = (work / "src/payload.bin").read_bytes()
    p = subprocess.run(argv, cwd=work, env=env, capture_output=True, timeout=100)
    after = (work / "src/payload.bin").read_bytes()
    logs = Path(env["OHM_CASE_LOGS"]); prefix = work.name + "-" + label
    (logs / (prefix + ".stdout")).write_bytes(p.stdout); (logs / (prefix + ".stderr")).write_bytes(p.stderr)
    rows = [json.loads(s) for s in p.stdout.splitlines()]
    codes = [e["message"]["code"]["code"] for e in rows if e.get("reason") == "compiler-message" and e["message"].get("code")]
    artifacts = [e for e in rows if e.get("reason") == "compiler-artifact" and e["target"]["name"] == TARGET]
    assert p.returncode == expected and rows[-1] == {"reason":"build-finished", "success": expected == 0}, (label, mode, p.returncode, codes, p.stderr[-1500:])
    assert ("E0308" in codes) == (expected == 101), (label, mode, codes)
    record = dict(mode=mode, label=label, args=argv, before=before.hex(), after=after.hex(), status=p.returncode,
                  fresh=[a["fresh"] for a in artifacts], codes=codes, sdk=env["RUSTC"], source_sha256=sha(work / "src/main.rs"))
    if mode != "check" and artifacts:
        exe, = {a["executable"] for a in artifacts if a.get("executable")}
        raw = subprocess.check_output([exe] + (["--list"] if mode == "test" else []), env=env)
        assert (b"returns_seventeen: test" in raw if mode == "test" else raw == b"17\n"), raw
        record.update(elf=sha(Path(exe)), output=raw.decode())
    assert before in (OLD, NEW) and after in (OLD, NEW)
    return record


def history(work, env, mode, candidate):
    seed(work)
    rows = [run(work, env, mode, "", "during-save", 0)]
    assert rows[0]["before"] == OLD.hex() and rows[0]["after"] == NEW.hex() and rows[0]["fresh"] == [False]
    (work / "armed").unlink()
    verdict = run(work, env, mode, "", "unchanged", 101 if candidate else 0)
    rows.append(verdict)
    if not candidate:
        assert verdict["fresh"] == [True] and verdict.get("elf") == rows[0].get("elf"), verdict
    rows.append(run(work, env, mode, "-clean", "independent-clean", 101))
    return rows


def repair(work, env, mode):
    (work / "src/payload.bin").write_bytes(OLD)
    repaired = run(work, env, mode, "", "repair", 0)
    clean = run(work, env, mode, "-clean", "repair-clean", 0)
    fresh = run(work, env, mode, "", "repair-unchanged", 0)
    assert fresh["fresh"] == [True] and repaired.get("elf") == clean.get("elf") == fresh.get("elf"), (repaired, clean, fresh)
    return [repaired, clean, fresh]


def smoke(root, manifest, base):
    proxy = Path(shutil.which("rustup", path=base["PATH"])).resolve(strict=True)
    proxies = root / "proxies"; proxies.mkdir()
    for name in ("rustup", "cargo", "rustc", "rustdoc"):
        (proxies / name).symlink_to(proxy)
    alias = Path(base["RUSTUP_HOME"]) / "toolchains/ohm"
    alias.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for role, label in (("P","normal"), ("C","defer")):
        target = Path(manifest["arms"][label]["root"])
        need(target.samefile(root / "reopened" / label), "foreign toolchain")
        if alias.is_symlink():
            alias.unlink()
        alias.symlink_to(target, target_is_directory=True)
        env = dict(base, PATH=str(proxies) + os.pathsep + base["PATH"], RUSTC=str(target / "bin/rustc"),
                   RUSTUP_TOOLCHAIN="ohm", LD_LIBRARY_PATH=str(target / "lib"), OHM_CASE_LOGS=str(root / "logs"))
        for tool in ("rustc","cargo","rustdoc"):
            path = subprocess.check_output(["rustup","which","--toolchain","ohm",tool], env=env, text=True).strip()
            need(Path(path).samefile(target / "bin" / tool), ("wrong tool", tool))
        for mode in ("check", "build", "test"):
            work = root / (role + "-" + mode)
            rows += history(work, env, mode, role == "C")
            if role == "C":
                rows += repair(work, env, mode)
                stale = root / ("P-" + mode)
                rows.append(run(stale, env, mode, "", "upgrade", 101))
                rows += repair(stale, env, mode)
            save(root / "logs/consumed-input-progress.json", rows)
    save(root / "logs/smoke.json", {"schema":1, "ordinary_cargo_histories":rows})
