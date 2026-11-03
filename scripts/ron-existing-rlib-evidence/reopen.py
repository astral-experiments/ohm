"""Read the physical producer, supervisor, native selections and products for a fixed role."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(p):
    with p.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def one(values):
    value, = values
    return value


def fields(file):
    result = {}
    charged = 0
    is_call = False
    for line in file.open(errors="replace"):
        name, sep, s = line.partition(":")
        if sep and name in {"pid", "cmd", "events", "summary", "totals"}:
            assert name not in result
            result[name] = s.strip()
        if line.startswith("calls="):
            is_call = True
        elif line[0] in "+-*0123456789":
            position, cost = line.split()
            if not is_call:
                charged += int(cost)
            is_call = False
    assert result["events"] == "Ir" and int(result["totals"]) == charged > 0
    return int(result["pid"]), result


def metadata(board, installed, work):
    """Use the independent signed-version Rust metadata decoder, keyed by stable definitions."""
    study = work / "metadata-readback"
    study.mkdir(exist_ok=True)
    events = study / "history/events"
    events.mkdir(parents=True, exist_ok=True)
    for idx, p in enumerate(installed):
        visit = events / f"visit-{idx:02}"
        visit.mkdir(exist_ok=True)
        f = visit / p.name
        if not f.exists():
            f.symlink_to(p)
        assert f.resolve(strict=True) == p.resolve(strict=True)
    gate = Path(__file__).resolve().parent.parent / "ron-module-resolution/decode.py"
    run = subprocess.run([sys.executable, "-IB", str(gate)], env={**os.environ, "RON_CONTROL_WORK": str(study)}, capture_output=True, check=True)
    (study / "decoder.stdout").write_bytes(run.stdout)
    typed = json.loads((study / "history/metadata-comparison.json").read_bytes())
    assert set(typed) == {sha(p) for p in installed}
    for h, r in typed.items():
        assert set(r["hash_fields"]) <= {"full"}
        assert all(not v["different"] and v["same_multiset"] for v in r["tables"].values())
        for slot in r["different_physical_indices"].values():
            assert all("opaque#" in str(name) and "'_" in str(name) for name in slot.values())
    return typed


def main():
    work = Path(sys.argv[1]).resolve(strict=True)
    root = work / "prices"
    original = json.loads((root / "closed.json").read_bytes())
    reg = json.loads((work / "registration.json").read_bytes())
    assert len(original) == 8 and len(reg["schedule"]) == 2 and reg["schedule"][1] == reg["schedule"][0][::-1]
    table = {(r["block"], r["role"], r["stage"]): r for r in original}
    result = []
    meta = []
    regular = {}
    for block, order in enumerate(reg["schedule"], 1):
        for role in order:
            for phase in ("cold", "unchanged"):
                d = root / f"block-{block}-{role}" / phase
                actual = json.loads((d / "completed.json").read_bytes())
                assert table[block, role, phase] == actual
                parent, child, code, rss, *identity = (d / "children.tsv").read_text().split()
                profiles = dict(fields(f) for f in sorted(d.glob("callgrind.*")))
                assert code == "0" and parent != child and set(profiles) == {int(parent), int(child)}
                counts = [int(profiles[int(pid)]["totals"]) for pid in (parent, child)]
                assert counts == [actual["supervisor_Ir"], actual["compiler_Ir"]]
                assert sum(counts) == actual["total_Ir"]
                assert int(rss) == int(actual["child_rss_kib_in_counter"])
                enrolled=json.loads((d/"start.json").read_bytes())["argv"]
                position,=[i for i,field in enumerate(enrolled)if Path(field).name=="supervise"]
                assert enrolled[position+1]==("reuse" if role=="candidate"else "stock")
                assert profiles[int(parent)]["cmd"]==" ".join(enrolled[position:])
                assert profiles[int(child)]["cmd"]==" ".join(enrolled[position+2:])
                assert Path(profiles[int(child)]["cmd"].split()[0]).name == "rustc"
                calls = Counter()
                sets = {}
                if (d / "native.tsv").exists():
                    for line in (d / "native.tsv").read_text().splitlines():
                        kind, name, *_ = line.split("\t")
                        calls[kind] += 1
                        names = sets.setdefault(kind, set())
                        assert name not in names
                        names.add(name)
                if role == "candidate":
                    assert len(identity) == 1 and len(identity[0]) == 64
                    assert calls["opt"] == calls["emit"] == 10 and sets["opt"] == sets["emit"]
                    assert calls["select"] == calls["replaced"] == (10 if phase == "unchanged" else 0)
                    if phase == "unchanged":
                        assert sets["select"] == sets["replaced"] == sets["opt"]
                else:
                    assert not identity and not calls
                assert dict(calls) == actual["calls"]
                saved = actual["files"]
                for name, record in saved.items():
                    p = d / name
                    assert p.stat().st_size == record["size"] and sha(p) == record["sha256"]
                    if p.suffix in (".d", ".rlib"):
                        assert regular.setdefault(p.suffix, sha(p)) == sha(p)
                    elif p.suffix == ".rmeta":
                        meta.append(p)
                assert (".ron-live-native-v2.tsv" in saved) == (role == "candidate")
                archive = one(d.glob("*.rlib"))
                members = subprocess.check_output(["ar", "t", str(archive)]).decode().splitlines()
                assert sum(name.endswith(".rcgu.o") for name in members) == 10
                receipt = saved.get(".ron-live-native-v2.tsv", {})
                result.append(dict(block=block, role=role, phase=phase, process_Ir=counts,
                                   total_Ir=sum(counts), guest_rss_KiB=int(rss), calls=dict(calls),
                                   installed_identity=identity, receipt_bytes=receipt.get("size", 0),
                                   allocated_bytes=sum(row["allocated"] for row in saved.values()),
                                   raw_files={f.name: sha(f) for f in d.iterdir() if f.is_file()},
                                   member_count=len(members)))
    assert len(meta) == 8
    decoded = metadata(work.parent, meta, work)
    out = dict(original_terminal_sha256=sha(root / "closed.json"), registration_sha256=sha(work / "registration.json"),
               rlib_and_depinfo=regular, typed=decoded, rows=result)
    terminal = work / "independent-prices.json"
    terminal.write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(sha(terminal), len(result), regular, flush=True)


if __name__ == "__main__":
    main()
