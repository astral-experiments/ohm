"""Replay only the earlier structural rows. Never open an old hardware observation."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", "/home/runner/work/_temp")
import bindings as b
import kernel_events as events

PHASES = {"cold-A", "first-B", "return-A", "return-B", "unchanged-B", "invalid", "repair"}
PRIOR = {
    "41200174886-01-13042772691.zip": "09a83406fc1d9d011c573dc88784b3fdbca1edaa927b553f5d0356601baf1586",
    "41200174886-02-13043111933.zip": "aeef5d5226815f3d5cd8a11210a1f2265ee1291214e5e885eddee1dc2c3cbb65",
}
SECOND = "c6f91a9d7139549e7ecf082ba60b22be248ecce6852c7adcdd07f73173310814"


def collect(package, originals, export):
    history, _, _ = events.readers(package)
    result = {"on": {}, "off": {}}
    witnesses = []
    coverage = {}
    def add(archive, name, raw):
        prefix, arm, phase, base = name.split("/")
        b.need(prefix == "structural" and arm in b.ORDERS["01"] and phase in PHASES
               and base == "native-execs.json.gz", "structural phases only")
        native = json.loads(gzip.decompress(raw))
        row = events.phase_shape(native, phase, history)
        flag = "on" if arm.endswith("on") else "off"
        if phase in result[flag]:
            b.need(result[flag][phase] == row, ("genuine earlier native rosters differ", arm, phase, result[flag][phase], row))
        result[flag][phase] = row
        coverage.setdefault((flag, phase), set()).add(arm[0])
        witnesses.append([archive, name, hashlib.sha256(raw).hexdigest()])

    for name, sha in PRIOR.items():
        path = originals / name
        b.need(b.sha(path) == sha, ("changed earlier official ZIP", name))
        with zipfile.ZipFile(path) as z:
            for member in sorted(z.namelist()):
                if member.startswith("structural/") and member.endswith("/native-execs.json.gz"):
                    add(sha, member, z.read(member))
    index = json.loads((export / "origin.json").read_bytes())
    b.need((index["run"], index["head"], index["zip"]["id"], index["zip"]["sha256"]) ==
           (41204995845, "f3b1c0113bc9b4b197ed3789a1480876c7575442", 13045166729, SECOND)
           and len(index["members"]) == 12, "wrong on-arm originals")
    for member, (size, sha) in sorted(index["members"].items()):
        raw = (export / member).read_bytes()
        b.need(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, "changed individual original")
        add(SECOND, member, raw)
    b.need(all(set(table) == PHASES for table in result.values()) and all(roles == {"F", "K"} for roles in coverage.values())
           and len(witnesses) == 32, "missing arm-phase reproduction")
    result["origins"] = witnesses
    return result


if __name__ == "__main__":
    package, originals, export = map(lambda p: Path(p).resolve(strict=True), sys.argv[1:4])
    result = collect(package, originals, export)
    if len(sys.argv) == 5:
        b.save(Path(sys.argv[4]), result)
    else:
        b.need(result == json.loads(events.GOLD.read_bytes()), "different registered raw roster")
    print("Matched F and K for all 14 on/off/phase rosters in 32 original structural visits.")
