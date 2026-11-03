"""Count the registered signed native process and its fork-inherited worker without double counting."""

from pathlib import Path
from zipfile import ZipFile
import gzip, hashlib, json, collections

root = Path(__file__).resolve().parent
original = json.loads((root / "stable-products.json").read_bytes())
import sys

z = ZipFile(
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else root.parent / "mdtest-restore-29697-01/13223081435.zip"
)
scope = "repeat-observed"
rd = lambda n: z.read(scope + "/" + n)
summary = json.loads(gzip.decompress(rd("owner-census.json.gz")))
parents = {}
counter = collections.defaultdict(lambda: [0, 0, 0])
outer = []
for line in rd("tasks/epochs.tsv").decode().splitlines():
    tag, *data = line.split()
    if tag == "F":
        parent, caller, child, ev = map(int, data)
        assert child not in parents
        parents[child] = parent
    if tag == "C":
        epoch, group, tid, value, en, run = map(int, data)
        assert en == run and min(value, en) >= 0
        for i, x in enumerate((value, en, run)):
            counter[epoch][i] += x
    if tag == "W":
        outer.append(list(map(int, data)))
assert (
    outer == [summary["outer"]] and outer[0][1] == outer[0][2] > 0 and outer[0][3] == 0
)
by_output = collections.defaultdict(dict)
for r in summary["roles"]:
    if r["mode"] != "Wild":
        continue
    raw = rd("tasks/" + r["argv"])
    assert hashlib.sha256(raw).hexdigest() == r["argv_sha256"]
    fields = raw.split(b"\0")
    assert list(map(int, fields[:3])) == [r["pid"], r["dev"], r["ino"]]
    args = fields[4:-1]
    assert (
        fields[3] == args[0]
        and bytes(r["output"], "utf8") == args[args.index(b"-o") + 1]
    )
    assert r["counter"] == counter[r["epoch"]]
    path = "target/" + r["output"].split("/target/", 1)[1]
    assert (
        path in original["preselected_full_signed_rows"]
        and r["trigger"] not in by_output[path]
    )
    by_output[path][r["trigger"]] = (r, args)
costs = {}
for dest, v in by_output.items():
    assert set(v) == {"exec", "first"}
    (ex, a), (child, b) = v["exec"], v["first"]
    assert (
        a == b
        and parents[child["pid"]] == ex["pid"]
        and (ex["dev"], ex["ino"]) == (child["dev"], child["ino"])
    )
    costs[dest] = {
        "wild_exec_epoch": ex["epoch"],
        "fork_inherited_epoch": child["epoch"],
        "owner_rustc_epoch": ex["owning_rustc_epoch"],
        "counts": {k: v[k][0]["counter"] for k in ("exec", "first")},
        "native_instructions": ex["counter"][0] + child["counter"][0],
    }
assert len(costs) == 50
t = outer[0][0]
cost = sum(v["native_instructions"] for v in costs.values())
threshold = next(
    i
    for i in range(1, 51)
    if sum(sorted((v["native_instructions"] for v in costs.values()), reverse=True)[:i])
    >= t / 2
)
print(
    json.dumps(
        {
            "zip_sha256": original["zip_sha256"],
            "role_inventory_sha256": hashlib.sha256(
                (root / "stable-products.json").read_bytes()
            ).hexdigest(),
            "whole_observed": outer[0],
            "native_instructions": cost,
            "observed_native_fraction": cost / t,
            "all_native_fraction_requiring_elimination_for_twice": t / 2 / cost,
            "minimum_largest_roles_if_native_became_zero": threshold,
            "all_epoch_instructions": sum(v["counter"][0] for v in summary["roles"]),
            "roles": costs,
        },
        sort_keys=True,
        indent=2,
    )
)
