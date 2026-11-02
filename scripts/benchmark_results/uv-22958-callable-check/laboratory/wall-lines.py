"""Audit the original timed-wait Cargo clock with the actual signed Cargo Finished lines."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from fractions import Fraction
from statistics import median
from zipfile import ZipFile

PREFIX = "    Finished `dev` profile [unoptimized + debuginfo] target(s) in "
ROLES = ["fa7a_stack_ctfe318_handwritten", "fa7a_stack_ctfe318_handwritten_coroutine_callables"]
SHA = lambda raw: hashlib.sha256(raw).hexdigest()

def line(data):
    finished, = [v for v in data.decode("utf-8").splitlines() if v.startswith(PREFIX)]
    f = finished.removeprefix(PREFIX)
    if m := re.fullmatch(r"(0|[1-9]\d*)\.(\d{2})s", f):
        assert int(m[1]) < 60
        lower, width = int(m[1])*1_000_000_000 + int(m[2])*10_000_000, 10_000_000
    else:
        m = re.fullmatch(r"([1-9]\d*)m ([0-5]\d)s", f)
        assert m, f
        lower, width = (int(m[1])*60 + int(m[2]))*1_000_000_000, 1_000_000_000
    return finished, (lower, lower + width)

def audit(z, subdir):
    stderr = z.read(subdir+"cargo.stderr")
    raw = z.read(subdir+"ordinary.json")
    clock = json.loads(raw)
    assert clock["mode"] == "native" and clock["exit"] == 0 and clock["invoked"] == clock["argv"]
    assert clock["argv"][1:] == ["check", "-p", "uv-client", "--locked", "--offline", "-j8"]
    outer = clock["end_ns"] - clock["start_ns"]
    assert clock["ns"] == outer > 0
    finished, (low, high) = line(stderr)
    return {"raw_finished":finished, "cargo_internal_ns_interval_left_closed": [low,high],
            "outward_clock_ns":outer, "outward_minus_internal_ns_interval_right_closed":[outer-high,outer-low],
            "raw_stderr_sha256":SHA(stderr),"original_clock_sha256":SHA(raw),"members":subdir}

def run(archive):
    with ZipFile(archive) as z:
        scores=json.loads(z.read("native-22958/score.json"))
        assert scores["complete"] and scores["boot"] == "13895848-ed2e-435a-b313-9e006b9ff3e2" and scores["independent_histories"] == 12
        pairs=[]
        for i in range(1,7):
            rows=[audit(z, f"native-22958/{i}-{r}/wall/") for r in ROLES]
            assert [v["outward_clock_ns"] for v in rows] == scores["metrics"]["wall"]["control_and_treatment"][i-1]
            a,b=[v["cargo_internal_ns_interval_left_closed"] for v in rows]
            ratios=[float(Fraction(b[0],a[1])),float(Fraction(b[1],a[0]))]
            pairs.append({"pair":i,"roles":dict(zip(ROLES,rows)),"internal_candidate_over_mature_display_bounds":ratios})
        return {"pairs":pairs, "external_registered_wall_ratio":scores["metrics"]["wall"]["paired_median"],
            "cargo_display_median_ratio_bounds":[median(p["internal_candidate_over_mature_display_bounds"][i] for p in pairs)for i in range(2)],
            "scope":"Signed Cargo truncates its internal JobQueue clock to 10ms for subminute calls, using its context-initialization Instant and sampling before final reporting. The outer clock includes launch, shutdown and the Python wait. The difference cannot isolate polling overhead on any individual visit. Keep both endpoints separate."}

def control(previous):
    with ZipFile(previous)as z:
        path="uv-client/pair-0-callables_ctfe318/wall/"
        actual=audit(z,path);raw=z.read(path+"cargo.stderr")
        for bad in (b"",raw+b"\n"+raw,raw.replace(b"] target(s) in ",b"] target(s) xx ")):
            try:line(bad)
            except (AssertionError,ValueError):continue
            raise ValueError("accepted malformed signed Cargo Finished output")
        assert line((PREFIX+"1m 08s\n").encode())[1] == (68_000_000_000,69_000_000_000)
        return dict(genuine_old_pair=actual["members"],genuine_raw_stderr_sha=actual["raw_stderr_sha256"],negative=3)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("archive",type=Path);parser.add_argument("--control",action="store_true");args=parser.parse_args()
    print(json.dumps((control if args.control else run)(args.archive),sort_keys=True,indent=2))
