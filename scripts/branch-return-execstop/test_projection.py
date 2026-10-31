"""Small synthetic executable assemblies for Ruff-specific classification and ancestry."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import images
from history import need


def setup():
    paths = {"cargo": "/sdk/bin/cargo", "rustc": "/sdk/bin/rustc", "wild": "/sdk/wild/ld.bfd",
             "proxy": "/proxy/rustup", "sysld": "/usr/bin/ld"}
    catalog = {r: {"path": path, "resolved": path if r != "sysld" else "/usr/bin/x86_64-linux-gnu-ld.bfd",
                   "identity": [str(i)*64, 100, i, 0o755, 1024, 10**9, 2*10**9]}
               for i, (r, path) in enumerate(paths.items(), 1)}
    data = []
    lines = ["R\t1\t1000\n"]
    def event(parent, role, argv):
        seq = len(data) + 1
        pid = 999 + seq
        if parent:
            lines.append(f"N\t{parent}\t{999+parent}\t1\t{seq}\t{pid}\n")
        lines.append(f"E\t{seq}\t{seq}\t{pid}\t{pid}\t0\t0\t0\t0\t0\n")
        sha, dev, ino, _, size, _, _ = catalog[role]["identity"]
        path = paths[role]
        data.append({"ordinal": seq, "lifetime": seq, "pid": pid, "former_tid": pid,
                     "image": {"id": ino, "dev": dev, "ino": ino, "size": size, "mode": 0o100755,
                               "sha256": sha, "mtime": "1.000000000", "ctime": "2.000000000"},
                     "exe": path if role != "sysld" else "/usr/bin/x86_64-linux-gnu-ld.bfd",
                     "execfn": path, "cwd": "/repo", "argv": [path, *argv]})
        return seq
    cargo = event(None, "cargo", ["build"])
    rustc = event(cargo, "rustc", ["--crate-name", "ruff", "--crate-type", "bin", "--emit=link", "-Zohm-check-relink-inputs"])
    event(rustc, "wild", ["-o", "/out/ruff"])
    event(cargo, "sysld", ["-o", "/private/conftest"])
    crates = [["ruff", "full", ["bin"], ["link"]]]
    for index, owner in enumerate(("fs-err", "memoffset", "num-traits"), 1):
        for n in range(2 if owner == "num-traits" else 1):
            event(cargo, "rustc", ["--crate-name", f"autocfg_{index:016x}_{n}", "--crate-type=lib", "--emit=llvm-ir",
                  "--out-dir", f"/sdk-private/build/{owner}/0011223344556677/out", "-"])
            crates.append([f"autocfg/{owner}/{n}", "full", ["lib"], ["llvm-ir"]])
    expected = {"native": {"rustc": sorted(crates, key=lambda row: json.dumps(row, separators=(",", ":"))),
                     "real_cargo": 1, "wild_queries": 0, "system_links": {"configure C executable": 1},
                     "wild_outputs": ["ruff"]}}
    return data, lines, catalog, expected


def suite():
    baseline, rows, catalog, expected = setup()
    def project(d, text, directory):
        from processes import other_link
        p = directory / "fixture.tsv"
        p.write_text("".join(text))
        return images.inventory(p, {"execs": d, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
                                catalog, expected, other_link)
    failures = {}
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        got = project(baseline, rows, directory)
        need(got["wild_processes"][0]["rustc_crate"] == "ruff", "expected installed compiler ancestry")
        for case in ("foreign-rustc-inode", "wrong-wild-sha", "changed-cold-compiler", "foreign-gnu-link",
                     "unexpected-Wild-output", "broken-wild-ancestry", "wrong-autocfg-owner", "wrong-autocfg-name",
                     "missing-gnu-link", "retention-activated", "interrupted-required-image", "wrong-resolved-ld"):
            events = copy.deepcopy(baseline)
            lines = rows.copy()
            if case == "foreign-rustc-inode": events[1]["image"]["ino"] = 345
            elif case == "wrong-wild-sha": events[2]["image"]["sha256"] = "a"*64
            elif case == "changed-cold-compiler": events[1]["argv"][2] = "other"
            elif case == "foreign-gnu-link": events[3]["image"]["dev"] = 99
            elif case == "unexpected-Wild-output": events[2]["argv"][-1] = "/out/other"
            elif case == "broken-wild-ancestry":
                n = next(i for i, s in enumerate(lines) if s.startswith("N\t2\t1001\t1\t3\t"))
                lines[n] = lines[n].replace("N\t2\t1001", "N\t1\t1000")
            elif case == "wrong-autocfg-owner": events[-1]["argv"][-2] = "/foo/other/id/out"
            elif case == "wrong-autocfg-name": events[-1]["argv"][2] = "autocfg_bad_0"
            elif case == "missing-gnu-link": events.pop(3)
            elif case == "retention-activated": events[1]["argv"].append("-Zohm-branch-cache=yes")
            elif case == "interrupted-required-image": lines.append("L\t3\t1002\t3\n")
            elif case == "wrong-resolved-ld": events[3]["exe"] = "/tmp/bin/ld"
            try:
                project(events, lines, directory)
            except ValueError as err:
                failures[case] = str(err)
            else:
                raise AssertionError((case, "qualified corrupt projection"))
    return {"positive": "synthetic native-role projection", "refusals": failures}


if __name__ == "__main__":
    # The historical GNU-ld argument checker uses no local paths. Its module also
    # contains hosted SDK functions whose constants are initialized at import.
    os.environ.setdefault("RUNNER_TEMP", "/unused-ruff-projection-fixture")
    sys.path.insert(0, str(HERE.parent / "branch-return-pmu"))
    print(json.dumps(suite(), sort_keys=True))
