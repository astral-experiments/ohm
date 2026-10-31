"""Unscored checks of the measured command, native thread closure and rejection rules."""

import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study


def reject(fn):
    try:
        fn()
    except AssertionError:
        return
    raise RuntimeError("expected the deliberately broken record to fail")


def original():
    assert (
        study.kit.sha(HERE / "local-kernel.tgz")
        == "ace8862abe0fa6a0ad4c8984815f9acbc2121a3e8894cbb6a8271ef3ce0948ac"
    )
    with tarfile.open(HERE / "local-kernel.tgz") as t:
        for p in ("old", "edit", "repeat", "empty"):
            raw = gzip.decompress(t.extractfile("lib/" + p + "/stdout.gz").read())
            study.verify_artifact_inventory(raw, p)
            wrong_phase = "repeat" if p != "repeat" else "edit"
            reject(lambda: study.verify_artifact_inventory(raw, wrong_phase))
        assert json.load(t.extractfile("lib/old/invocation.json"))["argv"] == study.CLI
        names = [
            l.split("\t")[4]
            for l in t.extractfile("lib/kernel/events.tsv").read().decode().splitlines()
            if l.startswith("name\t")
        ]
        assert (
            len(names) == 55
            and sum(n.startswith("opt ") for n in names) == 6
            and sum(n.startswith("cpy ") for n in names) == 36
        )


def kernel(root):
    bins = root / "bin"
    bins.mkdir()
    for name, extra in [("workers", ["-I", str(study.COMMON)]), ("calibrator", ["-pthread"])]:
        subprocess.run(
            [
                "cc",
                "-O2",
                "-std=gnu11",
                "-Wall",
                "-Wextra",
                "-Werror",
                *extra,
                HERE / (name + ".c"),
                "-o",
                bins / name,
            ],
            check=True,
        )
    trace = root / "no-pmu"
    trace.mkdir()
    cmd = [
        bins / "workers",
        trace,
        "topology",
        bins / "calibrator",
        "calibration",
        bins / "calibrator",
        "--crate-name",
        "calibration",
        "--out-dir",
        root,
        43,
        "fixture",
    ]
    p = study.run(root / "run", cmd, root)
    assert p.returncode == 0, p.stderr
    real = study.readback.observed(trace, False)
    assert set(real["names"].values()) == {
        "calibrator",
        "opt abcdefghijk",
        "opt 123456789ab",
        "cpy zyxwvutsrqp",
        "outside",
    }
    assert all(v == 0 for v in real["tasks"].values())
    # The rows below are constructed, only to test the algebraic admissions.
    synthetic = root / "synthetic"
    synthetic.mkdir()
    factors = {
        "calibrator": 0,
        "opt abcdefghijk": 1,
        "opt 123456789ab": 2,
        "cpy zyxwvutsrqp": 3,
        "outside": 5,
    }
    for i, n in enumerate((0, 4_000_000, 0, 12_000_000)):
        dest = synthetic / str(i)
        shutil.copytree(trace, dest)
        tasks = {tid: (40000 + 2 * n * factors[name]) for tid, name in real["names"].items()}
        lines = [("task", tid, count) for tid, count in tasks.items()]
        total = sum(tasks.values())
        lines.extend([("compiler", real["leader"], total), ("command", real["leader"], total + 3000)])
        (dest / "samples.tsv").write_text(
            "".join(f"{kind}\t{tid}\t1\t{count}\t9\t9\n" for kind, tid, count in lines)
        )
    result = study.readback.worker_calibration(synthetic)
    assert result["distinct_workers"] == 4 and result["two_doses"]
    last = synthetic / "3" / "samples.tsv"
    ok = last.read_text()
    last.write_text(ok.replace("\t9\t9\n", "\t10\t9\n", 1))
    reject(lambda: study.readback.worker_calibration(synthetic))
    last.write_text(ok)
    # Swapping the two opt workers preserves all totals and breaks both slopes.
    raw = synthetic / "3" / "events.tsv"
    raw.write_text(
        raw.read_text()
        .replace("opt abcdefghijk", "placeholder")
        .replace("opt 123456789ab", "opt abcdefghijk")
        .replace("placeholder", "opt 123456789ab")
    )
    reject(lambda: study.readback.worker_calibration(synthetic))


if __name__ == "__main__":
    original()
    with tempfile.TemporaryDirectory() as tmp:
        kernel(Path(tmp))
    print(
        "55 original renderer TIDs; 5 real fixture TIDs; synthetic slope/PMU mutations rejected; no hardware measurements"
    )
