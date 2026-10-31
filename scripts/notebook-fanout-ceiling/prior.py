"""Read the four original ZIPs. Historical edit PMU is whole-only; signed scoped PMU is unchanged-only."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c

SOURCES = {
    "source-parent": (
        13027075088,
        "4adb181df602589e65f922fb782b5d69b9726c5a742fcf104050171918d6d287",
        444,
    ),
    "source-mixed": (
        13025854595,
        "df8995f15a02fc8ce1891d1bfd56d644eb35c40c8223b779d5dff66dcd192619",
        445,
    ),
    "signed-strict": (
        13027159509,
        "fdd3fa987709c0c5431a1e51a89f626f18fad83fb07e75f100a1309ce720c429",
        548,
    ),
    "signed-293": (
        13027883805,
        "289f54cfca5066dd8fa6132a335aef12615b297102298b8c86bb3552be6da0dc",
        539,
    ),
}


def decode(z, name):
    raw = z.read(name)
    return json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


def checked_archive(z, stage):
    names = set(z.namelist())
    ret = {}
    record = decode(z, "registration.json" if stage else "enrollment.json")
    subject = record.get("subject", record)
    c.require(
        record["argv"] == c.CLI
        and subject["source"] == c.RUFF
        and (subject["e2e"]["patch_sha256"] if stage else subject["patch"]) == c.PATCH,
        "other edit",
    )
    ret.update(run=record["run"], head=record["head"], physical={})
    for phase in ("edited", "restored"):
        raw = gzip.decompress(z.read(f"trace/{phase}/stdout.jsonl.gz"))
        events = decode(z, f"trace/{phase}/execs.json.gz")
        command = decode(z, f"trace/{phase}/command.json")
        root = Path(command["working_directory"]).parent
        inv, products = c.typed(raw, root)
        counts = {}
        for _, _, _, args in events:
            if "--crate-name" in args and "--out-dir" in args:
                owner, output = c.compiler(args, root)
                c.require(
                    owner not in counts and products[owner] == output, (owner, "wrong concrete output")
                )
                counts[owner] = 1
        wild = decode(z, f"trace/{phase}/physical.json")["wild"]
        c.require(
            set(counts) == c.EDIT
            and len(wild) == 2
            and sum(w["same_returned_e2e"] for w in wild) == 1,
            "incomplete native roster",
        )
        edge = {}
        prev = ("prior-repeat" if stage else "prior-repeat-1") if phase == "edited" else "edit-repeat"

        def owned(which):
            return {
                n: {
                    p.name: tuple(row[i] for i in (1, 2, 5, 7))
                    for row in files
                    if (p := Path(row[0])).suffix == ".o"
                    and len(p.parts) > 5
                    and p.parts[-3].startswith(n + "-")
                    and p.parts[2] == "incremental"
                }
                for n in c.EIGHT
                for files in [decode(z, f"trace/{which}/allocated-files.json.gz")]
            }

        a, b = owned(prev), owned(phase)
        for n, want in c.EIGHT.items():
            c.require(len(a[n]) == want and a[n] == b[n], (n, phase, "changed signed work product"))
            edge[n] = len(a[n])
        ret["physical"][phase] = {
            "full": sorted(counts),
            "distinct_typed": len(set(inv)),
            "cargo_artifacts": len(inv),
            "wild_links": len(wild),
            "held_native_objects": edge,
            "tests": len(decode(z, f"trace/{phase}/actual-test-names.json")),
        }
    if stage:
        files = sorted(n for n in names if n.endswith("/whole.json"))
        c.require(
            len(files) == 6 and all(f"pmu/{n}/whole.json" in files for n in ["cold", *c.STATES]), files
        )
        c.require(
            not any(n.endswith(("/samples.tsv", "/counts.tsv")) for n in names),
            "unexpected component ledger",
        )
        ret["edit_whole_only"] = {}
        for f in files:
            v = decode(z, f)
            c.require(v["enabled"] == v["running"] > 0 and v["event_errno"] == v["code"] == 0, f)
            ret["edit_whole_only"][f.split("/")[1]] = v["instructions"]
    else:
        scoped = sorted(v for v in names if v.endswith("/counts.tsv"))
        c.require(
            scoped
            and all(
                v.startswith(("attribution/calibration/", "attribution/unchanged/")) for v in scoped
            ),
            "unexpected scoped costs",
        )
        result = decode(z, "attribution/scores.json")
        c.require(
            len(result["samples"]) == 5 and result["measurement_admitted"],
            "incomplete unchanged split",
        )
        ret["signed_sdk_sha256"] = c.signed_closure(decode(z, "sdk/complete-release.json.gz"))
        ret["unchanged_only"] = result["samples"][1::2]
    ret["edited_component_counts_available"] = False
    return ret


def main(paths):
    result = {}
    for label, (ix, h, count) in SOURCES.items():
        (file,) = [p for p in paths if str(ix) in p.name]
        with file.open("rb") as f:
            c.require(
                hashlib.file_digest(f, "sha256").hexdigest() == h, (label, "different original ZIP")
            )
        with ZipFile(file) as z:
            c.require(
                len(set(z.namelist())) == len(z.namelist()) == count and z.testzip() is None,
                "member list",
            )
            result[label] = {
                "original_id": ix,
                "original_sha256": h,
                "members": count,
                **checked_archive(z, label.startswith("source")),
            }
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archives", nargs=4, type=Path)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    row = main(args.archives)
    out = json.dumps(row, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(out)
    else:
        print(out, end="")
