"""Keep the full unassigned hardware residual, and reopen the independent second signed cohort by physical task."""

from pathlib import Path
from zipfile import ZipFile
from collections import Counter, defaultdict
import json, gzip, hashlib, sys

root = Path(__file__).resolve().parent
cases = [
    (
        41617756983,
        13223081435,
        "2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677",
        "repeat-observed",
        root.parent / "mdtest-restore-29697-01/13223081435.zip",
    ),
    (
        41627259427,
        13226747746,
        "9c5a3ac75da6e79b13042be19228a37418f46fc356cc40e5f77cddd2147ecf57",
        "actual-link-argv",
        root.parent / "native-input-cost-41627259427/original.zip",
    ),
]
specs = json.loads((root / "roles.json").read_bytes())


def read(reg, path, scope):
    run, artifact, digest = reg
    with path.open("rb") as src:
        assert digest == hashlib.file_digest(src, "sha256").hexdigest()
    with ZipFile(path) as z:

        def raw(name):
            return z.read(scope + "/" + name)

        summary = json.loads(gzip.decompress(raw("owner-census.json.gz")))
        parent = {}
        counters = defaultdict(Counter)
        outer = []
        for line in raw("tasks/epochs.tsv").decode().splitlines():
            tag, *values = line.split()
            if tag == "F":
                dad, caller, child, event = map(int, values)
                assert child not in parent
                parent[child] = dad
            if tag == "C":
                epoch, tg, tid, ins, en, ru = map(int, values)
                assert en == ru and min(ins, en) >= 0
                counters[epoch].update(
                    {"instructions": ins, "enabled": en, "running": ru}
                )
            if tag == "W":
                outer.append(list(map(int, values)))
        assert (
            outer == [summary["outer"]]
            and outer[0][1] == outer[0][2] > 0
            and outer[0][3] == 0
        )
        original_outputs = json.loads(gzip.decompress(raw("inventory.json.gz")))[
            "executables"
        ]
        assert len(original_outputs) == 102
        output_hashes = {}
        for dest, unit in original_outputs.items():
            name = [n for n in specs if dest.endswith(n)]
            if name:
                (key,) = name
                assert specs[key]["owner"] == unit["unit"] and key not in output_hashes
                output_hashes[key] = {
                    "bytes": unit["elf"]["bytes"],
                    "sha256": unit["elf"]["sha256"],
                }
        assert output_hashes.keys() == specs.keys()
        roles = defaultdict(dict)
        for r in summary["roles"]:
            c = counters[r["epoch"]]
            assert [c[n] for n in ("instructions", "enabled", "running")] == r[
                "counter"
            ]
            if r["mode"] != "Wild":
                continue
            args_raw = raw("tasks/" + r["argv"])
            assert hashlib.sha256(args_raw).hexdigest() == r["argv_sha256"]
            f = args_raw.rstrip(b"\0").split(b"\0")
            assert (
                tuple(map(int, f[:3])) == (r["pid"], r["dev"], r["ino"])
                and f[3] == f[4]
            )
            a = f[4:]
            output = a[a.index(b"-o") + 1].decode()
            assert output == r["output"]
            (role,) = [k for k in specs if output.endswith(k)]
            assert r["trigger"] not in roles[role]
            roles[role][r["trigger"]] = (r, a)
        assert roles.keys() == specs.keys()
        per = {}
        for k, images in roles.items():
            (e, a), (f, b) = images["exec"], images["first"]
            assert (
                len(images) == 2
                and a == b
                and parent[f["pid"]] == e["pid"]
                and (f["dev"], f["ino"]) == (e["dev"], e["ino"])
            )
            per[k] = sum(v["counter"][0] for v, _ in images.values())
        total = outer[0][0]
        all_ = sum(v["instructions"] for v in counters.values())
        native = sum(per.values())
        signed_residual = total - all_
        unassigned = max(0, signed_residual)
        ranked = sorted(per.values(), reverse=True)

        def n(bound):
            return next(
                n
                for n in range(len(ranked) + 1)
                if sum(ranked[:n]) + bound >= total / 2
            )

        return {
            "run": run,
            "artifact": artifact,
            "sha256": digest,
            "scope": scope,
            "whole": total,
            "assigned": all_,
            "unassigned": unassigned,
            "outer_minus_all_epochs": signed_residual,
            "wild_assigned": native,
            "half": total / 2,
            "min_top_roles_using_only_assigned_work": n(0),
            "minimum_even_if_all_unassigned_work_were_eligible": n(unassigned),
            "verified_role_costs": per,
            "verified_current_native_output": output_hashes,
        }


args = [Path(a) for a in sys.argv[1:]]
assert len(args) in (0, 2)
out = [
    read((run, artifact, sha), args[i] if args else p, scope)
    for i, (run, artifact, sha, scope, p) in enumerate(cases)
]
print(json.dumps(out, indent=2, sort_keys=True))
