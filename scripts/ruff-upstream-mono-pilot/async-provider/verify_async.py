"""Run real upstream async-drop provider transitions with ordinary O0 Cargo on Linux."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SHARED_SCRIPT = "1b0d3cc4811ed9eb43b38b4af38cf99e4772707dead272d93f1846c59d811c08"
SHARED_SOURCE = "840478a54201183472ee6459ee276c28c12a49ba2280b5e45537217803fdf7ac"
CTOR = "core::future::async_drop::async_drop_in_place::<mono_api::Envelope<mono_api::AsyncRecord>>"


def helper(shared):
    script = shared / "verify_owner.py"
    if hashlib.sha256(script.read_bytes()).hexdigest() != SHARED_SCRIPT:
        raise ValueError("the shared native observer differs from its registration")
    spec = importlib.util.spec_from_file_location("mono_owner_qa", script)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    source = shared / "source"
    digest = hashlib.sha256()
    for p in sorted(source.rglob("*")):
        if p.is_file():
            digest.update(str(p.relative_to(source)).encode() + b"\0" + bytes.fromhex(h.file_sha(p)))
    h.require(digest.hexdigest() == SHARED_SOURCE, "input workspace differs from its registration")
    h.NAMES = {"async": CTOR}
    return h


def identity(h, a, sdk, env):
    files, versions = {}, {}
    for n in ("rustc", "cargo"):
        p = Path(subprocess.check_output(["rustup", "which", "--toolchain", "ohm", n], env=env, text=True).strip()).resolve(strict=True)
        h.require(p == (sdk / "bin" / n).resolve(strict=True), "private SDK resolution mismatch")
        files["bin/" + n] = h.file_sha(p)
        versions[n] = subprocess.check_output([n, "+ohm", "-vV"], env=env, text=True)
    driver, = (sdk / "lib").glob("librustc_driver*.so")
    relative = str(driver.relative_to(sdk))
    files[relative] = h.file_sha(driver)
    h.require(files["bin/cargo"] == h.SIGNED_CARGO and files[relative] == a.expect_driver_sha256, "registered Cargo or driver digest differs")
    commit, = re.findall(r"^commit-hash: (\S+)$", versions["rustc"], re.M)
    bound = {}
    if commit == "unknown":
        sizes = {n: (sdk / n).stat().st_size for n in (relative, "bin/rustc")}
        bound = factory(h, a, sizes, relative, files, versions)
    else:
        h.require(commit == a.expect_commit and not a.factory_receipts and not a.expect_factory_sha256, "unregistered signed compiler")
    return {"source_commit": a.expect_commit, "files": files, "versions": versions, "factory": bound, "driver": files[relative]}


def factory(h, a, sizes, relative, files, versions):
    receipt = a.factory_receipts
    h.require(receipt and receipt.stat().st_size < 2 << 20 and h.file_sha(receipt) == a.expect_factory_sha256, "hashless SDK needs the externally authenticated factory ZIP")
    with zipfile.ZipFile(receipt) as z:
        names = ("P.json", "C.json", "registration.json", "rustcs.json")
        h.require(all(z.namelist().count(n) == 1 and z.getinfo(n).file_size < 1 << 20 for n in names), "ambiguous factory ZIP inventory")
        raw = {n: z.read(n) for n in names}
    reg = json.loads(raw["registration.json"])
    role, = [r for r in ("P", "C") if reg["roles"][r]["revision"] == a.expect_commit]
    m = json.loads(raw[role + ".json"])
    arm = {"P": "normal", "C": "defer"}[role]
    rebuilt = json.loads(raw["rustcs.json"])["arms"][arm]["files"]
    h.require(reg["bootstrap_flags"].count("rust.omit-git-hash=true") == 1 and m["role"] == role and m["commit"] == a.expect_commit and m["compiler_tree"] == reg["roles"][role]["compiler"], "factory source or role mismatch")
    h.require(all(rebuilt[n] == v for n, v in files.items()) and reg["signed_cargo"]["members"]["bin/cargo"][3] == files["bin/cargo"], "reassembled compiler or Cargo mismatch")
    for n in (relative, "bin/rustc"):
        h.require(m["files"][n][:2] == [files[n], sizes[n]], "factory binary receipt mismatch")
    h.require("host: " + reg["target"] in versions["rustc"].splitlines() and "LLVM version: 23.1.1" in versions["rustc"].splitlines(), "unexpected matched compiler host")
    return {"role": role, "zip_sha256": a.expect_factory_sha256, "source_manifests": {n: h.digest(b) for n, b in raw.items()}}


def inputs(h, src, shared, owners, bias):
    api = (HERE / "api.rs").read_text()
    h.require(api.count("wrapping_add(5)") == 1, "ambiguous async destructor body")
    sources = {"mono_api": api.replace("wrapping_add(5)", f"wrapping_add({bias})"), "mono_consumer": (HERE / "consumer.rs").read_text()}
    for p in h.PROVIDERS:
        anchor = (shared / "source" / p / "src/lib.rs").read_text()
        sources[p] = "#![feature(async_drop)]\n" + anchor + ((HERE / "offer.rs").read_text() if p in owners else "")
    for crate, body in sources.items():
        dest = src / crate / "src/lib.rs"
        if dest.read_text() != body:
            dest.write_text(body)
    return {str(p.relative_to(src)): h.file_sha(p) for p in sorted(src.rglob("*")) if p.is_file()}


def build(h, work, env, out, state, source):
    out.mkdir()
    run = h.command(h.CARGO, env, work / "src", out, "cargo")
    h.require(run["returncode"] == 0, "ordinary Cargo failed")
    messages = [json.loads(row) for row in (out / "cargo.stdout").read_bytes().splitlines() if row]
    h.require([m["success"] for m in messages if m.get("reason") == "build-finished"] == [True], "wrong final Cargo verdict")
    arts = {m["target"]["name"]: m for m in messages if m.get("reason") == "compiler-artifact"}
    h.require(set(arts) == {*h.CRATES, "mono_client"}, "missing real Cargo artifacts")
    binary = Path(arts["mono_client"]["executable"]).resolve(strict=True)
    h.require(binary.is_relative_to(work) and binary.stat().st_size < 8 << 20, "unknown or oversized linked fixture")
    linked = binary.read_bytes()
    cli_sha = h.digest(linked)
    bundle = out.parent.parent / "linked-binaries"
    bundle.mkdir(exist_ok=True)
    packed = bundle / (cli_sha + ".elf.gz")
    if not packed.exists():
        packed.write_bytes(gzip.compress(linked, compresslevel=6, mtime=0))
    h.require(gzip.decompress(packed.read_bytes()) == linked, "linked executable did not survive retention")
    verdict = {}
    for x in (2, 17):
        got = subprocess.check_output([binary, str(x)], env=env, timeout=10, text=True).strip()
        h.require(got == f"{2*x+3} {3*(x+2)+state['bias']}", "incorrect async destructor, provider or poll verdict")
        verdict[str(x)] = got
    ids, definitions, references, native, archives = {}, {}, [], {}, {}
    for crate in h.CRATES:
        lib, = [Path(p).resolve(strict=True) for p in arts[crate]["filenames"] if p.endswith(".rlib")]
        h.require(lib.is_relative_to(work), "rlib escaped private work directory")
        archives[crate] = lib
        folder = out / "objects" / crate
        folder.mkdir(parents=True)
        native[crate] = {}
        for member, data in h.native_members(lib).items():
            if not member.endswith(".o"):
                continue
            key = h.object_id(crate, member)
            h.require(key not in native[crate], "duplicated CGU identity")
            obj = folder / (key + ".o")
            obj.write_bytes(data)
            unit = h.object_evidence(obj)
            native[crate][key] = unit["sha256"]
            for p, ident in unit["provider_ids"].items():
                h.require(p == crate and p not in ids, "ambiguous stable crate ID")
                ids[p] = ident
            for d in unit["definitions"]:
                h.require(crate in state["owners"] and crate not in definitions and d["binding"] in ("T", "W") and d["symbol"].endswith(crate), "unexpected native constructor definition")
                definitions[crate] = {"cgu": key, **d}
            if crate == "mono_consumer":
                references.extend({"cgu": key, **r} for r in unit["references"])
        h.require(native[crate], "missing real native Cargo units")
    h.require(set(ids) == set(h.PROVIDERS) and len(set(ids.values())) == 2 and set(definitions) == set(state["owners"]), "provider or symbol custody mismatch")
    winner = min(state["owners"], key=lambda p: int(ids[p], 16))
    raw = definitions[winner]["symbol"]
    h.require(len({d["symbol"] for d in definitions.values()}) == len(definitions), "duplicated provider-qualified constructor")
    h.require(references and all(r["symbol"] == raw for r in references) and raw.encode() in linked, "consumer did not link the smallest stable eligible provider")
    result = {"state": state, "source": source, "output": verdict, "native": native, "binary_sha256": cli_sha, "provider_ids": ids, "definitions": definitions, "consumer_relocations": references, "winner": winner, "raw": raw}
    h.store(out / "result.json", {**result, "cargo": run, "fresh": {p:a["fresh"] for p,a in arts.items()}})
    return result, archives


def run(a):
    shared, sdk, work, out = (p.resolve() for p in (a.shared_fixture, a.sdk_root, a.work, a.out))
    h = helper(shared)
    h.require(re.fullmatch("[a-f0-9]{40}", a.expect_commit) and re.fullmatch("[a-f0-9]{64}", a.expect_driver_sha256), "need full registered source and driver digests")
    for p in (work, out):
        for q in (HERE, shared, sdk, out if p == work else work):
            h.require(p != q and p not in q.parents and q not in p.parents, "private paths alias one another, source or SDK")
    h.filled(work); h.filled(out)
    nonce = os.urandom(16).hex()
    marker = work / ".async-provider-owned"
    marker.write_text(nonce)
    src = work / "src"
    shutil.copytree(shared / "source", src)
    manifest = src / "Cargo.toml"
    profile = manifest.read_text()
    h.require(profile.count("opt-level=1") == 1, "profile mismatch")
    manifest.write_text(profile.replace("opt-level=1", "opt-level=0"))
    bindir = Path(shutil.which("rustup")).parent
    env = dict(HOME=str(work/"home"), CARGO_HOME=str(work/"cargo-home"), RUSTUP_HOME=str(work/"rustup"), RUSTUP_AUTO_INSTALL="0", CARGO_TARGET_DIR=str(work/"target"), CARGO_BUILD_BUILD_DIR=str(work/"build"), TMPDIR=str(work/"tmp"), CARGO_NET_OFFLINE="true", PATH=str(bindir)+":/usr/local/bin:/usr/bin:/bin", LC_ALL="C")
    (work / "rustup/toolchains").mkdir(parents=True)
    (work / "rustup/toolchains/ohm").symlink_to(sdk)
    h.new_cache(work, env)
    sdk_registration = identity(h, a, sdk, env)
    h.store(out / "registration.json", {"sdk": sdk_registration, "argv": h.CARGO, "profile": 0, "source_files": {n:h.file_sha(HERE/n) for n in ("verify_async.py","offer.rs","api.rs","consumer.rs")}, "shared_observer": SHARED_SCRIPT, "shared_source": SHARED_SOURCE, "runtime_floor_bytes": 8*h.GIB})
    plan = [dict(name="both", owners=list(h.PROVIDERS), bias=5)]
    histories = {}
    try:
        for history in ("warm", "clean"):
            dest = out / history
            dest.mkdir()
            histories[history] = {}
            for state in plan:
                if history == "clean":
                    h.new_cache(work, env)
                key = state["name"]
                r, archives = build(h, work, env, dest / key, state, inputs(h, src, shared, state["owners"], state["bias"]))
                histories[history][key] = r
                if history == "warm" and key == "both":
                    available = [p for p in h.PROVIDERS if p != r["winner"]]
                    plan.extend((dict(name="winner-withdrawn", owners=available, bias=5), dict(name="async-body-changed", owners=available, bias=19), dict(name="winner-restored", owners=list(h.PROVIDERS), bias=19)))
                    h.store(out / "enrolled.json", plan)
                elif history == "warm" and key == "winner-withdrawn":
                    both = histories[history]["both"]
                    prior = {"selected": {"async": {"raw": both["raw"]}}, "objects": {"mono_consumer": {k: {"sha256": v} for k,v in both["native"]["mono_consumer"].items()}}}
                    current = {"selected": {"async": {"raw": r["raw"]}}, "output": {int(k): v for k,v in r["output"].items()}}
                    link = out / "native-link-control"
                    link.mkdir()
                    h.stale_link(src, env, link, work, current, archives, prior, dest / "both")
                if history == "clean":
                    h.require(histories["warm"][key] == r, f"warm/fully independent clean mismatch at {key}")
                print(history, key, r["winner"], r["output"], flush=True)
        states = histories["warm"]
        both, removed, changed, restored = states.values()
        h.require(both["raw"] != removed["raw"] == changed["raw"] and restored["raw"] == both["raw"], "constructor relocation did not follow withdrawal and restoration")
        h.require(both["output"] == removed["output"] and changed["output"] == restored["output"] and all(changed["output"][x] != removed["output"][x] for x in changed["output"]), "async destructor body did not change both verdicts")
        h.require(removed["binary_sha256"] != changed["binary_sha256"], "semantic body edit returned the old executable")
        h.store(out / "terminal.json", {"success": True, "stale_link_receipt": h.file_sha(out / "native-link-control/result.json"), "commit": a.expect_commit, "driver": sdk_registration["driver"], "registration_sha256": h.file_sha(out/"registration.json"), "states": {k:{"winner": r["winner"], "output": r["output"], "refs": len(r["consumer_relocations"]), "warm": h.file_sha(out/"warm"/k/"result.json"), "clean": h.file_sha(out/"clean"/k/"result.json")} for k,r in states.items()}})
        h.require(marker.read_text() == nonce, "private ownership changed")
        shutil.rmtree(work)
    except Exception as error:
        h.store(out / "failure.json", {"error": str(error), "work": str(work)})
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shared-fixture", type=Path, default=HERE.parent / "fixture")
    p.add_argument("--sdk-root", type=Path, required=True)
    p.add_argument("--expect-commit", required=True)
    p.add_argument("--expect-driver-sha256", required=True)
    p.add_argument("--factory-receipts", type=Path)
    p.add_argument("--expect-factory-sha256", help="externally registered original ZIP digest of the source-built roles")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    run(p.parse_args())
