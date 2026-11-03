"""Freeze signed -24's actual typed role and argument shape from two separate ordinary boots."""

import gzip, hashlib, json, re, sys
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
P = HERE.parent / "workspace-link-proof"
sys.path.insert(0, str(P))
import bound_roster

ORIGINALS = {
    "PC": [
        "13273018586",
        "fb07d80e6d2e86c347209919fd9d83f87e1205c300dd45df5e2f77f90bc834ec",
    ],
    "CP": [
        "13273477987",
        "101251c3625c0e45466f643eecbae6952c1502e2271b2f0e270fb924bae1152c",
    ],
}


def shape(args, role, old):
    assert (
        args[18] == "-o"
        and args[19].endswith(role)
        and args[0].endswith("/wild-ld/ld.bfd")
    )
    (sym,) = [i for i, s in enumerate(args) if s.endswith("/symbols.o")]
    assert args[23] == "-L" + str(Path(args[sym]).parent / "raw-dylibs")
    libopts = [s for s in args if s.startswith("-l")]
    assert (
        libopts == [s for s in old["grammar"] if s.startswith("-l")]
        and len(libopts) == 7
    )
    shape = []
    positions = []
    for i, value in enumerate(args):
        if i == 0:
            field = "<static-gnu-wild>"
        elif i == 4:
            assert re.fullmatch(
                r"-plugin-opt=-fresolution=/tmp/cc[A-Za-z0-9]+\.res", value
            )
            field = "<unused-gcc-lto-resolution>"
        elif i == 19:
            field = "<registered-output>"
        elif 23 <= i < sym:
            assert value.startswith("-L/")
            field = "<library-search-dir>"
        elif value.startswith("/") and value not in (
            "/usr/libexec/gcc/x86_64-linux-gnu/13/liblto_plugin.so",
            "/lib64/ld-linux-x86-64.so.2",
        ):
            assert value.endswith((".o", ".rlib", ".a"))
            positions.append(i)
            field = "<input:" + Path(value).suffix + ">"
        else:
            field = value
        shape.append(field)
    record = {
        "argc": len(args),
        "direct_requests": len(positions) + 7,
        "symbols_position": sym,
        "regular_positions": positions,
        "owner": old["owner"],
        "grammar": shape,
    }
    assert bound_roster.grammar(args, {**record, "suffix": role})
    return record


def main(base):
    old = json.loads((P / "roles.json").read_bytes())
    rows = {}
    proof = {}
    for tag, (aid, digest) in ORIGINALS.items():
        file = base / (tag + ".zip")
        with file.open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == digest
        with ZipFile(file) as z:
            read = lambda n: json.loads(
                gzip.decompress(z.read("ordinary-repeat/" + n + ".json.gz"))
            )
            inv, execs = read("inventory"), read("owner-census")
            physical = [
                r
                for r in execs["roles"]
                if r["mode"] == "Wild" and r["trigger"] == "exec"
            ]
            assert len(physical) == 50 and len(inv["units"]) == 623
            current = {}
            for r in physical:
                (role,) = [k for k in old if r["output"].endswith(k)]
                assert role not in current
                (loc,) = [p for p in inv["executables"] if p.endswith(role)]
                assert inv["executables"][loc]["unit"] == old[role]["owner"]
                record = z.read("ordinary-repeat/tasks/" + r["argv"])
                assert hashlib.sha256(record).hexdigest() == r["argv_sha256"]
                args = record.decode().split("\0")[4:-1]
                template = shape(args, role, old[role])
                variants = rows.setdefault(role, [])
                if template not in variants:
                    variants.append(template)
                current[role] = {
                    "physical_argv_sha256": r["argv_sha256"],
                    "argc": len(args),
                    "variant": variants.index(template),
                }
            assert len(current) == 50
            proof[tag] = {
                "artifact": aid,
                "zip_sha256": digest,
                "real_exec": execs["real_execs"],
                "typed_units": len(inv["units"]),
                "Ruff": inv["state"],
                "signed_shapes": current,
            }
    complete = {k: len(v) for k, v in rows.items()}
    assert len(rows) == 50
    return {
        "schema": 1,
        "signed_run": 41722651807,
        "originals": proof,
        "variants": rows,
        "distinct_shapes": complete,
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), sort_keys=True, separators=(",", ":")))
