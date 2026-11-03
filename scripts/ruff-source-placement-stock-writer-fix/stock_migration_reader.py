"""Independently reopen the donor artifacts, admitted ELF bodies and both real kernel histories."""

from contextlib import ExitStack
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_scope as scope
import stock_gate
import stock_artifacts as artifacts
import stock_migration as migration
import migrate_index
import readback as real

need, read = scope.base.need, real.read
PREFIX = "physical/migration/"


def scan(z, originals, enrollment, run, head):
    files = z.infolist()
    need(
        len(files) == len({i.filename for i in files})
        and sum(i.file_size for i in files) < 80 << 30
        and all(i.file_size < 6 << 30 for i in files)
        and z.testzip() is None,
        "corrupt or unbounded migration history",
    )
    term = read(z, PREFIX + "complete.json")
    need(
        term["run"] == run
        and term["qa"] == head
        and term["source"] == enrollment["source"]
        and term["counter_samples"] == 0
        and term["study"] == scope.base.sha(scope.HERE / "selected-study.json"),
        "incorrect independent migration registration or scoring",
    )
    expected = enrollment["admissions"]["C3b_native"]
    chosen = expected["cross_victim"]
    role = real.raw.checked_json(z, "physical/physical-roles.json", term["physical_roles"])
    need(role["aliases"] == scope.INTERNAL, "misidentified source-built participants")
    acceptance = stock_gate.sealed(
        read(z, PREFIX + "prior-native.json"), enrollment, migration=False
    )
    need(
        term["boot"] not in {x["boot"] for x in acceptance["admissions"].values()},
        "prerequisite boot reused",
    )
    signed = real.raw.verify_bytes(z)
    records = {}
    for family, (path, receipt, version) in originals.items():
        pref = PREFIX + "donor-" + family + "/"
        cache = read(z, pref + "verified.json")
        need(
            cache["version"] == version
            and cache["victim"] == chosen
            and read(z, PREFIX + "origin-" + family + ".json") == receipt,
            "changed authenticated source donor",
        )
        obj = gzip.decompress(z.read(pref + "old-object.o.gz"))
        index = gzip.decompress(z.read(pref + "work-products.bin.gz"))
        with zipfile.ZipFile(path) as original:
            raw = "physical/durability/object-corrupt/"
            need(
                obj == gzip.decompress(original.read(raw + "original-old-object.o.gz"))
                and index == gzip.decompress(original.read(raw + "original-work-products.bin.gz"))
                and cache["sha256"] == sha256(obj).hexdigest()
                and cache["index"] == sha256(index).hexdigest(),
                "actual published prior object or complete index differs",
            )
            src = read(original, "physical/physical-roles.json")["kits"]["C"]
            need(
                all(
                    src[k]["sha"] == v["sha"]
                    for k, v in role["kits"][scope.INTERNAL[family]].items()
                ),
                "different donor compiler, Cargo, LLVM or linker",
            )
            values = read(original, "physical/option/acquired.json")["C"]
            for ph, key in (("old", "old"), ("new", "clean-new")):
                data = z.read(pref + ph + "-owner.rlib.gz")
                href = values[key]["owner_archive"]["sha256"]
                need(
                    data == original.read("physical/owner-archives/" + href + ".gz")
                    and migration.durable.member_map(gzip.decompress(data))
                    == cache["reference"][ph]["archive"]
                    and cache["reference"][ph]["elf"] == values[key]["elf"],
                    "different genuine independent native target",
                )
        records[family] = (obj, index, cache)
    need(records["Stock4"][0] == records["C3b"][0], "two allegedly equal prior ELFs differ")
    out = {}
    for donor, dest in (("C3b", "Stock4"), ("Stock4", "C3b")):
        tag = donor + "-to-" + dest
        where = PREFIX + tag + "/"
        obj, foreign, src = records[donor]
        target = records[dest][2]
        original = gzip.decompress(z.read(where + "before.bin.gz"))
        expected_index, proof = migrate_index.swap(
            original, target["version"], obj, foreign, src["version"], src["slot"]
        )
        actual = read(z, where + "physical-index-change.json")
        need(
            expected_index == gzip.decompress(z.read(where + "after.bin.gz"))
            and z.read(where + "original-inode.o") == obj
            and proof == read(z, where + "challenge.json")
            and actual["before"][0] == proof["destination_index_sha256"]
            and actual["after"][0] == proof["changed_index_sha256"]
            and actual["before"][-2:] == actual["after"][-2:]
            and actual["before"][1:3] != actual["after"][1:3],
            "another input changed or genuine foreign seal was lost",
        )
        results = term["true_directions"][tag]
        need(set(results) == {"old", "new"}, "incomplete migration site")
        for phase in ("old", "new"):
            phase_dir = where + phase
            trace = [
                i.filename
                for i in files
                if re.fullmatch(re.escape(phase_dir) + r"/trace/exec\.\d+", i.filename)
            ]
            projection = results[phase]
            with patch.object(real.tracking, "EXTRA", (*real.tracking.EXTRA, "link", "linkat")):
                hits, emits = real.selection_read(z, phase_dir, trace, role["sdk"])
            roster = lambda rows: sorted(v["cgu"] for v in rows if v["owner"] == "ruff_workspace")
            h, e = roster(hits), roster(emits)
            need(
                projection["hits"] == h
                and projection["emitted"] == e
                and projection["selection"] == real.whole(z, phase_dir + "/source-selection.json"),
                "physical codegen projection differs from original rustc syscalls",
            )
            actual_obj = migration.durable.member_map(
                gzip.decompress(z.read("physical/owner-archives/" + projection["archive"] + ".gz"))
            )
            native = target["reference"][phase]
            need(
                len(actual_obj["objects"]) == 125
                and actual_obj["objects"] == native["archive"]["objects"]
                and projection["archive"] in signed["owner-archives"]
                and native["elf"] == projection["reader"]
                and projection["reader"] in signed["native-bodies"],
                "wrong or unpreserved debuginfo/code/reader verdict",
            )
            if phase == "old":
                need(not h, "a purportedly clean seeded history reused an object")
            else:
                need(
                    set(h) == set(expected["hit"]["new"]) - {chosen}
                    and chosen in e
                    and not (set(h) & set(e))
                    and len(set(h) | set(e)) == 21
                    and projection["real_roster"]
                    == {"rustc": [["full", "ruff_workspace", 1]], "linkers": []},
                    "known incompatible hit or unrelated change in the physical owner",
                )
                certificate = read(z, where + "kernel-read.json")
                need(certificate["original"] == actual["path"], "different physical index")
                kernel = read(z, phase_dir + "/kernel.json")
                owners = migration.rustc_traces(trace, kernel, role["sdk"])
                with ExitStack() as streams:
                    observed = migrate_index.kernel_read(
                        [(Path(n).name, streams.enter_context(z.open(n))) for n in owners],
                        actual["path"],
                    )
                need(
                    observed == certificate["path_to_successful_open"],
                    "missing original file/open lineage",
                )
                out[tag] = {
                    "dirty": len(set(h) | set(e)),
                    "remaining_hits": len(h),
                    "ordinary": e,
                    "native_objects": len(actual_obj["objects"]),
                    "reader": projection["reader"],
                    "prior_and_foreign_seals": True,
                    "kernel_open": observed,
                    "prefix_sha256": proof["legacy_prefix_sha256"],
                }
    return {
        "schema": "independent-stock-genuine-migration-1",
        "verified": True,
        "victim": chosen,
        "source": term["source"],
        "run": run,
        "qa": head,
        "boot": term["boot"],
        "counter_samples": 0,
        "results": out,
        "terminal_sha256": real.whole(z, PREFIX + "complete.json"),
    }


def main(dest):
    study = scope.bind()
    run = int(os.environ["GITHUB_RUN_ID"])
    head = os.environ["GITHUB_SHA"]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as path:
        d = Path(path)
        row = artifacts.receive(run, head, "migration", 1, "raw", d / "migration.zip", 3 << 30)
        sources = migration.donor_sources(d, study)
        with zipfile.ZipFile(d / "migration.zip") as z:
            result = scan(z, sources, study, run, head)
    result["raw"] = row
    scope.base.save(dest, result)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
