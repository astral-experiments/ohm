"""Acquire a single published release history, preserving native counters and ordinary controls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import inventory
import worker as w
import owner_read as reader
from matched import COUNT_SHA
import signed23


def acquire():
    w.checked_head()
    w.need(not any(os.environ.get(k) for k in ("GH_TOKEN","GITHUB_TOKEN","RUSTC_WRAPPER","LD_PRELOAD")), "ambient control")
    top = w.OUT
    w.need(w.CMD == reader.CMD, "different ordinary command")
    installed = reader.read(top / "sdk.json")["members"]
    driver, = (w.SDK/"lib").glob("librustc_driver-*.so")
    arm = {"source":signed23.RUST, "cargo_source":signed23.CARGO}
    for name,path in (("driver",driver),("rustc",w.SDK/"bin/rustc"),("cargo",w.SDK/"bin/cargo"),("rustdoc",w.SDK/"bin/rustdoc")):
        arm[name]=w.sha(path)
        w.need(arm[name]==installed[str(path.relative_to(w.SDK))][3], "release executable identity")
    w.need(w.sha(w.HERE/"whole_count.c") == COUNT_SHA, "ordinary counter source")
    subprocess.run(["/usr/bin/cc","-O2","-Wall","-Wextra","-Werror",w.HERE/"whole_count.c","-o",w.ROOT/"whole-count"],check=True)
    donor = w.WS / "donor/scripts/ruff-default-owner-pmu"
    sys.path.insert(0,str(donor))
    import instrument
    table, pmu = instrument.compile_sources(w.WS/"collector", w.WS/"contract", top/"observer-source")
    kit = w.ROOT / "counter-kit"
    kit.mkdir()
    bins = pmu.compilers(kit)
    pmu.calibration(bins, top)
    env = w.environment()
    gcc = Path(shutil.which("cc",path=env["PATH"])).resolve(strict=True)
    collect2 = Path(subprocess.check_output([gcc,"-print-prog-name=collect2"], env=env, text=True).strip()).resolve(strict=True)
    wild = w.SDK / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    selectors = {k:table.location(v) for k,v in zip(table.ROLES,(w.SDK/"bin/rustc",gcc,collect2,wild), strict=True)}
    process = {"proxy":table.location(w.ROOT/"proxies/rustup"),"cargo":table.location(w.SDK/"bin/cargo")}
    w.save(top/"owner-inputs.json", {"selectors":selectors,"process":process, "sha256":{k:w.sha(Path(v[2])) for k,v in (selectors|process).items()},
           "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"head":os.environ["REVIEWED_HEAD"],
           "release_factory":41552791237, "observer_sha256":w.sha(bins/"tree")})
    w.OUT = top / "release23"
    w.OUT.mkdir()
    w.save(w.OUT/"compiler.json",dict(arm,rustc_vV=subprocess.check_output(["rustc","+ohm","-vV"],env=env,text=True)))
    def observe(out, env):
        trace = top / ("events-" + out.name)
        trace.mkdir()
        cmd = [bins/"tree",trace,"tree",*(selectors[n][2] for n in table.ROLES),*w.CMD]
        w.run(cmd, env, out)
        # Ordinary Cargo and rustc run unwrapped. Only the external observer owns these files.
        result, roots = reader.inspect(table, trace, selectors, process, (out/"stdout").read_bytes())
        w.save(out/"ownership.json",result)
        return roots
    def phase(name,state,**kwargs):
        measure = observe if name in ("edited","new-unchanged") else None
        return inventory.phase(name,state,observe=measure,**kwargs)
    inventory.main(phase=phase)
    phases = {s:reader.read(w.OUT/s/"phase.json") for s in ("old","old-unchanged","edited","new-unchanged","invalid","repair","clean")}
    edit = phases["edited"]; clean = phases["clean"]
    w.need(phases["invalid"]["counts"] == {inventory.PRODUCER:1} and any(r[:2] == ["error","E0308"] for r in phases["invalid"]["diagnostics"]), "real failed parent compiler")
    w.need(phases["old"]["workspace_rmeta"] == phases["old-unchanged"]["workspace_rmeta"]
           and edit["workspace_rmeta"] == phases["new-unchanged"]["workspace_rmeta"] == phases["repair"]["workspace_rmeta"], "changed same-history native metadata")
    same = sorted(k for k,h in edit["workspace_rmeta"].items() if clean["workspace_rmeta"].get(k)==h)
    w.need(len(edit["workspace_rmeta"]) == len(clean["workspace_rmeta"]) == 31 , "complete independent empty metadata table")
    w.save(top/"ownership-complete.json", {"head": os.environ["REVIEWED_HEAD"], "boot": reader.read(top/"owner-inputs.json")["boot"],
           "source": signed23.RUST, "cargo_source":signed23.CARGO, "edited":reader.read(w.OUT/"edited/ownership.json"), "unchanged":reader.read(w.OUT/"new-unchanged/ownership.json"),
           "physical_empty_equal":same,"empty_total":len(clean["workspace_rmeta"]), "controls":"7 original stages, including E0308/repair and independent empty NEW"})

if __name__ == "__main__":
    acquire()
