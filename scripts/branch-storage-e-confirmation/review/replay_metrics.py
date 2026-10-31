"""Independent pilot readback. The functions take raw receipts and have no worker imports."""
from fractions import Fraction
import hashlib
import json
from pathlib import PurePosixPath
import stat


VISITS = ("cold-A", "first-B", "return-A", "return-B", "unchanged-B", "invalid", "repair")
RETURNS = ("return-A", "return-B")
SDK = {
    "F": ("Foff", "Fon"),
    "K": ("Koff", "Kon"),
}
COMMAND = ["cargo", "+ohm", "build", "-p", "ruff", "--bin", "ruff", "--locked",
           "--offline", "-j4", "--message-format=json"]
REVS = {
    "A": "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13",
    "B": "7b13f01ba1569887a25670820764b24c206da8e5",
}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def allocation(ledger, totals, reading):
    by_root = {"target": set(), "build": set()}
    inodes = {}
    packed = set()
    private = set()
    for name, row in ledger.items():
        path = PurePosixPath(name)
        need(path.parts and path.as_posix() == name and ".." not in path.parts and
             path.parts[0] in by_root, ("unsafe ledger member", name))
        need(len(row) == 6 and all(type(n) is int and n >= 0 for n in row),
             ("invalid physical stat", name))
        dev, ino, nlinks, mode, blocks, size = row
        need(ino > 0 and nlinks >= 1 and stat.S_IFMT(mode) != 0, ("bad inode", name))
        key = (dev, ino)
        need(inodes.setdefault(key, row) == row, ("inconsistent hardlink", name))
        by_root[path.parts[0]].add(key)
        if stat.S_ISREG(mode) and path.name.startswith("ohm-packed-object-"):
            packed.add(key)
        if "incremental" in path.parts and path.name.startswith("s-") and path.name.endswith("-working"):
            private.add(name)
    def byte_count(keys):
        return sum(inodes[k][4] * 512 for k in keys)
    common = by_root["target"] & by_root["build"]
    union = byte_count(inodes)
    roots = {k: byte_count(v) for k, v in by_root.items()}
    need(union == sum(roots.values()) - byte_count(common), "root union")
    need(union == totals["allocated"] == reading["find_bytes"] == reading["du_bytes"] ==
         reading["python_bytes"], "allocated against three independent observations")
    need(len(ledger) == totals["all_names"] and
         len(inodes) == totals["all_inodes"] == reading["find_inodes"] == reading["python_inodes"],
         "physical file count")
    need(roots == totals["roots"] and len(common) == totals["shared_inodes"] and
         byte_count(common) == totals["bytes_aliased_between_roots"], "hardlink allocation")
    need(len(packed) == totals["packed_files"] and byte_count(packed) == totals["packed_bytes"],
         "packed allocation")
    need(sorted(private) == totals["failed_sessions"], "working sessions")
    return union


def measured_count(raw, expected_exit):
    fields = ("code", "event_errno", "instructions", "enabled", "running")
    need(all(type(raw[k]) is int for k in fields), "malformed perf_event_open result")
    need(raw["code"] == expected_exit and raw["event_errno"] == 0, "exit or PMU failure")
    need(raw["instructions"] > 0 and 0 < raw["running"] <= raw["enabled"] and
         1000 * raw["running"] >= 995 * raw["enabled"], "instruction scheduling coverage")
    return raw["instructions"]


def cargo_messages(data, diagnostics, record, expected_exit, source):
    need(record["argv"] == COMMAND, "different native Cargo command")
    need(record["exit"] == expected_exit and record["stdout_sha256"] == sha(data) and
         record["stderr_sha256"] == sha(diagnostics), "unmatched Cargo process")
    events = [json.loads(line) for line in data.splitlines()]
    finished = {"reason": "build-finished", "success": expected_exit == 0}
    need(events and events[-1] == finished and
         sum(e.get("reason") == "build-finished" for e in events) == 1, "Cargo final verdict")
    if expected_exit:
        errors = [e["message"] for e in events if e["reason"] == "compiler-message"
                  and e["message"].get("level") == "error"]
        code = lambda e: (e.get("code") or {}).get("code")
        need(any(code(e) == "E0308" and any(
            "ohm_branch_switch_invalid" in t["text"] for s in e["spans"] for t in s["text"]
        ) for e in errors), "expected failure from the deliberately wrong parser function")
        return None
    units = []
    dirty = []
    prefix = PurePosixPath(source).as_uri()
    for e in events:
        if e["reason"] != "compiler-artifact":
            continue
        id_ = e["package_id"]
        normalized = id_.replace(prefix, "file:///__public_ruff_source__")
        need(not id_.startswith("path+") or normalized != id_, ("unexpected path source", id_))
        t = e["target"]
        unit = dict(id=normalized, name=t["name"], kind=t["kind"], crate_types=t["crate_types"],
                    features=e["features"], profile=e["profile"])
        units.append(unit)
        need(type(e["fresh"]) is bool, "untyped Cargo freshness")
        if not e["fresh"]:
            dirty.append(unit)
    need(len(units) == 375, ("complete typed graph", len(units)))
    return {"members": sorted(units, key=canonical), "dirty": sorted(dirty, key=canonical)}


def ratio(top, bottom):
    f = Fraction(top, bottom)
    return {"numerator": top, "denominator": bottom, "ratio": float(f)}


def scores(arms):
    """Call only after native, inventory, scope and complete host admission."""
    need(set(arms) == set(sum(SDK.values(), ())), "incomplete four-arm pilot")
    report = {}
    for role, (off, on) in SDK.items():
        a, b = arms[off], arms[on]
        need(set(a) == set(b) == set(VISITS), "incomplete visits")
        per_visit = {}
        for visit in VISITS:
            x, y = a[visit], b[visit]
            need(x["instructions"] > 0 and y["instructions"] > 0, "zero units")
            per_visit[visit] = {
                "instructions_off_over_on": ratio(x["instructions"], y["instructions"]),
                "allocated_bytes_off": x["allocated"],
                "allocated_bytes_on": y["allocated"],
                "additional_allocated_bytes": y["allocated"] - x["allocated"],
            }
        cycles = {}
        for name, visits in {"both_returns": RETURNS,
                             "first_switch_and_first_return": ("first-B", "return-A"),
                             "installation_through_both_returns": VISITS[:4]}.items():
            cycles[name] = ratio(sum(a[p]["instructions"] for p in visits),
                                 sum(b[p]["instructions"] for p in visits))
        initial = sum(b[p]["instructions"] - a[p]["instructions"] for p in ("cold-A", "first-B"))
        saving = sum(a[p]["instructions"] - b[p]["instructions"] for p in RETURNS)
        break_even = 0 if initial <= 0 else ((initial + saving - 1) // saving if saving > 0 else None)
        report[role] = {"visits": per_visit, "combined": cycles,
                        "repeat_cycle_break_even_model": {
                            "extra_instructions_through_first_B": initial,
                            "instructions_saved_on_observed_return_pair": saving,
                            "pairs_to_repay_at_that_rate": break_even},
                        "each_return_at_least_2x": all(
                            a[p]["instructions"] >= 2 * b[p]["instructions"] for p in RETURNS)}
    report["packed_on_vs_full_on"] = {
        p: {"instruction_cost_ratio": ratio(arms["Kon"][p]["instructions"],
                                            arms["Fon"][p]["instructions"]),
            "additional_allocated_bytes": arms["Kon"][p]["allocated"] - arms["Fon"][p]["allocated"]}
        for p in VISITS}
    return report
