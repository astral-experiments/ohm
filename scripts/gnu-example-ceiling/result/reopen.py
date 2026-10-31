"""Replay every member of both original Actions ZIPs offline, without executing their binaries."""

import argparse
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import types
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import topology
import verify

RUN = 41175267642
HEAD = "5f3fcc6d826788835fd11eb668444d3b50236961"
H = lambda b: hashlib.sha256(b).hexdigest()
AMENDMENT = (
    "                    # The JSON writer sorts maps. Restore the observed kernel exec\n"
    "                    # order before comparing the original ordered per-example rows.\n"
    '                    v[n]["native"] = actual\n'
)


def unpack(temp, originals):
    cap = (HERE / "sources.tar.zst").read_bytes()
    assert H(cap) == "058716b88b220a32d746fef1c2cb831498fc4ec8ea7e974270858e004529dd68"
    raw = subprocess.check_output(["zstd", "-qdc"], input=cap)
    assert len(raw) < 8 * 1024**2
    official = verify.load(HERE / "official.json")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as t:
        members = t.getmembers()
        assert len(members) == len({m.name for m in members}) == 627 and all(
            m.isfile() for m in members
        )
        index = json.load(t.extractfile("files.json"))
        used = {h for files in index.values() for h in files.values()}
        assert set(index) == {"01", "02"} and set(t.getnames()) == used | {"files.json"}
        for h in used:
            assert re.fullmatch("[0-9a-f]{64}", h) and H(t.extractfile(h).read()) == h
        for pos, files in index.items():
            assert len(files) == official[pos]["members"] == 656
            for name, h in files.items():
                path = PurePosixPath(name)
                assert (
                    path.parts
                    and not path.is_absolute()
                    and ".." not in path.parts
                    and path.as_posix() == name
                )
                target = temp / pos / str(path)
                target.parent.mkdir(exist_ok=True, parents=True)
                with target.open("xb") as f:
                    f.write(t.extractfile(h).read())
            if originals:
                archive = originals / (official[pos]["name"] + ".zip")
                blob = archive.read_bytes()
                assert (
                    len(blob) == official[pos]["size_in_bytes"]
                    and "sha256:" + H(blob) == official[pos]["digest"]
                )
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    originals_utf8 = {
                        f.filename: H(z.read(f)) for f in z.infolist() if not f.is_dir()
                    }
                    assert len(originals_utf8) == len([f for f in z.infolist() if not f.is_dir()])
                    assert originals_utf8 == files
    return official


def expect_failure(call, original=False):
    try:
        call()
    except AssertionError as exc:
        if original:
            loc = exc.__traceback__
            while loc.tb_next is not None:
                loc = loc.tb_next
            assert loc.tb_frame.f_code.co_name == "host" and loc.tb_lineno == 89
        return
    raise ValueError("accepted deliberately inconsistent evidence")


def kernel_order(folder):
    events = [line.split("\t") for line in (folder / "exec.tsv").read_text().splitlines()]
    names = []
    for event in events:
        serial, _pid, kind, selected = map(int, event[:4])
        argv = (folder / f"args-{serial:04d}").read_bytes().decode().split("\0")
        if kind == selected == 1 and topology.option(argv, "--crate-type") == "bin":
            names.append(topology.option(argv, "--crate-name"))
    assert len(names) == len(set(names)) == 12
    return names


def original_verifier():
    path = HERE.parent / "verify.py"
    amended = path.read_text()
    assert amended.count(AMENDMENT) == 1
    old = amended.replace(AMENDMENT, "")
    assert H(old.encode()) == "6a967cd2e37a4f03f7d02b80a3e04d387c100a22fa8aed1d1ab000e8bd86c16e"
    module = types.ModuleType("original_verifier")
    module.__file__ = str(path)
    exec(compile(old, str(path), "exec"), module.__dict__)
    return module


def analyze(base, pos, original):
    root = base / pos
    e = verify.load(root / "enrollment.json")
    assert (e["run"], e["position"], e["attempt"], e["head"]) == (str(RUN), pos, "1", HEAD)
    assert (
        e["source"]["verify.py"]
        == "6a967cd2e37a4f03f7d02b80a3e04d387c100a22fa8aed1d1ab000e8bd86c16e"
    )
    expect_failure(lambda: original.host(root), original=True)
    answer = verify.host(root)
    qualified = verify.load(root / "qualified.json")
    tree = verify.load(root / "tree/accepted.json")
    calculations = {}
    for phase, v in qualified.items():
        data = v["resolved"]
        rows = data["examples"]
        order = [row["name"] for row in rows]
        if phase in ("edit", "repeat"):
            assert order == kernel_order(root / "tree" / phase / "trace")
            # This is the original verifier's discrepancy, for both commands on both boots.
            assert order != list(tree[phase]["native"]["examples"]) == sorted(order)
        full, links, wild = (
            sum(r[k] for r in rows) for k in ("rustc_tree", "cc_tree", "wild_tree")
        )
        whole = data["traced_whole"]
        plain = data["untraced_whole"]
        front = full - links
        lo, hi = max(whole, plain), min(whole, plain)
        bounds = answer["bounds"][phase]
        assert [
            bounds[k]
            for k in (
                "whole_traced",
                "whole_untraced",
                "rustc_including_links",
                "cc_including_wild",
                "wild_nested_attribution_only",
                "pure_rustc_upper_instructions",
                "outside_example_rustc",
            )
        ] == [whole, plain, full, links, wild, front, whole - full]
        assert (float(Fraction(lo, lo - front)), float(Fraction(hi, hi - front))) == (
            bounds["ideal_low"],
            bounds["ideal_high"],
        )
        calculations[phase] = {
            **bounds,
            "remaining_overhead_to_reach_2x": float(Fraction(2 * front - lo, 2)),
            "example_order": order,
        }
        if phase in ("edit", "repeat"):
            counts = tree[phase]["native"]
            calculations[phase].update(
                {
                    "separate_library": v["library_excluded"],
                    "native_execs": counts["execs"],
                    "linux_tasks": counts["tasks"],
                    "typed_units": len(tree[phase]["typed"]),
                    "typed_dirty": sum(not fresh for _, _, fresh in tree[phase]["typed"]),
                }
            )
    # A single raw CC instruction or a permutation of the original ordered report must still fail.
    counter = root / "tree/repeat/trace/samples.tsv"
    old = counter.read_bytes()
    lines = [l.split(b"\t") for l in old.splitlines()]
    row = next(r for r in lines if int(r[2]) == 2)
    row[5] = str(int(row[5]) + 1).encode()
    counter.write_bytes(b"\n".join(b"\t".join(r) for r in lines) + b"\n")
    expect_failure(lambda: verify.host(root))
    counter.write_bytes(old)
    report = root / "qualified.json"
    old = report.read_bytes()
    altered = json.loads(old)
    rows = altered["repeat"]["resolved"]["examples"]
    rows[0], rows[1] = rows[1], rows[0]
    report.write_text(json.dumps(altered))
    expect_failure(lambda: verify.host(root))
    report.write_bytes(old)
    assert verify.host(root) == answer
    return {"boot": answer["boot"], "order": e["order"], "commands": calculations}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--originals",
        type=Path,
        help="also compare every member with both separately downloaded official ZIPs",
    )
    cli.add_argument(
        "--scratch", type=Path, help="directory for a small temporary unpacked working tree"
    )
    args = cli.parse_args()
    with tempfile.TemporaryDirectory(dir=args.scratch) as temp:
        base = Path(temp)
        official = unpack(base, args.originals)
        original = original_verifier()
        workers = {p: analyze(base, p, original) for p in ("01", "02")}
        assert len({row["boot"] for row in workers.values()}) == 2
        assert {p: v["boot"] for p, v in workers.items()} == {
            p: v["boot"] for p, v in official.items()
        }
    assert all(v["commands"]["repeat"]["ideal_low"] > 2 for v in workers.values())
    result = {
        "workers": workers,
        "original_workflow_conclusion": "failure",
        "result": "both registered optimistic frontend ceilings admit a 2x design before its actual overhead",
        "mutation_gates": "two original ordering refusals, two modified CC counts and two modified ordered reports rejected; all complete unmodified records replayed",
    }
    assert verify.load(HERE / "result.json") == result
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
