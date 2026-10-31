"""Bind the stable parts of the two original default cold native rosters."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


def need(ok, reason):
    if not ok:
        raise ValueError(str(reason))


def digest(value):
    return hashlib.sha256((json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()).hexdigest()


def values(argv, flag):
    return [entry for i, entry in enumerate(argv) if i and argv[i-1] == flag] + [
        entry[len(flag) + 1:] for entry in argv if entry.startswith(flag + "=")
    ]


def shapes(native):
    compilers = []
    probe_owners = {}
    for r in native["rustcs"]:
        argv = r["argv"]
        # Rust probes can spell an explicit temporary path in --emit. The emission
        # kinds are stable. The complete original operands remain in the native ledger.
        emits = sorted(e.split("=", 1)[0] for part in values(argv, "--emit") for e in part.split(","))
        crate = r["crate"]
        if crate.startswith("autocfg_"):
            match = re.fullmatch(r"autocfg_([a-f0-9]{16})_([01])", crate)
            need(match and argv[-1] == "-" and emits == ["llvm-ir"] and values(argv, "--crate-type") == ["lib"],
                 ("unexpected autocfg probe", crate, argv[-1]))
            out, = values(argv, "--out-dir")
            owner = Path(out).parent.parent.name
            need(owner in {"memoffset", "num-traits", "fs-err"} and Path(out).name == "out", ("probe owner", out))
            need(probe_owners.setdefault(owner, match[1]) == match[1], ("probe UUID changed within one owner", owner))
            crate = f"autocfg/{owner}/{match[2]}"
        compilers.append([crate, r["mode"], values(argv, "--crate-type"), emits])
    need(len(set(probe_owners.values())) == len(probe_owners) == 3, "autocfg producer identities")
    wild = sorted(Path(r["output"]).name for r in native["wild_processes"])
    other = Counter(r["kind"] for r in native["other_linkers"])
    return {"rustc": sorted(compilers, key=lambda x: json.dumps(x, separators=(",", ":"))),
            "wild_outputs": wild, "system_links": dict(sorted(other.items())),
            "real_cargo": native["real_cargo"], "wild_queries": len(native["wild_queries"])}


def original(path, arm):
    with path.open("rb") as f:
        zip_sha = hashlib.file_digest(f, "sha256").hexdigest()
    member = "structural/" + arm + "/cold-A/"
    with zipfile.ZipFile(path) as z:
        raw = z.read(member + "native-execs.json.gz")
        visit = json.loads(z.read(member + "visit.json"))
        typed = json.loads(gzip.decompress(z.read(member + "roster.json.gz")))
    need(len(typed["members"]) == 375 and typed["members"] == typed["dirty"], "original is not 375 cold units")
    need(visit["dirty_digest"] == visit["graph"] == digest(typed["members"]), "original cold typed commitment")
    raw_native = json.loads(gzip.decompress(raw))
    native = shapes(raw_native)
    need(len(native["rustc"]) == 379 and len(native["wild_outputs"]) == 69, "original native count")
    need(set(r[1] for r in native["rustc"]) == {"full"}, "unexpected original link-only")
    return native, {"arm": arm, "archive": path.name, "archive_sha256": zip_sha,
                    "member": member + "native-execs.json.gz", "member_sha256": hashlib.sha256(raw).hexdigest(),
                    "typed": visit["graph"], "successful_execs": raw_native["successful_exec_count"]}


def registration(first, second):
    a, origin1 = original(Path(first), "Foff")
    b, origin2 = original(Path(second), "Koff")
    need(a == b and origin1["typed"] == origin2["typed"], "independent original off cold rosters differ")
    need(origin1["successful_execs"] == origin2["successful_execs"] == 4188, "independent cold exec totals differ")
    return {"originals": [origin1, origin2], "typed": origin1["typed"], "native": a, "successful_execs": 4188}


if __name__ == "__main__":
    print(json.dumps(registration(*sys.argv[1:]), separators=(",", ":"), sort_keys=True))
