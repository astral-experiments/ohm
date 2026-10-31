"""Extract the real neutral host programs, codegen libraries and actual native argument vectors."""

import argparse
import gzip
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reopen as r


def extract(source, row, dest):
    stem = source / ("share-bridge-" + row)
    meta = r.J(stem.with_suffix(".json").read_bytes())
    blobs = r.open_archive(stem.with_suffix(".zip").read_bytes(), meta, row)
    tools = r.J(blobs["subjects.json"])["tools"]
    wrapper = r.J(blobs["bridge.json"])["wrapper"]
    for arm in r.CASES[row]:
        q = "opt" + arm + "/empty-edited"
        kept = set()
        program, library = r.source_images(blobs, q, kept)
        visits = [r.J(blobs["opt" + arm + "/" + n + "/neutral-generator.json"]) for n in r.SCORE]
        assert all(x["sha256"] == program["sha256"] for x in visits)
        reported = r.J(blobs[q + "/handoff.json"])
        ((generator_pid, generator_path),) = reported["actual_generator"]
        assert generator_path == program["path"]
        selected = {}
        for line in blobs[q + "/kernel/exec.tsv"].decode().splitlines():
            n, p, dev, ino, _, image = line.split("\t")
            p = int(p)
            ident = [int(dev), int(ino)]
            raw = blobs[q + "/kernel/args-" + n.zfill(4)]
            assert raw.endswith(b"\0")
            a = [os.fsdecode(v) for v in raw[:-1].split(b"\0")]
            role = None
            if ident in (tools["rustc"]["dev_ino"], wrapper["dev_ino"]) and "--out-dir" in a:
                prefix = "rustc_" if ident == tools["rustc"]["dev_ino"] else "wrapper_"
                if r.NAMED in a:
                    role = prefix + "generator_library"
                if "crates/ruff_unicode_names2/build.rs" in a:
                    role = prefix + "build_script"
            if (
                ident == tools["wild"]["dev_ino"]
                and "-o" in a
                and a[a.index("-o") + 1] == generator_path
            ):
                role = "physical_Wild"
            if p == generator_pid and image == generator_path:
                role = "physical_generator"
            if role:
                assert role not in selected
                selected[role] = {"pid": p, "image": image, "dev_ino": ident, "argv": a}
        assert set(selected) == {
            "wrapper_build_script",
            "wrapper_generator_library",
            "rustc_build_script",
            "rustc_generator_library",
            "physical_Wild",
            "physical_generator",
        }
        for suffix in ("build_script", "generator_library"):
            w, rust = selected["wrapper_" + suffix], selected["rustc_" + suffix]
            extra = [r.FLAG] if suffix == "generator_library" and arm == "Q" else []
            assert w["pid"] == rust["pid"] and rust["argv"][1:] == w["argv"][2:] + extra
        out = dest / ("neutral-" + row + "-" + arm)
        out.mkdir(parents=True)
        record = {
            "arm": arm,
            "row": row,
            "source": r.h.SOURCES,
            "cargo": r.h.CARGO,
            "artifact": meta,
            "neutral": program,
            "rlib": library,
            "generated": r.J(blobs[q + "/visit.json"])["generated"],
            "corroborating_kernel": selected,
        }
        exe = out / "build_script_build"
        exe.write_bytes(gzip.decompress(blobs["retained-ELF/" + program["sha256"] + ".gz"]))
        exe.chmod(0o755)
        (out / "generator.rlib").write_bytes(
            gzip.decompress(blobs["bridge-rlibs/" + library["sha256"] + ".gz"])
        )
        (out / "actual.json").write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        print(arm, program["sha256"], out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=Path)
    p.add_argument("row", choices=sorted(r.CASES))
    p.add_argument("extraction", type=Path)
    a = p.parse_args()
    extract(a.data, a.row, a.extraction)
