#!/usr/bin/python3 -ISB
"""Record the real Cargo invocation and vary only the selected off-clock compiler's worker count."""

from pathlib import Path
import hashlib
import json
import os
import sys

a = sys.argv[1:]
forms = json.loads(Path(os.environ["OHM_22958_FORMS"]).read_bytes())
owner = os.environ["OHM_22958_OWNER"]
assert a[0] == os.environ["RUSTC"]
if "--crate-name" not in a or (
    a[1:4] == ["-", "--crate-name", "___"]
    and "--print=sysroot" in a
    and not any(v.startswith("--emit") for v in a)
):
    os.execv(a[0], a)
name = a[a.index("--crate-name") + 1]
assert name in forms and sum(v.startswith("--emit") for v in a) == 1
norm = lambda x: [v for v in x if not v.startswith("-Zthreads=")]
assert any(norm(x) == norm(a) for x in forms[name]), (name, a)
args = a
inputs = {}
if name == owner:
    threads = os.environ["OHM_22958_THREADS"]
    assert threads in ("1", "8") and all(
        v in ("-Zthreads=1", "-Zthreads=8") for v in a if v.startswith("-Zthreads=")
    )
    args = a + ["-Zthreads=" + threads]
    for i, v in enumerate(a):
        if v == "--extern" and "=" in a[i + 1]:
            f = Path(a[i + 1].split("=", 1)[1])
            assert f.is_absolute()
            with f.open("rb") as data:
                inputs[str(f)] = [
                    f.stat().st_size,
                    hashlib.file_digest(data, "sha256").hexdigest(),
                ]
out = Path(os.environ["OHM_22958_LOGS"]) / (name + "-" + str(os.getpid()) + ".json")
with out.open("x") as f:
    json.dump(
        dict(
            name=name,
            original=a,
            executed=args,
            inputs=inputs,
            pid=os.getpid(),
            cwd=os.getcwd(),
        ),
        f,
    )
os.execv(args[0], args)
