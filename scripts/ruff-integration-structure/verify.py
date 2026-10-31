"""Read a downloaded structure artifact with its original Cargo streams and complete ELF bodies."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", str(Path(tempfile.gettempdir()).resolve()))
import run
import suite


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def audit(logs):
    need = suite.require
    done, enrollment = (read(logs / name) for name in ("complete.json","enrollment.json"))
    need(done["qualified"] is True and done["clocks"] == 0 and done["head"] == enrollment["head"] and
         enrollment["argv"] == run.CARGO and enrollment["f"] == run.b.HEADS["F"] and
         enrollment["plan"] == run.sha(HERE / "PLAN.md") == run.sha(logs / "PLAN.md"), "enrollment")
    names = suite.inventory((HERE / "expected-tests.txt").read_bytes())
    reopened, refs, visits = {}, {}, []
    for stage in ("clean","history"):
        for arm in run.ARMS:
            folder = logs / stage / arm
            kit = read(folder / "arm.json")
            need(kit["arm"] == arm and kit["role"] == "F" and kit["files"]["bin/cargo"][0] == run.b.CARGO_ELF
                 and kit["files"][run.b.WILD][0] == run.b.WILD_ELF, "enrolled active SDK")
            phases = [(b,b) for b in "AB"] if stage == "clean" else run.historical.PHASES
            for phase, branch in phases:
                d = folder / phase
                rec = read(d / "visit.json")
                native = read(d / "native-execs.json.gz")
                cmd = read(d / "cargo.json.gz")
                need(cmd["argv"] == run.CARGO and native["real_cargo"] == 1 and native["cargos"][0]["argv"][1:] == run.CARGO[2:] and
                     ((phase == "invalid") == (cmd["exit"] == 101)) and cmd["exit"] == rec["code"], "literal Cargo/exit")
                with gzip.open(d / "exec.raw.gz", "rt") as stream:
                    events = set((p,e,tuple(a)) for p,e,a in run.historical.processes.execs(stream))
                for r in [*native["cargos"], *native["rustcs"], *native["wild_processes"]]:
                    need((r["pid"],r["exe"],tuple(r["argv"])) in events, "claimed PID and argv absent from kernel trace")
                need(rec["wild"] == len(native["wild_processes"]) and rec["full"] == sum(r["mode"]=="full" for r in native["rustcs"])
                     and rec["link_only"] == sum(r["mode"]=="link-only" for r in native["rustcs"]), "wrong native work count")
                for field in ("stdout","stderr"):
                    need(suite.sha(gzip.decompress((d / ("cargo."+field+".gz")).read_bytes())) == cmd[field+"_sha256"], "raw Cargo stream")
                lines = [json.loads(x) for x in gzip.decompress((d/"cargo.stdout.gz").read_bytes()).splitlines()]
                need(lines[-1] == {"reason":"build-finished","success":phase!="invalid"}, "unclosed actual Cargo stream")
                if stage == "history":
                    visits.append(rec)
                if phase == "invalid":
                    errors = read(d/"diagnostics.json.gz")
                    need(any(x["message"].get("code",{}).get("code")=="E0308" and
                             "ohm_branch_switch_invalid" in str(x["message"]["spans"]) for x in errors if x["message"].get("code")),
                         "wrong parser diagnostic")
                    continue
                source = read(d/"source.json")
                need(source["commit"] == run.kit.REVS[branch] and source["tree"] == run.kit.TREES[branch] and
                     rec["arm"] == arm and rec["state"] == branch and rec["visit"] == ("cold-"+phase if stage=="clean" else phase),
                     "source history or role")
                typed = read(d/"roster.json.gz")
                expect_units, expect_dirty = run.selection.roster(lines, Path(cmd["cwd"]))
                need(typed == {"units":expect_units,"dirty":expect_dirty} and len(expect_units)==rec["typed"] and
                     len(expect_dirty)==rec["distinct_dirty"], "actual typed and dirty graph")
                images = read(d/"native.json.gz")
                actual = {k:images[k] for k in ("cli","reader")} | {"harness":read(d/"harness-elf.json")}
                if stage == "clean":
                    refs[arm,branch] = actual
                else:
                    need(actual == refs[arm,branch], "complete own-empty products")
                for name, description in actual.items():
                    digest = description["whole"]
                    if digest not in reopened:
                        compressed = logs / "native-bodies" / (digest + ".zst")
                        with tempfile.TemporaryFile() as f:
                            subprocess.run(["zstd","-dq","--stdout",compressed],stdout=f,check=True)
                            reopened[digest] = run.native.elf(Path(f"/proc/self/fd/{f.fileno()}"))
                    need(reopened[digest] == description and rec["products"][name] == digest, "whole ELF, sections or loads")
                need(images["cli"]["whole"] == rec["products"]["cli"] and images["source"] == source["commit"],
                     "tested CLI or native source")
                suite_commands = ["libtest-list","libtest-full","dev-rule",*suite.EXACT]
                for label in suite_commands:
                    result = read(d / (label+".json"))
                    need(result["exit"] == 0 and Path(result["cwd"]) == Path(cmd["cwd"])/"crates/ruff" and
                         result["insta_root"] == cmd["cwd"] and
                         all(suite.sha(gzip.decompress((d/(label+"."+which+".gz")).read_bytes())) == result[which]
                             for which in ("stdout","stderr")), ("original off-window verdict",label))
                suite.inventory(gzip.decompress((d/"libtest-list.stdout.gz").read_bytes()))
                suite.verdict(gzip.decompress((d/"libtest-full.stdout.gz").read_bytes()), names)
                for name in suite.EXACT:
                    suite.verdict(gzip.decompress((d/(name+".stdout.gz")).read_bytes()),[name],95)
                    raw = read(d/(name+".json"))
                    with gzip.open(d/(name+".exec.gz"),"rt") as f:
                        events = run.historical.processes.execs(f)
                    selected = read(d/"libtest.json")["children"][name]
                    need(len(events)==2 and events[0][0]==selected["harness_pid"] and events[1]==
                         (selected["ruff_pid"],raw["cargo_bin"],selected["argv"]) and
                         Path(raw["cwd"]).name=="ruff" and Path(raw["cwd"]).parent.name=="crates", "actual fixture child")
                need(images["typed"] == f"Expr={64 if branch=='A' else 56} valid=1 rejected", "bad typed reader")
    need(visits == done["histories"] and len(visits) == 14 and set(refs) == {(x,y) for x in run.ARMS for y in "AB"},
         "missing or duplicated visit")
    return {"verified":True,"head":done["head"],"structural_cargo_invocations":18,"valid":16,
            "intentional_errors":2,"unique_full_elf_bodies":len(reopened),"clocks":0}


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1]).resolve()),sort_keys=True))
