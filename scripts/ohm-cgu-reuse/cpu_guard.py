"""Compare files and code emitted by the same rustc under two emulated host tuning models."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROTOCOL = Path(os.environ.get("CGU_KIT_HARNESS", HERE)).resolve()
sys.path[:0] = [str(PROTOCOL), str(PROTOCOL.parent / "ohm-aarch64-linux")]
import runtime as rt
from study import digest, load, need, save, sha

MODELS = {"A": "Haswell-v2", "B": "Opteron_G3"}


def main(expectation, role):
    kit = load(rt.LOG / f"{role}-sdk.json")
    rt.select(role)
    compiler = rt.SDK / "bin/rustc"
    driver, = (rt.SDK / "lib").glob("librustc_driver*.so")
    need(sha(compiler) == kit["files"]["bin/rustc"][0] and
         sha(driver) == kit["files"]["lib/"+driver.name][0], "foreign compiler or codegen backend")
    base = rt.ROOT / f"cpu-{role}"
    shutil.copytree(HERE / "cpu-fixture", base)
    (base / "payload.bin").write_bytes(bytes([17]))
    dest = rt.LOG / ("cpu-" + expectation + "-" + role)
    dest.mkdir()
    emulator = shutil.which("qemu-x86_64") or shutil.which("qemu-x86_64-static")
    need(emulator, "missing real QEMU user-mode binary")
    env = rt.environment()
    def record(argv, directory):
        return rt.record(argv, directory, base, env)
    cfg = {}
    options = ["-Clto=off", "-Copt-level=3", "-Ctarget-cpu=x86-64", "-Ztune-cpu=native"]
    for arm, model in MODELS.items():
        out = record([emulator, "-cpu", model, compiler, "--print", "cfg", *options], dest / ("cfg-"+arm))
        cfg[arm] = sorted(out.stdout.decode().splitlines())
    need(cfg["A"] == cfg["B"], "new cfg would invalidate the controlled ordinary cache")
    rows = {}
    for name, arm, cache in (("old","A","warm"), ("repeat","A","warm"), ("moved","B","warm"),
                             ("clean-new","B","empty-new"), ("clean-old","A","empty-old")):
        run = dest / name
        cache = base / cache
        target = [emulator, "-cpu", MODELS[arm]]
        args = [*target, compiler, "lib.rs", "--edition=2021", "--crate-name", "opaque_native_cpu",
                "--crate-type=rlib", *options, "-Ccodegen-units=16", "-Cdebuginfo=0", "-Cincremental="+str(cache),
                "-Zohm-check-relink-inputs", "-Zquery-dep-graph", "-Zprint-mono-items=yes",
                "--emit=link,dep-info=explicit.d", "--out-dir", base]
        result = record(args, run / "compile")
        need(b"ohm-untracked-relink-inputs" in (base/"explicit.d").read_bytes(), "lost opaque assembly marker")
        votes = {n.decode(): v.decode() for n, v in re.findall(rb"^CGU_REUSE (\S+) (No|PostLto)$", result.stdout, re.M)}
        files = {p.stem:p for p in cache.glob("*/s-*/*.o") if not p.parent.name.endswith("-working")}
        need(votes.keys() == files.keys() and len(files) == 2, "wrong or incomplete native objects")
        objects = {}
        for unit, path in files.items():
            symbols = record(["nm", "--defined-only", path], run / ("nm-"+unit)).stdout.decode()
            names = [symbol for symbol in ("independent_llvm_mask", "opaque_llvm_file") if re.search(" T "+symbol+"$", symbols, re.M)]
            need(len(names) == 1, "assembly and ordinary definitions must be in separate files")
            symbol, = names
            if symbol == "independent_llvm_mask":
                need(all(re.search(" T "+s+"$", symbols, re.M) for s in ("filled", "scan_words", "map_words")), "missing ordinary functions")
            record(["objdump", "-d", path], run / ("disassemble-"+unit))
            shutil.copyfile(path, run / (symbol+".o"))
            objects[symbol] = {"unit":unit, "sha256":sha(path), "reuse":votes[unit]}
        image = base / "read-terms"
        record(["cc", "-O2", "-no-pie", "-Wl,--build-id=none", base/"reader.c", run/"independent_llvm_mask.o",
                run/"opaque_llvm_file.o", "-o", image], run/"link")
        observed = record([*target, image], run/"execute").stdout.decode().strip()
        need(observed == "17 71 6320 11.163 25", "wrong native external-reader output: "+observed)
        shutil.copyfile(image, run/"program")
        rows[name] = {"objects":objects, "image":sha(image), "verdict":observed}
    def val(phase, symbol):
        return rows[phase]["objects"][symbol]["sha256"]
    pure, asm = "independent_llvm_mask", "opaque_llvm_file"
    need(rows["old"]["image"] == rows["clean-old"]["image"] and rows["old"]["image"] != rows["clean-new"]["image"]
         and val("clean-old",pure) != val("clean-new",pure), "two cold tuning models did not discriminate native code")
    need(val("moved",asm) == val("clean-new",asm) and rows["moved"]["objects"][asm]["reuse"] == "No",
         "assembler did not follow its actual new host")
    if expectation == "original-stale":
        need(val("moved",pure) == val("clean-old",pure) and rows["moved"]["objects"][pure]["reuse"] == "PostLto"
             and rows["moved"]["image"] != rows["clean-new"]["image"], "did not reproduce stale pure LLVM scheduling")
    else:
        need(expectation == "protected" and val("moved",pure) == val("clean-new",pure) and
             rows["moved"]["objects"][pure]["reuse"] == "No" and rows["moved"]["image"] == rows["clean-new"]["image"],
             "repaired compiler failed to use the active CPU's native schedule")
    save(dest/"terminal.json", {"role":role, "source":kit["source"], "compiler":sha(compiler), "driver":sha(driver),
         "qemu":sha(Path(emulator)), "fixture":{n:sha(base/n) for n in ("lib.rs","reader.c")}, "cfg":cfg,
         "models":MODELS,"expectation":expectation,"phases":rows})
    print("matched native tuning",role,expectation,flush=True)


if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("expectation",choices=["protected","original-stale"]);p.add_argument("role",choices=["P","C"])
    args=p.parse_args();main(args.expectation,args.role)
