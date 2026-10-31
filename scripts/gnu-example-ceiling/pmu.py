"""Calibrate inclusive hardware scope and keep every original watch and ptrace file."""

import gzip, json, os, shutil, statistics, subprocess, time
from pathlib import Path
import topology
from kit import HERE, sha, save

COUNT = 80_000_000
NESTED = (0, 2_000_000, 0, 8_000_000)


def gz(p, data):
    p.write_bytes(gzip.compress(data, compresslevel=1, mtime=0))


def spawn(argv, cwd, env, timeout=900):
    return subprocess.run(
        list(map(str, argv)), cwd=cwd, env=env, capture_output=True, timeout=timeout
    )


def compilers(store):
    bins = store / "bin"
    bins.mkdir()
    for name, src, pthread in [
        ("tree", "observer.c", False),
        ("plain", "watch.c", False),
        ("loop", "calibrate.c", True),
        ("nested", "nested.c", True),
    ]:
        argv = [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(["-pthread"] if pthread else []),
            HERE / src,
            "-o",
            bins / name,
        ]
        subprocess.run(argv, check=True)
    d = bins / "roles"
    d.mkdir()
    for name in ["root", "outside", *topology.ROLES]:
        shutil.copy2(bins / "nested", d / name)
    assert len({(d / n).stat().st_ino for n in ["root", "outside", *topology.ROLES]}) == 6
    return bins


def calibration(b, output, replay=False):
    d = output / "calibration"
    q = b / "roles"
    if replay:
        selectors = json.loads((d / "selectors.json").read_bytes())
    else:
        d.mkdir()
        selectors = {n: topology.location(q / n) for n in topology.ROLES}
        save(d / "selectors.json", selectors)
    runs = {}
    n = NESTED
    for i, (mode, copies) in enumerate(
        [("0", 1), ("1", 1), ("2", 1), ("2", 2), ("exec", 1), ("thread", 1), ("thread", 2)]
    ):
        sample = []
        for j, count in enumerate([0, COUNT, 0, COUNT]):
            f = d / f"whole-{i}-{j}.json"
            if not replay:
                r = spawn([b / "plain", f, b / "loop", mode, count, copies], d, None)
                assert r.returncode == 0 and not r.stdout and not r.stderr, (
                    f,
                    r.returncode,
                    r.stderr,
                )
            j0 = json.loads(f.read_bytes())
            assert (
                j0["code"] == 0
                and j0["event_errno"] == 0
                and j0["enabled"] == j0["running"] > 0
                and j0["instructions"] > 0
            ), (f, j0)
            sample.append(j0["instructions"])
        expect = 2 * copies * COUNT
        delta = statistics.median(sample[1::2]) - statistics.median(sample[::2])
        assert abs(delta / expect - 1) < 0.02, (mode, delta, expect)
        runs[f"{i}-{mode}"] = [sample, delta, expect]
    nested = {}
    for mode in ("plain", "tree"):
        results = []
        for j, count in enumerate(n):
            p = d / f"nested-{mode}-{j}"
            if not replay:
                p.mkdir()
                cmd = [
                    b / "tree",
                    p,
                    mode,
                    *[q / k for k in topology.ROLES],
                    q / "root",
                    q,
                    "ignore",
                    str(count),
                ]
                proc = spawn(cmd, d, None)
                gz(p / "stdout.gz", proc.stdout)
                gz(p / "stderr.gz", proc.stderr)
                save(p / "call.json", {"argv": list(map(str, cmd)), "returncode": proc.returncode})
                assert proc.returncode == 0
            raw = json.loads((p / "call.json").read_bytes())
            assert (
                raw["returncode"] == 0 and raw["argv"][2] == mode and raw["argv"][-1] == str(count)
            )
            assert not gzip.decompress((p / "stdout.gz").read_bytes()) and not gzip.decompress(
                (p / "stderr.gz").read_bytes()
            )
            results.append(
                topology.read(p, selectors, mode, synthetic=True, names=("alpha", "beta"))
            )

        def gates(getter, mult):
            values = [getter(x) for x in results]
            zero = statistics.median(values[::2])
            expected = [2 * mult * n[i] for i in (1, 3)]
            actual = [values[i] - zero for i in (1, 3)]
            assert all(abs(a / e - 1) < 0.02 for a, e in zip(actual, expected)), (
                mode,
                mult,
                values,
                actual,
                expected,
            )
            return {"values": values, "delta": actual, "ideal": expected}

        scalars = {"whole": gates(lambda x: x["whole"], 88)}
        if mode == "tree":
            for name, factor in [("alpha", 1), ("beta", 2)]:
                for role, mult in [("rustc_tree", 27), ("cc_tree", 26), ("wild_tree", 21)]:
                    scalars[name + "/" + role] = gates(
                        lambda v: v["examples"][name][role], mult * factor
                    )
                scalars[name + "/rustc-minus-cc"] = gates(
                    lambda v: v["examples"][name]["rustc_tree"] - v["examples"][name]["cc_tree"],
                    factor,
                )
                scalars[name + "/cc-minus-wild"] = gates(
                    lambda v: v["examples"][name]["cc_tree"] - v["examples"][name]["wild_tree"],
                    5 * factor,
                )
            scalars["outside"] = gates(
                lambda v: v["whole"] - sum(z["rustc_tree"] for z in v["examples"].values()), 7
            )
        nested[mode] = scalars
    for i in [1, 3]:
        traced, plain = [nested[m]["whole"]["values"][i] for m in ("tree", "plain")]
        assert abs(traced - plain) / min(traced, plain) < 0.02, (traced, plain)
    result = {
        "whole28": runs,
        "nested": nested,
        "bins": {n: sha(b / n) for n in ("plain", "tree", "nested", "loop")},
    }
    if replay:
        assert json.loads((d / "admitted.json").read_bytes()) == result
    else:
        save(d / "admitted.json", result)
    return result


def record(folder, b, mode, paths, cmd, src, env):
    folder.mkdir()
    trace = folder / "trace"
    trace.mkdir()
    args = [b / "tree", trace, mode, *[paths[n] for n in topology.ROLES], *cmd]
    p = spawn(args, src, env)
    # Only observer-side files are written. The caller starts the next measured
    # command before inspecting any caches, products, programs or even its JSON.
    gz(folder / "stdout.gz", p.stdout)
    gz(folder / "stderr.gz", p.stderr)
    save(
        folder / "invocation.json",
        {"argv": cmd, "native": list(map(str, args)), "status": p.returncode},
    )
    assert p.returncode == 0, (folder, p.returncode, p.stderr[-1000:])
    return p.stdout
