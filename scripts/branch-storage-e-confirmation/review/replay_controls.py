"""Reopen the host counter scope and backdated higher-priority native producer."""
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import re

from replay_metrics import need, sha
from replay_native import raw, read


CAL = "2f413ca94b84af2dbd6d6231bcf8d860c97ebee8"
OBS = "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
PACKAGING = Path("/home/dev-user/code/oss/ohm-package-qa-gnu-renderer-pfc-hardware-20261031")
OBSERVER = Path("/home/dev-user/code/oss/ohm-package-qa-gnu-renderer-library-workers-20261031")


def calibration(z, boot):
    ng = json.loads(z.read("observer.json"))
    host = json.loads(z.read("host.json"))
    need(host["raw_system"]["/proc/sys/kernel/random/boot_id"] == boot and
         len(set(host["affinity"])) == 8 and ng["ref"] == OBS, "meter source/boot")
    need(subprocess.check_output(["git", "-C", OBSERVER, "rev-parse", "HEAD"], text=True).strip() == OBS,
         "wrong verifier source checkout")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        src = root / "src"
        src.mkdir()
        for f in ("calibration.py", "ingress.py"):
            (src / f).write_bytes(subprocess.check_output(["git", "-C", PACKAGING, "show",
                                                           CAL + ":scripts/gnu-renderer-pfc-hardware/" + f]))
        for entry in z.infolist():
            name = PurePosixPath(entry.filename)
            if entry.is_dir() or name.parts[0] not in {
                "observers", "calibration", "calibration-commands", "worker-calibration",
                "worker-calibration.json", "observer.json"
            }:
                continue
            need(not name.is_absolute() and ".." not in name.parts and entry.file_size <= 24 << 20,
                 "unsafe calibration archive")
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            with (root / name).open("xb") as f:
                f.write(z.read(entry))
        need(all(sha((root / "observers" / n).read_bytes()) == h for n, h in ng["bins"].items()),
             "observer binary hashes")
        sys.path.insert(0, str(src))
        try:
            sp = importlib.util.spec_from_file_location("original_whole_pmu_calibration", src / "calibration.py")
            c = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(c)
            workers = c.replay(OBSERVER, root)
        finally:
            sys.path.remove(str(src))
        controls = json.loads((root / "calibration/admitted.json").read_bytes())
        need(controls["whole28"] and controls["nested"] and workers, "counter scope not validated")
        cpu = dict(s.split(":", 1) for s in host["cpuinfo"].splitlines() if ":" in s)
        cpu = {k.strip(): v.strip() for k, v in cpu.items()}
        cpu = {k: cpu[k] for k in ("vendor_id", "cpu family", "model", "model name", "stepping") if k in cpu}
        return {"calibrator": CAL, "observer": OBS, "boot": boot, "affinity": host["affinity"],
                "cpu": cpu, "platform": host["platform"], "machine": host["raw_system"]["/sys/class/dmi/id/product_name"],
                "pmu": host["raw_system"]["/sys/devices/cpu/caps/pmu_name"],
                "whole_control_cells": sum(len(v[0]) for v in controls["whole28"].values()),
                "nested": sorted(controls["nested"])}


def native_provider(z, arm):
    prefix = "providers/" + arm
    ordinary = prefix + "/provider-" + arm
    original = read(z, ordinary, "result.json")
    phases = {"cold-A": "17 1", "first-B": "29 2", "returned-A": "29 1", "invalid": None,
              "repair": "29 1", "empty-repair": "29 1"}
    for phase, output in phases.items():
        row = original[phase]
        p = ordinary + "/" + phase
        need(row["exit"] == (101 if output is None else 0) and read(z, p, "cargo.json.gz")["exit"] == row["exit"],
             "changed/corrupt native object on branch return")
        if output is not None:
            need(raw(z, p, "witness.stdout.gz").decode().strip() == row["output"] == output,
                 "returned executable linked the wrong archive")
    need(original["returned-A"]["binary"] == original["repair"]["binary"] ==
         original["empty-repair"]["binary"] != original["cold-A"]["binary"], "native repair versus empty build")
    desc = read(z, prefix, "complete.json")
    expected = {"absent": 0, "insert-83": 0, "same-inode-47": 0, "malformed": 101, "repair-47": 0, "remove": 0}
    need(desc["arm"] == arm and desc["status"] == expected, "native-provider rejection/verdict")
    records = {p: read(z, prefix + "/history/" + p, "provider.json") for p in expected}
    held = [records[p] for p in ("insert-83", "same-inode-47", "malformed", "repair-47")]
    need(held == desc["same_inode"] and len({(r["dev"], r["ino"], r["size"], r["mtime"]) for r in held}) == 1
         and held[1]["sha256"] == held[-1]["sha256"] and len({r["sha256"] for r in held}) == 3,
         "same-inode, size and mtime native control")
    want = {"absent": "0000", "insert-83": "0053", "same-inode-47": "002F", "malformed": None,
            "repair-47": "002F", "remove": "0000"}
    need(desc["values"] == want and desc["source"] == "93526150df078af7dd8fc4226cdcc469539d2001",
         "Ruff native generator expectation")
    seen = {}
    for phase, value in want.items():
        for lane in (("history",) if phase == "absent" else ("history", "empty")):
            base = prefix + "/" + lane + "/" + phase
            result = read(z, base, "observation.json")
            trace = z.read(base + "/exec-and-provider-open.gz")
            need(sha(trace) == result["trace"] and result["physical"]["ld"] and result["status"] == expected[phase],
                 "actual native relink, trace and status")
            events = [json.loads(s) for s in raw(z, base, "cargo.stdout.gz").splitlines()]
            need(events[-1] == {"reason": "build-finished", "success": value is not None}, "native Cargo verdict")
            if value is None:
                continue
            need(value == result["generate_code"] and set(result["generated"]) ==
                 {"generated.rs", "generated_alias.rs", "generated_phf.rs"}, "actual generated crate")
            for n, h in result["generated"].items():
                source = gzip.decompress(z.read("providers/objects/" + h + ".gz"))
                need(sha(source) == h, "generated source identity")
                if n == "generated_alias.rs":
                    need(re.findall(rb'\(b"NULL", .*?\\u\{(\w{4})\}', source) == [value.encode()],
                         "reopened generated NULL value")
            binary = gzip.decompress(z.read("providers/objects/" + result["reader_sha256"] + ".gz"))
            need(binary.startswith(b"\x7fELF") and sha(binary) == result["reader_sha256"], "native SDK consumer ELF")
            observed = raw(z, base, "reader-exec.stdout.gz").decode().splitlines()
            need(observed == result["reader"] and observed[:2] == [f"Some({int(value, 16)})", "Some(0)"],
                 "executed native API consumer")
            match = (result["generated"], observed, result["reader_sha256"])
            need(seen.setdefault(phase, match) == match, "same-path clean provider comparison")
    return {"status": expected, "generator": desc["values"], "branch_return_native_archive": phases,
            "native_source": desc["source"], "backdated_inplace_states": len(held)}
