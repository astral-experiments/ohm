"""Recount the portable reviewer's instruction profiles and match their real process and output receipts."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import runpy
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import replay


sys.path.insert(0, str(ROOT / "replay/ohm-aarch64-linux"))
import qualify as q

recount = runpy.run_path(str(ROOT / "replay/ohm-aarch64-registers/raw_counter.py"))["recount"]
native_roster = runpy.run_path(str(ROOT / "replay/ohm-aarch64-confirm/complete-native-roster.py"))["inspect"]


def sha(body):
    return hashlib.sha256(body).hexdigest()


def verify(read, names):
    def j(path):
        return json.loads(read(path))

    def profiles(directory, expected, target_jobserver):
        result = j(directory + "/observed.json")
        registered = result["processes"]
        assert set(registered) == set(expected)
        pids = {str(record["pid"]) for record in registered.values()}
        assert len(pids) == len(expected)
        prefix = directory + "/profiles/"
        assert {p[len(prefix):] for p in names if p.startswith(prefix) and p.endswith(".gz")} == {"cg." + p + ".gz" for p in pids}
        assert {p[len(prefix):] for p in names if p.startswith(prefix + "log.") and read(p)} == {"log." + p for p in pids}
        jobserver = j(directory + "/command/physical-jobserver.json") if target_jobserver else {}
        if target_jobserver:
            assert set(jobserver) == set(expected) - {"cargo"}
        counts = {}
        for name, row in registered.items():
            assert row["argv"] == expected[name]
            pid = row["pid"]
            body = gzip.decompress(read(prefix + f"cg.{pid}.gz"))
            log = read(prefix + f"log.{pid}")
            assert (sha(body), sha(log)) == (row["profile"], row["log"])
            counts[name] = recount(body, log, pid, row["argv"])
            assert counts[name] == row["Ir"] > 0
            if name in jobserver:
                evidence = jobserver[name]
                assert pid == evidence["pid"] and re.fullmatch(r"pipe:\[\d+\]", evidence["pipe"])
                flags = re.search(r"--jobserver-(?:auth|fds)=(\d+),(\d+)", evidence["jobserver"])
                assert flags and list(map(int, flags.groups())) == evidence["descriptor_numbers"]
                assert len(set(evidence["descriptor_numbers"])) == 2
        assert sum(counts.values()) == result["Ir"]
        return counts

    terminal = j("review-counter.json")
    assert terminal["independent_reviewer"] and terminal["formal_observations"] == 0
    native = j("reviewed-native.json")
    assert (terminal["role"], terminal["source"], terminal["native"]) == (native["role"], native["source"], sha(read("reviewed-native.json")))
    role = "M" if native["role"] == "V" else native["role"]
    sdk = j("reviewer-physical-kit.json")
    assert sha(read("reviewer-physical-kit.json")) == terminal["physical_kit"]
    table = json.loads((ROOT / "source/sdk-members.json").read_bytes())
    assert {n: v[-3:] for n, v in sdk.items()} == table["common"] | {table["driver_path"]: table["roles"][role]["driver"]}
    assert all(len(v) == 7 and all(isinstance(n, int) and n > 0 for n in v[:4]) for v in sdk.values())
    calibration = j("counter-calibrated.json")
    assert sha(read("counter-calibrated.json")) == terminal["calibration"]
    assert calibration["valgrind"] == "def5fdcf6ae64a4d3e6af3786b622978d8313e0734ecf3f6cbe71d8be9e274c8"
    assert sha((ROOT / "replay/ohm-aarch64-registers/calibrate.c").read_bytes()) == calibration["source"]
    assert set(calibration["subjects"]) == {"ordinary", "no-child", "parent-thread", "child-only", "repeat"}
    for case, recorded in calibration["subjects"].items():
        prefix = "cal-" + case
        observed = j(prefix + "/observed.json")["processes"]
        assert set(observed) == ({"parent"} if case == "no-child" else {"parent", "child"})
        assert profiles(prefix, {n: p["argv"] for n, p in observed.items()}, False) == recorded
    modes = calibration["subjects"]
    for case, subject in (("child-only", "child"), ("parent-thread", "parent")):
        other = "parent" if subject == "child" else "child"
        assert modes[case][subject] - modes["ordinary"][subject] > 3_000_000
        assert abs(modes[case][other] / modes["ordinary"][other] - 1) < .01
    assert all(abs(modes["repeat"][k] / v - 1) < .01 for k, v in modes["ordinary"].items())

    prior = "review-history/"
    cycle = "review-history-edit-cycle/"
    seal = j(cycle + "complete.json")
    assert seal["source"] == role and sha(read(cycle + "complete.json")) == terminal["cycle"]
    refs = {mode: q.semantic(j(prior + phase + "/verified.json")) for mode, phase in (("old", "old-empty"), ("edited", "empty-edited"))}
    evidence = type("Evidence", (), {"read": staticmethod(read)})()
    for folder, state in ((prior + "count-settled-reference", "edited"), (cycle + "old-empty", "old"), (cycle + "post-settled", "edited")):
        row = j(folder + "/verified.json")
        assert q.semantic(row) == refs[state] and q.archive(read("objects/" + row["archive"]["raw"] + ".rlib")) == row["archive"]
        assert sha(read("objects/" + row["reader"] + ".elf")) == row["reader"]
        raw = j(folder + "/native.json")
        assert sha(read(folder + "/native.json")) == row["native"] and len(row["typed"]) == 39
        assert native_roster(evidence, folder, raw)["cargo"] == 1
        assert j(folder + "/qemu/command.json")["exit"] == 0
        assert gzip.decompress(read(folder + "/qemu/stdout.gz")).decode().strip() == row["value"]

    table = {}
    for name, ordinary in (("first-real-edit", "edit"), ("immediate-repeat", "unchanged-1"), ("settled", "count-settled-reference")):
        data = j(prior + ordinary + "/native.json")
        args = {"cargo": data["cargo"][0]["argv"]} | {r["crate"]: r["argv"] for r in data["rustcs"]}
        wanted = {"cargo"} | replay.ROLE_HARD[role]
        if name == "first-real-edit":
            wanted.add("ruff_python_ast")
        assert set(args) == wanted and not data["link_tools"] and not data["compiler_probes"]
        assert all(r["terminal"] == [0] and not r["link_only"] for r in data["rustcs"])
        if name == "settled":
            directory = prior + "counter"
            row = j(directory + "/verified.json")
            assert terminal["settled"] == sha(read(directory + "/verified.json"))
            assert {k: p["argv"] for k, p in j(directory + "/physical.json")["roster"].items()} == args
            profile_dir = directory + "/whole"
        else:
            directory = cycle + name
            row = j(directory + "/verified.json")
            assert sha(read(directory + "/verified.json")) == seal["records"][name]
            assert q.archive(read("objects/" + row["archive"]["raw"] + ".rlib")) == row["archive"]
            assert [[n, s, h] for n, _, s, h in row["archive"]["objects"]] == refs["edited"]["native"]
            assert row["prior_raw_native"] == sha(read(prior + ordinary + "/native.json"))
            assert row["typed"] == j(prior + ordinary + "/verified.json")["typed"]
            profile_dir = directory
        counts = profiles(profile_dir, args, True)
        assert counts == {k: v["Ir"] for k, v in row["processes"].items()}
        assert sum(counts.values()) == terminal["host_Cargo_and_all_rustc_Ir"][name]
        table[name] = counts
    return {"role": terminal["role"], "source": terminal["source"], "formal_observations": 0,
            "raw_terminal": sha(read("review-counter.json")), "native_terminal": terminal["native"],
            "calibration": terminal["calibration"], "genuine_jobserver": True,
            "host_Cargo_and_all_rustc_Ir": table}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.receipts.is_dir():
        names = {p.relative_to(args.receipts).as_posix() for p in args.receipts.rglob("*") if p.is_file()}
        result = verify(lambda name: (args.receipts / name).read_bytes(), names)
    else:
        with zipfile.ZipFile(args.receipts) as archive:
            assert archive.testzip() is None and len(archive.namelist()) == len(set(archive.namelist()))
            end, = [n for n in archive.namelist() if Path(n).name == "review-counter.json"]
            base = end.removesuffix("review-counter.json")
            names = {n[len(base):] for n in archive.namelist() if n.startswith(base) and not n.endswith("/")}
            result = verify(lambda name: archive.read(base + name), names)
    data = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    if args.output:
        with args.output.open("xb") as f:
            f.write(data)
    print(sha(data))


if __name__ == "__main__":
    main()
