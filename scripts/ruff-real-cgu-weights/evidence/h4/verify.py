"""Verify the permanent H4 hardware observations, optionally reopening both full originals."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
SOURCES = HERE.parent.parent
sys.path.insert(0, str(SOURCES))
import object_windows
import typed_archive


def check(ok, detail):
    if not ok:
        raise ValueError(detail)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def measured(row):
    opening = row["open_return"]
    closing = row["close_entry"]
    native, enabled, running = (b - a for a, b in zip(opening, closing, strict=True))
    lifetime, total_enabled, total_running = row["worker_terminal"]
    check(0 < enabled == running <= total_running == total_enabled, "native PMU scheduling")
    check(0 < native <= lifetime, "native interval exceeds the worker")
    return native


def original(path, artifact, host, owners):
    with path.open("rb") as source:
        check(path.stat().st_size == artifact["size_in_bytes"] and
              "sha256:" + hashlib.file_digest(source, "sha256").hexdigest() == artifact["digest"],
              "complete GitHub ZIP differs")
    with zipfile.ZipFile(path) as source, tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        check(len(source.namelist()) == len(set(source.namelist())), "duplicate ZIP member")
        read = lambda name: json.loads(source.read(name))
        terminal = read("terminal.json")
        state = read("native-inputs.json")
        check(terminal["boot"] == host["boot"] and
              terminal["ordinary_parent"] == "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5",
              "terminal kernel boot or compiler")
        canonical = None
        for role, expected in host["archives"].items():
            summary = read(f"archive-{role}.json")
            compressed = source.read(f"archive-{role}.rlib.gz")
            check(digest(compressed) == summary["gzip_sha256"], "original compressed archive")
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as z:
                body = z.read(expected["bytes"] + 1)
            check(len(body) == expected["bytes"] and digest(body) == expected["original"],
                  "original complete rlib")
            projected, fields = typed_archive.project(body, owners["all_native"])
            check(fields["suffix"] == expected["suffix"] and
                  fields["full_main_rmeta"] == expected["main_metadata"] and
                  fields["raw_index"] == expected["index"] and len(fields["slots"]) == 250 and
                  fields["indices"]["count"] == 6297, "typed object/metadata correspondence")
            if canonical is None:
                canonical = projected
            check(canonical == projected and digest(projected) == expected["canonical"],
                  "complete within-boot projected archive")
        custody = source.read("native-window-custody.tar.gz")
        check(digest(custody) == host["raw_custody_sha256"], "original observed syscalls")
        with tarfile.open(fileobj=io.BytesIO(custody), mode="r:gz") as trace:
            names = trace.getnames()
            check(set(names) == set(state["files"]) and len(names) == len(set(names)),
                  "journal roster")
            for member in trace:
                check(member.isreg() and Path(member.name).name == member.name and member.size < 16 << 20,
                      "invalid journal")
                body = trace.extractfile(member).read()
                check(digest(body) == state["files"][member.name], "journal SHA-256")
                (root / member.name).write_bytes(body)
        rows = object_windows.prices(root, state["expected"], tuple(state["owner"]), state["libraries"])
        check(set(rows) == set(host["observations"]), "original object roster")
        owner, = object_windows.table(root / "owners.tsv")
        check(int(owner["image"]) == host["image"] and int(owner["tid"]) == host["main_tid"],
              "enrolled compiler physical owner")
        selected = (root / f"{host['image']:05}.nul").read_bytes()
        check(digest(selected) == host["argv_record"] and
              read("normal.json")["argv"][0][1] == [s.decode() for s in selected.split(b"\0")[4:-1]],
              "kernel original/pristine compiler argv")
        for name, row in rows.items():
            orig = host["observations"][name]
            check((row["native_instructions"], row["worker_instructions"], row["tid"], row["window"],
                   row["object"], row["bytes"]) ==
                  (measured(orig), orig["worker_terminal"][0], orig["tid"], orig["window"],
                   orig["object"], orig["bytes"]), "original physical worker or price")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, help="directory with original-1.zip and original-2.zip")
    args = parser.parse_args()
    receipt = load(HERE / "receipt.json")
    enrollment = receipt["enrollment"]
    for name, expected in enrollment["source_hashes"].items():
        check(digest((SOURCES / name).read_bytes()) == expected, "different producer " + name)
    meta = HERE / "metadata.json"
    check(digest(meta.read_bytes()) == receipt["independent_open_sha256"]["root-crossboot-rmeta.json"], "metadata comparison")
    owners = load(SOURCES / "owners.json")
    dirty = set(owners["dirty"])
    missed = dirty - set(owners["guarded_reused"])
    hosts = receipt["within_boot_native_and_behavior"]
    check(set(hosts) == {"1", "2"} and len({host["boot"] for host in hosts.values()}) == 2,
          "two independent kernel boots")
    costs = {}
    for rank, host in sorted(hosts.items()):
        rows = host["observations"]
        check(set(rows) == dirty and len({obs["tid"] for obs in rows.values()}) == len(rows) == 21 and
              all(obs["tid"] != host["main_tid"] for obs in rows.values()), "physical nonleader owner roster")
        check(all(row["object"] == owners["all_native"][name] for name, row in rows.items()),
              "enrolled native ELF")
        short, long = host["calibration"]["native"]
        check(390 * short < 100 * long < 410 * short, "4:1 calibration")
        if args.originals:
            original(args.originals / f"original-{rank}.zip", receipt["external_origins"][rank], host, owners)
        costs[rank] = {name: measured(value) for name, value in rows.items()}
        print(f"rank {rank}  six {sum(costs[rank][name] for name in missed):,}  all {sum(costs[rank].values()):,}")
    for name in sorted(dirty):
        a, b = costs["1"][name], costs["2"][name]
        check(100 * abs(a - b) < 2 * min(a, b), "unstable native price " + name)
    historical = receipt["historical_crossboot_qualification"]
    check(all(set(parts) == {"lib.rmeta"} for parts in historical["groups"].values()) and
          len({s["normalized_rlib"] for s in historical["sources"].values()}) == 3,
          "different full historical and cross-boot refusal")
    print("21/21 host-labelled observations agree at the registered threshold; complete semantic inputs differ.")


if __name__ == "__main__":
    main()
