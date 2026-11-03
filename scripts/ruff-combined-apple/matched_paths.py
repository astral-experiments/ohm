"""Run the pinned verdict fixture with clean and repaired outputs at one absolute path."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp

import smoke


def native(work, env, mode, label):
    row = smoke.run(work, env, mode, "", label, 0)
    if "elf" not in row:
        return row
    logs = Path(env["OHM_CASE_LOGS"])
    messages = (logs / f"{work.name}-{label}.stdout").read_bytes().splitlines()
    artifact, = [a for a in map(json.loads, messages)
                 if a.get("target", {}).get("name") == smoke.TARGET and a.get("executable")]
    executable = Path(artifact["executable"])
    data = executable.read_bytes()
    magic = bytes.fromhex("cffaedfe") if os.uname().sysname=="Darwin" else b"\x7fELF"
    assert data[:4] == magic and hashlib.sha256(data).hexdigest() == row["elf"]
    dest = logs / (row["elf"] + (".macho.gz" if os.uname().sysname=="Darwin" else ".elf.gz"))
    if not dest.exists():
        dest.write_bytes(gzip.compress(data, compresslevel=4, mtime=0))
    row["executable"] = str(executable)
    return row


def repair(work, env, mode):
    (work / "src/payload.bin").write_bytes(smoke.OLD)
    repaired = native(work, env, mode, "repair")
    warm, clean = (work / name for name in ("parked-warm", "parked-clean"))
    warm.mkdir()
    clean.mkdir()
    paths = [work / name for name in ("target", "build", "cargo-home")]
    for path in paths:
        if path.exists():
            assert path.is_dir() and not path.is_symlink()
            path.rename(warm / path.name)
    try:
        assert all(not p.exists() for p in paths)
        independent = native(work, env, mode, "repair-clean")
    finally:
        for path in paths:
            if path.exists():
                path.rename(clean / path.name)
            previous = warm / path.name
            if previous.exists():
                previous.rename(path)
    fresh = native(work, env, mode, "repair-unchanged")
    assert independent["fresh"] == [False] and fresh["fresh"] == [True]
    rows = [repaired, independent, fresh]
    assert len({r.get("output") for r in rows}) == 1
    assert len({r.get("executable") for r in rows}) == 1
    assert repaired.get("elf") == fresh.get("elf")
    return rows


def histories(root, normal, fixed, base):
    logs = root / "logs"
    proxy = Path(shutil.which("rustup", path=base["PATH"])).resolve(strict=True)
    proxies = root / "proxies"
    proxies.mkdir()
    for name in ("rustup", "cargo", "rustc", "rustdoc"):
        (proxies / name).symlink_to(proxy)
    alias = Path(base["RUSTUP_HOME"]) / "toolchains/ohm"
    alias.parent.mkdir(parents=True)
    rows, repairs, controls = [], [], []
    for role, sdk in (("P", normal), ("C", fixed)):
        if alias.is_symlink():
            alias.unlink()
        alias.symlink_to(sdk, target_is_directory=True)
        env = dict(base, PATH=str(proxies) + os.pathsep + base["PATH"], RUSTC=str(sdk / "bin/rustc"),
                   RUSTUP_TOOLCHAIN="ohm", LD_LIBRARY_PATH=str(sdk / "lib"), OHM_CASE_LOGS=str(logs))
        for name in ("rustc", "cargo", "rustdoc"):
            path = sp.check_output(["rustup", "which", "--toolchain", "ohm", name], env=env, text=True).strip()
            assert Path(path).samefile(sdk / "bin" / name)
        rows += smoke.mixed_alias(root / (role + "-mixed-alias"), env, role == "C")
        for mode in ("check", "build", "test"):
            work = root / (role + "-" + mode)
            rows += smoke.history(work, env, mode, role == "C")
            if role == "C":
                for case in (work, root / ("P-" + mode)):
                    if case != work:
                        rows += [smoke.run(case, env, mode, "", "upgrade", 101)]
                    trio = repair(case, env, mode)
                    repairs.append([row.get("elf") for row in trio])
                    rows += trio
            smoke.save(logs / f"{role}-{mode}-histories.json", rows)
        for mode in ("build", "test"):
            case = root / (role + "-valid-control-" + mode)
            smoke.seed(case)
            (case / "armed").unlink()
            first = native(case, env, mode, "valid-seed")
            trio = repair(case, env, mode)
            assert first["fresh"] == [False]
            controls.append(dict(role=role, mode=mode, rows=[first, *trio]))
    assert len(rows) == 45 and len(controls) == 4 and len(repairs) == 6
    smoke.save(logs / "smoke.json", {"ordinary_cargo_histories": rows, "controls": controls, "repairs": repairs})
    return repairs + [[x["elf"] for x in c["rows"]] for c in controls]
