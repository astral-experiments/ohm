"""Select and price the Unicode compiler from the actual kernel journals without worker code."""
import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from statistics import median
import zipfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def primary(z, role):
    base = role + "/check/observed-edit/tasks/"
    install = json.loads(z.read("installed-" + role + ".json"))["rustc"]
    journal = [r.split() for r in z.read(base + "epochs.tsv").splitlines()]
    owner = []
    for record, *part in journal:
        if record != b"I" or part[-1] != b"exec":
            continue
        index, pid = map(int, part[:2])
        payload = z.read(base + f"{index:05}.nul").split(b"\0")
        assert payload[-1] == b"" and int(payload[0]) == pid
        if list(map(int, payload[1:3])) != [install["device"], install["inode"]]:
            continue
        args = payload[4:-1]
        if b"--crate-name" not in args or args[args.index(b"--crate-name") + 1] != b"unicode_normalization":
            continue
        assert b"--emit=dep-info,metadata" in args and b"-Zlink-only" not in args
        assert sum(a.endswith(b"/unicode-normalization-0.1.25/src/lib.rs") for a in args) == 1
        count, = [tuple(map(int, r[3:])) for r in journal
                  if r[0] == b"R" and int(r[1]) == index and int(r[2]) == pid]
        instructions, enabled, running, status = count
        assert instructions > 0 and enabled == running > 0 and status == 0
        owner.append(instructions)
    value, = owner
    whole = json.loads(z.read(role + "/check/ordinary-edit/hardware.json"))
    assert whole["pid"] > 0 and whole["enabled"] == whole["running"] > 0 and whole["status"] == 0
    return {"owner": value, "whole": whole["instructions"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("verdict", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    verdict = json.loads(args.verdict.read_bytes())
    official = json.loads((args.directory / "official.json").read_bytes())
    assert official["run"]["status"] == "completed" and official["run"]["conclusion"] == "success"
    totals = {}
    for asset in official["artifacts"]:
        path = args.directory / (str(asset["id"]) + ".zip")
        assert path.stat().st_size == asset["size_in_bytes"] and "sha256:" + digest(path) == asset["digest"]
        with zipfile.ZipFile(path) as z:
            bind = json.loads(z.read("binding.json"))
            values = {role:primary(z,role) for role in ("C5","C7")}
        b, = [b for b in verdict["blocks"] if b["slot"] == bind["slot"] and b["boot"] == bind["boot"]]
        for role,v in values.items():
            assert v["owner"] == b["prices"][role]["check"]["observed-edit-rustc"]
            assert v["whole"] == b["prices"][role]["check"]["ordinary-edit"]
        totals[bind["slot"]] = values
    fractions = {k:[Fraction(v["C5"][k]-v["C7"][k],v["C5"][k]) for v in totals.values()] for k in ("owner","whole")}
    for metric,key in (("owner","median_rustc"),("whole","median_whole")):
        assert abs(100*float(median(fractions[metric]))-verdict[key]) < 1e-12
    args.out.write_text(json.dumps({"raw_counts":totals,"all_owners_saved_at_least_one_fifth":min(fractions["owner"])>=Fraction(1,5),
                       "all_whole_checks_improved":min(fractions["whole"])>0,"registered_projection":digest(args.verdict)},
                       sort_keys=True,indent=2)+"\n")


if __name__ == "__main__":
    main()
