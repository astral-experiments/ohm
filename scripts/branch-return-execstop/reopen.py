"""Reopen an extracted official qualification archive without an installed Ruff SDK."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
os.environ.setdefault("RUNNER_TEMP", "/unused-offline-exec-qualification")
sys.path[:0] = [str(HERE), str(HERE / "kernel")]
import images
import qualify as job
from read_events import read


def raw(p):
    return gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()


def j(p):
    return json.loads(raw(p))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def reopen(logs):
    b = job.b
    end, current = j(logs / "complete.json"), j(logs / "enrollment.json")
    a, z = logs / "clean/cold-A", logs / "observed/cold-A"
    expected = job.inputs()
    b.need(end["host_complete"] is True and current["original_head"] == job.HISTORICAL
           and current["source"] == b.spec() and current["arm"] == "Koff"
           and current["command"] == job.old.CARGO and current["counter"] is None
           and len(current["process_cpus"]) == 8 and current["process_cpus"] == sorted(current["available_cpus"])[:8],
           "wrong enrollment")
    manifest = j(logs / "sdk/manifest.json")
    b.need(b.sha(logs / "sdk/manifest.json") == b.spec()["manifest"] and manifest["roles"]["K"]["commit"] == b.HEADS["K"],
           "unbound Packed source")
    arm = j(logs / "observed/arm.json")
    b.need(arm == j(logs / "clean/arm.json") and arm["role"] == "K", "different empty reference or installed SDK")
    catalog = j(logs / "observed/catalog.json")
    for key in ("bin/cargo", "bin/rustc", b.WILD):
        role = {b.WILD: "wild", "bin/rustc": "rustc", "bin/cargo": "cargo"}[key]
        b.need(catalog[role]["identity"] == arm["files"][key] and manifest["files"]["K"][key][0] == arm["files"][key][0],
               ("different executable catalog", key))
    b.need(j(a / "source.json") == j(z / "source.json") and j(a / "source.json")["commit"] == job.old.kit.REVS["A"],
           "wrong historical source")
    b.need(dict(j(a / "visit.json"), allocated=None) == dict(j(z / "visit.json"), allocated=None)
           and j(z / "visit.json")["instructions"] is None, "different actual cold visit or unexpected clock")
    fixtures = j(logs / "fixtures/qualified.json")
    b.need(fixtures["observer_sha256"] == b.sha(logs / "fixtures/observe.elf") == end["observer_sha256"],
           "installed observer differs from qualified ELF")
    for name, s in fixtures["originals"].items():
        b.need(b.sha(logs / "fixtures/original" / name) == s, ("changed native fixture", name))
    for name, s in fixtures["sources"].items():
        b.need(b.sha(HERE / "kernel" / name) == s, ("changed observer fixture source", name))
    check = subprocess.check_output([sys.executable, "-IB", HERE / "kernel/qualify.py", "cases", logs / "fixtures/original"])
    portable = json.loads(check)
    b.need(portable == dict(fixtures["native"], live_physical_reopen=False), "different native fixture verdicts")
    b.need(len(fixtures["ruff_projection"]["refusals"]) == 12, "missing negative executable classifications")
    with tempfile.TemporaryDirectory() as temp:
        ledger = Path(temp) / "positive.tsv"
        with gzip.open(z / "kernel.tsv.gz", "rb") as src, ledger.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        closed = read(ledger, expected_code=0, expected_sha=end["ledger_sha256"])
        native = images.inventory(ledger, closed, catalog, expected, job.old.processes.other_link)
    b.need(native == j(z / "native-execs.json.gz") and native["successful_exec_count"] == expected["successful_execs"],
           "actual kernel roster changed")
    source = j(a / "source.json")
    for d, observed in ((a, False), (z, True)):
        argv = j(d / "cargo.json.gz")
        b.need(argv["exit"] == 0 and argv["argv"] == job.old.CARGO and argv["env"] == arm["env"]
               and bool(argv["observer_argv"]) == observed, "different Cargo command, mode or environment")
        stdout, stderr = raw(d / "cargo.stdout.gz"), raw(d / "cargo.stderr.gz")
        b.need(sha(stdout) == argv["stdout_sha256"] and sha(stderr) == argv["stderr_sha256"], "Cargo streams")
        typed = [json.loads(line) for line in stdout.splitlines()]
        b.need(typed[-1] == {"reason": "build-finished", "success": True} and
               all(x["message"]["level"] != "error" for x in typed if x["reason"] == "compiler-message"), "Cargo verdict")
        rows, dirty = job.old.historical.roster(typed, Path(argv["cwd"]))
        b.need(rows == dirty and job.digest(rows) == expected["typed"] and len(rows) == 375 and
               j(d / "roster.json.gz") == {"members": rows, "dirty": dirty}, "typed empty graph or dirty total")
        outputs = j(d / "native.json.gz")
        b.need(outputs["source"] == source["commit"] and outputs["branch"] == "A", "behavior source")
        cli_cases = {"version": ("ruff-version", 0), "source": ("ruff-version-json", 0), "clean": ("ruff-clean", 0),
                     "warning": ("ruff-warning", 1), "fixed": ("ruff-fix", 1), "recheck": ("ruff-recheck", 0),
                     "invalid": ("ruff-invalid", 1)}
        b.need(set(outputs["cli_cases"]) == set(cli_cases) and outputs["typed"] == "Expr=64 valid=1 rejected",
               "wrong real Ruff CLI inventory or typed AST value")
        for case, (basename, code) in cli_cases.items():
            verdict = outputs["cli_cases"][case]
            b.need(verdict["status"] == code and sha(raw(d / (basename + ".stdout"))) == verdict["stdout_sha256"]
                   and sha(raw(d / (basename + ".stderr"))) == verdict["stderr_sha256"], ("changed real CLI result", case))
        for rec in d.glob("*.json.gz"):
            val = j(rec)
            if not isinstance(val, dict) or "stdout_sha256" not in val or rec.name == "cargo.json.gz":
                continue
            name = rec.name[:-len(".json.gz")]
            b.need(val["exit"] == val["expected"] and sha(raw(d / (name + ".stdout.gz"))) == val["stdout_sha256"] and
                   sha(raw(d / (name + ".stderr.gz"))) == val["stderr_sha256"], ("native output streams", name))
    b.need(j(a / "native.json.gz") == j(z / "native.json.gz"), "different native behavior or ELF bytes")
    native_info = j(a / "native.json.gz")
    for kind in ("cli", "reader"):
        key = native_info[kind]["whole"]
        b.need(key == end["native"][kind], ("wrong native output hash", kind))
        with subprocess.Popen(["zstd", "-dcq", logs / "native-bodies" / (key + ".zst")], stdout=subprocess.PIPE) as proc:
            got = hashlib.file_digest(proc.stdout, "sha256").hexdigest()
            b.need(proc.wait() == 0 and got == key, ("wrong retained native ELF body", kind))
    origin = j(z / "settled-origin.json")
    b.need(origin["emitter"]["cargo_link_blake3"] == job.old.settled_link.marker((z / "dep-lib-zmij").read_bytes())
           and origin["emitter"]["rustc_rules"] == job.old.settled_link.make_rules((z / "zmij.d").read_bytes(), origin["cold"]["zmij"]),
           "invalid native Cargo record or depfile rules")
    linked, = [r for r in native["wild_processes"] if r["event"] == end["cli_link"]]
    b.need(linked["rustc_crate"] == "ruff" and linked["output"] == end["cli_linked_file"] and
           native["cargos"][0]["argv"][1:] == job.old.CARGO[2:], "CLI compiler/link provenance")
    return {"run": current["run"], "boot": current["boot"], "head": current["head"], "physical_execs": len(closed["execs"]),
            "full_rustcs": len(native["rustcs"]), "wild_outputs": native["wild"], "gnu_configure_links": len(native["other_linkers"]),
            "typed": len(rows), "bodies": end["native"], "positive_ledger": closed["sha256"], "performance_observations": 0}


if __name__ == "__main__":
    print(json.dumps(reopen(Path(sys.argv[1])), sort_keys=True))
