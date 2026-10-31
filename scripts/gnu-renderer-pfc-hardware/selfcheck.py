"""Offline calibration and ordinary-arm reread. Optional paths point only at pre-existing original evidence."""

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibration
import evidence
import ingress
import mono

OLD = {
    "01": (
        "b4bcda371cab930395b9c8b281890f1343f0a406c364ae218baeee37cb9f2709",
        "0e17d46f-ba25-4ae2-9004-e6bd164431cd",
    ),
    "02": (
        "cf4be4be56ee33801694034692253e0122e19ceb3270875447c542294d094350",
        "e80c2b0d-f542-4bd5-8cd8-5c7fc6667dc1",
    ),
}


def rejects(f):
    try:
        f()
    except (ValueError, AssertionError):
        return
    raise AssertionError("a corrupted input passed")


def check_pipe():
    """Recreate the captured Cargo jobserver at unusual FDs and prove they survived a real exec."""
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        shim = folder / "fd-read"
        shim.write_text(
            "#!/usr/bin/python3\nimport os,sys\nassert sys.argv[1:] == ['+ohm','test-only']\n"
            "assert os.read(5, 3) == b'+++'\nos.write(7, b'x')\nassert os.read(5, 1) == b'x'\n"
        )
        shim.chmod(0o700)
        spec = {
            "cwd": str(folder),
            "environment": {"CARGO_MAKEFLAGS": "-j --jobserver-fds=5,7 --jobserver-auth=5,7"},
            "proxy": str(shim),
            "argv": ["/not-an-enrolled-compiler", "test-only"],
        }
        path = folder / "case.json"
        path.write_text(json.dumps(spec))
        subprocess.run([sys.executable, "-IB", mono.__file__, "child", path], check=True, timeout=10)


def main(a):
    check_pipe()
    results = {
        "passed": ["real non-Rust child reopened matching anonymous pipe FDs and all three -j4 tokens"]
    }
    r = ingress.registration()
    assert r["positions"] == ingress.POSITIONS
    if not r["source"] or r["source"]["artifacts"] is None:
        rejects(lambda: ingress.registration("qualify"))
    if r["root_acceptance"] is None:
        rejects(lambda: ingress.registration("screen"))
    assert not ingress.legal("../sneaky") and not ingress.legal("/absolute")
    good = {
        "start": 100,
        "stop": 180,
        "instructions": 5871,
        "user_us": 438,
        "system_us": 21,
        "enabled": 17,
        "running": 17,
        "event_errno": 0,
        "code": 0,
    }
    term = {"status": 0, "begin_mono_ns": 90, "end_mono_ns": 190}
    assert evidence.metered(good, term) == 5871
    for field, v in [
        ("code", 101),
        ("enabled", 19),
        ("instructions", 0),
        ("event_errno", 13),
        ("start", 89),
        ("stop", 191),
    ]:
        rejects(lambda: evidence.metered(good | {field: v}, term))
    assert mono.jobserver("-j --jobserver-fds=5,7 --jobserver-auth=5,7") == [5, 7]
    for v in [
        "-j --jobserver-fds=5,7 --jobserver-auth=5,8",
        "-j4",
        "-j --jobserver-fds=1,2 --jobserver-auth=1,2",
    ]:
        rejects(lambda: mono.jobserver(v))
    results["passed"] += [
        "unadmitted gates fail closed",
        "full-duty/exit/window mutations rejected",
        "raw Cargo jobserver pair validated",
    ]
    if a.archives:
        assert a.observers
        for pos, (expected, boot) in OLD.items():
            p = a.archives / (pos + ".zip")
            assert ingress.sha(p) == expected
            with tempfile.TemporaryDirectory(dir=a.scratch) as tmp:
                temp = Path(tmp)
                with zipfile.ZipFile(p) as z:
                    for n in z.namelist():
                        if n.split("/")[0] in {
                            "observers",
                            "host.json",
                            "calibration",
                            "calibration-commands",
                            "worker-calibration",
                            "worker-calibration.json",
                        }:
                            assert ingress.legal(n)
                            z.extract(n, temp)
                assert (
                    evidence.read(temp / "host.json")["raw_system"]["/proc/sys/kernel/random/boot_id"] == boot
                )
                calibration.replay(a.observers, temp)
                d = temp / "calibration/whole-1-1.json"
                raw = evidence.read(d)
                raw["running"] -= 1
                d.write_text(json.dumps(raw))
                rejects(lambda: calibration.replay(a.observers, temp))
            results["passed"].append(
                "native original "
                + pos
                + " 28 whole + 8 nested + 4 worker calibrations; real PMU mutation rejected"
            )
    if a.signed:
        observations = {}
        for h in ingress.STUDIES:
            d = a.signed / h
            run = evidence.read(d / "runtime.json")
            boot = run["boot"]
            result = evidence.cell(d, "signed-control", h, "structural", None, boot)
            rejects(lambda: evidence.cell(d, "P", h, "structural", None, boot))
            rejects(lambda: evidence.cell(d, "signed-control", h, "structural", None, "different"))
            assert (
                len(result["kernel_compilers"]["old"]) == 4
                and result["kernel_compilers"]["edit"] == ["annotate_snippets"]
                and result["kernel_compilers"]["repeat"] == []
            )
            assert all(
                result["storage"][f]["session_indices"] == 1 for f in ("old", "edit", "repeat", "empty")
            )
            observations[h] = {
                "terminal": result["semantic_complete"],
                "warm": result["storage"]["edit"],
                "empty": result["storage"]["empty"],
            }
        results["signed_dry_replay"] = observations
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("observers", "archives", "signed"):
        p.add_argument("--" + key, type=Path)
    p.add_argument("--scratch", type=Path, default=Path("/dev/shm"))
    main(p.parse_args())
