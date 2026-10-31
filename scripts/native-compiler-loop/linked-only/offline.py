"""Exercise the prospective observer on sealed real positive and rejected native inputs, without Cargo."""

from hashlib import sha256
from pathlib import Path
import gzip
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure_link as trial


def archive(base):
    meta = json.loads(base.with_suffix(".json").read_bytes())
    data = base.with_suffix(".zip").read_bytes()
    digest = sha256(data).hexdigest()
    assert meta["digest"] == "sha256:" + digest and len(data) == meta["size_in_bytes"]
    with zipfile.ZipFile(io.BytesIO(data)) as zipf:
        assert not zipf.testzip()
        (name,) = zipf.namelist()
        return tarfile.open(fileobj=io.BytesIO(zipf.read(name))), digest


def bytes_at(files, member):
    return files.extractfile("./" + member).read()


def read(files, member):
    return json.loads(bytes_at(files, member))


def positive(files):
    fresh, warm = [], []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for rank in range(2):
            prefix = "ordinary-lib/opt" + str(rank)
            target = base / prefix
            for visit in (
                "cold",
                "neutral-unchanged",
                "historical-hunk",
                "first-unchanged",
                "traced-repeat",
                "independent-empty",
            ):
                p = target / visit
                p.mkdir(parents=True)
                (p / "build.json").write_bytes(
                    bytes_at(files, prefix + "/" + visit + "/build.json")
                )
                if visit not in ("traced-repeat", "independent-empty"):
                    (p / "whole.json").write_bytes(
                        bytes_at(files, prefix + "/" + visit + "/whole.json")
                    )
                    continue
                loc = prefix + "/" + visit
                results = read(files, loc + "/build.json")
                pids = {pid for pid, _ in results["physical_rustcs"]}
                chosen = []
                for row in (
                    bytes_at(files, loc + "/kernel/exec.tsv").decode().splitlines()
                ):
                    n, pid, _, _, _, image = row.split("\t")
                    if int(pid) not in pids or Path(image).name != "rustc":
                        continue
                    data = bytes_at(files, loc + "/kernel/args-" + n.zfill(4))[
                        :-1
                    ].split(b"\0")
                    args = list(map(os.fsdecode, data))
                    if (
                        "--out-dir" not in args
                        or "--crate-name" not in args
                        or any(v.startswith("--print") for v in args)
                    ):
                        continue
                    line = (
                        "execve("
                        + json.dumps(image)
                        + ", "
                        + json.dumps(args)
                        + ', ["LC_ALL=C"]) = 0'
                    ).encode()
                    assert trial.compilation_argv(line) == args
                    chosen.append({"pid": int(pid), "argv": args})
                assert len(chosen) == len(pids)
                if visit == "traced-repeat":
                    assert not trial.stage_roster(chosen, "build-repeat")
                    warm.append(len(chosen))
                else:
                    rows = trial.stage_roster(chosen, "build-cold")
                    assert len(rows) == 1
                    fresh.append(len(chosen))
            assert len(trial.reader_gate(target)) == 6
        original = trial.O
        trial.O = base
        try:
            assert len(trial.decision()["complete_whole_Cargo"]) == 5
        finally:
            trial.O = original
    return {"genuine_cold": fresh, "genuine_repeat": warm, "reader_visits": 12}


def rejected(files):
    original_lines = 0
    for which in ("P", "C"):
        loc = "opt" + which + "1/actual-cargo-driver/"
        raw = gzip.decompress(
            bytes_at(files, loc + "all-process-opens.gz")
        ).splitlines()
        permitted = trial.inspect(
            raw,
            lambda x: x.name == "rustc" and x.parent.name == "bin",
            lambda x: x.parent.name == "lib" and x.name.startswith("librustc_driver"),
        )
        got = []
        for line in raw:
            pid, proc = line.rstrip().split(b" ", 1)
            match = re.match(rb'^execve\("([^"]+)",', proc)
            if (
                match
                and proc.endswith(b"= 0")
                and Path(os.fsdecode(match[1])).name == "rustc"
            ):
                a = trial.compilation_argv(proc)
                if a:
                    got.append([int(pid), a[a.index("--crate-name") + 1]])
        assert sorted(got) == [[n, crate] for n, crate, _ in permitted]
        assert sorted(x[1] for x in got) == [
            "build_script_build",
            "ron",
            "unicode_names2",
        ]
        original_lines += len(got)
    failed = False
    try:
        trial.stage_roster(
            [{"pid": 1, "argv": ["--crate-name", "unicode_names2"]}] * 2, "build-repeat"
        )
    except AssertionError:
        failed = True
    assert failed
    return {
        "actual_regular_strace_full_argv": original_lines,
        "two_compiler_repeat_rejected": True,
    }


if __name__ == "__main__":
    signed, staged, markers = map(Path, sys.argv[1:])
    observations = json.loads(markers.read_bytes())
    assert (
        sha256(markers.read_bytes()).hexdigest()
        == "645274c47a85ec6a2b8276e36c5c75aca1e3c5547392c2e4d94f2ed29047ac66"
    )
    for name, item in observations.items():
        trial.marker_check(
            {k: {"bytes": v} for k, v in item["markers"].items()},
            name in ("scratch-missing", "scratch-missing-again"),
        )
    records = {"local_signed_minus18_marker_legs": len(observations)}
    for row in ("01", "02"):
        old, sh = archive(signed / ("one-package-" + row))
        red, rh = archive(staged / ("actual-compiler-loop-" + row))
        with old, red:
            records[row] = {
                "signed": sh,
                "staged": rh,
                "signed_inputs": positive(old),
                "real_staged_inputs": rejected(red),
            }
    print(json.dumps(records, indent=2, sort_keys=True))
