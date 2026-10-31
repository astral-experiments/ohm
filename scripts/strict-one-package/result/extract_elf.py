"""Extract one genuine counted check's neutral Unicode build script and exact corresponding compiler/linker arguments."""

import argparse, gzip, json, os, sys
from pathlib import Path

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import reopen as r


def details(raw, meta, row, arm):
    blobs = r.open_archive(raw, meta, row)
    p = "opt" + arm + "/empty-edited"
    j = lambda n: r.h.read(blobs[n])
    a = j(p + "/neutral-generator.json")
    body = gzip.decompress(blobs["retained-ELF/" + a["sha256"] + ".gz"])
    assert r.h.sha(body) == a["sha256"] and body[:4] == b"\x7fELF"
    real = j(p + "/all-physical.json")
    q = j(p + "/visit.json")
    assert real["generators"] == [[real["generators"][0][0], a["path"]]]
    chosen = {}
    for l in blobs[p + "/kernel/exec.tsv"].decode().splitlines():
        n, pid, dev, ino, selected, path = l.split("\t")
        argv = [os.fsdecode(b) for b in blobs[p + "/kernel/args-" + n.zfill(4)][:-1].split(b"\0")]
        kind = None
        if (
            "--crate-name" in argv
            and "--out-dir" in argv
            and (
                "crates/ruff_unicode_names2_generator/src/lib.rs" in argv
                or "crates/ruff_unicode_names2/build.rs" in argv
            )
        ):
            kind = (
                "generator_library_rustc"
                if "crates/ruff_unicode_names2_generator/src/lib.rs" in argv
                else "build_script_rustc"
            )
        if Path(path).name == "ld.bfd" and "-o" in argv and argv[argv.index("-o") + 1] == a["path"]:
            kind = "physical_Wild"
        if path == a["path"] and int(pid) == real["generators"][0][0]:
            kind = "physical_generator"
        if kind:
            assert kind not in chosen
            chosen[kind] = {
                "pid": int(pid),
                "image": path,
                "kernel_dev_ino": [int(dev), int(ino)],
                "argv": argv,
            }
    assert set(chosen) == {
        "generator_library_rustc",
        "build_script_rustc",
        "physical_Wild",
        "physical_generator",
    }
    return body, {
        "source": r.h.SOURCES,
        "cargo": r.h.CARGO,
        "row": row,
        "arm": arm,
        "artifact": meta["id"],
        "archive_sha256": meta["digest"],
        "neutral": a,
        "expected_outputs": q["generated"],
        "actual_kernel": chosen,
        "control": "empty edited source; same full generator SHA as untraced original, edited and first unchanged",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("metadata", type=Path)
    p.add_argument("row", choices=sorted(r.REG))
    p.add_argument("arm", choices=["0", "1"])
    p.add_argument("new_directory", type=Path)
    args = p.parse_args()
    data, receipt = details(
        args.archive.read_bytes(), r.h.read(args.metadata.read_bytes()), args.row, args.arm
    )
    args.new_directory.mkdir()
    binary = args.new_directory / "build_script_build"
    binary.write_bytes(data)
    binary.chmod(0o755)
    (args.new_directory / "actual.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    print(receipt["neutral"]["sha256"])
