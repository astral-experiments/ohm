"""Reopen every complete Callgrind stream and the native input and placement records."""

import gzip
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES = (
    "OHMInputEligibility",
    "OHMCloneModule",
    "OHMStockDeadArgAndGlobalDCE",
    "OHMTypedBitcodeAndPlacements",
    "OHMDestroyScratch",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def check_trace(raw, row):
    require(digest(raw) == row["trace_sha256"], "trace bytes")
    symbols = {}
    caller = callee = ""
    incoming = {}
    lines = raw.decode().splitlines()
    require([x for x in lines if x.startswith("events:")] == ["events: Ir"], "counter")
    totals = [int(x.split()[1]) for x in lines if x.startswith("totals:")]
    require(totals == [row["total_ir"]], "total")
    require(any(x.startswith("cmd: reader ") and row["phase"] in x.split() for x in lines), "mode")

    def symbol(value):
        record = re.fullmatch(r"\((\d+)\)(?: (.*))?", value)
        if not record:
            return value
        number, name = record.groups()
        if name is not None:
            symbols[number] = name
        return symbols[number]

    for i, line in enumerate(lines):
        if line.startswith("fn="):
            caller = symbol(line[3:])
        elif line.startswith("cfn="):
            callee = symbol(line[4:])
        elif line.startswith("calls=") and callee in STAGES:
            calls = int(line[6:].split()[0])
            instructions = int(lines[i + 1].split()[-1])
            incoming.setdefault(callee, []).append([caller, calls, instructions])

    require(incoming == row["call_ir"], "physical call graph")
    expected = set() if row["phase"] == "parse" else set(STAGES)
    require(set(incoming) == expected, "stage roster")
    require(all(len(edges) == 1 and edges[0][1] == 1 for edges in incoming.values()), "multiplicity")
    require(row["other_ir"] == totals[0] - sum(x[0][2] for x in incoming.values()), "residual")


def tar_records(path):
    with subprocess.Popen(["zstd", "-qdc", path], stdout=subprocess.PIPE) as process:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                require(member.isreg(), "regular tar member")
                yield member.name, archive.extractfile(member).read()
        require(process.wait() == 0, "zstd")


def verify():
    for line in (ROOT / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ")
        require("/" not in name and digest((ROOT / name).read_bytes()) == expected, name)
    receipts = json.loads(gzip.decompress((ROOT / "observations.json.gz").read_bytes()))
    native = receipts["native"]
    baseline = receipts["baseline"]
    require(set(native) == set(baseline) and len(native) == 21, "original modules")
    all_wires = {name[:-4]: raw for name, raw in tar_records(ROOT / "current-placement-wires.tar.zst")}
    for unit, pair in native.items():
        for role in ("old", "new"):
            record = pair[role]
            require(record["status"] == "eligible" and record["post_dae_roundtrip"], "inverse")
            require(record["untouched_ordinary_module"] == record["unmodified_clone"], "unchanged ordinary IR")
            wire = all_wires[record["placements_sha256"]]
            require(digest(wire) == record["placements_sha256"] and len(wire) == record["placement_bytes"], "placements")
        require(pair["same"] == (pair["old"]["complete_key"] == pair["new"]["complete_key"]), "key")
        require(pair["new"]["input"] == baseline[unit]["new_preopt"], "physical baseline input")

    parsed = {}
    policy = {}
    complete = {}
    original = sum(row["total"] for row in baseline.values())
    eligible = sum(baseline[unit]["total"] for unit, row in native.items() if row["same"])
    for collection in ("initial", "full"):
        records = receipts[collection]["observations"]
        n = 45 if collection == "initial" else 21
        require(len(records) == n, "complete roster")
        members = tar_records(ROOT / f"{collection}-callgrind.tar.zst")
        for seq, ((name, raw), row) in enumerate(zip(members, records, strict=True), 1):
            require(seq == row["seq"] and name == row["trace"], "chronology")
            require(row["native_key"] == native[row["unit"]]["new"]["complete_key"], "native input gate")
            check_trace(raw, row)
            if row["cohort"] == "primary":
                target = parsed if row["phase"] == "parse" else policy
                target[row["unit"]] = row
            elif collection == "full":
                complete[row["unit"]] = row

    require(set(native) == set(parsed) == set(policy) == set(complete), "full matrices")
    components = {s: sum(row["call_ir"][s][0][2] for row in policy.values()) for s in STAGES}
    for unit in native:
        require(policy[unit]["call_ir"] == complete[unit]["call_ir"], "component reproduction")
    cost = sum(r["total_ir"] for r in policy.values())
    parse = sum(r["total_ir"] for r in parsed.values())
    total = sum(r["total_ir"] for r in complete.values())
    require((original, eligible, parse, cost, total) == (120906271208, 83908903279, 3908761345, 7842462241, 12261923442), "archived totals")
    require(sum(row["same"] for row in native.values()) == 15, "eligible count")
    pointer = receipts["observed_pointer"]["rows"]
    require([pointer[r]["native"]["value"] for r in ("old", "new")] == [5, 9], "native indirect call")
    require(pointer["old"]["typed"]["complete_key"] != pointer["new"]["typed"]["complete_key"], "observed caller")
    neg = receipts["negative"]["native_results"]
    require(len(neg) == 25 and sum(r["status"] == "fallback" for r in neg.values()) == 19, "negative controls")
    print(json.dumps({"current_parse_and_verify_Ir": parse, "policy_Ir": cost, "components": components,
                      "all_including_ordinary_teardown_Ir": total, "eligible_original_backend_Ir": eligible,
                      "original_backend_Ir": original}, indent=2))


if __name__ == "__main__":
    verify()
