"""Bind session creation, exact Git revision and kernel-returned donor FD to an installed rustc."""

from pathlib import Path
import re
import stat
from binding import need, sha
from donor_open import OPEN, ACCESS

OWN = ("ruff_python_ast", "ruff_python_edits")
TABLES = ("dep-graph.bin", "query-cache.bin")
PATTERN = re.compile(r"s-([0-9a-z]+)-_([0-9a-f]{16})_(?:r([0-9a-f]{16})_)?([0-9a-z]+)-([0-9a-z]+)")


def snapshot(target, role, *, packed_git=False):
    result = {}
    for p in sorted((target / "debug/incremental").glob("*/*/s-*")):
        if not p.is_dir() or p.is_symlink() or p.name.endswith("-working"):
            continue
        owner = next((k for k in OWN if re.fullmatch(k + r"-[0-9a-z]+", p.parent.name)), None)
        if not owner:
            continue
        m = PATTERN.fullmatch(p.name)
        # D may omit a revision on a packed branch. The packed contact independently
        # binds every allowed tagged or untagged owner to its actual Git checkout.
        if not packed_git:
            need(m and (m[3] is None) == (role == "E"), "unregistered surviving session " + str(p))
        else:
            need(m and role in ("D", "Q") and (role == "D" or m[3] is not None),
                 "unregistered packed-ref session " + str(p))
        s = p.stat()
        row = {
            "directory": [s.st_dev, s.st_ino],
            "owner": owner,
            "branch": m[2],
            "revision": m[3],
            "time": m[1],
            "tables": {},
        }
        for table in TABLES:
            candidates = [p / table, p / ("ohm-packed-" + table)]
            found = [q for q in candidates if q.is_file()]
            need(
                len(found) == 1 and found[0].resolve() == found[0],
                "missing or ambiguous raw/packed pair",
            )
            f = found[0]
            q = f.stat()
            row["tables"][table] = {
                "path": str(f),
                "dev": q.st_dev,
                "ino": q.st_ino,
                "length": q.st_size,
                "blocks": q.st_blocks * 512,
                "sha256": sha(f),
            }
        result[str(p)] = row
    need(
        all(sum(v["owner"] == k for v in result.values()) <= 2 for k in OWN),
        "retained a third generation",
    )
    return result


def enrollment(first, old_x, last, role, rev):
    need(
        last["source"]["head"] == rev and last["source"]["branch"] == "ast-A",
        "not a real X@B build",
    )
    produced = {x["name"]: x for x in last["full"] if x["name"] in OWN}
    registered = {}
    for owner in OWN:
        (y,) = [p for p, v in first["sessions"].items() if v["owner"] == owner]
        now = {p: v for p, v in last["sessions"].items() if v["owner"] == owner}
        need(
            y in now and now[y] == first["sessions"][y] and len(now) == 2, "lost initial physical Y"
        )
        (x,) = set(now) - {y}
        need(
            x not in old_x["sessions"]
            and now[x]["directory"] != now[y]["directory"]
            and now[x]["branch"] != now[y]["branch"]
            and int(now[x]["time"], 36) > int(now[y]["time"], 36)
            and owner in produced,
            "not the newly published later X@B donor",
        )
        if role == "D":
            need(
                now[x]["revision"] == now[y]["revision"] == rev[:16],
                "different actual revision label",
            )
        (inc,) = [
            arg.split("=", 1)[1]
            for arg in produced[owner]["argv"]
            if arg.startswith("incremental=")
        ]
        need(
            Path(x).parent.parent == Path(inc) and Path(x).parent == Path(y).parent,
            "different incremental owner",
        )
        registered[owner] = {
            "X": now[x],
            "Y": now[y],
            "X_path": x,
            "Y_path": y,
            "X_at_B_rustc": produced[owner]["pid"],
        }
    return registered


def verify_opens(registration, observed, compiles, role, *, expected_side=None):
    lookup = {}
    for owner, labels in registration.items():
        for side in ("Y", "X"):
            for kind, f in labels[side]["tables"].items():
                key = (f["dev"], f["ino"])
                need(key not in lookup, "ambiguous donor inode across registered files")
                lookup[key] = (owner, side, kind, f)
    watched = {(r["dev"], r["ino"]): r for r in observed["registered"]}
    need(
        len(watched) == len(observed["registered"])
        and set(watched) == set(lookup)
        and all(
            watched[k] == {i: v for i, v in z[3].items() if i != "blocks"}
            for k, z in lookup.items()
        ),
        "fanotify mark was not the registered file",
    )
    pids = {c["pid"]: c["name"] for c in compiles}
    need(len(pids) == len(compiles), "ambiguous compiler PID within this Cargo command")
    actual = {owner: {} for owner in OWN}
    for event in observed["events"]:
        owner, side, kind, row = lookup[(event["dev"], event["ino"])]
        need(
            pids.get(event["pid"]) == owner and row["length"] == event["length"],
            "open from foreign compiler or file",
        )
        actual[owner].setdefault((side, kind), []).append(event)
    want = expected_side if expected_side is not None else "Y" if role == "E" else "X"
    need(want in ("X", "Y"), "unregistered physical donor side")
    for owner in OWN:
        expected = {(want, t) for t in TABLES} if owner in pids.values() else set()
        need(set(actual[owner]) == expected, "wrong or missing physical donor for " + owner)
        for k, events in actual[owner].items():
            need(
                any(e["mask"] & OPEN for e in events)
                and (
                    any(e["mask"] & ACCESS for e in events)
                    or not Path(registration[owner][k[0]]["tables"][k[1]]["path"]).name.startswith(
                        "ohm-packed"
                    )
                ),
                "no committed kernel opening of chosen file",
            )
    return {
        owner: {"/".join(k): v for k, v in selected.items()} for owner, selected in actual.items()
    }


def allocated(target, build):
    seen = {}
    parts = {}
    for label, path in (("target", target), ("build", build)):
        local = {}
        for p in path.rglob("*"):
            s = p.lstat()
            if stat.S_ISREG(s.st_mode):
                k = (s.st_dev, s.st_ino)
                n = s.st_blocks * 512
                local[k] = n
                need(seen.setdefault(k, n) == n, "file changed during quiescent census")
        parts[label] = sum(local.values())
    return dict(
        regular=parts, unique_allocated=sum(seen.values()), unique_inodes=len(seen), held_sessions=0
    )


def working(target):
    return sorted(
        str(p) for p in (target / "debug/incremental").glob("*/*/s-*-working") if p.is_dir()
    )
