"""Read original Cargo streams, CLI verdicts and monotonic timestamps from the confirmation zip."""
import argparse
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(path):
    receipt = json.loads(Path(__file__).with_name("results.json").read_text())
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == receipt["reference_artifacts"]["confirmation"][1]

    with zipfile.ZipFile(path) as z:
        assert len(z.namelist()) == len(set(z.namelist())) and z.testzip() is None

        def read(name):
            return json.loads(z.read(name))

        def unpack(name):
            return gzip.decompress(z.read(name))

        root = "objc2-clock-confirmation/"
        registration = read(root + "registration.json")
        order = registration["order"]
        balanced = list(itertools.combinations(range(12), 6))
        assigned = balanced[registration["assignment"]]
        assert order == ["PC" if i in assigned else "CP" for i in range(12)]
        assert registration["primary"] == "repeat-1"
        refs = {}
        for role in "PC":
            for state in ("old", "new"):
                path = f"objc2-cli/PC/{role}/clean-{state}/clean/"
                prod = read(path + "verified.json")["product"]
                assert sha(unpack("objc2-cli-programs/" + prod["raw"] + ".gz")) == prod["raw"]
                refs[role, state] = prod, unpack(path + "ty-stdout.gz")
            assert refs[role, "old"][1] == b"All checks passed!\n"
            assert refs[role, "new"][1].endswith(b"Found 2 diagnostics\n")

        endpoints = {name: [] for name in ("edit", "repeat-1", "repeat-2", "edit+repeat-1")}
        previous = -1
        for block, roles in enumerate(order, 1):
            both = {}
            for role in roles:
                times = {}
                for step in ("cold", "edit", "repeat-1", "repeat-2"):
                    folder = root + f"pair-{block:02}/{role}/{step}/"
                    row = read(folder + "result.json")
                    t = row["cargo"]
                    stdout = unpack(folder + "stdout.gz")
                    assert sha(stdout) == t["streams"]["stdout"]
                    assert sha(unpack(folder + "stderr.gz")) == t["streams"]["stderr"]
                    messages = list(map(json.loads, stdout.splitlines()))
                    assert messages[-1] == {"reason": "build-finished", "success": True}
                    assert sum(m["reason"] == "compiler-artifact" for m in messages) == (353 if step == "cold" else 354)
                    expected, answer = refs[role, "old" if step == "cold" else "new"]
                    assert row["product"] == row["expected"] == expected
                    assert unpack(folder + "ty-stdout.gz") == answer and not unpack(folder + "ty-stderr.gz")
                    assert read(folder + "ty-exit.json") == expected["exit"]
                    if step != "cold":
                        assert t["stop_ns"] > t["start_ns"] > previous
                        times[step] = t["stop_ns"] - t["start_ns"]
                        assert times[step] == t["ns"]
                        previous = t["stop_ns"]
                times["edit+repeat-1"] = times["edit"] + times["repeat-1"]
                both[role] = times
            for name, pairs in endpoints.items():
                pairs.append([both["P"][name], both["C"][name]])

        for name, pairs in endpoints.items():
            ratios = [p / c for p, c in pairs]
            logs = [math.log(r / 2) for r in ratios]
            signs = [v if direction == "PC" else -v for v, direction in zip(logs, order)]
            observed = sum(logs) / len(logs)
            p = sum(
                sum(v if i in assigned else -v for i, v in enumerate(signs)) / 12 >= observed - 1e-12
                for assigned in balanced
            ) / len(balanced)
            expected = receipt["confirmation"]["scores"][name]
            assert expected["pairs"] == pairs and expected["paired"] == statistics.median(ratios)
            assert expected["ci"] == [sorted(ratios)[2], sorted(ratios)[9]] and expected["p"] == p
            print(f"{name:14} {statistics.median(ratios):.3f}x  interval {expected['ci'][0]:.3f}–{expected['ci'][1]:.3f}  p={p:.6f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    verify(p.parse_args().archive)
