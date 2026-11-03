"""Reopen the actual signed workspace's native outputs before classifying any prospective reuse."""

import collections, gzip, hashlib, json
from pathlib import Path
from zipfile import ZipFile

D = Path(__file__).resolve().parent.parent
import sys

archive = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else D / "mdtest-restore-29697-01/13223081435.zip"
)
with archive.open("rb") as src:
    archive_sha = hashlib.file_digest(src, "sha256").hexdigest()
assert archive_sha == "2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677"
z = ZipFile(archive)


def get(n):
    return json.loads(gzip.decompress(z.read(n)))


stages = [
    "ordinary-old",
    "ordinary-edit",
    "first-unchanged",
    "repeat-unchanged",
    "repeat-observed",
    "independent-NEW",
    "repair",
]
inventory = {s: get(s + "/inventory.json.gz")["executables"] for s in stages}
assert all(
    len(i) == 102 and i.keys() == inventory[stages[0]].keys()
    for i in inventory.values()
)
observed = get("repeat-observed/owner-census.json.gz")
roles = [r for r in observed["roles"] if r["mode"] == "Wild" and r["trigger"] == "exec"]
assert (
    len(roles) == 50
    and len({r["epoch"] for r in roles}) == len({r["output"] for r in roles}) == 50
)
rows = {}
for r in roles:
    raw = z.read("repeat-observed/tasks/" + r["argv"])
    assert hashlib.sha256(raw).hexdigest() == r["argv_sha256"] and raw.endswith(b"\0")
    fields = raw.decode().rstrip("\0").split("\0")
    assert (
        tuple(map(int, fields[:3])) == (r["pid"], r["dev"], r["ino"])
        and fields[3] == r["path"]
    )
    args = fields[4:]
    assert args[0] == r["path"]
    assert args.count("-o") == 1 and args[args.index("-o") + 1] == r["output"]
    output = "target/" + r["output"].split("/target/", 1)[1]
    files = {s: i[output]["elf"] for s, i in inventory.items()}
    unit = inventory["repeat-observed"][output]["unit"]
    assert all(i[output]["unit"] == unit for i in inventory.values())
    sha = {s: e["sha256"] for s, e in files.items()}
    size = {s: e["bytes"] for s, e in files.items()}
    assert all(len(h) == 64 for h in sha.values()) and all(n > 0 for n in size.values())
    rows[output] = {
        "owner": unit,
        "exec_epoch": r["epoch"],
        "owner_epoch": r["owning_rustc_epoch"],
        "argv_sha256": r["argv_sha256"],
        "argc": len(args),
        "searches": [a for a in args if a.startswith("-l") and len(a) > 2],
        "native_path_count": sum(a.startswith("/") and a != r["output"] for a in args),
        "symbols_o": [a for a in args if a.endswith("/symbols.o")],
        "bytes": size,
        "sha256": sha,
    }


def changed(*stages):
    return sorted(
        out for out, v in rows.items() if len({v["sha256"][s] for s in stages}) != 1
    )


comparisons = {
    "genuine_old_to_edit": ("ordinary-old", "ordinary-edit"),
    "ordinary_edit_to_first_unchanged": ("ordinary-edit", "first-unchanged"),
    "ordinary_first_to_second_unchanged": ("first-unchanged", "repeat-unchanged"),
    "ordinary_second_to_traced_unchanged": ("repeat-unchanged", "repeat-observed"),
    "ordinary_edit_to_independent_clean": ("ordinary-edit", "independent-NEW"),
    "warm_everything_through_independent_clean": tuple(stages[1:6]),
    "entire_old_through_independent_clean": tuple(stages[:6]),
    "repaired_to_independent_clean": ("repair", "independent-NEW"),
}
differences = {n: changed(*s) for n, s in comparisons.items()}
regular = collections.Counter(tuple(v["searches"]) for v in rows.values())
result = {
    "run": 41617756983,
    "artifact": 13223081435,
    "zip_sha256": archive_sha,
    "history": stages,
    "n_native_real_exec": len(roles),
    "all_execs": observed["real_execs"],
    "unit_roster": dict(
        collections.Counter(tuple(v["owner"][2])[0] for v in rows.values())
    ),
    "outputs_bytes_repeat": sum(r["bytes"]["repeat-unchanged"] for r in rows.values()),
    "unknown_complete_resolution_groups_outside_e2e": 49,
    "literal_search_patterns": [
        {"requested": list(s), "n": n} for s, n in sorted(regular.items())
    ],
    "comparisons": {
        k: {"equal": 50 - len(v), "different": v} for k, v in differences.items()
    },
    "preselected_full_signed_rows": rows,
}
print(json.dumps(result, indent=2, sort_keys=True))
