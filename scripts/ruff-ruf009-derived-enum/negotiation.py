"""Read option negotiations and checked rustcs from the kernel's own exec records."""
import gzip
import json
from pathlib import Path
import re

FLAG = "-Zohm-checked-private-derives-v2"


def read(directory, driver, role, root=None):
    decoder = json.JSONDecoder()
    probes, compiled = [], []
    sdk = Path(driver).parents[1]
    root = sdk.parent if root is None else root
    aliases = {sdk / "bin/rustc", root / "rustup/toolchains/ohm/bin/rustc"}
    proxy = root / "proxies/rustc"
    for trace in directory.glob("trace.*.gz"):
        pid = int(trace.name.split(".")[1])
        records = gzip.decompress(trace.read_bytes()).decode().splitlines()
        mapped = any(line.startswith("mmap(") and "PROT_EXEC" in line and "<" + str(driver) + ">" in line
                     and re.search(r" = 0x[0-9a-f]+$", line.rstrip()) for line in records)
        if not mapped:
            continue
        forwarded = []
        for line in records:
            if not line.startswith("execve(") or not line.endswith(" = 0"):
                continue
            program, n = decoder.raw_decode(line[7:])
            if Path(program).name != "rustc":
                continue
            argv, _ = decoder.raw_decode(line[n+7:].lstrip(", "))
            if Path(program) == proxy:
                forwarded.append(argv[1:])
                continue
            assert Path(program) in aliases, ("unregistered rustc image", program, sorted(map(str, aliases)))
            if forwarded:
                assert all(args == argv[1:] for args in forwarded), ("proxy/compiler argv mismatch", pid)
                forwarded.clear()
            if argv[1:] == [FLAG, "--print=sysroot"]:
                probes.append([pid, program])
            if "--crate-name" in argv and "--out-dir" in argv and any(s.startswith("--emit=dep-info,metadata") for s in argv):
                crate = argv[argv.index("--crate-name") + 1]
                kind = argv[argv.index("--crate-type") + 1]
                assert "-Zohm-checked-private-derives" not in argv
                enabled = argv.count(FLAG)
                assert enabled in (0, 1)
                if role == "P" or kind not in ("lib", "rlib"):
                    assert not enabled
                if crate == "ruff_linter" and kind == "lib":
                    assert enabled == int(role == "C")
                    assert "-Zpublic-api-hash" in argv and "-Zohm-shared-stages" in argv
                    assert any("incremental=" in s for s in argv) and any("checksum-hash-algorithm=blake3" in s for s in argv)
                compiled.append([pid, crate, kind, enabled])
        assert not forwarded, ("rustup proxy has no affiliated actual compiler", pid)
    assert probes and len(probes) == len({p[0] for p in probes})
    return {"probes": sorted(probes), "compilers": sorted(compiled)}
