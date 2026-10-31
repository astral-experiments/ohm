"""Read both extracted original Actions artifacts. No cross-machine speed ratio is computed."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "mixed-generics-ruff")]
from kits import need
import cost
import study


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def native(root, folder, value):
    listing = gzip.decompress((folder / "native-list.stdout.gz").read_bytes())
    names = sorted(line[:-6] for line in listing.decode().splitlines() if line.endswith(": test"))
    need(names == value["names"] == read(folder / "actual-test-names.json")
         and len(set(names)) == len(names) > 100 and hashlib.sha256(listing).hexdigest() == value["list_sha"]
         and read(folder / "native-list.status.json") == value["list_exit"] == 0, "wrong raw native inventory")
    for name, verdict in value["runtime"].items():
        base = "native-" + name.split("::")[-1]
        run = gzip.decompress((folder / (base + ".stdout.gz")).read_bytes())
        need(verdict == {"code": 0, "one_named": True} and read(folder / (base + ".status.json")) == 0
             and ("test " + name + " ... ok").encode() in run and b"1 passed; 0 failed" in run,
             "wrong raw named verdict")
    img = read(root / value["elf"]["native_index"])
    need(img["sha256"] == value["elf"]["sha256"] and img["size"] == value["elf"]["size"]
         and img["segments"] and any(s[1] == ".text" for s in img["sections"]), "incomplete native ELF receipt")
    return value


def registered(root, role, run, head):
    entry = read(root / "enrollment.json")
    need((entry["run"], entry["attempt"], entry["head"], entry["role"], entry["argv"]) ==
         (run, 1, head, role, study.panel.E2E), "wrong worker or command")
    old = read(root / "sdk/complete-release.json.gz")
    new = read(root / "sdk/actual-installed.json.gz")
    need(set(old) == set(new) and {n for n in old if old[n] != new[n]} == {"bin/cargo"}
         and new["bin/cargo"]["sha256"] == study.CARGOS[role][1]
         and old["bin/cargo"]["sha256"] == study.SDK["cargo"] and "bin/rustdoc" in new,
         "wrong signed SDK or unexpected changed component")
    originals = {}
    for state in ("original", "reversed"):
        d = root / "clean" / state
        r = read(d / "visit.json")
        need(r["status"] == 0 and r["terminal"] == {"reason": "build-finished", "success": True}
             and not r["issues"], "invalid independent clean")
        originals[state] = native(root, d, r["test"])
    need(set(originals["original"]["names"]) - set(originals["reversed"]["names"])
         == set(originals["original"]["new_cases"]) and len(originals["original"]["new_cases"]) == 1
         and not set(originals["reversed"]["names"]) - set(originals["original"]["names"]), "wrong edit delta")
    need(originals["original"]["elf"]["sha256"] != originals["reversed"]["elf"]["sha256"], "edit left identical binary")
    by_phase = {}
    for phase, state in (("cold","original"),("prior-repeat-1","original"),("prior-repeat-2","original"),
                         ("edited","reversed"),("edit-repeat","reversed"),("restored","original"),("restore-repeat","original")):
        d = root / "trace" / phase
        r = read(d / "visit.json")
        x = native(root, d, r["test"])
        need(not r["issues"] and all(x[k] == originals[state][k] for k in ("names", "list_sha", "runtime"))
             and x["elf"]["sha256"] == originals[state]["elf"]["sha256"], "failed own clean on " + phase)
        p = read(d / "physical.json")
        events = read(d / "execs.json.gz")
        source = [e for e in events if e[1] == [new["bin/rustc"]["dev"], new["bin/rustc"]["ino"]]
                  and "--crate-name" in e[3] and "--out-dir" in e[3] and e[3][e[3].index("--crate-name")+1] == "e2e"]
        compiles = ["link-only" if any(a.removeprefix("-Z").split("=", 1)[0] == "link-only" for a in e[3])
                    else "full" for e in source]
        linked = [z for z in p["wild"] if z["same_returned_e2e"]]
        for link in linked:
            ev, = [e for e in events if e[0] == link["pid"] and e[1] == link["identity"] and "-o" in e[3]]
            need(ev[3][ev[3].index("-o")+1] == link["output"] and link["identity"] ==
                 [new[str(study.WILD)]["dev"], new[str(study.WILD)]["ino"]], "wrong physical returned linker")
        if phase in ("edited", "restored"):
            need(len(linked) == 1, "genuine edit lacked physical Wild")
        by_phase[phase] = {"e2e": compiles, "wild": len(linked), "total_wild": len(p["wild"]),
                          "full": [x[1] for x in p["compilers"] if x[2] == "full"]}
    info = []
    for phase in ("repeat-1", "repeat-2"):
        d = root / "info" / phase
        cmd = read(d / "command.json")
        need(cmd["status"] == 0 and cmd["argv"] == study.panel.E2E and cmd["logging"], "not a logging-only repeat")
        returned = native(root, d, read(d / "test.json"))
        need(returned["elf"]["sha256"] == originals["original"]["elf"]["sha256"], "INFO path changed binary")
        lines = gzip.decompress((d / "stderr.gz").read_bytes())
        relevant = [(i,l) for i,l in enumerate(lines.decode(errors="replace").splitlines(), 1)
                    if ("ty_server" in l and ("early cutoff" in l or "relink-only" in l or "fingerprint" in l))]
        fp = read(d / "proof-inputs/fingerprints.json")
        for path, (size, digest) in fp.items():
            raw = gzip.decompress((d / "proof-inputs" / (Path(path).name + ".gz")).read_bytes())
            need(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest, "changed enrolled depinfo")
        markers = read(d / "proof-inputs/workspace-markers.json")
        for size, digest, text in markers.values():
            need(len(bytes.fromhex(text)) == size and hashlib.sha256(bytes.fromhex(text)).hexdigest() == digest, "marker")
        info.append({"stderr_sha256": hashlib.sha256(lines).hexdigest(), "matching_line_count": len(relevant),
                     "e2e_reason_or_action": [(i, l) for i,l in relevant if ("fs_status=" in l and "/out/e2e-" in l)
                     or "reusing cached codegen for ty_server " in l], "markers": markers,
                     "raw_recipe_objects": len(read(d / "proof-inputs/rlink-objects.json"))})
    sem = read(root / "semantics.json")
    need(not sem["issues"], sem["issues"])
    final = read(root / "verdict.json")
    need(not final["semantic_issues"], final["semantic_issues"])
    data = {"unavailable": final["attribution_unavailable"]}
    scores = root / "attribution/scores.json"
    if scores.exists():
        stage = root / "attribution"
        cal = cost.check_calibration(stage / "calibration")
        need(cal == read(stage / "calibration.json"), "changed underlying calibration")
        for i, mode in enumerate(cost.SCHEDULE, 1):
            d = stage / "unchanged" / f"{i}-{mode}"
            kind = native(root, d, read(d / "test.json"))
            need(kind["elf"]["sha256"] == originals["original"]["elf"]["sha256"], "PMU visit changed binary")
        val = cost.score(stage / "unchanged", read(stage / "enrollment.json"))
        need(val == read(scores) and val["measurement_admitted"] == final["qualified_cost"], "changed PMU verdict")
        data["admitted"] = val["measurement_admitted"]
        data["descriptive_samples"] = val
    return {"role": role, "physical": by_phase, "info": info, "cost": data,
            "test_sets": {name:r["names"] for name,r in originals.items()},
            "named_verdicts": {name:r["runtime"] for name,r in originals.items()},
            "common_sdk": {n:[v["sha256"],v["size"],v["mode"],v["link"]] for n,v in old.items()}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("strict", type=Path)
    ap.add_argument("pr293", type=Path)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    rows = [registered(d, role, a.run, a.head) for d, role in [(a.strict, "strict"), (a.pr293, "293")]]
    for key in ("common_sdk", "test_sets", "named_verdicts"):
        need(rows[0][key] == rows[1][key], "workers disagree on " + key)
    for r in rows:
        r.pop("common_sdk")
    a.output.write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
