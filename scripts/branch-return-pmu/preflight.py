"""Exercise the exact phase, counter and syscall readers without collecting candidate observations."""

import argparse
import ast
import collections
import gzip
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bindings as b
import meter
import processes
import worker


def rejects(f, *args):
    try:
        f(*args)
    except (ValueError, AssertionError, RuntimeError, SyntaxError):
        return
    raise AssertionError("accepted a rejected fixture")


def mechanical():
    arm_env = {r: b.environment(r) for r in b.ORDERS["01"]}
    assert arm_env["Foff"] == arm_env["Koff"] and arm_env["Fon"] == arm_env["Kon"]
    assert arm_env["Foff"] | {"CARGO_ENCODED_RUSTFLAGS": "-Zohm-branch-cache=yes"} == arm_env["Fon"]
    absent = {
        "CI",
        "TF_BUILD",
        "RUSTFLAGS",
        "RUSTC",
        "RUSTDOC",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTUP_TOOLCHAIN",
        "LD_PRELOAD",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    }
    assert not any(absent.intersection(e) for e in arm_env.values())
    assert b.ORDERS["02"] == b.ORDERS["01"][::-1] and [k for k, _ in worker.PHASES] == [
        "cold-A",
        "first-B",
        "return-A",
        "return-B",
        "unchanged-B",
        "invalid",
        "repair",
    ]
    assert b.sha(HERE / "PLAN.md") == b.PLAN
    assert (
        b.sha(HERE / "object_equality.py")
        == "ea6526bd3466552797cd0e003ec0c831a78c4fb560d483c72b42e8d55a36685d"
    )
    for f in sorted(HERE.glob("*.py")):
        ast.parse(f.read_bytes(), filename=str(f))
    text = '7 execve("/tool", ["/tool", "x"], 0xffff /* 2 vars */) = 0\n'
    split = [
        '7 execve("/tool", ["/tool", "x"], 0xffff /* 2 vars */ <unfinished ...>\n',
        "7 <... execve resumed>) = 0\n",
    ]
    want = [(7, "/tool", ["/tool", "x"])]
    assert processes.execs([text]) == processes.execs(split) == want
    assert not processes.execs([text.replace("= 0", "= -1 ENOENT (No such file or directory)")])
    bad = [
        split[:1],
        split[1:],
        [text.replace('"x"', "...")],
        [text.replace("execve(", "execveat(")],
        [text.replace("= 0", "= ?")],
        split[:1] + [text],
    ]
    for rows in bad:
        rejects(processes.execs, rows)
    example = {
        "event_errno": 0,
        "user_us": 3,
        "system_us": 2,
        "instructions": 9000,
        "enabled": 1000,
        "running": 995,
        "start": 24,
        "stop": 48,
        "code": 101,
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clock.json"
        path.write_text(json.dumps(example))
        assert meter.clock(path, 101)["instructions"] == 9000
        for edits, wanted in [
            ({"event_errno": 1}, 101),
            ({"running": 994}, 101),
            ({"running": 1001}, 101),
            ({"instructions": 0}, 101),
            ({}, 0),
            ({"running": True}, 101),
        ]:
            path.write_text(json.dumps(example | edits))
            rejects(meter.clock, path, wanted)
        # Renaming native directories must leave contained file device, inode, mtime and ctime intact.
        root = Path(tmp) / "role"
        root.mkdir()
        sdk = root / "sdk"
        saved = {}
        for role in ("F", "K"):
            (root / role).mkdir()
            p = root / role / "driver"
            p.write_text(role)
            saved[role] = b.numbers(p)
        current = None
        for arm in b.ORDERS["01"] + b.ORDERS["02"]:
            role = arm[0]
            if current != role:
                if current is not None:
                    sdk.rename(root / current)
                (root / role).rename(sdk)
                current = role
            assert (sdk / "driver").read_text() == role and b.numbers(sdk / "driver") == saved[role]
    return {
        "arms": list(b.ORDERS["01"]),
        "phases": len(worker.PHASES),
        "trace_rejections": len(bad),
        "clock_rejections": 6,
        "schedule_fixture_activations": 8,
        "candidate_samples": 0,
    }


def old_archive(path, kind):
    specs = {
        "screen": ("51fb156eb4c1b57f2c3f9ec5ee456eaecd6762a28fa518c356c1d223f45ebad4", 12984940261),
        "confirm": (
            "e9fcdd65d0244f5a03f115a3b1640a1c79386b06722b082959f87ec0f8c47518",
            12987886884,
        ),
    }
    h, ident = specs[kind]
    assert b.sha(path) == h
    totals = collections.Counter()
    return_shapes = {}
    with zipfile.ZipFile(path) as z:
        traces = [p for p in z.namelist() if p.endswith("/exec.raw.gz")]
        for name in sorted(traces):
            raw = z.read(name)
            events = processes.execs(io.StringIO(gzip.decompress(raw).decode()))
            captured = {(pid, tuple(argv)) for pid, _, argv in events}
            prefix = name.removesuffix("exec.raw.gz")
            gold = json.loads(gzip.decompress(z.read(prefix + "native-execs.json.gz")))
            assert all((r["pid"], tuple(r["argv"])) in captured for r in gold["rustcs"])
            wild = [
                argv
                for _, exe, argv in events
                if "wild-ld/" in exe and Path(exe).name in ("ld.bfd", "ld")
            ]
            assert len(wild) == gold["wild"]
            nonwild = [
                processes.other_link(exe, argv)
                for _, exe, argv in events
                if Path(exe).name
                in ("ld", "ld.bfd", "ld.lld", "ld.gold", "wild", "rust-lld", "mold")
                and "wild-ld/" not in exe
            ]
            totals["full_C_configure_link"] += sum(k != "query" for k, _ in nonwild)
            totals["default_aout"] += sum(v == "a.out" for _, v in nonwild)
            totals.update(
                traces=1,
                successful_execs=len(events),
                verified_rustc=len(gold["rustcs"]),
                verified_wild=len(wild),
            )
        for name in sorted(
            n for n in z.namelist() if n.endswith("/cargo.stdout.gz") and "triplet-" in n
        ):
            chunks = [json.loads(v) for v in gzip.decompress(z.read(name)).splitlines()]
            phase = name.rsplit("/", 2)[-2]
            if phase == "invalid":
                assert chunks[-1] == {"reason": "build-finished", "success": False} and any(
                    c.get("message", {}).get("code")
                    and c["message"]["code"]["code"] == "E0308"
                    and c["target"]["name"] == "ruff_python_parser"
                    for c in chunks
                )
                totals["verified_invalid"] += 1
                continue
            assert chunks[-1] == {"reason": "build-finished", "success": True}
            units = [r for r in chunks if r["reason"] == "compiler-artifact"]
            assert len(units) == 375
            relative = next(
                m["target"]["src_path"].split("/crates/")[0]
                for m in units
                if m["package_id"].startswith("path+")
            )
            both = worker.historical.roster(chunks, Path(relative))
            prior = json.loads(
                gzip.decompress(z.read(name.replace("cargo.stdout.gz", "roster.json.gz")))
            )
            assert list(both) == [prior["members"], prior["dirty"]]
            totals["verified_375_rows"] += 1
            return_shapes.setdefault(phase, set()).add(len(both[1]))
    assert totals["traces"] == {"screen": 21, "confirm": 54}[kind]
    return dict(
        archive=ident,
        sha256=h,
        counts=totals,
        historical_dirty={k: sorted(v) for k, v in return_shapes.items()},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", type=Path)
    args = parser.parse_args()
    results = {"syntax_and_controls": mechanical()}
    if args.historical:
        for kind in ("screen", "confirm"):
            results[kind] = old_archive(args.historical / (kind + ".zip"), kind)
    print(json.dumps(results, sort_keys=True, indent=2))
