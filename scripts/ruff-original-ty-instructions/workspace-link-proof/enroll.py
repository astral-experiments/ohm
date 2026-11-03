"""Freeze the 50 historical normal driver argument grammars and role-indexed admissions."""

from collections import Counter
from pathlib import Path
from zipfile import ZipFile
import json, gzip, hashlib, re

here = Path(__file__).resolve().parent
d = here.parent
import sys

z = ZipFile(
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else d / "mdtest-restore-29697-01/13223081435.zip"
)
rows = json.loads((here / "stable-products.json").read_bytes())[
    "preselected_full_signed_rows"
]
roles = [
    r
    for r in json.loads(
        gzip.decompress(z.read("repeat-observed/owner-census.json.gz"))
    )["roles"]
    if r["trigger"] == "exec" and r["mode"] == "Wild"
]
reg = {}
for r in roles:
    raw = z.read("repeat-observed/tasks/" + r["argv"])
    assert hashlib.sha256(raw).hexdigest() == r["argv_sha256"]
    a = raw.decode().split("\0")[4:-1]
    destination = a[a.index("-o") + 1].split("/target/", 1)[1]
    assert r["output"].endswith("/" + destination)
    row = rows["target/" + destination]
    suffix = "/" + "/".join(Path(destination).parts[-4:])
    assert suffix not in reg
    (sym,) = [i for i, v in enumerate(a) if v.endswith("/symbols.o")]
    assert (
        a.index("-o") == 18
        and a[:1][0] == r["path"]
        and a[23] == "-L" + str(Path(a[sym]).parent / "raw-dylibs")
    )
    tmpl = []
    positions = []
    for i, v in enumerate(a):
        if i == 0:
            t = "<static-gnu-wild>"
        elif i == 4:
            assert re.fullmatch(r"-plugin-opt=-fresolution=/tmp/cc[A-Za-z0-9]+\.res", v)
            t = "<unused-gcc-lto-resolution>"
        elif i == 19:
            t = "<registered-output>"
        elif 23 <= i < sym:
            assert v.startswith("-L/")
            t = "<library-search-dir>"
        elif v.startswith("/"):
            if v in (
                "/usr/libexec/gcc/x86_64-linux-gnu/13/liblto_plugin.so",
                "/lib64/ld-linux-x86-64.so.2",
            ):
                t = v
            else:
                assert v.endswith((".o", ".rlib", ".a"))
                positions.append(i)
                t = "<input:" + Path(v).suffix + ">"
        else:
            t = v
        tmpl.append(t)
    assert len(positions) > 20 and len(row["searches"]) == 7
    reg[suffix] = {
        "argc": len(a),
        "symbols_position": sym,
        "regular_positions": positions,
        "direct_requests": len(positions) + 7,
        "grammar": tmpl,
        "argv_input_sha256": r["argv_sha256"],
        "owner": row["owner"],
        "expected_source_shas": row["sha256"],
    }
assert len(reg) == 50
print(json.dumps(reg, sort_keys=True, separators=(",", ":")))
