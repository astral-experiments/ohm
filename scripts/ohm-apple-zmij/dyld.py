"""Check which compiler libraries dyld loaded on a real off-clock object emission."""

import os
import re
import subprocess
from pathlib import Path

from study import digest, load, need, physical, save


def check(root, role, sdk, out, paths=None):
    if paths is None:
        paths = load(root / "receipts/pair.json")["differ"]
    drivers = list((sdk / "lib").glob("librustc_driver*.dylib"))
    need(len(drivers) == 1, "unknown driver")
    want = {str(Path(p)) for p in paths} | {str(drivers[0].relative_to(sdk))}
    out.mkdir(parents=True)
    obj = out / "test.o"
    cmd = [
        str(sdk / "bin/rustc"),
        "--crate-name",
        "qa_dyld_owner",
        "--crate-type=lib",
        "--emit=obj",
        "-o",
        str(obj),
        "-",
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DYLD_", "RUSTFLAGS", "RUSTC_"))}
    env["DYLD_PRINT_LIBRARIES"] = "1"
    p = subprocess.run(
        cmd,
        env=env,
        input=b"pub fn answer(n:u32)->u32 { n.wrapping_mul(29) }\n",
        capture_output=True,
        timeout=90,
    )
    need(
        p.returncode == 0 and p.stdout == b"" and obj.read_bytes()[:8] == bytes.fromhex("cffaedfe0c000001"),
        "dyld object emission failed",
    )
    observed = {}
    for raw in p.stderr.decode(errors="replace").splitlines():
        match = re.search(r"(/[^\r\n]*?\.dylib)\s*$", raw)
        if not match:
            continue
        actual = Path(match[1])
        for rel in want:
            if actual.name == Path(rel).name:
                need(actual.samefile(sdk / rel), "foreign loaded compiler library " + actual.name)
                observed[rel] = physical(actual)
    need(
        set(observed) == want, "dyld did not prove actual loaded driver/backend: " + str(want - set(observed))
    )
    save(
        out / "verified.json",
        {"role": role, "object": digest(obj.read_bytes()), "stderr": digest(p.stderr), "loaded": observed},
    )
