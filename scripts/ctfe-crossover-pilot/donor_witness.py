"""Observe the two existing incremental donors on structural commands only."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gnu-same-revision-donor"))
import donor_open
import donors
import driver_map
import live_driver

OWN = donors.OWN
X = "historical-parent"
Y = "historical-feature"
B = "7b13f01ba1569887a25670820764b24c206da8e5"


def need(ok, why):
    if not ok:
        raise ValueError(why)


def write(path, value):
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as f:
        f.write(gzip.compress(data, mtime=0) if path.suffix == ".gz" else data)


def rows(native):
    return [
        {
            "name": r["crate"],
            "pid": r["pid"],
            "argv": r["argv"],
            "mode": "compile" if r["mode"] == "full" else r["mode"],
        }
        for r in native["rustcs"]
    ]


def register(states, last_full, role, *, refnames=(X, Y)):
    """Enroll only two actual immutable pre-return sessions per observed Rust crate."""
    need(role in ("E", "D") and len(states) == 3, "unknown role or incomplete checkout training")
    first, prior, last = states
    need(
        (first["source"]["ref"], prior["source"]["ref"], last["source"]["ref"])
        == (refnames[1], refnames[0], refnames[0])
        and first["source"]["revision"] == last["source"]["revision"] == B
        and prior["source"]["revision"] == "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13",
        "different checkout or fast-forward",
    )
    recorded = {}
    for owner in OWN:

        def owned(state):
            return {k: v for k, v in state["sessions"].items() if v["owner"] == owner}

        (y,), x_prev, both = owned(first), owned(prior), owned(last)
        need(
            y in x_prev
            and y in both
            and len(x_prev) == len(both) == 2
            and first["sessions"][y] == x_prev[y] == both[y],
            "old Y did not survive",
        )
        (x,) = both.keys() - {y}
        a, b = both[x], both[y]
        need(
            x not in x_prev
            and a["branch"] != b["branch"]
            and a["directory"] != b["directory"]
            and int(a["time"], 36) > int(b["time"], 36)
            and all(v["revision"] == (B[:16] if role == "D" else None) for v in (a, b)),
            "second session is not the newly finalized, same-revision X",
        )
        (producer,) = [r for r in last_full if r["name"] == owner and r["mode"] == "compile"]
        (inc,) = [v.split("=", 1)[1] for v in producer["argv"] if v.startswith("incremental=")]
        need(
            Path(x).parent.parent == Path(inc)
            and Path(x).parent == Path(y).parent
            and "-Zohm-branch-cache=yes" in producer["argv"],
            "other incremental owner",
        )
        for path, row in ((x, a), (y, b)):
            m = donors.PATTERN.fullmatch(Path(path).name)
            need(
                m
                and (m[1], m[2], m[3]) == (row["time"], row["branch"], row["revision"])
                and set(row["tables"]) == set(donors.TABLES),
                "wrong session fields",
            )
            for kind, t in row["tables"].items():
                p = Path(t["path"])
                need(
                    p.parent == Path(path)
                    and p.name in (kind, "ohm-packed-" + kind)
                    and all(
                        type(t[k]) is int and t[k] > 0 for k in ("dev", "ino", "length", "blocks")
                    )
                    and re.fullmatch("[0-9a-f]{64}", t["sha256"]),
                    "wrong original table",
                )
        recorded[owner] = {
            "X": a,
            "Y": b,
            "X_path": x,
            "Y_path": y,
            "X_at_B_rustc": producer["pid"],
        }
    return recorded


def capture(call, where, env, arm, record, registered, *, expected_side=None):
    files = [
        Path(t["path"])
        for s in registered.values()
        for k in ("X", "Y")
        for t in s[k]["tables"].values()
    ]
    sdk = Path(env["LD_LIBRARY_PATH"]).parent
    driver = record["driver"]

    def invoke(folder, code):
        watch = donor_open.Watch(files)
        try:
            result = call(folder, env, code, arm)
        finally:
            write(folder / "donor-opens.json", watch.close())
        return *result[:2], rows(result[2]), result[2]

    msgs, count, comp, physical = live_driver.watch(
        invoke, where, 0, sdk, sdk / driver, write, record["files"][driver]
    )
    raw = json.loads((where / "donor-opens.json").read_bytes())
    write(where / "donor-selected.json", donors.verify_opens(registered, raw, comp, arm[0], expected_side=expected_side))
    return msgs, count, physical


def check_processes(proof, current, driver, files, comp, *, expected_side=None):
    reference = proof["reference"]
    driver_map.check_reference(reference, driver, files)
    need(not proof["refused"] and type(proof["worker_pid"]) is int, "live driver reader refused")
    need(len({x["pid"] for x in comp}) == len(comp), "duplicate installed compiler PIDs")
    for c in comp:
        if c["name"] not in OWN or c["mode"] != "compile":
            continue
        p = proof["actual"][str(c["pid"])]
        need(
            p["pid"] == c["pid"]
            and p["argv"][1:] == c["argv"][1:]
            and p["ancestry"]
            and p["ancestry"][0] == proof["worker_pid"],
            "sample and real compiler disagree",
        )
        driver_map.check_process(
            reference, driver, files, p["mount_namespace"], p["visible"], p["maps"]
        )
    return donors.verify_opens(current[0], current[1], comp, current[2], expected_side=expected_side)


def check_ledger(state, ledger, root):
    """Independently tie every selected donor inode to its quiescent, full two-root disk ledger."""
    paths = {}
    for path, row in state["sessions"].items():
        key = str(Path(path).relative_to(root / "work"))
        need(key in ledger and ledger[key][:2] == row["directory"], "wrong donor directory inode")
        for t in row["tables"].values():
            k = str(Path(t["path"]).relative_to(root / "work"))
            need(
                k in ledger
                and ledger[k][:2] == [t["dev"], t["ino"]]
                and ledger[k][4] * 512 == t["blocks"]
                and ledger[k][5] == t["length"],
                "unbound table in disk census",
            )
            paths[k] = t["sha256"]
    need(len(paths) == 2 * len(state["sessions"]), "non-unique table paths")
    return paths


def refs(repo, expected):
    import subprocess

    out = {}
    for label in (X, Y):
        ref = "refs/heads/" + label
        path = repo / ".git" / ref
        s = path.lstat()
        data = path.read_bytes()
        sha = subprocess.check_output(
            ["git", "--no-optional-locks", "-C", repo, "rev-parse", "--verify", ref], text=True
        ).strip()
        need(
            path.resolve(strict=True) == path
            and s.st_size == 41
            and data == (expected + "\n").encode()
            and sha == expected,
            "donors were not both at the same actual Git revision",
        )
        out[ref] = {
            "revision": sha,
            "sha256": hashlib.sha256(data).hexdigest(),
            "inode": [s.st_dev, s.st_ino],
        }
    return out


def check_refs(original):
    need(
        set(original) == {"refs/heads/" + a for a in (X, Y)},
        "missing physical current checkout tip",
    )
    for v in original.values():
        need(
            v["revision"] == B
            and v["sha256"] == hashlib.sha256((B + "\n").encode()).hexdigest()
            and len(v["inode"]) == 2
            and all(type(i) is int and i > 0 for i in v["inode"]),
            "foreign branch tip",
        )
